"""
Ring Partner API integration endpoints.

Implements the three partner-hosted endpoints required for
one-way (Ring-driven) account linking, per:
https://developer.amazon.com/docs/ring/api-documentation.html#authentication

Uses PASSWORDLESS AUTO-LINKING: since the HMAC nonce already
cryptographically proves the redirect came from Ring for a specific
account_id (and we already have that user's profile from /v1/users/me
at token-exchange time), /account_link completes the link automatically
with no sign-in form -- eliminating the biggest source of drop-off.

  - /token_exchange   -> Token Exchange URL (Ring POSTs the auth code here)
  - /account_link     -> Account Link URL (auto-completes nonce matching)
  - /default_redirect -> Default Redirect URL (generic post-auth routing)

Storage functions (get_unclaimed_ring_users, store_unclaimed_token, etc.)
are stubs -- wire these up to your actual database.
"""

import base64
import hashlib
import hmac
import time
from typing import cast

import flask_dictabase
import requests
from flask import Flask, jsonify, redirect, request, session, flash

import config
from ring_user import RingUser
from slack import send_slack_message

# --- Partner credentials (issued once, in the Ring Developer Portal) ---
CLIENT_ID = config.RING_CLIENT_ID
CLIENT_SECRET = config.RING_CLIENT_SECRET
HMAC_KEY = config.RING_HMAC_SIGNATURE_KEY

OAUTH_TOKEN_URL = "https://oauth.ring.com/oauth/token"
AVA_BASE_URL = "https://api.amazonvision.com"

NONCE_VALIDATION_WINDOW_SECONDS = 600  # 10 minutes


