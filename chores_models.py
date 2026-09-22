import datetime
import random
from typing import Dict, List, Literal, Optional, cast

import pytz
from flask import Flask
from flask_dictabase import BaseTable, Dictabase

import ring_user
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

app: Flask = None


def setup(a: Flask):
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
    repeat_time: Optional[str] = None  # user local timezone
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
        print('chore.assign_to', person)
        print('145 chore.Get("assigned_to")=', self.Get('assigned_to', None))
        self.Append('assigned_to', person['id'], allowDuplicates=False)
        self.Remove('completed_by', person['id'], removeAll=True)
        print('149 chore.Get("assigned_to")=', self.Get('assigned_to', None))

    def unassign(self, person: Person) -> None:
        print('chore.unassign', person)
        print('150 chore.Get("assigned_to")=', self.Get('assigned_to', None))
        self.Remove('assigned_to', person['id'], removeAll=True)
        print('152 chore.Get("assigned_to")=', self.Get('assigned_to', None))

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
        self.SetItem('last_completed', str(person_id), datetime.datetime.now(datetime.timezone.utc).isoformat())

        if self.get('assignment_mode') == 'first-done':
            for person in self.get_assigned_to_persons():
                if person['id'] != person_id:
                    self.unassign(person)

    def get_last_completed_dt(self) -> Optional[datetime.datetime]:
        completed_dates = filter(
            lambda iso: iso is not None,
            self.Get('last_completed', {}).values()
        )
        return max([datetime.datetime.fromisoformat(iso) for iso in completed_dates], default=None)

    def mark_incomplete_by(self, person_id: int) -> None:
        '''
        Mark the chore as incomplete by a specific person.
        '''
        self.Remove('completed_by', person_id, removeAll=True)

        self.SetItem('last_completed', str(person_id), None)

        if self.get('assignment_mode') == 'first-done':
            for person in self.get_can_be_assigned_to_persons():
                self.assign_to(person)

    def get_scheduled_job_dt(self) -> Optional[datetime.datetime]:

        if self.get('job_id', None) is not None:
            job = self.app.jobs.GetJob(self.get('job_id'))
            if job is not None:
                return job.get('dt', None)

        return None

    def refresh_scheduled_job(self) -> None:
        if self.get('job_id', None) is not None:
            old_job = self.app.jobs.GetJob(self.get('job_id'))
            if old_job:
                old_job.Delete()

        dt_utc = self.get_next_start_dt_utc()
        print('refresh_scheduled_job: dt_utc=', dt_utc, ', name=', self.get('name'))
        if dt_utc is None:
            raise Exception('no scheduled job')

        new_job = self.app.jobs.ScheduleJob(
            func=assign_chore_to_persons,
            args=(self['id'],),
            dt=dt_utc,
            errorCallback=send_slack_error,
            name=f"Assign chore '{self['name']}' to persons",
        )
        self['job_id'] = new_job['id']

    def get_next_start_dt_utc(self) -> Optional[datetime.datetime]:
        '''
        Get the next start datetime for the chore, based on its repeat settings.
        If the chore is a one-time chore, return None.
        The return datetime is in UTC
        '''
        user_tz = self.user.get('timezone', 'UTC')
        now_dt_usertz = datetime.datetime.now(tz=pytz.timezone(user_tz))

        if self.get('kind') == 'one-time':
            dt_usertz = datetime.datetime.strptime(self.get('schedule_for'), '%Y-%m-%dT%H:%M') if self.get(
                'schedule_for') else None
            dt_usertz = get_utc_from_users_time(dt_usertz, self.user) if dt_usertz else None
            if dt_usertz and dt_usertz > now_dt_usertz:
                return dt_usertz
            else:
                return None  # one-time chore is in the past, no next start datetime

        # For repeat chores, calculate the next start datetime based on the repeat settings

        if self.get('repeat_interval') == 'daily':
            if self.get('repeat_time_of_day') == 'specific':
                chore_time_usertz = self.get_chore_time_usertz()
                print('250 chore_time_usertz=', chore_time_usertz)
                dt_usertz = datetime.datetime.combine(now_dt_usertz.date(), chore_time_usertz)
                print('252 dt_usertz=', dt_usertz)
                dt_utc = get_utc_from_users_time(dt_usertz, self.user)
                print('253 dt_utc=', dt_utc)
                if dt_utc < datetime.datetime.now(datetime.timezone.utc):
                    dt_utc += datetime.timedelta(days=1)
                    print('257 dt_utc=', dt_utc)
                print('258 return dt_utc=', dt_utc)
                return dt_utc
            else:
                for time_of_day in ['morning', 'afternoon', 'evening']:
                    if self.get('repeat_time_of_day', None) == time_of_day:
                        chore_time_usertz = self.get_chore_time_usertz()
                        dt_usertz = datetime.datetime.combine(now_dt_usertz.date(), chore_time_usertz)
                        dt_utc = get_utc_from_users_time(dt_usertz, self.user)
                        if dt_utc < datetime.datetime.now(datetime.timezone.utc):
                            dt_utc += datetime.timedelta(days=1)
                        return dt_utc


        elif self.get('repeat_interval') == 'weekly':
            # set the time
            chrore_time_usertz = self.get_chore_time_usertz()
            dt_usertz = datetime.datetime.combine(now_dt_usertz.date(), chrore_time_usertz)

            # go forward until with day+=1 we are on the correct day

            correct_day_of_week_index = [
                'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'
            ].index(self.get('repeat_day_of_week'))

            i = 0
            while i < 7:
                if dt_usertz.weekday() == correct_day_of_week_index and dt_usertz > now_dt_usertz:
                    dt_utc = get_utc_from_users_time(dt_usertz, self.user)
                    return dt_utc
                dt_usertz += datetime.timedelta(days=1)
                i += 1


        elif self.get('repeat_interval') == 'other':
            timedelta_kwargs = {}
            if self.get('repeat_units') == 'day':
                timedelta_kwargs['days'] = self.get('repeat_every_number_of', 1)
            elif self.get('repeat_units') == 'week':
                timedelta_kwargs['days'] = self.get('repeat_every_number_of', 1) * 7

            chore_time_usertz = self.get_chore_time_usertz()
            print('247 chore_time_usertz=', chore_time_usertz)
            dt_usertz = datetime.datetime.combine(now_dt_usertz.date(), chore_time_usertz)
            print('249 dt_usertz=', dt_usertz)
            if self.get('repeat_units') == 'month':
                # bump the dt out by x num of months
                num_months = self.get('repeat_every_number_of', 1)
                dt = dt_usertz.replace(month=(dt_usertz.month - 1 + num_months) % 12 + 1,
                                       year=dt_usertz.year + (dt_usertz.month - 1 + num_months) // 12)
            else:
                dt_usertz = dt_usertz + datetime.timedelta(**timedelta_kwargs)
            print('259 dt_usertz=', dt_usertz)
            dt_utc = get_utc_from_users_time(dt_usertz, self.user)
            return dt_utc

        return None

    @property
    def user(self):
        return self.app.db.FindOne(ring_user.RingUser, id=self['owner_id'])

    def get_chore_time_usertz(self) -> Optional[datetime.time]:
        '''
        This returns only the datetime.time that this chore should be assigned
        The return datetime.time() is in user_local_timezone
        '''
        if self.get('repeat_time_of_day') == 'specific':
            repeat_time_str: Optional[str] = self.get('repeat_time', None)
            if isinstance(repeat_time_str, str):
                repeat_time_dt = datetime.datetime.strptime(
                    repeat_time_str,
                    '%H:%M'
                )
                return repeat_time_dt.time()
            else:
                return None
        else:
            user = self.app.db.FindOne(ring_user.RingUser, id=self['owner_id'])
            for time_of_day in ['morning', 'afternoon', 'evening']:
                if self.get('repeat_time_of_day', None) == time_of_day:
                    time_str = user.get_chore_settings().get(f'{time_of_day}_time')
                    print('time_str=', time_str)
                    time = datetime.datetime.strptime(time_str, '%H:%M:%S').time()
                    return time


def get_utc_from_users_time(dt: datetime.datetime, user: ring_user.RingUser):
    '''
    The jobs are scheduled in UTC.
    So adjust the datetime from the users timezone to UTC,
    including daylight savings if the user has it enabled.
    '''
    user_tz = user.get('timezone', 'UTC')

    if user_tz == 'UTC':
        return dt.replace(tzinfo=datetime.timezone.utc)
    else:
        tz = pytz.timezone(user_tz)
        dt_with_tz = tz.localize(dt)
        dt_utc = dt_with_tz.astimezone(pytz.utc)
        # adjust for daylight savings if the user has it enabled
        if user.get('enable_daylight_savings', True):
            if dt_with_tz.dst():
                dt_utc -= dt_with_tz.dst()

        return dt_utc


def get_user_local_dt_from_utc(dt: datetime.datetime, user: ring_user.RingUser):
    if dt is None or dt.tzinfo is not None and dt.tzinfo not in (
            pytz.UTC,
            datetime.timezone.utc,
    ):
        raise ValueError(
            "A datetime passed to this function need to have no timezone "
            "info or need to use the UTC timezone."
        )

    user_has_dst = user.get('enable_daylight_savings', True)
    user_tz = pytz.timezone(user.get('timezone', 'UTC'))

    dt_utc = pytz.utc.localize(dt)

    local_dt = dt_utc.astimezone(user_tz)
    if user_has_dst and local_dt.dst():
        local_dt += local_dt.dst()

    return local_dt


def assign_chore_to_persons(chore_id: int):
    print('assign_chore_to_persons(chore_id=', chore_id, ')')
    with app.app_context():
        app.db = cast(Dictabase, app.db)
        chore: Chore = app.db.FindOne(Chore, id=chore_id)

        if chore is None:
            print(f"Chore with id {chore_id} not found.")
            return

        possible_assignees = chore.get_can_be_assigned_to_persons()
        if not possible_assignees:
            print(f"No possible assignees for chore '{chore['name']}' (id: {chore_id}).")
            return

        if chore.get('assignment_mode') in ['all', 'first-done']:
            for person in possible_assignees:
                chore.assign_to(person)

        elif chore.get('assignment_mode') == 'random':
            person = random.choice(possible_assignees)
            chore.assign_to(person)

        return chore


def get_persons(user: ring_user.RingUser):
    print('user=', user)
    print('user.is_wall_user=', user.is_wall_user)

    with app.app_context():
        ring_user = user.get_ring_user()
        print('ring_user.is_wall_user=', ring_user.is_wall_user)
        ret = list(app.db.FindAll(Person, owner_id=ring_user['id']))
        print('ret=', ret)
        return ret

def get_chores(user: ring_user.RingUser):
    with app.app_context():
        ring_user = user.get_ring_user()
        ret = list(app.db.FindAll(Chore, owner_id=ring_user['id']))
        print('get_chores ret=', ret)
        return ret