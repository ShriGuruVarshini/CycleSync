# Feature: cycle-sync, Property 15: Phase-to-mood prediction mapping

"""
Property 15: Phase-to-mood prediction mapping

For any cycle phase value in {Period, Follicular, Ovulation, Luteal/PMS},
the prediction_engine Lambda should return the defined predicted mood
(Period: Sad, Follicular: Happy, Ovulation: Happy, Luteal/PMS: Angry).

Validates: Requirements 6.1
"""

import importlib.util
import os
import sys

from hypothesis import given, settings, strategies as st

# ---------------------------------------------------------------------------
# Path setup — load handler by absolute path to avoid sys.modules collisions
# ---------------------------------------------------------------------------
_HANDLER_PATH = os.path.join(os.path.dirname(__file__), "..", "handler.py")
_spec = importlib.util.spec_from_file_location("prediction_engine_handler", _HANDLER_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
predict_mood = _mod.predict_mood

# ---------------------------------------------------------------------------
# Expected mapping (mirrors Requirements 6.1)
# ---------------------------------------------------------------------------
_EXPECTED = {
    "Period": "Sad",
    "Follicular": "Happy",
    "Ovulation": "Happy",
    "Luteal/PMS": "Angry",
}

# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------
_phase_strategy = st.sampled_from(["Period", "Follicular", "Ovulation", "Luteal/PMS"])

# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------


@given(phase=_phase_strategy)
@settings(max_examples=100)
def test_phase_to_mood_mapping(phase):
    """
    Property 15: Phase-to-mood prediction mapping.

    For every valid cycle phase the predict_mood pure function must return
    exactly the mood defined in Requirements 6.1.
    """
    result = predict_mood(phase)
    expected = _EXPECTED[phase]
    assert result == expected, (
        f"predict_mood({phase!r}) returned {result!r}, expected {expected!r}"
    )
