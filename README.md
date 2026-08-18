# SmartServe Webhook Receiver

Replaces the Make.com scenario with a simpler, faster, more reliable Python service. Handles both **Vapi phone call events** and **website contact form submissions** in one place.

## What it does

When someone calls (833) 350-6821 and the AI calls `save_lead`, Vapi sends the lead data to this webhook. The webhook:

1. **Writes a row to Google Sheets** with the lead info
2. **Sends an email** to you with the same info
3. **Returns a response to Vapi** so the AI says "Perfect, lead saved"

When someone submits the contact form on smartserve.cloud, the same webhook:

1. **Writes a row to Google Sheets** (with `Source: Web Form`)
2. **Sends an email** with the form details
3. **Returns 200 OK** to the form

It also logs Vapi `end-of-call-report` events to Sheets (with the full transcript and recording URL) so you have a record of every call.

## Quick Start

### Option A: Render.com (easiest, ~$7/mo, recommended)

1. Sign up at https://render.com
2. Click **New +** → **Web Service** → **Connect a repo** (or use "Public Git Repository" → point to your fork)
3. Render auto-detects the `render.yaml` and deploys
4. In the Render dashboard, set the environment variables (see below)
5. Your webhook URL will be `https://smartserve-webhook-xxxx.onrender.com/webhook`
6. Update Vapi's serverUrl to this URL
7. Update the contact form on smartserve.cloud to POST here

### Option B: Docker (self-host anywhere)

```bash
# Clone or copy the files
cp .env.example .env
# Edit .env with your real values

# Run
docker-compose up -d

# Check logs
docker-compose logs -f
```

Webhook URL: `http://your-server:5000/webhook`

### Option C: Run locally (testing)

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env
python app.py
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_SHEET_ID` | Yes (for Sheets) | The ID from your Google Sheet URL |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Yes (for Sheets) | Service account JSON as a single string |
| `EMAIL_FROM` | Yes (for email) | Sender email address |
| `EMAIL_TO` | Yes (for email) | Where lead notifications go |
| `SMTP_USER` | Yes (for Gmail) | Gmail address (or other SMTP user) |
| `SMTP_PASS` | Yes (for Gmail) | Gmail app password (not account password) |
| `PORT` | No (default 5000) | Port to listen on |
| `EMAIL_ENABLED` | No (default true) | Set to `false` to disable email |

## Setup: Google Sheets

1. Go to https://console.cloud.google.com/
2. Create a new project (or use existing)
3. Enable the **Google Sheets API**
4. Create a **Service Account**:
   - IAM & Admin → Service Accounts → Create Service Account
   - Name: `smartserve-webhook`
   - Role: Project → Editor
5. Create a key: Actions → Manage Keys → Add Key → Create new key → JSON
6. Copy the JSON content into `GOOGLE_SERVICE_ACCOUNT_JSON` env var (single line)
7. Note the `client_email` from the JSON (looks like `smartserve-webhook@project.iam.gserviceaccount.com`)
8. Open your Google Sheet → Share → paste that email → give it **Editor** access
9. Copy the Sheet ID from the URL and put it in `GOOGLE_SHEET_ID`

## Setup: Gmail App Password

1. Enable 2-Step Verification on your Google account
2. Go to https://myaccount.google.com/apppasswords
3. Create an app password for "Mail" / "Other (SmartServe Webhook)"
4. Copy the 16-char password into `SMTP_PASS`

## Sheet Column Structure

The webhook writes to these columns in order:

| Col | Field | Example |
|---|---|---|
| A | Timestamp | `2026-08-17T21:38:56.729Z` |
| B | Source | `Phone Call` / `Web Form` / `Call Log` |
| C | Name | `Troy Trottier` |
| D | Phone | `403-462-4720` |
| E | Email | `troy@example.com` |
| F | Business | `Rodriguez Plumbing` |
| G | Business type | `plumbing` |
| H | Call volume | `200-500` |
| I | Use case / message | `Missing after-hours calls` |
| J | Urgency | `this-week` |
| K | Callback time | `afternoon` |
| L | Customer number | `+14034624720` |
| M | Call ID | `01a011a9-cf85-...` |
| N | Summary / extra | (varies) |
| O | Transcript | (only for end-of-call-report) |
| P | Recording URL | (only for end-of-call-report) |
| Q | Duration | `84` (seconds) |
| R | End reason | `customer-ended-call` |

Tip: Add a header row in row 1 of your sheet with these column names.

## After deploying

### 1. Update Vapi
- Go to https://dashboard.vapi.ai/assistants/94fcd023-5a33-47de-8ed2-604b103bbc81
- Change **Server URL** to your new webhook URL
- Save

### 2. Update the contact form on smartserve.cloud
- Edit `/workspace/smartserve-v2/index.html`
- Find the form: `<form id="contact-form" class="contact-form" action="https://hook.us2.make.com/...">`
- Change the `action` to your new webhook URL
- Drag to Netlify → publish

### 3. Test
- Visit `https://your-webhook-url.com/` — should return `{"service": "smartserve-webhook", "status": "ok"}`
- Visit `https://your-webhook-url.com/healthz` — should return `{"ok": true}`
- Call (833) 350-6821 and give name + number
- Check Google Sheets — new row should appear
- Check email — lead notification should arrive
- Submit a test form on smartserve.cloud — same flow

## Stop using Make.com (optional)

Once this is working, you can disable the Make.com scenario to avoid double-emails:

1. Go to https://us2.make.com/scenarios/4762805/edit
2. Toggle the scenario **OFF** (don't delete it, in case you need to roll back)
3. Future webhooks will go to your Python app only

## Files

- `app.py` — main Flask application
- `requirements.txt` — Python dependencies
- `.env.example` — environment variable template
- `render.yaml` — one-click deploy to Render.com
- `Dockerfile` — container build
- `docker-compose.yml` — local container orchestration
