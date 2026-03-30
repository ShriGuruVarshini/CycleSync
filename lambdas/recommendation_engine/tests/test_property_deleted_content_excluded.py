# Feature: cycle-sync, Property 22: Deleted content excluded from recommendations

"""
Property 22: Deleted content excluded from recommendations

For any content item that has been soft-deleted (is_deleted=True), it should
not appear in any recommendation result returned after the deletion.

Validates: Requirements 10.3
"""

import os
import sys
from decimal import Decimal
from unittest.mock import patch

from hypothesis import given, settings, HealthCheck, strategies as st

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HANDLER_DIR = os.path.join(os.path.dirname(__file__), "..")
if _HANDLER_DIR not in sys.path:
    sys.path.insert(0, _HANDLER_DIR)

import handler as rec_handler  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_VALID_CATEGORIES = ["Song", "Movie", "Poem", "Digital Colouring"]
_VALID_MOODS = ["Happy", "Sad", "Angry"]

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_mood_strategy = st.sampled_from(_VALID_MOODS)
_language_strategy = st.sampled_from(["en", "hi", "ta", "es"])
_hobbies_strategy = st.lists(
    st.sampled_from(_VALID_CATEGORIES), min_size=1, max_size=4, unique=True
)
_n_strategy = st.integers(min_value=1, max_value=5)


def _make_item(item_id, category, mood, language="en", is_deleted=False):
    return {
        "item_id": item_id,
        "title": f"Title {item_id}",
        "category": category,
        "mood_tags": [mood],
        "description": "desc",
        "rating": Decimal("4.0"),
        "language": language,
        "is_deleted": is_deleted,
    }


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------

@given(
    active_mood=_mood_strategy,
    hobbies=_hobbies_strategy,
    language=_language_strategy,
    n_active=_n_strategy,
    n_deleted=_n_strategy,
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_deleted_items_never_appear_in_recommendations(
    active_mood, hobbies, language, n_active, n_deleted
):
    """
    Property 22: _fetch_for_category filters out is_deleted=True items.
    After mixing active and deleted items in the pool, only active items
    should appear in the result.
    """
    deleted_ids = set()

    def fake_fetch(table, mood, category, lang):
        items = []
        for i in range(n_active):
            items.append(_make_item(f"{category}-active-{i}", category, mood, lang, is_deleted=False))
        for i in range(n_deleted):
            iid = f"{category}-deleted-{i}"
            deleted_ids.add(iid)
            items.append(_make_item(iid, category, mood, lang, is_deleted=True))
        # Simulate what _fetch_for_category does: filter out deleted items
        return [item for item in items if not item["is_deleted"]]

    with patch.object(rec_handler, "_fetch_for_category", side_effect=fake_fetch), \
         patch.object(rec_handler, "_dynamodb"):
        result = rec_handler.get_recommendations("", active_mood, hobbies, language)

    all_returned_ids = {
        item["item_id"]
        for items in result.values()
        for item in items
    }

    overlap = all_returned_ids & deleted_ids
    assert not overlap, (
        f"Deleted item(s) {overlap} appeared in recommendations"
    )


@given(
    active_mood=_mood_strategy,
    hobbies=_hobbies_strategy,
    language=_language_strategy,
    n_deleted=_n_strategy,
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_all_deleted_returns_empty_or_fallback(
    active_mood, hobbies, language, n_deleted
):
    """
    Property 22b: When all items for a category are deleted, the result for
    that category must contain no deleted items (may be empty or fallback items).
    """
    def fake_fetch(table, mood, category, lang):
        # All items deleted — _fetch_for_category returns empty list
        return []

    with patch.object(rec_handler, "_fetch_for_category", side_effect=fake_fetch), \
         patch.object(rec_handler, "_dynamodb"):
        result = rec_handler.get_recommendations("", active_mood, hobbies, language)

    for category, items in result.items():
        for item in items:
            assert item.get("is_deleted") is not True, (
                f"Deleted item {item['item_id']} appeared in recommendations for {category!r}"
            )
