"""Find the Filament parts of a Laravel project: panels, resources, relation managers, pages, widgets."""

from __future__ import annotations

from dataclasses import dataclass, field

from .laravel import LaravelProject
from .php import (
    Arr,
    ClassConst,
    Const,
    Node,
    PhpClass,
    StaticCall,
    Str,
    Var,
    chain,
    is_literal,
    literal,
    short,
)

STANDARD_PAGES = {"ListRecords", "CreateRecord", "EditRecord", "ViewRecord", "ManageRecords"}

#: Filament plugins people use, and what to use in Tungsten instead
PLUGIN_HINTS = {
    "FilamentShieldPlugin": "roles and permissions are built in: panel.rbac() (see docs/roles-and-permissions.md)",
    "BreezyCore": "profile page and two-factor login are built in: Auth(profile=True, two_factor=True)",
    "FilamentFullCalendarPlugin": "use the tungsten-calendar plugin",
    "EnvironmentIndicatorPlugin": "use the tungsten-environment-indicator plugin",
    "FilamentEnvironmentIndicatorPlugin": "use the tungsten-environment-indicator plugin",
    "FilamentSpatieLaravelBackupPlugin": "use the tungsten-backups plugin",
    "SpatieLaravelMediaLibraryPlugin": "use the tungsten-media-library plugin",
    "FilamentSpatieTagsPlugin": "use the tungsten-tags plugin",
    "FilamentPwaPlugin": "use the tungsten-pwa plugin",
    "ActivitylogPlugin": "the activity log is built in: Panel(activity_log=True)",
    "FilamentLogManager": "the activity log is built in: Panel(activity_log=True)",
    "FilamentApexChartsPlugin": "use tungsten.ChartWidget (see docs/widgets.md)",
    "SpatieLaravelTranslatablePlugin": "translations of the panel are built in (docs/translations.md); "
                                       "translatable model columns need hand work",
    "FilamentExceptionsPlugin": "no Tungsten match yet",
    "QuickCreatePlugin": "use the tungsten-quick-create plugin",
    "FilamentImpersonatePlugin": "use the tungsten-impersonate plugin",
    "FilamentKanbanPlugin": "use the tungsten-kanban plugin",
    "FilamentDashboardPlugin": "use the tungsten-dashboards plugin",
    "TenancyPlugin": "multi-tenancy is built in: Panel(tenancy=Tenancy(...)) (docs/multi-tenancy.md)",
}


@dataclass
class PanelInfo:
    cls: PhpClass
    id: str = "admin"
    path: str = "admin"
    brand: str | None = None
    colors: dict[str, str] = field(default_factory=dict)
    features: set[str] = field(default_factory=set)
    navigation_groups: list[str] = field(default_factory=list)
    plugins: list[tuple[str, str]] = field(default_factory=list)  # (plugin, hint)
    other: list[str] = field(default_factory=list)


@dataclass
class ResourceInfo:
    cls: PhpClass
    model: str | None
    relation_managers: list[PhpClass] = field(default_factory=list)
    missing_relation_managers: list[str] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)
    simple: bool = False
    custom_pages: list[str] = field(default_factory=list)
    page_hooks: list[str] = field(default_factory=list)


@dataclass
class FilamentProject:
    panels: list[PanelInfo]
    resources: list[ResourceInfo]
    pages: list[PhpClass]
    widgets: list[PhpClass]
    version: int


def _ancestry(cls: PhpClass, project: LaravelProject) -> list[str]:
    """Full names of the parent classes, nearest first (follows the project's own base classes)."""
    out, seen = [], set()
    current = cls
    while current is not None and current.extends and len(out) < 8:
        full = current.resolve(current.extends)
        if full in seen:
            break
        seen.add(full)
        out.append(full)
        current = project.classes.get(short(full))
        if current is not None and current.fqn != full:
            current = None
    return out


def _is(cls: PhpClass, project: LaravelProject, *suffixes: str) -> bool:
    return any(p.endswith(s) for p in _ancestry(cls, project) for s in suffixes)


def read_filament(project: LaravelProject) -> FilamentProject:
    resources, pages, widgets, panels = [], [], [], []
    version = 3
    for cls in project.classes.values():
        if cls.kind != "class" or cls.file.path is None:
            continue
        if "Filament\\Schemas\\Schema" in cls.file.uses.values():
            version = 4
        if _is(cls, project, "Filament\\Resources\\Resource"):
            resources.append(read_resource(cls, project))
        elif _is(cls, project, "Filament\\PanelProvider"):
            panels.append(read_panel(cls))
        elif _is(cls, project, "Filament\\Pages\\Page", "Filament\\Pages\\Dashboard",
                 "Filament\\Pages\\SettingsPage") or (
                any("\\Pages\\" in p for p in _ancestry(cls, project))
                and not any("\\Resources\\Pages\\" in p or "\\RelationManagers\\" in p
                            for p in _ancestry(cls, project))
                and any(p.startswith("Filament\\") for p in _ancestry(cls, project))):
            pages.append(cls)
        elif any("Filament\\Widgets\\" in p for p in _ancestry(cls, project)):
            widgets.append(cls)
    resources.sort(key=lambda r: r.cls.name)
    return FilamentProject(panels=panels, resources=resources, pages=sorted(pages, key=lambda c: c.name),
                           widgets=sorted(widgets, key=lambda c: c.name), version=version)


