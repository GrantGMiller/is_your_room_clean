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


Assignees = List[Person]


class Chore(BaseTable):
    name: str
    kind: ChoreKind
    assignment_mode: Optional[AssignmentMode] = None
    schedule_for: Optional[str] = None
    repeat_interval: Optional[RepeatInterval] = None
    repeat_day: Optional[RepeatDay] = None
    repeat_time_of_day: Optional[RepeatTimeOfDay] = None
    repeat_time: Optional[str] = None
    repeat_every: Optional[int] = None
    repeat_unit: Optional[RepeatUnit] = None
    owner_id: int
    tags: List[str] = []

    def ui_safe(self):
        ret = {
            "name": self.get('name', None),
            "kind": self.get('kind', None),
            "assignment_mode": self.get('assignment_mode', None),
            "schedule_for": self.get('schedule_for', None),
            "repeat_interval": self.get('repeat_interval', None),
            "repeat_day": self.get('repeat_day', None),
            "repeat_time_of_day": self.get('repeat_time_of_day', None),
            "repeat_unit": self.get('repeat_unit', None),
            "owner_id": self.get('owner_id', None),
            "tags": self.get('tags', None),
            'assigned_to_ids': self.get_assigned_to_ids(),
            'can_be_assigned_to_ids': self.get_can_be_assigned_to_ids(),
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
        self.Append('tags', tag)

    def remove_tag(self, tag: str):
        self.Remove('tags', tag)
