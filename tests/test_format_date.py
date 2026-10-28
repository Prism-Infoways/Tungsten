"""Date formats with glibc-only codes work everywhere (issue #101)."""

import datetime as dt

from tungsten.support.dates import format_date
from tungsten.tables.columns import TextColumn


def test_no_leading_zero_codes():
    when = dt.datetime(2026, 3, 5, 7, 4)
    assert format_date(when, "%b %-d, %Y %-I:%M") == "Mar 5, 2026 7:04"
    assert format_date(when, "%-m/%-d") == "3/5"
    assert format_date(dt.datetime(2026, 1, 1, 0, 0), "%-H") == "0"
    assert format_date(when, "100%% %-d") == "100% 5"
    assert format_date(when, "%d %b") == "05 Mar"


def test_unix_time_code():
    when = dt.datetime(2026, 3, 5, tzinfo=dt.timezone.utc)
    assert format_date(when, "%s") == str(int(when.timestamp()))


def test_text_column_date_uses_it():
    col = TextColumn("at").date("%-d %b")
    assert col._format(dt.date(2026, 3, 5)) == "5 Mar"
