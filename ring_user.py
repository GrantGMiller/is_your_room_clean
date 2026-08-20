import time

import requests
from flask_dictabase import BaseTable


class RingUser(BaseTable):
    account_id: str
    access_token: str
    refresh_token: str
    expires_at: float
    status: str

    def ui_safe(self):
        return {
            'account_id': self['account_id'],
            'access_token': self['access_token'][:10] + '*' * len(self['access_token']),
            'refresh_token': self['refresh_token'][:10] + '*' * len(self['refresh_token']),
            'expires_at': self['expires_at'],
            'status': self['status'],

        }
    def _refresh_token_if_needed(self):
        pass

    def get_valid_access_token(self):
        if time.time() >= self['expires_at'] - 60:  # Refresh 1 minute early
            self._refresh_token_if_needed()
        return self['access_token']

    def make_authenticated_request(self, *args, **kwargs):
        headers = kwargs.get('headers', {})
        headers['Authorization'] = 'Bearer {}'.format(self.get_valid_access_token())
        return requests.get(*args, **kwargs, headers=headers)

    # def _get_users_email(self):
    #     resp = self.make_authenticated_request(
    #         method='GET',
    #         url='https://api.amazonvision.com/v1/users/me'
    #     )
    #     '''
    #     https://developer.amazon.com/docs/ring/api-documentation.html#access-tokens
    #     resp looks like
    #     {
    #       "data": {
    #         "type": "users",
    #         "id": "ava1.ring.account.XXXYYY",
    #         "attributes": {
    #           "first_name": "John",
    #           "last_name": "Doe",
    #           "email": "johndoe@example.com"
    #         }
    #       }
    #     }
    #     '''
    #     data = resp.json().get('data', {})
    #     if data.get('id', None):
    #         self._set_user_id(data['id'])
