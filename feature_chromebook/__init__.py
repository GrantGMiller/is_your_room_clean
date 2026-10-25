from flask import flash, jsonify, redirect, render_template, request
from urllib.parse import unquote
from familylink_bonustime import FamilyLinkWithBonusTime
from familylink_bonustime.helper import get_cookies_dict
from app_types import Application
import config



def setup(a:Application):
    global app
    app = a

    @app.route('/chromebook', methods=['GET', 'POST'])
    def chromebook():
        user = app.get_current_user()
        if not user:
            flash('Unrecognized user', 'danger')
            return redirect('/')
        
        familylink = get_family_link()

        if request.method == 'POST':
            # cookie_string = config.CHROMEBOOK_COOKIES# request.form.get('cookie_string')
            # account_index = config.CHROMEBOOK_AUTH_USER#request.form.get('account_index', 0)
            
            cookie_string = request.form.get('cookie_string')
            account_index = request.form.get('account_index', 0)
            
            if cookie_string:
                user.SetItem('chromebook', 'cookie_string', unquote(cookie_string))
                user.SetItem('chromebook', 'account_index', int(account_index))
                familylink = get_family_link()

        if not familylink:
            return render_template(
                "chromebook/needs_auth.html",
                                   persons=app.get_all_user_persons(),
                                   user=user,
                                   familylink=familylink
                                   )
        
        return render_template(
            'chromebook/assign_devices.html', 
            persons=list(app.get_all_user_persons()),
            assigned_devices=user.GetItem('chromebook', 'assigned_devices', {}) or {},
                                   user=user,
                                   familylink=familylink
                                   )

       

    @app.route('/chromebook/get_devices/<int:person_id>')
    def get_devices(person_id):
        devices = {}
        return render_template(
            "chromebook/chromebook.html",
            devices=devices
        )

    @app.route('/chromebook/assign', methods=['POST'])
    def assign_device():
        person_id = request.form.get('person_id', type=int)
        chromebook_child_name = request.form.get('chromebook_child_name')
        chromebook_device_name = request.form.get('chromebook_device_name')
        
        user = app.get_current_user()
        if not user:
            return jsonify({'error': 'Unrecognized user', 'category': 'danger'}), 404

        if person_id is None:
            return jsonify({'error': 'Person ID not provided', 'category': 'danger'}), 404

        person = app.get_person(person_id)
        if not person:
            return jsonify({'error': 'Person not found', 'category': 'danger'}), 404

        familylink = get_family_link()
        if not familylink:
            return jsonify({'error': 'FamilyLink not configured', 'category': 'danger'}), 404

        data = user.GetItem('chromebook', 'assigned_devices', {}) or {}
        data[str(person_id)] = (chromebook_child_name, chromebook_device_name)
        user.SetItem('chromebook', 'assigned_devices', data)

        return jsonify({
            'message': f'Assigned {chromebook_device_name} to {chromebook_child_name} for person {person["name"]}',
            'user': user
        })

    @app.route('/chromebook/unassign/<int:person_id>')
    def unassign_device(person_id):
        user = app.get_current_user()
        if not user:
            return jsonify({'error': 'Unrecognized user', 'category': 'danger'}), 404

        data = user.GetItem('chromebook', 'assigned_devices', {}) or {}
        if str(person_id) in data:
            del data[str(person_id)]
            user.SetItem('chromebook', 'assigned_devices', data)
            return jsonify({'message': f'Unassigned device for person {person_id}'})
        else:
            return jsonify({'error': 'No device assigned to this person', 'category': 'danger'}), 404

    @app.route('/chromebook/add_bonus_time/<int:person_id>/<int:minutes>')
    def add_bonus_time(person_id, minutes):
        user = app.get_current_user()
        if not user:
            return jsonify({'error': 'Unrecognized user', 'category': 'danger'}), 404

        person = app.get_person(person_id)
        if not person:
            return jsonify({'error': 'Person not found', 'category': 'danger'}), 404

        familylink = get_family_link()
        if not familylink:
            return jsonify({'error': 'FamilyLink not configured', 'category': 'danger'}), 404

        # Assuming FamilyLinkWithBonusTime has a method to add bonus time
        
        data = user.GetItem('chromebook', 'assigned_devices', {}) or {}
        if str(person_id) not in data:
            return jsonify({'error': 'No device assigned to this person', 'category': 'danger'}), 404
        
        familylink.add_bonus_time(
            child_name=data[str(person_id)][0],
            device_name=data[str(person_id)][1],
            minutes=minutes,
            verify=True
        )

        return jsonify({'message': f'Added bonus time {minutes} minutes for person {person["name"]}'})

    @app.route('/chromebook/logout')
    def chromebook_logout():
        user = app.get_current_user()
        if not user:
            flash('Unrecognized user', 'danger')
            return redirect('/')
        
        user.SetItem('chromebook', 'cookie_string', None)
        user.SetItem('chromebook', 'account_index', 0)
        flash('Logged out of Chromebook', 'success')
        return redirect('/chromebook')

def get_family_link():
    with app.app_context():
        user= app.get_current_user()
        if not user:
            return None
        
        cookie_string = user.GetItem('chromebook', 'cookie_string', None)
        auth_user_index = user.GetItem('chromebook', 'account_index', 0) or 0

        print('cookie_string:', cookie_string)
        print('auth_user_index:', auth_user_index)
        
        if cookie_string:
            return FamilyLinkWithBonusTime(
                cookies=get_cookies_dict(cookie_string),
                auth_user=auth_user_index
                )
        
        return None