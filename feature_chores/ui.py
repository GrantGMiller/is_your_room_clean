import base64
import datetime
import time
from io import BytesIO
from typing import cast

import flask_login
import pyqrcode
import pytz
from flask import Flask, flash, redirect, render_template, request, jsonify
from flask_dictabase import Dictabase

import config
from feature_chores import helpers
from feature_chores import update_job_clear_completed_chores
from feature_chores import wizard
from feature_chores.models import (
    Chore,
    Person,
    assign_chore_to_persons,
    setup as setup_chores_models, get_user_local_dt_from_utc,
)
from ring.user import RingUser, get_current_wall_user
from feature_nintendo import get_device_names

global app


def setup(a: Flask):
    global app
    app = a
    app.db = cast(Dictabase, app.db)
    wizard.setup(app)
    helpers.setup(app)
    setup_chores_models(app)

    @app.route("/chores")
    def chores():
        pass

    @app.route("/chores/person/edit", methods=["GET", "POST"])
    @app.route('/chores/person/add', methods=["GET"])
    def edit_person():

        user = app.get_current_user()
        assigned_chores = app.db.FindAll(Chore, owner_id=user['id'])
        person_id = request.args.get("id", type=int)
        person = app.db.FindOne(Person, id=person_id,
                                owner_id=user['id']) if person_id is not None else None
        assigned_chores = [chore for chore in assigned_chores if person_id in chore.get_assigned_to_ids()]

        if request.method == 'GET':

            mode = 'edit' if person is not None else 'add'
            return render_template(
                "chores/person_edit.html",
                person=person,
                mode=mode,
                assigned_chores=assigned_chores,
                device_names=get_device_names(user['id'])
            )

        elif request.method == "POST":
            person_id = request.args.get("id", type=int)
            name = request.form.get("name", "").strip()
            color = request.form.get("color", "primary")
            nintendo_device_name = request.form.get("nintendo_device_name", "")
            if nintendo_device_name and nintendo_device_name not in get_device_names(
                user['id']
            ):
                return "Invalid Nintendo device", 400
            allowed_colors = {
                "primary",
                "secondary",
                "success",
                "danger",
                "warning",
                "info",
                "light",
                "dark",
            }
            if name:
                person = app.db.FindOne(Person, id=person_id, owner_id=user['id'])
                if not person:
                    person = app.db.New(
                        Person,
                        name=name,
                        color=color if color in allowed_colors else "primary",
                        nintendo_device_name=nintendo_device_name,
                        owner_id=get_current_user()['id'],
                    )
                else:
                    person['name'] = name
                    person['nintendo_device_name'] = nintendo_device_name
                    if color in allowed_colors:
                        person['color'] = color

                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return jsonify(person.ui_safe())

                return redirect("/chores/overview")

        return render_template(
            "chores/person_edit.html",
            person=person,
            mode='edit',
            assigned_chores=assigned_chores,
            device_names=get_device_names(user['id'])
               
                                  
        )

    @app.route("/chores/person/delete", methods=["POST"])
    def delete_person():
        person_id = request.args.get("id", type=int)
        user = app.get_current_user()
        person = (
            app.db.FindOne(Person, id=person_id, owner_id=user["id"])
            if person_id is not None and user
            else None
        )

        if person is not None:
            app.db.Delete(person)

        return redirect("/chores/overview")

    @app.route("/chores/edit", methods=["GET", "POST"])
    def edit_chore():
        chore_id = request.args.get("id", type=int)
        chore = helpers.get_current_user_chore(chore_id)

        if chore is None:
            print('Chore not found', 'danger')
            return redirect("/chores/overview")

        print('request.form=', request.form)
        if request.method == "POST":
            for key in [
                "name",
                "kind",
                "schedule_for",
                "repeat_interval",
                "repeat_time",
                "repeat_units",
                "assignment_mode",
            ]:
                if key in request.form:
                    chore[key] = request.form.get(key)

            if "repeat_time_of_day" in request.form:
                chore.Set(
                    "repeat_time_of_day",
                    request.form.getlist("repeat_time_of_day"),
                )

            chore.Set("repeat_day_of_week", request.form.getlist("repeat_day_of_week"))

            if "tags" in request.form:
                tags = request.form.get("tags", "").split(",")
                # make sure the tags contain text
                tags = [t.strip() for t in tags]
                new_tags = []
                for tag in tags:
                    if tag:
                        new_tags.append(tag)
                chore.Set('tags', new_tags)

            if "repeat_every_number_of" in request.form:
                chore["repeat_every_number_of"] = request.form.get(
                    "repeat_every_number_of", type=int
                )

            if "enabled" in request.form:
                chore['enabled'] = request.form.get("enabled") == 'on'

            chore.refresh_scheduled_job()
            return jsonify(chore.ui_safe())

        return render_template(
            "chores/edit_chore.html",
            chore=chore,
            user=get_current_user(),
            persons=helpers.get_current_user_persons(),
            get_user_local_dt_from_utc=get_user_local_dt_from_utc,
        )

    @app.route("/chores/delete", methods=["POST"])
    def delete_chore():
        chore_id = request.args.get("id", type=int)
        user = app.get_current_user()
        chore = (
            app.db.FindOne(Chore, id=chore_id, owner_id=user["id"])
            if chore_id is not None and user
            else None
        )

        if chore is not None:
            app.db.Delete(chore)

        return redirect("/chores/overview")

    @app.route("/chores/overview")
    def overview():
        user = app.get_current_user()
        if not user:
            return redirect('/dashboard')

        return render_template(
            "chores/overview.html",
            persons=helpers.get_current_user_persons(),
            chores=helpers.get_current_user_chores(),
            now=datetime.datetime.now(datetime.timezone.utc),
            get_user_local_dt_from_utc=get_user_local_dt_from_utc,
            user=get_current_user(),
        )

    @app.route('/chores/settings', methods=["GET", "POST"])
    def chores_settings():
        user: RingUser = app.get_current_user()

        if request.method == "POST":
            print('request.form=', request.form)
            should_refresh_chores = False
            for key in ['morning_time', 'afternoon_time', 'evening_time']:
                if key in request.form:
                    user.SetItem(
                        'chore_settings',
                        key,
                        # convert the string from the form into a datetime.time object
                        datetime.datetime.strptime(request.form.get(key), "%H:%M").time().isoformat()
                        # datetime.datetime.now().time().isoformat()
                    )
                    should_refresh_chores = True

            timezone = request.form.get("timezone")
            if timezone in pytz.all_timezones:
                user['timezone'] = timezone

            user['enable_daylight_savings'] = (
                    request.form.get("enable_daylight_savings") == "on"
            )

            helpers.refresh_all_current_user_chores()
            print('218 update clean completed jobs')
            update_job_clear_completed_chores(user)

            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({
                    **user.get_chore_settings(),
                    "timezone": user.get("timezone", "US/Eastern"),
                    "enable_daylight_savings": user.get(
                        "enable_daylight_savings", True
                    ),
                })

            return redirect("/chores/overview")

        return render_template(
            "chores/settings.html",
            settings=user.get_chore_settings(),
            timezone=user.get("timezone", "US/Eastern"),
            timezones=pytz.all_timezones,
            enable_daylight_savings=user.get("enable_daylight_savings", True),

        )

    @app.route('/chores/assign', methods=['POST'])
    def chore_assign():
        chore_id = request.args.get("chore_id", type=int)
        person_id = request.args.get("person_id", type=int)
        new_state = bool(request.json.get('is_assigned', None))

        user = app.get_current_user()
        print('new_state=', new_state)
        if user and chore_id and person_id and new_state is not None:
            chore = helpers.get_current_user_chore(chore_id)
            person = helpers.get_current_user_person(person_id)
            if chore and person:
                if new_state:
                    chore.assign_to(person)
                else:
                    chore.unassign(person)

                chore.refresh_scheduled_job()
                return jsonify(chore.ui_safe())

        return 'chore or person not found', 404

    @app.route('/chores/unassign/<int:person_id>/<int:chore_id>/', methods=['POST'])
    def chore_unassign(person_id, chore_id):
        chore = helpers.get_current_user_chore(chore_id)
        if not chore:
            return 'chore not found', 404

        chore.unassign(
            helpers.get_current_user_person(
                person_id
                )
            )
        return jsonify(chore.ui_safe())

    @app.route('/chores/assignable', methods=['POST'])
    def chore_assignable():
        data = request.get_json(silent=True) or {}
        chore_id = data.get("chore_id")
        person_id = data.get("person_id")
        is_assignable = data.get("is_assignable")

        if chore_id is None or person_id is None or is_assignable is None:
            return 'chore or person not found', 404

        chore = helpers.get_current_user_chore(int(chore_id))
        person = helpers.get_current_user_person(int(person_id))
        if not chore or not person:
            return 'chore or person not found', 404

        if is_assignable:
            chore.Append('can_be_assigned_to', person['id'])
        else:
            chore.Remove('can_be_assigned_to', person['id'])

        chore.refresh_scheduled_job()
        return jsonify(chore.ui_safe())

    @app.route('/chores/assign-now', methods=['POST'])
    def chore_assign_now():
        data = request.get_json(silent=True) or {}
        chore_id = data.get("chore_id")

        if chore_id is None or helpers.get_current_user_chore(int(chore_id)) is None:
            return jsonify({"error": "chore not found"}), 404

        updated_chore = assign_chore_to_persons(int(chore_id))
        if updated_chore is None:
            return jsonify({"error": "chore not found"}), 404
        return jsonify(updated_chore.ui_safe())

    @app.route('/chores/complete', methods=['POST'])
    def chore_complete():
        chore_id = request.form.get('chore_id', type=int)
        person_id = request.form.get('person_id', type=int)
        chore = helpers.get_current_user_chore(chore_id)
        person = helpers.get_current_user_person(person_id)

        if (
                chore is None
                or person is None
                or person['id'] not in chore.get_assigned_to_ids()
        ):
            return 'chore or person not found', 404

        is_completed = request.form.get('is_completed', 'false').lower() == 'true'
        if is_completed:
            chore.mark_incomplete_by(person['id'])
        else:
            chore.mark_completed_by(person['id'])

        return jsonify({**chore.ui_safe(), 'is_completed': not is_completed})

    @app.route('/chores/view', methods=['GET'])
    def chores_assignee_view():
        print('test284')
        return render_template(
            "chores/assignee_view.html",
            persons=helpers.get_current_user_persons(),
            chores=helpers.get_current_user_chores(),
            now=datetime.datetime.now(datetime.timezone.utc),
            ring_user=get_current_user()
        )

    @app.route('/chores/wall_display', methods=['GET'])
    def chores_wall_display_link():
        user = app.get_current_user()
        if not user:
            flash('You must be logged in to view the wall display.', 'danger')
            return redirect('/')

        wall_display_url = user.get_new_wall_display_url()

        qr = pyqrcode.create(wall_display_url)
        image_buffer = BytesIO()
        qr.png(image_buffer, scale=6)
        wall_display_image = base64.b64encode(image_buffer.getvalue()).decode()

        return render_template(
            "chores/wall_display_link.html",
            wall_display_url=wall_display_url,
            wall_display_image=wall_display_image,
        )

    @app.route('/wall/<code>', methods=['GET', 'POST'])
    def chores_wall(code):
        url = f'{config.SERVER_HOST_URL}wall/{code}'
        user: RingUser = app.db.FindOne(RingUser, wall_display_url=url)
        if not user:
            flash('User not found. Please try again.', 'danger')
            return redirect('/')

        if user and time.time() > float(user.get('wall_link_expires_at', 0)):
            flash('Wall Link expired.', 'danger')
            return redirect('/')

        # dont let them use the same code twice
        user['wall_link_expires_at'] = time.time()

        print('wall user logged in')
        wall_user = user.get_wall_user()
        print('login_user(wall_user=', wall_user)
        flask_login.login_user(wall_user, remember=True)

        return redirect('/wall_display')

    @app.route('/wall_display', methods=['GET'])
    def chores_wall_display():
        wall_user = get_current_wall_user()
        print('get_current_wall_user=', wall_user)
        if not wall_user:
            return render_template(
                'chores/wall_display_user_unknown.html',
            )

        ring_user = wall_user.get_ring_user()
        return render_template(
            'chores/wall_display.html',
            ring_user=ring_user,
            persons=helpers.get_persons(ring_user),
            chores=helpers.get_chores(ring_user),

        )
