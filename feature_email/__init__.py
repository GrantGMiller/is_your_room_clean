import datetime

from flask import Flask, flash, redirect, render_template, request

from ring_user import get_current_user


def setup(app:Flask):
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
        settings_key = 'email_notification_settings'

        if request.method == 'POST':
            for setting_name in setting_names:
                user.SetItem(
                    settings_key,
                    setting_name,
                    request.form.get(setting_name) == 'on',
                )

            summary_time = request.form.get('daily_chore_summary_time', '')
            try:
                datetime.datetime.strptime(summary_time, '%H:%M')
            except ValueError:
                flash('Enter a valid time for the daily chore summary.', 'danger')
            else:
                user.SetItem(settings_key, 'daily_chore_summary_time', summary_time)
                flash('Email notification settings saved.', 'success')

            return redirect('/email')

        settings = {
            'email_when_all_rooms_clean': user.GetItem(
                settings_key, 'email_when_all_rooms_clean', False
            ),
            'email_when_rooms_dirty': user.GetItem(
                settings_key, 'email_when_rooms_dirty', False
            ),
            'daily_chore_summary': user.GetItem(
                settings_key, 'daily_chore_summary', False
            ),
            'daily_chore_summary_time': user.GetItem(
                settings_key, 'daily_chore_summary_time', '08:00'
            ),
        }
        return render_template('email/email.html', user=user, settings=settings)