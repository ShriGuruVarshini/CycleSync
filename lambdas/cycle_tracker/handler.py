"""
cycle_tracker Lambda handler — Lambda Function URL (no API Gateway).
GET /cycle/phase
"""
import json
import logging
import os
import time
import hashlib
import hmac
from datetime import date, datetime
from typing import Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

USERS_TABLE_NAME = os.environ.get("USERS_TABLE", "cyclesync-users")
SESSIONS_TABLE_NAME = os.environ.get("SESSIONS_TABLE", "cyclesync-sessions")
CONFIG_TABLE_NAME = os.environ.get("CONFIG_TABLE", "cyclesync-config")
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

_ddb = boto3.resource("dynamodb", region_name=AWS_REGION)
_jwt_secret_cache: Optional[str] = None


# ── helpers ────────────────────────────────────────────────────────────────

def _resp(status, body):
    return {"statusCode": status, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body)}

def _ok(b):     return _resp(200, b)
def _unauth(m): return _resp(401, {"error": "unauthorized", "message": m})


def _get_jwt_secret() -> str:
    global _jwt_secret_cache
    if _jwt_secret_cache:
        return _jwt_secret_cache
    item = _ddb.Table(CONFIG_TABLE_NAME).get_item(Key={"config_key": "jwt_secret"}).get("Item")
    if not item:
        raise RuntimeError("jwt_secret not seeded")
    _jwt_secret_cache = item["value"]
    return _jwt_secret_cache


def _b64url(data: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _verify_token(token: str) -> Optional[dict]:
    import base64, json as _j
    try:
        header, payload, sig = token.split(".")
    except ValueError:
        return None
    secret = _get_jwt_secret().encode()
    expected = _b64url(hmac.new(secret, f"{header}.{payload}".encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, sig):
        return None
    pad = 4 - len(payload) % 4
    data = _j.loads(base64.urlsafe_b64decode(payload + "=" * (pad % 4)))
    return data if data.get("exp", 0) >= int(time.time()) else None


def _require_auth(event: dict) -> tuple:
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    auth = headers.get("authorization", "")
    if not auth.startswith("bearer "):
        return None, _unauth("Missing Authorization header")
    token = auth[7:]
    payload = _verify_token(token)
    if not payload:
        return None, _unauth("Invalid or expired token")
    resp = _ddb.Table(SESSIONS_TABLE_NAME).get_item(Key={"token": token})
    if "Item" not in resp:
        return None, _unauth("Session expired — please log in again")
    return payload["sub"], None


# ── phase calculation (pure function) ─────────────────────────────────────

def calculate_phase(last_period_date: date, cycle_length: int, today: date) -> dict:
    """Pure function: compute day_in_cycle and phase."""
    day_in_cycle = ((today - last_period_date).days % cycle_length) + 1
    if day_in_cycle <= 5:
        phase = "Period"
    elif day_in_cycle <= 13:
        phase = "Follicular"
    elif day_in_cycle <= 16:
        phase = "Ovulation"
    else:
        phase = "Luteal/PMS"
    return {"phase": phase, "day_in_cycle": day_in_cycle}


# ── handler ────────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    # Support direct invocation from dashboard Lambda
    if "user_id" in event and "httpMethod" not in event and "requestContext" not in event:
        return _get_phase_for_user(event["user_id"])

    user_id, err = _require_auth(event)
    if err:
        return err

    return _get_phase_for_user(user_id)


def _get_phase_for_user(user_id: str) -> dict:
    try:
        result = _ddb.Table(USERS_TABLE_NAME).get_item(Key={"user_id": user_id})
    except ClientError as e:
        logger.error("DynamoDB error: %s", e)
        return _resp(500, {"error": "internal_error", "message": "Could not retrieve profile"})

    item = result.get("Item")
    if not item:
        return _resp(404, {"error": "not_found", "message": "User profile not found"})

    lpd_str = item.get("last_period_date") or ""
    cl_raw = item.get("cycle_length_days")

    if not lpd_str or cl_raw is None:
        return _ok({"profile_incomplete": True, "message": "Please complete your profile to see cycle phase"})

    try:
        lpd = datetime.strptime(lpd_str, "%Y-%m-%d").date()
        cl = int(cl_raw)
    except (ValueError, TypeError):
        return _ok({"profile_incomplete": True, "message": "Please complete your profile to see cycle phase"})

    return _ok(calculate_phase(lpd, cl, date.today()))
