from flask import Flask, redirect, session, jsonify, render_template, request

from app_types import Application
from feature_chores.helpers import get_current_user_person


def setup(a: Application):
    global app
    app = a

    @app.route('/wall_display/person/<int:person_id>', methods=['GET', 'POST'])
    def wall_display_person(person_id):

        person = get_current_user_person(person_id)
        if not person:
            return "Person not found", 404
        
        if not person.get('pin'):
            return redirect(f'/wall_display/setup_pin/{person_id}')

        if not session.get('person_id') == person_id:
            return redirect(f'/wall_display/pin/{person_id}')
        
        if request.method == 'POST':
            payload = request.get_json()
            if not isinstance(payload, dict):
                return jsonify({"error": "Expected a JSON object"}), 400
            color = payload.get('color')
            allowed_colors = {
                "primary",
                "secondary",
                "success",
                "danger",
                "warning",
                "info",
                "light",
                "dark",
            }
            if color not in allowed_colors:
                return jsonify({"error": "Invalid color"}), 400

            person['color'] = color
            return jsonify({"color": color})

        device_name = person.get('nintendo_device_name', None)
        key = f'nintendo_settings_{device_name}'
        data = app.get_current_user().get_ring_user().Get(key, {})
        rooms_to_clean = data.get('room_names_to_clean', []) or []
        current_cleanliness = (
            app.get_current_user()
            .get_ring_user()
            .Get('last_clean_score', {})
            or {}
        )
        minimum_cleanliness = data.get('minimum_cleanliness', 50)

        # chromebook stuff
        assigned_devices = (
            app.get_current_user().get_ring_user().GetItem('chromebook', 'assigned_devices', {})
            or {}
        )
        print('assigned_devices=', assigned_devices)
        chromebook_assignment = (
            assigned_devices.get(str(person_id))
            or assigned_devices.get(person_id)
        )
        print('chromebook_assignment:', chromebook_assignment   )
        return render_template(
            'chores/wall_display/person_page.html',
            person=person,
            rooms_to_clean=rooms_to_clean,
            current_cleanliness=current_cleanliness,
            minimum_cleanliness=minimum_cleanliness,
            chromebook_assignment=chromebook_assignment,
        )

    @app.route('/wall_display/person/<int:person_id>/sticker_archive')
    def wall_display_sticker_archive(person_id):
        person = get_current_user_person(person_id)
        if not person:
            return jsonify({"error": "Person not found"}), 404
        if session.get('person_id') != person_id:
            return jsonify({"error": "PIN required"}), 403

        sticker_archive = person.Get('sticker_archive', []) or []
        if not isinstance(sticker_archive, list) or any(
            not isinstance(sticker, str) for sticker in sticker_archive
        ):
            return jsonify({"error": "Invalid sticker archive"}), 500

        return jsonify({"stickers": sticker_archive})

    @app.route('/wall_display/add_nintendo_time/<int:person_id>', methods=['POST'])
    def wall_display_add_nintendo_time(person_id):
        person = get_current_user_person(person_id)
        if not person:
            return jsonify({"error": "Person not found"}), 404
        if session.get('person_id') != person_id:
            return jsonify({"error": "PIN required"}), 403

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Expected a JSON object"}), 400
        minutes = payload.get('minutes')
        if (
            isinstance(minutes, bool)
            or not isinstance(minutes, int)
            or minutes <= 0
        ):
            return jsonify({"error": "Minutes must be a positive whole number"}), 400

        device_name = person.get('nintendo_device_name')
        if not device_name:
            return jsonify({"error": "No Nintendo device is associated with this person"}), 400

        user = app.get_current_user().get_ring_user()
        settings = user.Get(f'nintendo_settings_{device_name}', {}) or {}
        rooms_to_clean = settings.get('room_names_to_clean', []) or []
        minimum_cleanliness = int(settings.get('minimum_cleanliness', 50))
        current_cleanliness = user.Get('last_clean_score', {}) or {}
        if any(
            int(current_cleanliness.get(room_name, 0)) < minimum_cleanliness
            for room_name in rooms_to_clean
        ):
            return jsonify({
                "error": (
                    "Required rooms have not reached the cleanliness threshold"
                )
            }), 403

        available_minutes = person.get('nintendo_time', 0) or 0
        if minutes > available_minutes:
            return jsonify({
                "error": "Requested time exceeds the available balance"
            }), 400

        from feature_nintendo import get_ns_manager

        ns = get_ns_manager(person['owner_id'])
        ns.add_playtime_minutes_for_today(device_name, minutes)
        remaining_minutes = available_minutes - minutes
        person['nintendo_time'] = remaining_minutes
        return jsonify({
            "device_name": device_name,
            "remaining_minutes": remaining_minutes,
        })

    @app.route('/wall_display/pin/<int:person_id>')
    def wall_display_pin(person_id):
        person = get_current_user_person(person_id)
        if not person:
            return "Person not found", 404
        return render_template(
            'chores/wall_display/pin_page.html',
            person_id=person_id
        )

    @app.route('/wall_display/setup_pin/<int:person_id>')
    def wall_display_setup_pin(person_id):
        person = get_current_user_person(person_id)
        if not person:
            return "Person not found", 404
        return render_template(
            'chores/wall_display/setup_pin.html',
            person_id=person_id,
            person_name=person['name'],
        )

    @app.route('/wall_display/check_pin/<int:person_id>', methods=['POST'])
    def wall_display_check_pin(person_id):
        form_pin = request.form.get('pin')
        person = app.get_person(person_id)
        print('74 person=', person)
        if not person:
            return "Person not found", 404
        if person.get('pin') != form_pin:
            return jsonify({"error": "Invalid pin"}), 400
        session['person_id'] = person['id']
        print('session=', session)
        return redirect(f'/wall_display/person/{person_id}')

    @app.route('/wall_display/save_pin/<int:person_id>', methods=['POST'])
    def wall_display_save_pin(person_id):
        form_pin = request.form.get('pin')
        form_pin_confirm = request.form.get('pin_confirm')
        person = app.get_person(person_id)
        if not person:
            return "Person not found", 404
        if form_pin != form_pin_confirm:
            return jsonify({"error": "Pins do not match"}), 400
        person['pin'] = form_pin
        session['person_id'] = person['id']
        return redirect(f'/wall_display/person/{person_id}')

    @app.route('/wall_display/clear_pin/<int:person_id>', methods=['GET'])
    def wall_display_clear_pin(person_id):
        print('clear_pin', person_id)
        person = app.get_person(person_id)
        print('99 person=', person)
        if not person:
            return "Person not found", 404
        person['pin'] = None
        print('cleared pin for', person['name'])
        return redirect(f'/chores/person/edit?id={person_id}')