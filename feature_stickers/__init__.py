import datetime
import html
import json
import random
from typing import cast

from flask import Flask, jsonify, request
import pytz
import requests
from flask_jobs import Job, JobScheduler

from app_types import Application


def setup(a: Application):
    global app
    app = a

    @app.route('/stickers/random_emoji/<int:number>')
    def random_emoji(number: int):
        return jsonify(get_random_emoji(number))

    @app.route('/stickers/add/<int:person_id>', methods=['POST'])
    def add_sticker(person_id: int):

        person = app.get_person(person_id)
        if not person:
            return jsonify({"error": "Person not found"}), 404

        payload = request.get_json(silent=True)
        stickers = payload.get('stickers') if isinstance(payload, dict) else None
        if (
            not isinstance(stickers, list)
            or not stickers
            or any(
                not isinstance(sticker, str) or not sticker for sticker in stickers
            )
        ):
            return jsonify({"error": "A non-empty list of stickers is required"}), 400

        credits = person.get('sticker_credits', 0) or 0
        if len(stickers) != credits:
            return jsonify({"error": "Sticker count must match available credits"}), 400

        person["stickers"] = json.dumps(person.get_stickers() + stickers)
        person['sticker_credits'] = 0
        return jsonify(person.ui_safe())

def update_archive_sticker_job():
    with app.app_context():
        # archive the stickers weekly
        job_name = 'archive_stickers_weekly'
        job:Job = app.jobs.Find(name=job_name)
        if job:
            job.Delete()
        app.jobs = cast(JobScheduler, app.jobs)
        startDT = datetime.datetime.now(pytz.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        for _ in range(7):
            if startDT.weekday() == 6:  # job should run on Sunday
                break
            startDT += datetime.timedelta(days=1)
    
        new_job = app.jobs.RepeatJob(
            name=job_name,
            startDT=startDT,
            days=7,
        )
        print('new_job=', new_job)


def get_random_emoji(number: int):
    ret = []
    for _ in range(number):
        categories = [
            "smileys and people",
            "animals and nature",
            "food and drink",
            "travel and places",
            "activities",
            "objects",
            "symbols",
            "flags",
        ]
        category = random.choice(categories)
        resp = requests.get(
            f'https://emojihub.yurace.pro/api/random/category/{category.replace(" ", "%20")}'
        )
        resp.raise_for_status()
        data = resp.json()
        ret.append(html.unescape(data['htmlCode'][0]))
    return ret

def archive_stickers(person_id: int):
    with app.app_context():
        person = app.get_person(person_id)
        if not person:
            return jsonify({"error": "Person not found"}), 404
        old_archive = person.Get('sticker_archive', []) or []
        new_archive = old_archive + person.get_stickers()
        person.Set('sticker_archive', new_archive)
        person.Set('stickers', [])
        return jsonify(person.ui_safe())