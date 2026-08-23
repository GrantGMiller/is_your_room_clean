import datetime
import sys
import time

import requests

import config

app = None


def setup(a):
    global app
    app = a

    @app.route('/slack_test')
    def slack_test():
        send_slack_message('The time is ' + time.asctime())
        return 'sent slack message'


def send_slack_message(*a):
    print('SendSlackNotification(', a)
    msg = ' '.join([str(aa) for aa in a])
    if app:
        app.jobs.AddJob(
            func=do_send_slack_notification,
            args=(msg,),
            successCallback=None,
            errorCallback=send_error,
        )


def do_send_slack_notification(msg, **kwargs):
    if not isinstance(msg, str):
        msg = str(msg)

    if sys.platform.startswith('win') or sys.platform.startswith('darwin'):
        msg = '***DEV***\r\n' + msg
    else:  # linux
        if 'beta' in config.SERVER_HOST_URL:
            if datetime.datetime.now().date() > datetime.date(
                    year=2026,
                    month=8,
                    day=24 # today
            ):  # dont send me beta notifications perpetually
                return
            msg = f'***  {config.SERVER_HOST_URL}  *** \r\n' + msg
        else:
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
