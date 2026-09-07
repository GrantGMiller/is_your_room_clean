import datetime
from typing import Dict, List, Literal, Optional

from flask import Flask
from flask_dictabase import BaseTable
import pytz
import random
from ring_user import RingUser
from slack import send_slack_error

ChoreKind = Literal["one-time", "repeat"]
AssignmentMode = Literal["all", "random", "first-done"]
RepeatInterval = Literal["daily", "weekly", "other"]
RepeatTimeOfDay = Literal["morning", "afternoon", "evening", "specific"]
RepeatDay = Literal[
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]
RepeatUnit = Literal["day", "week", "month"]
PersonColor = Literal[
    "primary", "secondary", "success", "danger", "warning", "info", "light", "dark"
]


LastCompleted = Dict[int, datetime.datetime]
# LastCompleted is a dictionary where the key is the person_id and the value is the datetime when they last completed the chore.

app:Flask = None
def setup(a:Flask):
    global app
    app = a

class Person(BaseTable):
    name: str
    color: Optional[PersonColor] = "primary"
    chores_assigned: List["Chore"] = []
    chores_completed: List["Chore"] = []
    owner_id: int

    def ui_safe(self):
        ret = {
            "id": self.get("id", None),
            "name": self.get("name", None),
            "color": self.get("color", None),
            "owner_id": self.get("owner_id", None),
        }
        return ret

    def get_number_of_chores_assigned(self) -> int:
        num = 0
        for chore in self.app.db.FindAll(Chore, owner_id=self['owner_id']):
            if self['id'] in chore.get_assigned_to_ids():
                num += 1
        return num

    def get_number_of_chores_completed(self) -> int:
        num = 0
        for chore in self.app.db.FindAll(Chore, owner_id=self['owner_id']):
            if self['id'] in chore.Get('completed_by', []):
                num += 1
        return num

    def get_number_of_chores_incomplete(self) -> int:
        num = 0
        for chore in self.app.db.FindAll(Chore, owner_id=self['owner_id']):
            if self['id'] in chore.get_assigned_to_ids() and self['id'] not in chore.Get('completed_by', []):
                num += 1
        return num


Assignees = List[Person]


