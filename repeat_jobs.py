from __future__ import annotations

import datetime
import os
from app_types import Application

from ring.user import RingImage
from slack import send_slack_message, send_slack_error, send_all_slack_messages

app: Application


def setup(a: Application) -> None:
    global app
    app = a

    with app.app_context():
        add_new_repeat_job(
            app,
            job_name='delete old images',
            startDT=datetime.datetime.utcnow().replace(
                hour=0, minute=0, second=0, microsecond=0
            ) - datetime.timedelta(days=1),  # midnight
            func=delete_old_images,
            minutes=30,
            errorCallback=send_slack_error
        )

        add_new_repeat_job(
            app,
            job_name='send slack messages',
            startDT=datetime.datetime.utcnow(),
            func=send_all_slack_messages,
            errorCallback=send_slack_error,
            minutes=1
        )


def add_new_repeat_job(app: Application, job_name, *a, **k):
    with app.app_context():
        # if the job already exists, delete it first so we can add a new one
        existing_job = app.jobs.Find(name=job_name)
        if existing_job:
            existing_job.Delete()

        new_job = app.jobs.RepeatJob(
            *a, name=job_name, **k,
        )
        return new_job


def delete_old_images():
    with app.app_context():
        dt_expired_img = datetime.datetime.now() - datetime.timedelta(hours=1)
        num_img_deleted = 0
        for img in app.db.FindAll(RingImage):
            img_timestamp = (img.get('timestamp_epoch_ms', 0) or 0) / 1000
            img_dt = datetime.datetime.fromtimestamp(img_timestamp)
            if img_dt < dt_expired_img:
                print('deleting img=', img)
                app.db.Delete(img)  # delete the obj from the database
                num_img_deleted += 1
                try:
                    os.remove(img['image_path'])  # delete the img from the server hard drive
                except Exception as e:
                    send_slack_message('Error deleting old image', e)

        # if num_img_deleted:
        #     send_slack_message('deleted', num_img_deleted, 'old images')
