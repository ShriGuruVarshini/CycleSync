"""
Unit tests for GET /profile and PUT /profile handlers.
Validates Requirements 3.1, 3.2, 3.3
"""
import json
from unittest.mock import MagicMock, patch

import pytest

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from handler import lambda_handler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(method: str, path: str, body: dict = None, user_id: str = "user-123"):
    """Build an event with a mocked Authorization header (JWT bypassed via _require_auth mock)."""
    event = {
        "rawPath": path,
        "httpMethod": method,
        "path": path,
        "body": json.dumps(body) if body else None,
        "headers": {"authorization": "bearer fake-token"},
        "requestContext": {
            "http": {
                "method": method,
                "path": path,
            }
        },
    }
    return event, user_id


def _make_event_no_auth(method: str, path: str, body: dict = None):
    return {
        "rawPath": path,
        "httpMethod": method,
        "path": path,
        "body": json.dumps(body) if body else None,
        "headers": {},
        "requestContext": {
            "http": {
                "method": method,
                "path": path,
            }
        },
    }


SAMPLE_PROFILE = {
    "user_id": "user-123",
    "email": "test@example.com",
    "display_name": "Alice",
    "age": 28,
    "last_period_date": "2024-01-01",
    "cycle_length_days": 28,
    "language_preference": "en",
    "hobby_preferences": ["Songs"],
    "notifications_on": True,
    "created_at": "2024-01-01T00:00:00+00:00",
    "updated_at": "2024-01-01T00:00:00+00:00",
}


# ---------------------------------------------------------------------------
# GET /profile tests
# ---------------------------------------------------------------------------

class TestGetProfile:
    def test_returns_profile_for_authenticated_user(self):
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": SAMPLE_PROFILE}

        event, user_id = _make_event("GET", "/profile")
        with patch("handler._require_auth", return_value=(user_id, None)), \
             patch("handler._ddb") as mock_ddb:
            mock_ddb.Table.return_value = mock_table
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["user_id"] == "user-123"
        assert body["email"] == "test@example.com"

    def test_returns_401_when_no_auth_context(self):
        event = _make_event_no_auth("GET", "/profile")
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 401

    def test_returns_404_when_profile_not_found(self):
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}  # no "Item" key

        event, user_id = _make_event("GET", "/profile")
        with patch("handler._require_auth", return_value=(user_id, None)), \
             patch("handler._ddb") as mock_ddb:
            mock_ddb.Table.return_value = mock_table
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 404
        body = json.loads(resp["body"])
        assert body["error"] == "not_found"


# ---------------------------------------------------------------------------
# PUT /profile tests
# ---------------------------------------------------------------------------

