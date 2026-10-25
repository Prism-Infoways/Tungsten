"""Dashboard widgets for the shop demo."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import func, select

from tungsten import (
    ActivityWidget,
    BannerWidget,
    ChartWidget,
    ChecklistWidget,
    ColumnsWidget,
    Dashboard,
    FunnelWidget,
    GaugeWidget,
    HeroStatWidget,
    Item,
    LeaderboardWidget,
    ProgressItem,
    ProgressListWidget,
    QuickActionsWidget,
    ScheduleWidget,
    Stat,
    StatsOverviewWidget,
    TableWidget,
    TeamWidget,
)
from tungsten.forms import Select
from tungsten.i18n import translate as __
from tungsten.models import Role, RoleAssignment
from tungsten.tables import TextColumn

from .models import Category, Customer, Order, OrderItem, OrderStatus, Post, Product, User

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
    sort = 4

    @classmethod
    def stats(cls, db, ctx, filters):
        days = int(filters.get("period") or 30)
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
        new_products = period_counts(db, Product, Product.created_at, days)
        return [
            Stat("Total users", f"{users:,}").icon("users").color("primary").trend(*compare(*new_users))
            .describe(__("+:count new users", count=int(new_users[0]))).chart(u).url(ctx.url("users")).highlight(),
            Stat("Orders", f"{int(orders[0]):,}").icon("shopping-cart").color("success").trend(*compare(*orders))
            .describe(__("In the last :days days", days=days)).chart(o).url(ctx.url("orders")),
            Stat("Revenue", inr(revenue[0])).icon("indian-rupee").color("info").trend(*compare(*revenue))
            .describe(__("In the last :days days", days=days)).chart(r),
            Stat("Active products", f"{active:,}").icon("package").color("purple").trend(*compare(*new_products))
            .describe(__("+:count new products", count=int(new_products[0])))
            .chart(p).url(ctx.url("products")),
        ]


class ShopDashboard(Dashboard):
    """The dashboard with a period picker that every widget can read as ``filters["period"]``."""

    subheading = "Here's what's happening with your store today."

    @classmethod
    def filters_form(cls, form):
        return form.schema([
            Select("period").options({"7": "Last 7 days", "30": "Last 30 days", "90": "Last 90 days", "365": "Last 12 months"})
            .default("30").native().placeholder("Period"),
        ])


class RevenueChart(ChartWidget):
    heading = "Revenue overview"
    description = "Monthly revenue and orders."
    icon = "chart-column"
    type = "bar"
    column_span = 2
    sort = 14
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
                {"label": "Revenue (₹)", "data": revenue, "color": "primary", "yAxisID": "y", "prefix": INR},
                {"label": "Orders", "data": orders, "color": "gray", "type": "line", "yAxisID": "y1", "fill": False},
            ],
        }

    options = {"scales": {
        "y": {"ticks": {"prefix": INR, "compact": True}},
        "y1": {"display": True, "position": "right", "grid": {"display": False}, "beginAtZero": True},
    }}


class RecentOrders(TableWidget):
    heading = "Recent orders"
    description = "Latest orders from your store"
    icon = "shopping-cart"
    model = Order
    column_span = 2
    sort = 8

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
    description = "Best performing products by sales"
    icon = "crown"
    model = Product
    column_span = 2
    sort = 15

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
    description = "Users in each role"
    icon = "users"
    type = "doughnut"
    column_span = 1
    sort = 16
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
    description = "Share of total revenue"
    icon = "chart-pie"
    column_span = 1
    sort = 17

    @classmethod
    def items(cls, db):
        rows = db.execute(
            select(Category.name, Category.icon, func.coalesce(func.sum(OrderItem.quantity * OrderItem.unit_price), 0))
            .join(Product, Product.category_id == Category.id, isouter=True)
            .join(OrderItem, OrderItem.product_id == Product.id, isouter=True)
            .group_by(Category.id).order_by(func.sum(OrderItem.quantity * OrderItem.unit_price).desc())
        ).all()
        total = sum(float(r[2]) for r in rows) or 1
        palette = ["primary", "pink", "info", "purple", "success", "teal", "warning"]
        return [ProgressItem(r[0], f"{float(r[2]) / total * 100:.0f}%", float(r[2]) / total * 100, r[1] or "tag",
                             palette[i % len(palette)]) for i, r in enumerate(rows)]


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


class OrderStats(StatsOverviewWidget):
    lazy = False
    columns = 5

    @classmethod
    def stats(cls, db):
        def count(status=None):
            q = select(func.count()).select_from(Order)
            return db.scalar(q if status is None else q.where(Order.status == status)) or 0

        o = monthly_counts(db, Order, Order.created_at)
        return [
            Stat("Total orders", f"{count():,}").icon("shopping-bag").trend(*change(o)).chart(o)
            .describe("All time"),
            Stat("Pending", f"{count(OrderStatus.PENDING):,}").icon("hourglass").color("danger")
            .describe("Awaiting confirmation").chart([3, 5, 4, 6, 5, 7, 8]),
            Stat("Processing", f"{count(OrderStatus.PROCESSING):,}").icon("settings").color("warning")
            .describe("Being prepared").chart([4, 6, 5, 7, 4, 6, 5]),
            Stat("Shipped", f"{count(OrderStatus.SHIPPED):,}").icon("truck").color("info")
            .describe("On the way").chart([2, 4, 3, 6, 4, 7, 6]),
            Stat("Paid", f"{count(OrderStatus.PAID):,}").icon("credit-card").color("success")
            .describe("Completed").chart([3, 4, 6, 5, 8, 6, 9]),
        ]



# ---------------------------------------------------------------------- modern dashboard cards
class RevenueHero(HeroStatWidget):
    sort = 1
    description = "All time"

    @classmethod
    def stat(cls, db, ctx, filters):
        days = int(filters.get("period") or 30)
        total = db.scalar(select(func.coalesce(func.sum(Order.total), 0)))
        this, prev = period_counts(db, Order, Order.created_at, days, value=Order.total)
        return (Stat("Total revenue", inr(total)).icon("wallet").trend(*compare(this, prev))
                .describe(__("Revenue in the last :days days: :amount", days=days, amount=inr(this)))
                .chart(monthly_counts(db, Order, Order.created_at, months=9, value=Order.total)))

    @classmethod
    def actions(cls, ctx):
        return [
            Item("New order", url=ctx.url("orders", "create"), icon="plus", color="primary"),
            Item("Add product", url=ctx.url("products", "create"), icon="package-plus", color="dark"),
            Item("Reports", url=ctx.url("reports"), icon="chart-column", color="gray"),
        ]


class MonthlyTarget(GaugeWidget):
    heading = "Monthly target"
    description = "Revenue this month"
    sort = 2
    label = "Target"
    target = 500000

    @classmethod
    def value(cls, db):
        start = dt.date.today().replace(day=1)
        month = float(db.scalar(select(func.coalesce(func.sum(Order.total), 0)).where(Order.created_at >= start)) or 0)
        return {"value": month, "max": cls.target, "display": inr(month), "caption": __("of :amount", amount=inr(cls.target))}


class ShortcutsWidget(QuickActionsWidget):
    heading = "Shortcuts"
    sort = 3
    columns = 2

    @classmethod
    def items(cls, ctx):
        return [
            Item("New order", url=ctx.url("orders", "create"), icon="shopping-cart", color="primary"),
            Item("Customer", url=ctx.url("customers", "create"), icon="user-plus", color="info"),
            Item("Product", url=ctx.url("products", "create"), icon="package-plus", color="purple"),
            Item("Blog post", url=ctx.url("posts", "create"), icon="pen-line", color="pink"),
        ]


class SalesOverview(ColumnsWidget):
    heading = "Sales overview"
    description = "Orders per month"
    icon = "chart-no-axes-column"
    column_span = 2
    sort = 5
    filters = {"6": "6 months", "9": "9 months", "12": "12 months"}

    @classmethod
    def data(cls, db, filter):
        months = int(filter or 6)
        today = dt.date.today().replace(day=1)
        labels, values = [], []
        for i in range(months - 1, -1, -1):
            start = (today - dt.timedelta(days=31 * i)).replace(day=1)
            end = (start + dt.timedelta(days=32)).replace(day=1)
            labels.append(__(start.strftime("%b")))
            values.append(db.scalar(select(func.count()).select_from(Order)
                                    .where(Order.created_at >= start, Order.created_at < end)) or 0)
        return {"labels": labels, "values": values, "display": [__(":count orders", count=v) for v in values]}


class OrderFunnel(FunnelWidget):
    heading = "Order funnel"
    description = "Where orders are right now"
    icon = "filter"
    sort = 6

    @classmethod
    def items(cls, db):
        counts = dict(db.execute(select(Order.status, func.count()).group_by(Order.status)).all())
        total = sum(counts.values())
        processing = total - counts.get(OrderStatus.PENDING, 0) - counts.get(OrderStatus.CANCELLED, 0)
        shipped = counts.get(OrderStatus.SHIPPED, 0) + counts.get(OrderStatus.PAID, 0)
        return [
            Item("Placed", total, color="primary"),
            Item("Confirmed", processing, color="info"),
            Item("Shipped", shipped, color="purple"),
            Item("Paid", counts.get(OrderStatus.PAID, 0), color="success"),
        ]


class TopCustomers(LeaderboardWidget):
    heading = "Top customers"
    description = "By total spend"
    icon = "trophy"
    sort = 7

    @classmethod
    def items(cls, db, ctx):
        rows = db.execute(
            select(Customer, func.coalesce(func.sum(Order.total), 0).label("spent"), func.count(Order.id))
            .join(Order, Order.customer_id == Customer.id).group_by(Customer.id)
            .order_by(func.sum(Order.total).desc()).limit(5)
        ).all()
        top = float(rows[0][1]) if rows else 1
        return [Item(c.name, inr(spent), description=__(":count orders", count=n), avatar=c.avatar,
                     percent=float(spent) / top * 100, color="primary") for c, spent, n in rows]


class RecentActivity(ActivityWidget):
    heading = "Recent activity"
    icon = "activity"
    sort = 9

    @classmethod
    def items(cls, db, ctx):
        icons = {"pending": "clock", "processing": "loader", "shipped": "truck", "paid": "badge-check", "cancelled": "circle-x"}
        orders = db.scalars(select(Order).order_by(Order.created_at.desc()).limit(5)).all()
        return [Item(f"{o.number} · {__(o.status.value.title())}",
                     description=f"{o.customer.name} · {inr(o.total)}", time=o.created_at.strftime("%d %b"),
                     icon=icons[o.status.value], color=o.status.color, url=ctx.url("orders", o.id, "edit")) for o in orders]


class TeamSchedule(ScheduleWidget):
    description = "Today's plan"
    sort = 10

    @classmethod
    def items(cls):
        return [
            Item("Stand-up with the team", description="Google Meet", time="10:00", color="primary"),
            Item("Pack and ship orders", description="Warehouse", time="12:30", color="info"),
            Item("Review new products", description="Catalog", time="16:00", color="purple"),
        ]


class GrowBanner(BannerWidget):
    heading = "Selling is better together"
    text = "Invite your teammates to manage orders, products and customers with you."
    eyebrow = "Team"
    button_label = "Invite people"
    variant = "soft"
    color = "purple"
    sort = 11

    @classmethod
    def get_button_url(cls, ctx):
        return ctx.url("users", "create")


class TeamMembers(TeamWidget):
    heading = "Members"
    icon = "users"
    sort = 12

    @classmethod
    def items(cls, db, ctx):
        users = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.id).limit(6)).all()
        return [Item(u.name.split()[0], description=u.department, avatar=u.avatar, badge="online" if i % 3 == 0 else None,
                     color="success", url=ctx.url("users", u.id, "edit")) for i, u in enumerate(users)]


class SetupGuide(ChecklistWidget):
    heading = "Setup guide"
    description = "Get your store ready"
    icon = "list-checks"
    icon_color = "success"
    sort = 13

    @classmethod
    def items(cls, db, ctx):
        has = lambda model: bool(db.scalar(select(func.count()).select_from(model)))  # noqa: E731
        return [
            Item("Add your first product", done=has(Product), url=ctx.url("products", "create")),
            Item("Get your first order", done=has(Order), url=ctx.url("orders", "create")),
            Item("Write a blog post", done=has(Post), url=ctx.url("posts", "create")),
            Item("Set up payments", description="Connect a payment gateway", url=ctx.url("system-settings")),
        ]


DASHBOARD_WIDGETS = [RevenueHero, MonthlyTarget, ShortcutsWidget, ShopStats, SalesOverview, OrderFunnel, TopCustomers,
                     RecentOrders, RecentActivity, TeamSchedule, GrowBanner, TeamMembers, SetupGuide,
                     RevenueChart, TopProducts, UsersByRole, SalesByCategory]
