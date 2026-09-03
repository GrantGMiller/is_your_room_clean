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
        self.Append('assigned_to', person.id)

    @property
    def is_assigned_to(self) -> List[Person]:
        '''
        This is a list of Persons that the chore is currently assigned to.
        '''
        ids = self.Get('assigned_to', [])
        return [self.app.db.FindOne(Person, id=id, owner_id=self.owner_id) for id in ids]

    def add_tag(self, tag: str):
        self.Append('tags', tag)

    def remove_tag(self, tag: str):
        self.Remove('tags', tag)
