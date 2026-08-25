import requests

import config

APIKEY = config.SELFAPIKEY


def get(*a, **k):
    return requests.get(*a, headers={
        'X-API-KEY': APIKEY,
    }, **k)


BASE_URL = config.SERVER_HOST_URL + 'api'
devices = get(f'{BASE_URL}/get_devices').json()
for device in devices:
    print('name=', device['attributes']['name'], ', device_id=', device['id'], )
    data = get(f'{BASE_URL}/get_summary/{device["id"]}').json()
    print('summary=', data.get('summary', None), ', cleanliness=', data.get('cleanliness', None))
