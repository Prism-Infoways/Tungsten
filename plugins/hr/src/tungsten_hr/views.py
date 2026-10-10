"""Small HTML blocks the HR screens show: leave balance and this month's attendance."""

from __future__ import annotations

import datetime as dt
from typing import Any

from markupsafe import Markup, escape

from .models import Employee
from .service import ATTENDANCE_STATUSES, leave_balance, month_summary

_BOX = "border:1px solid rgba(127,127,127,.25);border-radius:10px;padding:10px 12px"


def _num(value: float | None) -> str:
    return "∞" if value is None else f"{value:g}"


def balance_html(db: Any, employee: Employee | None, year: int | None = None) -> Markup:
    """One bar per leave type: used of allowed, and what is waiting for approval."""
    if employee is None or employee.id is None:
        return Markup("")
    rows = leave_balance(db, employee, year)
    if not rows:
        return Markup('<p style="margin:0;opacity:.7">No leave types yet. Add them under HR, Leave types.</p>')
    out = ['<div style="display:grid;gap:10px;grid-template-columns:repeat(auto-fill,minmax(180px,1fr))">']
    for row in rows:
        allowed, used = row["allowed"], row["used"]
        width = min(100, round(used / allowed * 100)) if allowed else 0
        color = "#dc2626" if row["left"] is not None and row["left"] <= 0 else "#16a34a"
        waiting = (f'<div style="font-size:12px;color:#d97706">{_num(row["pending"])} waiting</div>'
                   if row["pending"] else "")
        out.append(
            f'<div style="{_BOX}"><div style="font-size:13px;opacity:.75">{escape(row["name"])}</div>'
            f'<div style="font-size:22px;font-weight:600">{_num(row["left"])}'
            f' <span style="font-size:13px;font-weight:400;opacity:.7">left</span></div>'
            f'<div style="height:6px;border-radius:99px;background:rgba(127,127,127,.2);overflow:hidden;margin:6px 0">'
            f'<span style="display:block;height:100%;width:{width}%;background:{color}"></span></div>'
            f'<div style="font-size:12px;opacity:.75">{_num(used)} used of {_num(allowed)}</div>{waiting}</div>')
    out.append("</div>")
    return Markup("".join(out))


def month_html(db: Any, employee: Employee | None, day: dt.date | None = None) -> Markup:
    """Counts of present, absent, leave... for the current month."""
    if employee is None or employee.id is None:
        return Markup("")
    day = day or dt.date.today()
    summary = month_summary(db, employee, day.year, day.month)
    cells = [(label, summary.get(key, 0)) for key, (label, _) in ATTENDANCE_STATUSES.items()]
    cells += [("Late", summary["late"]), ("Hours", summary["hours"])]
    out = [f'<div style="font-size:13px;opacity:.75;margin-bottom:6px">{day:%B %Y}</div>',
           '<div style="display:grid;gap:8px;grid-template-columns:repeat(auto-fill,minmax(110px,1fr))">']
    for label, value in cells:
        out.append(f'<div style="{_BOX}"><div style="font-size:12px;opacity:.75">{escape(label)}</div>'
                   f'<div style="font-size:18px;font-weight:600">{value:g}</div></div>')
    out.append("</div>")
    return Markup("".join(out))
