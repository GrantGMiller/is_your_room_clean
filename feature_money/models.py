
from typing import Optional
import datetime
from flask_dictabase import BaseTable
class MoneyTransaction(BaseTable):
    from_id: Optional[int]
    to_id: Optional[int]
    amount: int
    timestamp: float # seconds
    message: str

    def get_from_person(self):
        return self.app.get_person(self.get('from_id', None))

    def get_to_person(self):
        return self.app.get_person(self.get('to_id', None))

    def get_from_name(self):
        from_person = self.get_from_person()
        return from_person.get('name') if from_person else 'someone'

    def get_to_name(self):
        to_person = self.get_to_person()
        return to_person.get('name') if to_person else 'someone'

    def get_dt_utc(self):
        timestamp = self.get('timestamp', None)
        if timestamp is not None:
            return datetime.datetime.fromtimestamp(
                float(timestamp),
                tz=datetime.timezone.utc,
            )
        return None

    def get_dt_usertz(self):
        dt_utc = self.get_dt_utc()
        if dt_utc is not None:
            return self.app.get_user_local_dt_from_utc(
                dt_utc, 
                self.app.get_current_user().get_ring_user()
                )
        return None
