"""Dashboard widgets for the shop demo."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import func, select

from tungsten import ChartWidget, Dashboard, ProgressItem, ProgressListWidget, Stat, StatsOverviewWidget, TableWidget
from tungsten.forms import Select
from tungsten.models import Role, RoleAssignment
from tungsten.tables import TextColumn

from .models import Category, Order, OrderItem, Product, User

INR = "₹"


def inr(amount) -> str:
    """Indian grouping: 1248000 -> 12,48,000."""
    n = int(Decimal(amount or 0))
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return f"{'-' if n < 0 else ''}{INR}{s}"


def monthly_counts(db, model, column, months: int = 7, value=None) -> list[float]:
    """Counts (or sums) for the last ``months`` 30-day windows — for sparklines."""
    end = dt.datetime.now()
    points = []
    for i in range(months - 1, -1, -1):
        stop = end - dt.timedelta(days=30 * i)
        start = stop - dt.timedelta(days=30)
        expr = func.count() if value is None else func.coalesce(func.sum(value), 0)
        points.append(float(db.scalar(select(expr).select_from(model).where(column >= start, column < stop)) or 0))
    return points


def change(points: list[float]) -> tuple[str, str]:
    if len(points) < 2 or not points[-2]:
        return "0%", "up"
    pct = (points[-1] - points[-2]) / points[-2] * 100
    return f"{abs(pct):.0f}%", "up" if pct >= 0 else "down"


def period_counts(db, model, column, days: int, value=None) -> tuple[float, float]:
    """(this period, previous period) totals for the last ``days`` days."""
    now = dt.datetime.now()
    expr = func.count() if value is None else func.coalesce(func.sum(value), 0)
    this = db.scalar(select(expr).select_from(model).where(column >= now - dt.timedelta(days=days))) or 0
    prev = db.scalar(select(expr).select_from(model).where(column >= now - dt.timedelta(days=2 * days),
                                                           column < now - dt.timedelta(days=days))) or 0
    return float(this), float(prev)


def compare(this: float, prev: float) -> tuple[str, str]:
    if not prev:
        return ("new" if this else "0%"), "up"
    pct = (this - prev) / prev * 100
    return f"{abs(pct):.0f}%", "up" if pct >= 0 else "down"


class ShopStats(StatsOverviewWidget):
    sort = 1

    @classmethod
    def stats(cls, db, ctx, filters):
        days = int(filters.get("period") or 30)
        label = {7: "vs previous week", 30: "vs previous 30 days", 90: "vs previous 90 days"}.get(days, "vs previous year")
        users = db.scalar(select(func.count()).select_from(User))
        new_users = period_counts(db, User, User.created_at, days)
        orders = period_counts(db, Order, Order.created_at, days)
        revenue = period_counts(db, Order, Order.created_at, days, value=Order.total)
        active = db.scalar(select(func.count()).select_from(Product).where(Product.status == "published",
                                                                          Product.deleted_at.is_(None)))
        u = monthly_counts(db, User, User.created_at)
        o = monthly_counts(db, Order, Order.created_at)
        r = monthly_counts(db, Order, Order.created_at, value=Order.total)
        p = monthly_counts(db, Product, Product.created_at)
        return [
            Stat("Total users", f"{users:,}").icon("users").color("primary").trend(*compare(*new_users))
            .describe(label).chart(u).url(ctx.url("users")),
            Stat("Orders", f"{int(orders[0]):,}").icon("shopping-cart").color("success").trend(*compare(*orders))
            .describe(label).chart(o).url(ctx.url("orders")),
            Stat("Revenue", inr(revenue[0])).icon("indian-rupee").color("info").trend(*compare(*revenue))
            .describe(label).chart(r),
            Stat("Active products", f"{active:,}").icon("package").color("purple").chart(p).url(ctx.url("products")),
        ]


class ShopDashboard(Dashboard):
    """The dashboard with a period picker that every widget can read as ``filters["period"]``."""

    @classmethod
    def filters_form(cls, form):
        return form.schema([
            Select("period").options({"7": "Last 7 days", "30": "Last 30 days", "90": "Last 90 days", "365": "Last 12 months"})
            .default("30").native().placeholder("Period"),
        ])


class RevenueChart(ChartWidget):
    heading = "Revenue overview"
    description = "Monthly revenue and orders."
    type = "bar"
    column_span = 2
    sort = 2
    filters = {"12": "Last 12 months", "6": "Last 6 months", "3": "Last 3 months"}

    @classmethod
    def data(cls, db, filter):
        months = int(filter or 12)
        today = dt.date.today().replace(day=1)
        labels, revenue, orders = [], [], []
        for i in range(months - 1, -1, -1):
            start = (today - dt.timedelta(days=31 * i)).replace(day=1)
            end = (start + dt.timedelta(days=32)).replace(day=1)
            labels.append(start.strftime("%b"))
            revenue.append(float(db.scalar(select(func.coalesce(func.sum(Order.total), 0))
                                           .where(Order.created_at >= start, Order.created_at < end)) or 0))
            orders.append(db.scalar(select(func.count()).select_from(Order)
                                    .where(Order.created_at >= start, Order.created_at < end)) or 0)
        return {
            "labels": labels,
            "datasets": [
                {"label": "Revenue", "data": revenue, "color": "primary", "yAxisID": "y"},
                {"label": "Orders", "data": orders, "color": "gray", "type": "line", "yAxisID": "y1", "fill": False},
            ],
        }

    options = {"scales": {"y1": {"display": True, "position": "right", "grid": {"display": False}, "beginAtZero": True}}}


class RecentOrders(TableWidget):
    heading = "Recent orders"
    model = Order
    column_span = 2
    sort = 3

    @classmethod
    def query(cls, ctx):
        return select(Order)

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("number").label("#").weight("medium"),
                TextColumn("customer.name").label("Customer").avatar("customer.avatar"),
                TextColumn("total").label("Amount").money(INR, 0),
                TextColumn("status").badge(),
                TextColumn("created_at").label("Date").date(),
            ])
            .default_sort("created_at", "desc")
            .limit(5)
            .toolbar(False)
        )


class TopProducts(TableWidget):
    heading = "Top products"
    model = Product
    column_span = 2
    sort = 4

    @classmethod
    def query(cls, ctx):
        return select(Product).where(Product.deleted_at.is_(None))

    @classmethod
    def table(cls, table):
        sold = lambda record, db: db.scalar(  # noqa: E731
            select(func.coalesce(func.sum(OrderItem.quantity), 0)).where(OrderItem.product_id == record.id))
        return (
            table.columns([
                TextColumn("name").label("Product").avatar(lambda record: record.image, circular=False)
                .description(lambda record: record.category.name if record.category else None),
                TextColumn("sales").label("Sales").state(sold),
                TextColumn("price").label("Price").money(INR, 0),
            ])
            .row_index()
            .default_sort("price", "desc")
            .limit(5)
            .toolbar(False)
        )


class UsersByRole(ChartWidget):
    heading = "Users by role"
    type = "doughnut"
    column_span = 1
    sort = 5
    side_legend = True
    max_height = "14rem"

    @classmethod
    def data(cls, db):
        rows = db.execute(select(Role.name, func.count(RoleAssignment.id)).join(RoleAssignment, isouter=True)
                          .group_by(Role.name)).all()
        total = db.scalar(select(func.count()).select_from(User))
        return {
            "labels": [r[0] for r in rows],
            "datasets": [{"label": "Users", "data": [r[1] for r in rows]}],
            "center": {"value": f"{total:,}", "label": "Users"},
        }


class SalesByCategory(ProgressListWidget):
    heading = "Sales by category"
    column_span = 1
    sort = 6

    @classmethod
    def items(cls, db):
        rows = db.execute(
            select(Category.name, Category.icon, func.coalesce(func.sum(OrderItem.quantity * OrderItem.unit_price), 0))
            .join(Product, Product.category_id == Category.id, isouter=True)
            .join(OrderItem, OrderItem.product_id == Product.id, isouter=True)
            .group_by(Category.id).order_by(func.sum(OrderItem.quantity * OrderItem.unit_price).desc())
        ).all()
        total = sum(float(r[2]) for r in rows) or 1
        return [ProgressItem(r[0], f"{float(r[2]) / total * 100:.0f}%", float(r[2]) / total * 100, r[1] or "tag")
                for r in rows]


# ---------------------------------------------------------------------- list page stats
class UserStats(StatsOverviewWidget):
    lazy = False

    @classmethod
    def stats(cls, db):
        total = db.scalar(select(func.count()).select_from(User))
        active = db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True)))
        new = db.scalar(select(func.count()).select_from(User).where(
            User.created_at >= dt.datetime.now() - dt.timedelta(days=30)))
        pts = monthly_counts(db, User, User.created_at)
        return [
            Stat("Total users", f"{total:,}").icon("users").trend(*change(pts)).chart(pts),
            Stat("Active users", f"{active:,}").icon("user-check").color("success").chart([3, 5, 4, 6, 7, 8, 9]),
            Stat("Inactive users", f"{total - active:,}").icon("user-x").color("danger")
            .trend("4%", "down").chart([6, 5, 6, 4, 5, 3, 4]),
            Stat("New users (30 days)", f"{new:,}").icon("user-plus").color("purple").chart(pts[-4:] or [0, 1]),
        ]


class ProductStats(StatsOverviewWidget):
    lazy = False

    @classmethod
    def stats(cls, db):
        base = select(func.count()).select_from(Product).where(Product.deleted_at.is_(None))
        total = db.scalar(base)
        published = db.scalar(base.where(Product.status == "published"))
        drafts = db.scalar(base.where(Product.status == "draft"))
        out = db.scalar(base.where(Product.stock <= 0))
        return [
            Stat("Total products", f"{total:,}").icon("package").chart([4, 6, 5, 8, 9, 11, 12]).trend("12%"),
            Stat("Published", f"{published:,}").icon("shopping-cart").color("success").chart([3, 4, 6, 5, 7, 8, 9]).trend("8%"),
            Stat("Drafts", f"{drafts:,}").icon("file-pen").color("danger").chart([5, 4, 6, 3, 4, 5, 4]).trend("4%", "down"),
            Stat("Out of stock", f"{out:,}").icon("eye").color("purple").chart([1, 2, 1, 3, 2, 4, 5]).trend("25%", "up", "danger"),
        ]


DASHBOARD_WIDGETS = [ShopStats, RevenueChart, RecentOrders, TopProducts, UsersByRole, SalesByCategory]
