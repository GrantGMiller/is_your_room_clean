from typing import cast

from flask import Flask, request, jsonify
from flask_dictabase import Dictabase

import config
from chores_models import Chore, Person
from ring_user import RingUser


def setup(app: Flask):
    app.db = cast(Dictabase, app.db)

    @app.route('/migrate/chore', methods=['POST'])
    def migrate_chore():
        apikey = request.json.get('api_key', None)
        if apikey != config.IYRC_KEY:
            return 'wrong api key'

        req_chore = request.json.get('chore', None)
        req_chore.pop('id', None)

        new_chore: Chore = app.db.NewOrFind(
            Chore,
            name=req_chore.get('name'),
        )
        print('req_chore=', req_chore)


        grant = app.db.FindOne(RingUser, email='grant@grant-miller.com')
        if not grant:
            raise Exception('grant not found')
        new_chore['owner_id'] = grant['id']

        new_chore['tags'] = None
        for name in req_chore.pop('can_be_assigned_to_names', []):
            child = app.db.NewOrFind(Person, name=name, owner_id=grant['id'])
            if child:
                new_chore.Append('can_be_assigned_to', child['id'], allowDuplicates=False)

        for tag in req_chore.pop('tags', []):
            new_chore.Append('tags', tag.lower(), allowDuplicates=False)

        new_chore.update(req_chore)

        print('db new_chore=', new_chore)
        return jsonify(new_chore)
