import datetime
import json
from collections import defaultdict
from functools import lru_cache
from typing import cast

from flask import Flask
from flask_dictabase import Dictabase
from flask_jobs import JobScheduler, Job

import feature_email
from chores_models import get_utc_from_users_time, get_chores, Chore, Person
from ring_user import RingUser

app: Flask


def setup(a: Flask):
    global app
    app = a


def get_daily_job_name(user_id: int):
    return f'email_send_daily_update_person={user_id}'


def update_email_job(user_id: int):
    print('update_email_job', user_id)
    user_id = int(user_id)
    app.db = cast(Dictabase, app.db)
    app.jobs = cast(JobScheduler, app.jobs)
    if not app:
        return
    with app.app_context():
        existing_job: Job = app.jobs.Find(name=get_daily_job_name(user_id))
        if existing_job:
            existing_job.Delete()

        user = app.db.FindOne(RingUser, id=user_id)
        start_time_usertz = datetime.datetime.strptime(
            user.GetItem(
                feature_email.SETTINGS_KEY, 'daily_chore_summary_time', '08:00'
            ),
            '%H:%M',
        ).time()
        start_dt_usertz = datetime.datetime.combine(
            datetime.datetime.now(), start_time_usertz
        )
        start_dt_utc = get_utc_from_users_time(start_dt_usertz, user)

        job = app.jobs.RepeatJob(
            name=get_daily_job_name(user_id),
            func=send_daily_email_summary,
            args=(user_id,),
            startDT=start_dt_utc,
            days=1,
        )
        print('new job=', job)


def send_daily_email_summary(user_id: int):
    with app.app_context():
        app.db = cast(Dictabase, app.db)
        user = app.db.FindOne(RingUser, id=user_id)

        data = defaultdict(list)  # {
        # str(person['name']): [str(chore['name'])...]
        # }

        now_dt_utc = datetime.datetime.now(datetime.timezone.utc)
        one_day_ago_utc = now_dt_utc - datetime.timedelta(days=1)

        @lru_cache
        def get_person_name(person_id: int):
            person = app.db.FindOne(Person, id=person_id)
            return person['name']

        for chore in get_chores(user):
            chore = cast(Chore, chore)
            possible_assignees_ids = chore.get_can_be_assigned_to_ids()
            for assignee_id in possible_assignees_ids:
                last_completed = chore.get_last_completed_dt_utc(assignee_id)
                if last_completed and last_completed >= one_day_ago_utc:
                    data[get_person_name(assignee_id)].append(chore['name'])

        print('data=', json.dumps(data, indent=2))

