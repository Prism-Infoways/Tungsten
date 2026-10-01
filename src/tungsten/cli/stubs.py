"""File templates used by the CLI generators."""

from __future__ import annotations


def _indent(lines: list[str], spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(f"{pad}{line}," for line in lines)


def resource(*, cls: str, model_module: str, model: str, fields: list[str], columns: list[str],
             search: list[str], imports: list[str], simple: bool, soft_deletes: bool) -> str:
    table_imports = ["TextColumn"]
    if any(c.startswith("IconColumn") for c in columns):
        table_imports.append("IconColumn")
    if soft_deletes:
        table_imports.append("TrashedFilter")
    actions = ["EditAction", "DeleteAction", "DeleteBulkAction"]
    if soft_deletes:
        actions += ["RestoreAction", "RestoreBulkAction", "ForceDeleteBulkAction"]
    enum_imports = sorted({f.split(".options(")[1].split(")")[0] for f in fields
                           if ".options(" in f and not f.split(".options(")[1].startswith(("[", "{"))})
    model_import = ", ".join([model, *enum_imports])
    row_actions = "EditAction(), DeleteAction()" + (", RestoreAction()" if soft_deletes else "")
    bulk = "DeleteBulkAction()" + (", RestoreBulkAction(), ForceDeleteBulkAction()" if soft_deletes else "")
    filters = "\n            .filters([TrashedFilter()])" if soft_deletes else ""
    simple_line = "\n    simple = True  # create/edit in modals" if simple else ""
    return f'''from tungsten import Resource
from tungsten.actions import {", ".join(sorted(actions))}
from tungsten.forms import Section, {", ".join(imports)}
from tungsten.tables import {", ".join(table_imports)}

from {model_module} import {model_import}


class {cls}Resource(Resource):
    model = {model}
    icon = "file-text"
    # navigation_group = "Shop"
    global_search_attributes = {search!r}{simple_line}

    @classmethod
    def form(cls, form):
        return form.schema([
            Section("{cls}").schema([
{_indent(fields, 16)}
            ]),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
{_indent(columns, 16)}
            ]){filters}
            .actions([{row_actions}])
            .bulk_actions([{bulk}])
        )
'''


def relation_manager(*, cls: str, relationship: str, attach: bool) -> str:
    header = "AttachAction(), CreateAction()" if attach else "CreateAction()"
    row = "EditAction(), DetachAction()" if attach else "EditAction(), DeleteAction()"
    imports = ["CreateAction", "EditAction", "DeleteBulkAction"] + (
        ["AttachAction", "DetachAction"] if attach else ["DeleteAction"])
    return f'''from tungsten import RelationManager
from tungsten.actions import {", ".join(sorted(imports))}
from tungsten.forms import TextInput
from tungsten.tables import TextColumn


class {cls}(RelationManager):
    relationship = "{relationship}"
    icon = "list"

    @classmethod
    def form(cls, form):
        return form.schema([
            TextInput("name").required(),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("name").searchable().sortable(),
            ])
            .header_actions([{header}])
            .actions([{row}])
            .bulk_actions([DeleteBulkAction()])
        )
'''


def page(*, cls: str, form: bool) -> str:
    if not form:
        return f'''from markupsafe import Markup

from tungsten import Page


class {cls}(Page):
    icon = "file"
    # navigation_group = "Settings"
    subheading = "A custom page."

    @classmethod
    def content(cls, ctx):
        return Markup('<div class="tw-card p-6">Hello from {cls}!</div>')
'''
    return f'''from tungsten import Page
from tungsten.forms import Section, TextInput, Toggle


class {cls}(Page):
    icon = "settings"
    # navigation_group = "Settings"

    @classmethod
    def form(cls, form):
        return form.schema([
            Section("General").schema([
                TextInput("site_name").required(),
                Toggle("maintenance_mode"),
            ]),
        ])

    @classmethod
    def mount(cls, ctx):
        """Initial form data."""
        return {{"site_name": "My site", "maintenance_mode": False}}

    @classmethod
    def save(cls, ctx, data):
        """Called with the validated data when the form is submitted."""
        print("saving", data)
'''


def widget(*, cls: str, kind: str) -> str:
    if kind == "chart":
        return f'''from tungsten import ChartWidget


class {cls}(ChartWidget):
    heading = "{cls}"
    type = "line"  # line, bar, pie, doughnut, radar, polarArea
    filters = {{"week": "This week", "month": "This month"}}

    @classmethod
    def data(cls, ctx, filter):
        return {{
            "labels": ["Mon", "Tue", "Wed", "Thu", "Fri"],
            "datasets": [{{"label": "Sales", "data": [3, 7, 4, 9, 6], "color": "primary"}}],
        }}
'''
    if kind == "table":
        return f'''from sqlalchemy import select

from tungsten import TableWidget
from tungsten.tables import TextColumn

# from app.models import Order


class {cls}(TableWidget):
    heading = "{cls}"
    model = None  # set to your model, e.g. Order

    @classmethod
    def query(cls, ctx):
        return select(cls.model)

    @classmethod
    def table(cls, table):
        return table.columns([TextColumn("id")]).limit(5)
'''
    if kind == "progress":
        return f'''from tungsten import ProgressItem, ProgressListWidget


class {cls}(ProgressListWidget):
    heading = "{cls}"

    @classmethod
    def items(cls, ctx):
        return [ProgressItem("Clothing", "35%", 35, "shirt"), ProgressItem("Footwear", "25%", 25, "footprints")]
'''
    return f'''from tungsten import Stat, StatsOverviewWidget


class {cls}(StatsOverviewWidget):
    @classmethod
    def stats(cls, ctx, db):
        return [
            Stat("Total users", "1,248").icon("users").trend("12%", "up").chart([3, 5, 4, 6, 8, 7, 9]),
            Stat("Orders", "892").icon("shopping-cart").color("success").trend("8%", "up"),
            Stat("Revenue", "₹12,48,000").icon("indian-rupee").color("info"),
            Stat("Refunds", "12").icon("rotate-ccw").color("danger").trend("4%", "down"),
        ]
'''


def plugin(*, cls: str, plugin_id: str) -> str:
    return f'''from markupsafe import Markup

from tungsten import Plugin


class {cls}(Plugin):
    id = "{plugin_id}"

    def register(self, panel):
        """Add resources, pages and widgets here."""
        # panel.resources([...]).pages([...]).widgets([...])

    def boot(self, panel):
        """Runs once before the panel serves requests."""
        panel.render_hook("sidebar.nav.end", lambda: Markup(""))
'''


def panel() -> str:
    return '''"""Your Tungsten admin panel. Mount it with ``panel.mount(app)``."""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tungsten import Auth, Panel

# from app.models import User

engine = create_engine(os.environ.get("DATABASE_URL", "sqlite:///app.db"))
SessionLocal = sessionmaker(engine, expire_on_commit=False)

panel = Panel(
    path="/admin",
    session_factory=SessionLocal,
    secret_key=os.environ.get("SECRET_KEY", "change-me"),
    # auth=Auth(User),  # turn on login
    brand_name="Admin",
    colors={"primary": "orange"},
)

# panel.resources([UserResource])
# panel.rbac()                # roles & permissions
panel.create_tables(engine)   # Tungsten's own tables (roles, notifications)
'''
