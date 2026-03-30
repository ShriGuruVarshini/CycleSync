"""Shared utilities for CycleSync Lambda functions."""
import json
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------

def build_response(status_code: int, body: dict) -> dict:
    """Return a standard API Gateway proxy response dict."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        },
        "body": json.dumps(body),
    }


def ok(body: dict) -> dict:
    """200 OK response."""
    return build_response(200, body)


def created(body: dict) -> dict:
    """201 Created response."""
    return build_response(201, body)


def error_response(status_code: int, error: str, message: str) -> dict:
    """Return a structured error response."""
    return build_response(status_code, {"error": error, "message": message})


def bad_request(error: str, message: str) -> dict:
    """400 Bad Request."""
    return error_response(400, error, message)


def unauthorized(message: str = "Unauthorized") -> dict:
    """401 Unauthorized."""
    return error_response(401, "unauthorized", message)


def forbidden(message: str = "Forbidden") -> dict:
    """403 Forbidden."""
    return error_response(403, "forbidden", message)


def not_found(resource: str = "Resource") -> dict:
    """404 Not Found."""
    return error_response(404, "not_found", f"{resource} not found")


def conflict(message: str) -> dict:
    """409 Conflict."""
    return error_response(409, "conflict", message)


def internal_error(message: str = "Internal server error") -> dict:
    """500 Internal Server Error."""
    return error_response(500, "internal_error", message)


# ---------------------------------------------------------------------------
# JWT / Cognito claim helpers
# ---------------------------------------------------------------------------

def extract_user_id(event: dict) -> str | None:
    """
    Extract the Cognito ``sub`` claim injected by API Gateway's Cognito
    Authorizer.  Returns None if the claim is absent (e.g. in unit tests
    that don't go through the authorizer).
    """
    try:
        return event["requestContext"]["authorizer"]["claims"]["sub"]
    except (KeyError, TypeError):
        return None


def extract_claims(event: dict) -> dict:
    """Return the full claims dict from the API Gateway request context."""
    try:
        return event["requestContext"]["authorizer"]["claims"]
    except (KeyError, TypeError):
        return {}


def is_admin(event: dict) -> bool:
    """Return True if the caller has the ``custom:is_admin`` Cognito attribute."""
    claims = extract_claims(event)
    return claims.get("custom:is_admin", "false").lower() == "true"


# ---------------------------------------------------------------------------
# Request parsing helpers
# ---------------------------------------------------------------------------

def parse_body(event: dict) -> dict:
    """
    Parse the JSON body from an API Gateway event.
    Returns an empty dict on missing or malformed body.
    """
    raw = event.get("body") or "{}"
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse request body: %s", raw)
        return {}


# ---------------------------------------------------------------------------
# JWT secret — loaded from DynamoDB ConfigTable at Lambda cold start
# ---------------------------------------------------------------------------
import os
import hmac
import hashlib
import base64
import time
import uuid
import boto3
from boto3.dynamodb.conditions import Key

_ddb = boto3.resource("dynamodb")
_jwt_secret: str | None = None  # cached after first cold start


def _get_jwt_secret() -> str:
    """Read jwt_secret from ConfigTable once per cold start, then cache it."""
    global _jwt_secret
    if _jwt_secret:
        return _jwt_secret
    table = _ddb.Table(os.environ["CONFIG_TABLE"])
    resp = table.get_item(Key={"config_key": "jwt_secret"})
    item = resp.get("Item")
    if not item:
        raise RuntimeError("jwt_secret not found in ConfigTable — run seed_config.py")
    _jwt_secret = item["value"]
    return _jwt_secret


# ---------------------------------------------------------------------------
# Minimal JWT (HMAC-SHA256, no external library needed)
# ---------------------------------------------------------------------------

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    pad = 4 - len(s) % 4
    return base64.urlsafe_b64decode(s + "=" * (pad % 4))


def create_token(user_id: str, ttl_minutes: int = 30) -> str:
    """Create a signed JWT token storing user_id and expiry."""
    import json as _json
    header = _b64url(b'{"alg":"HS256","typ":"JWT"}')
    payload = _b64url(_json.dumps({
        "sub": user_id,
        "jti": str(uuid.uuid4()),
        "exp": int(time.time()) + ttl_minutes * 60,
        "iat": int(time.time()),
    }).encode())
    secret = _get_jwt_secret().encode()
    sig = _b64url(hmac.new(secret, f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def verify_token(token: str) -> dict | None:
    """
    Verify signature and expiry. Returns payload dict on success, None on failure.
    Does NOT check SessionsTable — callers must do that for logout invalidation.
    """
    import json as _json
    try:
        header, payload, sig = token.split(".")
    except ValueError:
        return None
    secret = _get_jwt_secret().encode()
    expected = _b64url(hmac.new(secret, f"{header}.{payload}".encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, sig):
        return None
    data = _json.loads(_b64url_decode(payload))
    if data.get("exp", 0) < int(time.time()):
        return None
    return data


def get_user_id_from_event(event: dict) -> str | None:
    """
    Extract and verify the Bearer token from the Authorization header.
    Works with Lambda Function URLs (no API Gateway Cognito Authorizer).
    Returns user_id (sub) on success, None on failure.
    """
    auth_header = (
        event.get("headers", {}) or {}
    ).get("authorization") or (
        event.get("headers", {}) or {}
    ).get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:]
    payload = verify_token(token)
    return payload.get("sub") if payload else None


def require_auth(event: dict) -> tuple[str | None, dict | None]:
    """
    Call at the top of every protected Lambda handler.
    Returns (user_id, None) on success or (None, error_response) on failure.

    Usage:
        user_id, err = require_auth(event)
        if err:
            return err
    """
    sessions_table = _ddb.Table(os.environ["SESSIONS_TABLE"])
    auth_header = (
        event.get("headers", {}) or {}
    ).get("authorization") or (
        event.get("headers", {}) or {}
    ).get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, unauthorized("Missing Authorization header")
    token = auth_header[7:]
    payload = verify_token(token)
    if not payload:
        return None, unauthorized("Invalid or expired token")
    # Check token is still in SessionsTable (not logged out)
    resp = sessions_table.get_item(Key={"token": token})
    if "Item" not in resp:
        return None, unauthorized("Session not found — please log in again")
    return payload["sub"], None
