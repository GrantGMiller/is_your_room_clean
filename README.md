# Did You Clean Your Room?

Did You Clean Your Room? connects Ring cameras to a room-cleanliness dashboard.
When a camera reports motion, the application retrieves a snapshot, uses
Gemini to estimate the room's cleanliness, and displays the score and a summary.
It also includes optional chore management and email notifications.

## How it works

1. A user links a Ring account through the Ring Partner API OAuth flow.
2. Ring motion events reach the application's signed `/webhook` endpoint.
3. The application retrieves a camera snapshot and analyzes it for a
   cleanliness score and summary.
4. The dashboard shows the latest snapshot and analysis for each available
   camera.

The app only has access to events and snapshots available after Ring access is
granted. It cannot backfill events from before authorization. Snapshot requests
are rate-limited per device.

## Features

- Passwordless login by email link, with a six-digit login code.
- Ring account linking, device discovery, signed webhooks, and camera snapshots.
- Gemini-based room cleanliness scores and summaries.
- Optional chore assignment, scheduling, completion tracking, and wall display.
- Optional email notifications for cleanliness and daily chore summaries.
- API endpoints for device, snapshot, and summary access.

## Technology

- Python 3.8 (the version specified in `Pipfile`)
- Flask and Flask-Login
- Flask-Dictabase for application persistence
- Flask-Jobs for scheduled tasks
- Ring Partner API and Ring webhook integration
- Gemini API for image analysis
- AWS SES SMTP for email delivery

## Project layout

| Path | Purpose |
| --- | --- |
| `main.py` | Flask application initialization and core routes |
| `ring/` | Ring user integration, token endpoints, and webhook handling |
| `feature_chores/` | Chore models, helpers, wizard, and UI routes |
| `feature_email/` | Email settings, templates, and scheduled summaries |
| `templates/` | Jinja templates for the application UI and email |
| `static/` | Static assets |

## Local development

Install [Pipenv](https://pipenv.pypa.io/) and Python 3.8, then install the
locked dependencies:

```sh
pipenv sync --dev
```

Create a private `config.py` in the repository root. It is intentionally
ignored by Git because it contains credentials. The application reads settings
from this Python module; it does not load them from `.env` automatically.

At minimum, configure the following values for the corresponding integrations:

| Setting | Purpose |
| --- | --- |
| `SECRET_KEY` | Flask session signing |
| `SERVER_HOST_URL` | Public base URL used for Ring callbacks and login links; include a trailing slash |
| `RING_CLIENT_ID` | Ring Partner API client ID |
| `RING_CLIENT_SECRET` | Ring Partner API client secret |
| `RING_HMAC_SIGNATURE_KEY` | Ring webhook signature verification |
| `GEMINI_API_KEY` | Room image analysis |
| `ADMINS` | List of administrator email addresses |
| `SES_SMTP_SERVER` | SMTP host for outbound email |
| `SES_USERNAME` | SMTP username |
| `SES_PASSWORD` | SMTP password |
| `SLACK_NOTIFICATION_URL` | Slack incoming webhook used for notifications |
| `SELFAPIKEY` | Key used by protected internal API routes |
| `IYRC_KEY` | Key used by the chore migration endpoint |

Set `APP_NAME` and `APP_URL` to customize the displayed application name and
base URL. Feature flags are optional and default to disabled:

```python
ENABLE_CHORES = True
ENABLE_FEATURE_EMAIL_NOTIFICATIONS = False
ENABLE_MIGRATE_CHORES = False
```

Do not commit `config.py`, API keys, webhook signing keys, email credentials, or
other secrets. Use separate credentials for development and production.

Run the development server from the repository root:

```sh
pipenv run python main.py
```

The development entry point listens on port `3888`. For a WSGI deployment, the
repository includes Gunicorn:

```sh
pipenv run gunicorn --bind 0.0.0.0:3888 main:app
```

For Ring integration, configure the Ring Partner API endpoints to point at the
deployed application's `/token_exchange`, `/account_link`,
`/default_redirect`, and `/webhook` routes. The webhook URL must be reachable
by Ring and the signing key must match the Ring configuration.

## API endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/get_devices` | List the linked user's devices |
| `GET` | `/api/get_snapshot/<device_id>` | Retrieve a device snapshot |
| `GET` | `/api/get_summary/<device_id>` | Retrieve the latest cleanliness summary |
| `POST` | `/webhook` | Receive and authenticate Ring webhook events |

API access is authenticated by the application's API key flow. See
[`templates/api-key.html`](templates/api-key.html) for request examples.

## Development checks

HTML and Jinja templates can be checked with the repository's Prettier setup:

```sh
npm ci
npm run format:check
```

Python dependencies include Black as a development dependency:

```sh
pipenv run black --check .
```

The `test_*.py` scripts are manual integration utilities and may require a
running application, external Ring credentials, or other configured services.
