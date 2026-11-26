import datetime
import re
import sys
from html.parser import HTMLParser
from typing import List

from flask import Flask, abort, flash, jsonify, redirect, render_template, request
from flask_tools import SendEmail_SMTP

from app_types import Application
import config
from ring import user as ring_user
from feature_email.jobs import (
    get_summary_data,
    render_daily_summary,
    update_email_job,
    setup as setup_email_jobs, send_daily_email_summary,
)
from slack import send_slack_message, send_slack_error

SETTINGS_KEY = 'email_notification_settings'


class _EmailTextParser(HTMLParser):
    _BLOCK_TAGS = {
        'address', 'article', 'blockquote', 'br', 'dd', 'div', 'dl', 'dt',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'li', 'ol', 'p',
        'section', 'table', 'tr', 'ul',
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skipped_tags = []
        self.links = []
        self.list_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'head', 'style', 'script', 'title'}:
            self.skipped_tags.append(tag)
            return
        if self.skipped_tags:
            return

        if tag in {'ul', 'ol'}:
            self.list_depth += 1
        if tag == 'li':
            self._append_boundary()
            self.parts.append('  ' * max(0, self.list_depth - 1) + '- ')
        elif tag in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}:
            self._append_boundary()
            self.parts.append('#' * int(tag[1]) + ' ')
        elif tag in self._BLOCK_TAGS:
            self._append_boundary()

        if tag == 'a':
            href = dict(attrs).get('href')
            self.links.append((href, len(self.parts)))

    def handle_endtag(self, tag):
        if self.skipped_tags:
            if tag == self.skipped_tags[-1]:
                self.skipped_tags.pop()
            return

        if tag == 'a' and self.links:
            href, start_index = self.links.pop()
            link_text = ''.join(self.parts[start_index:]).strip()
            if href and href not in link_text:
                self.parts.append(f' ({href})')
        elif tag in {'ul', 'ol'}:
            self.list_depth = max(0, self.list_depth - 1)

        if tag in self._BLOCK_TAGS:
            self._append_boundary()

    def handle_data(self, data):
        if not self.skipped_tags:
            self.parts.append(data)

    def _append_boundary(self):
        if self.parts and not self.parts[-1].endswith('\n'):
            self.parts.append('\n')

    def get_text(self):
        text = ''.join(self.parts)
        lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in text.splitlines()]
        text = '\n'.join(line for line in lines if line)
        return re.sub(r'\n{3,}', '\n\n', text).strip()


def html_email_to_text(html):
    parser = _EmailTextParser()
    parser.feed(html)
    parser.close()
    return parser.get_text()


app: Application

def setup(a: Application):
    global app
    app = a
    setup_email_jobs(app)

    @app.route('/email', methods=['GET', 'POST'])
    def email():
        user = app.get_current_user()
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
        user = app.get_current_user()
        if not user or user.get('email') not in getattr(config, 'ADMINS', []):
            abort(403)

        data = get_summary_data(user['id'])
        return render_daily_summary(data)

    @app.route('/email/preview_room_clean')
    def preview_room_clean():
        current_user = app.get_current_user()
        if not current_user or current_user.get('email') not in getattr(config, 'ADMINS', []):
            abort(403)

        data = current_user.Get('last_clean_score', {})
        return render_room_clean_email(data)

    @app.route('/email/send_template_test')
    def send_template():
        current_user = app.get_current_user()
        if not current_user or current_user.get('email') not in getattr(config, 'ADMINS', []):
            abort(403)

        template_name = request.args.get('template_name')
        subject = request.args.get('subject')
        frm_email = request.args.get('frm_email') or config.ADMINS[0]
        admin_emails = getattr(config, 'ADMINS', [])
        if not template_name or frm_email not in admin_emails:
            abort(400)

        users = list(get_test_subscribed_users())
        send_email_template_to_list(
            users, template_name, frm_email=frm_email, subject=subject
        )
        return jsonify({'success': True})

    @app.route('/email/send_template_live', methods=['POST'])
    def send_template_live():
        current_user = app.get_current_user()
        if not current_user or current_user.get('email') not in getattr(config, 'ADMINS', []):
            abort(403)

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({'success': False, 'error': 'Expected a JSON object.'}), 400

        template_name = payload.get('template_name')
        subject = payload.get('subject')
        frm_email = payload.get('frm_email') or config.ADMINS[0]
        allowed_templates = {
            template[6:-5]
            for template in app.jinja_env.list_templates()
            if template.startswith('email/') and template.endswith('.html')
        }
        admin_emails = getattr(config, 'ADMINS', [])
        if template_name not in allowed_templates or frm_email not in admin_emails:
            return jsonify({'success': False, 'error': 'Invalid template or sender.'}), 400

        users = list(get_subscribed_users())
        send_email_template_to_list(
            users, template_name, frm_email=frm_email, subject=subject
        )
        return jsonify({'success': True, 'recipient_count': len(users)})


def render_room_clean_email(data):
    send_slack_message('render room clean email data=', data)
    return render_template(
        'email/room_clean_email.html',
        data=data,
        app_url=config.SERVER_HOST_URL.rstrip('/'),
    )

def get_subscribed_users():
    block_list = ['amazon', 'ring.com']
    with app.app_context():
        for user in app.db.FindAll(ring_user.RingUser):
            if not user.get('is_unsubscribed', False) and \
                user['email'] and \
                    not any(blocked_domain in user['email'] for blocked_domain in block_list):
                yield user

def get_test_subscribed_users():
    with app.app_context():
        for email in config.ADMINS:
            user = app.db.NewOrFind(ring_user.RingUser, email=email)
            yield user


def send_email_template_to_list(
    users, template_name: str, frm_email=config.ADMINS[0], subject=None
):
    with app.app_context():
        email_subject = (
            subject.strip()
            if isinstance(subject, str) and subject.strip()
            else template_name.capitalize()
        )
        # Implement the logic to send an email using the specified template
        # This is a placeholder implementation
        send_slack_message(f'Sending email template "{template_name}" to {len(users)} users from {frm_email}')
        for user in users:
            if sys.platform != 'darwin':
                html_body = render_template(
                    f"email/{template_name}.html",
                    unsubscribe_link=user.get_unsubscribe_url(),
                )
                app.jobs.AddJob(
                    func=SendEmail_SMTP,
                    kwargs={
                        "smtpServerURL": config.SES_SMTP_SERVER,
                        "smtpUsername": config.SES_USERNAME,
                        "smtpPassword": config.SES_PASSWORD,
                        "to": user['email'],
                        "frm": frm_email,
                        "subject": email_subject,
                        "body": html_email_to_text(html_body),
                        "html": html_body
                    },
                    errorCallback=send_slack_error,
                )
            else:
                send_slack_message(
                    f'Sending email template "{template_name}" to {user["email"]}'
                )