class Chore(BaseTable):
    name: str
    kind: ChoreKind
    assignment_mode: Optional[AssignmentMode] = None
    schedule_for: Optional[str] = None
    repeat_interval: Optional[RepeatInterval] = None
    repeat_day_of_week: Optional[RepeatDay] = None
    repeat_time_of_day: Optional[RepeatTimeOfDay] = None
    repeat_time: Optional[str] = None
    repeat_every_number_of: Optional[int] = None
    repeat_units: Optional[RepeatUnit] = None
    owner_id: int
    tags: List[str] = []
    job_id: Optional[int] = None
    last_completed: LastCompleted

    def ui_safe(self):
        ret = {
            'assigned_to_ids': self.get_assigned_to_ids(),
            'can_be_assigned_to_ids': self.get_can_be_assigned_to_ids(),
            "assignment_mode": self.get('assignment_mode', None),
            "kind": self.get('kind', None),
            "name": self.get('name', None),
            "owner_id": self.get('owner_id', None),
            "repeat_day_of_week": self.get('repeat_day_of_week', None),
            "repeat_every_number_of": self.get('repeat_every_number_of', None),
            "repeat_interval": self.get('repeat_interval', None),
            "repeat_time_of_day": self.get('repeat_time_of_day', None),
            "repeat_time": self.get('repeat_time', None),
            "repeat_units": self.get('repeat_units', None),
            "schedule_for": self.get('schedule_for', None),
            "tags": self.get('tags', None),
        }
        return ret

    @property
    def can_be_assigned_to(self) -> List[Person]:
        '''
        This is a list of Persons that the chore can be assigned to.
        However, it may not be assigned currently.

        For example, if the chore gets assigned on Fridays, but today is Monday, it wont
        be assigned to anyone.
        '''
        ids = self.Get('can_be_assigned_to', [])
        return [self.app.db.FindOne(Person, id=id, owner_id=self.owner_id) for id in ids]

    def get_can_be_assigned_to_ids(self) -> List[int]:
        return self.Get('can_be_assigned_to', [])

    def get_can_be_assigned_to_persons(self) -> List[Person]:
        ret = []
        for id in self.get_can_be_assigned_to_ids():
            person = self.app.db.FindOne(Person, id=id, owner_id=self['owner_id'])
            if person is not None:
                ret.append(person)
        return ret

    def assign_to(self, person: Person) -> None:
        '''
        Assign the chore to a specific person.
        '''
        self.Append('assigned_to', person['id'], allowDuplicates=False)
        self.Remove('completed_by', person['id'], removeAll=True)  

    def unassign(self, person: Person) -> None:
        self.Remove('assigned_to', person['id'], removeAll=True)

    def is_assigned_to(self, person_id: int) -> bool:
        return person_id in self.Get('assigned_to', [])

    def get_assigned_to_ids(self) -> List[int]:
        return self.Get('assigned_to', [])

    def get_assigned_to_persons(self) -> List[Person]:
        return [
            self.app.db.FindOne(
                Person,
                id=idd,
                owner_id=self['owner_id']
            ) for idd in self.Get('assigned_to', [])
        ]

    def add_tag(self, tag: str):
        self.Append('tags', tag, allowDuplicates=False)

    def remove_tag(self, tag: str):
        self.Remove('tags', tag, removeAll=True)

    def mark_completed_by(self, person_id: int) -> None:
        '''
        Mark the chore as completed by a specific person.
        '''
        self.Append('completed_by', person_id, allowDuplicates=False)
        self.SetItem('last_completed', person_id, datetime.datetime.now(datetime.timezone.utc))

        if self.get('assignment_mode') == 'first-done':
            for person in self.get_assigned_to_persons():
                if person['id'] != person_id:
                    self.unassign(person)

    def mark_incomplete_by(self, person_id: int) -> None:
        '''
        Mark the chore as incomplete by a specific person.
        '''
        self.Remove('completed_by', person_id, removeAll=True)

    def refresh_scheduled_job(self) -> None:
        if self.get('job_id', None) is not None:
            old_job = self.app.jobs.GetJob(self.get('job_id'))
            if old_job:
                old_job.Delete()

        dt = self.get_next_start_dt()
        print('refresh_scheduled_job: dt=', dt,', name=', self.get('name'))
        if dt is None:
            print('oops')
            return
        
        new_job = self.app.jobs.ScheduleJob(
            func=assign_chore_to_persons,
            args=(self['id'],),
            dt=dt,
            errorCallback=send_slack_error,
            name=f"Assign chore '{self['name']}' to persons",
        )
        self['job_id'] = new_job['id']

    def get_next_start_dt(self) -> Optional[datetime.datetime]:
        '''
        Get the next start datetime for the chore, based on its repeat settings.
        If the chore is a one-time chore, return None.
        '''
        user = self.app.db.FindOne(RingUser, id=self['owner_id'])
        now = datetime.datetime.now()
        now = get_utc_from_users_time(now, user)

        if self.get('kind') == 'one-time':
            dt = datetime.datetime.strptime(self.get('schedule_for'), '%Y-%m-%d %H:%M:%S') if self.get('schedule_for') else None
            dt = get_utc_from_users_time(dt, user) if dt else None
            if dt and dt > now:
                return dt
            else:
                return None  # one-time chore is in the past, no next start datetime

        # For repeat chores, calculate the next start datetime based on the repeat settings
       
        
        if self.get('repeat_interval') == 'daily':
               if self.get('repeat_time_of_day') == 'specific':
                   time = self.get_chore_time()
                   dt = datetime.datetime.combine(now.date(), time)
                   dt = get_utc_from_users_time(dt, user)
                   if dt < now:
                       dt += datetime.timedelta(days=1)
                   return dt
               else:
                for time_of_day in ['morning', 'afternoon', 'evening']:
                    if self.get('repeat_time_of_day', None) == time_of_day:
                        time = self.get_chore_time()
                        dt = datetime.datetime.combine(now.date(), time)
                        dt = get_utc_from_users_time(dt, user)
                        if dt < now:
                            dt += datetime.timedelta(days=1)
                        return dt
                       
             
        elif self.get('repeat_interval') == 'weekly':
            # set the time
            time = self.get_chore_time()
            dt = datetime.datetime.combine(now.date(), time)
            dt = get_utc_from_users_time(dt, user)

            # go forward until with day+=1 we are on the correct day
            i = 0
            correct_day_of_week_index = [
                'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'
            ].index(self.get('repeat_day_of_week'))

            while i < 7: 
                if dt.weekday() == correct_day_of_week_index and dt > now:
                    return dt
                dt += datetime.timedelta(days=1)
                i += 1


        elif self.get('repeat_interval') == 'other': 
            timedelta_kwargs = {}
            if self.get('repeat_units') == 'day':
                timedelta_kwargs['days'] = self.get('repeat_every_number_of', 1)
            elif self.get('repeat_units') == 'week':
                timedelta_kwargs['days'] = self.get('repeat_every_number_of', 1) * 7

            time = self.get_chore_time()
            print('247 time=', time)
            dt = datetime.datetime.combine(now.date(), time)
            print('249 dt=', dt)
            if self.get('repeat_units') == 'month':
                # bump the dt out by x num of months
                num_months = self.get('repeat_every_number_of', 1)
                dt = dt.replace(month= (dt.month - 1 + num_months) % 12 + 1, year=dt.year + (dt.month - 1 + num_months) // 12)
            else:
                dt = dt + datetime.timedelta(**timedelta_kwargs)
            print('259 dt=', dt)
            return dt

        return None

    def get_chore_time(self) -> Optional[datetime.time]:
       '''
       This returns only the datetime.time for this chore
       '''
       if self.get('repeat_time_of_day') == 'specific':
            time = datetime.time.strptime(self.get('repeat_time'), '%H:%M')
            return time
       else:
            user = self.app.db.FindOne(RingUser, id=self['owner_id'])
            for time_of_day in ['morning', 'afternoon', 'evening']:
                if self.get('repeat_time_of_day', None) == time_of_day:
                    time_str = user.Get('chore_settings', {}).get(f'{time_of_day}_time')
                    print('time_str=', time_str)
                    time = datetime.datetime.strptime(time_str, '%H:%M:%S').time()
                    return time

def get_utc_from_users_time(dt:datetime.datetime, user:RingUser):
    '''
    The jobs are scheduled in UTC.
    So adust the datetime from the users timezone to UTC,
    including daylight savings if the user has it enabled.
    '''
    user_tz = user.get('timezone', 'UTC')
    if user_tz == 'UTC':
        return dt
    else:
        tz = pytz.timezone(user_tz)
        dt_with_tz = tz.localize(dt)
        dt_utc = dt_with_tz.astimezone(pytz.utc)
        # adjust for daylight savings if the user has it enabled
        if user.get('enable_daylight_savings', True):
            if tz.dst(dt_with_tz):
                dt_utc -= tz.dst(dt_with_tz)
        return dt_utc

def assign_chore_to_persons(chore_id:int):
    with app.app_context():
        chore:Chore = app.db.FindOne(Chore, id=chore_id)
        
        if chore is None:
            print(f"Chore with id {chore_id} not found.")
            return

        possible_assignees = chore.get_can_be_assigned_to_persons()
        if not possible_assignees:
            print(f"No possible assignees for chore '{chore['name']}' (id: {chore_id}).")
            return

        if chore.get('assignment_mode') in [ 'all', 'first-done']:
            for person in possible_assignees:
                chore.assign_to(person)

        elif chore.get('assignment_mode') == 'random':
            person = random.choice(possible_assignees)
            chore.assign_to(person)

        return chore

        