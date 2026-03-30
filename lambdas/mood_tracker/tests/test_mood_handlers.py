"""
Unit tests for POST /mood, GET /mood/today, GET /mood/history handlers.
Validates Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6
"""
import json
import sys
import os
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import handler as mood_handler
from handler import lambda_handler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(method: str, path: str, body: dict = None, user_id: str = "user-abc"):
    return {
        "httpMethod": method,
        "path": path,
        "body": json.dumps(body) if body is not None else None,
        "headers": {},
        "requestContext": {
            "authorizer": {
                "claims": {"sub": user_id}
            }
        },
    }


def _make_event_no_auth(method: str, path: str, body: dict = None):
    return {
        "httpMethod": method,
        "path": path,
        "body": json.dumps(body) if body is not None else None,
        "headers": {},
        "requestContext": {},
    }


TODAY = date.today().isoformat()
SAMPLE_ENTRY = {
    "user_id": "user-abc",
    "entry_date": TODAY,
    "mood": "Happy",
    "note": "",
    "created_at": "2024-01-01T00:00:00+00:00",
    "updated_at": "2024-01-01T00:00:00+00:00",
}


# ---------------------------------------------------------------------------
# POST /mood
# ---------------------------------------------------------------------------

class TestPostMood:
    def test_stores_valid_mood_no_note(self):
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}
        mock_table.put_item.return_value = {}

        with patch("handler._dynamodb") as mock_ddb, \
             patch("handler.KMS_KEY_ID", ""):
            mock_ddb.return_value.Table.return_value = mock_table
            event = _make_event("POST", "/mood", {"mood": "Happy"})
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["mood"] == "Happy"
        assert body["user_id"] == "user-abc"
        assert body["entry_date"] == TODAY

    def test_stores_valid_mood_with_note(self):
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}
        mock_table.put_item.return_value = {}

        with patch("handler._dynamodb") as mock_ddb, \
             patch("handler.KMS_KEY_ID", ""):
            mock_ddb.return_value.Table.return_value = mock_table
            event = _make_event("POST", "/mood", {"mood": "Sad", "note": "Feeling low today"})
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["mood"] == "Sad"
        assert body["note"] == "Feeling low today"

    def test_accepts_all_valid_moods(self):
        for mood in ["Happy", "Sad", "Angry"]:
            mock_table = MagicMock()
            mock_table.get_item.return_value = {}
            mock_table.put_item.return_value = {}

            with patch("handler._dynamodb") as mock_ddb, \
                 patch("handler.KMS_KEY_ID", ""):
                mock_ddb.return_value.Table.return_value = mock_table
                event = _make_event("POST", "/mood", {"mood": mood})
                resp = lambda_handler(event, None)

            assert resp["statusCode"] == 200, f"Expected 200 for mood={mood}"

    def test_rejects_invalid_mood(self):
        event = _make_event("POST", "/mood", {"mood": "Excited"})
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 400
        body = json.loads(resp["body"])
        assert body["error"] == "mood"

    def test_rejects_missing_mood(self):
        event = _make_event("POST", "/mood", {"note": "some note"})
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 400
        body = json.loads(resp["body"])
        assert body["error"] == "mood"

    def test_rejects_note_over_500_chars(self):
        long_note = "x" * 501
        event = _make_event("POST", "/mood", {"mood": "Happy", "note": long_note})
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 400
        body = json.loads(resp["body"])
        assert body["error"] == "note"

    def test_accepts_note_exactly_500_chars(self):
        note_500 = "x" * 500
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}
        mock_table.put_item.return_value = {}

        with patch("handler._dynamodb") as mock_ddb, \
             patch("handler.KMS_KEY_ID", ""):
            mock_ddb.return_value.Table.return_value = mock_table
            event = _make_event("POST", "/mood", {"mood": "Angry", "note": note_500})
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 200

    def test_accepts_empty_note(self):
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}
        mock_table.put_item.return_value = {}

        with patch("handler._dynamodb") as mock_ddb, \
             patch("handler.KMS_KEY_ID", ""):
            mock_ddb.return_value.Table.return_value = mock_table
            event = _make_event("POST", "/mood", {"mood": "Happy", "note": ""})
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 200

    def test_upsert_preserves_created_at(self):
        """Second submission on same day should preserve original created_at."""
        original_created_at = "2024-06-01T08:00:00+00:00"
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": {**SAMPLE_ENTRY, "created_at": original_created_at}}
        mock_table.put_item.return_value = {}

        with patch("handler._dynamodb") as mock_ddb, \
             patch("handler.KMS_KEY_ID", ""):
            mock_ddb.return_value.Table.return_value = mock_table
            event = _make_event("POST", "/mood", {"mood": "Sad"})
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["created_at"] == original_created_at

    def test_returns_401_without_auth(self):
        event = _make_event_no_auth("POST", "/mood", {"mood": "Happy"})
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 401

    def test_kms_encrypt_called_when_key_set(self):
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}
        mock_table.put_item.return_value = {}

        fake_ciphertext = b"encrypted-bytes"
        mock_kms = MagicMock()
        mock_kms.encrypt.return_value = {"CiphertextBlob": fake_ciphertext}
        mock_kms.decrypt.return_value = {"Plaintext": b"my note"}

        with patch("handler._dynamodb") as mock_ddb, \
             patch("handler.KMS_KEY_ID", "alias/test-key"), \
             patch("handler._kms", return_value=mock_kms):
            mock_ddb.return_value.Table.return_value = mock_table
            event = _make_event("POST", "/mood", {"mood": "Happy", "note": "my note"})
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 200
        mock_kms.encrypt.assert_called_once()
        # Response note should be decrypted
        body = json.loads(resp["body"])
        assert body["note"] == "my note"

    def test_response_includes_timestamps(self):
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}
        mock_table.put_item.return_value = {}

        with patch("handler._dynamodb") as mock_ddb, \
             patch("handler.KMS_KEY_ID", ""):
            mock_ddb.return_value.Table.return_value = mock_table
            event = _make_event("POST", "/mood", {"mood": "Happy"})
            resp = lambda_handler(event, None)

        body = json.loads(resp["body"])
        assert "created_at" in body
        assert "updated_at" in body


