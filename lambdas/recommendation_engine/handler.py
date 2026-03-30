"""
recommendation_engine Lambda handler.
Routes:
  GET    /admin/content      — list content items (paginated scan)
  POST   /admin/content      — create a new content item
  PUT    /admin/content/{id} — update a content item
  DELETE /admin/content/{id} — soft-delete a content item
  GET    /recommendations    — get personalised content recommendations
"""
import base64
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Environment variables
# ---------------------------------------------------------------------------
CONTENT_TABLE_NAME = os.environ.get("CONTENT_TABLE_NAME", "cyclesync-content-items")
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

VALID_CATEGORIES = {"Song", "Movie", "Poem", "Digital Colouring"}
MAX_DESCRIPTION_LENGTH = 80
RATING_MIN = Decimal("1.0")
RATING_MAX = Decimal("5.0")
MAX_ITEMS_PER_CATEGORY = 5

# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _resp(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=_decimal_default),
    }


def _ok(body: dict) -> dict:
    return _resp(200, body)


def _bad_request(error: str, message: str) -> dict:
    return _resp(400, {"error": error, "message": message})


def _decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


# ---------------------------------------------------------------------------
# AWS clients (lazy singletons)
# ---------------------------------------------------------------------------

def _dynamodb():
    return boto3.resource("dynamodb", region_name=AWS_REGION)


# ---------------------------------------------------------------------------
# Identity / admin helpers
# ---------------------------------------------------------------------------

import hashlib
import hmac as _hmac
import time as _time

_ddb_res = boto3.resource("dynamodb", region_name=AWS_REGION)
_jwt_secret_cache: Optional[str] = None
SESSIONS_TABLE_NAME = os.environ.get("SESSIONS_TABLE", "cyclesync-sessions")
CONFIG_TABLE_NAME = os.environ.get("CONFIG_TABLE", "cyclesync-config")


def _get_jwt_secret() -> str:
    global _jwt_secret_cache
    if _jwt_secret_cache:
        return _jwt_secret_cache
    item = _ddb_res.Table(CONFIG_TABLE_NAME).get_item(Key={"config_key": "jwt_secret"}).get("Item")
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
    expected = _b64url(_hmac.new(secret, f"{header}.{payload}".encode(), hashlib.sha256).digest())
    if not _hmac.compare_digest(expected, sig):
        return None
    pad = 4 - len(payload) % 4
    data = _j.loads(base64.urlsafe_b64decode(payload + "=" * (pad % 4)))
    return data if data.get("exp", 0) >= int(_time.time()) else None


def _get_user_id(event: dict):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    auth = headers.get("authorization", "")
    if not auth.startswith("bearer "):
        return None
    token = auth[7:]
    payload = _verify_token(token)
    if not payload:
        return None
    resp = _ddb_res.Table(SESSIONS_TABLE_NAME).get_item(Key={"token": token})
    return payload["sub"] if "Item" in resp else None


def _is_admin(event: dict) -> bool:
    """Admin check: user must have is_admin=True in their DynamoDB record."""
    user_id = _get_user_id(event)
    if not user_id:
        return False
    users_table = os.environ.get("USERS_TABLE", "cyclesync-users")
    resp = _ddb_res.Table(users_table).get_item(Key={"user_id": user_id})
    item = resp.get("Item", {})
    return bool(item.get("is_admin", False))


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_content_fields(body: dict, require_all: bool = True):
    """Validate content item fields.

    Returns (None, None) on success or (error_field, message) on failure.
    When require_all=False (for PUT), only validates fields that are present.
    """
    description = body.get("description")
    rating = body.get("rating")
    category = body.get("category")
    language = body.get("language")

    if require_all:
        for field in ("title", "category", "mood_tags", "description", "rating", "language"):
            if field not in body:
                return field, f"{field} is required"

    if description is not None:
        if len(str(description)) > MAX_DESCRIPTION_LENGTH:
            return "description", f"description must be {MAX_DESCRIPTION_LENGTH} characters or fewer"

    if rating is not None:
        try:
            r = Decimal(str(rating))
        except Exception:
            return "rating", "rating must be a number between 1.0 and 5.0"
        if r < RATING_MIN or r > RATING_MAX:
            return "rating", "rating must be between 1.0 and 5.0"

    if category is not None:
        if category not in VALID_CATEGORIES:
            return "category", f"category must be one of: {', '.join(sorted(VALID_CATEGORIES))}"

    if language is not None:
        if not isinstance(language, str) or not language.strip():
            return "language", "language must be a non-empty BCP 47 language code string"

    if require_all:
        mood_tags = body.get("mood_tags")
        if not isinstance(mood_tags, list) or len(mood_tags) == 0:
            return "mood_tags", "mood_tags must be a non-empty list"
        valid_moods = {"Happy", "Sad", "Angry"}
        for tag in mood_tags:
            if tag not in valid_moods:
                return "mood_tags", f"mood_tags values must be one of: {', '.join(sorted(valid_moods))}"

    return None, None


