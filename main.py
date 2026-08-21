import time

import flask_dictabase
from flask import Flask, jsonify
from flask_jobs import JobScheduler

import ring_token_endpoints
import ring_webhook_helper
from ring_user import RingUser

app = Flask('Is Your Room Clean')
app.db = flask_dictabase.Dictabase(app)
app.jobs = JobScheduler(
    app,
    SERVER_HOST_URL='https://beta.domainservices.biz/',  # only required for linux
    deleteOldJobs=False,  # whether to keep old jobs in the database
)

ring_token_endpoints.setup(app)
ring_webhook_helper.setup(app)

@app.route('/')
def index():
    return 'Welcome to IsYourRoomClean'


@app.route('/dashboard')
def dashboard():
    # Ring calls this the "App Homepage"
    ring_users = list(app.db.FindAll(RingUser, _limit=25))
    return jsonify([u.ui_safe() for u in ring_users])


@app.route('/test')
def test():
    return 'The time is ' + time.asctime()




if __name__ == '__main__':
    app.run(port=3888, debug=True)
