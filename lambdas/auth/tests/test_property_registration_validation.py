# Feature: cycle-sync, Property 1: Registration rejects missing required fields

"""
Property 1: Registration rejects missing required fields

For any registration request missing one or more required fields (email,
password, display name, age, last period date, cycle length), the Auth_Service
should return a validation error and no user account should be created.

Validates: Requirements 1.1
"""

import json
import os
import sys

import boto3
import pytest
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

REQUIRED_FIELDS = [
    "email",
    "password",
    "display_name",
    "age",
    "last_period_date",
    "cycle_length_days",
]

_REGION = "us-east-1"
_USERS_TABLE = "cyclesync-users"
_SESSIONS_TABLE = "cyclesync-sessions"
_CONFIG_TABLE = "cyclesync-config"
_JWT_SECRET = "test-secret-for-property-tests"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_valid_payload() -> dict:
    return {
        "email": "test@example.com",
        "password": "Password1!",
        "display_name": "Test User",
        "age": 25,
        "last_period_date": "2024-01-01",
        "cycle_length_days": 28,
    }


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
    # Users table with email GSI
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

    # Sessions table
    try:
        dynamodb_resource.create_table(
            TableName=_SESSIONS_TABLE,
            KeySchema=[{"AttributeName": "token", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "token", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
    except Exception:
        pass

    # Config table with JWT secret
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


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------

@mock_aws
@given(
    missing_fields=st.lists(
        st.sampled_from(REQUIRED_FIELDS),
        min_size=1,
        max_size=len(REQUIRED_FIELDS),
        unique=True,
    )
)
@settings(max_examples=100, deadline=None)
def test_registration_rejects_missing_required_fields(missing_fields):
    """
    Property 1: For any subset of required fields that is absent from the
    registration payload, the handler must return HTTP 400 and must NOT
    create a user in DynamoDB.
    """
    import handler as auth_handler

    dynamodb = boto3.resource("dynamodb", region_name=_REGION)
    _create_tables(dynamodb)
    _setup_aws_env()
    _patch_handler(auth_handler)

    payload = make_valid_payload()
    for field in missing_fields:
        del payload[field]

    event = _make_api_gw_event(payload)
    response = lambda_handler(event, {})

    assert response["statusCode"] == 400, (
        f"Expected 400 for missing fields {missing_fields}, "
        f"got {response['statusCode']}. Body: {response.get('body')}"
    )

    # Assert no user was created in DynamoDB
    table = dynamodb.Table(_USERS_TABLE)
    scan_result = table.scan()
    assert len(scan_result.get("Items", [])) == 0, (
        f"A user was created despite missing fields {missing_fields}"
    )
