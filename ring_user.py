import time
import uuid
from pathlib import Path

import requests
from flask import flash
from flask_dictabase import BaseTable

import config
from slack import send_slack_message

OAUTH_TOKEN_URL = 'https://oauth.ring.com/oauth/token'
AVA_BASE_URL = "https://api.amazonvision.com"

IMAGE_REQUEST_TIMEOUT = 15 * 60  # (seconds) only request an image every X seconds


class RingUser(BaseTable):
    account_id: str
    access_token: str
    refresh_token: str
    expires_at: float
    status: str
    email: str
    login_url: str
    login_url_expires_at: int  # epoch seconds
    last_image_timestamp: dict  # keep track of the last image requested, only request a new image every IMAGE_REQUEST_TIMEOUT seconds

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
        self['login_url'] = f'{config.SERVER_HOST_URL}magic_link/{uuid.uuid4()}'
        # link is only valid for X seconds
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

        if not resp.ok:
            self.app.logger.error(str(resp))
            send_slack_message('error 131:', resp.status_code, resp.headers, resp.reason, str(resp.text))
            flash(resp.reason, 'danger')
            return []

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

        # if an image was requested less than X seconds ago, just return the last image
        latest_images = list(self.app.db.FindAll(
            RingImage,
            device_id=device_id,
            _orderBy='timestamp_epoch_ms',
            _limit=1,
            _reverse=True,
        ))
        self.app.logger.error('lastest images=' + str(latest_images))
        if latest_images and (latest_images[0].get('timestamp_epoch_ms', 0) or 0) > (time.time() * 1000) - (
                IMAGE_REQUEST_TIMEOUT * 1000):
            return latest_images[0]['id']

        # the existing images are too old, request a new image

        start_timestamp_ms = int(time.time() * 1000) - (12 * 60 * 60 * 1000)
        # end_timestamp_ms = int(time.time() * 1000)
        resp = self.make_authenticated_request(
            'https://api.amazonvision.com/v1/devices/{}/media/image/download'.format(device_id),
            method='POST',
            json={
                'type': 'latest_in_range',
                "start_timestamp": start_timestamp_ms,
                "image_options": {
                    "format": "jpeg",
                    "resolution": {"width": 1280, "height": 720}
                },
            },
        )
        if not resp.ok:
            send_slack_message(resp.headers, resp.text)

        resp.raise_for_status()

        save_path = Path(save_dir) / f'{uuid.uuid4()}.jpg'
        with open(save_path, 'wb') as f:
            f.write(resp.content)

        ring_image = self.db.New(
            RingImage,
            account_id=self['account_id'],
            device_id=device_id,
            image_path=str(save_path),
            timestamp_epoch_ms=time.time() * 1000,
        )

        return ring_image['id']


class RingImage(BaseTable):
    account_id: str
    device_id: str
    image_path: str
    cleanliness: int  # 0-100 (100 means perfectly clean)
    summary: str  # description of the cleanliness
    scoring_in_progress: bool  # true when the request has already been sent to the ai for scoring
    timestamp_epoch_ms: int  # when the image was requested
    isError: bool
    error: str

    def ui_safe(self):
        return dict(self)
