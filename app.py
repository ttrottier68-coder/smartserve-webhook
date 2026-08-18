"""
SmartServe Webhook Receiver
Handles both Vapi phone call events and website contact form submissions.
Replaces the Make.com scenario with a simpler, more reliable Python service.

Endpoints:
- POST /webhook        - Main webhook for Vapi and form submissions
- GET  /                - Health check
- GET  /healthz         - Health check (for load balancers)
"""

import os
from dotenv import load_dotenv
load_dotenv()
import json
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from flask import Flask, request, jsonify

try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False

# ---------- Config ----------
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")  # The ID from the Sheet URL
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")  # JSON string
GOOGLE_SHEET_TAB = os.environ.get("GOOGLE_SHEET_TAB", "Sheet1")  # Tab name

EMAIL_ENABLED = os.environ.get("EMAIL_ENABLED", "true").lower() == "true"
EMAIL_FROM = os.environ.get("EMAIL_FROM")  # e.g., leads@smartserve.cloud
EMAIL_TO = os.environ.get("EMAIL_TO")  # Where lead notifications go
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")  # Usually same as EMAIL_FROM
SMTP_PASS = os.environ.get("SMTP_PASS")  # Gmail app password

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("smartserve-webhook")

app = Flask(__name__)

# ---------- Google Sheets ----------
_gsheet_client = None


def get_gsheet_client():
    """Lazy-load the Google Sheets client."""
    global _gsheet_client
    if _gsheet_client is not None:
        return _gsheet_client
    if not GSPREAD_AVAILABLE:
        log.warning("gspread not installed; Sheets writes will be skipped")
        return None
    if not GOOGLE_SHEET_ID or not GOOGLE_SERVICE_ACCOUNT_JSON:
        log.warning("GOOGLE_SHEET_ID or GOOGLE_SERVICE_ACCOUNT_JSON not set; Sheets writes will be skipped")
        return None
    try:
        creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        _gsheet_client = gspread.authorize(creds)
        log.info("Google Sheets client initialized")
        return _gsheet_client
    except Exception as e:
        log.error("Failed to initialize Google Sheets client: %s", e)
        return None


def write_to_sheet(row: list):
    """Append a row to the configured Google Sheet."""
    client = get_gsheet_client()
    if not client:
        log.warning("Skipping Sheets write (no client)")
        return False
    try:
        sheet = client.open_by_key(GOOGLE_SHEET_ID).worksheet(GOOGLE_SHEET_TAB)
        sheet.append_row(row, value_input_option="USER_ENTERED")
        log.info("Wrote row to Sheets (%d cols)", len(row))
        return True
    except Exception as e:
        log.error("Sheets write failed: %s", e)
        return False


# ---------- Email ----------
def send_email(subject: str, body: str):
    """Send a plain-text email via SMTP."""
    if not EMAIL_ENABLED:
        log.info("Email disabled; skipping send")
        return False
    if not all([EMAIL_FROM, EMAIL_TO, SMTP_USER, SMTP_PASS]):
        log.warning("Email config incomplete; skipping send")
        return False
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_FROM
        msg["To"] = EMAIL_TO
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(EMAIL_FROM, [EMAIL_TO], msg.as_string())
        log.info("Email sent: %s", subject)
        return True
    except Exception as e:
        log.error("Email send failed: %s", e)
        return False


# ---------- Helpers ----------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def truncate(s, n=5000):
    """Safely truncate a value to n chars (under Sheets' 50000/cell)."""
    if s is None:
        return ""
    s = str(s)
    return s if len(s) <= n else s[:n] + "…"


# ---------- Event handlers ----------
def handle_vapi_function_call(payload: dict):
    """Handle a Vapi function-call event (e.g., save_lead was called)."""
    fc = payload.get("message", {}).get("functionCall", {})
    params = fc.get("parameters", {}) or {}
    call = payload.get("message", {}).get("call", {}) or {}

    # Extract lead data
    name = params.get("name", "")
    phone = params.get("phone", "")
    email = params.get("email", "")
    business = params.get("business", "")
    business_type = params.get("business_type", "")
    call_volume = params.get("call_volume", "")
    use_case = params.get("use_case", "")
    urgency = params.get("urgency", "")
    callback_time = params.get("callback_time", "")

    customer_number = (call.get("customer") or {}).get("number", "")
    call_id = call.get("id", "")

    log.info("Vapi function-call: name=%s phone=%s business=%s", name, phone, business)

    # Write to Sheets
    sheet_row = [
        now_iso(),
        "Phone Call",
        truncate(name, 200),
        truncate(phone, 50),
        truncate(email, 200),
        truncate(business, 200),
        truncate(business_type, 100),
        truncate(call_volume, 50),
        truncate(use_case, 5000),
        truncate(urgency, 50),
        truncate(callback_time, 100),
        truncate(customer_number, 50),
        truncate(call_id, 100),
    ]
    write_to_sheet(sheet_row)

    # Send email
    subject = f"New phone lead: {name or 'Unknown'}" + (f" ({business})" if business else "")
    body = f"""New call lead from (833) 350-6821

Name: {name}
Phone: {phone}
Email: {email or '(not provided)'}
Business: {business or '(not provided)'}
Type: {business_type or '(not provided)'}
Monthly call volume: {call_volume or '(not provided)'}
Use case: {use_case or '(not provided)'}
Urgency: {urgency or '(not provided)'}
Callback time: {callback_time or '(not provided)'}

Customer number: {customer_number}
Call ID: {call_id}
Time: {now_iso()}
"""
    send_email(subject, body)

    # Return the Vapi-mandated response so the AI says "Perfect, lead saved"
    return jsonify({
        "results": [
            {
                "name": "save_lead",
                "result": "Lead saved successfully",
            }
        ]
    })


