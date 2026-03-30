"""
Auth Lambda handler — Lambda Function URL (no API Gateway, no Cognito).
Routes determined by rawPath + requestContext.http.method from Function URL events.

POST /auth/register
POST /auth/login
POST /auth/logout
POST /auth/forgot-password
POST /auth/confirm-forgot-password
GET  /profile
PUT  /profile
PUT  /profile/hobbies
"""
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

USERS_TABLE_NAME = os.environ.get("USERS_TABLE", "cyclesync-users")
SESSIONS_TABLE_NAME = os.environ.get("SESSIONS_TABLE", "cyclesync-sessions")
CONFIG_TABLE_NAME = os.environ.get("CONFIG_TABLE", "cyclesync-config")
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

REQUIRED_FIELDS = ["email", "password", "display_name", "age", "last_period_date", "cycle_length_days"]
VALID_HOBBIES = ["Songs", "Movies", "Poetry", "Digital Colouring"]
CYCLE_MIN, CYCLE_MAX = 21, 45
SESSION_TTL_MINUTES = 30

_ddb = boto3.resource("dynamodb", region_name=AWS_REGION)
_jwt_secret_cache: Optional[str] = None


# ── helpers ────────────────────────────────────────────────────────────────

def _resp(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=lambda o: int(o) if isinstance(o, Decimal) else float(o)),
    }

def _ok(body):   return _resp(200, body)
def _created(b): return _resp(201, b)
def _bad(f, m):  return _resp(400, {"error": f, "message": m})
def _unauth(m="Unauthorized"): return _resp(401, {"error": "unauthorized", "message": m})
def _conflict(m): return _resp(409, {"error": "conflict", "message": m})


def _parse_event(event: dict):
    """Extract path, method, headers, body from Lambda Function URL event."""
    ctx = event.get("requestContext", {}).get("http", {})
    path = event.get("rawPath") or ctx.get("path", "/")
    method = ctx.get("method", "POST").upper()
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    raw = event.get("body") or "{}"
    try:
        body = json.loads(raw)
    except Exception:
        body = {}
    return path, method, headers, body


def _get_jwt_secret() -> str:
    global _jwt_secret_cache
    if _jwt_secret_cache:
        return _jwt_secret_cache
    table = _ddb.Table(CONFIG_TABLE_NAME)
    resp = table.get_item(Key={"config_key": "jwt_secret"})
    item = resp.get("Item")
    if not item:
        raise RuntimeError("jwt_secret not seeded — run: python scripts/seed_config.py")
    _jwt_secret_cache = item["value"]
    return _jwt_secret_cache