class TestPutProfile:
    def _mock_update(self, updated_attrs: dict):
        mock_table = MagicMock()
        mock_table.update_item.return_value = {"Attributes": updated_attrs}
        return mock_table

    def test_updates_display_name(self):
        updated = {**SAMPLE_PROFILE, "display_name": "Bob"}
        mock_table = self._mock_update(updated)

        event, user_id = _make_event("PUT", "/profile", {"display_name": "Bob"})
        with patch("handler._require_auth", return_value=(user_id, None)), \
             patch("handler._ddb") as mock_ddb:
            mock_ddb.Table.return_value = mock_table
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["display_name"] == "Bob"

    def test_updates_language_preference(self):
        updated = {**SAMPLE_PROFILE, "language_preference": "hi"}
        mock_table = self._mock_update(updated)

        event, user_id = _make_event("PUT", "/profile", {"language_preference": "hi"})
        with patch("handler._require_auth", return_value=(user_id, None)), \
             patch("handler._ddb") as mock_ddb:
            mock_ddb.Table.return_value = mock_table
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["language_preference"] == "hi"

    def test_accepts_cycle_length_at_lower_boundary(self):
        updated = {**SAMPLE_PROFILE, "cycle_length_days": 21}
        mock_table = self._mock_update(updated)

        event, user_id = _make_event("PUT", "/profile", {"cycle_length_days": 21})
        with patch("handler._require_auth", return_value=(user_id, None)), \
             patch("handler._ddb") as mock_ddb:
            mock_ddb.Table.return_value = mock_table
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 200

    def test_accepts_cycle_length_at_upper_boundary(self):
        updated = {**SAMPLE_PROFILE, "cycle_length_days": 45}
        mock_table = self._mock_update(updated)

        event, user_id = _make_event("PUT", "/profile", {"cycle_length_days": 45})
        with patch("handler._require_auth", return_value=(user_id, None)), \
             patch("handler._ddb") as mock_ddb:
            mock_ddb.Table.return_value = mock_table
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 200

    def test_rejects_cycle_length_below_21(self):
        event, user_id = _make_event("PUT", "/profile", {"cycle_length_days": 20})
        with patch("handler._require_auth", return_value=(user_id, None)):
            resp = lambda_handler(event, None)
        assert resp["statusCode"] == 400
        body = json.loads(resp["body"])
        assert body["error"] == "cycle_length_days"
        assert "21" in body["message"] and "45" in body["message"]

    def test_rejects_cycle_length_above_45(self):
        event, user_id = _make_event("PUT", "/profile", {"cycle_length_days": 46})
        with patch("handler._require_auth", return_value=(user_id, None)):
            resp = lambda_handler(event, None)
        assert resp["statusCode"] == 400
        body = json.loads(resp["body"])
        assert body["error"] == "cycle_length_days"

    def test_rejects_non_numeric_cycle_length(self):
        event, user_id = _make_event("PUT", "/profile", {"cycle_length_days": "abc"})
        with patch("handler._require_auth", return_value=(user_id, None)):
            resp = lambda_handler(event, None)
        assert resp["statusCode"] == 400
        body = json.loads(resp["body"])
        assert body["error"] == "cycle_length_days"

    def test_rejects_empty_body(self):
        event, user_id = _make_event("PUT", "/profile", {})
        with patch("handler._require_auth", return_value=(user_id, None)):
            resp = lambda_handler(event, None)
        assert resp["statusCode"] == 400

    def test_ignores_non_updatable_fields(self):
        # email and user_id should not be updatable via PUT /profile
        updated = {**SAMPLE_PROFILE}
        mock_table = self._mock_update(updated)

        event, user_id = _make_event("PUT", "/profile", {"display_name": "Alice", "email": "hacker@evil.com"})
        with patch("handler._require_auth", return_value=(user_id, None)), \
             patch("handler._ddb") as mock_ddb:
            mock_ddb.Table.return_value = mock_table
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 200
        # Verify update_item was called without email in the expression
        call_kwargs = mock_table.update_item.call_args[1]
        attr_names = call_kwargs.get("ExpressionAttributeNames", {})
        assert "email" not in attr_names.values()

    def test_returns_401_when_no_auth_context(self):
        event = _make_event_no_auth("PUT", "/profile", {"display_name": "Alice"})
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 401

    def test_updates_multiple_fields_at_once(self):
        updated = {**SAMPLE_PROFILE, "display_name": "Carol", "age": 30, "cycle_length_days": 30}
        mock_table = self._mock_update(updated)

        event, user_id = _make_event("PUT", "/profile", {
            "display_name": "Carol",
            "age": 30,
            "cycle_length_days": 30,
        })
        with patch("handler._require_auth", return_value=(user_id, None)), \
             patch("handler._ddb") as mock_ddb:
            mock_ddb.Table.return_value = mock_table
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["display_name"] == "Carol"
        assert body["age"] == 30


# ---------------------------------------------------------------------------
# PUT /profile/hobbies tests
# ---------------------------------------------------------------------------

