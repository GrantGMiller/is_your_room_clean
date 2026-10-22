import datetime
import json
import os
import sys
import time
from typing import Optional, List

import flask_login
from flask import flash, jsonify, redirect, render_template, request, send_file, session
from flask_dictabase import Dictabase
from flask_jobs import JobScheduler
from flask_tools import IsValidEmail, SendEmail_SMTP

import api
import config
import migrate_helper
import repeat_jobs
from app_types import Application
from feature_chores import setup as setup_chores
from feature_chores import ui
from feature_chores.helpers import get_current_user_chores
from feature_chores.models import Person, get_user_local_dt_from_utc
from feature_email import setup as setup_email
from feature_money import setup as setup_money
from feature_nintendo import setup as setup_nintendo
from feature_stickers import setup as setup_stickers, update_archive_sticker_job
from ring import token_endpoints, webhook, setup as ring_setup
from ring.token_endpoints import mask_email
from ring.user import (
    RingUser,
    RingImage,
    delete_stored_images,
    setup as ring_user_setup,
    get_snapshots_for_user_id,
)
from slack import send_slack_message, setup as slack_setup, send_slack_error

if not os.path.exists("images"):
    # this will hold the ring camera screenshots
    os.mkdir("images")

app = Application(getattr(config, 'APP_NAME', '{{ app_name }}'))
app.secret_key = config.SECRET_KEY
app.db = Dictabase(app)
app.jobs = JobScheduler(
    app,
    SERVER_HOST_URL=config.SERVER_HOST_URL,  # only required for linux
    deleteOldJobs=False,  # whether to keep old jobs in the database
)

token_endpoints.setup(app)
webhook.setup(app)
slack_setup(app)
ring_setup(app)
ring_user_setup(app)
api.setup(app)
repeat_jobs.setup(app)
ui.setup(app)
setup_chores(app)
setup_stickers(app)
setup_money(app)
if getattr(config, 'ENABLE_NINTENDO', False):
    setup_nintendo(app)

if getattr(config, 'ENABLE_FEATURE_EMAIL_NOTIFICATIONS', False):
    setup_email(app)

if getattr(config, 'ENABLE_MIGRATE_CHORES', False):
    migrate_helper.setup(app)


@app.route("/")
def index():
    return redirect("/dashboard")


@app.route("/get_snapshot/<device_id>")
def get_snapshot(device_id):
    ring_user: RingUser = app.get_current_user()
    if ring_user:
        img_id = ring_user.get_snapshot(device_id)
        img: RingImage = app.db.FindOne(RingImage, id=img_id)
        if img:
            return send_file(img["image_path"])

    return f"image id={img_id} not found", 404


@app.route("/dashboard")
def dashboard():
    # Ring calls this the "App Homepage"

    ring_user = app.get_current_user()
    # print('77 ring_user=', ring_user)
    if ring_user:
        # if no events have occured since the app was authorized
        # then no snapshots can be grabbed and this app is useless
        # send a flash message to the user to let them know
        devs = ring_user.get_devices()
        devices_without_events = []
        if len(devs) == 0:
            # all devices were unauthorized, clear the stored latest events
            ring_user.Set('latest_events', {})
        # print('devs=', devs)

        for dev in devs:
            if not ring_user.GetItem('latest_events', dev['id'], None):
                latest_event = ring_user.get_latest_event(dev['id'])
                if not latest_event:
                    devices_without_events.append(dev["attributes"]["name"])
                else:
                    print('saving latest event')
                    ring_user.SetItem('latest_events', dev['id'], latest_event['attributes']['start'])

        
        # send_slack_message('len(devs)=', len(devs))
        # send_slack_message('len(devices_without_events=', len(devices_without_events), ', devices_without_events=', devices_without_events)
        
        if devs and len(devices_without_events) == len(devs):
            return render_template(
                "ring/no_events.html",
                ring_user=ring_user,
                device_names=devices_without_events,
            )

        if devices_without_events:
            flash(
                f'No events found yet for {", ".join(devices_without_events)}. '
                'Please wait for a new motion event to occur.',
                'warning',
            )

    if not ring_user:
        # ask for the users email, send them a link
        return render_template("login/email_input.html")

    if ring_user and ring_user.get('access_token', None) is None:
        return render_template("dashboard_unauth.html")

    return render_template("dashboard.html", ring_user=ring_user)


@app.route('/events_exist')
def events_exist():
    ring_user = app.get_current_user()
    print('125 ring_user=', ring_user)
    if not ring_user:
        return 'no user found', 404

    devs = ring_user.get_devices()
    # print('130 devs=', devs)
    devices_without_events = []

    for dev in devs:
        if not ring_user.GetItem('latest_events', dev['id'], None):
            print('get_latest_event')
            latest_event = ring_user.get_latest_event(dev['id'])
            if not latest_event:
                dev_name = dev["attributes"]["name"]
                devices_without_events.append(dev_name)
            else:
                print('saving latest event')
                ring_user.SetItem('latest_events', dev['id'], latest_event['attributes']['start'])

    if not devs or len(devices_without_events) == len(devs):
        return jsonify({'message': f'no events exist for any device. device={devices_without_events}'}), 404

    # at least one device with an event exist
    return f'at least one device with an event exist. devices_without_events={devices_without_events}', 200


