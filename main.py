import time

import flask_dictabase
from flask import Flask, request
from flask_jobs import JobScheduler

import ring_token_endpoints

app = Flask('Is Your Room Clean')
app.db = flask_dictabase.Dictabase(app)
app.jobs = JobScheduler(
    app,
    SERVER_HOST_URL='https://beta.domainservices.biz/',  # only required for linux
    deleteOldJobs=False,  # whether to keep old jobs in the database
)

ring_token_endpoints.setup(app)


@app.route('/')
def index():
    return 'Welcome to IsYourRoomClean'


@app.route('/dashboard')
def dashboard():
    # Ring calls this the "App Homepage"
    return 'Dashboard pladeholder'


@app.route('/test')
def test():
    return 'The time is ' + time.asctime()


@app.route('/webhook')
def webhook():
    return 'webhook placeholder'


if __name__ == '__main__':
    app.run(port=3888, debug=True)
