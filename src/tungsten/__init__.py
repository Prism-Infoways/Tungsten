"""Tungsten — a Filament-style admin panel for FastAPI.

Quick start::

    from tungsten import Panel, Resource, Auth
    from tungsten.forms import TextInput
    from tungsten.tables import TextColumn

    class ProductResource(Resource):
        model = Product

        @classmethod
        def form(cls, form):
            return form.schema([TextInput("name").required()])

        @classmethod
        def table(cls, table):
            return table.columns([TextColumn("name").searchable().sortable()])

    panel = Panel(engine=engine, secret_key="...", auth=Auth(User))
    panel.resources([ProductResource]).mount(app)
"""

from .auth import Auth, hash_password, verify_password
from .context import Context
from .i18n import __, translate
from .navigation import NavigationGroup, NavigationItem
from .notifications import Notification
from .pages import Dashboard, Page
from .panel import VERSION as __version__
from .panel import Panel
from .plugins import Plugin
from .resources.relation_manager import RelationManager
from .resources.resource import Resource
from .storage import LocalStorage, Storage
from .tenancy import Tenancy
from .widgets import (
    AccountWidget,
    ChartWidget,
    ProgressItem,
    ProgressListWidget,
    Stat,
    StatsOverviewWidget,
    TableWidget,
    Widget,
)

__all__ = [
    "AccountWidget", "Auth", "ChartWidget", "Context", "Dashboard", "LocalStorage", "NavigationGroup",
    "NavigationItem", "Notification", "Page", "Panel", "Plugin", "ProgressItem", "ProgressListWidget",
    "RelationManager", "Resource", "Stat", "StatsOverviewWidget", "Storage", "TableWidget", "Tenancy", "Widget",
    "__", "__version__", "hash_password", "translate", "verify_password",
]