class TestPutHobbies:
    def _mock_update(self, updated_attrs: dict):
        mock_table = MagicMock()
        mock_table.update_item.return_value = {"Attributes": updated_attrs}
        return mock_table

    def test_updates_valid_hobby_subset(self):
        updated = {**SAMPLE_PROFILE, "hobby_preferences": ["Songs", "Movies"]}
        mock_table = self._mock_update(updated)

        event, user_id = _make_event("PUT", "/profile/hobbies", {"hobby_preferences": ["Songs", "Movies"]})
        with patch("handler._require_auth", return_value=(user_id, None)), \
             patch("handler._ddb") as mock_ddb:
            mock_ddb.Table.return_value = mock_table
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["hobby_preferences"] == ["Songs", "Movies"]

    def test_updates_all_four_hobbies(self):
        all_hobbies = ["Songs", "Movies", "Poetry", "Digital Colouring"]
        updated = {**SAMPLE_PROFILE, "hobby_preferences": all_hobbies}
        mock_table = self._mock_update(updated)

        event, user_id = _make_event("PUT", "/profile/hobbies", {"hobby_preferences": all_hobbies})
        with patch("handler._require_auth", return_value=(user_id, None)), \
             patch("handler._ddb") as mock_ddb:
            mock_ddb.Table.return_value = mock_table
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 200

    def test_defaults_to_all_four_when_empty_list(self):
        all_hobbies = ["Songs", "Movies", "Poetry", "Digital Colouring"]
        updated = {**SAMPLE_PROFILE, "hobby_preferences": all_hobbies}
        mock_table = self._mock_update(updated)

        event, user_id = _make_event("PUT", "/profile/hobbies", {"hobby_preferences": []})
        with patch("handler._require_auth", return_value=(user_id, None)), \
             patch("handler._ddb") as mock_ddb:
            mock_ddb.Table.return_value = mock_table
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 200
        # Verify update_item was called with all four hobbies
        call_kwargs = mock_table.update_item.call_args[1]
        stored = call_kwargs["ExpressionAttributeValues"][":hp"]
        assert set(stored) == {"Songs", "Movies", "Poetry", "Digital Colouring"}

    def test_defaults_to_all_four_when_key_missing(self):
        all_hobbies = ["Songs", "Movies", "Poetry", "Digital Colouring"]
        updated = {**SAMPLE_PROFILE, "hobby_preferences": all_hobbies}
        mock_table = self._mock_update(updated)

        event, user_id = _make_event("PUT", "/profile/hobbies", {})
        with patch("handler._require_auth", return_value=(user_id, None)), \
             patch("handler._ddb") as mock_ddb:
            mock_ddb.Table.return_value = mock_table
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 200
        call_kwargs = mock_table.update_item.call_args[1]
        stored = call_kwargs["ExpressionAttributeValues"][":hp"]
        assert set(stored) == {"Songs", "Movies", "Poetry", "Digital Colouring"}

    def test_rejects_invalid_hobby(self):
        event, user_id = _make_event("PUT", "/profile/hobbies", {"hobby_preferences": ["Songs", "Gaming"]})
        with patch("handler._require_auth", return_value=(user_id, None)):
            resp = lambda_handler(event, None)
        assert resp["statusCode"] == 400
        body = json.loads(resp["body"])
        assert body["error"] == "hobby_preferences"
        assert "Gaming" in body["message"]

    def test_rejects_completely_invalid_list(self):
        event, user_id = _make_event("PUT", "/profile/hobbies", {"hobby_preferences": ["Cooking", "Sports"]})
        with patch("handler._require_auth", return_value=(user_id, None)):
            resp = lambda_handler(event, None)
        assert resp["statusCode"] == 400

    def test_returns_401_when_no_auth_context(self):
        event = _make_event_no_auth("PUT", "/profile/hobbies", {"hobby_preferences": ["Songs"]})
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 401

    def test_updates_updated_at_timestamp(self):
        all_hobbies = ["Songs"]
        updated = {**SAMPLE_PROFILE, "hobby_preferences": all_hobbies, "updated_at": "2024-06-01T00:00:00+00:00"}
        mock_table = self._mock_update(updated)

        event, user_id = _make_event("PUT", "/profile/hobbies", {"hobby_preferences": ["Songs"]})
        with patch("handler._require_auth", return_value=(user_id, None)), \
             patch("handler._ddb") as mock_ddb:
            mock_ddb.Table.return_value = mock_table
            resp = lambda_handler(event, None)

        assert resp["statusCode"] == 200
        # Verify updated_at was included in the update expression values
        call_kwargs = mock_table.update_item.call_args[1]
        assert ":ua" in call_kwargs["ExpressionAttributeValues"]
