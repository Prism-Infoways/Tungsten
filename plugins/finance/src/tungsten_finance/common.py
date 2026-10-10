"""Small helpers the admin screens share."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from .ledger import MONEY_KINDS
from .models import Contact, LedgerAccount
from .service import CURRENCY_SYMBOLS, money


def qty(value: Any) -> str:
    """A quantity or rate without trailing zeros: 12.000 is "12", 2.500 is "2.5"."""
    from decimal import Decimal

    text = f"{Decimal(str(value or 0)).normalize():f}"
    return text


def plugin_of(ctx: Any) -> Any:
    return ctx.panel.get_plugin("finance") if ctx is not None else None


def currency(ctx: Any) -> str:
    plugin = plugin_of(ctx)
    return plugin.currency if plugin is not None else "INR"


def symbol(ctx: Any) -> str:
    cur = currency(ctx)
    return CURRENCY_SYMBOLS.get(cur, f"{cur} ").strip()


def fmt(ctx: Any):
    """A ``format_state_using`` function that shows money in the plugin's currency."""
    return lambda state, ctx=ctx: money(state, currency(ctx))


def show_money(state: Any, ctx: Any) -> str:
    return money(state, currency(ctx))


def money_account_options(ctx: Any) -> dict[str, str]:
    """Bank and cash accounts, for "Paid into" / "Paid from"."""
    rows = ctx.db.scalars(select(LedgerAccount).where(LedgerAccount.kind.in_(MONEY_KINDS),
                                                      LedgerAccount.is_active.is_(True))
                          .order_by(LedgerAccount.kind, LedgerAccount.name)).all()
    return {str(a.id): a.name for a in rows}


def default_money_account(ctx: Any) -> str | None:
    plugin = plugin_of(ctx)
    found = plugin.default_account_id(ctx.db) if plugin is not None else None
    return str(found) if found else None


def expense_account_options(ctx: Any) -> dict[str, str]:
    rows = ctx.db.scalars(select(LedgerAccount).where(
        LedgerAccount.kind.in_(("expense", "direct_expense", "purchase")), LedgerAccount.is_active.is_(True))
        .order_by(LedgerAccount.name)).all()
    return {str(a.id): a.name for a in rows}


def all_account_options(ctx: Any) -> dict[str, str]:
    rows = ctx.db.scalars(select(LedgerAccount).where(LedgerAccount.is_active.is_(True))
                          .order_by(LedgerAccount.code, LedgerAccount.name)).all()
    return {str(a.id): f"{a.code} · {a.name}" if a.code else a.name for a in rows}


def customers(query: Any) -> Any:
    return query.where(Contact.kind.in_(("customer", "both")))


def vendors(query: Any) -> Any:
    return query.where(Contact.kind.in_(("vendor", "both")))


def contact_options(ctx: Any) -> dict[str, str]:
    rows = ctx.db.scalars(select(Contact).order_by(Contact.name)).all()
    return {str(c.id): c.name for c in rows}


def cached(ctx: Any, key: str, fn: Any) -> Any:
    """Work something out once per request (balances shown on every table row)."""
    store = ctx.__dict__.setdefault("_finance_cache", {})
    if key not in store:
        store[key] = fn()
    return store[key]


def dr_cr(value: Any, ctx: Any) -> str:
    """``₹1,200.00 Dr`` / ``₹300.00 Cr``, like Tally."""
    from decimal import Decimal

    amount = Decimal(value or 0)
    if not amount:
        return money(0, currency(ctx))
    return f"{money(abs(amount), currency(ctx))} {'Dr' if amount > 0 else 'Cr'}"