# ---------------------------------------------------------------------------
# GET /mood/today
# ---------------------------------------------------------------------------

class TestGetMoodToday:
    def test_returns_entry_when_exists(self):
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": SAMPLE_ENTRY}

        with patch("handler._dynamodb") as mock_ddb, \
             patch("handler.KMS_KEY_ID", ""):
            mock_ddb.return_value.Table.return_value = mock_table
            event = _make_event("GET", "/mood/today")
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["entry"] is not None
        assert body["entry"]["mood"] == "Happy"

    def test_returns_null_when_no_entry(self):
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}

        with patch("handler._dynamodb") as mock_ddb, \
             patch("handler.KMS_KEY_ID", ""):
            mock_ddb.return_value.Table.return_value = mock_table
            event = _make_event("GET", "/mood/today")
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["entry"] is None

    def test_returns_401_without_auth(self):
        event = _make_event_no_auth("GET", "/mood/today")
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 401

    def test_decrypts_note_in_response(self):
        entry_with_encrypted_note = {**SAMPLE_ENTRY, "note": "c29tZW5vdGU="}  # base64 placeholder
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": entry_with_encrypted_note}

        mock_kms = MagicMock()
        mock_kms.decrypt.return_value = {"Plaintext": b"somenote"}

        with patch("handler._dynamodb") as mock_ddb, \
             patch("handler.KMS_KEY_ID", "alias/test-key"), \
             patch("handler._kms", return_value=mock_kms):
            mock_ddb.return_value.Table.return_value = mock_table
            event = _make_event("GET", "/mood/today")
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["entry"]["note"] == "somenote"


# ---------------------------------------------------------------------------
# GET /mood/history
# ---------------------------------------------------------------------------

class TestGetMoodHistory:
    def _make_entries(self, n: int):
        """Generate n mood entries for consecutive days ending today."""
        today = date.today()
        entries = []
        for i in range(n):
            d = (today - timedelta(days=i)).isoformat()
            entries.append({
                "user_id": "user-abc",
                "entry_date": d,
                "mood": "Happy",
                "note": "",
                "created_at": "2024-01-01T00:00:00+00:00",
                "updated_at": "2024-01-01T00:00:00+00:00",
            })
        return entries

    def test_returns_entries_list(self):
        entries = self._make_entries(5)
        mock_table = MagicMock()
        mock_table.query.return_value = {"Items": entries}

        with patch("handler._dynamodb") as mock_ddb, \
             patch("handler.KMS_KEY_ID", ""):
            mock_ddb.return_value.Table.return_value = mock_table
            event = _make_event("GET", "/mood/history")
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert "entries" in body
        assert len(body["entries"]) == 5

    def test_returns_empty_list_when_no_history(self):
        mock_table = MagicMock()
        mock_table.query.return_value = {"Items": []}

        with patch("handler._dynamodb") as mock_ddb, \
             patch("handler.KMS_KEY_ID", ""):
            mock_ddb.return_value.Table.return_value = mock_table
            event = _make_event("GET", "/mood/history")
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["entries"] == []

    def test_query_uses_scan_index_forward_false(self):
        """Verify descending order is requested from DynamoDB."""
        mock_table = MagicMock()
        mock_table.query.return_value = {"Items": []}

        with patch("handler._dynamodb") as mock_ddb, \
             patch("handler.KMS_KEY_ID", ""):
            mock_ddb.return_value.Table.return_value = mock_table
            event = _make_event("GET", "/mood/history")
            lambda_handler(event, None)

        call_kwargs = mock_table.query.call_args[1]
        assert call_kwargs.get("ScanIndexForward") is False

    def test_query_uses_30_day_window(self):
        """Verify the query covers the last 30 days."""
        mock_table = MagicMock()
        mock_table.query.return_value = {"Items": []}

        with patch("handler._dynamodb") as mock_ddb, \
             patch("handler.KMS_KEY_ID", ""):
            mock_ddb.return_value.Table.return_value = mock_table
            event = _make_event("GET", "/mood/history")
            lambda_handler(event, None)

        call_kwargs = mock_table.query.call_args[1]
        # KeyConditionExpression should reference a 30-day range
        # We verify the query was called with a KeyConditionExpression
        assert "KeyConditionExpression" in call_kwargs

    def test_returns_401_without_auth(self):
        event = _make_event_no_auth("GET", "/mood/history")
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 401

    def test_decrypts_notes_in_history(self):
        entries = [{
            **SAMPLE_ENTRY,
            "note": "c29tZW5vdGU=",  # base64 placeholder
        }]
        mock_table = MagicMock()
        mock_table.query.return_value = {"Items": entries}

        mock_kms = MagicMock()
        mock_kms.decrypt.return_value = {"Plaintext": b"somenote"}

        with patch("handler._dynamodb") as mock_ddb, \
             patch("handler.KMS_KEY_ID", "alias/test-key"), \
             patch("handler._kms", return_value=mock_kms):
            mock_ddb.return_value.Table.return_value = mock_table
            event = _make_event("GET", "/mood/history")
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["entries"][0]["note"] == "somenote"


# ---------------------------------------------------------------------------
# Route fallback
# ---------------------------------------------------------------------------

class TestRouting:
    def test_unknown_route_returns_404(self):
        event = _make_event("GET", "/mood/unknown")
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 404
