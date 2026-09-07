'''
Use this to make sure the API is working
'''
import json

import requests

import config


LOCAL_PARAMS = {
    'BASE_URL': 'http://localhost:3888/',
    'KEY': config.SELFAPIKEY
}


def get(*a, **k):
    return requests.get(*a, headers={
        'X-API-KEY': PARAMS['KEY'],
    }, **k)

PARAMS = LOCAL_PARAMS

devices = get(f'{PARAMS["BASE_URL"]}api/get_devices').json()

for device in devices:
    print('device=', json.dumps(device, indent=2))
    # print('name=', device['attributes']['name'], ', device_id=', device['id'], )
    # data = get(f'{BASE_URL}/get_summary/{device["id"]}').json()
    # print('summary=', data.get('summary', None), ', cleanliness=', data.get('cleanliness', None))
