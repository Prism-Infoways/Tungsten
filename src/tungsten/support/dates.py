"""Date formatting that works the same on every platform."""

from __future__ import annotations

import re
from typing import Any

_GLIBC_ONLY = re.compile(r"%%|%-([a-zA-Z])|%s")


def format_date(value: Any, fmt: str) -> str:
    """``value.strftime(fmt)``, with the glibc-only ``%-d`` / ``%-m`` / ``%-I`` / ``%-H`` (no leading zero) and
    ``%s`` (Unix time) working on Windows and macOS too."""
    if "%-" not in fmt and "%s" not in fmt:
        return value.strftime(fmt)

    def portable(match: re.Match) -> str:
        token = match.group(0)
        if token == "%%":
            return token
        if token == "%s":
            return str(int(value.timestamp())) if hasattr(value, "timestamp") else ""
        return (value.strftime("%" + match.group(1)).lstrip("0") or "0").replace("%", "%%")

    return value.strftime(_GLIBC_ONLY.sub(portable, fmt))
