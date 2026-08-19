import time

from flask import Flask

app = Flask('Is Your Room Clean')


@app.route('/test')
def test():
    return 'The time is ' + time.asctime()


if __name__ == '__main__':
    app.run(port=3888, debug=True)
