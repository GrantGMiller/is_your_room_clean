import sys
from typing import cast

import requests
from flask import Flask
from flask_dictabase import BaseTable, Dictabase

import config

app: Flask


def setup(a):
    global app
    app = a

    # @app.route('/slack_test')
    # def slack_test():
    #     send_slack_message('The time is ' + time.asctime())
    #     return 'sent slack message'


def send_slack_message(*a):
    print('send_slack_message(', a)
    msg = ' '.join([str(aa) for aa in a])
    app.db = cast(Dictabase, app.db)
    app.db.New(SlackMessage, message=msg)


def do_send_slack_notification(msg, **kwargs):
    if not isinstance(msg, str):
        msg = str(msg)

    if sys.platform.startswith('win') or sys.platform.startswith('darwin'):
        msg = '***DEV***\r\n' + msg
    else:  # linux
        msg = f'***  {config.SERVER_HOST_URL}  *** \r\n' + msg

    requests.post(
        url=config.SLACK_NOTIFICATION_URL,
        json={'text': msg}
    )


def send_error(err):
    requests.post(
        url=config.SLACK_NOTIFICATION_URL,
        json={'text': f'Error Sending Slack Message: {err}'}
    )


def send_slack_error(job):
    send_slack_message("Error:", job)


class SlackMessage(BaseTable):
    message: str


def send_all_slack_messages():
    print('send_all_slack_messages()')
    with app.app_context():
        app.db = cast(Dictabase, app.db)
        msg = ''
        for sm in app.db.FindAll(SlackMessage):
            msg += sm.get('message', '') + '\r\n'
            app.db.Delete(sm)

        requests.post(
            url=config.SLACK_NOTIFICATION_URL,
            json={'text': msg}
        )