# ---------------------------------------------------------------------------
# Handler routing
# ---------------------------------------------------------------------------

def lambda_handler(event, context):
    # Support direct invocation (no httpMethod) for get_recommendations
    if "httpMethod" not in event and "phase" in event:
        return _handle_direct_recommendations(event)

    ctx = event.get("requestContext", {}).get("http", {})
    path = event.get("rawPath") or ctx.get("path", event.get("path", ""))
    method = ctx.get("method", event.get("httpMethod", "GET")).upper()
    path_params = event.get("pathParameters") or {}

    # Admin content endpoints
    if path == "/admin/content" and method == "GET":
        return _handle_admin_get_content(event)
    if path == "/admin/content" and method == "POST":
        return _handle_admin_post_content(event)
    if (path.startswith("/admin/content/") or path_params.get("id")) and method == "PUT":
        item_id = path_params.get("id") or path.split("/admin/content/", 1)[-1]
        return _handle_admin_put_content(event, item_id)
    if (path.startswith("/admin/content/") or path_params.get("id")) and method == "DELETE":
        item_id = path_params.get("id") or path.split("/admin/content/", 1)[-1]
        return _handle_admin_delete_content(event, item_id)

    # Recommendations endpoint
    if path == "/recommendations" and method == "GET":
        return _handle_get_recommendations(event)

    return _resp(404, {"error": "not_found", "message": f"Route {method} {path} not found"})


# ---------------------------------------------------------------------------
# GET /admin/content
# ---------------------------------------------------------------------------

def _handle_admin_get_content(event: dict) -> dict:
    if not _is_admin(event):
        return _resp(403, {"error": "forbidden", "message": "Admin access required"})

    query_params = event.get("queryStringParameters") or {}
    last_key_b64 = query_params.get("last_key")

    scan_kwargs = {}
    if last_key_b64:
        try:
            last_key_json = base64.b64decode(last_key_b64).decode("utf-8")
            scan_kwargs["ExclusiveStartKey"] = json.loads(last_key_json)
        except Exception:
            return _bad_request("last_key", "Invalid pagination key")

    table = _dynamodb().Table(CONTENT_TABLE_NAME)
    try:
        result = table.scan(**scan_kwargs)
    except ClientError as e:
        logger.error("DynamoDB scan error: %s", e)
        return _resp(500, {"error": "internal_error", "message": "Failed to list content items"})

    items = result.get("Items", [])
    response = {"items": items}

    last_evaluated_key = result.get("LastEvaluatedKey")
    if last_evaluated_key:
        next_key_json = json.dumps(last_evaluated_key, default=_decimal_default)
        response["next_key"] = base64.b64encode(next_key_json.encode("utf-8")).decode("utf-8")

    return _ok(response)


# ---------------------------------------------------------------------------
# POST /admin/content
# ---------------------------------------------------------------------------

def _handle_admin_post_content(event: dict) -> dict:
    if not _is_admin(event):
        return _resp(403, {"error": "forbidden", "message": "Admin access required"})

    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return _bad_request("body", "Invalid JSON body")

    error_field, error_msg = _validate_content_fields(body, require_all=True)
    if error_field:
        return _bad_request(error_field, error_msg)

    now_iso = datetime.now(timezone.utc).isoformat()
    item = {
        "item_id": str(uuid.uuid4()),
        "title": body["title"],
        "category": body["category"],
        "mood_tags": body["mood_tags"],
        "description": body["description"],
        "rating": Decimal(str(body["rating"])),
        "language": body["language"],
        "is_deleted": False,
        "created_at": now_iso,
    }

    table = _dynamodb().Table(CONTENT_TABLE_NAME)
    try:
        table.put_item(Item=item)
    except ClientError as e:
        logger.error("DynamoDB put_item error: %s", e)
        return _resp(500, {"error": "internal_error", "message": "Failed to create content item"})

    return _resp(201, item)


