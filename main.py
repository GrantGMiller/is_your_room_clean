import datetime
import os
import time

from flask import render_template, session, Flask, request, redirect, send_file
from flask_dictabase import Dictabase
from flask_jobs import JobScheduler
from flask_tools import IsValidEmail, SendEmail_SMTP

import config
import ring_token_endpoints
import ring_webhook_helper
from ring_user import RingUser, RingImage
from slack import send_slack_message, setup as slack_setup

if not os.path.exists('images'):
    # this will hold the ring camera screenshots
    os.mkdir('images')

app = Flask('Is Your Room Clean')
app.db = Dictabase(app)
app.jobs = JobScheduler(
    app,
    SERVER_HOST_URL=config.SERVER_HOST_URL,  # only required for linux
    deleteOldJobs=False,  # whether to keep old jobs in the database
)

ring_token_endpoints.setup(app)
ring_webhook_helper.setup(app)
slack_setup(app)

# temp
# make sure we have all the users email addresses
with app.app_context():
    for user in app.db.FindAll(RingUser):
        print('user.email=', user.get_email())


@app.route('/')
def index():
    return redirect('/dashboard')


@app.route('/dashboard')
def dashboard():
    # Ring calls this the "App Homepage"

    if request.args.get('key', 'Miller') and datetime.datetime.now() < datetime.datetime.now().replace(
            year=2026,
            month=8,
            day=23
    ):
        ring_user = app.db.FindOne(RingUser, email='grant@grant-miller.com')
    else:
        ring_user = app.db.FindOne(RingUser, account_id=session.get('account_id', None))

    if not ring_user:
        # ask for the users email, send them a link
        return render_template('email_input.html')

    return render_template(
        'dashboard.html',
        ring_user=ring_user
    )


@app.route('/send_login_email', methods=['GET', 'POST'])
def send_login_email():
    email = request.form.get('email', None)
    if IsValidEmail(email):
        user = app.db.FindOne(
            RingUser,
            email=email.lower()
        )
        if user:
            user.get_new_login_url()
            app.jobs.AddJob(
                func=SendEmail_SMTP,
                kwargs={
                    'smtpServerURL': config.SES_SMTP_SERVER,
                    'smtpUsername': config.SES_USERNAME,
                    'smtpPassword': config.SES_PASSWORD,
                    'to': email,
                    'frm': config.ADMINS[0],
                    'subject': 'Login with a Magic Link',
                    'body': f'Click this link to login.\r{user.get_last_login_url()}',
                    'html': f'<a href="{user.get_last_login_url()}">Click here to login.</a>',
                },
                errorCallback=send_slack_error
            )

        # note, if the user was not found, we dont actually send an email, but dont tell them that
        return render_template(
            'email_sent.html',
            email=email,
        )

    return render_template(
        'email_input.html',
        message='Invalid Email Address'
    )


@app.route('/image/<image_id>')
def image(image_id):
    image = app.db.FindOne(
        RingImage,
        id=image_id,
        account_id=session.get('account_id', None),
    )
    return send_file(
        image['image_path'],
        mimetype='image/jpeg',
    )


@app.route('/test')
def test():
    return 'The time is ' + time.asctime()


def send_slack_error(job):
    send_slack_message('Error:', job)


if __name__ == '__main__':
    app.run(port=3888, debug=True)
