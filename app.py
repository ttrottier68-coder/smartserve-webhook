"""
SmartServe Webhook Receiver v2
Adds: in-memory request log, /stats endpoint, raw request logging
"""

import os
import json
import logging
import smtplib
import time
from collections import deque
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
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
GOOGLE_SHEET_TAB = os.environ.get("GOOGLE_SHEET_TAB", "Sheet1")

EMAIL_ENABLED = os.environ.get("EMAIL_ENABLED", "true").lower() == "true"
EMAIL_FROM = os.environ.get("EMAIL_FROM")
EMAIL_TO = os.environ.get("EMAIL_TO")
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("smartserve-webhook")

app = Flask(__name__)

# ---------- In-memory request log (last 50 requests) ----------
request_log = deque(maxlen=50)


def log_request(path, method, payload_summary, response_summary, duration_ms, status_code):
    entry = {
        "time": now_iso(),
        "path": path,
        "method": method,
        "payload": payload_summary,
        "response": response_summary,
        "duration_ms": duration_ms,
        "status": status_code,
        "remote": request.remote_addr if request else "?"
    }
    request_log.append(entry)
    log.info("REQ %s %s -> %d (%dms) | %s", method, path, status_code, duration_ms, payload_summary[:80])


# ---------- Google Sheets ----------
_gsheet_client = None


