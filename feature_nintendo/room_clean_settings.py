from flask import Flask, jsonify, render_template, request

from ring.user import get_current_user


def setup(a:Flask):
    global app
    app = a

    @app.route('/nintendo/settings/<device_name>', methods=['GET', 'POST'])
    def nintendo_settings(device_name):
        user = get_current_user()
        if not user:
            return "Unauthorized", 401

        key = f'nintendo_settings_{device_name}'

        if request.method == 'POST':
            for form_key in [
                'room_names_to_clean',
                'minimum_cleanliness'
            ]:
                form_value = request.json.get(form_key)
                user.SetItem(key, form_key, form_value)

            return jsonify(user.Get(key, {}))
      
        person_data = user.Get(
            key,
            {}
            )

        return render_template(
            'nintendo/settings.html', person_data=person_data,
            all_room_names = user.get_devices_names(),
            device_name = device_name,
        )