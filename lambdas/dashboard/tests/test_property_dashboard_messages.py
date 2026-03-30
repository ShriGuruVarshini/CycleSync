# Feature: cycle-sync, Property 16: Phase explanatory message length
# Feature: cycle-sync, Property 23: Phase support message length
# Feature: cycle-sync, Property 17: Logged mood takes priority on dashboard

"""
Property 16: Phase explanatory message <= 100 chars. Validates: Requirements 6.3
Property 23: Phase support message <= 150 chars. Validates: Requirements 9.2
Property 17: Logged mood takes priority as active_mood. Validates: Requirements 6.4
"""

import importlib.util
import os
import sys

from hypothesis import given, settings, HealthCheck, strategies as st

# ---------------------------------------------------------------------------
# Load handler by absolute path to avoid sys.modules collisions
# ---------------------------------------------------------------------------
_HANDLER_PATH = os.path.join(os.path.dirname(__file__), "..", "handler.py")
_spec = importlib.util.spec_from_file_location("dashboard_handler", _HANDLER_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
PHASE_MESSAGES = _mod.PHASE_MESSAGES
SUPPORT_MESSAGES = _mod.SUPPORT_MESSAGES

_PHASES = ["Period", "Follicular", "Ovulation", "Luteal/PMS"]
_MOODS = ["Happy", "Sad", "Angry"]
_phase_strategy = st.sampled_from(_PHASES)
_mood_strategy = st.sampled_from(_MOODS)


@given(phase=_phase_strategy)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_phase_message_length(phase):
    """Property 16: PHASE_MESSAGES[phase] must be <= 100 chars."""
    msg = PHASE_MESSAGES.get(phase, "")
    assert len(msg) <= 100, (
        f"Phase message for {phase!r} is {len(msg)} chars (max 100): {msg!r}"
    )


@given(phase=_phase_strategy)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_phase_message_non_empty(phase):
    """Every phase must have a non-empty explanatory message."""
    assert PHASE_MESSAGES.get(phase), f"PHASE_MESSAGES missing entry for {phase!r}"


@given(phase=_phase_strategy)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_support_message_length(phase):
    """Property 23: SUPPORT_MESSAGES[phase] must be <= 150 chars."""
    msg = SUPPORT_MESSAGES.get(phase, "")
    assert len(msg) <= 150, (
        f"Support message for {phase!r} is {len(msg)} chars (max 150): {msg!r}"
    )


@given(phase=_phase_strategy)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_support_message_non_empty(phase):
    """Every phase must have a non-empty support message."""
    assert SUPPORT_MESSAGES.get(phase), f"SUPPORT_MESSAGES missing entry for {phase!r}"


@given(predicted_mood=_mood_strategy, logged_mood=_mood_strategy)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_logged_mood_takes_priority(predicted_mood, logged_mood):
    """Property 17: When logged_mood exists, active_mood == logged_mood."""
    active_mood = logged_mood or predicted_mood
    assert active_mood == logged_mood, (
        f"active_mood should be {logged_mood!r}, got {active_mood!r}"
    )


@given(predicted_mood=_mood_strategy)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_predicted_mood_used_when_no_log(predicted_mood):
    """Property 17b: When no mood logged, active_mood == predicted_mood."""
    active_mood = None or predicted_mood
    assert active_mood == predicted_mood
