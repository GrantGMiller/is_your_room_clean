from flask import Flask, jsonify


def setup(a:Flask):
    global app
    app = a

    @app.route('/money/add/<int:person_id>/<int:amount>')
    def add_money(person_id, amount):
        person = app.get_person(person_id)
        if not person:
            return jsonify({'error': 'person not found'}), 500
        person['money'] = (person.get('money', 0) or 0) + amount
        return jsonify({"person_id": person_id, "money": person['money']})

    @app.route('/money/reduce/<int:person_id>/<int:amount>')
    def reduce_money(person_id, amount):
        person = app.get_person(person_id)
        if not person:
            return jsonify({'error': 'person not found'}), 500
        person['money'] = (person.get('money', 0) or 0) - amount
        return jsonify({"person_id": person_id, "money": person['money']})

    @app.route('/money/set/<int:person_id>/<int:amount>')
    def set_money(person_id, amount):
        person = app.get_person(person_id)
        if not person:
            return jsonify({'error': 'person not found'}), 500
        person['money'] = amount
        return jsonify({"person_id": person_id, "money": person['money']})