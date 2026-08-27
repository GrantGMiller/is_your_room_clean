import datetime
import os
from typing import cast

from flask_dictabase import Dictabase
from flask_jobs import JobScheduler

from ring_user import RingImage
from slack import send_slack_message, send_slack_error

global app


def setup(a):
    global app
    app = a
    app.jobs = cast(JobScheduler, app.jobs)

    with app.app_context():
        add_new_daily_job(
            app,
            job_name='delete old images',
            startDT=datetime.datetime.utcnow().replace(
                hour=0, minute=0, second=0, microsecond=0
            ) - datetime.timedelta(days=1),  # midnight
            func=delete_old_images,
            hours=1,
            errorCallback=send_slack_error
        )


def add_new_daily_job(app, job_name, *a, **k):
    app.jobs = cast(JobScheduler, app.jobs)
    with app.app_context():
        existing_job = app.jobs.Find(name=job_name)
        if existing_job:
            existing_job.Delete()

        new_job = app.jobs.RepeatJob(
            *a, name=job_name, **k,
        )
        return new_job


def delete_old_images():
    app.jobs = cast(JobScheduler, app.jobs)
    app.db = cast(Dictabase, app.db)

    with app.app_context():
        dt_24hrs_ago = datetime.datetime.now() - datetime.timedelta(hours=24)
        num_img_deleted = 0
        for img in app.db.FindAll(RingImage):
            img_timestamp = (img.get('timestamp_epoch_ms', 0) or 0) / 1000
            img_dt = datetime.datetime.fromtimestamp(img_timestamp)
            if img_dt > dt_24hrs_ago:
                print('deleting img=', img)
                app.db.Delete(img)  # delete the obj from the database
                num_img_deleted += 1
                try:
                    os.remove(img['image_path'])  # delete the img from the server hard drive
                except Exception as e:
                    send_slack_message('Error deleting old image', e)
        send_slack_message('deleted', num_img_deleted, 'old images')