@app.route("/send_login_email", methods=["GET", "POST"])
def send_login_email():
    email = request.form.get("email", "")
    if email and IsValidEmail(email):
        session["login_email"] = email.lower()
        user = app.db.NewOrFind(RingUser, email=email.lower())
        if user:
            user.get_new_login_url()
            send_slack_message('sending magic link to', email)

            if sys.platform != 'darwin':
                app.jobs.AddJob(
                    func=SendEmail_SMTP,
                    kwargs={
                        "smtpServerURL": config.SES_SMTP_SERVER,
                        "smtpUsername": config.SES_USERNAME,
                        "smtpPassword": config.SES_PASSWORD,
                        "to": email,
                        "frm": config.ADMINS[0],
                        "subject": "Login with a Magic Link",
                        "body": f"Click this link to login.\r{user.get_last_login_url()}\r\rYour login code is: {user['login_code']}",
                        "html": render_template(
                            "login/email_body_magic_link.html",
                            login_url=user.get_last_login_url(),
                            login_code=user["login_code"],
                        ),
                    },
                    errorCallback=send_slack_error,
                )

            # get the new snapshots cuz the user is prob going to want to see them soon, so lets pre load them
            app.jobs.AddJob(
                func=get_snapshots_for_user_id,
                args=(user['id'],)
            )

        # note, if the user was not found, we dont actually send an email, but dont tell them that
        return render_template(
            "login/email_sent.html",
            email=session["login_email"],
        )

    return render_template("login/email_input.html", message="Invalid Email Address")


@app.route('/logout')
def logout():
    flask_login.logout_user()
    return redirect("/dashboard")


@app.route("/image/<device_id>")
def image_summary(device_id):
    """
    Return the latest summary for device_id
    :param device_id:
    :return:
    """
    img: RingImage = get_latest_ring_image(device_id)
    if not img:
        return 'no image found', 404

    img_dt = datetime.datetime.fromtimestamp((img.get("timestamp_epoch_ms", 0) or 0) / 1000)
    print("140 img_dt=", img_dt, " img=", img)
    if img:
        return jsonify(img.ui_safe())
    else:
        return jsonify(img), 404


def get_latest_ring_image(device_id):
    ring_user = flask_login.current_user
    if ring_user.is_authenticated:
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
        return render_template("email/contact_us.html")

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
    return render_template("legal/privacy.html")


@app.route("/terms")
def terms():
    return render_template("legal/terms.html")


@app.route("/data_flow")
def data_flow():
    return render_template("legal/data_flow.html")


