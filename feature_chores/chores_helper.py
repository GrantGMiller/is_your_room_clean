from typing import cast, Optional, List

from flask import Flask
from flask_dictabase import Dictabase

from chores_models import Person, Chore

global app


def setup(a: Flask):
    global app
    app = a
    app.db = cast(Dictabase, app.db)


def get_current_user_persons() -> List[Person]:
    from ring_user import get_current_user

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
    from ring_user import get_current_user

    with app.app_context():
        user = get_current_user()
        if not user:
            return []

        return list(
            app.db.FindAll(
                Chore,
                owner_id=user['id'],
                _orderBy='enabled',
                _reverse=True
            )
        )


def get_current_user_person(person_id: int) -> Optional[Person]:
    from ring_user import get_current_user

    with app.app_context():
        user = get_current_user()
        if not user:
            return None
        user = user.get_ring_user()
        return app.db.FindOne(Person, id=person_id, owner_id=user['id'])


def get_current_user_chore(chore_id: int) -> Optional[Chore]:
    from ring_user import get_current_user

    with app.app_context():
        user = get_current_user()
        if not user:
            return None
        user = user.get_ring_user()
        return app.db.FindOne(Chore, id=chore_id, owner_id=user['id'])


def get_persons(user) -> List[Person]:
    with app.app_context():
        owner_user = user.get_ring_user()
        return list(app.db.FindAll(Person, owner_id=owner_user['id']))


def get_chores(user) -> List[Chore]:
    with app.app_context():
        owner_user = user.get_ring_user()
        return list(app.db.FindAll(Chore, owner_id=owner_user['id']))


def refresh_all_current_user_chores():
    from ring_user import get_current_user

    print('Refreshing all current user chores')
    with app.app_context():
        user = get_current_user()
        if not user:
            return

        for chore in get_current_user_chores():
            chore.refresh_scheduled_job()