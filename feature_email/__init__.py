import datetime

from flask import Flask, flash, jsonify, redirect, render_template, request

from feature_email.jobs import update_email_job, setup as setup_email_jobs
from ring_user import get_current_user

SETTINGS_KEY = 'email_notification_settings'


def setup(app: Flask):
    setup_email_jobs(app)

    @app.route('/email', methods=['GET', 'POST'])
    def email():
        user = get_current_user()
        if not user:
            return redirect('/dashboard')

        setting_names = (
            'email_when_all_rooms_clean',
            'email_when_rooms_dirty',
            'daily_chore_summary',
        )

        if request.method == 'POST':
            summary_time = request.form.get('daily_chore_summary_time', '')
            try:
                datetime.datetime.strptime(summary_time, '%H:%M')
            except ValueError:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'success': False, 'error': 'Invalid summary time.'}), 400
                flash('Enter a valid time for the daily chore summary.', 'danger')
                return redirect('/email')

            for setting_name in setting_names:
                user.SetItem(
                    SETTINGS_KEY,
                    setting_name,
                    request.form.get(setting_name) == 'on',
                )

            user.SetItem(SETTINGS_KEY, 'daily_chore_summary_time', summary_time)

            update_email_job(user['id'])

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': True})

            return redirect('/email')

        settings = {
            'email_when_all_rooms_clean': user.GetItem(
                SETTINGS_KEY, 'email_when_all_rooms_clean', False
            ),
            'email_when_rooms_dirty': user.GetItem(
                SETTINGS_KEY, 'email_when_rooms_dirty', False
            ),
            'daily_chore_summary': user.GetItem(
                SETTINGS_KEY, 'daily_chore_summary', False
            ),
            'daily_chore_summary_time': user.GetItem(
                SETTINGS_KEY, 'daily_chore_summary_time', '08:00'
            ),
        }
        return render_template('email/email.html', user=user, settings=settings)
