import datetime
import time
import uuid
from pathlib import Path

import requests
from flask_dictabase import BaseTable

import config
from slack import send_slack_message

OAUTH_TOKEN_URL = 'https://oauth.ring.com/oauth/token'
AVA_BASE_URL = "https://api.amazonvision.com"


class RingUser(BaseTable):
    account_id: str
    access_token: str
    refresh_token: str
    expires_at: float
    status: str
    email: str
    login_url: str
    login_url_expires_at: int  # epoch seconds

    def ui_safe(self):
        return {
            'account_id': self['account_id'],
            'access_token': self['access_token'][:10] + '*' * len(self['access_token']),
            'refresh_token': self['refresh_token'][:10] + '*' * len(self['refresh_token']),
            'expires_at': self['expires_at'],
            'status': self['status'],

        }

    def get_last_login_url(self):
        if not self.get('login_url', None):
            return self.get_new_login_url()
        else:
            return self.get('login_url')

    def get_new_login_url(self):
        self['login_url'] = f'{config.SERVER_HOST_URL}/magic_link/{uuid.uuid4()}'
        # link is only valid for X minutes
        self['login_url_expires_at'] = time.time() + (10 * 60)
        return self['login_url']

    def get_email(self):
        if self.get('email', None):
            return self['email']
        else:
            """
            Calls Ring's /v1/users/me directly with a raw access token (no
            RingUser/db lookup involved) and returns the email from the response.
            Useful at token-exchange time, before a RingUser row even exists yet.
            https://developer.amazon.com/docs/ring/api-documentation.html#access-tokens
            """

            resp = self.make_authenticated_request(
                f"{AVA_BASE_URL}/v1/users/me",
            )
            resp.raise_for_status()
            email = resp.json()["data"]["attributes"]["email"]
            self['email'] = email.lower()
            return email

    def _refresh_token_if_needed(self):
        """
        Exchange the stored refresh_token for a new access_token (and,
        per OAuth 2.0 refresh-token rotation, typically a new refresh_token
        too). Ring's token endpoint is the same one used for the initial
        code exchange, just with grant_type=refresh_token.
        https://developer.amazon.com/docs/ring/api-documentation.html#access-tokens
        """
        response = requests.post(
            OAUTH_TOKEN_URL,
            data={
                'grant_type': 'refresh_token',
                'refresh_token': self['refresh_token'],
                'client_id': config.RING_CLIENT_ID,
                'client_secret': config.RING_CLIENT_SECRET,
            },
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
        )
        response.raise_for_status()
        tokens = response.json()

        # Each assignment below is auto-persisted to the DB by Dictabase.
        self['access_token'] = tokens['access_token']
        self['refresh_token'] = tokens.get('refresh_token', self['refresh_token'])
        self['expires_at'] = time.time() + tokens['expires_in']

    def get_valid_access_token(self):
        if time.time() >= self['expires_at'] - 60:  # Refresh 1 minute early
            self._refresh_token_if_needed()
        return self['access_token']

    def make_authenticated_request(self, *args, method='GET', **kwargs):
        headers = kwargs.pop('headers', {})
        headers['Authorization'] = 'Bearer {}'.format(self.get_valid_access_token())
        return requests.request(method, *args, headers=headers, **kwargs)

    def get_devices(self, include='status,capabilities'):
        """
        Returns all Ring devices this user has granted the app access to.
        https://developer.amazon.com/docs/ring/api-documentation.html
        GET /v1/devices returns a JSON:API-formatted list under 'data', e.g.:
        {
          "data": [
            {
              "type": "devices",
              "id": "...",
              "attributes": {"name": "Front Door", "kind": "doorbell", ...}
            },
            ...
          ]
        }
        `include` controls which related resources get embedded per item
        (comma-separated), e.g. 'status,capabilities'.
        """
        resp = self.make_authenticated_request(
            'https://api.amazonvision.com/v1/devices',
            params={'include': include},
        )
        resp.raise_for_status()
        return resp.json().get('data', [])

    def get_snapshot(self, device_id: str, save_dir: Path = 'images'):
        """
        Fetches the most recent still-frame image for a device.
        https://developer.amazon.com/docs/ring/api-documentation.html#download-flow
        (Image Snapshots API)

        POST /v1/devices/{device_id}/media/image/download
        Returns the raw image bytes (JPEG/PNG) -- Ring applies a mandatory
        watermark (Ring logo, Device ID, App Name, timestamp) server-side,
        this cannot be disabled.

        Usage:
            image_bytes = ring_user.get_snapshot(device='123')
            with open('snapshot.jpg', 'wb') as f:
                f.write(image_bytes)
        """
        start_dt = datetime.datetime.now() - datetime.timedelta(days=2)
        end_dt = datetime.datetime.now()
        resp = self.make_authenticated_request(
            'https://api.amazonvision.com/v1/devices/{}/media/image/download'.format(device_id),
            method='POST',
            json={
                'type': 'latest_in_range',
                "start_timestamp": int(start_dt.timestamp() * 1000),
                "end_timestamp": int(end_dt.timestamp() * 1000),
                "image_options": {
                    "format": "jpeg",
                    # "resolution": {"width": 1920, "height": 1080}
                },
                "components": [
                    {"component_id": '1'}
                ]
            },
        )
        if not resp.ok:
            send_slack_message(resp.headers, resp.text)

        resp.raise_for_status()

        save_path = save_dir / f'{uuid.uuid4()}.jpg'
        with open(save_path, 'wb') as f:
            f.write(resp.content)

        return save_path
