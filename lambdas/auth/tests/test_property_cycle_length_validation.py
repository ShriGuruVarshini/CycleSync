# Feature: cycle-sync, Property 9: Cycle length validation

"""
Property 9: Cycle length validation

For any cycle length value outside the range [21, 45], the profile Lambda
should return a validation error. For any value within [21, 45], it should
be accepted.

Validates: Requirements 3.3
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

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

invalid_cycle_length_strategy = st.one_of(
    st.integers(max_value=20),
    st.integers(min_value=46),
)

valid_cycle_length_strategy = st.integers(min_value=21, max_value=45)

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


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------

@mock_aws
@given(cycle_length_days=invalid_cycle_length_strategy)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_invalid_cycle_length_returns_400(cycle_length_days):
    """
    Property 9a: For any cycle_length_days < 21 or > 45,
    PUT /profile should return 400 with error="cycle_length_days".
    """
    dynamodb = boto3.resource("dynamodb", region_name=_REGION)
    _create_tables(dynamodb)
    _setup_aws_env()
    _patch_handler()

    user_id = str(uuid.uuid4())
    _seed_user(dynamodb, user_id)
    token = auth_handler._create_token(user_id)
    _create_session(dynamodb, token, user_id)

    event = _make_put_profile_event(token, {"cycle_length_days": cycle_length_days})
    response = lambda_handler(event, {})

    assert response["statusCode"] == 400, (
        f"Expected 400 for cycle_length_days={cycle_length_days}, "
        f"got {response['statusCode']}: {response.get('body')}"
    )

    body = json.loads(response["body"])
    assert body.get("error") == "cycle_length_days", (
        f"Expected error='cycle_length_days', got error={body.get('error')!r} "
        f"for cycle_length_days={cycle_length_days}"
    )


@mock_aws
@given(cycle_length_days=valid_cycle_length_strategy)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_valid_cycle_length_returns_200(cycle_length_days):
    """
    Property 9b: For any cycle_length_days in [21, 45],
    PUT /profile should return 200.
    """
    dynamodb = boto3.resource("dynamodb", region_name=_REGION)
    _create_tables(dynamodb)
    _setup_aws_env()
    _patch_handler()

    user_id = str(uuid.uuid4())
    _seed_user(dynamodb, user_id)
    token = auth_handler._create_token(user_id)
    _create_session(dynamodb, token, user_id)

    event = _make_put_profile_event(token, {"cycle_length_days": cycle_length_days})
    response = lambda_handler(event, {})

    assert response["statusCode"] == 200, (
        f"Expected 200 for cycle_length_days={cycle_length_days}, "
        f"got {response['statusCode']}: {response.get('body')}"
    )
