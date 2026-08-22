import os
import time

from flask import render_template, session, Flask, request
from flask_dictabase import Dictabase
from flask_jobs import JobScheduler
from flask_tools import IsValidEmail, SendEmail_SMTP

import config
import ring_token_endpoints
import ring_webhook_helper
from ring_user import RingUser

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


@app.route('/')
def index():
    return 'Welcome to IsYourRoomClean'


@app.route('/dashboard')
def dashboard():
    # Ring calls this the "App Homepage"
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
            app.jobs.AddJob(
                func=SendEmail_SMTP,
                kwargs={
                    'smtpServerURL': config.SES_SMTP_SERVER,
                    'smtpUsername ': config.SES_USERNAME,
                    'smtpPassword': config.SES_PASSWORD,
                    'to': email,
                    'frm': 'admin@domainservices.biz'
                }
            )

        # note, if the user was not found, we dont actually send an email, but dont tell them that
        return render_template(
            'email_sent.html',
            email=email,
        )


@app.route('/test')
def test():
    return 'The time is ' + time.asctime()


if __name__ == '__main__':
    app.run(port=3888, debug=True)