def read_resource(cls: PhpClass, project: LaravelProject) -> ResourceInfo:
    model_node = cls.prop("model")
    model = short(cls.resolve(model_node.cls)) if isinstance(model_node, ClassConst) else None
    if isinstance(model_node, Str):
        model = short(model_node.value)
    info = ResourceInfo(cls=cls, model=model)
    for node in cls.returns("getRelations"):
        for _, value in (node.items if isinstance(node, Arr) else []):
            if isinstance(value, ClassConst) and value.name == "class":
                rm = project.classes.get(short(cls.resolve(value.cls)))
                if rm is not None:
                    info.relation_managers.append(rm)
                else:
                    info.missing_relation_managers.append(value.cls)
            elif isinstance(value, StaticCall):  # RelationGroup::make('Contacts', [A::class, B::class])
                for arg in value.args:
                    if isinstance(arg.value, Arr):
                        for _, inner in arg.value.items:
                            if isinstance(inner, ClassConst):
                                rm = project.classes.get(short(cls.resolve(inner.cls)))
                                if rm is not None:
                                    info.relation_managers.append(rm)
        break
    for node in cls.returns("getPages"):
        if not isinstance(node, Arr):
            continue
        for key, value in node.items:
            name = literal(key) if key is not None and is_literal(key) else None
            base, _ = chain(value) if value is not None else (None, [])
            page_cls = project.classes.get(short(cls.resolve(base.cls))) if isinstance(base, StaticCall) else None
            parent = short(page_cls.resolve(page_cls.extends)) if page_cls and page_cls.extends else ""
            if parent == "ManageRecords":
                info.simple = True
                info.pages.append("index")
            elif name in ("index", "create", "edit", "view") and (parent in STANDARD_PAGES or page_cls is None):
                info.pages.append(name)
            else:
                info.custom_pages.append(f"{name}: {short(base.cls) if isinstance(base, StaticCall) else '?'}")
            if page_cls is not None:
                hooks = [m for m in page_cls.methods if m not in ("getHeaderActions", "getTitle", "getHeading",
                                                                   "getRedirectUrl", "getHeaderWidgets",
                                                                   "getFooterWidgets", "getTabs")]
                if hooks:
                    info.page_hooks.append(f"{page_cls.name}: {', '.join(hooks)}")
                if "getTabs" in page_cls.methods:
                    info.page_hooks.append(f"{page_cls.name}: getTabs (list tabs)")
        break
    return info


def read_panel(cls: PhpClass) -> PanelInfo:
    info = PanelInfo(cls=cls)
    for node in cls.returns("panel"):
        base, calls = chain(node)
        if not isinstance(base, Var):
            continue
        for call in calls:
            m = call.method
            arg = call.args[0].value if call.args else None
            if m == "id" and isinstance(arg, Str):
                info.id = arg.value
            elif m == "path" and isinstance(arg, Str):
                info.path = arg.value
            elif m == "brandName" and isinstance(arg, Str):
                info.brand = arg.value
            elif m == "colors" and isinstance(arg, Arr):
                for k, v in arg.items:
                    if isinstance(k, Str) and isinstance(v, ClassConst):
                        info.colors[k.value] = v.name.lower()
                    elif isinstance(k, Str) and isinstance(v, Str) and v.value.startswith("#"):
                        info.colors[k.value] = v.value
            elif m in ("login", "registration", "passwordReset", "emailVerification", "profile", "spa",
                       "databaseNotifications", "multiFactorAuthentication", "sidebarCollapsibleOnDesktop",
                       "topNavigation", "globalSearch", "darkMode"):
                if not (isinstance(arg, Const) and arg.name.lower() == "false"):
                    info.features.add(m)
            elif m == "navigationGroups" and isinstance(arg, Arr):
                for _, v in arg.items:
                    if isinstance(v, Str):
                        info.navigation_groups.append(v.value)
                    else:
                        b, _ = chain(v)
                        if isinstance(b, StaticCall) and b.args and isinstance(b.args[0].value, Str):
                            info.navigation_groups.append(b.args[0].value.value)
            elif m in ("plugin", "plugins"):
                values = [v for _, v in arg.items] if isinstance(arg, Arr) else [arg]
                for v in values:
                    b, _ = chain(v) if v is not None else (None, [])
                    name = short(cls.resolve(b.cls)) if isinstance(b, (StaticCall,)) else \
                        short(cls.resolve(b.cls)) if hasattr(b, "cls") else (v.src if v is not None else "?")
                    info.plugins.append((name, PLUGIN_HINTS.get(name, "no Tungsten match yet: check "
                                                                       "https://tungsten.prisminfoways.com/plugins")))
            elif m in ("default", "discoverResources", "discoverPages", "discoverWidgets", "pages", "widgets",
                       "middleware", "authMiddleware", "authGuard", "viteTheme", "favicon", "font", "brandLogo",
                       "maxContentWidth", "resources", "renderHook", "navigationItems", "userMenuItems"):
                if m in ("renderHook", "navigationItems", "userMenuItems", "authGuard", "viteTheme"):
                    info.other.append(m)
            else:
                info.other.append(m)
        break
    return info


def first_return(cls: PhpClass, method: str) -> Node | None:
    rets = cls.returns(method)
    return rets[0] if rets else None


def delegated(node: Node | None, project: LaravelProject, cls: PhpClass) -> tuple[Node | None, PhpClass] | None:
    """Filament 4 keeps forms and tables in their own classes: ``return ProductForm::configure($schema);``."""
    if isinstance(node, StaticCall) and node.method in ("configure", "make", "form", "table", "schema", "infolist"):
        target = project.classes.get(short(cls.resolve(node.cls)))
        if target is not None:
            return first_return(target, node.method), target
    return None

