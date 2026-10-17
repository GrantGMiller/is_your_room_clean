from flask import Flask, redirect, session, jsonify, render_template, request

from feature_chores.helpers import get_current_user_person


def setup(a: Flask):
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
        current_cleanliness = app.get_current_user().get_ring_user().Get('last_clean_score', {}) or {}
        minimum_cleanliness=data.get('minimum_cleanliness', {}) or {}

        return render_template(
            'chores/wall_display/person_page.html',
            person=person,
            rooms_to_clean=rooms_to_clean,
            current_cleanliness=current_cleanliness,
            minimum_cleanliness=minimum_cleanliness,
        )

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