# ---------------------------------------------------------------------------
# PUT /admin/content/:id
# ---------------------------------------------------------------------------

def _handle_admin_put_content(event: dict, item_id: str) -> dict:
    if not _is_admin(event):
        return _resp(403, {"error": "forbidden", "message": "Admin access required"})

    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return _bad_request("body", "Invalid JSON body")

    if not body:
        return _bad_request("body", "Request body must contain at least one field to update")

    error_field, error_msg = _validate_content_fields(body, require_all=False)
    if error_field:
        return _bad_request(error_field, error_msg)

    table = _dynamodb().Table(CONTENT_TABLE_NAME)

    # Check item exists
    try:
        existing = table.get_item(Key={"item_id": item_id})
    except ClientError as e:
        logger.error("DynamoDB get_item error: %s", e)
        return _resp(500, {"error": "internal_error", "message": "Failed to retrieve content item"})

    if not existing.get("Item"):
        return _resp(404, {"error": "not_found", "message": f"Content item '{item_id}' not found"})

    # Build UpdateExpression dynamically
    updatable_fields = ("title", "category", "mood_tags", "description", "rating", "language")
    update_parts = []
    expr_names = {}
    expr_values = {}

    for field in updatable_fields:
        if field in body:
            placeholder = f"#f_{field}"
            value_key = f":v_{field}"
            expr_names[placeholder] = field
            update_parts.append(f"{placeholder} = {value_key}")
            if field == "rating":
                expr_values[value_key] = Decimal(str(body[field]))
            else:
                expr_values[value_key] = body[field]

    # Always update updated_at
    expr_names["#f_updated_at"] = "updated_at"
    expr_values[":v_updated_at"] = datetime.now(timezone.utc).isoformat()
    update_parts.append("#f_updated_at = :v_updated_at")

    update_expression = "SET " + ", ".join(update_parts)

    try:
        result = table.update_item(
            Key={"item_id": item_id},
            UpdateExpression=update_expression,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
            ReturnValues="ALL_NEW",
        )
    except ClientError as e:
        logger.error("DynamoDB update_item error: %s", e)
        return _resp(500, {"error": "internal_error", "message": "Failed to update content item"})

    return _ok(result.get("Attributes", {}))


# ---------------------------------------------------------------------------
# DELETE /admin/content/:id  (soft-delete)
# ---------------------------------------------------------------------------

def _handle_admin_delete_content(event: dict, item_id: str) -> dict:
    if not _is_admin(event):
        return _resp(403, {"error": "forbidden", "message": "Admin access required"})

    table = _dynamodb().Table(CONTENT_TABLE_NAME)

    # Check item exists
    try:
        existing = table.get_item(Key={"item_id": item_id})
    except ClientError as e:
        logger.error("DynamoDB get_item error: %s", e)
        return _resp(500, {"error": "internal_error", "message": "Failed to retrieve content item"})

    if not existing.get("Item"):
        return _resp(404, {"error": "not_found", "message": f"Content item '{item_id}' not found"})

    try:
        table.update_item(
            Key={"item_id": item_id},
            UpdateExpression="SET is_deleted = :val, updated_at = :ts",
            ExpressionAttributeValues={
                ":val": True,
                ":ts": datetime.now(timezone.utc).isoformat(),
            },
        )
    except ClientError as e:
        logger.error("DynamoDB update_item error: %s", e)
        return _resp(500, {"error": "internal_error", "message": "Failed to delete content item"})

    return _ok({"message": f"Content item '{item_id}' deleted"})


# ---------------------------------------------------------------------------
# GET /recommendations  (and direct Lambda invocation)
# ---------------------------------------------------------------------------

def _handle_get_recommendations(event: dict) -> dict:
    user_id = _get_user_id(event)
    if not user_id:
        return _resp(401, {"error": "unauthorized", "message": "Missing user identity"})

    query_params = event.get("queryStringParameters") or {}
    phase = query_params.get("phase", "")
    active_mood = query_params.get("active_mood", "")
    hobbies_raw = query_params.get("hobbies", "")
    language_preference = query_params.get("language_preference", "en")

    hobbies = [h.strip() for h in hobbies_raw.split(",") if h.strip()] if hobbies_raw else []
    if not hobbies:
        hobbies = list(VALID_CATEGORIES)

    recommendations = get_recommendations(phase, active_mood, hobbies, language_preference)
    return _ok({"recommendations": recommendations})


