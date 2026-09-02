
from flask import Flask
from flask_dictabase import Dictabase
from typing import cast

from chores_models import Person, Chore
from ring_user import get_current_user


global app
def setup(a: Flask):
    global app
    app = a
    app.db = cast(Dictabase, app.db)
    
def get_current_user_persons():
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

def get_current_user_chores():
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