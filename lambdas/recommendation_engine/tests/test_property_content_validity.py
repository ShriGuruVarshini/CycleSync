# Feature: cycle-sync, Property 20: Content item validity invariant

"""
Property 20: Content item validity invariant

For any content item stored in cyclesync-content-items, its description
should be no more than 80 characters, its rating should be between 1.0 and
5.0, its category should be one of {Song, Movie, Poem, Digital Colouring},
and its language should be a non-empty string.

Validates: Requirements 8.5, 10.1
"""

import os
import sys

from hypothesis import given, settings, strategies as st, HealthCheck

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HANDLER_DIR = os.path.join(os.path.dirname(__file__), "..")
if _HANDLER_DIR not in sys.path:
    sys.path.insert(0, _HANDLER_DIR)

from handler import _validate_content_fields  # noqa: E402

# ---------------------------------------------------------------------------
# Constants (mirror handler constants)
# ---------------------------------------------------------------------------
_VALID_CATEGORIES = ["Song", "Movie", "Poem", "Digital Colouring"]
_VALID_MOODS = ["Happy", "Sad", "Angry"]
_MAX_DESCRIPTION_LENGTH = 80

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_valid_content_item_strategy = st.fixed_dictionaries({
    "title": st.text(min_size=1, max_size=100),
    "category": st.sampled_from(_VALID_CATEGORIES),
    "mood_tags": st.lists(
        st.sampled_from(_VALID_MOODS),
        min_size=1,
        max_size=3,
        unique=True,
    ),
    "description": st.text(min_size=0, max_size=_MAX_DESCRIPTION_LENGTH),
    "rating": st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False),
    "language": st.text(min_size=1, max_size=10).filter(lambda s: s.strip() != ""),
})

_invalid_description_strategy = st.fixed_dictionaries({
    "title": st.text(min_size=1, max_size=100),
    "category": st.sampled_from(_VALID_CATEGORIES),
    "mood_tags": st.lists(st.sampled_from(_VALID_MOODS), min_size=1, max_size=3, unique=True),
    "description": st.text(min_size=_MAX_DESCRIPTION_LENGTH + 1, max_size=200),
    "rating": st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False),
    "language": st.text(min_size=1, max_size=10).filter(lambda s: s.strip() != ""),
})

_invalid_rating_strategy = st.fixed_dictionaries({
    "title": st.text(min_size=1, max_size=100),
    "category": st.sampled_from(_VALID_CATEGORIES),
    "mood_tags": st.lists(st.sampled_from(_VALID_MOODS), min_size=1, max_size=3, unique=True),
    "description": st.text(min_size=0, max_size=_MAX_DESCRIPTION_LENGTH),
    "rating": st.one_of(
        st.floats(max_value=0.99, allow_nan=False, allow_infinity=False),
        st.floats(min_value=5.01, max_value=100.0, allow_nan=False, allow_infinity=False),
    ),
    "language": st.text(min_size=1, max_size=10).filter(lambda s: s.strip() != ""),
})

_invalid_category_strategy = st.fixed_dictionaries({
    "title": st.text(min_size=1, max_size=100),
    "category": st.text(min_size=1, max_size=50).filter(
        lambda c: c not in {"Song", "Movie", "Poem", "Digital Colouring"}
    ),
    "mood_tags": st.lists(st.sampled_from(_VALID_MOODS), min_size=1, max_size=3, unique=True),
    "description": st.text(min_size=0, max_size=_MAX_DESCRIPTION_LENGTH),
    "rating": st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False),
    "language": st.text(min_size=1, max_size=10).filter(lambda s: s.strip() != ""),
})

_invalid_language_strategy = st.fixed_dictionaries({
    "title": st.text(min_size=1, max_size=100),
    "category": st.sampled_from(_VALID_CATEGORIES),
    "mood_tags": st.lists(st.sampled_from(_VALID_MOODS), min_size=1, max_size=3, unique=True),
    "description": st.text(min_size=0, max_size=_MAX_DESCRIPTION_LENGTH),
    "rating": st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False),
    "language": st.just(""),
})

_invalid_content_item_strategy = st.one_of(
    _invalid_description_strategy,
    _invalid_rating_strategy,
    _invalid_category_strategy,
    _invalid_language_strategy,
)

# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


@given(item=_valid_content_item_strategy)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_valid_content_item_passes_validation(item):
    """
    Property 20a: For any content item with description <= 80 chars,
    rating in [1.0, 5.0], category in valid set, and non-empty language,
    _validate_content_fields should return (None, None).
    """
    error_field, error_msg = _validate_content_fields(item, require_all=True)
    assert error_field is None, (
        f"Expected no validation error for valid item, "
        f"got error_field={error_field!r}, message={error_msg!r}. Item: {item}"
    )
    assert error_msg is None


@given(item=_invalid_content_item_strategy)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_invalid_content_item_fails_validation(item):
    """
    Property 20b: For any content item with at least one invalid field
    (description > 80 chars, rating outside [1.0, 5.0], invalid category,
    or empty language), _validate_content_fields should return a non-None
    error_field indicating which constraint was violated.
    """
    error_field, error_msg = _validate_content_fields(item, require_all=True)
    assert error_field is not None, (
        f"Expected a validation error for invalid item, but got (None, None). Item: {item}"
    )
