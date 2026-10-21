import datetime
from typing import cast
from typing import cast

from flask import Flask
from flask_jobs import Job, JobScheduler
from flask_dictabase import Dictabase

from app_types import Application
from feature_chores.models import Person, get_user_local_dt_from_utc, get_utc_from_users_time
from feature_chores.helpers import get_chores
from feature_chores.wall_display import setup as setup_wall_display
from feature_nintendo.rewards import give_nintendo_reward

def setup(a: Application):
    global app
    app = a
    setup_wall_display(app)

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

        start_dt_utc = datetime.datetime.now(datetime.timezone.utc)
        start_dt_usertz = get_user_local_dt_from_utc(start_dt_utc, user)
        start_dt_usertz = datetime.datetime.combine(start_dt_usertz, time_obj_usertz)
        # move this job back a bit so that it doesnt overlap
        #  the assignment job(s)
        start_dt_usertz -=  datetime.timedelta(minutes=5)
        
        start_dt_utc = get_utc_from_users_time(start_dt_usertz, user)


        print('start_dt_utc=', start_dt_utc)
        
        app.jobs = cast(JobScheduler, app.jobs)
        new_job = app.jobs.RepeatJob(
            startDT=start_dt_utc,
            name=job_name,
            func=clear_completed_chores,
            args=(user['id'],),
            days=1
       )
        print('46 new job created', new_job['name'], new_job['startDT'])

def clear_completed_chores(user_id:int):
    '''
    Unsassign and clear the completed_by for all chores
    '''

    print('clear_completed_chores called')
    app.db = cast(Dictabase, app.db)
    with app.app_context():

        # keep track of how many chores each person completed
        # if they have completed X num of chores give them a reward 
        num_chores_complted = {
            #Person()['id']: int(num_chores_completed)
        }
        
        user = app.get_user(user_id)
        if user:
            user = user.get_ring_user()
            for chore in get_chores(user):
                for person_id in chore.Get('completed_by', []):
                    person = app.db.FindOne(Person, id=person_id, owner_id=user['id'])
                    if person:
                        chore.unassign(person)
                        person.inc_completed_chore_count()
                        num_chores_complted[person['id']] = num_chores_complted.get(person['id'], 0) + 1
                        print('chore.reward=', chore['reward'])
                        if chore.get('reward', 0):
                            person.add_money(int(chore['reward']), f'Chore Reward: {chore["name"]}')
                            print('new_money=', person['money'])
                
                        if chore.get('kind', None) == 'one-time':
                            app.db.Delete(chore)
                            
                chore.clear_completed_by()
                chore.refresh_scheduled_job()

        print('81 num_chores_completed', num_chores_complted)
        give_nintendo_reward(user_id, num_chores_complted)
