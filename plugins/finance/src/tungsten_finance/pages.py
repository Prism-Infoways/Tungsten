"""The Reports page: profit and loss, where the money went, who owes you, tax and bank balances."""

from __future__ import annotations

from typing import Any, ClassVar

from markupsafe import Markup
from sqlalchemy import select

from tungsten import Page
from tungsten.forms import Select

from .models import MoneyAccount
from .service import AGING_BUCKETS, PERIODS, account_balance, money, receivables, tax_summary, top_debtors
from .widgets import CashFlowChart, ExpenseCategoryChart, ReportStats, currency, report_range


class FinanceReports(Page):
    slug = "finance-reports"
    title = "Finance reports"
    navigation_label = "Reports"
    icon = "chart-pie"
    navigation_group = "Finance"
    navigation_sort = 10
    subheading = "Profit, spending, money owed to you and tax, for the period you pick."
    widgets: ClassVar[list] = [ReportStats, ExpenseCategoryChart, CashFlowChart]
    permission = "finance.reports"

    @classmethod
    def filters_form(cls, form):
        return form.schema([Select("period").options(PERIODS).default("this_month").native()])

    @classmethod
    def content(cls, ctx: Any) -> Any:
        db, cur = ctx.db, currency(ctx)
        start, end = report_range(ctx)
        aging = receivables(db)
        tax = tax_summary(db, start, end)
        accounts = db.scalars(select(MoneyAccount).where(MoneyAccount.is_active.is_(True))
                              .order_by(MoneyAccount.name)).all()
        return Markup(ctx.panel.renderer.render(
            "tungsten_finance/reports.html", ctx=ctx,
            aging=[(label, money(aging[key], cur), key != "current" and aging[key] > 0) for key, label in AGING_BUCKETS],
            aging_total=money(sum(aging.values()), cur),
            debtors=[(name, money(amount, cur)) for name, amount in top_debtors(db)],
            tax={key: money(value, cur) for key, value in tax.items()},
            accounts=[(a.name, money(account_balance(db, a), cur)) for a in accounts],
        ))
