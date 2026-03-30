# Feature: cycle-sync, Property 2: Registration round-trip

"""
Property 2: Registration round-trip

For any valid registration payload (unique email, password >= 8 chars, all
required fields present), submitting it should result in a new user existing
in the system and a valid session token being returned.

Validates: Requirements 1.2
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

_REGION = "us-east-1"
_USERS_TABLE = "cyclesync-users"
_SESSIONS_TABLE = "cyclesync-sessions"
_CONFIG_TABLE = "cyclesync-config"
_JWT_SECRET = "test-secret-for-property-tests"


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

valid_email_strategy = st.emails()

valid_password_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"),
        whitelist_characters="!@#$%^&*",
    ),
    min_size=8,
    max_size=32,
)

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

    # Config table for JWT secret
    try:
        config_table = dynamodb_resource.create_table(
            TableName=_CONFIG_TABLE,
            KeySchema=[{"AttributeName": "config_key", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "config_key", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        config_table.put_item(Item={"config_key": "jwt_secret", "value": _JWT_SECRET})
    except Exception:
        # Table already exists — ensure JWT secret is seeded
        try:
            dynamodb_resource.Table(_CONFIG_TABLE).put_item(
                Item={"config_key": "jwt_secret", "value": _JWT_SECRET}
            )
        except Exception:
            pass


def _patch_handler(handler_module) -> None:
    """Patch handler module-level constants and reset JWT cache."""
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
    email=valid_email_strategy,
    password=valid_password_strategy,
    display_name=valid_display_name_strategy,
    age=valid_age_strategy,
    last_period_date=valid_date_strategy,
    cycle_length_days=valid_cycle_length_strategy,
)
@settings(max_examples=100, deadline=None)
def test_registration_roundtrip(
    email,
    password,
    display_name,
    age,
    last_period_date,
    cycle_length_days,
):
    """
    Property 2: For any valid registration payload (unique email, password >= 8
    chars, all required fields present), the handler must:
      - Return HTTP 200 or 201
      - Include a token in the response body
      - Create a user record in the cyclesync-users DynamoDB table
    """
    import handler as auth_handler

    dynamodb = boto3.resource("dynamodb", region_name=_REGION)
    _create_tables(dynamodb)
    _setup_aws_env()
    _patch_handler(auth_handler)

    payload = {
        "email": email,
        "password": password,
        "display_name": display_name,
        "age": age,
        "last_period_date": last_period_date,
        "cycle_length_days": cycle_length_days,
    }

    event = _make_api_gw_event(payload)
    response = lambda_handler(event, {})

    assert response["statusCode"] in (200, 201), (
        f"Expected 200 or 201 for valid payload, got {response['statusCode']}. "
        f"Body: {response.get('body')}"
    )

    body = json.loads(response["body"])
    # Handler returns "token" (JWT)
    has_token = bool(body.get("token") or body.get("id_token") or body.get("IdToken"))
    assert has_token, (
        f"Expected a token in response body, got: {body}"
    )

    # Assert user record exists in DynamoDB
    table = dynamodb.Table(_USERS_TABLE)
    scan_result = table.scan()
    user_records = scan_result.get("Items", [])
    assert len(user_records) >= 1, (
        f"Expected at least one user record in DynamoDB after registration, "
        f"found {len(user_records)}"
    )

    emails_in_db = [item.get("email") for item in user_records]
    assert email.lower().strip() in emails_in_db, (
        f"Expected email '{email.lower().strip()}' to be stored in DynamoDB, "
        f"found emails: {emails_in_db}"
    )
