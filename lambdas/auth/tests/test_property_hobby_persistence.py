# Feature: cycle-sync, Property 18: Hobby preference persistence round-trip

"""
Property 18: Hobby preference persistence round-trip

For any non-empty subset of {Songs, Movies, Poetry, Digital Colouring}, saving it
as hobby preferences should result in the same set being returned on the next
profile fetch from DynamoDB. Similarly, saving a Language_Preference code should
return the same code on the next fetch.

Validates: Requirements 7.3, 7.4, 7.7
"""

import json
import os
import sys
import uuid
import time

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
_ALL_HOBBIES = ["Songs", "Movies", "Poetry", "Digital Colouring"]

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

hobby_subset_strategy = st.lists(
    st.sampled_from(_ALL_HOBBIES),
    min_size=1,
    unique=True,
)

language_strategy = st.sampled_from(["en", "hi", "ta", "es"])

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
    table = dynamodb_resource.Table(_USERS_TABLE)
    table.put_item(Item={
        "user_id": user_id,
        "email": f"{user_id}@example.com",
        "display_name": "Test User",
        "age": 28,
        "last_period_date": "2024-01-01",
        "cycle_length_days": 28,
        "language_preference": "en",
        "hobby_preferences": [],
        "notifications_on": True,
        "created_at": "2024-01-01T00:00:00+00:00",
        "updated_at": "2024-01-01T00:00:00+00:00",
    })


def _create_session(dynamodb_resource, token: str, user_id: str) -> None:
    table = dynamodb_resource.Table(_SESSIONS_TABLE)
    table.put_item(Item={
        "token": token,
        "user_id": user_id,
        "ttl": int(time.time()) + 1800,
    })


def _make_put_hobbies_event(token: str, hobbies: list) -> dict:
    return {
        "rawPath": "/profile/hobbies",
        "httpMethod": "PUT",
        "path": "/profile/hobbies",
        "headers": {
            "Content-Type": "application/json",
            "authorization": f"bearer {token}",
        },
        "body": json.dumps({"hobby_preferences": hobbies}),
        "requestContext": {"http": {"method": "PUT", "path": "/profile/hobbies"}},
    }


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
# Property test: hobby preferences round-trip
# ---------------------------------------------------------------------------

@mock_aws
@given(hobbies=hobby_subset_strategy)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_hobby_preferences_roundtrip(hobbies):
    """
    Property 18 (hobbies): For any non-empty subset of valid hobby options,
    saving via PUT /profile/hobbies should return the same set on GET /profile.
    """
    dynamodb = boto3.resource("dynamodb", region_name=_REGION)
    _create_tables(dynamodb)
    _setup_aws_env()
    _patch_handler()

    user_id = str(uuid.uuid4())
    _seed_user(dynamodb, user_id)
    token = auth_handler._create_token(user_id)
    _create_session(dynamodb, token, user_id)

    put_event = _make_put_hobbies_event(token, hobbies)
    put_response = lambda_handler(put_event, {})

    assert put_response["statusCode"] == 200, (
        f"PUT /profile/hobbies failed with {put_response['statusCode']}: "
        f"{put_response.get('body')}"
    )

    get_event = _make_get_profile_event(token)
    get_response = lambda_handler(get_event, {})

    assert get_response["statusCode"] == 200, (
        f"GET /profile failed with {get_response['statusCode']}: "
        f"{get_response.get('body')}"
    )

    profile = json.loads(get_response["body"])

    assert set(profile["hobby_preferences"]) == set(hobbies), (
        f"hobby_preferences mismatch: expected {set(hobbies)!r}, "
        f"got {set(profile.get('hobby_preferences', []))!r}"
    )


# ---------------------------------------------------------------------------
# Property test: language preference round-trip
# ---------------------------------------------------------------------------

@mock_aws
@given(language=language_strategy)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_language_preference_roundtrip(language):
    """
    Property 18 (language): For any valid language code, saving via
    PUT /profile should return the same code on GET /profile.
    """
    dynamodb = boto3.resource("dynamodb", region_name=_REGION)
    _create_tables(dynamodb)
    _setup_aws_env()
    _patch_handler()

    user_id = str(uuid.uuid4())
    _seed_user(dynamodb, user_id)
    token = auth_handler._create_token(user_id)
    _create_session(dynamodb, token, user_id)

    put_event = _make_put_profile_event(token, {"language_preference": language})
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

    assert profile["language_preference"] == language, (
        f"language_preference mismatch: expected {language!r}, "
        f"got {profile.get('language_preference')!r}"
    )
