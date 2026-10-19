import datetime

from flask import Flask, jsonify, redirect, render_template, request, session

from feature_money.models import MoneyTransaction


def setup(a:Flask):
    global app
    app = a

    @app.route('/money/add/<int:person_id>/<int:amount>')
    def add_money(person_id, amount):
        person = app.get_person(person_id)
        if not person:
            return jsonify({'error': 'person not found'}), 500
        
        person.add_money(int(amount), "Added from administrator")
        return jsonify(person.ui_safe())

    @app.route('/money/reduce/<int:person_id>/<int:amount>')
    def reduce_money(person_id, amount):
        person = app.get_person(person_id)
        if not person:
            return jsonify({'error': 'person not found'}), 500
        person.send_money(int(amount), "Taken by administrator")
        return jsonify(person.ui_safe())

    @app.route('/money/set/<int:person_id>/<int:amount>')
    def set_money(person_id, amount):
        person = app.get_person(person_id)
        if not person:
            return jsonify({'error': 'person not found'}), 500
        old_money = person.get('money', 0) or 0
        new_money = int(amount)
        diff = old_money - new_money
        if diff > 0:
            person.send_money(diff, "Reduced by administrator")
        elif diff < 0:
            person.add_money(-diff, "Increased by administrator")
        person['money'] = new_money
        return jsonify(person.ui_safe())

    @app.route('/money/send/<int:person_id>', methods=['GET'])
    def send_money(person_id):
        person = app.get_person(person_id)
        if not person:
            return redirect('/wall_display/person/{}'.format(person_id))

        recent_transactions = list(app.db.FindAll(MoneyTransaction, from_id=person['id'], _orderBy='timestamp', _limit=100))
        recent_transactions.extend(list(app.db.FindAll(MoneyTransaction, to_id=person['id'], _orderBy='timestamp', _limit=100)))
        for transaction in sorted(recent_transactions, key=lambda tx: tx.get('timestamp', 0) or 0, reverse=True):
            if transaction.get('from_id') == person['id'] or transaction.get('to_id') == person['id']:
                transaction_time = transaction.get('timestamp')
                if transaction_time is not None:
                    transaction['dt_utc'] = datetime.datetime.fromtimestamp(
                        float(transaction_time),
                        tz=datetime.timezone.utc,
                    )
                recent_transactions.append(transaction)
        recent_transactions.sort(key=lambda tx: tx.get('timestamp', 0) or 0, reverse=True)

        return render_template(
            'money/send_money.html',
            person=person,
            user=app.get_current_user(),
            all_persons=app.get_all_user_persons(),
            recent_transactions=recent_transactions[:10],
        )

    @app.route('/money/process_transaction', methods=['POST'])
    def process_transaction():
        sender_id = request.form.get('sender_id')
        session_person_id = session.get('person_id')
        if sender_id and session_person_id is not None and int(sender_id) != int(session_person_id):
            return jsonify({'error': 'sender does not match session'}), 400

        recipient_id = request.form.get('recipient_id', type=int)
        amount = request.form.get('amount', type=int)
        if not sender_id or not recipient_id or not amount:
            return jsonify({'error': 'missing sender, recipient, or amount'}), 400
        
        sender = app.get_person(int(sender_id))
        recipient = app.get_person(recipient_id)
        if not sender or not recipient:
            return jsonify({'error': 'sender or recipient not found'}), 400
        
        message = (request.form.get('message') or '').strip()
        sender.send_money(
            int(amount),
            message or "Sent to {}".format(recipient.get('name', 'someone')),
            to_person_id=recipient_id,
        )
        return jsonify({
            'success': True,
            'from_person': sender.ui_safe(),
            'to_person': recipient.ui_safe(),
        })

    @app.route('/money/trade_time', methods=['POST'])
    def trade_time():
        person_id = session.get('person_id')
        if not person_id:
            return jsonify({'error': 'person not found'}), 400
        person = app.get_person(person_id)
        if not person:
            return jsonify({'error': 'person not found'}), 400
        if person.get('nintendo_time', 0) < 60:
            return jsonify({'error': 'not enough Nintendo time to trade'}), 400
        person['nintendo_time'] -= 60
        person['money'] = person.get('money', 0) + 1
        return jsonify(
           person.ui_safe()
        )