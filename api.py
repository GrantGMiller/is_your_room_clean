import random
import string
from typing import cast

import flask_login
from flask import request, jsonify, send_file, flash, redirect, render_template
from flask_dictabase import Dictabase

from ring_user import RingUser, RingImage, get_current_user


def setup(a):
    global app
    app = a
    app.db = cast(Dictabase, app.db)

    @app.route('/api/get_devices', methods=['GET'])
    def api_get_devices():
        ring_user = get_user_from_api_request()
        return jsonify(ring_user.get_devices())

    @app.route('/api/get_snapshot/<device_id>')
    def api_get_snapshot(device_id):
        ring_user = get_user_from_api_request()
        img_id = ring_user.get_snapshot(device_id)
        img: RingImage = app.db.FindOne(RingImage, id=img_id)
        return send_file(img['image_path'])

    @app.route('/api/get_summary/<device_id>')
    def api_get_summary(device_id):
        ring_user = get_user_from_api_request()
        img_id = ring_user.get_snapshot(device_id)
        img: RingImage = app.db.FindOne(RingImage, id=img_id)
        return jsonify(img)

    #
    @app.route('/api')
    def api():
        ring_user: RingUser = get_current_user()
        print('ring_user=', ring_user)
        if not ring_user:
            flash('unknown user', 'warning')
            return redirect('/dashboard')

        current_api_key = ring_user.get('api_key', '') or ''
        NUM_MASKED_CHARS = 5
        masked_key = current_api_key[:NUM_MASKED_CHARS] + '*' * (len(current_api_key) - NUM_MASKED_CHARS)
        return render_template(
            'api-key.html',
            current_api_key_masked=masked_key,
        )

    @app.route('/get_new_api_key')
    def get_new_api_key():
        ring_user = app.db.FindOne(
            RingUser,
            account_id=flask_login.current_user.get('account_id', None)
        )
        if not ring_user:
            flash('unknown user', 'warning')
            redirect('/dashboard')

        new_api_key = ''.join(random.choice(string.hexdigits) for _ in range(256))
        ring_user['api_key'] = new_api_key
        return new_api_key

    @app.route('/delete_api_key', methods=['POST'])
    def api_delete_key():
        ring_user: RingUser = flask_login.current_user
        if ring_user:
            ring_user['api_key'] = None
        return redirect('/api')


def get_user_from_api_request():
    if not request.headers.get('X-API-KEY', None):
        # if the key is empty, returnnone
        return None

    ring_user: RingUser = app.db.FindOne(
        RingUser,
        api_key=request.headers.get('X-API-KEY')
    )
    return ring_user
