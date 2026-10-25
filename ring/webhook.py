import hashlib
import hmac
from typing import cast

from flask import request, jsonify
from flask_dictabase import BaseTable, Dictabase
from flask_jobs import JobScheduler

import config
import slack
from app_types import Application
from ring.user import RingUser, delete_stored_images
from slack import send_slack_message

# Store this in an environment variable, not in source control.
HMAC_KEY = config.RING_HMAC_SIGNATURE_KEY


def verify_ring_webhook_signature(
        signing_key: str,
        raw_body: bytes,
        received_signature: str,
) -> bool:
    """
    Verify a Ring webhook HMAC-SHA256 signature.

    Ring signs the raw HTTP request body using HMAC-SHA256
    and sends the hex digest in the X-Signature header.
    """

    if not received_signature:
        return False

    expected_signature = hmac.new(
        signing_key.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    # Ring documents the signature as:
    #   sha256=<signature>
    received_signature = received_signature.lstrip("sha256=")

    # Constant-time comparison to prevent timing attacks.
    return hmac.compare_digest(
        expected_signature,
        received_signature,
    )


global app


def setup(a: Application):
    global app
    app = a
    app.db = cast(Dictabase, app.db)
    app.jobs = cast(JobScheduler, app.jobs)

    @app.route("/webhook", methods=["POST"])
    def webhook():
        # https://developer.amazon.com/docs/ring/api-documentation.html#webhook-v11-payload-structure
        # IMPORTANT:
        # Use request.get_data() rather than request.json here.
        # The HMAC must be calculated against the exact raw bytes
        # Ring sent.
        raw_body = request.get_data()

        # Get Ring's signature.
        signature = request.headers.get("X-Signature")

        # Authenticate the webhook BEFORE parsing/processing it.
        if not verify_ring_webhook_signature(
                HMAC_KEY,
                raw_body,
                signature,
        ):
            return jsonify({
                "error": "Invalid signature"
            }), 401

        # Now that the message is authenticated, parse the JSON.
        try:
            payload = request.get_json()
        except Exception:
            return jsonify({
                "error": "Invalid JSON"
            }), 400

        if not payload:
            return jsonify({
                "error": "Empty payload"
            }), 400

        # Basic payload validation.
        meta = payload.get("meta", {})
        data = payload.get("data", {})

        request_id = meta.get("request_id")
        account_id = meta.get("account_id")
        event_id = data.get("id")
        event_type = data.get("type")

        if not request_id or not event_id or not event_type:
            return jsonify({
                "error": "Invalid webhook payload"
            }), 400

        #  Check whether request_id has already been processed.
        if app.db.FindOne(RingWebhook, request_id=request_id):
            return jsonify({"status": "already_processed"}), 200

        # Store the authenticated webhook.

        new_ring_webhook = app.db.New(
            RingWebhook,
            request_id=request_id,
            account_id=account_id,
        )
        new_ring_webhook.Set('data', data)

        app.jobs.AddJob(
            func=process_webhook,
            args=(request_id,),
            name=f"Webhook {request_id}",
            errorCallback=slack.send_slack_error
        )

        return jsonify({
            "status": "processed"
        }), 200


class RingWebhook(BaseTable):
    request_id: str
    account_id: str
    data: dict


def process_webhook(request_id):
    global app
    app.db = cast(Dictabase, app.db)
    with app.app_context():
        webhook = app.db.FindOne(RingWebhook, request_id=request_id)
        if not webhook:
            return

        data = webhook.Get('data', {}) or {}
        event_type = data.get('type', None)
        if event_type in [
            'motion_detected', 
            'button_press', 
            'device_offline',
              'device_online',
              'device_removed',
              'device_added'
              ]:
            return

        send_slack_message('webhook event_type=', event_type, webhook.Get('data'))
        # Route to appropriate handler
        # if event_type == 'motion_detected':
        #     handle_motion_detection(payload)
        # elif event_type == 'button_press':
        #     handle_button_press(payload)
        # elif event_type == 'device_added':
        #     handle_device_addition(payload)
        # elif event_type == 'device_removed':
        #     handle_device_removal(payload)
        # elif event_type == 'device_online':
        #     handle_device_online(payload)
        # elif event_type == 'device_offline':
        #     handle_device_offline(payload)
        # elif event_type == 'app_integration_added':
        #     handle_app_integration_added(payload)
        # elif event_type == 'app_integration_removed':
        #     handle_app_integration_removed(payload)
        # elif event_type == 'subscription_activated':
        #     handle_subscription_activated(payload)
        # elif event_type == 'subscription_deactivated':
        #     handle_subscription_deactivated(payload)
        # else:
        #     return jsonify({'error': 'Unknown event type'}), 400

        if event_type in ['app_integration_removed', 'subscription_deactivated']:
            if data['attributes']['source']:
                account_id = data['attributes']['source']
                send_slack_message('app_integration_removed for account_id', account_id)
                ring_user = app.db.FindOne(RingUser, account_id=account_id)
                if ring_user:
                    send_slack_message('deleting stored images for ring_user', ring_user['email'])
                    delete_stored_images(app, ring_user['id'])
                    ring_user.Set('latest_events', None)
                    ring_user['subscription_status'] = event_type

        elif event_type in ['app_integration_added', 'subscription_activated']:
            if data['attributes']['source']:
                account_id = data['attributes']['source']
                send_slack_message('app_integration_added for account_id', account_id)
                ring_user = app.db.FindOne(RingUser, account_id=account_id)
                if ring_user:
                    ring_user['subscription_status'] = event_type
            
