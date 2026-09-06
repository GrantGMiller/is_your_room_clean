import datetime
from typing import cast

from flask import Flask, flash, redirect, render_template, request, jsonify
from flask_dictabase import Dictabase

import chores_helper
import chores_wizard
from chores_models import Chore, Person
from ring_user import RingUser, get_current_user

global app


def setup(a: Flask):
    global app
    app = a
    app.db = cast(Dictabase, app.db)
    chores_wizard.setup(app)
    chores_helper.setup(app)

    @app.route("/chores")
    def chores():
        pass

    @app.route("/chores/person/edit", methods=["GET", "POST"])
    @app.route('/chores/person/add', methods=["GET"])
    def edit_person():
        if request.method == 'GET':
            person_id = request.args.get("id", type=int)
            person = app.db.FindOne(Person, id=person_id,
                                    owner_id=get_current_user()['id']) if person_id is not None else None
            mode = 'edit' if person is not None else 'add'
            return render_template("chores_person_edit.html", person=person, mode=mode)

        elif request.method == "POST":
            person_id = request.args.get("id", type=int)
            name = request.form.get("name", "").strip()
            if name:
                person = app.db.FindOne(Person, id=person_id, owner_id=get_current_user()['id'])
                if not person:
                    person = app.db.New(Person, name=name, owner_id=get_current_user()['id'])
                else:
                    person['name'] = name
                return redirect("/chores/overview")

        return render_template("chores_person_edit.html", person=person, mode='edit')

    @app.route("/chores/edit", methods=["GET", "POST"])
    def edit_chore():
        chore_id = request.args.get("id", type=int)
        user = get_current_user()
        chore = (
            app.db.FindOne(Chore, id=chore_id, owner_id=user["id"])
            if chore_id is not None and user
            else None
        )

        if chore is None:
            flash('Chore not found', 'danger')
            return redirect("/chores/overview")
        print('request.form=', request.form)
        if request.method == "POST":
            for key in [
                "name",
                "kind",
                "schedule_for",
                "repeat_interval",
                "repeat_day_of_week",
                "repeat_time_of_day",
                "repeat_time",
                "repeat_units",
                "assignment_mode",
                "tags",
            ]:
                if key in request.form:
                    chore[key] = request.form.get(key)

            if "repeat_every_number_of" in request.form:
                chore["repeat_every_number_of"] = request.form.get(
                    "repeat_every_number_of", type=int
                )

            return jsonify(chore.ui_safe())


        return render_template(
            "chores_edit_chore.html",
            chore=chore,
            persons=chores_helper.get_current_user_persons(),
        )

    @app.route("/chores/delete", methods=["POST"])
    def delete_chore():
        chore_id = request.args.get("id", type=int)
        user = get_current_user()
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
        return render_template(
            "chores_overview.html",
            persons=chores_helper.get_current_user_persons(),
            chores=chores_helper.get_current_user_chores(),
        )

    @app.route('/chores/settings', methods=["GET", "POST"])
    def chores_settings():
        user: RingUser = get_current_user()

        if request.method == "POST":
            print('request.form=', request.form)
            for key in ['morning_time', 'afternoon_time', 'evening_time']:
                if key in request.form:
                    user.SetItem(
                        'chore_settings',
                        key,
                        # convert the string from the form into a datetime.time object
                        datetime.datetime.strptime(request.form.get(key), "%H:%M").time().isoformat()
                        # datetime.datetime.now().time().isoformat()
                    )
                    return redirect("/chores/overview")

        return render_template(
            "chores_settings.html",
            settings=user.get_chore_settings()

        )

    @app.route('/chores/assign', methods=['POST'])
    def chore_assign():
        chore_id = request.args.get("chore_id", type=int)
        person_id = request.args.get("person_id", type=int)
        new_state = bool(request.json.get('is_assigned', None))

        user = get_current_user()

        if user and chore_id and person_id and new_state is not None:
            chore = chores_helper.get_current_user_chore(chore_id)
            person = chores_helper.get_current_user_person(person_id)
            if chore and person:
                if new_state:
                    chore.assign_to(person)
                else:
                    chore.unassign(person)

                return jsonify(chore.ui_safe())

        return 'chore or person not found', 404

    @app.route('/chores/assignable', methods=['POST'])
    def chore_assignable():
        data = request.get_json(silent=True) or {}
        chore_id = data.get("chore_id")
        person_id = data.get("person_id")
        is_assignable = data.get("is_assignable")

        if chore_id is None or person_id is None or is_assignable is None:
            return 'chore or person not found', 404

        chore = chores_helper.get_current_user_chore(int(chore_id))
        person = chores_helper.get_current_user_person(int(person_id))
        if not chore or not person:
            return 'chore or person not found', 404

        if is_assignable:
            chore.Append('can_be_assigned_to', person['id'])
        else:
            chore.Remove('can_be_assigned_to', person['id'])

        return jsonify(chore.ui_safe())
