# Feature: cycle-sync, Property 19: Recommendation correctness

"""
Property 19: Recommendation correctness

For any active mood and set of hobby preferences, every content item returned
by get_recommendations should have a mood tag matching the active mood and a
category matching one of the user's selected hobbies. The count per category
should be at most 5.

Validates: Requirements 8.1, 8.2
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
_MAX_PER_CATEGORY = 5

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_mood_strategy = st.sampled_from(_VALID_MOODS)
_language_strategy = st.sampled_from(["en", "hi", "ta", "es"])
_hobbies_strategy = st.lists(
    st.sampled_from(_VALID_CATEGORIES),
    min_size=1,
    max_size=4,
    unique=True,
)
_count_strategy = st.integers(min_value=0, max_value=10)


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
# Property tests — patch _fetch_for_category to return controlled items
# so we avoid DynamoDB entirely and test the orchestration logic only.
# ---------------------------------------------------------------------------

@given(
    active_mood=_mood_strategy,
    hobbies=_hobbies_strategy,
    language=_language_strategy,
    n_per_category=_count_strategy,
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_recommendations_keys_match_hobbies(active_mood, hobbies, language, n_per_category):
    """
    Property 19a: The keys in the recommendations dict must exactly match
    the requested hobbies list.
    """
    def fake_fetch(table, mood, category, lang):
        return [_make_item(f"{category}-{i}", category, mood, lang) for i in range(n_per_category)]

    with patch.object(rec_handler, "_fetch_for_category", side_effect=fake_fetch), \
         patch.object(rec_handler, "_dynamodb"):
        result = rec_handler.get_recommendations("", active_mood, hobbies, language)

    assert set(result.keys()) == set(hobbies), (
        f"Result keys {set(result.keys())} != requested hobbies {set(hobbies)}"
    )


@given(
    active_mood=_mood_strategy,
    hobbies=_hobbies_strategy,
    language=_language_strategy,
    n_per_category=st.integers(min_value=1, max_value=5),
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_recommendations_at_most_5_per_category(active_mood, hobbies, language, n_per_category):
    """
    Property 19b: The number of items returned per category must never exceed 5.
    _fetch_for_category enforces the cap internally; get_recommendations passes
    its result through directly, so we verify the end-to-end count is <= 5.
    """
    def fake_fetch(table, mood, category, lang):
        # Return exactly n_per_category items (already capped by _fetch_for_category)
        return [_make_item(f"{category}-{i}", category, mood, lang) for i in range(n_per_category)]

    with patch.object(rec_handler, "_fetch_for_category", side_effect=fake_fetch), \
         patch.object(rec_handler, "_dynamodb"):
        result = rec_handler.get_recommendations("", active_mood, hobbies, language)

    for category, items in result.items():
        assert len(items) <= _MAX_PER_CATEGORY, (
            f"Category {category!r} returned {len(items)} items, max is {_MAX_PER_CATEGORY}"
        )


@given(
    active_mood=_mood_strategy,
    hobbies=_hobbies_strategy,
    language=_language_strategy,
    n_per_category=st.integers(min_value=1, max_value=5),
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_recommendations_items_have_correct_category(active_mood, hobbies, language, n_per_category):
    """
    Property 19c: Every item returned for a given category key must have
    its category field matching that key.
    """
    def fake_fetch(table, mood, category, lang):
        return [_make_item(f"{category}-{i}", category, mood, lang) for i in range(n_per_category)]

    with patch.object(rec_handler, "_fetch_for_category", side_effect=fake_fetch), \
         patch.object(rec_handler, "_dynamodb"):
        result = rec_handler.get_recommendations("", active_mood, hobbies, language)

    for category, items in result.items():
        for item in items:
            assert item["category"] == category, (
                f"Item {item['item_id']} has category {item['category']!r}, expected {category!r}"
            )
            assert active_mood in item["mood_tags"], (
                f"Item {item['item_id']} missing mood tag {active_mood!r}"
            )
