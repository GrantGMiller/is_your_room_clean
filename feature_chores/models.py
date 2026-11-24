import datetime
import json
import random
import time
from typing import Dict, List, Literal, Optional, cast

import pytz
from flask import flash
from flask_dictabase import BaseTable
from flask_jobs import Job

from app_types import Application
from feature_money.models import MoneyTransaction
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

LastCompleted = Dict[int, datetime.datetime.isoformat]
# LastCompleted is a dictionary where the key is the person_id and the value is the datetime when they last completed the chore.

app: Application


def setup(a: Application):
    global app
    app = a


class Person(BaseTable):
    name: str
    color: Optional[PersonColor] = "primary"
    owner_id: int
    nintendo_device_name: Optional[str] = None
    money: int = 0
    sticker_credits: int = 0
    stickers: List[str] = []
    sticker_archive: List[str] = []
    num_of_completed_chores: int = 0

    def inc_completed_chore_count(self):
        self['num_of_completed_chores'] = (self.get('num_of_completed_chores', 0) or 0) + 1
        if self['num_of_completed_chores'] % 15 == 0:
            self['sticker_credits'] = (self.get('sticker_credits', 0) or 0) + 1

    def get_stickers(self) -> List[str]:
        stickers = self.Get('stickers', []) or []
        return stickers

    def ui_safe(self):
        ret = {
            "id": self.get("id", None),
            "name": self.get("name", None),
            "color": self.get("color", None),
            "owner_id": self.get("owner_id", None),
            "nintendo_device_name": self.get("nintendo_device_name", None),
            "nintendo_time": self.get('nintendo_time', 0) or 0,
            "money": self.get('money', 0) or 0,
            "sticker_credits": self.get('sticker_credits', 0) or 0,
            "num_of_completed_chores": self.get('num_of_completed_chores', 0) or 0,
            "stickers": self.get_stickers(),
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

    def add_money(self, amount: int, message: str, from_person_id: Optional[int] = None):
        self['money'] = (self.get('money', 0) or 0) + amount
        self.app.db.New(
            MoneyTransaction,
            from_id=int(from_person_id) if from_person_id else None,
            to_id=int(self['id']),
            amount=amount,
            timestamp=time.time(),
            message=message
        )
        if from_person_id is not None:
            from_person = self.app.get_person(from_person_id)
            if from_person:
                from_person['money'] = (from_person.get('money', 0) or 0) - amount

    def send_money(self, amount: int, message: str, to_person_id: Optional[int] = None):
        new_money = (self.get('money', 0) or 0) - amount
        if new_money < 0:
            flash('You do not have enough money', 'danger')
            return

        self['money'] = new_money
        self.app.db.New(
            MoneyTransaction,
            from_id=int(self['id']),
            to_id=int(to_person_id) if to_person_id else None,
            amount=amount,
            timestamp=time.time(),
            message=message
        )
        if to_person_id is not None:
            other_person = self.app.get_person(to_person_id)
            if other_person:
                other_person['money'] = (other_person.get('money', 0) or 0) + amount


Assignees = List[Person]


class Chore(BaseTable):
    name: str
    kind: ChoreKind
    assignment_mode: Optional[AssignmentMode] = None
    schedule_for: Optional[str] = None  # ex. '%Y-%m-%dT%H:%M'
    repeat_interval: Optional[RepeatInterval] = None
    repeat_day_of_week: Optional[List[RepeatDay]] = None
    repeat_time_of_day: Optional[List[RepeatTimeOfDay]] = None
    repeat_time: Optional[str] = None  # user local timezone
    repeat_every_number_of: Optional[int] = None
    repeat_units: Optional[RepeatUnit] = None
    owner_id: int
    tags: List[str] = []
    # job_id: Optional[int] = None # deprecated
    last_completed: LastCompleted
    enabled: bool
    reward: int = 0  # money reward for completing this chore
    jobs: Dict[int, List[int]] = {}  # {int(person_id): [int(job_id1), int(job_id2)]}

    def ui_safe(self):
        next_assignment_dt_utc_iso = self.get_next_start_dt_utc()
        if next_assignment_dt_utc_iso:
            next_assignment_dt_utc_iso = next_assignment_dt_utc_iso.isoformat()
        ret = {
            'assigned_to': self.get_assigned_to_ids(),
            'can_be_assigned_to_ids': self.get_can_be_assigned_to_ids(),
            "assignment_mode": self.get('assignment_mode', None),
            "kind": self.get('kind', None),
            "name": self.get('name', None),
            "owner_id": self.get('owner_id', None),
            "repeat_day_of_week": self.Get('repeat_day_of_week', None),
            "repeat_every_number_of": self.get('repeat_every_number_of', None),
            "repeat_interval": self.get('repeat_interval', None),
            "repeat_time_of_day": self.get_repeat_time_of_day(),
            "repeat_time": self.get('repeat_time', None),
            "repeat_units": self.get('repeat_units', None),
            "schedule_for": self.get('schedule_for', None),
            "tags": self.get('tags', None),
            "next_assignment_dt_utc_iso": next_assignment_dt_utc_iso,
            "assignment_job_id": self.get('job_id', None),
            "last_completed": self.get('last_completed', {}),
            'enabled': self.get('enabled', False),
            'reward': self.get('reward', 0),
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

    def assign_to_person_id(self, person_id: int) -> None:
        self.Append('assigned_to', person_id, allowDuplicates=False)
        self.Remove('completed_by', person_id, removeAll=True)

    def unassign(self, person: Person) -> None:
        print('chore.unassign', person)
        print('150 chore.Get("assigned_to")=', self.Get('assigned_to', None))
        self.Remove('assigned_to', person['id'], removeAll=True)
        print('152 chore.Get("assigned_to")=', self.Get('assigned_to', None))

    def unassign_all(self) -> None:
        '''
        Unassign all persons from the chore.
        '''
        self.Set('assigned_to', [])

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

    def get_delta(self) -> Optional[datetime.timedelta]:
        # return the timedelta between two assignments
        # for example, if this repeats every 2 days then it will return a timedelta(days=2)

        if self.get('repeat_interval') == 'daily':
            return datetime.timedelta(days=1)
        elif self.get('repeat_interval') == 'weekly':
            # 'weekly' can mean every tues/thurs 
            least_num_days = 7
            day_names = []

            temp_dt_usertz = get_user_local_dt_from_utc(datetime.datetime.now(datetime.timezone.utc), self.user)
            for i in range(7):
                day_names.append((temp_dt_usertz).strftime('%A').lower())
                temp_dt_usertz += datetime.timedelta(days=1)

            selected_day_names = self.Get('repeat_day_of_week', []) or []
            for selected_day_name1 in selected_day_names:
                for selected_day_name2 in selected_day_names:
                    if selected_day_name1 != selected_day_name2:
                        diff = abs(day_names.index(selected_day_name1) - day_names.index(selected_day_name2))
                        if diff < least_num_days:
                            least_num_days = diff

            return datetime.timedelta(days=least_num_days)

        elif self.get('repeat_interval') == 'other':
            repeat_units = self.get('repeat_units', 'days')
            repeat_value = self.get('repeat_every_number_of', 1)
            print('285 get_delta: repeat_units:', repeat_units, 'repeat_value:', repeat_value)
            print('self=', self)
            if repeat_units == 'days':
                return datetime.timedelta(days=repeat_value)
            elif repeat_units == 'weeks':
                return datetime.timedelta(days=repeat_value * 7)
            elif repeat_units == 'month':
                return datetime.timedelta(days=repeat_value * 30)
            else:
                return None
        else:
            return None

    def get_next_chore_time_dt_utc(self, dt_utc: datetime.datetime) -> Optional[datetime.datetime]:
        dt_usertz = get_user_local_dt_from_utc(dt_utc, self.user)
        now_usertz = datetime.datetime.now(pytz.timezone(self.user.get('timezone', 'UTC')))
        chore_times_usertz = self.get_chore_times_usertz()
        for chore_time_usertz in chore_times_usertz:
            this_dt_usertz = datetime.datetime.combine(
                dt_usertz.date(),
                chore_time_usertz,
                tzinfo=dt_usertz.tzinfo
            )
            if this_dt_usertz > now_usertz:
                return get_utc_from_users_time(
                    this_dt_usertz,
                    self.user
                )
        else:
            return dt_utc

    def get_last_completed_dt_utc(self, person_id: Optional[int] = None) -> Optional[datetime.datetime]:
        '''

        :param person_id: pass this if you want the last time a specific person completed this chore,
            if None then return the most recent time ANYONE completed the chore
        :return: datetime.datetime with pytz.utc
        '''
        if person_id:
            iso = self.GetItem('last_completed', str(person_id), None)

            if iso:
                dt_utc = datetime.datetime.fromisoformat(iso)
                return dt_utc
            else:
                return None
        else:
            if self.get('assignment_mode') == 'all':
                isos = []
                for person_id, iso in self.Get('last_completed', {}).items():
                    # only look at isos for persons this chore can be assigned to
                    if int(person_id or -1) in self.get_can_be_assigned_to_ids():
                        isos.append(iso)
                isos = list(filter(None, isos))  # filter out any blank isos
                print('332 isos=', isos)
                if len(list(isos)) == 0:
                    print('334 return None')
                    return None
                last_completed_iso = min(
                    list(isos)
                )
                ret = datetime.datetime.fromisoformat(last_completed_iso) if last_completed_iso else None
                print('340 return {}'.format(ret))
                return ret

            elif self.get('assignment_mode') in ['first-done', 'random']:
                isos = list(filter(None, (self.Get('last_completed', {}) or {}).values()))
                # send_slack_message("299 isos=", isos)
                if len(list(isos)) == 0:
                    # send_slack_message('300 return None')
                    return None
                last_completed_iso = max(
                    list(isos)
                )
                return datetime.datetime.fromisoformat(last_completed_iso) if last_completed_iso else None

            return None

    def mark_incomplete_by(self, person_id: int) -> None:
        '''
        Mark the chore as incomplete by a specific person.
        '''
        self.Remove('completed_by', person_id, removeAll=True)

        self.SetItem('last_completed', str(person_id), None)

        if self.get('assignment_mode') == 'first-done':
            for person in self.get_can_be_assigned_to_persons():
                self.assign_to(person)

    def clear_completed_by(self) -> None:
        self.Set('completed_by', [])

    def get_scheduled_job_dt_utc(self) -> Optional[datetime.datetime]:
        print('393 get_scheduled_job_dt_utc')
        return self.get_next_start_dt_utc()

    def refresh_scheduled_job(self) -> None:
        '''
        We will use one job per person/assignments.
        We will also use one job per day. So if the job repeats on tues/thurs
          then the self['jobs'] will look like {
            person_id: [job_id1, job_id2]
                }
        
        '''
        print('refresh_scheduled_job')
        # delete deprecated job
        job_id = self.get('job_id', None)
        if job_id:
            job = app.jobs.GetJob(job_id)
            if job:
                job.Delete()

        # Delete all existing jobs for all persons
        for _, job_ids in self.Get('jobs', {}).items():
            for job_id in job_ids:
                job = self.app.jobs.GetJob(job_id)
                if job:
                    print('deleting old job=', job)
                    job.Delete()
        self.Set('jobs', {})

        def append_job(person_id: int, job: Job):
            print('append_job person_id=', person_id, ', job=', job)
            these_job_ids = (self.Get('jobs', {}) or {}).get(str(person_id), [])
            these_job_ids.append(job['id'])
            self.SetItem('jobs', str(person_id), these_job_ids)

        # if this is a AssignmentMode 'all' or 'first-done', then we make
        #  one job per person

        person_ids = []
        if self.get('assignment_mode') in ['all', 'first-done']:
            person_ids = [person['id'] for person in self.get_can_be_assigned_to_persons()]
        elif self.get('assignment_mode') == 'random':
            person_ids = [-1]  # this means we will pick the person to assign it to later

        # create new job(s)
        for person_id in person_ids:
            if self.get('repeat_interval') == 'daily':
                for chore_time_usertz in self.get_chore_times_usertz():
                    this_day_of_week_date = datetime.datetime.today()
                    start_dt_usertz = datetime.datetime.combine(this_day_of_week_date.date(), chore_time_usertz)
                    start_dt_utc = get_utc_from_users_time(start_dt_usertz, self.user)

                    new_job = self.app.jobs.RepeatJob(
                        func=assign_chore_to_persons,
                        kwargs={
                            'chore_id': self['id'],
                            'person_id': person_id
                        },
                        startDT=start_dt_utc,
                        errorCallback=send_slack_error,
                        name=f"Assign chore '{self['name']}' to person_id={person_id} at {start_dt_usertz}",
                        days=1,
                    )

                    append_job(person_id, new_job)

            elif self.get('repeat_interval') == 'weekly':
                day_names = [
                    'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'
                ]
                for day_of_week in self.Get('repeat_day_of_week', []) or []:
                    this_day_of_week_date = datetime.datetime.today()
                    for _ in range(7):
                        if day_names[this_day_of_week_date.weekday()] != day_of_week:
                            this_day_of_week_date -= datetime.timedelta(days=1)
                        else:
                            break

                    for chore_time_usertz in self.get_chore_times_usertz():
                        start_dt_usertz = datetime.datetime.combine(this_day_of_week_date.date(), chore_time_usertz)
                        start_dt_utc = get_utc_from_users_time(start_dt_usertz, self.user)

                        new_job = self.app.jobs.RepeatJob(
                            func=assign_chore_to_persons,
                            kwargs={
                                'chore_id': self['id'],
                                'person_id': person_id
                            },
                            startDT=start_dt_utc,
                            errorCallback=send_slack_error,
                            name=f"Assign chore '{self['name']}' to person_id={person_id} at {start_dt_usertz}",
                            days=7,
                        )

                        append_job(person_id, new_job)

            elif self.get('repeat_interval') == 'other':
                repeat_every_num_of = max(1, int(self.get('repeat_every_number_of', 1) or 1))

                interval_days = 1

                if self.get('repeat_units') == 'day':
                    interval_days = 1 * repeat_every_num_of

                elif self.get('repeat_units') == 'week':
                    interval_days = 7 * repeat_every_num_of

                elif self.get('repeat_units') == 'month':
                    interval_days = 30 * repeat_every_num_of

                this_day_of_week_date = datetime.datetime.today()
                for chore_time_usertz in self.get_chore_times_usertz():
                    start_dt_usertz = datetime.datetime.combine(this_day_of_week_date.date(), chore_time_usertz)
                    start_dt_utc = get_utc_from_users_time(start_dt_usertz, self.user)

                    new_job = self.app.jobs.RepeatJob(
                        func=assign_chore_to_persons,
                        kwargs={
                            'chore_id': self['id'],
                            'person_id': person_id
                        },
                        startDT=start_dt_utc,
                        errorCallback=send_slack_error,
                        name=f"Assign chore '{self['name']}' to person_id={person_id} at {start_dt_usertz}",
                        days=interval_days,
                    )

                    append_job(person_id, new_job)

    def get_next_start_dt_utc(self, person_id: Optional[int] = None) -> Optional[datetime.datetime]:
        '''
        Get the next start datetime for the chore, based on its repeat settings.
        If the chore is a one-time chore, return None.
        The return datetime is in UTC
        '''
        if self.get('kind') == 'one-time':
            return None

        all_job_dts = []
        data = (self.Get('jobs', {}) or {})
        print('565 jobs=', data)
        for this_person_id, job_ids in data.items():
            print('565 this_person_id=', this_person_id, 'job_ids=', job_ids)
            if person_id is not None and int(person_id) != this_person_id:
                print('571 continue')
                continue
            for job_id in job_ids:
                print('574 job_id=', job_id)
                job = self.app.jobs.GetJob(job_id)
                print('574 found job=', job)
                if job and job['dt']:
                    all_job_dts.append(job['dt'])
        print('576 all_job_dts=', all_job_dts)
        ret = min(all_job_dts) if all_job_dts else None
        print('578 ret=', ret)
        return ret

    @property
    def user(self):
        from ring import user as ring_user

        return self.app.db.FindOne(ring_user.RingUser, id=self['owner_id'])

    def get_repeat_time_of_day(self) -> List[RepeatTimeOfDay]:
        # just in case the chore has an old repeat_time_of_day
        repeat_times = self.get('repeat_time_of_day')
        if not repeat_times:
            return []

        if isinstance(repeat_times, str):
            try:
                repeat_times = json.loads(repeat_times)
            except json.JSONDecodeError:
                pass

        if isinstance(repeat_times, str):
            if repeat_times in ('morning', 'afternoon', 'evening', 'specific'):
                return [cast(RepeatTimeOfDay, repeat_times)]
            return []
        if isinstance(repeat_times, list):
            return repeat_times
        return []

    def get_chore_times_usertz(self) -> List[datetime.time]:
        repeat_times = self.get_repeat_time_of_day()
        user_settings = self.user.get_chore_settings()
        chore_times = []
        for time_of_day in repeat_times or []:
            if time_of_day == 'specific':
                repeat_time = self.get('repeat_time')
                if isinstance(repeat_time, str):
                    try:
                        chore_times.append(
                            datetime.datetime.strptime(repeat_time, '%H:%M').time()
                        )
                    except ValueError:
                        pass
            elif time_of_day in ['morning', 'afternoon', 'evening']:
                time_string = user_settings.get(f'{time_of_day}_time')
                if isinstance(time_string, str):
                    for time_format in ['%H:%M:%S', '%H:%M']:
                        try:
                            chore_times.append(
                                datetime.datetime.strptime(
                                    time_string, time_format
                                ).time()
                            )
                            break
                        except ValueError:
                            continue

        return chore_times

    def round_down_to_choretime_dt_utc(self, dt_utc: Optional[datetime.datetime]) -> Optional[datetime.datetime]:
        # if the dt_utc is like 6:37am and the chore times are 6:00am, 7:00am, etc.,
        # round it down to the nearest chore time.
        chore_times_usertz = self.get_chore_times_usertz()
        if dt_utc is None:
            return None
        dt_usertz = get_user_local_dt_from_utc(dt_utc, self.user)
        for chore_time_usertz in sorted(chore_times_usertz, reverse=True):
            if dt_usertz.time() >= chore_time_usertz:
                return get_utc_from_users_time(
                    dt_usertz.replace(hour=chore_time_usertz.hour, minute=chore_time_usertz.minute,
                                      second=chore_time_usertz.second),
                    self.user
                )
        else:
            return dt_utc


def get_utc_from_users_time(dt_usertz: datetime.datetime, user):
    '''
    The jobs are scheduled in UTC.
    So adjust the datetime from the users timezone to UTC,
    including daylight savings if the user has it enabled.
    '''
    from ring import user as ring_user

    user = cast(ring_user.RingUser, user)
    print('426 dt_usertz=', dt_usertz)
    user_tz_str = user.get('timezone') or 'UTC'
    print('user_tz_str=', user_tz_str)

    if user_tz_str == 'UTC':
        return dt_usertz.replace(tzinfo=datetime.timezone.utc)
    else:
        dt_now_utc = datetime.datetime.now(pytz.timezone(user_tz_str))
        print('now.dst=', dt_now_utc.dst())
        user_tz = pytz.timezone(user_tz_str)
        if not dt_usertz.tzinfo:
            dt_with_tz = user_tz.localize(
                dt_usertz,
            )
        else:
            dt_with_tz = dt_usertz.astimezone(user_tz)

        dt_utc = dt_with_tz.astimezone(pytz.utc)

        print('dt_with_tz=', dt_with_tz)
        print('442 return dt_utc=', dt_utc)
        return dt_utc


def get_user_local_dt_from_utc(dt: datetime.datetime, user):
    from ring import user as ring_user

    user = cast(ring_user.RingUser, user)
    if dt is None or dt.tzinfo is not None and dt.tzinfo not in (
            pytz.UTC,
            datetime.timezone.utc,
    ):
        raise ValueError(
            "A datetime passed to this function need to have no timezone "
            "info or need to use the UTC timezone."
        )

    user_has_dst = user.get('enable_daylight_savings', True)
    print('user_has_dst=', user_has_dst)
    user_tz = pytz.timezone(user.get('timezone') or 'UTC')
    print('user_tz=', user_tz)
    if dt.tzinfo is None:
        dt_utc = pytz.utc.localize(dt)
    else:
        dt_utc = dt.astimezone(pytz.utc)
    print('before normalize dt_utc=', dt_utc)
    dt_utc = pytz.utc.normalize(dt_utc)
    print('after normalize dt_utc=', dt_utc)
    # local_dt = dt_utc.astimezone(user_tz)
    local_dt = user_tz.normalize(dt_utc)
    print('local_dt=', local_dt)

    # if user_has_dst and local_dt.dst():
    #     print('469 adjust for dst local_dt.dst()=', local_dt.dst())
    #     local_dt = local_dt.dst()

    print('return local_dt=', local_dt)
    return local_dt


def assign_chore_to_persons(chore_id: int, person_id: int = -1, debug: bool = False):
    '''
    if this is a random chore, then person_id will be -1
    '''
    with app.app_context():
        chore = app.db.FindOne(Chore, id=chore_id)
        if chore is None:
            print(f"Chore with id {chore_id} not found.")
            return
        if chore.get('enabled', False) == False:
            print(f'Chore {chore["name"]} is disbled. No assignment needed.')
            return

        if chore.get('assignment_mode') == 'random':
            potential_persons = chore.get_can_be_assigned_to_persons()
            assign_to_person = random.choice(potential_persons)
            chore.assign_to(assign_to_person)

        else:  # assignment_mode is 'all' or 'first-done'
            if person_id > 0:
                chore.assign_to_person_id(person_id)
            else:
                # If no specific person_id is provided, assign the chore to all eligible persons
                for person in chore.get_can_be_assigned_to_persons():
                    chore.assign_to(person)
