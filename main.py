import datetime
import json
import os
import sys
import time

import flask_login
from flask import render_template, Flask, request, redirect, send_file, jsonify, flash
from flask_dictabase import Dictabase
from flask_jobs import JobScheduler
from flask_tools import IsValidEmail, SendEmail_SMTP

import api
import chores_ui
import config
import daily_jobs
import ring_token_endpoints
import ring_webhook
from ring_user import RingUser, RingImage, setup as ring_user_setup, get_current_user
from slack import send_slack_message, setup as slack_setup, send_slack_error

if not os.path.exists("images"):
    # this will hold the ring camera screenshots
    os.mkdir("images")

app = Flask("Is Your Room Clean")
app.secret_key = config.SECRET_KEY
app.db = Dictabase(app)
app.jobs = JobScheduler(
    app,
    SERVER_HOST_URL=config.SERVER_HOST_URL,  # only required for linux
    deleteOldJobs=False,  # whether to keep old jobs in the database
)

ring_token_endpoints.setup(app)
ring_webhook.setup(app)
slack_setup(app)
ring_user_setup(app)
api.setup(app)
daily_jobs.setup(app)
chores_ui.setup(app)


@app.route("/")
def index():
    return redirect("/dashboard")


@app.route("/get_snapshot/<device_id>")
def get_snapshot(device_id):
    ring_user: RingUser = get_current_user()
    if ring_user:
        img_id = ring_user.get_snapshot(device_id)
        img: RingImage = app.db.FindOne(RingImage, id=img_id)
        if img:
            return send_file(img["image_path"])

    return "image not found", 404


@app.route("/dashboard")
def dashboard():
    # Ring calls this the "App Homepage"

    if request.args.get(
            "key", None
    ) == "force" and datetime.datetime.now() < datetime.datetime.now().replace(
        year=2026, month=8, day=25
    ):
        ring_user = app.db.FindOne(RingUser, email="grant@grant-miller.com")
        flask_login.login_user(ring_user, remember=True)
    else:
        ring_user = get_current_user()

    # app.logger.error("111 ring_user=" + str(ring_user))

    if not ring_user:
        # send_slack_message(
        #     'form=', request.form,
        #     ', args=', request.args,
        #     ', headers=', request.headers
        #
        # )
        # ask for the users email, send them a link
        return render_template("email_input.html")

    return render_template("dashboard.html", ring_user=ring_user)


@app.route("/send_login_email", methods=["GET", "POST"])
def send_login_email():
    email = request.form.get("email", None)
    if IsValidEmail(email):
        user = app.db.FindOne(RingUser, email=email.lower())
        if user:
            user.get_new_login_url()
            send_slack_message('sending magic link to', email, user.get_last_login_url())
            app.jobs.AddJob(
                func=SendEmail_SMTP,
                kwargs={
                    "smtpServerURL": config.SES_SMTP_SERVER,
                    "smtpUsername": config.SES_USERNAME,
                    "smtpPassword": config.SES_PASSWORD,
                    "to": email,
                    "frm": config.ADMINS[0],
                    "subject": "Login with a Magic Link",
                    "body": f"Click this link to login.\r{user.get_last_login_url()}",
                    "html": render_template(
                        "email_body_magic_link.html",
                        login_url=user.get_last_login_url(),
                    ),
                },
                errorCallback=send_slack_error,
            )

        # note, if the user was not found, we dont actually send an email, but dont tell them that
        return render_template(
            "email_sent.html",
            email=email,
        )

    return render_template("email_input.html", message="Invalid Email Address")


@app.route("/image/<device_id>")
def image_summary(device_id):
    """
    Return the latest summary for device_id
    :param device_id:
    :return:
    """
    img: RingImage = get_latest_ring_image(device_id)
    img_dt = datetime.datetime.fromtimestamp(img.get("timestamp_epoch_ms", 0) / 1000)
    print("140 img_dt=", img_dt, " img=", img)
    if img:
        return jsonify(img.ui_safe())
    else:
        return jsonify(img), 404


def get_latest_ring_image(device_id):
    ring_user = flask_login.current_user
    if ring_user:
        images = list(
            app.db.FindAll(
                RingImage,
                account_id=ring_user.get("account_id", None),
                device_id=device_id,
                _limit=1,
                _reverse=True,
                _orderBy="timestamp_epoch_ms",
            )
        )
        if images:
            return images[0]
        return None