def handle_vapi_end_of_call_report(payload: dict):
    """Handle a Vapi end-of-call-report event. Logs the call for record-keeping."""
    message = payload.get("message", {}) or {}
    call = message.get("call", {}) or {}
    summary = (message.get("analysis") or {}).get("summary", "")
    transcript = message.get("transcript", "")
    recording_url = message.get("recordingUrl", "") or call.get("recordingUrl", "")

    customer_number = (call.get("customer") or {}).get("number", "")
    call_id = call.get("id", "")
    duration = call.get("duration", 0)
    ended_reason = call.get("endedReason", "")

    log.info("Vapi end-of-call-report: duration=%ss reason=%s", duration, ended_reason)

    # Write a separate row to Sheets for the call record
    sheet_row = [
        now_iso(),
        "Call Log",
        "",  # name (not collected on every call)
        "",  # phone
        "",  # email
        "",  # business
        "",  # business_type
        "",  # call_volume
        "",  # use_case
        "",  # urgency
        "",  # callback_time
        truncate(customer_number, 50),
        truncate(call_id, 100),
        truncate(summary, 5000),
        truncate(transcript, 49000),  # leave headroom under 50000
        truncate(recording_url, 500),
        truncate(str(duration), 20),
        truncate(ended_reason, 100),
    ]
    write_to_sheet(sheet_row)
    return jsonify({"ok": True})


def handle_form_submission(payload: dict):
    """Handle a website contact form submission."""
    name = payload.get("name", "")
    email = payload.get("email", "")
    phone = payload.get("phone", "")
    company = payload.get("company", "")
    industry = payload.get("industry", "")
    call_volume = payload.get("call_volume", "")
    message = payload.get("message", "")
    referrer = payload.get("referrer", "")
    source = payload.get("source", "")

    log.info("Form submission: name=%s email=%s company=%s", name, email, company)

    sheet_row = [
        now_iso(),
        "Web Form",
        truncate(name, 200),
        truncate(phone, 50),
        truncate(email, 200),
        truncate(company, 200),
        truncate(industry, 100),
        truncate(call_volume, 50),
        truncate(message, 5000),
        "",  # urgency (not collected on form)
        "",  # callback_time
        "",  # customer_number
        "",  # call_id
        truncate(f"Source: {source}\nReferrer: {referrer}", 500),
    ]
    write_to_sheet(sheet_row)

    subject = f"New web lead: {name or 'Unknown'}" + (f" ({company})" if company else "")
    body = f"""New lead from smartserve.cloud

Name: {name}
Email: {email}
Phone: {phone}
Company: {company}
Industry: {industry}
Call volume: {call_volume}

Message:
{message or '(none)'}

---
Source: {source}
Referrer: {referrer}
Time: {now_iso()}
"""
    send_email(subject, body)
    return jsonify({"ok": True})


# ---------- Routes ----------
@app.route("/", methods=["GET"])
def root():
    return jsonify({
        "service": "smartserve-webhook",
        "status": "ok",
        "endpoints": ["/webhook", "/healthz"],
    })


@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify({"ok": True})


@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    if request.method == "GET":
        return jsonify({"ok": True, "hint": "POST to this URL"})

    # Parse body
    if request.is_json:
        payload = request.get_json(silent=True) or {}
    else:
        # Try form-encoded
        payload = request.form.to_dict() or {}

    log.info("Webhook hit: keys=%s", list(payload.keys())[:10])

    # Route based on payload structure
    raw_message = payload.get("message")
    message = raw_message if isinstance(raw_message, dict) else {}
    msg_type = message.get("type", "") if isinstance(message, dict) else ""

    # Vapi function-call event (save_lead fired)
    if message.get("functionCall"):
        return handle_vapi_function_call(payload)

    # Vapi end-of-call-report
    if msg_type == "end-of-call-report" or message.get("transcript"):
        return handle_vapi_end_of_call_report(payload)

    # Vapi other events (status-update, conversation-update, etc.) - acknowledge but don't process
    if msg_type and msg_type != "":
        log.info("Ignoring Vapi event type=%s", msg_type)
        return jsonify({"ok": True, "ignored": msg_type})

    # Form submission (has top-level name/email/phone)
    if payload.get("name") or payload.get("email") or payload.get("phone"):
        return handle_form_submission(payload)

    # Unknown payload
    log.warning("Unknown payload structure: %s", json.dumps(payload)[:500])
    return jsonify({"ok": True, "note": "unknown payload"}), 200


# ---------- Main ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    log.info("Starting SmartServe webhook on port %d", port)
    log.info("Sheets: %s | Email: %s", "enabled" if GOOGLE_SHEET_ID else "disabled", "enabled" if EMAIL_ENABLED else "disabled")
    app.run(host="0.0.0.0", port=port, debug=False)
