import datetime
import json
import random
import string
import time
import uuid
from pathlib import Path
from typing import Optional, TypedDict, cast

import flask_login
import requests
from flask import flash
from flask_dictabase import BaseTable, Dictabase

import config
import slack
from ai_cleanliness import evaluate_cleanliness
from app_types import Application
from feature_email import render_room_clean_email, SETTINGS_KEY
from feature_email.helpers import send_email
from slack import send_slack_message

OAUTH_TOKEN_URL = 'https://oauth.ring.com/oauth/token'
AVA_BASE_URL = "https://api.amazonvision.com"

IMAGE_REQUEST_TIMEOUT = 5 * 60  # (seconds) only request an image every X seconds


class ChoreSettings(TypedDict):
    morning_time: str  # datetime.time.isoformat()
    afternoon_time: str  # datetime.time.isoformat()
    evening_time: str  # datetime.time.isoformat()


class RingUser(flask_login.UserMixin, BaseTable):
    account_id: str
    access_token: str
    refresh_token: str
    expires_at: float
    status: str
    email: str
    login_url: str
    login_code: str  # a six digit code like "012345"
    login_url_expires_at: int  # epoch seconds
    last_image_timestamp: dict  # keep track of the last image requested, only request a new image every IMAGE_REQUEST_TIMEOUT seconds
    api_key: Optional[str]
    chore_settings: ChoreSettings  # store the user's chore settings
    ring_user_claimed_at_ms: int  # epoch milliseconds when the app was authorized, used to prevent requesting images before this time
    timezone: str  # store the user's timezone, default to UTC if not set
    enable_daylight_savings: bool
    latest_events: dict  # {device_id: timestamp_ms}
    wall_display_url: str
    wall_link_expires_at: float
    is_wall_user: bool
    enabled_features: dict  # {str(feature_name): bool(enabled)}
    last_clean_score: str
    subscription_status: str # latest subscription status

    def log_cleanliness_score(self, device_id: str, cleanliness_score: float):
        print('log_cleanliness_score', device_id[:10], cleanliness_score)

        old_are_all_rooms_clean = self.are_all_rooms_clean
        # send_slack_message('61 old_are_all_rooms_clean', old_are_all_rooms_clean)

        device_name = None
        for dev in self.get_devices():
            if dev['id'] == device_id:
                device_name = dev['attributes']['name']
        # send_slack_message('67 device_name', device_name)
        self.SetItem(
            'last_clean_score',
            device_name,
            cleanliness_score
        )

        new_are_all_rooms_clean = self.are_all_rooms_clean
        # send_slack_message('75 new_are_all_rooms_clean', new_are_all_rooms_clean)
        if new_are_all_rooms_clean != old_are_all_rooms_clean:
            self.send_clean_email()

    @property
    def clean_threshold(self):
        return 50  # percent

    @property
    def are_all_rooms_clean(self):
        return all([score > self.clean_threshold for score in self.Get('last_clean_score', {}).values()])

    def send_clean_email(self):
        # send_slack_message('84 send_clean_email')
        are_all_rooms_clean = self.are_all_rooms_clean
        should_send_clean_email = self.GetItem(SETTINGS_KEY, 'email_when_all_rooms_clean', False)
        should_send_dirty_email = self.GetItem(SETTINGS_KEY, 'email_when_rooms_dirty', False)

        if are_all_rooms_clean:
            if not should_send_clean_email:
                return
        else:
            # at least one room is dirty
            if not should_send_dirty_email:
                return

        room_data = self.Get('last_clean_score', {}) or {}
        if room_data:
            send_email(
                to=self['email'],
                subject='Room Cleanliness Update',
                html=render_room_clean_email(room_data),
                body=json.dumps(room_data, indent=2),
            )

    def get_chore_settings(self) -> ChoreSettings:
        ret = self.Get('chore_settings', {})
        if 'morning_time' not in ret:
            ret['morning_time'] = datetime.time(hour=6, minute=0).isoformat()
        if 'afternoon_time' not in ret:
            ret['afternoon_time'] = datetime.time(hour=12, minute=0).isoformat()
        if 'evening_time' not in ret:
            ret['evening_time'] = datetime.time(hour=17, minute=0).isoformat()
        return ret

    def get_id(self, *a, **k):
        # needed for flask_login to identify the user
        # since im using two classes for a logged in user
        # RingUser and WallUser
        # Need to make sure the ids are not duplicated.
        return self['id']

    def get_subscription_status(self):
        resp = self.make_authenticated_request(
            url='https://api.amazonvision.com/v1/accounts/me/subscriptions'
        )
        if not resp.ok:
            return None

        resp_payload = resp.json()
        print('resp_payload=', resp_payload)
        if not isinstance(resp_payload, dict) or not isinstance(resp_payload.get('data'), list):
            print('Invalid subscriptions response: expected a data list')
            return None

        statuses = []
        for subscription in resp_payload['data']:
            if not isinstance(subscription, dict):
                print('Invalid subscription entry')
                return None
            attributes = subscription.get('attributes')
            if not isinstance(attributes, dict) or not isinstance(
                attributes.get('status'), str
            ):
                print('Invalid subscription entry: missing status')
                return None
            sub_id = subscription.get('id')
            sub_status = attributes['status']
            statuses.append(f'{sub_id}: {sub_status}')

        status_string = ', '.join(statuses)
        if statuses:
            self['subscription_status'] = status_string
            return status_string
        return None

    def ui_safe(self):
        return {
            'account_id': self['account_id'],
            'access_token': self['access_token'][:10] + '*' * len(self['access_token']),
            'refresh_token': self['refresh_token'][:10] + '*' * len(self['refresh_token']),
            'expires_at': self['expires_at'],
            'status': self['status'],
            'api_key': '*' * len(self['api_key']),
        }

    def get_last_login_url(self):
        if not self.get('login_url', None):
            return self.get_new_login_url()
        else:
            return self.get('login_url')

    def get_new_login_url(self):
        self['login_url'] = f'{config.SERVER_HOST_URL}magic_link/{uuid.uuid4()}'
        self['login_code'] = str(random.randint(0, 999999)).zfill(6)
        print('login_url=', self['login_url'])
        print('login_code=', self['login_code'])
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
            if not resp.ok:
                return None
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
        if not self.get('refresh_token', None):
            return

        response = requests.post(
            OAUTH_TOKEN_URL,
            data={
                'grant_type': 'refresh_token',
                'refresh_token': self.get('refresh_token', None),
                'client_id': config.RING_CLIENT_ID,
                'client_secret': config.RING_CLIENT_SECRET,
            },
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
        )
        if not response.ok:
            return
        tokens = response.json()

        # Each assignment below is auto-persisted to the DB by Dictabase.
        self['access_token'] = tokens['access_token']
        self['refresh_token'] = tokens.get('refresh_token', self['refresh_token'])
        self['expires_at'] = time.time() + tokens['expires_in']

    def get_valid_access_token(self):
        if not self.get('expires_at', None) or time.time() >= float(
                self.get('expires_at', 0)) - 60:  # Refresh 1 minute early
            self._refresh_token_if_needed()
        return self.get('access_token', None)

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

        if not self.get('access_token', None):
            return []

        resp = self.make_authenticated_request(
            'https://api.amazonvision.com/v1/devices',
            params={'include': include},
        )

        if not resp.ok:
            self.app.logger.error(str(resp))
            send_slack_message('error 131:', resp.status_code, resp.headers, resp.reason, str(resp.text))
            flash(resp.reason, 'danger')
            return self.Get('last_devices', [])

        devices = resp.json().get('data', [])
        self.Set('last_devices', devices)
        if len(devices) == 0:
            # we lost authorization to the devices
            self['ring_user_claimed_at_ms'] = None

        return devices

    def get_devices_names(self):
        devices = self.get_devices()
        return [device.get('attributes', {}).get('name') for device in devices]

    def get_latest_event(self, device_id: str) -> Optional[dict]:
        """Return the newest event for a device, or None when no events exist."""
        print('get_latest_event', device_id[-10:])
        response = self.make_authenticated_request(
            f'https://api.amazonvision.com/v1/history/devices/{device_id}/events'
        )
        print('268  response.text=', response.text)
        if response.ok:
            events = response.json().get('data', [])
            return events[0] if events else None
        else:
            send_slack_message(response.text)

        return None

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
            image_bytes = self.get_snapshot(device_id='123')
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

        print('dev=', device_id[-10:], 'lastest images=' + str(latest_images))
        if latest_images and (latest_images[0].get('timestamp_epoch_ms', 0) or 0) > (time.time() * 1000) - (
                IMAGE_REQUEST_TIMEOUT * 1000):
            img = latest_images[0]
            print('179 get_snapshot returning old image', img)
            print('old image dt=', datetime.datetime.fromtimestamp(img['timestamp_epoch_ms'] / 1000))
            return img['id']

        # the existing images are too old, request a new image

        # ok some weirdness, you cannot request a start_time that is before the app was authorized
        # so use the start_time or the app creation time, whichever is greater
        dt_one_min_ago = datetime.datetime.now(
            datetime.timezone.utc,
        ) - datetime.timedelta(minutes=1)
        last_event_timestamp_ms = self.GetItem(
            'latest_events',
            device_id,
            dt_one_min_ago.timestamp() * 1000
        ) or dt_one_min_ago.timestamp() * 1000

        start_timestamp_ms = int(last_event_timestamp_ms)  # make sure its an int cuz server will reject a float
        # end_timestamp_ms = int(time.time() * 1000) # defaults to now

        print('grabbing a new snapshot, start_timestamp_ms=', start_timestamp_ms, 'as dt=',
              datetime.datetime.fromtimestamp(start_timestamp_ms / 1000))
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

        has_time_range_error = False
        try:
            errors = resp.json().get('errors', [])
            for error in errors:
                print('error=', error)
                code = error.get('code', None)
                print('code=', code)
                if code == 'TIME_RANGE_NOT_AUTHORIZED':
                    has_time_range_error = True
        except Exception as e:
            print('354', e)

        if resp.status_code == 416 or has_time_range_error:
            # The user may have tried to access a time before this app was authorized
            # Or we otherwise lost the authorization
            print('clearing the latest_events for', device_id)
            self.SetItem('latest_events', device_id, None)
            return f'359 {resp.status_code} {resp.text}'

        if not resp.ok:
            return f'364 {resp.status_code} {resp.text} {resp.reason} {resp.headers}'
        
        if resp.ok and not self.get('ring_user_claimed_at_ms', None):
            self['ring_user_claimed_at_ms'] = time.time() * 1000

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

        self.app.jobs.AddJob(
            func=score_cleanliness,
            kwargs={
                'image_id': ring_image['id'],
            },
            errorCallback=slack.send_slack_error
        )

        return ring_image['id']

    def get_new_wall_display_url(self):
        # generate a new wall display url for the user
        wall_link_code = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(6))
        self['wall_display_url'] = f'{config.SERVER_HOST_URL}wall/{wall_link_code}'
        self['wall_link_expires_at'] = time.time() + (60 * 60 * 1)
        return self['wall_display_url']

    def get_wall_link_url(self):
        if not self.get('wall_display_url', None):
            return self.get_new_wall_display_url()
        else:
            return self['wall_display_url']

    def get_ring_user(self):
        print('get_ring_user')
        if self.get('is_wall_user', False):
            print('returning ring_user')
            ret = self.app.db.FindOne(RingUser, wall_user_id=self['id'])
            print('ret.is_wall_user=', ret.is_wall_user)
            return ret
        else:
            print('returning self')
            return self

    def get_wall_user(self):
        print('428 get_wall_user')
        if self.get('is_wall_user', False):
            print('returning wall_user self')
            return self

        if self.get('wall_user_id', None) is None:
            kwargs = dict(self)
            kwargs.pop('id', None)
            kwargs['is_wall_user'] = True

            print('creating new wall user')
            wall_user: RingUser = self.app.db.New(
                RingUser,
                **kwargs,
            )

            self['wall_user_id'] = wall_user['id']
            print('443 wall_user=', wall_user)
            return wall_user

        print('returning wall_user self wall_user_id=', self.get('wall_user_id', None))
        wall_user: Optional[RingUser] = self.app.db.FindOne(RingUser, id=self.get('wall_user_id', None))
        if not wall_user:
            self['wall_user_id'] = None
            print('woohoo recursion!!!')
            return self.get_wall_user() #
        print('450 returning walluser=', wall_user)
        return wall_user

    @property
    def is_wall_user(self):
        return self.get('is_wall_user', False)


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

    @property
    def user(self):
        return self.app.db.FindOne(
            RingUser,
            account_id=self['account_id'],
        ).get_ring_user()

    def log_cleanliness(self, score: float):
        print('390 log_cleanliness(', score)
        user: RingUser = self.user
        print('431 user=', user)
        # send_slack_message('436')
        if user:
            user.log_cleanliness_score(
                self['device_id'],
                score,
            )


