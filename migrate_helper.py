import datetime
from typing import cast

import pytz
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

        if 'repeat_day_of_week' in req_chore:
            new_chore['repeat_day_of_week'] = None
            for day in req_chore.pop('repeat_day_of_week', []):
                new_chore.Append('repeat_day_of_week', day, allowDuplicates=False)



        if req_chore.get('last_completed', None):
            new_chore['last_completed'] = None
            for person_name, timestamp in req_chore.pop('last_completed', {}).items():

                print('person_name=', person_name, timestamp)
                person = app.db.NewOrFind(Person, name=person_name, owner_id=grant['id'])

                print('last_completed=', timestamp, person)
                if timestamp:
                    new_chore.SetItem(
                        'last_completed',
                        str(person['id']),
                        datetime.datetime.fromtimestamp(timestamp, tz=pytz.utc).isoformat(),
                    )
            print('db last_completed=', new_chore.Get('last_completed', {}))

        if req_chore.get('repeat_time_of_day'):
            new_chore['repeat_time_of_day'] = None
            for time_of_day in req_chore.pop('repeat_time_of_day', []):
                new_chore.Append('repeat_time_of_day', time_of_day, allowDuplicates=False)

        new_chore.update(req_chore)

        print('db new_chore=', new_chore)
        new_chore.refresh_scheduled_job()
        return jsonify(new_chore)
