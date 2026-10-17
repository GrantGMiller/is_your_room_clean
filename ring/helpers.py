
from typing import Optional


from flask import Flask



def setup(a:Flask):
    global app
    app = a

def get_user(user_id) :
    from ring.user import RingUser

    with app.app_context():
        return app.db.FindOne(RingUser, id=int(user_id))


