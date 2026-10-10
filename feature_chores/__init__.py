import datetime
from typing import cast
from typing import cast

from flask import Flask
from flask_jobs import Job, JobScheduler

from chores_models import Person, get_chores, get_utc_from_users_time
from ring_user import RingUser

def setup(a:Flask):
    global app
    app = a

def update_job_clear_completed_chores(user):
    '''
    There will be a job run daily at the 'morning', 'afternoon' and 'evening'
      times that will clear the completed chores from the persons
    '''
    print('update_job_clear_completed_chores called')
    chore_times_usertz = user.get_chore_settings()

    for time_of_day, time_iso in chore_times_usertz.items():
        time_obj_usertz = datetime.time.fromisoformat(time_iso)
        job_name = f"clear_completed_chores_{time_of_day}_{user['id']}"
        existing_job:Job = app.jobs.Find(
            name=job_name
        )
        if existing_job:
            existing_job.Delete()

        startDT = datetime.datetime.now(datetime.timezone.utc)
        startDT = datetime.datetime.combine(startDT, time_obj_usertz)
        # move this job back a bit so that it doesnt overlap
        #  the assignment job(s)
        startDT = startDT - datetime.timedelta(minutes=5)

        startDT = get_utc_from_users_time(startDT, user)
        print('startDT utc=', startDT   )
        
        app.jobs = cast(JobScheduler, app.jobs)
        new_job = app.jobs.RepeatJob(
            startDT=startDT,
            name=job_name,
            func=clear_completed_chores,
            args=(user['id'],),
            days=1
       )
        print('46 new job created', new_job)

def clear_completed_chores(user_id:int):
    '''
    Unsassign and clear the completed_by for all chores
    '''
    print('clear_completed_chores called')
    with app.app_context():
        user:RingUser = app.db.FindOne(RingUser, id=user_id)
        if user:
            user = user.get_ring_user()
            for chore in get_chores(user):
                for person_id in chore.Get('completed_by', []):
                    person = app.db.FindOne(Person, id=person_id, owner_id=user['id'])
                    if person:
                        chore.unassign(person)
                    chore.clear_completed_by()

