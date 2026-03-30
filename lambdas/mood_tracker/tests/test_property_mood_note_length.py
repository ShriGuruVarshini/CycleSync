# Feature: cycle-sync, Property 11: Mood note length enforcement

"""
Property 11: Mood note length enforcement

For any mood entry note longer than 500 characters, the mood_tracker Lambda
should reject the submission. For any note of 500 characters or fewer, length
alone should not cause rejection.

Validates: Requirements 5.2
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

# Notes strictly longer than 500 characters
long_note_strategy = st.text(min_size=501, max_size=1000)

# Notes of 500 characters or fewer (including empty)
valid_note_strategy = st.text(min_size=0, max_size=500)

valid_mood_strategy = st.sampled_from(["Happy", "Sad", "Angry"])

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


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------

@mock_aws
@given(mood=valid_mood_strategy, note=long_note_strategy)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_note_over_500_chars_rejected(mood, note):
    """
    Property 11a: For any note longer than 500 characters,
    POST /mood should return 400 with error="note".
    """
    dynamodb = boto3.resource("dynamodb", region_name=_REGION)
    _create_mood_table(dynamodb)
    _patch_handler_env()

    user_id = str(uuid.uuid4())
    event = _make_post_mood_event(user_id, mood, note)
    response = lambda_handler(event, {})

    assert response["statusCode"] == 400, (
        f"Expected 400 for note of length {len(note)}, "
        f"got {response['statusCode']}: {response.get('body')}"
    )

    body = json.loads(response["body"])
    assert body.get("error") == "note", (
        f"Expected error='note', got error={body.get('error')!r} "
        f"for note of length {len(note)}"
    )


@mock_aws
@given(mood=valid_mood_strategy, note=valid_note_strategy)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_note_500_chars_or_fewer_accepted(mood, note):
    """
    Property 11b: For any note of 500 characters or fewer,
    note length alone should not cause POST /mood to return 400.
    """
    dynamodb = boto3.resource("dynamodb", region_name=_REGION)
    _create_mood_table(dynamodb)
    _patch_handler_env()

    user_id = str(uuid.uuid4())
    event = _make_post_mood_event(user_id, mood, note)
    response = lambda_handler(event, {})

    # Note length alone should not cause rejection — 200 expected
    assert response["statusCode"] == 200, (
        f"Expected 200 for note of length {len(note)}, "
        f"got {response['statusCode']}: {response.get('body')}"
    )
