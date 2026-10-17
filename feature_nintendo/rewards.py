from flask import Flask, jsonify, request
from ring.user import RingUser, get_current_user


def setup(a:Flask):
    global app
    app = a

    @app.route('/nintendo/rewards', methods=['POST'])
    def nintendo_rewards():
        user = get_current_user()
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

def reward_user_with_nintendo_time(user_id:int, minutes:int):
    with app.app_context():
        user = app.db.FindOne(RingUser, id=int(user_id))
        if not user:
            return None
        old_minutes = user.GetItem('nintendo_rewards', 'nintendo_reward_minutes', 0) or 0
        user.SetItem('nintendo_rewards', 'nintendo_reward_minutes', old_minutes + minutes)
        return user