@app.route("/admin")
def admin():
    user = app.get_current_user()
    if not user or user.get("email", None) not in getattr(config, "ADMINS", []):
        return redirect("/dashboard")

    now_ms = time.time() * 1000
    user_rows = {}
    num_devices = 0
    for registered_user in app.db.FindAll(RingUser, _limit=100, _orderBy="timestamp_epoch_ms"):
        email = registered_user.get("email")
        if not email:
            continue

        claimed_at_ms = registered_user.get("ring_user_claimed_at_ms")
        created_age = "Unknown"
        if claimed_at_ms is not None:
            try:
                days_ago = max(
                    0,
                    int((now_ms - float(claimed_at_ms)) // 86_400_000),
                )
                day_label = "day" if days_ago == 1 else "days"
                created_age = f"{days_ago} {day_label} ago"
            except (TypeError, ValueError):
                pass

        masked_email = mask_email(email)

        if masked_email not in user_rows and created_age != "Unknown":
            devs = user.Get('last_devices', []) or []
            # print('devs=', [dev['attributes']['name'] for dev in devs])
            num_devices += len(devs)

        user_rows[masked_email] = created_age

    return render_template(
        "admin.html",
        num_of_users=len(user_rows),
        user_rows=user_rows,
        num_devices=num_devices
    )


@app.route("/admin/unassign_all_chores", methods=["POST"])
def admin_unassign_all_chores():
    user = app.get_current_user()
    if not user or user.get("email", None) not in getattr(config, "ADMINS", []):
        return jsonify({"error": "forbidden"}), 403

    for chore in get_current_user_chores():
        chore['assigned_to'] = None
        chore.refresh_scheduled_job()

    return jsonify({"success": True})


@app.route("/admin/delete_all_chores", methods=["POST"])
def admin_delete_all_chores():
    user = app.get_current_user()
    if not user or user.get("email", None) not in getattr(config, "ADMINS", []):
        return jsonify({"error": "forbidden"}), 403

    chores = get_current_user_chores()
    for chore in chores:
        job_id = chore.get("job_id")
        if job_id is not None:
            job = app.jobs.GetJob(job_id)
            if job:
                job.Delete()
        app.db.Delete(chore)

    return jsonify({"success": True, "deleted": len(chores)})


@app.route("/my_account", methods=["GET", "POST"])
def my_account():
    ring_user = app.get_current_user()
    if not ring_user:
        return redirect("/dashboard")

    email = ring_user.get("email", "")
    local, _, domain = email.partition("@")
    masked_email = f"{local[:4]}*****@{domain[-9:]}"

    if request.method == "POST":
        for key in ['chores', 'email_notifications', 'nintendo']:
            if key in request.form and request.form.get(key, type=bool):
                new_state = True
            else:
                new_state = False
            ring_user.SetItem('enabled_features', key, new_state)

    advanced_features = {
        # 'feature_name': bool(enabled)
    }
    if getattr(config, 'ENABLE_CHORES', False):
        advanced_features['chores'] = ring_user.GetItem('enabled_features', 'chores')

    if getattr(config, 'ENABLE_FEATURE_EMAIL_NOTIFICATIONS', False):
        advanced_features['email_notifications'] = ring_user.GetItem('enabled_features', 'email_notifications')

    if getattr(config, 'ENABLE_NINTENDO', False):
        advanced_features['nintendo'] = ring_user.GetItem('enabled_features', 'nintendo')

    return render_template(
        "my_account.html",
        masked_email=masked_email,
        advanced_features=advanced_features
    )


@app.route("/delete_account", methods=["POST"])
def delete_account():
    ring_user = app.get_current_user()
    if not ring_user:
        return redirect("/dashboard")

    try:
        for u in app.db.FindAll(RingUser, email=ring_user.get("email")):
            app.db.Delete(u)  # just in case

        for img in app.db.FindAll(RingImage, account_id=ring_user.get("account_id", None)):
            app.db.Delete(img)

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
def delete_stored_images_endpoint():
    ring_user = app.get_current_user()
    if not ring_user:
        return redirect("/dashboard")

    try:
        deleted_count = delete_stored_images(app, ring_user.get("id"))
        if deleted_count > 0:
            flash(f"Deleted {deleted_count} stored image(s).", "success")
        else:
            flash("No stored images found to delete.", "info")
    except Exception:
        app.logger.exception("Failed to delete stored images")
        flash(
            "There was a problem deleting your stored images. Please try again or contact support.",
            "danger",
        )

    return redirect("/my_account")


@app.route("/no_events")
def no_events():
    # show this page when there are no ring events
    supress_auto_redirect = (
            request.args.get("supress_auto_redirect", "false").lower() == "true"
    )
    print('supress_auto_redirect=', supress_auto_redirect)
    return render_template(
        "ring/no_events.html",

        supress_auto_redirect=supress_auto_redirect
    )


@app.errorhandler(404)
def page_not_found(e):
    if not 'installHook' in request.path:
        flash('Page not found: ' + request.path, 'danger')

    user: RingUser = app.get_current_user()
    if not user:
        return redirect("/dashboard")
    if user.is_wall_user:
        return redirect("/wall_display")

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

    flash("An error has occurred. The admin has been notified. ", "danger")
    return redirect("/dashboard")


@app.route("/test")
def test():
    return "The time is " + time.asctime()


@app.route('/delete_access_token/<key>')
def delete_access_token(key):
    if key == config.SELFAPIKEY:
        print('request.json=', request.json)
        email = request.json.get('email')
        existing_user: RingUser = app.db.FindOne(RingUser, email=email)
        existing_user['access_token'] = None
        return jsonify(existing_user)
    return 'no user found', 404


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


@app.context_processor
def inject_app_values():
    return {
        'enabled_features': {
            'chores': getattr(config, 'ENABLE_CHORES', False),
            'admins': getattr(config, 'ADMINS', []),
            'email_notifications': getattr(config, 'ENABLE_FEATURE_EMAIL_NOTIFICATIONS', False),
            'nintendo': getattr(config, 'ENABLE_NINTENDO', False),
        },
        'app_name': getattr(config, 'APP_NAME', '{{ app_name }}'),
        'app_url': getattr(config, 'APP_URL', '/'),
        'money_name': getattr(config, 'MONEY_NAME', 'ChoreBucks'),
    }


@app.route('/favicon.ico')
def favicon():
    return redirect("/static/favicon.ico")


def get_current_user() -> Optional[RingUser]:
    with app.app_context():
        # return user object if logged in, else return None

        user = flask_login.current_user
        # print('392 user=', user)
        if user and user.is_anonymous:
            return None

        return user


app.get_current_user = get_current_user


def get_person(person_id) -> Optional[Person]:
    with app.app_context():
        user = get_current_user().get_ring_user()
        person = app.db.FindOne(Person, id=person_id, owner_id=user['id'])
        return person


app.get_person = get_person


def get_user(user_id) -> Optional[RingUser]:
    with app.app_context():
        user = app.db.FindOne(RingUser, id=user_id)
        return user


app.get_user = get_user


def get_all_user_persons() -> List[Person]:
    with app.app_context():
        user = get_current_user().get_ring_user()
        persons = app.db.FindAll(Person, owner_id=user['id'])
        return persons


app.get_all_user_persons = get_all_user_persons

app.get_user_local_dt_from_utc = get_user_local_dt_from_utc

update_archive_sticker_job()

if __name__ == "__main__":
    app.run(port=3888, debug=True)
