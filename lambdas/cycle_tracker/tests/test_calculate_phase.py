"""Unit tests for calculate_phase in cycle_tracker handler."""
import sys
import os
from datetime import date, timedelta

import pytest

# Make the handler importable without boto3 side-effects
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from handler import calculate_phase


# ---------------------------------------------------------------------------
# Phase boundary examples
# ---------------------------------------------------------------------------

class TestCalculatePhaseExamples:
    """Specific day-boundary examples for each phase."""

    def _make_today(self, day_in_cycle: int, cycle_length: int = 28) -> tuple:
        """Return (last_period_date, today) such that today is `day_in_cycle` into the cycle."""
        last_period_date = date(2024, 1, 1)
        today = last_period_date + timedelta(days=day_in_cycle - 1)
        return last_period_date, today

    # Period: days 1-5
    def test_day_1_is_period(self):
        lpd, today = self._make_today(1)
        result = calculate_phase(lpd, 28, today)
        assert result["phase"] == "Period"
        assert result["day_in_cycle"] == 1

    def test_day_5_is_period(self):
        lpd, today = self._make_today(5)
        result = calculate_phase(lpd, 28, today)
        assert result["phase"] == "Period"
        assert result["day_in_cycle"] == 5

    # Follicular: days 6-13
    def test_day_6_is_follicular(self):
        lpd, today = self._make_today(6)
        result = calculate_phase(lpd, 28, today)
        assert result["phase"] == "Follicular"
        assert result["day_in_cycle"] == 6

    def test_day_13_is_follicular(self):
        lpd, today = self._make_today(13)
        result = calculate_phase(lpd, 28, today)
        assert result["phase"] == "Follicular"
        assert result["day_in_cycle"] == 13

    # Ovulation: days 14-16
    def test_day_14_is_ovulation(self):
        lpd, today = self._make_today(14)
        result = calculate_phase(lpd, 28, today)
        assert result["phase"] == "Ovulation"
        assert result["day_in_cycle"] == 14

    def test_day_16_is_ovulation(self):
        lpd, today = self._make_today(16)
        result = calculate_phase(lpd, 28, today)
        assert result["phase"] == "Ovulation"
        assert result["day_in_cycle"] == 16

    # Luteal/PMS: days 17 to end of cycle
    def test_day_17_is_luteal(self):
        lpd, today = self._make_today(17)
        result = calculate_phase(lpd, 28, today)
        assert result["phase"] == "Luteal/PMS"
        assert result["day_in_cycle"] == 17

    def test_last_day_of_cycle_is_luteal(self):
        lpd, today = self._make_today(28)
        result = calculate_phase(lpd, 28, today)
        assert result["phase"] == "Luteal/PMS"
        assert result["day_in_cycle"] == 28

    # Cycle wraps around correctly
    def test_cycle_wraps_to_day_1(self):
        """Day 29 in a 28-day cycle should be day 1 of the next cycle."""
        lpd = date(2024, 1, 1)
        today = lpd + timedelta(days=28)  # 29th day = day 1 of next cycle
        result = calculate_phase(lpd, 28, today)
        assert result["day_in_cycle"] == 1
        assert result["phase"] == "Period"

    # Boundary cycle lengths
    def test_cycle_length_21_last_day_is_luteal(self):
        lpd, today = self._make_today(21, cycle_length=21)
        result = calculate_phase(lpd, 21, today)
        assert result["day_in_cycle"] == 21
        assert result["phase"] == "Luteal/PMS"

    def test_cycle_length_45_last_day_is_luteal(self):
        lpd, today = self._make_today(45, cycle_length=45)
        result = calculate_phase(lpd, 45, today)
        assert result["day_in_cycle"] == 45
        assert result["phase"] == "Luteal/PMS"
