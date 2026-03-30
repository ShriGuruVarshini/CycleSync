"""
dashboard Lambda handler — Lambda Function URL (no API Gateway).
GET /dashboard — orchestrates cycle_tracker, prediction_engine, mood_tracker, recommendation_engine.
"""
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

SESSIONS_TABLE_NAME = os.environ.get("SESSIONS_TABLE", "cyclesync-sessions")
USERS_TABLE_NAME = os.environ.get("USERS_TABLE", "cyclesync-users")
CONFIG_TABLE_NAME = os.environ.get("CONFIG_TABLE", "cyclesync-config")
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

_ddb = boto3.resource("dynamodb", region_name=AWS_REGION)
_lambda_client = boto3.client("lambda", region_name=AWS_REGION)
_jwt_secret_cache: Optional[str] = None

# Phase messages (≤100 chars each)
PHASE_MESSAGES = {
    "Period":     "Your body is renewing itself. Rest, hydrate, and be gentle with yourself today.",
    "Follicular": "Energy is rising! Great time to start new projects and connect with others.",
    "Ovulation":  "You're at your peak. Confidence is high — go after what you want today.",
    "Luteal/PMS": "Slow down and reflect. Your intuition is sharp; trust your feelings.",
}

# Support messages (≤150 chars each)
SUPPORT_MESSAGES = {
    "Period":     "Warmth and rest are your best friends right now. You're doing great — one day at a time.",
    "Follicular": "Fresh energy, fresh start. You've got this — channel that momentum into something meaningful.",
    "Ovulation":  "This is your moment to shine. Speak up, connect, and let your best self lead the way.",
    "Luteal/PMS": "It's okay to feel more sensitive right now. Be kind to yourself — you deserve that grace.",
}


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


def _invoke(fn_name: str, payload: dict) -> dict:
    """Invoke a Lambda function directly and return parsed response."""
    env = os.environ.get("ENVIRONMENT", "dev")
    full_name = f"{fn_name}-{env}"
    try:
        resp = _lambda_client.invoke(
            FunctionName=full_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode(),
        )
        return json.loads(resp["Payload"].read())
    except Exception as e:
        logger.error("Lambda invoke error (%s): %s", full_name, e)
        return {}


# ── handler ────────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    user_id, err = _require_auth(event)
    if err:
        return err

    # Get user profile for hobbies + language
    try:
        user_item = _ddb.Table(USERS_TABLE_NAME).get_item(
            Key={"user_id": user_id}
        ).get("Item", {})
    except ClientError:
        user_item = {}

    hobbies = user_item.get("hobby_preferences") or ["Songs", "Movies", "Poetry", "Digital Colouring"]
    language = user_item.get("language_preference", "en")

    # 1. Get cycle phase
    phase_resp = _invoke("cyclesync-cycle-tracker", {"user_id": user_id})
    if phase_resp.get("profile_incomplete"):
        return _ok({
            "profile_incomplete": True,
            "message": "Please complete your profile to see your dashboard",
        })

    phase = phase_resp.get("phase", "")
    day_in_cycle = phase_resp.get("day_in_cycle", 0)

    # 2. Predict mood
    pred_resp = _invoke("cyclesync-prediction-engine", {"phase": phase})
    predicted_mood = pred_resp.get("predicted_mood", "")

    # 3. Get today's logged mood
    mood_resp = _invoke("cyclesync-mood-tracker", {"user_id": user_id, "action": "get_today"})
    mood_entry = (mood_resp.get("entry") or {}) if isinstance(mood_resp, dict) else {}
    logged_mood = mood_entry.get("mood") if mood_entry else None

    # Active mood: logged takes priority over predicted
    active_mood = logged_mood or predicted_mood

    # 4. Get recommendations
    rec_resp = _invoke("cyclesync-recommendation-engine", {
        "phase": phase,
        "active_mood": active_mood,
        "hobbies": hobbies,
        "language_preference": language,
    })
    recommendations = rec_resp.get("recommendations", {})

    phase_message = PHASE_MESSAGES.get(phase, "")
    support_message = SUPPORT_MESSAGES.get(phase, "")

    return _ok({
        "phase": phase,
        "day_in_cycle": day_in_cycle,
        "phase_message": phase_message,
        "support_message": support_message,
        "predicted_mood": predicted_mood,
        "logged_mood": logged_mood,
        "active_mood": active_mood,
        "recommendations": recommendations,
        "display_name": user_item.get("display_name", ""),
    })
