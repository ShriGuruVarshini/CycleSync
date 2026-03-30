# Feature: cycle-sync, Property 4: Passwords are never stored in plaintext

"""
Property 4: Passwords are never stored in plaintext

For any registered user, the value stored for the password should not equal
the original plaintext password string.

Validates: Requirements 1.5
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

valid_password_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"),
        whitelist_characters="!@#$%^&*",
    ),
    min_size=8,
    max_size=32,
)

valid_email_strategy = st.emails()

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


def _all_string_values(item: dict) -> list:
    values = []
    for v in item.values():
        if isinstance(v, str):
            values.append(v)
        elif isinstance(v, dict):
            values.extend(_all_string_values(v))
        elif isinstance(v, list):
            for elem in v:
                if isinstance(elem, str):
                    values.append(elem)
                elif isinstance(elem, dict):
                    values.extend(_all_string_values(elem))
    return values


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------

@mock_aws
@given(
    email=valid_email_strategy,
    password=valid_password_strategy,
)
@settings(max_examples=100, deadline=None)
def test_password_not_stored_in_plaintext(email, password):
    """
    Property 4: After a successful registration, the plaintext password must
    not appear in any DynamoDB attribute value in the cyclesync-users table.
    """
    import handler as auth_handler

    dynamodb = boto3.resource("dynamodb", region_name=_REGION)
    _create_tables(dynamodb)
    _setup_aws_env()
    _patch_handler(auth_handler)

    payload = {
        "email": email,
        "password": password,
        "display_name": "Test User",
        "age": 25,
        "last_period_date": "2024-01-01",
        "cycle_length_days": 28,
    }

    event = _make_api_gw_event(payload)
    response = lambda_handler(event, {})

    # Only assert the hashing property when registration succeeds
    if response["statusCode"] not in (200, 201):
        return

    # Assert plaintext password is NOT in DynamoDB
    table = dynamodb.Table(_USERS_TABLE)
    scan_result = table.scan()
    for item in scan_result.get("Items", []):
        string_values = _all_string_values(item)
        assert password not in string_values, (
            f"Plaintext password found in DynamoDB item: {item}"
        )
