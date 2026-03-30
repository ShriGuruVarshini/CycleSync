# Feature: cycle-sync, Property 13: One mood entry per day (upsert invariant)

"""
Property 13: One mood entry per day (upsert invariant)

For any user and any number of mood submissions on the same calendar day,
querying that day's entry should return exactly one record reflecting the
most recent submission.

Validates: Requirements 5.4, 5.5
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

# A list of 2 to 5 mood submissions representing multiple submissions in one day
multiple_submissions_strategy = st.lists(
    valid_mood_strategy,
    min_size=2,
    max_size=5,
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


def _make_post_mood_event(user_id: str, mood: str, note: str = "") -> dict:
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
@given(submissions=multiple_submissions_strategy)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_only_one_entry_per_day_after_multiple_submissions(submissions):
    """
    Property 13a: After submitting multiple mood entries on the same day,
    GET /mood/today should return exactly one entry reflecting the last submission.
    """
    dynamodb = boto3.resource("dynamodb", region_name=_REGION)
    _create_mood_table(dynamodb)
    _patch_handler_env()

    user_id = str(uuid.uuid4())

    # Submit all moods in sequence
    for mood in submissions:
        post_event = _make_post_mood_event(user_id, mood)
        post_response = lambda_handler(post_event, {})
        assert post_response["statusCode"] == 200, (
            f"POST /mood failed with {post_response['statusCode']}: "
            f"{post_response.get('body')}"
        )

    # Retrieve today's entry
    get_event = _make_get_today_event(user_id)
    get_response = lambda_handler(get_event, {})

    assert get_response["statusCode"] == 200, (
        f"GET /mood/today failed with {get_response['statusCode']}: "
        f"{get_response.get('body')}"
    )

    body = json.loads(get_response["body"])
    entry = body.get("entry")

    assert entry is not None, "Expected an entry to be returned, got None"

    # The entry should reflect the most recent (last) submission
    last_mood = submissions[-1]
    assert entry["mood"] == last_mood, (
        f"Expected most recent mood {last_mood!r}, got {entry.get('mood')!r}"
    )


@mock_aws
@given(submissions=multiple_submissions_strategy)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_history_has_exactly_one_entry_for_today_after_multiple_submissions(submissions):
    """
    Property 13b: After submitting multiple mood entries on the same day,
    GET /mood/history should contain exactly one entry for today's date.
    """
    from datetime import date

    dynamodb = boto3.resource("dynamodb", region_name=_REGION)
    _create_mood_table(dynamodb)
    _patch_handler_env()

    user_id = str(uuid.uuid4())
    today_str = date.today().isoformat()

    # Submit all moods in sequence
    for mood in submissions:
        post_event = _make_post_mood_event(user_id, mood)
        post_response = lambda_handler(post_event, {})
        assert post_response["statusCode"] == 200, (
            f"POST /mood failed with {post_response['statusCode']}: "
            f"{post_response.get('body')}"
        )

    # Retrieve history
    history_event = _make_get_history_event(user_id)
    history_response = lambda_handler(history_event, {})

    assert history_response["statusCode"] == 200, (
        f"GET /mood/history failed with {history_response['statusCode']}: "
        f"{history_response.get('body')}"
    )

    body = json.loads(history_response["body"])
    entries = body.get("entries", [])

    # Count entries for today
    today_entries = [e for e in entries if e.get("entry_date") == today_str]

    assert len(today_entries) == 1, (
        f"Expected exactly 1 entry for today ({today_str}), "
        f"got {len(today_entries)} after {len(submissions)} submissions"
    )
