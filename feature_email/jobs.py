import datetime
from typing import cast

from flask import Flask
from flask_dictabase import Dictabase
from flask_jobs import JobScheduler

import feature_email
from chores_models import get_utc_from_users_time
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
        existing_job = app.jobs.Find(name=get_daily_job_name(user_id))
        if existing_job:
            existing_job.delete()

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
    print('todo send_daily_email_summary user_id=', user_id)
