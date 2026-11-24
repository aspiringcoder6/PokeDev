"""Minimal five-field cron expression engine for ADLC run triggers.

Supports the standard minute hour day-of-month month day-of-week syntax with
``*``, lists, ranges, steps, three-letter month/weekday names, and the cron
dom/dow OR rule when both day fields are restricted. Seconds, year fields,
and time zones inside the expression are intentionally out of scope; callers
always evaluate against timezone-aware UTC datetimes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

CRON_FIELD_COUNT = 5
CRON_SUNDAY_ALIAS = 7
_MAX_SEARCH_DAYS = 4 * 366

_MONTH_NAMES = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_WEEKDAY_NAMES = {
    "sun": 0,
    "mon": 1,
    "tue": 2,
    "wed": 3,
    "thu": 4,
    "fri": 5,
    "sat": 6,
}


class CronParseError(ValueError):
    """Raised when a cron expression cannot be understood."""


@dataclass(frozen=True, slots=True)
class CronExpression:
    """A parsed cron expression able to compute its next fire time."""

    expression: str
    minutes: tuple[int, ...]
    hours: tuple[int, ...]
    days_of_month: tuple[int, ...]
    months: tuple[int, ...]
    days_of_week: tuple[int, ...]
    day_of_month_restricted: bool
    day_of_week_restricted: bool

    def matches(self, value: datetime) -> bool:
        """Return whether the aware datetime lands exactly on a fire minute."""
        return (
            value.minute in self.minutes
            and value.hour in self.hours
            and value.month in self.months
            and self._day_matches(value)
        )

    def next_after(self, value: datetime) -> datetime:
        """Return the first fire time strictly after the aware datetime."""
        if value.tzinfo is None or value.utcoffset() is None:
            message = "cron evaluation requires a timezone-aware datetime"
            raise CronParseError(message)
        candidate = (value + timedelta(minutes=1)).replace(second=0, microsecond=0)
        limit = candidate + timedelta(days=_MAX_SEARCH_DAYS)
        while candidate < limit:
            if candidate.month not in self.months or not self._day_matches(candidate):
                candidate = self._first_minute_of_next_day(candidate)
                continue
            for hour in self.hours:
                for minute in self.minutes:
                    if hour > candidate.hour or (hour == candidate.hour and minute >= candidate.minute):
                        return candidate.replace(hour=hour, minute=minute)
            candidate = self._first_minute_of_next_day(candidate)
        message = f"cron expression {self.expression!r} has no fire time within {_MAX_SEARCH_DAYS} days"
        raise CronParseError(message)

    def _day_matches(self, value: datetime) -> bool:
        dom_match = value.day in self.days_of_month
        dow_match = ((value.weekday() + 1) % 7) in self.days_of_week
        if self.day_of_month_restricted and self.day_of_week_restricted:
            return dom_match or dow_match
        if self.day_of_month_restricted:
            return dom_match
        if self.day_of_week_restricted:
            return dow_match
        return True

    def _first_minute_of_next_day(self, value: datetime) -> datetime:
        return (value + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def parse_cron(expression: str) -> CronExpression:
    """Parse a five-field cron expression or raise :class:`CronParseError`."""
    if not isinstance(expression, str):
        message = "cron expression must be a string"
        raise CronParseError(message)
    fields = expression.split()
    if len(fields) != CRON_FIELD_COUNT:
        message = f"cron expression must have exactly {CRON_FIELD_COUNT} fields, got {len(fields)}"
        raise CronParseError(message)
    try:
        minutes = _parse_field(fields[0], 0, 59, ())
        hours = _parse_field(fields[1], 0, 23, ())
        days_of_month = _parse_field(fields[2], 1, 31, ())
        months = _parse_field(fields[3], 1, 12, _MONTH_NAMES.items())
        days_of_week = _parse_field(fields[4], 0, 7, _WEEKDAY_NAMES.items())
    except CronParseError:
        raise
    except ValueError as exc:
        message = f"invalid cron expression {expression!r}"
        raise CronParseError(message) from exc
    if CRON_SUNDAY_ALIAS in days_of_week:
        days_of_week = frozenset(days_of_week - {CRON_SUNDAY_ALIAS} | {0})
    return CronExpression(
        expression=expression,
        minutes=tuple(sorted(minutes)),
        hours=tuple(sorted(hours)),
        days_of_month=tuple(sorted(days_of_month)),
        months=tuple(sorted(months)),
        days_of_week=tuple(sorted(days_of_week)),
        day_of_month_restricted=fields[2] != "*",
        day_of_week_restricted=fields[4] != "*",
    )


def describe_cron_next(expression: str, *, after: datetime, limit: int = 1) -> list[datetime]:
    """Return up to ``limit`` upcoming fire times for a cron expression."""
    parsed = parse_cron(expression)
    upcoming: list[datetime] = []
    cursor = after
    while len(upcoming) < limit:
        cursor = parsed.next_after(cursor)
        upcoming.append(cursor)
    return upcoming


def _parse_field(
    field: str,
    low: int,
    high: int,
    names: tuple[tuple[str, int], ...] | frozenset[tuple[str, int]],
) -> frozenset[int]:
    name_map = dict(names)
    values: set[int] = set()
    for term in field.split(","):
        values.update(_parse_term(term, low, high, name_map))
    if not values:
        message = f"cron field {field!r} selects no values"
        raise CronParseError(message)
    return frozenset(values)


def _parse_term(
    term: str,
    low: int,
    high: int,
    name_map: dict[str, int],
) -> set[int]:
    step = 1
    body = term
    if "/" in term:
        body, _, step_text = term.partition("/")
        if not step_text.isdigit() or int(step_text) < 1:
            message = f"invalid cron step in {term!r}"
            raise CronParseError(message)
        step = int(step_text)
    if body in ("*", ""):
        start, end = low, high
    elif "-" in body:
        start_text, _, end_text = body.partition("-")
        start = _resolve_value(start_text, low, high, name_map)
        end = _resolve_value(end_text, low, high, name_map)
        if start > end:
            message = f"cron range {body!r} is inverted"
            raise CronParseError(message)
    else:
        start = _resolve_value(body, low, high, name_map)
        end = high if "/" in term else start
    return {value for value in range(start, end + 1) if low <= value <= high and (value - start) % step == 0}


def _resolve_value(text: str, low: int, high: int, name_map: dict[str, int]) -> int:
    normalized = text.strip().lower()
    if normalized in name_map:
        return name_map[normalized]
    if not text.isdigit():
        message = f"invalid cron value {text!r}"
        raise CronParseError(message)
    value = int(text)
    if not low <= value <= high:
        message = f"cron value {value} is outside [{low}, {high}]"
        raise CronParseError(message)
    return value
