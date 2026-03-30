# Feature: cycle-sync, Property 8: Profile update round-trip

"""
Property 8: Profile update round-trip

For any valid profile update payload (name, age, last period date, cycle length
in range), saving it should result in the updated values being returned on the
next profile fetch.

Validates: Requirements 3.1
"""

import json
import os
import sys
import uuid

import boto3
from botocore.exceptions import ClientError
from hypothesis import given, settings, strategies as st, HealthCheck

from moto import mock_aws

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_AUTH_DIR = os.path.join(os.path.dirname(__file__), "..")
if _AUTH_DIR not in sys.path:
    sys.path.insert(0, _AUTH_DIR)

import handler as auth_handler  # noqa: E402
from handler import lambda_handler  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_REGION = "us-east-1"
_USERS_TABLE = "cyclesync-users"
_SESSIONS_TABLE = "cyclesync-sessions"
_CONFIG_TABLE = "cyclesync-config"
_JWT_SECRET = "test-secret-for-property-tests"

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

valid_display_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs")),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip())

valid_age_strategy = st.integers(min_value=18, max_value=45)

valid_date_strategy = st.dates(
    min_value=__import__("datetime").date(2023, 1, 1),
    max_value=__import__("datetime").date(2025, 12, 31),
).map(lambda d: d.strftime("%Y-%m-%d"))

valid_cycle_length_strategy = st.integers(min_value=21, max_value=45)

valid_language_strategy = st.sampled_from(["en", "hi", "ta", "es"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_aws_env() -> None:
    os.environ["AWS_DEFAULT_REGION"] = _REGION
    os.environ["USERS_TABLE"] = _USERS_TABLE
    os.environ["SESSIONS_TABLE"] = _SESSIONS_TABLE
    os.environ["CONFIG_TABLE"] = _CONFIG_TABLE


def _patch_handler() -> None:
    auth_handler.USERS_TABLE_NAME = _USERS_TABLE
    auth_handler.SESSIONS_TABLE_NAME = _SESSIONS_TABLE
    auth_handler.CONFIG_TABLE_NAME = _CONFIG_TABLE
    auth_handler.AWS_REGION = _REGION
    auth_handler._jwt_secret_cache = None
    auth_handler._ddb = boto3.resource("dynamodb", region_name=_REGION)


def _create_tables(dynamodb_resource) -> None:
    try:
        dynamodb_resource.create_table(
            TableName=_USERS_TABLE,
            KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "user_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
    except Exception:
        pass

    try:
        dynamodb_resource.create_table(
            TableName=_SESSIONS_TABLE,
            KeySchema=[{"AttributeName": "token", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "token", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
    except Exception:
        pass

    try:
        config_table = dynamodb_resource.create_table(
            TableName=_CONFIG_TABLE,
            KeySchema=[{"AttributeName": "config_key", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "config_key", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        config_table.put_item(Item={"config_key": "jwt_secret", "value": _JWT_SECRET})
    except Exception:
        pass


def _seed_user(dynamodb_resource, user_id: str) -> None:
    """Insert a minimal user record directly into DynamoDB."""
    table = dynamodb_resource.Table(_USERS_TABLE)
    table.put_item(Item={
        "user_id": user_id,
        "email": f"{user_id}@example.com",
        "display_name": "Original Name",
        "age": 25,
        "last_period_date": "2024-01-01",
        "cycle_length_days": 28,
        "language_preference": "en",
        "hobby_preferences": [],
        "notifications_on": True,
        "created_at": "2024-01-01T00:00:00+00:00",
        "updated_at": "2024-01-01T00:00:00+00:00",
    })


def _create_session(dynamodb_resource, token: str, user_id: str) -> None:
    """Store a session token in DynamoDB so _require_auth passes."""
    import time
    table = dynamodb_resource.Table(_SESSIONS_TABLE)
    table.put_item(Item={
        "token": token,
        "user_id": user_id,
        "ttl": int(time.time()) + 1800,
    })


def _make_put_profile_event(token: str, body: dict) -> dict:
    return {
        "rawPath": "/profile",
        "httpMethod": "PUT",
        "path": "/profile",
        "headers": {
            "Content-Type": "application/json",
            "authorization": f"bearer {token}",
        },
        "body": json.dumps(body),
        "requestContext": {"http": {"method": "PUT", "path": "/profile"}},
    }


def _make_get_profile_event(token: str) -> dict:
    return {
        "rawPath": "/profile",
        "httpMethod": "GET",
        "path": "/profile",
        "headers": {"authorization": f"bearer {token}"},
        "body": None,
        "requestContext": {"http": {"method": "GET", "path": "/profile"}},
    }


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------

@mock_aws
@given(
    display_name=valid_display_name_strategy,
    age=valid_age_strategy,
    last_period_date=valid_date_strategy,
    cycle_length_days=valid_cycle_length_strategy,
    language_preference=valid_language_strategy,
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_profile_update_roundtrip(
    display_name,
    age,
    last_period_date,
    cycle_length_days,
    language_preference,
):
    """
    Property 8: For any valid profile update payload, saving it via PUT /profile
    should result in the same values being returned by the subsequent GET /profile.
    """
    dynamodb = boto3.resource("dynamodb", region_name=_REGION)
    _create_tables(dynamodb)
    _setup_aws_env()
    _patch_handler()

    user_id = str(uuid.uuid4())
    _seed_user(dynamodb, user_id)

    # Create a real JWT token and store the session
    token = auth_handler._create_token(user_id)
    _create_session(dynamodb, token, user_id)

    update_payload = {
        "display_name": display_name,
        "age": age,
        "last_period_date": last_period_date,
        "cycle_length_days": cycle_length_days,
        "language_preference": language_preference,
    }

    put_event = _make_put_profile_event(token, update_payload)
    put_response = lambda_handler(put_event, {})

    assert put_response["statusCode"] == 200, (
        f"PUT /profile failed with {put_response['statusCode']}: "
        f"{put_response.get('body')}"
    )

    get_event = _make_get_profile_event(token)
    get_response = lambda_handler(get_event, {})

    assert get_response["statusCode"] == 200, (
        f"GET /profile failed with {get_response['statusCode']}: "
        f"{get_response.get('body')}"
    )

    profile = json.loads(get_response["body"])

    assert profile["display_name"] == display_name, (
        f"display_name mismatch: expected {display_name!r}, got {profile.get('display_name')!r}"
    )
    assert int(profile["age"]) == age, (
        f"age mismatch: expected {age}, got {profile.get('age')}"
    )
    assert profile["last_period_date"] == last_period_date, (
        f"last_period_date mismatch: expected {last_period_date!r}, got {profile.get('last_period_date')!r}"
    )
    assert int(profile["cycle_length_days"]) == cycle_length_days, (
        f"cycle_length_days mismatch: expected {cycle_length_days}, got {profile.get('cycle_length_days')}"
    )
    assert profile["language_preference"] == language_preference, (
        f"language_preference mismatch: expected {language_preference!r}, got {profile.get('language_preference')!r}"
    )
