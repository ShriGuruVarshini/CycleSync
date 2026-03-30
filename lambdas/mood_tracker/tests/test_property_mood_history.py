# Feature: cycle-sync, Property 14: Mood history ordering and window

"""
Property 14: Mood history ordering and window

For any user's mood history response, all entries should have dates within
the last 30 calendar days and the list should be sorted in descending date order.

Validates: Requirements 5.6
"""

import json
import os
import sys
import uuid
from datetime import date, timedelta

import boto3
from botocore.exceptions import ClientError
from hypothesis import given, settings, strategies as st, HealthCheck

from moto import mock_aws

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_MOOD_DIR = os.path.join(os.path.dirname(__file__), "..")
if _MOOD_DIR not in sys.path:
    sys.path.insert(0, _MOOD_DIR)

import handler as mood_handler  # noqa: E402
from handler import lambda_handler  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_REGION = "us-east-1"
_MOOD_TABLE = "cyclesync-mood-entries"

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

valid_mood_strategy = st.sampled_from(["Happy", "Sad", "Angry"])

# Generate a set of day offsets (0 = today, 29 = 29 days ago) to seed entries
# We pick between 1 and 10 distinct offsets within the 30-day window
day_offsets_strategy = st.lists(
    st.integers(min_value=0, max_value=29),
    min_size=1,
    max_size=10,
    unique=True,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_handler_env() -> None:
    mood_handler.MOOD_TABLE_NAME = _MOOD_TABLE
    mood_handler.KMS_KEY_ID = ""
    mood_handler.AWS_REGION = _REGION
    os.environ["AWS_DEFAULT_REGION"] = _REGION
    os.environ["MOOD_TABLE_NAME"] = _MOOD_TABLE
    os.environ["KMS_KEY_ID"] = ""


def _create_mood_table(dynamodb_resource) -> None:
    try:
        dynamodb_resource.create_table(
            TableName=_MOOD_TABLE,
            KeySchema=[
                {"AttributeName": "user_id", "KeyType": "HASH"},
                {"AttributeName": "entry_date", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "user_id", "AttributeType": "S"},
                {"AttributeName": "entry_date", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceInUseException":
            raise


def _seed_entry(dynamodb_resource, user_id: str, entry_date: str, mood: str) -> None:
    """Insert a mood entry directly into DynamoDB."""
    table = dynamodb_resource.Table(_MOOD_TABLE)
    table.put_item(Item={
        "user_id": user_id,
        "entry_date": entry_date,
        "mood": mood,
        "note": "",
        "created_at": f"{entry_date}T08:00:00+00:00",
        "updated_at": f"{entry_date}T08:00:00+00:00",
    })


def _make_get_history_event(user_id: str) -> dict:
    return {
        "httpMethod": "GET",
        "path": "/mood/history",
        "headers": {},
        "body": None,
        "requestContext": {
            "authorizer": {
                "claims": {"sub": user_id}
            }
        },
    }


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------

@mock_aws
@given(day_offsets=day_offsets_strategy, mood=valid_mood_strategy)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_history_entries_within_30_day_window(day_offsets, mood):
    """
    Property 14a: All entries in GET /mood/history should have dates within
    the last 30 calendar days (today inclusive, 29 days back).
    """
    dynamodb = boto3.resource("dynamodb", region_name=_REGION)
    _create_mood_table(dynamodb)
    _patch_handler_env()

    user_id = str(uuid.uuid4())
    today = date.today()

    # Seed entries at the given offsets within the 30-day window
    for offset in day_offsets:
        entry_date = (today - timedelta(days=offset)).isoformat()
        _seed_entry(dynamodb, user_id, entry_date, mood)

    # Also seed one entry outside the 30-day window (31 days ago)
    outside_date = (today - timedelta(days=31)).isoformat()
    _seed_entry(dynamodb, user_id, outside_date, mood)

    # Retrieve history
    event = _make_get_history_event(user_id)
    response = lambda_handler(event, {})

    assert response["statusCode"] == 200, (
        f"GET /mood/history failed with {response['statusCode']}: "
        f"{response.get('body')}"
    )

    body = json.loads(response["body"])
    entries = body.get("entries", [])

    thirty_days_ago = (today - timedelta(days=29)).isoformat()
    today_str = today.isoformat()

    for entry in entries:
        entry_date = entry.get("entry_date", "")
        assert thirty_days_ago <= entry_date <= today_str, (
            f"Entry date {entry_date!r} is outside the 30-day window "
            f"[{thirty_days_ago}, {today_str}]"
        )

    # The outside entry should not appear
    returned_dates = {e.get("entry_date") for e in entries}
    assert outside_date not in returned_dates, (
        f"Entry from {outside_date} (31 days ago) should not appear in history"
    )


@mock_aws
@given(day_offsets=day_offsets_strategy, mood=valid_mood_strategy)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_history_entries_sorted_descending(day_offsets, mood):
    """
    Property 14b: The entries in GET /mood/history should be sorted in
    descending date order (most recent first).
    """
    dynamodb = boto3.resource("dynamodb", region_name=_REGION)
    _create_mood_table(dynamodb)
    _patch_handler_env()

    user_id = str(uuid.uuid4())
    today = date.today()

    # Seed entries at the given offsets
    for offset in day_offsets:
        entry_date = (today - timedelta(days=offset)).isoformat()
        _seed_entry(dynamodb, user_id, entry_date, mood)

    # Retrieve history
    event = _make_get_history_event(user_id)
    response = lambda_handler(event, {})

    assert response["statusCode"] == 200, (
        f"GET /mood/history failed with {response['statusCode']}: "
        f"{response.get('body')}"
    )

    body = json.loads(response["body"])
    entries = body.get("entries", [])

    if len(entries) < 2:
        return  # Nothing to compare

    dates = [e.get("entry_date", "") for e in entries]
    for i in range(len(dates) - 1):
        assert dates[i] >= dates[i + 1], (
            f"History not sorted descending: {dates[i]!r} should be >= {dates[i + 1]!r} "
            f"(full order: {dates})"
        )
