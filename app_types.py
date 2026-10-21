from __future__ import annotations

from typing import TYPE_CHECKING, Callable, List, Optional

from flask import Flask

if TYPE_CHECKING:
    import datetime

    from flask_dictabase import Dictabase
    from flask_jobs import JobScheduler

    from feature_chores.models import Person
    from ring.user import RingUser


class Application(Flask):
    db: Dictabase
    jobs: JobScheduler
    get_current_user: Callable[[], Optional[RingUser]]
    get_person: Callable[[int], Optional[Person]]
    get_user: Callable[[int], Optional[RingUser]]
    get_all_user_persons: Callable[[], List[Person]]
    get_user_local_dt_from_utc: Callable[
        [datetime.datetime, RingUser], datetime.datetime
    ]
