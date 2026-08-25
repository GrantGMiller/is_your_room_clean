from typing import cast

from flask import request, jsonify, send_file
from flask_dictabase import Dictabase

from ring_user import RingUser, RingImage


def setup(a):
    global app
    app = a
    app.db = cast(Dictabase, app.db)

    @app.route('/api/get_devices', methods=['GET'])
    def get_devices():
        ring_user = get_user()
        return jsonify(ring_user.get_devices())

    @app.route('/api/get_snapshot/<device_id>')
    def get_snapshot(device_id):
        ring_user = get_user()
        img_id = ring_user.get_snapshot(device_id)
        img: RingImage = app.db.FindOne(RingImage, id=img_id)
        return send_file(img['image_path'])

    @app.route('/api/get_summary/<device_id>')
    def get_summary(device_id):
        ring_user = get_user()
        img_id = ring_user.get_snapshot(device_id)
        img: RingImage = app.db.FindOne(RingImage, id=img_id)
        return jsonify(img)


def get_user():
    ring_user: RingUser = app.db.FindOne(
        RingUser,
        api_key=request.headers.get('X-API-KEY')
    )
    return ring_user