def setup(a: Flask):
    global app
    app = a
    app.db = cast(flask_dictabase.Dictabase, app.db)

    @app.route('/token_exchange', methods=['POST'])
    def token_exchange():
        """
        Ring Backend POSTs an authorization code here after a user confirms
        the integration in the Ring AppStore. The code is single-use and
        expires in 60 seconds for one-way linking, so exchange it immediately.
        """
        authorization_code = request.form.get('code') or (request.json or {}).get('code')
        if not authorization_code:
            return jsonify({"error": "missing 'code'"}), 400

        token_response = requests.post(
            OAUTH_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "code": authorization_code,
                "client_secret": CLIENT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_response.status_code != 200:
            return jsonify({"error": "token exchange failed", "detail": token_response.text}), 502

        tokens = token_response.json()

        # Fetch profile now so /account_link never has to ask the user
        # for anything -- account_id AND email are captured up front.
        profile_response = requests.get(
            f"{AVA_BASE_URL}/v1/users/me",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        if profile_response.status_code != 200:
            return jsonify({"error": "failed to fetch user profile", "detail": profile_response.text}), 502

        attrs = profile_response.json()["data"]["attributes"]
        account_id = profile_response.json()["data"]["id"]

        store_unclaimed_token(
            account_id=account_id,
            email=attrs["email"],
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            expires_at=time.time() + tokens["expires_in"],
        )

        return '', 200

    @app.route('/account_link')
    def account_link():
        """
        Ring redirects the user's browser here with ?nonce=...&time=...
        after they click Confirm in the Ring app. Passwordless auto-linking:
        the nonce match itself is sufficient proof of identity, so we
        complete the link immediately -- no sign-in form, no user input.
        """
        nonce = request.args.get('nonce')
        time_param = request.args.get('time')
        if not nonce or not time_param:
            return "Missing nonce or time parameter", 400

        current_time_ms = int(time.time() * 1000)
        try:
            time_delta_seconds = (current_time_ms - int(time_param)) / 1000
        except ValueError:
            return "Invalid time parameter", 400

        if time_delta_seconds > NONCE_VALIDATION_WINDOW_SECONDS:
            return "Link request expired", 400
        if time_delta_seconds < 0:
            return "Invalid timestamp: cannot be in the future", 400

        ring_user = get_ring_user_from_nonce(nonce, time_param)
        if ring_user is None:
            return "Unable to verify link request", 400

        # Step 1: confirm the link (transitions Ring-side status to 'awaiting')
        post_response = requests.post(
            f"{AVA_BASE_URL}/v1/accounts/me/app-integrations",
            headers={
                "Authorization": f"Bearer {ring_user['access_token']}",
                "Content-Type": "application/json",
            },
            json={
                "account_identifier": mask_email(ring_user['email']),
                "nonce": nonce,
            },
        )
        if post_response.status_code != 200:
            return jsonify({"error": "account link failed", "detail": post_response.text}), 502

        send_slack_message('New User:', ring_user['email'])
        # Step 2: mark integration fully configured/completed
        patch_response = requests.patch(
            f"{AVA_BASE_URL}/v1/accounts/me/app-integrations",
            headers={
                "Authorization": f"Bearer {ring_user['access_token']}",
                "Content-Type": "application/json",
            },
            json={"status": "completed"},
        )

        # save the user account_id to the session cookie so that the dashboard url knows which user is viewing
        session['account_id'] = ring_user['account_id']

        if patch_response.status_code != 200:
            return jsonify({"error": "failed to complete integration", "detail": patch_response.text}), 502

        mark_ring_user_claimed(ring_user)

        return redirect('/default_redirect')

    @app.route('/default_redirect')
    def default_redirect():
        """
        Single entry point for post-linking / cross-platform routing.
        Route the user wherever makes sense once account linking is done
        (e.g. your app's dashboard, or a mobile deep link if on mobile web).
        """
        return redirect('/dashboard')

    @app.route('/magic_link/<uid>')
    def magic_link(uid):
        send_slack_message('incoming magic link=' + uid)
        now_timestamp = time.time()

        login_url = f'{config.SERVER_HOST_URL}magic_link/{uid}'

        ring_user: RingUser = app.db.FindOne(
            RingUser,
            login_url=login_url
        )

        if not ring_user:
            send_slack_message('no ring user found')
            all_users = app.db.FindAll(RingUser)
            send_slack_message([u.get('login_url', None) for u in all_users])
            send_slack_message('login_url=', login_url)

        print('ring_user=', ring_user)

        if not ring_user:
            send_slack_message('ring user=', str(ring_user))
            send_slack_message('magic link user not found', uid)
            flash('User Not Found', 'danger')
            return redirect('/dashboard')

        elif ring_user['login_url_expires_at'] > now_timestamp:
            # success, log this user in
            send_slack_message('user found and magic link NOT expired', uid)
            session['account_id'] = ring_user['account_id']
            return redirect('/dashboard')

        else:
            # the timestamp may have been expired
            # route them to the dashboard to initiate a new magic link
            send_slack_message(
                'user found but link probably expired',
                ring_user.get('login_url_expires_at', None),
                uid)
            flash('Magic Link Expired', 'danger')
            return redirect('/dashboard')


# --- Helpers -----------------------------------------------------------

def compute_nonce(time_param, account_id, hmac_key=HMAC_KEY):
    """Recompute the nonce Ring generated, to match against unclaimed tokens."""
    payload = f"{time_param}:{account_id}"
    mac = hmac.new(hmac_key.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).rstrip(b'=').decode('utf-8')


def get_ring_user_from_nonce(received_nonce, time_param):
    for ring_user in get_unclaimed_ring_users():
        computed_nonce = compute_nonce(time_param, ring_user['account_id'])
        if hmac.compare_digest(computed_nonce, received_nonce):
            return ring_user
    return None


def mask_email(email):
    local, domain = email.split('@')
    masked = local[0] + '***' + (local[-1] if len(local) > 2 else '')
    return f"{masked}@{domain}"


# --- Storage stubs -- replace with your actual persistence layer -------

def store_unclaimed_token(account_id: str, email: str, access_token: str, refresh_token: str, expires_at: int):
    app.db = cast(flask_dictabase.Dictabase, app.db)
    with app.app_context():
        app.db.New(
            RingUser,
            account_id=account_id,
            email=email,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            status='unclaimed',
        )


def get_unclaimed_ring_users():
    app.db = cast(flask_dictabase.Dictabase, app.db)
    return app.db.FindAll(RingUser, status='unclaimed')


def mark_ring_user_claimed(ring_user: RingUser):
    ring_user['status'] = 'claimed'