def get_gsheet_client():
    global _gsheet_client
    if _gsheet_client is not None:
        return _gsheet_client
    if not GSPREAD_AVAILABLE or not GOOGLE_SHEET_ID or not GOOGLE_SERVICE_ACCOUNT_JSON:
        return None
    try:
        creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        creds = Credentials.from_service_account_info(
            creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        _gsheet_client = gspread.authorize(creds)
        return _gsheet_client
    except Exception as e:
        log.error("Sheets init failed: %s", e)
        return None


def write_to_sheet(row):
    client = get_gsheet_client()
    if not client:
        return False
    try:
        sheet = client.open_by_key(GOOGLE_SHEET_ID).worksheet(GOOGLE_SHEET_TAB)
        sheet.append_row(row, value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        log.error("Sheets write failed: %s", e)
        return False


# ---------- Email ----------
def send_email(subject, body):
    if not EMAIL_ENABLED or not all([EMAIL_FROM, EMAIL_TO, SMTP_USER, SMTP_PASS]):
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
        return True
    except Exception as e:
        log.error("Email send failed: %s", e)
        return False


# ---------- Helpers ----------
def now_iso():
    return datetime.now(timezone.utc).isoformat()


def truncate(s, n=5000):
    if s is None: return ""
    s = str(s)
    return s if len(s) <= n else s[:n] + "..."


# ---------- Event handlers ----------
def handle_vapi_function_call(payload):
    fc = payload.get("message", {}).get("functionCall", {})
    params = fc.get("parameters", {}) or {}
    call = payload.get("message", {}).get("call", {}) or {}
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

    sheet_row = [
        now_iso(), "Phone Call", truncate(name, 200), truncate(phone, 50),
        truncate(email, 200), truncate(business, 200), truncate(business_type, 100),
        truncate(call_volume, 50), truncate(use_case, 5000), truncate(urgency, 50),
        truncate(callback_time, 100), truncate(customer_number, 50), truncate(call_id, 100),
    ]
    write_to_sheet(sheet_row)

    subject = f"New phone lead: {name or 'Unknown'}"
    body = f"""New call lead from (833) 350-6821

Name: {name}
Phone: {phone}
Email: {email or '(not provided)'}
Business: {business or '(not provided)'}
Type: {business_type or '(not provided)'}
Call volume: {call_volume or '(not provided)'}
Use case: {use_case or '(not provided)'}
Urgency: {urgency or '(not provided)'}
Callback time: {callback_time or '(not provided)'}

Customer: {customer_number}
Call: {call_id}
Time: {now_iso()}
"""
    send_email(subject, body)

    # CRITICAL: this is the response Vapi waits for
    return jsonify({"results": [{"name": "save_lead", "result": "Lead saved successfully"}]})


def handle_vapi_end_of_call_report(payload):
    message = payload.get("message", {}) or {}
    call = message.get("call", {}) or {}
    summary = (message.get("analysis") or {}).get("summary", "")
    transcript = message.get("transcript", "")
    recording_url = message.get("recordingUrl", "") or call.get("recordingUrl", "")
    customer_number = (call.get("customer") or {}).get("number", "")
    call_id = call.get("id", "")
    duration = call.get("duration", 0)
    ended_reason = call.get("endedReason", "")

    sheet_row = [
        now_iso(), "Call Log", "", "", "", "", "", "", "", "", "",
        truncate(customer_number, 50), truncate(call_id, 100),
        truncate(summary, 5000), truncate(transcript, 49000),
        truncate(recording_url, 500), truncate(str(duration), 20),
        truncate(ended_reason, 100),
    ]
    write_to_sheet(sheet_row)
    return jsonify({"ok": True})


def handle_form_submission(payload):
    name = payload.get("name", "")
    email = payload.get("email", "")
    phone = payload.get("phone", "")
    company = payload.get("company", "")
    industry = payload.get("industry", "")
    call_volume = payload.get("call_volume", "")
    message = payload.get("message", "")
    referrer = payload.get("referrer", "")

    sheet_row = [
        now_iso(), "Web Form", truncate(name, 200), truncate(phone, 50),
        truncate(email, 200), truncate(company, 200), truncate(industry, 100),
        truncate(call_volume, 50), truncate(message, 5000), "", "", "", "",
        truncate(f"Referrer: {referrer}", 500),
    ]
    write_to_sheet(sheet_row)

    subject = f"New web lead: {name or 'Unknown'}"
    body = f"""New lead from smartserve.cloud

Name: {name}
Email: {email}
Phone: {phone}
Company: {company}
Industry: {industry}
Call volume: {call_volume}
Message: {message or '(none)'}

Time: {now_iso()}
"""
    send_email(subject, body)
    return jsonify({"ok": True})


# ---------- Routes ----------
@app.before_request
def start_timer():
    request.start_time = time.time()


@app.after_request
def log_response(response):
    if hasattr(request, "start_time") and not request.path.startswith(("/static", "/healthz", "/stats")):
        duration = int((time.time() - request.start_time) * 1000)
        try:
            payload_summary = json.dumps(request.get_json(silent=True) or {})[:200]
        except Exception:
            payload_summary = "?"
        try:
            response_summary = response.get_data(as_text=True)[:200]
        except Exception:
            response_summary = "?"
        log_request(request.path, request.method, payload_summary, response_summary, duration, response.status_code)
    return response


@app.route("/", methods=["GET"])
def root():
    return jsonify({"service": "smartserve-webhook", "status": "ok", "endpoints": ["/webhook", "/healthz", "/stats"]})


@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify({"ok": True})


@app.route("/stats", methods=["GET"])
def stats():
    """Return recent request log for debugging."""
    return jsonify({
        "recent_requests": list(request_log),
        "count": len(request_log),
        "max": request_log.maxlen
    })


@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    if request.method == "GET":
        return jsonify({"ok": True, "hint": "POST to this URL"})

    if request.is_json:
        payload = request.get_json(silent=True) or {}
    else:
        payload = request.form.to_dict() or {}

    raw_message = payload.get("message")
    message = raw_message if isinstance(raw_message, dict) else {}
    msg_type = message.get("type", "") if isinstance(message, dict) else ""

    if message.get("functionCall"):
        return handle_vapi_function_call(payload)

    if msg_type == "end-of-call-report" or message.get("transcript"):
        return handle_vapi_end_of_call_report(payload)

    if msg_type and msg_type != "":
        return jsonify({"ok": True, "ignored": msg_type})

    if payload.get("name") or payload.get("email") or payload.get("phone"):
        return handle_form_submission(payload)

    return jsonify({"ok": True, "note": "unknown payload"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    log.info("Starting SmartServe webhook on port %d", port)
    app.run(host="0.0.0.0", port=port, debug=False)
