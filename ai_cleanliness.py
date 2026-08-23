"""
Room cleanliness evaluation via Google Gemini's vision API, called
directly over REST with `requests` (no google-genai SDK dependency).

pip install requests
"""

import base64
import json

import requests

import config

MODEL = 'gemini-3.7-flash'

GEMINI_URL = (
    'https://generativelanguage.googleapis.com/v1beta/interactions'
)

PROMPT = """You are evaluating a photo of a room for tidiness, for a parental
chore-tracking app. Look at the floor, surfaces, and bed (if visible) for
clutter, scattered items, laundry, or trash.

Respond with ONLY a JSON object, no other text, in this exact shape:
{"cleanliness": <integer 0-100, 100 = spotless>, "summary": "<one short sentence, e.g. 'Toys scattered across the floor.'>"}
"""


def evaluate_cleanliness(image_bytes, mime_type='image/jpeg'):
    """
    Sends a room snapshot to Gemini and returns a cleanliness score.

    Returns:
        {
            "cleanliness": int,
            "summary": str
        }

    Raises:
        requests.HTTPError: On a failed API call.
        ValueError: If Gemini's response isn't parseable JSON.
    """

    encoded_image = base64.b64encode(image_bytes).decode('utf-8')

    payload = {
        "model": MODEL,
        "input": [
            {
                "type": "text",
                "text": PROMPT,
            },
            {
                "type": "image",
                "data": encoded_image,
                "mime_type": mime_type,
            },
        ],
    }

    response = requests.post(
        GEMINI_URL,
        headers={
            'x-goog-api-key': config.GEMINI_API_KEY,
            'Content-Type': 'application/json',
        },
        json=payload,
    )

    response.raise_for_status()

    data = response.json()

    # Find the model's output in the Interactions API response.
    raw_text = None

    for step in data.get("steps", []):
        if step.get("type") != "model_output":
            continue

        for content in step.get("content", []):
            if content.get("type") == "text":
                raw_text = content.get("text")
                break

        if raw_text is not None:
            break

    if raw_text is None:
        raise ValueError(
            f"Unexpected Gemini response shape: {data!r}"
        )

    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Gemini returned non-JSON output: {raw_text!r}"
        ) from e

    cleanliness = result.get('cleanliness')

    if (
            not isinstance(cleanliness, (int, float))
            or isinstance(cleanliness, bool)
            or not 0 <= cleanliness <= 100
    ):
        raise ValueError(
            f"Unexpected cleanliness value: {result!r}"
        )

    summary = result.get('summary', '')

    if not isinstance(summary, str):
        raise ValueError(
            f"Unexpected summary value: {result!r}"
        )

    return {
        'cleanliness': int(cleanliness),
        'summary': summary,
    }


if __name__ == '__main__':
    with open(
            'images/164b205e-b126-4d6c-bdaa-5987cd895432.jpg',
            'rb'
    ) as f:
        image_bytes = f.read()

    res = evaluate_cleanliness(image_bytes=image_bytes)
    '''
    response shape: {'id': 'kjsdnflaj', 'status': 'completed', 'usage': {'total_tokens': 1492, 'total_input_tokens': 1208, 'input_tokens_by_modality': [{'modality': 'image', 'tokens': 1100}, {'modality': 'text', 'tokens': 108}], 'total_cached_tokens': 0, 'total_output_tokens': 26, 'total_tool_use_tokens': 0, 'total_thought_tokens': 258, 'raw_prompt_token': 1413}, 'created': '2026-08-23T03:53:07Z', 'updated': '2026-08-23T03:53:07Z', 'service_tier': 'standard', 'steps': [{'signature': 'EoMICoAIARFNMg8xm6Xw91CKw==', 'type': 'thought'}, {'content': [{'text': '{"cleanliness": 46, "summary": "Clutter and items are scattered across the floor and work surfaces."}', 'type': 'text'}], 'type': 'model_output'}], 'object': 'interaction', 'model': 'gemini-3.7-flash'}
    '''
    print('res=', res)
