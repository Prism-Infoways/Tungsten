"""Custom pages and the dashboard."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, ClassVar

from markupsafe import Markup

from .hosts import Host
from .i18n import translate as __
from .support.component import headline
from .support.evaluate import call

if TYPE_CHECKING:  # pragma: no cover
    from .context import Context
    from .forms.form import Form
    from .tables.table import Table


def _kebab(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()


class Page:
    """A custom page in the panel. Give it content, widgets, a form, or all three::

        class Settings(Page):
            icon = "settings"
            navigation_group = "Settings"

            @classmethod
            def form(cls, form):
                return form.schema([TextInput("site_name").required()])

            @classmethod
            def mount(cls, ctx):          # initial form data
                return load_settings(ctx.db)

            @classmethod
            def save(cls, ctx, data):     # on submit
                store_settings(ctx.db, data)
    """

    slug: ClassVar[str | None] = None
    title: ClassVar[str | None] = None
    subheading: ClassVar[str | None] = None
    icon: ClassVar[str | None] = "file"
    navigation_group: ClassVar[str | None] = None
    navigation_label: ClassVar[str | None] = None
    navigation_sort: ClassVar[int] = 0
    navigation_parent: ClassVar[str | None] = None
    show_in_navigation: ClassVar[bool] = True
    #: a :class:`~tungsten.navigation.Cluster`: the page then sits in that cluster's sub-menu
    cluster: ClassVar[Any] = None
    template: ClassVar[str] = "tungsten/pages/page.html"
    #: template rendered inside the page body (receives ``ctx`` and ``page``)
    content_template: ClassVar[str | None] = None
    widgets: ClassVar[list] = []
    widget_columns: ClassVar[int] = 4
    #: where the page's widgets go: ``"above"`` the form (default) or ``"below"`` it (and below its table)
    widgets_position: ClassVar[str] = "above"
    save_label: ClassVar[str] = "Save changes"
    #: the model of the page's own table (see :meth:`table`)
    table_model: ClassVar[Any] = None
    permission: ClassVar[str | None] = None
    #: set for a page that lives under a resource (``Resource.custom_pages``): its users need that resource
    resource: ClassVar[Any] = None

    @classmethod
    def get_slug(cls) -> str:
        return cls.slug or _kebab(cls.__name__)

    @classmethod
    def get_title(cls) -> str:
        return __(cls.title or headline(_kebab(cls.__name__).replace("-", "_")))

    @classmethod
    def get_navigation_label(cls, ctx: "Context | None" = None) -> str:
        return __(cls.navigation_label) if cls.navigation_label else cls.get_title()

    @classmethod
    def get_navigation_group(cls, ctx: "Context | None" = None) -> str | None:
        """The sidebar group: ``navigation_group``, or override to pick one per user."""
        return cls.navigation_group

    @classmethod
    def navigation_badge(cls, ctx: "Context") -> Any:
        return None

    @classmethod
    def navigation_badge_tooltip(cls, ctx: "Context") -> str | None:
        """Hover text for the menu badge (e.g. "3 waiting for you")."""
        return None

    navigation_badge_color: ClassVar[str] = "primary"

    @classmethod
    def can_access(cls, ctx: "Context") -> bool:
        if cls.resource is not None and not cls.resource.can(ctx, "view_any"):
            return False
        if cls.permission:
            return ctx.can(cls.permission)
        return True

    @classmethod
    def get_subheading(cls, ctx: "Context") -> str | None:
        return __(cls.subheading) if cls.subheading else None

    @classmethod
    def content(cls, ctx: "Context") -> Any:
        """Return HTML (``Markup``) for the page body, or ``None``."""
        if cls.content_template:
            return ctx.panel.renderer.render(cls.content_template, ctx=ctx, page=cls)
        return None

    @classmethod
    def form(cls, form: "Form") -> "Form | None":
        return None

    @classmethod
    def table(cls, table: "Table") -> "Table | None":
        """A full table on the page (search, filters, actions), like a resource list. Set ``table_model``::

            table_model = Order

            @classmethod
            def table(cls, table):
                return table.columns([TextColumn("number"), TextColumn("total").money("INR")])
        """
        return None

    @classmethod
    def table_query(cls, ctx: "Context") -> Any:
        """The records of :meth:`table` (override to narrow them)."""
        from sqlalchemy import select

        return select(cls.table_model)

    @classmethod
    def mount(cls, ctx: "Context") -> dict[str, Any]:
        return {}

    @classmethod
    def save(cls, ctx: "Context", data: dict[str, Any]) -> Any:
        return None

    @classmethod
    def header_actions(cls, ctx: "Context") -> list:
        return []

    @classmethod
    def filters_form(cls, form: "Form") -> "Form | None":
        """Filters shown in the page header and passed to every widget as ``filters``::

            return form.schema([Select("period").options({"7": "Last 7 days"}).default("7")])
        """
        return None

    @classmethod
    def build_filters_form(cls, ctx: "Context") -> "Form | None":
        from .forms.form import Form

        form = cls.filters_form(Form())
        if form is None:
            return None
        form.bind(ctx, operation="filter", refresh_url="", id="tw-page-filters")
        params = ctx.request.query_params
        if any(f.name in params for f, _, _ in form.walk_fields()):
            form.load(params)
        else:
            form.fill()
        return form

    @classmethod
    def get_filters(cls, ctx: "Context") -> dict[str, Any]:
        from .forms.form import ValidationError

        form = cls.build_filters_form(ctx)
        if form is None:
            return {}
        try:
            return form.validate()
        except ValidationError:
            form.fill()
            return form.validate()

    @classmethod
    def get_widgets(cls, ctx: "Context") -> list:
        return [w for w in cls.widgets if w.can_view(ctx)]

    @classmethod
    def host(cls) -> "PageHost":
        return PageHost(cls)

    @classmethod
    def get_url(cls, ctx: "Context") -> str:
        return ctx.url(cls.get_slug())

    @classmethod
    def permission_prefix(cls) -> str:
        return f"page.{cls.get_slug()}"


class Dashboard(Page):
    """The panel home page. Widgets come from ``panel.widgets([...])`` by default."""

    slug = ""
    title = "Dashboard"
    icon = "layout-dashboard"
    navigation_sort = -100
    template = "tungsten/pages/dashboard.html"

    @classmethod
    def get_widgets(cls, ctx: "Context") -> list:
        widgets = cls.widgets or ctx.panel.get_widgets()
        return sorted([w for w in widgets if w.can_view(ctx)], key=lambda w: w.sort)

    @classmethod
    def get_subheading(cls, ctx: "Context") -> str | None:
        if cls.subheading:
            return __(cls.subheading)
        return __("Here's what's happening today.")

    @classmethod
    def greeting(cls, ctx: "Context") -> str:
        name = ctx.panel.auth.display_name(ctx.user).split(" ")[0] if ctx.user else ""
        return __("Welcome back, :name!", name=name) if name else __("Dashboard")


class PageHost(Host):
    def __init__(self, page: type[Page]) -> None:
        self.page = page
        self.key = f"page:{page.get_slug() or '_dashboard'}"
        self.model = page.table_model

    def get_table(self, ctx: "Context") -> "Table | None":
        if self.page.table_model is None:
            return None
        from .tables.table import Table

        table = Table()
        table.ctx = ctx
        return self.page.table(table)

    def base_query(self, ctx: "Context") -> Any:
        return call(self.page.table_query, ctx=ctx, db=ctx.db, user=ctx.user)

    def form(self, ctx: "Context", operation: str = "edit", record: Any = None) -> "Form | None":
        from .forms.form import Form

        form = self.page.form(Form())
        if form is None:
            return None
        form.bind(ctx, operation=operation, source={"kind": "host", "host": self.key, "op": operation, "record": ""})
        return form

    def page_actions(self, ctx: "Context", record: Any = None) -> list:
        return list(self.page.header_actions(ctx) or [])

    def can(self, ctx: "Context", ability: str, record: Any = None) -> bool:
        return self.page.can_access(ctx)

    def page_url(self, ctx: "Context") -> str | None:
        return self.page.get_url(ctx)

    def title(self) -> str:
        return self.page.get_title()

    def save(self, ctx: "Context", data: dict) -> Any:
        return call(self.page.save, ctx=ctx, data=data, db=ctx.db, user=ctx.user)


def render_markup(value: Any) -> Markup:
    return value if isinstance(value, Markup) else Markup(value or "")