def _b64url(data: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _create_token(user_id: str) -> str:
    import base64, json as _j
    header = _b64url(b'{"alg":"HS256","typ":"JWT"}')
    payload = _b64url(_j.dumps({
        "sub": user_id,
        "jti": str(uuid.uuid4()),
        "exp": int(time.time()) + SESSION_TTL_MINUTES * 60,
        "iat": int(time.time()),
    }).encode())
    secret = _get_jwt_secret().encode()
    sig = _b64url(hmac.new(secret, f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


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
    if data.get("exp", 0) < int(time.time()):
        return None
    return data


def _require_auth(headers: dict) -> tuple:
    """Returns (user_id, None) or (None, error_response)."""
    auth = headers.get("authorization", "")
    if not auth.startswith("bearer "):
        return None, _unauth("Missing Authorization header")
    token = auth[7:]
    payload = _verify_token(token)
    if not payload:
        return None, _unauth("Invalid or expired token")
    # Verify session still exists in DynamoDB (handles logout)
    table = _ddb.Table(SESSIONS_TABLE_NAME)
    resp = table.get_item(Key={"token": token})
    if "Item" not in resp:
        return None, _unauth("Session expired — please log in again")
    return payload["sub"], None


def _hash_password(password: str) -> str:
    """SHA-256 hash with a per-user salt stored alongside."""
    salt = uuid.uuid4().hex
    h = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}:{h}"


def _check_password(password: str, stored: str) -> bool:
    try:
        salt, h = stored.split(":", 1)
        return hmac.compare_digest(
            hashlib.sha256(f"{salt}{password}".encode()).hexdigest(), h
        )
    except Exception:
        return False


# ── routing ────────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    path, method, headers, body = _parse_event(event)

    routes = {
        ("POST", "/auth/register"):                _handle_register,
        ("POST", "/auth/login"):                   _handle_login,
        ("POST", "/auth/logout"):                  _handle_logout,
        ("POST", "/auth/forgot-password"):         _handle_forgot_password,
        ("POST", "/auth/confirm-forgot-password"): _handle_confirm_forgot_password,
        ("GET",  "/profile"):                      _handle_get_profile,
        ("PUT",  "/profile"):                      _handle_put_profile,
        ("PUT",  "/profile/hobbies"):              _handle_put_hobbies,
    }

    handler_fn = routes.get((method, path))
    if not handler_fn:
        return _resp(404, {"error": "not_found", "message": f"{method} {path} not found"})
    return handler_fn(headers, body)


# ── register ───────────────────────────────────────────────────────────────

def _handle_register(headers, body):
    for field in REQUIRED_FIELDS:
        if not body.get(field) and body.get(field) != 0:
            return _bad(field, f"'{field}' is required")

    password = str(body["password"])
    if len(password) < 8:
        return _bad("password", "Password must be at least 8 characters")

    try:
        cycle_length = int(body["cycle_length_days"])
    except (ValueError, TypeError):
        return _bad("cycle_length_days", "cycle_length_days must be a number")
    if not (CYCLE_MIN <= cycle_length <= CYCLE_MAX):
        return _bad("cycle_length_days", f"cycle_length_days must be between {CYCLE_MIN} and {CYCLE_MAX}")

    email = body["email"].lower().strip()
    users_table = _ddb.Table(USERS_TABLE_NAME)

    # Check email uniqueness via GSI
    try:
        resp = users_table.query(
            IndexName="email-index",
            KeyConditionExpression=boto3.dynamodb.conditions.Key("email").eq(email),
            Limit=1,
        )
        if resp.get("Items"):
            return _conflict("An account with this email already exists")
    except ClientError as e:
        logger.error("email check error: %s", e)
        return _resp(500, {"error": "internal_error", "message": "Registration failed"})

    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    try:
        users_table.put_item(Item={
            "user_id": user_id,
            "email": email,
            "password_hash": _hash_password(password),
            "display_name": str(body["display_name"]),
            "age": int(body["age"]),
            "last_period_date": str(body["last_period_date"]),
            "cycle_length_days": cycle_length,
            "language_preference": body.get("language_preference", "en"),
            "hobby_preferences": [],
            "notifications_on": True,
            "created_at": now,
            "updated_at": now,
        })
    except ClientError as e:
        logger.error("DynamoDB put_item error: %s", e)
        return _resp(500, {"error": "internal_error", "message": "Could not create user"})

    token = _create_token(user_id)
    _store_session(token, user_id)

    return _created({"user_id": user_id, "email": email, "token": token})


# ── login ──────────────────────────────────────────────────────────────────

def _handle_login(headers, body):
    email = (body.get("email") or "").lower().strip()
    password = body.get("password") or ""
    if not email or not password:
        return _unauth()

    users_table = _ddb.Table(USERS_TABLE_NAME)
    try:
        resp = users_table.query(
            IndexName="email-index",
            KeyConditionExpression=boto3.dynamodb.conditions.Key("email").eq(email),
            Limit=1,
        )
        items = resp.get("Items", [])
    except ClientError as e:
        logger.error("login query error: %s", e)
        return _unauth()

    if not items:
        return _unauth()

    user = items[0]
    if not _check_password(password, user.get("password_hash", "")):
        return _unauth()

    token = _create_token(user["user_id"])
    _store_session(token, user["user_id"])
    return _ok({"token": token, "user_id": user["user_id"]})


def _store_session(token: str, user_id: str):
    sessions_table = _ddb.Table(SESSIONS_TABLE_NAME)
    sessions_table.put_item(Item={
        "token": token,
        "user_id": user_id,
        "ttl": int(time.time()) + SESSION_TTL_MINUTES * 60,
    })


# ── logout ─────────────────────────────────────────────────────────────────

def _handle_logout(headers, body):
    auth = headers.get("authorization", "")
    if not auth.startswith("bearer "):
        return _bad("authorization", "Missing Authorization header")
    token = auth[7:]
    sessions_table = _ddb.Table(SESSIONS_TABLE_NAME)
    try:
        sessions_table.delete_item(Key={"token": token})
    except ClientError as e:
        logger.error("logout delete error: %s", e)
    return _ok({"message": "Logged out successfully"})


# ── forgot / confirm password ──────────────────────────────────────────────

def _handle_forgot_password(headers, body):
    """
    Stores a reset token in DynamoDB with 15-min TTL.
    In production, email the token via SES. Here we return it directly
    (replace with SES call when email is configured).
    """
    email = (body.get("email") or "").lower().strip()
    if not email:
        return _bad("email", "'email' is required")

    users_table = _ddb.Table(USERS_TABLE_NAME)
    try:
        resp = users_table.query(
            IndexName="email-index",
            KeyConditionExpression=boto3.dynamodb.conditions.Key("email").eq(email),
            Limit=1,
        )
        items = resp.get("Items", [])
    except ClientError:
        items = []

    # Always return generic response (prevent email enumeration)
    if not items:
        return _ok({"message": "If this email is registered, you will receive a reset code"})

    user = items[0]
    reset_code = str(uuid.uuid4().int)[:6]  # 6-digit code
    reset_token = hashlib.sha256(f"{user['user_id']}{reset_code}".encode()).hexdigest()

    # Store reset token with 15-min TTL in sessions table (reuse for simplicity)
    sessions_table = _ddb.Table(SESSIONS_TABLE_NAME)
    sessions_table.put_item(Item={
        "token": f"reset:{reset_token}",
        "user_id": user["user_id"],
        "reset_code": reset_code,
        "ttl": int(time.time()) + 15 * 60,
    })

    # TODO: send reset_code via SES to email
    # For now, return it in response (dev only — remove in prod)
    logger.info("Reset code for %s: %s", email, reset_code)
    return _ok({"message": "If this email is registered, you will receive a reset code"})


def _handle_confirm_forgot_password(headers, body):
    email = (body.get("email") or "").lower().strip()
    code = str(body.get("code") or "")
    new_password = body.get("new_password") or ""

    if not email:   return _bad("email", "'email' is required")
    if not code:    return _bad("code", "'code' is required")
    if not new_password: return _bad("new_password", "'new_password' is required")
    if len(new_password) < 8:
        return _bad("new_password", "Password must be at least 8 characters")

    users_table = _ddb.Table(USERS_TABLE_NAME)
    try:
        resp = users_table.query(
            IndexName="email-index",
            KeyConditionExpression=boto3.dynamodb.conditions.Key("email").eq(email),
            Limit=1,
        )
        items = resp.get("Items", [])
    except ClientError:
        return _bad("code", "Invalid or expired code. Please request a new one.")

    if not items:
        return _bad("code", "Invalid or expired code. Please request a new one.")

    user = items[0]
    reset_token = hashlib.sha256(f"{user['user_id']}{code}".encode()).hexdigest()

    sessions_table = _ddb.Table(SESSIONS_TABLE_NAME)
    resp = sessions_table.get_item(Key={"token": f"reset:{reset_token}"})
    if "Item" not in resp:
        return _bad("code", "Invalid or expired code. Please request a new one.")

    # Delete the reset token and update password
    sessions_table.delete_item(Key={"token": f"reset:{reset_token}"})
    now = datetime.now(timezone.utc).isoformat()
    users_table.update_item(
        Key={"user_id": user["user_id"]},
        UpdateExpression="SET password_hash = :ph, updated_at = :ua",
        ExpressionAttributeValues={
            ":ph": _hash_password(new_password),
            ":ua": now,
        },
    )
    return _ok({"message": "Password reset successful. You can now log in."})


# ── profile ────────────────────────────────────────────────────────────────

def _handle_get_profile(headers, body):
    user_id, err = _require_auth(headers)
    if err: return err

    try:
        result = _ddb.Table(USERS_TABLE_NAME).get_item(Key={"user_id": user_id})
    except ClientError as e:
        logger.error("get_profile error: %s", e)
        return _resp(500, {"error": "internal_error", "message": "Could not retrieve profile"})

    item = result.get("Item")
    if not item:
        return _resp(404, {"error": "not_found", "message": "Profile not found"})

    # Never expose password_hash
    item.pop("password_hash", None)
    return _ok(item)


def _handle_put_profile(headers, body):
    user_id, err = _require_auth(headers)
    if err: return err

    if "cycle_length_days" in body:
        try:
            cl = int(body["cycle_length_days"])
        except (ValueError, TypeError):
            return _bad("cycle_length_days", "cycle_length_days must be a number")
        if not (CYCLE_MIN <= cl <= CYCLE_MAX):
            return _bad("cycle_length_days", f"Must be between {CYCLE_MIN} and {CYCLE_MAX}")
        body["cycle_length_days"] = cl

    allowed = {"display_name", "age", "last_period_date", "cycle_length_days", "language_preference"}
    fields = {k: v for k, v in body.items() if k in allowed}
    if not fields:
        return _bad("body", "No updatable fields provided")

    fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    set_expr = ", ".join(f"#f{i} = :v{i}" for i in range(len(fields)))
    names = {f"#f{i}": k for i, k in enumerate(fields)}
    values = {f":v{i}": v for i, (k, v) in enumerate(fields.items())}

    try:
        result = _ddb.Table(USERS_TABLE_NAME).update_item(
            Key={"user_id": user_id},
            UpdateExpression=f"SET {set_expr}",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )
    except ClientError as e:
        logger.error("put_profile error: %s", e)
        return _resp(500, {"error": "internal_error", "message": "Could not update profile"})

    item = result.get("Attributes", {})
    item.pop("password_hash", None)
    return _ok(item)


def _handle_put_hobbies(headers, body):
    user_id, err = _require_auth(headers)
    if err: return err

    hobbies = body.get("hobby_preferences", [])
    if hobbies:
        for h in hobbies:
            if h not in VALID_HOBBIES:
                return _bad("hobby_preferences", f"Invalid hobby '{h}'. Must be one of: {', '.join(VALID_HOBBIES)}")
    if not hobbies:
        hobbies = list(VALID_HOBBIES)

    now = datetime.now(timezone.utc).isoformat()
    try:
        result = _ddb.Table(USERS_TABLE_NAME).update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET hobby_preferences = :hp, updated_at = :ua",
            ExpressionAttributeValues={":hp": hobbies, ":ua": now},
            ReturnValues="ALL_NEW",
        )
    except ClientError as e:
        logger.error("put_hobbies error: %s", e)
        return _resp(500, {"error": "internal_error", "message": "Could not update hobbies"})

    item = result.get("Attributes", {})
    item.pop("password_hash", None)
    return _ok(item)