def _handle_direct_recommendations(event: dict) -> dict:
    """Handle direct Lambda invocation (e.g. from dashboard Lambda)."""
    phase = event.get("phase", "")
    active_mood = event.get("active_mood", "")
    hobbies = event.get("hobbies") or list(VALID_CATEGORIES)
    language_preference = event.get("language_preference", "en")

    recommendations = get_recommendations(phase, active_mood, hobbies, language_preference)
    return {"recommendations": recommendations}


# ---------------------------------------------------------------------------
# Core recommendation logic
# ---------------------------------------------------------------------------

def get_recommendations(
    phase: str,
    active_mood: str,
    hobbies: list,
    language_preference: str,
) -> dict:
    """Return up to 5 content items per hobby category.

    Selection priority:
    1. Items matching mood + category + user language (not deleted)
    2. Fall back to language="en" if < 5 results
    3. Fall back to top-rated items in category regardless of language if still < 5
    """
    table = _dynamodb().Table(CONTENT_TABLE_NAME)
    result = {}

    for category in hobbies:
        items = _fetch_for_category(table, active_mood, category, language_preference)
        result[category] = items

    return result


def _fetch_for_category(table, active_mood: str, category: str, language_preference: str) -> list:
    """Fetch up to MAX_ITEMS_PER_CATEGORY items for a single category."""
    items = []

    # Step 1: preferred language + mood match
    if active_mood:
        items = _scan_content(
            table,
            mood=active_mood,
            category=category,
            language=language_preference,
        )

    # Step 2: fall back to English if not enough
    if len(items) < MAX_ITEMS_PER_CATEGORY and language_preference != "en":
        en_items = _scan_content(
            table,
            mood=active_mood,
            category=category,
            language="en",
        )
        # Merge, avoiding duplicates
        existing_ids = {i["item_id"] for i in items}
        for item in en_items:
            if item["item_id"] not in existing_ids and len(items) < MAX_ITEMS_PER_CATEGORY:
                items.append(item)
                existing_ids.add(item["item_id"])

    # Step 3: fall back to top-rated in category regardless of language
    if len(items) < MAX_ITEMS_PER_CATEGORY:
        fallback_items = _scan_top_rated(table, category=category)
        existing_ids = {i["item_id"] for i in items}
        for item in fallback_items:
            if item["item_id"] not in existing_ids and len(items) < MAX_ITEMS_PER_CATEGORY:
                items.append(item)
                existing_ids.add(item["item_id"])

    return items[:MAX_ITEMS_PER_CATEGORY]


def _scan_content(table, mood: str, category: str, language: str) -> list:
    """Scan content items matching mood tag, category, language, and not deleted."""
    filter_expr = (
        Attr("is_deleted").eq(False)
        & Attr("category").eq(category)
        & Attr("language").eq(language)
        & Attr("mood_tags").contains(mood)
    )

    try:
        result = table.scan(FilterExpression=filter_expr)
        items = result.get("Items", [])
        # Handle DynamoDB pagination
        while "LastEvaluatedKey" in result:
            result = table.scan(
                FilterExpression=filter_expr,
                ExclusiveStartKey=result["LastEvaluatedKey"],
            )
            items.extend(result.get("Items", []))
        return items
    except ClientError as e:
        logger.error("DynamoDB scan error in _scan_content: %s", e)
        return []


def _scan_top_rated(table, category: str) -> list:
    """Scan top-rated active items in a category, sorted by rating descending."""
    filter_expr = (
        Attr("is_deleted").eq(False)
        & Attr("category").eq(category)
    )

    try:
        result = table.scan(FilterExpression=filter_expr)
        items = result.get("Items", [])
        while "LastEvaluatedKey" in result:
            result = table.scan(
                FilterExpression=filter_expr,
                ExclusiveStartKey=result["LastEvaluatedKey"],
            )
            items.extend(result.get("Items", []))
        # Sort by rating descending
        items.sort(key=lambda x: float(x.get("rating", 0)), reverse=True)
        return items
    except ClientError as e:
        logger.error("DynamoDB scan error in _scan_top_rated: %s", e)
        return []
