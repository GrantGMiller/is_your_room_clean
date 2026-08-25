import datetime
import json
import os
import sys
import time

from flask import render_template, session, Flask, request, redirect, send_file, jsonify, flash
from flask_dictabase import Dictabase
from flask_jobs import JobScheduler
from flask_tools import IsValidEmail, SendEmail_SMTP

import config
import ring_token_endpoints
import ring_webhook_helper
from ai_cleanliness import evaluate_cleanliness
from ring_user import RingUser, RingImage
from slack import send_slack_message, setup as slack_setup

if not os.path.exists('images'):
    # this will hold the ring camera screenshots
    os.mkdir('images')

app = Flask('Is Your Room Clean')
app.secret_key = config.SECRET_KEY
app.db = Dictabase(app)
app.jobs = JobScheduler(
    app,
    SERVER_HOST_URL=config.SERVER_HOST_URL,  # only required for linux
    deleteOldJobs=False,  # whether to keep old jobs in the database
)

ring_token_endpoints.setup(app)
ring_webhook_helper.setup(app)
slack_setup(app)

with app.app_context():
    if sys.platform == 'darwin' and datetime.datetime.now() < datetime.datetime.now().replace(
            year=2026,
            month=8,
            day=25
    ):
        # create a fake user to test with
        ring_user: RingUser = app.db.NewOrFind(
            RingUser,
            account_id='fake',
            email='grant@grant-miller.com',
        )
        print('magic link=', ring_user.get_new_login_url())
        ring_user['expires_at'] = (datetime.datetime.now() + datetime.timedelta(days=10)).timestamp()
        ring_user['access_token'] = 'fake'
        ring_user['refresh_token'] = 'fake'
        ring_user['status'] = 'confirmed'

        app.db.NewOrFind(
            RingImage,
            account_id='fake',
            device_id='1',
            image_path=r'images/13bc15d3-985f-440e-b6a9-e8d159c0fc75.jpg',
            cleanliness=99,
            summary='fake summary'
        )
        app.db.NewOrFind(
            RingImage,
            account_id='fake',
            device_id='2',
            image_path=r'images/13bc15d3-985f-440e-b6a9-e8d159c0fc75.jpg',
            cleanliness=1,
            summary='fake summary2'
        )


@app.route('/')
def index():
    return redirect('/dashboard')


@app.route('/dashboard')
def dashboard():
    # Ring calls this the "App Homepage"

    if request.args.get('key', None) == 'fake' and datetime.datetime.now() < datetime.datetime.now().replace(
            year=2026,
            month=8,
            day=25
    ):
        ring_user = app.db.FindOne(RingUser, account_id='fake')
        if ring_user:
            session['account_id'] = ring_user['account_id']
    else:
        ring_user = app.db.FindOne(RingUser, account_id=session.get('account_id', None))

    if not ring_user:
        # send_slack_message(
        #     'form=', request.form,
        #     ', args=', request.args,
        #     ', headers=', request.headers
        #
        # )
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
    if not image:
        return 'image not found', 404

    if image.get('cleanliness', None) is None:
        app.jobs.AddJob(
            func=score_cleanliness,
            kwargs={
                'image_id': image_id,
            },
            errorCallback=send_slack_error
        )

    return send_file(
        image['image_path'],
        mimetype='image/jpeg',
    )


@app.route('/image/<image_id>/summary')
def image_summary(image_id):
    img: RingImage = app.db.FindOne(
        RingImage,
        id=image_id,
        account_id=session.get('account_id', None),
    )
    if img and img.get('summary', None) is not None:
        return img.ui_safe()

    if img.get('isError', False):
        return jsonify(img), 500

    return 'summary not ready', 404


def score_cleanliness(image_id):
    with app.app_context():
        image = app.db.FindOne(
            RingImage,
            id=image_id,
        )
        if image and image.get('cleanliness', None) is None and not image.get('scoring_in_progress', False):
            image['scoring_in_progress'] = True
            with open(
                    image['image_path'],
                    'rb'
            ) as f:
                image_bytes = f.read()

            try:
                res = evaluate_cleanliness(image_bytes=image_bytes)
                image['cleanliness'] = res['cleanliness']
                image['summary'] = res['summary']
            except Exception as e:
                image['isError'] = True
                image['error'] = str(e)
                raise e  # raise so that the error is sent via slack


@app.route('/job/<job_id>')
def job(job_id):
    if not datetime.datetime.now() < datetime.datetime.now().replace(
            year=2026,
            month=8,
            day=24,
    ):
        return 'too late'

    job = app.jobs.GetJob(job_id)
    ret = {}
    for key, value in job.items():
        ret[key] = str(value)

    return jsonify(ret)


@app.route('/api-key')
def apikey():
    ring_user = app.db.FindOne(RingUser, account_id=session.get('account_id', None))
    if not ring_user:
        flash('unknown user', 'warning')
        redirect('/dashboard')

    return render_template(
        'api-key.html',
        api_key=user.api_key,
        new_api_key=new_api_key  # pass if this is a new key
    )


@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'GET':
        return render_template('contact_us.html')

    elif request.method == 'POST':
        flash('Thank you. Your message has been sent to our support staff.', 'success')
        message = json.dumps(request.form, indent=4, )
        print('message=', message)
        app.jobs.AddJob(
            func=SendEmail_SMTP,
            kwargs={
                'smtpServerURL': config.SES_SMTP_SERVER,
                'smtpUsername': config.SES_USERNAME,
                'smtpPassword': config.SES_PASSWORD,
                'to': config.ADMINS[0],
                'frm': config.ADMINS[0],
                'subject': 'A user has requested help.',
                'body': message,
            },
            errorCallback=send_slack_error
        )
        send_slack_message(message)

    return redirect('/dashboard')


@app.route('/privacy')
def privacy():
    return render_template('privacy.html')


@app.route('/terms')
def terms():
    return render_template('terms.html')


@app.errorhandler(Exception)
def not_found_error(error):
    flash('An error has occurred. This has been sent to our support staff.', 'danger')
    send_slack_error(error)
    return redirect('/dashboard')


@app.route('/test')
def test():
    return 'The time is ' + time.asctime()


def send_slack_error(job):
    send_slack_message('Error:', job)


if __name__ == '__main__':
    app.run(port=3888, debug=True)