@app.route("/job/<job_id>")
def job(job_id):
    if not datetime.datetime.now() < datetime.datetime.now().replace(
            year=2026,
            month=8,
            day=24,
    ):
        return "too late"

    job = app.jobs.GetJob(job_id)
    ret = {}
    for key, value in job.items():
        ret[key] = str(value)

    return jsonify(ret)


@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "GET":
        return render_template("contact_us.html")

    elif request.method == "POST":
        flash("Thank you. Your message has been sent to our support staff.", "success")
        message = json.dumps(
            request.form,
            indent=4,
        )
        print("message=", message)
        app.jobs.AddJob(
            func=SendEmail_SMTP,
            kwargs={
                "smtpServerURL": config.SES_SMTP_SERVER,
                "smtpUsername": config.SES_USERNAME,
                "smtpPassword": config.SES_PASSWORD,
                "to": config.ADMINS[0],
                "frm": config.ADMINS[0],
                "subject": "A user has requested help.",
                "body": message,
            },
            errorCallback=send_slack_error,
        )
        send_slack_message(message)

    return redirect("/dashboard")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/data_flow")
def data_flow():
    return render_template("data_flow.html")


@app.route("/my_account", methods=["GET"])
def my_account():
    ring_user = get_current_user()
    if not ring_user:
        return redirect("/dashboard")
    return render_template("my_account.html")


@app.route("/delete_account", methods=["POST"])
def delete_account():
    ring_user = get_current_user()
    if not ring_user:
        return redirect("/dashboard")

    try:
        app.db.Delete(ring_user)
        flask_login.logout_user()
        flash("Your account has been deleted.", "success")
    except Exception:
        app.logger.exception("Failed to delete account")
        flash(
            "There was a problem deleting your account. Please try again or contact support.",
            "danger",
        )

    return redirect("/dashboard")


@app.route("/delete_stored_images", methods=["POST"])
def delete_stored_images():
    ring_user = get_current_user()
    if not ring_user:
        return redirect("/dashboard")

    try:
        image_records = list(
            app.db.FindAll(RingImage, account_id=ring_user.get("account_id", None))
        )
        deleted_count = 0
        for image in image_records:
            image_path = image.get("image_path")
            try:
                if image_path and os.path.exists(image_path):
                    os.remove(image_path)
            except Exception:
                app.logger.exception("Failed to delete image file")
            app.db.Delete(image)
            deleted_count += 1

        flash(f"Deleted {deleted_count} stored image(s).", "success")
    except Exception:
        app.logger.exception("Failed to delete stored images")
        flash(
            "There was a problem deleting your stored images. Please try again or contact support.",
            "danger",
        )

    return redirect("/my_account")


@app.route("/tutorial")
def tutorial():
    return render_template("tutorial.html")


@app.errorhandler(404)
def page_not_found(e):
    flash('Page not found: ' + request.path, 'danger')
    return redirect("/dashboard")


@app.errorhandler(500)
def handle_error(e):
    msg = str(e)
    if not sys.platform == "darwin":
        try:
            with open(f'gerror.log', mode="rt") as file:
                msg += "\r\n\r\n****GUNICORN ERROR LOG****\r\n" + file.read()
        except Exception as e2:
            msg += str(e2)

        send_slack_message("HTTP Error" + msg)

    flash("An error has occurred. The admin has been notified. " "danger")
    return redirect("/dashboard")


@app.route("/test")
def test():
    return "The time is " + time.asctime()


@app.route("/get_grant")
def get_grant():
    ring_user = get_current_user()
    return jsonify(ring_user)


@app.route('/create_user/<key>')
def create_user(key):
    # migrate users from beta to prod
    if key == config.SELFAPIKEY:
        user_data: RingUser = request.json
        print('user_data=', user_data)
        email = user_data.get('email', None)
        existing_user: RingUser = app.db.FindOne(RingUser, email=email)
        if not existing_user and email:
            user_data.pop('id', None)
            app.db.New(
                RingUser,
                **user_data,
            )
            return f'added user {email}'
        else:
            return f'user already exist for {email}'
    return 'nope'


@app.route('/get_user/<key>')
def get_user(key):
    if key == config.SELFAPIKEY:
        print('request.json=', request.json)
        email = request.json.get('email')
        existing_user: RingUser = app.db.FindOne(RingUser, email=email)
        return jsonify(existing_user)
    return jsonify({'error': 'nope'})


if __name__ == "__main__":
    app.run(port=3888, debug=True)
