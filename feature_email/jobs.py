import datetime
import json
from collections import defaultdict
from functools import lru_cache
from typing import cast, Dict

from flask import Flask, render_template
from flask_dictabase import Dictabase
from flask_jobs import JobScheduler, Job

import chores_models
import feature_email
import ring_user
from feature_email.helpers import send_email

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

        user = app.db.FindOne(ring_user.RingUser, id=user_id)
        if not user and user.Get('email_notification_settings', 'daily_chore_summary', False):
            print('email notification is disabled')
            return

        start_time_usertz = datetime.datetime.strptime(
            user.GetItem(
                feature_email.SETTINGS_KEY, 'daily_chore_summary_time', '08:00'
            ),
            '%H:%M',
        ).time()
        start_dt_usertz = datetime.datetime.combine(
            datetime.datetime.now(), start_time_usertz
        )
        start_dt_utc = chores_models.get_utc_from_users_time(start_dt_usertz, user)

        job = app.jobs.RepeatJob(
            name=get_daily_job_name(user_id),
            func=send_daily_email_summary,
            args=(user_id,),
            startDT=start_dt_utc,
            days=1,
        )
        print('new job=', job)


def get_summary_data(user_id: int):
    with app.app_context():
        app.db = cast(Dictabase, app.db)
        user = app.db.FindOne(ring_user.RingUser, id=user_id)

        data = defaultdict(list)  # {
        # str(person['name']): [str(chore['name'])...]
        # }

        now_dt_utc = datetime.datetime.now(datetime.timezone.utc)
        one_day_ago_utc = now_dt_utc - datetime.timedelta(days=1)

        @lru_cache
        def get_person_name(person_id: int):
            person = app.db.FindOne(chores_models.Person, id=person_id)
            return person['name']

        for chore in chores_models.get_chores(user):
            possible_assignees_ids = chore.get_can_be_assigned_to_ids()
            for assignee_id in possible_assignees_ids:
                last_completed = chore.get_last_completed_dt_utc(assignee_id)
                if last_completed and last_completed >= one_day_ago_utc:
                    data[get_person_name(assignee_id)].append(chore['name'])

        return data


def send_daily_email_summary(user_id: int):
    with app.app_context():
        app.db = cast(Dictabase, app.db)
        data = get_summary_data(user_id)
        user = app.db.FindOne(ring_user.RingUser, id=user_id)
        if not user:
            return
        print('data=', json.dumps(data, indent=2))
        send_email(
            to=user['email'],
            subject='Chores - Daily Summary',
            html=render_template('email/daily_summary_email.html', data=data),
            body=json.dumps(data, indent=2),

        )


def render_daily_summary(data: Dict):
    return render_template(
        'email/daily_summary.html',
        data=data
    )
