import os
import hmac
import hashlib
import config

from flask import Flask, request, jsonify


# Store this in an environment variable, not in source control.
HMAC_KEY = config.RING_HMAC_SIGNATURE_KEY


def verify_ring_webhook_signature(
    signing_key: str,
    raw_body: bytes,
    received_signature: str,
) -> bool:
    """
    Verify a Ring webhook HMAC-SHA256 signature.

    Ring signs the raw HTTP request body using HMAC-SHA256
    and sends the hex digest in the X-Signature header.
    """

    if not received_signature:
        return False

    expected_signature = hmac.new(
        signing_key.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    # Ring documents the signature as:
    #   sha256=<signature>
    received_signature = received_signature.lstrip("sha256=")

    # Constant-time comparison to prevent timing attacks.
    return hmac.compare_digest(
        expected_signature,
        received_signature,
    )


def store_webhook(payload):
    """
    TODO: Store the webhook in the database.

    You probably want to store at least:
      - request_id
      - event_id
      - event_type
      - account_id
      - device_id
      - received_at
      - payload

    Make request_id unique so duplicate Ring deliveries
    can be safely ignored.
    """

    # Example:
    #
    # webhook = Webhook(
    #     request_id=payload["meta"]["request_id"],
    #     event_id=payload["data"]["id"],
    #     event_type=payload["data"]["type"],
    #     account_id=payload["meta"]["account_id"],
    #     payload=payload,
    # )
    #
    # db.session.add(webhook)
    # db.session.commit()

    pass


@app.route("/webhook", methods=["POST"])
def webhook():
    # IMPORTANT:
    # Use request.get_data() rather than request.json here.
    # The HMAC must be calculated against the exact raw bytes
    # Ring sent.
    raw_body = request.get_data()

    # Get Ring's signature.
    signature = request.headers.get("X-Signature")

    # Authenticate the webhook BEFORE parsing/processing it.
    if not verify_ring_webhook_signature(
        HMAC_KEY,
        raw_body,
        signature,
    ):
        return jsonify({
            "error": "Invalid signature"
        }), 401

    # Now that the message is authenticated, parse the JSON.
    try:
        payload = request.get_json()
    except Exception:
        return jsonify({
            "error": "Invalid JSON"
        }), 400

    if not payload:
        return jsonify({
            "error": "Empty payload"
        }), 400

    # Basic payload validation.
    meta = payload.get("meta", {})
    data = payload.get("data", {})

    request_id = meta.get("request_id")
    account_id = meta.get("account_id")
    event_id = data.get("id")
    event_type = data.get("type")

    if not request_id or not event_id or not event_type:
        return jsonify({
            "error": "Invalid webhook payload"
        }), 400

    # TODO: Check whether request_id has already been processed.
    #
    # if webhook_exists(request_id):
    #     return jsonify({"status": "already_processed"}), 200

    # Store the authenticated webhook.
    store_webhook(payload)

    # TODO: Eventually dispatch the event to your application.
    #
    # if event_type == "motion_detected":
    #     handle_motion_detected(payload)
    #
    # elif event_type == "button_press":
    #     handle_button_press(payload)
    #
    # elif event_type == "device_added":
    #     handle_device_added(payload)
    #
    # etc.

    return jsonify({
        "status": "processed"
    }), 200