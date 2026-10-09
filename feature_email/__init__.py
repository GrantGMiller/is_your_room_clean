import datetime

from flask import Flask, abort, flash, jsonify, redirect, render_template, request

import config
import ring_user
from feature_email.jobs import (
    get_summary_data,
    render_daily_summary,
    update_email_job,
    setup as setup_email_jobs,
)

SETTINGS_KEY = 'email_notification_settings'


def setup(app: Flask):
    setup_email_jobs(app)

    @app.route('/email', methods=['GET', 'POST'])
    def email():
        user = ring_user.get_current_user()
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

    @app.route('/email/preview_daily_summary')
    def preview_daily_summary():
        user = ring_user.get_current_user()
        if not user or user.get('email') not in getattr(config, 'ADMINS', []):
            abort(403)

        data = get_summary_data(user['id'])
        return render_daily_summary(data)

    @app.route('/email/preview_room_clean')
    def preview_room_clean():
        current_user = ring_user.get_current_user()
        if not current_user or current_user.get('email') not in getattr(config, 'ADMINS', []):
            abort(403)

        data = current_user.Get('last_clean_score', {})
        return render_room_clean_email(data)


def render_room_clean_email(data):
    return render_template(
        'email/room_clean_email.html',
        data=data,
        app_url=config.SERVER_HOST_URL.rstrip('/'),
    )
