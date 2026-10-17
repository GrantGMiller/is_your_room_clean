from typing import cast

from flask import Flask, flash, jsonify, render_template, request
from ring.user import RingUser, get_current_user
from ns_parental_controls import ParentalControl
from flask_dictabase import Dictabase
from .rewards import setup as setup_rewards
from .room_clean_settings import setup as setup_room_clean_settings
def setup(a:Flask):
    global app
    app = a
    setup_rewards(app)
    setup_room_clean_settings(app)

    @app.route('/nintendo')
    def nintendo():
        user = get_current_user()
        if not user:
            return "User not authenticated", 401

        ns = get_ns_manager(user['id'])

        if not ns.access_token or not ns.session_token:
            return render_template('nintendo/not_auth.html', auth_url=ns.get_auth_url())

        ns.get_device('') # updates the devices_map
        
        device_names= (user.GetItem('nintendo', 'device_map', {}) or {}).keys()
        
        
        return render_template(
            'nintendo/authorized.html', 
            device_names=device_names,
            nintendo_rewards=user.Get('nintendo_rewards', {}) or {}
        )
    
    @app.route('/nintendo/auth', methods=['POST'])
    def nintendo_auth():
        user = get_current_user()
        if not user:
            return "User not authenticated", 401

        ns = get_ns_manager(user['id'])
        auth_link = request.json.get('auth_link')
        print('44 auth_link=', auth_link)
        ns.process_auth_link(auth_link)

    
        if ns.access_token:
            return jsonify('nintendo account authorized')
        else:
            flash('Failed to link Nintendo account')
            return jsonify('nintendo account not authorized'), 401

    @app.route('/nintendo/get_allowed_playtime_today/<device_name>')
    def get_allowed_playtime_today(device_name):
        user = get_current_user()
        if not user:
            return "User not authenticated", 401

        ns = get_ns_manager(user['id'])
        allowed_playtime = ns.get_allowed_playtime_today(device_name)
        return jsonify({'allowed_playtime_today': allowed_playtime})

    @app.route('/nintendo/get_today_playtime_minutes/<device_name>')
    def get_today_playtime_minutes(device_name):
        user = get_current_user()
        if not user:
            return "User not authenticated", 401

        ns = get_ns_manager(user['id'])
        today_playtime_minutes = ns.get_today_playtime_minutes(device_name)
        return jsonify({'today_playtime_minutes': today_playtime_minutes})

    @app.route('/nintendo/lock_device/<device_name>', methods=['POST'])
    def lock_device(device_name):
        user = get_current_user()
        if not user:
            return "User not authenticated", 401

        ns = get_ns_manager(user['id'])
        ns.lock_device(device_name, True)
        return jsonify({'status': 'success'})
    
    @app.route('/nintendo/unlock_device/<device_name>', methods=['POST'])
    def unlock_device(device_name):
            user = get_current_user()
            if not user:
                return "User not authenticated", 401
    
            ns = get_ns_manager(user['id'])
            ns.lock_device(device_name, False)
            return jsonify({'status': 'success'})

    @app.route('/nintendo/add_time/<device_name>', methods=['POST'])
    def add_time(device_name):
        user = get_current_user()
        if not user:
            return "User not authenticated", 401

        ns = get_ns_manager(user['id'])
        minutes = request.json.get('minutes', 0)
        ns.add_playtime_minutes_for_today(device_name, minutes)
        return jsonify({'status': 'success'})

    @app.route('/nintendo/set_time/<device_name>/<int:minutes>', methods=['POST'])
    def set_time(device_name, minutes):
        user = get_current_user()
        if not user:
            return "User not authenticated", 401

        ns = get_ns_manager(user['id'])
        ns.set_playtime_minutes_for_today(device_name, minutes)
        return jsonify({'status': 'success'})

def save_state(**kwargs):
    print('save_state kwargs:', kwargs)
    app.db = cast(Dictabase, app.db)
    with app.app_context():
        user = app.db.FindOne(RingUser, id=kwargs['user_id'])
        for key, value in kwargs.items():
            user.SetItem(f'nintendo', key, value)
        

def load_state(**kwargs):
    print('load_state kwargs:', kwargs)
    with app.app_context():
        user = app.db.FindOne(RingUser, id=kwargs['user_id'])
        if 'user_id' in kwargs:
            user.SetItem(f'nintendo', 'user_id', kwargs['user_id'])
    return user.Get('nintendo', {})

def get_ns_manager(user_id):
    print('get_ns_manager(user_id:', user_id)
    with app.app_context():
        ns = ParentalControl(
            save_state_callback=save_state,
            load_state_callback=load_state,
            callback_kwargs = {'user_id': user_id},
            # debug=True
        )
        print('ns=', ns)
        print('ns.callback_kwargs=', ns.callback_kwargs)
        return ns

def get_device_names(user_id:int):
    with app.app_context():
        user = app.db.FindOne(RingUser, id=user_id)
        if not user:
            return []
        device_names= (user.GetItem('nintendo', 'device_map', {}) or {}).keys()
        return list(device_names)