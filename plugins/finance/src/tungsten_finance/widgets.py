"""Dashboard and report widgets: money in and out, profit, what customers owe."""

from __future__ import annotations

import datetime as dt
from typing import Any, ClassVar

from sqlalchemy import func, select

from tungsten import ChartWidget, Stat, StatsOverviewWidget

from .ledger import profit_and_loss
from .models import Invoice
from .service import (
    OPEN_STATUSES,
    PERIODS,
    expenses_by_category,
    invoiced,
    money,
    money_in,
    money_out,
    month_start,
    monthly,
    payables,
    period_range,
    receivables,
)


def currency(ctx: Any) -> str:
    plugin = ctx.panel.get_plugin("finance") if ctx is not None else None
    return plugin.currency if plugin is not None else "INR"


def _year_start(ctx: Any) -> int:
    plugin = ctx.panel.get_plugin("finance") if ctx is not None else None
    return plugin.year_start_month if plugin is not None else 4


def report_range(ctx: Any) -> tuple[dt.date | None, dt.date | None]:
    period = (ctx.filters or {}).get("period") if ctx is not None else None
    return period_range(period or "this_month", year_start_month=_year_start(ctx))


class FinanceStats(StatsOverviewWidget):
    """This month at a glance, for the dashboard."""

    lazy = False
    sort = 5

    @classmethod
    def stats(cls, db, ctx):
        cur = currency(ctx)
        today = dt.date.today()
        start = month_start(today)
        got, spent = money_in(db, start, today), money_out(db, start, today)
        owed = sum(receivables(db).values())
        owe = sum(payables(db).values())
        overdue = db.scalar(select(func.count()).select_from(Invoice).where(
            Invoice.kind == "invoice", Invoice.status.in_(OPEN_STATUSES), Invoice.due_date < today)) or 0
        profit = profit_and_loss(db, start, today)["net_profit"]
        return [
            Stat("Money in this month", money(got, cur)).icon("arrow-down-left").color("success")
            .describe(f"Money out {money(spent, cur)}"),
            Stat("Profit this month", money(profit, cur)).icon("trending-up" if profit >= 0 else "trending-down")
            .color("success" if profit >= 0 else "danger").describe("Sales less purchases and expenses"),
            Stat("Customers owe you", money(owed, cur)).icon("hand-coins").color("warning")
            .describe(f"{overdue} overdue invoice{'s' if overdue != 1 else ''}" if overdue else "Nothing overdue"),
            Stat("You owe vendors", money(owe, cur)).icon("receipt").color("info").describe("Unpaid bills"),
        ]


class CashFlowChart(ChartWidget):
    heading = "Money in and out"
    description = "Payments received, and expenses and bills paid, month by month."
    type = "bar"
    column_span = 2
    filters: ClassVar[dict[str, str]] = {"6": "Last 6 months", "12": "Last 12 months"}
    sort = 6

    @classmethod
    def data(cls, db, filter=None):
        rows = monthly(db, int(filter or 6))
        return {
            "labels": [row["label"] for row in rows],
            "datasets": [
                {"label": "Money in", "data": [float(row["in"]) for row in rows], "color": "success"},
                {"label": "Money out", "data": [float(row["out"]) for row in rows], "color": "danger"},
            ],
        }


class ReportStats(StatsOverviewWidget):
    """Profit and loss for the period picked on the Reports page."""

    lazy = False

    @classmethod
    def stats(cls, db, ctx):
        cur = currency(ctx)
        start, end = report_range(ctx)
        got, spent = money_in(db, start, end), money_out(db, start, end)
        pnl = profit_and_loss(db, start, end)
        profit = pnl["net_profit"]
        margin = f"{profit / pnl['income'] * 100:.0f}% of income" if pnl["income"] else "No income yet"
        return [
            Stat("Sales", money(invoiced(db, start, end), cur)).icon("file-text").color("info")
            .describe("Invoices dated in this period"),
            Stat("Money in", money(got, cur)).icon("arrow-down-left").color("success")
            .describe("Payments received"),
            Stat("Money out", money(spent, cur)).icon("arrow-up-right").color("danger")
            .describe("Expenses and bills paid"),
            Stat("Net profit", money(profit, cur)).icon("trending-up" if profit >= 0 else "trending-down")
            .color("success" if profit >= 0 else "danger").describe(margin),
        ]


class ExpenseCategoryChart(ChartWidget):
    heading = "Where the money went"
    type = "doughnut"
    column_span = 2
    side_legend = True

    @classmethod
    def data(cls, db, ctx):
        start, end = report_range(ctx)
        rows = expenses_by_category(db, start, end)
        return {"labels": [name for name, _ in rows],
                "datasets": [{"label": "Expenses", "data": [float(total) for _, total in rows]}]}


__all__ = ["PERIODS", "CashFlowChart", "ExpenseCategoryChart", "FinanceStats", "ReportStats"]
