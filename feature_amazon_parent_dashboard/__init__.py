from urllib.parse import unquote

from amazon_parent_dashboard import ParentDashboard
from flask import render_template, flash, redirect, request, jsonify

from app_types import Application


def setup(a: Application):
    global app
    app = a

    @app.route('/amazon', methods=['GET', 'POST'])
    def amazon_endpoint():
        user = app.get_current_user()
        if not user:
            flash('Unrecognized user', 'danger')
            return redirect('/')

        pd = get_parent_dashboard()

        if request.method == 'POST':

            cookie_string = str(request.form.get('cookie_string'))

            if cookie_string:
                user.SetItem('amazon', 'cookie_string', str(unquote(cookie_string)))
                pd = get_parent_dashboard()

        if not pd:
            return render_template(
                "amazon/no_auth.html",

            )

        return render_template(
            'amazon/assign_devices.html',
            parent_dashboard=pd,
            persons=list(app.get_all_user_persons()),
            assigned_devices=user.GetItem('amazon', 'assigned_devices', {}) or {},
            user=user,
        )

    @app.route('/amazon/assign', methods=['POST'])
    def amazon_assign_device():
        person_id = request.form.get('person_id', type=int)
        amazon_child_name = request.form.get('amazon_child_name')

        user = app.get_current_user()
        if not user:
            return jsonify({'error': 'Unrecognized user', 'category': 'danger'}), 404

        if person_id is None:
            return jsonify({'error': 'Person ID not provided', 'category': 'danger'}), 404

        person = app.get_person(person_id)
        if not person:
            return jsonify({'error': 'Person not found', 'category': 'danger'}), 404

        pd = get_parent_dashboard()
        if not pd:
            return jsonify({'error': 'ParentDashboard not configured', 'category': 'danger'}), 404

        data = user.GetItem('amazon', 'assigned_devices', {}) or {}
        data[str(person_id)] = amazon_child_name
        user.SetItem('amazon', 'assigned_devices', data)

        return jsonify({
            'message': f'Assigned Amazon Child {amazon_child_name} for person {person["name"]}',
            'user': user.ui_safe()
        })

    @app.route('/amazon/unassign/<int:person_id>')
    def amazon_unassign_device(person_id):
        user = app.get_current_user()
        if not user:
            return jsonify({'error': 'Unrecognized user', 'category': 'danger'}), 404

        data = user.GetItem('amazon', 'assigned_devices', {}) or {}
        if str(person_id) in data:
            del data[str(person_id)]
            user.SetItem('amazon', 'assigned_devices', data)
            return jsonify({'message': f'Unassigned device for person {person_id}'})
        else:
            return jsonify({'error': 'No device assigned to this person', 'category': 'danger'}), 404

    @app.route('/amazon/add_bonus_time/<int:person_id>/<int:minutes>', methods=['GET', 'POST'])
    def amazon_add_bonus_time(person_id, minutes):
        user = app.get_current_user()
        if not user:
            return jsonify({'error': 'Unrecognized user', 'category': 'danger'}), 404
        user = user.get_ring_user()
        person = app.get_person(person_id)
        if not person:
            return jsonify({'error': 'Person not found', 'category': 'danger'}), 404

        if minutes > person.get('nintendo_time', 0):
            return jsonify({'error': 'Not enough Nintendo time available', 'category': 'danger'}), 404

        pd = get_parent_dashboard()
        if not pd:
            return jsonify({'error': 'FamilyLink not configured', 'category': 'danger'}), 404

        # Assuming FamilyLinkWithBonusTime has a method to add bonus time

        data = user.GetItem('amazon', 'assigned_devices', {}) or {}
        if str(person_id) not in data:
            return jsonify({'error': 'No device assigned to this person', 'category': 'danger'}), 404

        pd.add_bonus_time(
            child_name=data[str(person_id)],
            minutes=minutes,
        )

        if not request.args.get('dont_subtract_nintendo_time', type=bool):
            person['nintendo_time'] = person.get('nintendo_time', 0) - minutes

        return jsonify({'message': f'Added amazon bonus time {minutes} minutes for person {person["name"]}'})

    @app.route('/amazon/logout')
    def amazon_logout():
        user = app.get_current_user()
        user.SetItem('amazon', 'cookie_string', None)
        flash('Logged out of Parent Dashboard', 'success')
        return redirect('/amazon')
        return jsonify(user.ui_safe())


def get_parent_dashboard():
    with app.app_context():
        user = app.get_current_user()
        if not user:
            return None
        user = user.get_ring_user()

        cookie_string = user.GetItem('amazon', 'cookie_string', None)
        if not cookie_string:
            return None

        if cookie_string:
            return ParentDashboard(
                cookies=cookie_string,
            )

        return None