def delete_stored_images(app: Application, user_id: int) -> int:
    with app.app_context():
        ring_user = app.db.FindOne(RingUser, id=int(user_id))
        if not ring_user:
            return 0

        image_records = list(
            app.db.FindAll(RingImage, account_id=ring_user.get("account_id", None))
        )
        deleted_count = 0
        for image in image_records:
            image_path = image.get("image_path")
            try:
                if image_path:
                    path = Path(image_path)
                    if path.exists():
                        path.unlink()
            except OSError:
                app.logger.exception("Failed to delete image file")
            app.db.Delete(image)
            deleted_count += 1

        return deleted_count


def setup(a: Application):
    global app
    app = a
    app.db = cast(Dictabase, app.db)

    login_manager = flask_login.LoginManager()
    login_manager.init_app(app)

    @login_manager.user_loader
    def user_loader(user_id):
        try:
            return app.db.FindOne(RingUser, id=int(user_id))
        except Exception as e:
            print('Error loading user_id=', user_id, e)
            return None


def get_current_wall_user() -> Optional[RingUser]:
    with app.app_context():
        user = app.get_current_user()
        if user:
            return user.get_wall_user()
        return None


def score_cleanliness(image_id):
    print('score_cleanliness id=', image_id)
    with app.app_context():
        app.db = cast(Dictabase, app.db)
        image = app.db.FindOne(
            RingImage,
            id=image_id,
        )
        if image and image.get('cleanliness', None) is None and not image.get('scoring_in_progress', False):
            image['scoring_in_progress'] = True
            with open(
                    image['image_path'],
                    'rb'
            ) as f:
                image_bytes = f.read()

            try:
                # send_slack_message('before evaluate_cleanliness')
                res = evaluate_cleanliness(image_bytes=image_bytes)
                print('ai returned score_cleanliness id=', image_id, ', res=', res)
                if res:
                    image.log_cleanliness(res['cleanliness'])
                    image['cleanliness'] = res['cleanliness']
                    image['summary'] = res['summary']
                else:
                    print('evaluation failed')
                    return
            except Exception as e:
                print('score_cleanliness error=', e)
                image['isError'] = True
                image['error'] = str(e)
                image['scoring_in_progress'] = False  # maybe we will try again
                raise e  # raise so that the error is sent via slack


def get_snapshots_for_user_id(id: int):
    # fetch the latest snapshots for all of the users devices
    with app.app_context():
        app.db = cast(Dictabase, app.db)
        user: RingUser = app.db.FindOne(RingUser, id=int(id))
        if user:
            for device in user.get_devices():
                user.get_snapshot(device['id'])
