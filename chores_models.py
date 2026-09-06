from typing import List, Literal, Optional

from flask_dictabase import BaseTable

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


class Person(BaseTable):
    name: str
    chores_assigned: List["Chore"] = []
    chores_completed: List["Chore"] = []
    owner_id: int

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

    def assign_to(self, person: Person) -> None:
        '''
        Assign the chore to a specific person.
        '''
        self.Append('assigned_to', person['id'], allowDuplicates=False)

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

    def mark_incomplete_by(self, person_id: int) -> None:
        '''
        Mark the chore as incomplete by a specific person.
        '''
        self.Remove('completed_by', person_id, removeAll=True)
