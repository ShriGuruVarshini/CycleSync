"""
mood_tracker Lambda handler.
POST /mood
GET  /mood/today
GET  /mood/history

Auth: supports both
  - API GW authorizer claims (requestContext.authorizer.claims.sub)
  - Direct invocation with user_id + action fields
"""
import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

MOOD_TABLE_NAME = os.environ.get("MOOD_TABLE", "cyclesync-mood-entries")
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

# KMS_KEY_ID: set to a KMS key ARN/alias to enable note encryption.
# Leave empty (default) to store notes as plaintext — DynamoDB SSE handles at-rest encryption.
KMS_KEY_ID = os.environ.get("KMS_KEY_ID", "")

VALID_MOODS = {"Happy", "Sad", "Angry"}
MAX_NOTE_LENGTH = 500


# ── AWS client factories (patchable in tests) ──────────────────────────────

def _dynamodb():
    return boto3.resource("dynamodb", region_name=AWS_REGION)


def _kms():
    return boto3.client("kms", region_name=AWS_REGION)


# ── response helpers ───────────────────────────────────────────────────────

def _json_default(obj):
    if isinstance(obj, Decimal):
        try:
            n = int(obj)
            return n if Decimal(n) == obj else float(obj)
        except Exception:
            return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _resp(status, body):
    return {"statusCode": status, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body, default=_json_default)}

def _ok(b):     return _resp(200, b)
def _bad(f, m): return _resp(400, {"error": f, "message": m})
def _unauth(m): return _resp(401, {"error": "unauthorized", "message": m})


# ── auth ───────────────────────────────────────────────────────────────────

def _get_user_id(event: dict):
    """Extract user_id from API GW authorizer claims. Returns None if absent."""
    try:
        return event["requestContext"]["authorizer"]["claims"]["sub"]
    except (KeyError, TypeError):
        return None


def _require_auth(event: dict):
    """Returns (user_id, None) or (None, error_response)."""
    user_id = _get_user_id(event)
    if not user_id:
        return None, _unauth("Missing or invalid authorization")
    return user_id, None


# ── note encryption helpers (only active when KMS_KEY_ID is set) ───────────

def _encrypt_note(note: str) -> str:
    """Encrypt note with KMS if KMS_KEY_ID is configured, else return as-is."""
    if not KMS_KEY_ID or not note:
        return note
    import base64
    resp = _kms().encrypt(KeyId=KMS_KEY_ID, Plaintext=note.encode())
    return base64.b64encode(resp["CiphertextBlob"]).decode()


def _decrypt_note(note: str) -> str:
    """Decrypt note with KMS if KMS_KEY_ID is configured, else return as-is."""
    if not KMS_KEY_ID or not note:
        return note
    import base64
    try:
        ciphertext = base64.b64decode(note)
        resp = _kms().decrypt(CiphertextBlob=ciphertext)
        return resp["Plaintext"].decode()
    except Exception:
        return note


# ── handler ────────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    # Direct invocation from dashboard Lambda
    if "user_id" in event and "action" in event:
        if event["action"] == "get_today":
            return _get_today_for_user(event["user_id"])

    # Resolve path and method — support both API GW proxy and Function URL events
    path = (
        event.get("rawPath")
        or event.get("path")
        or (event.get("requestContext", {}).get("http") or {}).get("path", "/")
    )
    method = (
        event.get("httpMethod")
        or (event.get("requestContext", {}).get("http") or {}).get("method", "GET")
    ).upper()

    user_id, err = _require_auth(event)
    if err:
        return err

    if path == "/mood" and method == "POST":
        return _handle_post_mood(event, user_id)
    if path == "/mood/today" and method == "GET":
        return _get_today_for_user(user_id)
    if path == "/mood/history" and method == "GET":
        return _handle_get_history(user_id)

    return _resp(404, {"error": "not_found", "message": f"{method} {path} not found"})


# ── POST /mood ─────────────────────────────────────────────────────────────

def _handle_post_mood(event: dict, user_id: str) -> dict:
    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return _bad("body", "Invalid JSON body")

    mood = body.get("mood")
    if not mood:
        return _bad("mood", "mood is required")
    if mood not in VALID_MOODS:
        return _bad("mood", f"mood must be one of: {', '.join(sorted(VALID_MOODS))}")

    note = body.get("note", "") or ""
    if len(note) > MAX_NOTE_LENGTH:
        return _bad("note", f"note must be {MAX_NOTE_LENGTH} characters or fewer")

    today_str = date.today().isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()
    table = _dynamodb().Table(MOOD_TABLE_NAME)

    try:
        existing = table.get_item(Key={"user_id": user_id, "entry_date": today_str})
        created_at = existing.get("Item", {}).get("created_at", now_iso)
    except ClientError:
        created_at = now_iso

    stored_note = _encrypt_note(note)

    item = {
        "user_id": user_id,
        "entry_date": today_str,
        "mood": mood,
        "note": stored_note,
        "created_at": created_at,
        "updated_at": now_iso,
        "ttl": int(time.time()) + 31 * 24 * 3600,
    }

    try:
        table.put_item(Item=item)
    except ClientError as e:
        logger.error("put_item error: %s", e)
        return _resp(500, {"error": "internal_error", "message": "Failed to save mood entry"})

    # Return item with decrypted note in response
    response_item = {**item, "note": note}
    return _ok(response_item)


# ── GET /mood/today ────────────────────────────────────────────────────────

def _get_today_for_user(user_id: str) -> dict:
    today_str = date.today().isoformat()
    try:
        result = _dynamodb().Table(MOOD_TABLE_NAME).get_item(
            Key={"user_id": user_id, "entry_date": today_str}
        )
    except ClientError as e:
        logger.error("get_item error: %s", e)
        return _resp(500, {"error": "internal_error", "message": "Failed to retrieve mood"})

    entry = result.get("Item")
    if entry and KMS_KEY_ID:
        entry = {**entry, "note": _decrypt_note(entry.get("note", ""))}
    return _ok({"entry": entry})


# ── GET /mood/history ──────────────────────────────────────────────────────

def _handle_get_history(user_id: str) -> dict:
    today = date.today()
    thirty_days_ago = (today - timedelta(days=29)).isoformat()
    try:
        result = _dynamodb().Table(MOOD_TABLE_NAME).query(
            KeyConditionExpression=Key("user_id").eq(user_id)
            & Key("entry_date").between(thirty_days_ago, today.isoformat()),
            ScanIndexForward=False,
        )
    except ClientError as e:
        logger.error("query error: %s", e)
        return _resp(500, {"error": "internal_error", "message": "Failed to retrieve history"})

    entries = result.get("Items", [])
    if KMS_KEY_ID:
        entries = [{**e, "note": _decrypt_note(e.get("note", ""))} for e in entries]
    return _ok({"entries": entries})
