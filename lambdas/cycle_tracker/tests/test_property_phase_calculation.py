# Feature: cycle-sync, Property 10: Phase calculation correctness

"""
Property 10: Phase calculation correctness

For any last period date and cycle length in [21, 45], the computed
day_in_cycle = (today - last_period_date) mod cycle_length should fall in
[1, cycle_length], and the resulting phase should match the defined
day-range mapping (1-5: Period, 6-13: Follicular, 14-16: Ovulation,
17-end: Luteal/PMS).

Validates: Requirements 4.1, 4.2
"""

import os
import sys
from datetime import date, timedelta

from hypothesis import given, settings, strategies as st

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HANDLER_DIR = os.path.join(os.path.dirname(__file__), "..")
if _HANDLER_DIR not in sys.path:
    sys.path.insert(0, _HANDLER_DIR)

from handler import calculate_phase  # noqa: E402

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate a base date (last_period_date) within a reasonable range
_base_date_strategy = st.dates(
    min_value=date(2000, 1, 1),
    max_value=date(2030, 12, 31),
)

# Cycle length must be in [21, 45] per requirements
_cycle_length_strategy = st.integers(min_value=21, max_value=45)


def _today_strategy(last_period_date: date):
    """Generate a today date that is >= last_period_date."""
    return st.dates(
        min_value=last_period_date,
        max_value=last_period_date + timedelta(days=365 * 5),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_PHASES = {"Period", "Follicular", "Ovulation", "Luteal/PMS"}


def _expected_phase(day_in_cycle: int) -> str:
    if day_in_cycle <= 5:
        return "Period"
    elif day_in_cycle <= 13:
        return "Follicular"
    elif day_in_cycle <= 16:
        return "Ovulation"
    else:
        return "Luteal/PMS"


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------

@given(
    last_period_date=_base_date_strategy,
    cycle_length=_cycle_length_strategy,
    days_offset=st.integers(min_value=0, max_value=365 * 5),
)
@settings(max_examples=100)
def test_phase_calculation_correctness(last_period_date, cycle_length, days_offset):
    """
    Property 10: Phase calculation correctness.

    For any last_period_date, cycle_length in [21, 45], and today >= last_period_date:
    1. day_in_cycle is in [1, cycle_length]
    2. phase is one of the four valid phases
    3. phase matches the defined day-range mapping
    """
    today = last_period_date + timedelta(days=days_offset)

    result = calculate_phase(last_period_date, cycle_length, today)

    day_in_cycle = result["day_in_cycle"]
    phase = result["phase"]

    # Assertion 1: day_in_cycle is in [1, cycle_length]
    assert 1 <= day_in_cycle <= cycle_length, (
        f"day_in_cycle={day_in_cycle} is out of range [1, {cycle_length}] "
        f"for last_period_date={last_period_date}, today={today}"
    )

    # Assertion 2: phase is one of the valid phases
    assert phase in _VALID_PHASES, (
        f"phase={phase!r} is not a valid phase; expected one of {_VALID_PHASES}"
    )

    # Assertion 3: phase matches the day-range mapping
    expected = _expected_phase(day_in_cycle)
    assert phase == expected, (
        f"phase={phase!r} does not match expected={expected!r} "
        f"for day_in_cycle={day_in_cycle} "
        f"(last_period_date={last_period_date}, cycle_length={cycle_length}, today={today})"
    )
