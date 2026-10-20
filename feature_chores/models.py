import calendar
from curses import flash
import datetime
import json
import random
import time
from typing import Dict, List, Literal, Optional, cast

import pytz
from flask import Flask
from flask_dictabase import BaseTable, Dictabase

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

app: Flask = None


def setup(a: Flask):
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

    def add_money(self, amount: int,  message: str,from_person_id: int = None):
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

    def send_money(self, amount: int, message: str, to_person_id: int=None):
        new_money = (self.get('money', 0) or 0) - amount
        if new_money < 0:
            flash('You do not have enough money')
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
    job_id: Optional[int] = None
    last_completed: LastCompleted
    enabled: bool
    reward: int = 0 # money reward for completing this chore

    def ui_safe(self):
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
            "next_assignment_dt_utc_iso": self.get_next_start_dt_utc().isoformat(),
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

    def get_next_chore_time_dt_utc(self, dt_utc: datetime.datetime) -> Optional[datetime.datetime]:
        dt_usertz = get_user_local_dt_from_utc(dt_utc, self.user)
        now_usertz = datetime.datetime.now(pytz.timezone(self.user.get('timezone', 'UTC')))
        chore_times_usertz = self.get_chore_times_usertz()
        for chore_time_usertz in chore_times_usertz:
            this_dt_usertz = datetime.datetime.combine(
                dt_usertz.date(),
                chore_times_usertz
            )
            if this_dt_usertz > now_usertz:
                return get_utc_from_users_time(
                    this_dt_usertz
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
                #print('return dt_utc=', dt_utc)
                return dt_utc
            else:
                return None
        else:
            if self.get('assignment_mode') == 'all':
                isos = list(filter(lambda x: not x, (self.Get('last_completed', {}) or {}).values()))
                
                # send_slack_message("290 isos=", isos)
                if len(list(isos)) == 0:
                    # send_slack_message('292 return None')
                    return None
                last_completed_iso = min(
                    list(isos)
                )
                return datetime.datetime.fromisoformat(last_completed_iso) if last_completed_iso else None
            elif self.get('assignment_mode') == 'first-done':
                isos = list(filter(lambda x: not x, (self.Get('last_completed', {}) or {}).values()))
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
        print('get_scheduled_job_dt name=', self['name'], self.get('job_id', None))
        if self.get('job_id', None) is not None:
            job = self.app.jobs.GetJob(self.get('job_id'))
            print('job=', job)
            if job is not None:
                ret = job.get('dt', None)
                print('ret=', ret)
                return ret
            else:
                self['job_id'] = None
                return None

        print('225 no job id')
        return None

    def refresh_scheduled_job(self, person_ids: Optional[List[int]] = None) -> None:
        if self.get('job_id', None) is not None:
            old_job = self.app.jobs.GetJob(self.get('job_id'))
            if old_job:
                old_job.Delete()

        if person_ids:
            dt_utc = min([self.get_next_start_dt_utc(person_id) for person_id in person_ids])
        else:
            dt_utc = self.get_next_start_dt_utc()
        print('refresh_scheduled_job: dt_utc=', dt_utc, ', name=', self.get('name'))
        if dt_utc is None:
            print('no scheduled job', self)
            return

        new_job = self.app.jobs.ScheduleJob(
            func=assign_chore_to_persons,
            args=(self['id'],),
            dt=dt_utc,
            errorCallback=send_slack_error,
            name=f"Assign chore '{self['name']}' to persons",
        )
        self['job_id'] = new_job['id']
        print('new_job=', new_job)

    def get_next_start_dt_utc(self, person_id: Optional[int] = None) -> Optional[datetime.datetime]:
        '''
        Get the next start datetime for the chore, based on its repeat settings.
        If the chore is a one-time chore, return None.
        The return datetime is in UTC
        '''
        user_tz = self.user.get('timezone', 'UTC') or 'UTC'
        now_dt_usertz = datetime.datetime.now(tz=pytz.timezone(user_tz))
        now_dt_utc = datetime.datetime.now(datetime.timezone.utc)
                    
        print('250 get_next_start_dt_utc chore=', self['name'])
        if self.get('kind') == 'one-time':
            dt_usertz = datetime.datetime.strptime(self.get('schedule_for'), '%Y-%m-%dT%H:%M') if self.get(
                'schedule_for') else None
            dt_usertz = get_utc_from_users_time(dt_usertz, self.user) if dt_usertz else None
            if dt_usertz and dt_usertz > now_dt_usertz:
                return dt_usertz
            else:
                return None  # one-time chore is in the past, no next start datetime

        # For repeat chores, calculate the next start datetime based on the repeat settings

        chore_times_usertz = self.get_chore_times_usertz()
        if not chore_times_usertz:
            return None

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        if self.get('repeat_interval') == 'daily':
        
            # get the last completed time
            # if this is a 'all' chore, then get the smallest last completed and schedule this +2 days
            # if this a first-done, then get the largest last completed
        
            last_completed_dt_utc = self.get_last_completed_dt_utc(person_id)
            if not last_completed_dt_utc:
                return now_dt_utc

            next_day_dt_utc = last_completed_dt_utc + datetime.timedelta(days=1)
            if next_day_dt_utc < now_dt_utc:
                return self.get_next_chore_time_dt_utc(
                    now_dt_utc
                    )
            else:
                return self.get_next_chore_time_dt_utc(
                    next_day_dt_utc
                    )

        elif self.get('repeat_interval') == 'weekly':
            selected_day_names = self.Get('repeat_day_of_week', []) or []

            if not selected_day_names:
                return None

            day_names = [
                'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'
            ]

            last_completed_dt_utc = self.get_last_completed_dt_utc(person_id)
            next_dt_utc = last_completed_dt_utc or now_dt_utc
            for i in range(7):
                this_day_index = next_dt_utc.weekday()
                if day_names[this_day_index] in selected_day_names:
                    break
                else:
                    next_dt_utc += datetime.timedelta(days=1)
            
            if next_dt_utc < now_dt_utc:
                return self.get_next_chore_time_dt_utc(
                    now_dt_utc
                    )
            else:
                return self.get_next_chore_time_dt_utc(
                    next_dt_utc
                    )

        elif self.get('repeat_interval') == 'other':
            print('324 repeat_interval=', 'other')
            repeat_every_num_of = max(1, int(self.get('repeat_every_number_of', 1) or 1))
            print('repeat_every=', repeat_every_num_of)
            target_date_utc = (self.get_last_completed_dt_utc(person_id) or now_utc).date()
            print('target_date_utc=', target_date_utc)
            print('repeat_units=', self.get('repeat_units', ''))

            if self.get('repeat_units') == 'day':
                target_date_utc += datetime.timedelta(days=repeat_every_num_of)
            elif self.get('repeat_units') == 'week':
                target_date_utc += datetime.timedelta(days=repeat_every_num_of * 7)
            if self.get('repeat_units') == 'month':
                month_index = target_date_utc.month - 1 + repeat_every_num_of
                target_year = target_date_utc.year + month_index // 12
                target_month = month_index % 12 + 1
                target_day = min(
                    target_date_utc.day,
                    calendar.monthrange(target_year, target_month)[1],
                )
                target_date_utc = datetime.date(target_year, target_month, target_day)

            candidates = [
                get_utc_from_users_time(
                    datetime.datetime.combine(target_date_utc, chore_time), self.user
                )
                for chore_time in chore_times_usertz
            ]
            print('candidates=', candidates, ', min=', min(candidates))
            ret_dt_utc = min(candidates)

            if ret_dt_utc > now_utc:
                print('return ret_dt_utc=', ret_dt_utc)
                return ret_dt_utc
            else:
                print('return now_utc=', now_utc)
                return now_utc

        return None

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
                return [repeat_times]

        if isinstance(repeat_times, str):
            return [repeat_times]
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
        dt_with_tz = user_tz.localize(
            dt_usertz,
        )
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


def assign_chore_to_persons(chore_id: int):
    print('assign_chore_to_persons(chore_id=', chore_id, ')')
    with app.app_context():
        app.db = cast(Dictabase, app.db)
        chore: Chore = app.db.FindOne(Chore, id=chore_id)

        if chore and chore.get('enabled', False) is False:
            print(f'Chore {chore["name"]} is disbled. No assignment needed.')
            return

        if chore is None:
            print(f"Chore with id {chore_id} not found.")
            return

        chore.clear_completed_by()
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
