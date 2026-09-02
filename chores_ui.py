from typing import cast
from flask_dictabase import Dictabase
from flask import Flask, abort, flash, redirect, render_template, request

import chores_wizard
from chores_models import Chore, Person
import chores_helper
from ring_user import get_current_user

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
            person = app.db.FindOne(Person, id=person_id, owner_id=get_current_user()['id']) if person_id is not None else None
            return render_template("chores_person_edit.html", person=person, mode='add')

        elif request.method == "POST":
            person_id = request.args.get("id", type=int)
            name = request.form.get("name", "").strip()
            if name:
                person = app.db.FindOne(Person, id=person_id, owner_id=get_current_user()['id'])
                if not person:
                    person = app.db.New(Person, name=name, owner_id=get_current_user()['id'])
                return redirect("/chores/overview")

        return render_template("chores_person_edit.html", person=person, mode='edit')

    @app.route("/chores/edit", methods=["GET"])
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
