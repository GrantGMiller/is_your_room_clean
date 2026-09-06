from typing import cast, Optional, List

from flask import Flask
from flask_dictabase import Dictabase

from chores_models import Person, Chore
from ring_user import get_current_user

global app


def setup(a: Flask):
    global app
    app = a
    app.db = cast(Dictabase, app.db)


def get_current_user_persons() -> List[Person]:
    with app.app_context():
        user = get_current_user()
        if not user:
            return []

        return list(
            app.db.FindAll(
                Person,
                owner_id=user['id']
            )
        )


def get_current_user_chores() -> List[Chore]:
    with app.app_context():
        user = get_current_user()
        if not user:
            return []

        return list(
            app.db.FindAll(
                Chore,
                owner_id=user['id']
            )
        )


def get_current_user_person(person_id: int) -> Optional[Person]:
    with app.app_context():
        user = get_current_user()
        if not user:
            return None
        return app.db.FindOne(Person, id=person_id, owner_id=user['id'])


def get_current_user_chore(chore_id: int) -> Optional[Chore]:
    with app.app_context():
        user = get_current_user()
        if not user:
            return None
        return app.db.FindOne(Chore, id=chore_id, owner_id=user['id'])
