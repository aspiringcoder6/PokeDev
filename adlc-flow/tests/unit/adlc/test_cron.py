# ruff: noqa: INP001, S101, DTZ001

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from langflow.adlc.cron import CronParseError, describe_cron_next, parse_cron


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


def test_parse_rejects_wrong_field_count() -> None:
    for expression in ("* * * *", "* * * * * *", ""):
        with pytest.raises(CronParseError):
            parse_cron(expression)


def test_parse_rejects_out_of_range_values() -> None:
    for expression in ("60 * * * *", "* 24 * * *", "* * 32 * *", "* * * 13 *", "* * * * 8"):
        with pytest.raises(CronParseError):
            parse_cron(expression)


def test_parse_supports_steps_ranges_lists_and_names() -> None:
    parsed = parse_cron("*/15 0-6 * jan-mar MON,FRI")
    assert parsed.minutes == (0, 15, 30, 45)
    assert parsed.hours == tuple(range(7))
    assert parsed.months == (1, 2, 3)
    assert parsed.days_of_week == (1, 5)


def test_parse_maps_sunday_alias_seven_to_zero() -> None:
    assert parse_cron("0 0 * * 7").days_of_week == (0,)
    assert parse_cron("0 0 * * SUN").days_of_week == (0,)


def test_next_after_steps_one_minute_forward() -> None:
    parsed = parse_cron("* * * * *")
    assert parsed.next_after(_utc(2026, 3, 1, 12, 30, 59)) == _utc(2026, 3, 1, 12, 31)


def test_next_after_selects_next_matching_minute() -> None:
    parsed = parse_cron("*/15 * * * *")
    assert parsed.next_after(_utc(2026, 3, 1, 12, 16)) == _utc(2026, 3, 1, 12, 30)


def test_next_after_crosses_day_month_and_year() -> None:
    daily = parse_cron("0 0 * * *")
    assert daily.next_after(_utc(2026, 12, 31, 23, 59)) == _utc(2027, 1, 1)
    monthly = parse_cron("0 0 1 * *")
    assert monthly.next_after(_utc(2026, 1, 15)) == _utc(2026, 2, 1)


def test_next_after_respects_month_restriction() -> None:
    july_only = parse_cron("0 12 * jul *")
    assert july_only.next_after(_utc(2026, 6, 30, 12, 0)) == _utc(2026, 7, 1, 12)
    assert july_only.next_after(_utc(2026, 7, 31, 12, 0)) == _utc(2027, 7, 1, 12)
    daily = parse_cron("0 12 * * *")
    assert daily.next_after(_utc(2026, 6, 30, 11, 0)) == _utc(2026, 6, 30, 12, 0)
    assert daily.next_after(_utc(2026, 6, 30, 12, 0)) == _utc(2026, 7, 1, 12, 0)


def test_dom_and_dow_restricted_use_or_semantics() -> None:
    parsed = parse_cron("0 0 13 * fri")
    after_friday = parsed.next_after(_utc(2026, 10, 9, 0, 1))
    assert after_friday == _utc(2026, 10, 13)
    after_thirteenth = parsed.next_after(_utc(2026, 10, 13, 0, 1))
    assert after_thirteenth == _utc(2026, 10, 16)
    assert parsed.matches(_utc(2026, 10, 16))
    assert not parsed.matches(_utc(2026, 10, 14))


def test_unrestricted_dom_and_dow_match_every_day() -> None:
    parsed = parse_cron("30 4 * * *")
    assert parsed.next_after(_utc(2026, 5, 9, 4, 31)) == _utc(2026, 5, 10, 4, 30)


def test_matches_requires_exact_minute_and_weekday_range() -> None:
    parsed = parse_cron("0 9 * * 1-5")
    monday = _utc(2026, 10, 5, 9)
    assert parsed.matches(monday)
    assert not parsed.matches(monday + timedelta(minutes=1))
    assert not parsed.matches(_utc(2026, 10, 10, 9))


def test_next_after_requires_timezone_aware_value() -> None:
    parsed = parse_cron("0 0 * * *")
    with pytest.raises(CronParseError):
        parsed.next_after(datetime(2026, 1, 1, 0, 0))


def test_describe_cron_next_returns_ordered_sequence() -> None:
    upcoming = describe_cron_next("*/30 * * * *", after=_utc(2026, 3, 1, 10, 0, 10), limit=3)
    assert upcoming == [
        _utc(2026, 3, 1, 10, 30),
        _utc(2026, 3, 1, 11, 0),
        _utc(2026, 3, 1, 11, 30),
    ]
