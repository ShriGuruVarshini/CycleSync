# Feature: cycle-sync, Property 12: Mood entry persistence round-trip

"""
Property 12: Mood entry persistence round-trip

For any valid mood entry (mood value + optional note), after submission the
entry should be retrievable from DynamoDB with the same mood value, note,
and a timestamp.

Validates: Requirements 5.3
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

# Optional note: empty string or up to 500 chars
optional_note_strategy = st.one_of(
    st.just(""),
    st.text(min_size=1, max_size=500),
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


def _make_post_mood_event(user_id: str, mood: str, note: str) -> dict:
    return {
        "httpMethod": "POST",
        "path": "/mood",
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"mood": mood, "note": note}),
        "requestContext": {
            "authorizer": {
                "claims": {"sub": user_id}
            }
        },
    }


def _make_get_today_event(user_id: str) -> dict:
    return {
        "httpMethod": "GET",
        "path": "/mood/today",
        "headers": {},
        "body": None,
        "requestContext": {
            "authorizer": {
                "claims": {"sub": user_id}
            }
        },
    }


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------

@mock_aws
@given(mood=valid_mood_strategy, note=optional_note_strategy)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_mood_entry_persistence_roundtrip(mood, note):
    """
    Property 12: For any valid mood entry (mood + optional note), after
    POST /mood the entry should be retrievable via GET /mood/today with
    the same mood value, note, and a timestamp.
    """
    dynamodb = boto3.resource("dynamodb", region_name=_REGION)
    _create_mood_table(dynamodb)
    _patch_handler_env()

    user_id = str(uuid.uuid4())

    # --- POST /mood ---
    post_event = _make_post_mood_event(user_id, mood, note)
    post_response = lambda_handler(post_event, {})

    assert post_response["statusCode"] == 200, (
        f"POST /mood failed with {post_response['statusCode']}: "
        f"{post_response.get('body')}"
    )

    # --- GET /mood/today ---
    get_event = _make_get_today_event(user_id)
    get_response = lambda_handler(get_event, {})

    assert get_response["statusCode"] == 200, (
        f"GET /mood/today failed with {get_response['statusCode']}: "
        f"{get_response.get('body')}"
    )

    body = json.loads(get_response["body"])
    entry = body.get("entry")

    assert entry is not None, "Expected an entry to be returned, got None"

    assert entry["mood"] == mood, (
        f"mood mismatch: expected {mood!r}, got {entry.get('mood')!r}"
    )
    assert entry["note"] == note, (
        f"note mismatch: expected {note!r}, got {entry.get('note')!r}"
    )
    assert "created_at" in entry and entry["created_at"], (
        "Expected a non-empty created_at timestamp in the retrieved entry"
    )
    assert "updated_at" in entry and entry["updated_at"], (
        "Expected a non-empty updated_at timestamp in the retrieved entry"
    )
