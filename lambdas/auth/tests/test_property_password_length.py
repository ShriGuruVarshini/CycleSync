# Feature: cycle-sync, Property 3: Password minimum length enforcement

"""
Property 3: Password minimum length enforcement

For any password string shorter than 8 characters, the Auth_Service should
reject the registration and return an error. For any password of 8 or more
characters, length alone should not cause rejection.

Validates: Requirements 1.4
"""

import json
import os
import sys

import boto3
from hypothesis import given, settings, strategies as st
from moto import mock_aws

# ---------------------------------------------------------------------------
# Path setup — allow importing the auth handler from the lambdas/auth package
# ---------------------------------------------------------------------------
_AUTH_DIR = os.path.join(os.path.dirname(__file__), "..")
if _AUTH_DIR not in sys.path:
    sys.path.insert(0, _AUTH_DIR)

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

short_password_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"),
        whitelist_characters="!@#$%^&*",
    ),
    min_size=0,
    max_size=7,
)

valid_length_password_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"),
        whitelist_characters="!@#$%^&*",
    ),
    min_size=8,
    max_size=32,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_api_gw_event(body: dict) -> dict:
    return {
        "rawPath": "/auth/register",
        "httpMethod": "POST",
        "path": "/auth/register",
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
        "requestContext": {"http": {"method": "POST", "path": "/auth/register"}},
    }


def _setup_aws_env() -> None:
    os.environ["AWS_DEFAULT_REGION"] = _REGION
    os.environ["USERS_TABLE"] = _USERS_TABLE
    os.environ["SESSIONS_TABLE"] = _SESSIONS_TABLE
    os.environ["CONFIG_TABLE"] = _CONFIG_TABLE


def _create_tables(dynamodb_resource) -> None:
    try:
        dynamodb_resource.create_table(
            TableName=_USERS_TABLE,
            KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "user_id", "AttributeType": "S"},
                {"AttributeName": "email", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[{
                "IndexName": "email-index",
                "KeySchema": [{"AttributeName": "email", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }],
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


def _patch_handler(handler_module) -> None:
    handler_module.USERS_TABLE_NAME = _USERS_TABLE
    handler_module.SESSIONS_TABLE_NAME = _SESSIONS_TABLE
    handler_module.CONFIG_TABLE_NAME = _CONFIG_TABLE
    handler_module.AWS_REGION = _REGION
    handler_module._jwt_secret_cache = None
    handler_module._ddb = boto3.resource("dynamodb", region_name=_REGION)


def _base_payload(password: str) -> dict:
    return {
        "email": "test@example.com",
        "password": password,
        "display_name": "Test User",
        "age": 25,
        "last_period_date": "2024-01-01",
        "cycle_length_days": 28,
    }


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------

@mock_aws
@given(password=short_password_strategy)
@settings(max_examples=100, deadline=None)
def test_short_password_is_rejected(password):
    """
    Property 3 (short side): For any password shorter than 8 characters,
    the handler must return HTTP 400.
    """
    import handler as auth_handler

    dynamodb = boto3.resource("dynamodb", region_name=_REGION)
    _create_tables(dynamodb)
    _setup_aws_env()
    _patch_handler(auth_handler)

    payload = _base_payload(password)
    event = _make_api_gw_event(payload)
    response = lambda_handler(event, {})

    assert response["statusCode"] == 400, (
        f"Expected 400 for short password (len={len(password)}), "
        f"got {response['statusCode']}. Body: {response.get('body')}"
    )


@mock_aws
@given(password=valid_length_password_strategy)
@settings(max_examples=100, deadline=None)
def test_valid_length_password_not_rejected_for_length(password):
    """
    Property 3 (valid-length side): For any password of 8 or more characters,
    the handler must NOT return 400 due to password length alone.
    """
    import handler as auth_handler

    dynamodb = boto3.resource("dynamodb", region_name=_REGION)
    _create_tables(dynamodb)
    _setup_aws_env()
    _patch_handler(auth_handler)

    payload = _base_payload(password)
    event = _make_api_gw_event(payload)
    response = lambda_handler(event, {})

    # Accept 200/201 (success) or 409 (duplicate email in repeated runs).
    if response["statusCode"] == 400:
        body_str = response.get("body", "")
        assert "password" not in body_str.lower() or "length" not in body_str.lower(), (
            f"Handler rejected a {len(password)}-char password for length reasons. "
            f"Body: {body_str}"
        )
