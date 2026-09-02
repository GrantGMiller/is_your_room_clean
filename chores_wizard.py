import json

from flask import Flask, redirect, render_template, request
from flask_dictabase import Dictabase
from typing import cast

from chores_helper import  get_current_user_persons
from chores_models import Chore
from ring_user import get_current_user


def setup(app: Flask):
    app.db = cast(Dictabase, app.db)
    @app.route("/chores/wizard/start", methods=["GET", "POST"])
    def start():
        if request.method == "POST":
            kind = request.form.get("kind")
            chore_fields = {
                "name": request.form.get("name", "").strip(),
                "kind": kind,
            }

            if kind == "one-time":
                chore_fields["schedule_for"] = request.form.get("schedule_for")
            elif kind == "repeat":
                chore_fields.update(
                    {
                        "repeat_interval": request.form.get("repeat_interval"),
                        "repeat_day": request.form.get("repeat_day"),
                        "repeat_time_of_day": request.form.get("repeat_time_of_day"),
                        "repeat_time": request.form.get("repeat_time"),
                        "repeat_every": request.form.get("repeat_every", type=int),
                        "repeat_unit": request.form.get("repeat_unit"),
                    }
                )

            chore = app.db.New(
                Chore, 
                owner_id=get_current_user()["id"],
                  **chore_fields
                  )
            return redirect(f'/chores/wizard/2/{chore["id"]}')

        return render_template(
            "chores_wizard_1.html",
        )

    @app.route("/chores/wizard/2/<new_chore_id>", methods=["GET", "POST"])
    def two(new_chore_id):
        chore = app.db.FindOne(Chore, id=int(new_chore_id))

        if request.method == "POST":
            all_people_ids = {str(person["id"]): person for person in get_current_user_persons()}
            selected_person_ids = [
                int(person_id)
                for person_id in request.form.getlist("person_ids")
                if person_id in all_people_ids
            ]
            chore.Set('can_be_assigned_to', selected_person_ids)
            chore["assignment_mode"] = request.form.get("assignment_mode")
            return redirect("/chores/overview")

        return render_template(
            "chores_wizard_2.html",
            chore=chore,
            persons=get_current_user_persons(),
        )
