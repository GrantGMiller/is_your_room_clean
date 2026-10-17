from flask import Flask, jsonify, request
from feature_chores.models import Person
from ring.helpers import get_user


def setup(a:Flask):
    global app
    app = a

    @app.route('/nintendo/rewards', methods=['POST'])
    def nintendo_rewards():
        user = app.get_current_user()
        if not user:
            return "User not authenticated", 401

        for form_name in [
            'reward-with-nintendo-time', # turn rewards on/off
            'nintendo_reward_minutes', #number of minutes rewarded
            'nintendo_reward_chores', # number of chores completed
        ]:
            form_value = request.json.get(form_name)
            user.SetItem('nintendo_rewards', form_name, form_value)

        return jsonify(user.Get('nintendo_rewards', {}))    

def reward_user_with_nintendo_time(user_id:int,person_id:int, minutes:int):
    with app.app_context():
        person = app.db.FindOne(Person, id=person_id, owner_id=user_id)
        if not person:
            return None
        old_minutes = person.get('nintendo_time', 0) or 0
        person['nintendo_time'] = old_minutes + minutes
        return person

def give_nintendo_reward(user_id, num_chores_complted:dict):
    with app.app_context():
        user = get_user(user_id)
        if not user:
            return None
        if not user.GetItem('nintendo_rewards', 'reward-with-nintendo-time', False):
            return None

        num_chores = user.GetItem('nintendo_rewards', 'nintendo_reward_chores', 0) or 0
        num_minutes = user.GetItem('nintendo_rewards', 'nintendo_reward_minutes', 0) or 0

        minutes_per_chore = num_minutes / num_chores if num_chores > 0 else 0
        if minutes_per_chore <= 0:
            return None

        for person_id, num_chores in num_chores_complted.items():
            reward_user_with_nintendo_time(user_id, person_id, num_chores * minutes_per_chore)