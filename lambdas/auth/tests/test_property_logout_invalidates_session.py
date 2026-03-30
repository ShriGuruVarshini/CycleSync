# Feature: cycle-sync, Property 7: Logout invalidates session

"""
Property 7: Logout invalidates session

For any active session, after the user calls logout, the session token
should be deleted from DynamoDB and subsequent authenticated requests
should be rejected.

Validates: Requirements 2.4
"""

import json
import os
import sys

import boto3
from botocore.exceptions import ClientError
from hypothesis import given, settings, strategies as st, HealthCheck, assume
from moto import mock_aws

# ---------------------------------------------------------------------------
# Path setup — allow importing the auth handler from the lambdas/auth package
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

def _make_register_event(body: dict) -> dict:
    return {
        "rawPath": "/auth/register",
        "httpMethod": "POST",
        "path": "/auth/register",
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
        "requestContext": {"http": {"method": "POST", "path": "/auth/register"}},
    }


def _make_logout_event(token: str) -> dict:
    return {
        "rawPath": "/auth/logout",
        "httpMethod": "POST",
        "path": "/auth/logout",
        "headers": {
            "Content-Type": "application/json",
            "authorization": f"bearer {token}",
        },
        "body": json.dumps({}),
        "requestContext": {"http": {"method": "POST", "path": "/auth/logout"}},
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


def _patch_handler() -> None:
    auth_handler.USERS_TABLE_NAME = _USERS_TABLE
    auth_handler.SESSIONS_TABLE_NAME = _SESSIONS_TABLE
    auth_handler.CONFIG_TABLE_NAME = _CONFIG_TABLE
    auth_handler.AWS_REGION = _REGION
    auth_handler._jwt_secret_cache = None
    auth_handler._ddb = boto3.resource("dynamodb", region_name=_REGION)


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
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_logout_invalidates_session(
    email,
    password,
    display_name,
    age,
    last_period_date,
    cycle_length_days,
):
    """
    Property 7: For any active session, after the user calls logout,
    the session should be invalidated (token deleted from DynamoDB).

    Verifies:
    1. The logout call returns HTTP 200.
    2. After logout, accessing a protected endpoint returns 401.

    Validates: Requirements 2.4
    """
    dynamodb = boto3.resource("dynamodb", region_name=_REGION)
    _create_tables(dynamodb)
    _setup_aws_env()
    _patch_handler()

    # Register the user
    register_payload = {
        "email": email,
        "password": password,
        "display_name": display_name,
        "age": age,
        "last_period_date": last_period_date,
        "cycle_length_days": cycle_length_days,
    }
    register_response = lambda_handler(_make_register_event(register_payload), {})

    # Skip if email already registered in a prior Hypothesis example
    assume(register_response["statusCode"] not in (409,))

    assert register_response["statusCode"] in (200, 201), (
        f"Registration failed with {register_response['statusCode']}: "
        f"{register_response.get('body')}"
    )

    register_body = json.loads(register_response["body"])
    token = register_body.get("token")
    assume(token)  # skip if no token returned

    # Logout: verify it returns 200
    logout_response = lambda_handler(_make_logout_event(token), {})

    assert logout_response["statusCode"] == 200, (
        f"Expected 200 from logout, got {logout_response['statusCode']}. "
        f"Body: {logout_response.get('body')}"
    )

    logout_body = json.loads(logout_response["body"])
    assert "message" in logout_body, (
        f"Expected 'message' in logout response body, got: {logout_body}"
    )

    # After logout, the session token should be deleted from DynamoDB
    sessions_table = dynamodb.Table(_SESSIONS_TABLE)
    resp = sessions_table.get_item(Key={"token": token})
    assert "Item" not in resp, (
        f"Expected session to be deleted after logout, but it still exists"
    )

    # Accessing a protected endpoint with the invalidated token should return 401
    profile_response = lambda_handler(_make_get_profile_event(token), {})
    assert profile_response["statusCode"] == 401, (
        f"Expected 401 after logout, got {profile_response['statusCode']}. "
        f"Body: {profile_response.get('body')}"
    )
