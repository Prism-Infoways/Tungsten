"""Turn Filament form, table, infolist and action code into Tungsten Python code.

Every Filament call is mapped to the Tungsten call with the same meaning. Tungsten
copies Filament's API (``TextInput("name").required().max_length(255)``), so most
calls map by name. Before a call is written, it is checked against the real
Tungsten class, so the generated code only uses methods that exist. Whatever
cannot be carried over is written as a ``# TODO(filament)`` comment next to the
component and listed in the migration report.
"""

from __future__ import annotations

import inspect
import keyword
import re
from dataclasses import dataclass, field
from typing import Any

from . import closures
from .laravel import LaravelProject, snake
from .php import (
    Arg,
    Arr,
    Call,
    ClassConst,
    Closure,
    Const,
    MethodCall,
    New,
    Node,
    Num,
    PhpFile,
    Prop,
    Raw,
    StaticCall,
    Str,
    Var,
    chain,
    is_literal,
    literal,
    short,
)


# ------------------------------------------------------------------ bookkeeping
@dataclass
class Todo:
    file: str
    line: int
    code: str
    reason: str

    def comment(self) -> str:
        code = " ".join(self.code.split())
        if len(code) > 90:
            code = code[:87] + "..."
        return f"# TODO(filament): {self.reason}: {code}" if code else f"# TODO(filament): {self.reason}"


class Imports:
    def __init__(self) -> None:
        self.modules: dict[str, set[str]] = {}
        self.plain: set[str] = set()

    def add(self, module: str, name: str) -> None:
        self.modules.setdefault(module, set()).add(name)

    def lines(self) -> list[str]:
        out = sorted(self.plain)
        if out:
            out.append("")
        groups = sorted(self.modules.items(), key=lambda kv: (kv[0].startswith("."), kv[0]))
        last_local = None
        for module, names in groups:
            local = module.startswith(".")
            if last_local is not None and local != last_local:
                out.append("")
            last_local = local
            line = f"from {module} import {', '.join(sorted(names))}"
            if len(line) > 110:
                line = f"from {module} import (\n" + indent(", ".join(sorted(names))) + ",\n)"
                if max(len(x) for x in line.split("\n")) > 110:
                    line = f"from {module} import (\n" + "".join(f"    {n},\n" for n in sorted(names)) + ")"
            out.append(line)
        return out


@dataclass
class Ctx:
    project: LaravelProject
    php: PhpFile
    where: str
    imports: Imports
    todos: list[Todo] = field(default_factory=list)
    model: str | None = None  # the resource's model, for filter queries

    def todo(self, node: Node | None, reason: str) -> Todo:
        t = Todo(self.where, getattr(node, "line", 0) or 0, getattr(node, "src", "") or "", reason)
        self.todos.append(t)
        return t

    def resolve(self, name: str) -> str:
        return self.php.resolve(name)

    def has_relation(self, name: str) -> bool:
        """False only when the resource's model is known and models.py has no relation by that name."""
        known = self.project.converted_relations.get(self.model or "")
        model = self.project.models.get(self.model or "")
        return known is None or name in known or bool(model and name in model.casts)  # a JSON column path

    def enum_value(self, cls: str, case: str) -> Any:
        enum = self.project.enums.get(short(self.resolve(cls)))
        if enum is None:
            return None
        for name, value in enum.cases:
            if name == case:
                return value
        return None


# ------------------------------------------------------------------ Tungsten classes
def _tungsten() -> dict[str, dict[str, Any]]:
    from tungsten import actions, forms, infolists, tables

    def pick(mod: Any, names: list[str]) -> dict[str, Any]:
        return {n: getattr(mod, n) for n in names}

    return {
        "tungsten.forms": pick(forms, [n for n in forms.__all__ if n[0].isupper()]),
        "tungsten.tables": pick(tables, [n for n in tables.__all__ if n[0].isupper()]),
        "tungsten.actions": pick(actions, [n for n in actions.__all__ if n[0].isupper()]),
        "tungsten.infolists": pick(infolists, [n for n in infolists.__all__ if n[0].isupper()]),
    }


_TW: dict[str, dict[str, Any]] | None = None


def tw(module: str, name: str) -> Any:
    global _TW
    if _TW is None:
        _TW = _tungsten()
    return _TW[module][name]


# Filament class -> (Tungsten module, Tungsten class, extra calls, note)
FORM_FIELDS = {
    "TextInput": "TextInput", "Textarea": "Textarea", "Select": "Select", "Checkbox": "Checkbox", "Toggle": "Toggle",
    "CheckboxList": "CheckboxList", "Radio": "Radio", "ToggleButtons": "ToggleButtons", "DatePicker": "DatePicker",
    "DateTimePicker": "DateTimePicker", "TimePicker": "TimePicker", "ColorPicker": "ColorPicker",
    "RichEditor": "RichEditor", "TagsInput": "TagsInput", "FileUpload": "FileUpload", "Repeater": "Repeater",
    "Builder": "Builder", "KeyValue": "KeyValue", "Hidden": "Hidden", "Placeholder": "Placeholder",
    "Block": "Block", "MorphToSelect": None, "ViewField": None, "View": None, "Livewire": None,
    "MarkdownEditor": "Textarea", "SpatieMediaLibraryFileUpload": "FileUpload", "SpatieTagsInput": "TagsInput",
    "TableRepeater": "Repeater", "CodeEditor": "Textarea", "Slider": "TextInput", "ModalTableSelect": "Select",
}
FORM_LAYOUTS = {
    "Section": "Section", "Card": "Section", "Fieldset": "Fieldset", "Grid": "Grid", "Group": "Group", "Tabs": "Tabs",
    "Tab": "Tab", "Wizard": "Wizard", "Step": "Step", "Split": "Grid", "Flex": "Grid", "FusedGroup": "Group",
}
FIELD_NOTES = {
    "MarkdownEditor": "MarkdownEditor became a Textarea (Tungsten has no Markdown editor; the text is kept as is)",
    "SpatieMediaLibraryFileUpload": "Spatie media files live in the `media` table; this FileUpload saves a path in "
                                    "the column instead. Map it by hand or use tungsten-media-library",
    "SpatieTagsInput": "Spatie tags live in the `tags`/`taggables` tables; consider tungsten-tags",
    "CodeEditor": "CodeEditor became a Textarea",
    "Slider": "Slider became a number input",
    "TableRepeater": "TableRepeater became a Repeater",
    "ModalTableSelect": "ModalTableSelect became a Select",
}
COLUMNS = {
    "TextColumn": "TextColumn", "IconColumn": "IconColumn", "ImageColumn": "ImageColumn", "ToggleColumn": "ToggleColumn",
    "CheckboxColumn": "CheckboxColumn", "TextInputColumn": "TextInputColumn", "SelectColumn": "SelectColumn",
    "ColorColumn": "ColorColumn", "BadgeColumn": "TextColumn", "BooleanColumn": "IconColumn", "TagsColumn": "TextColumn",
    "SpatieMediaLibraryImageColumn": "ImageColumn", "SpatieTagsColumn": "TextColumn", "ViewColumn": None,
    "Split": None, "Stack": None, "Panel": None, "Layout": None,
}
COLUMN_EXTRA = {"BadgeColumn": ".badge()", "BooleanColumn": ".boolean()", "TagsColumn": ".badge()",
                "SpatieTagsColumn": ".badge()"}
FILTERS = {"SelectFilter": "SelectFilter", "TernaryFilter": "TernaryFilter", "TrashedFilter": "TrashedFilter",
           "Filter": "Filter", "QueryBuilder": None, "DateFilter": "DateFilter"}
ACTIONS = {
    "CreateAction": "CreateAction", "EditAction": "EditAction", "ViewAction": "ViewAction",
    "DeleteAction": "DeleteAction", "RestoreAction": "RestoreAction", "ForceDeleteAction": "ForceDeleteAction",
    "ReplicateAction": "ReplicateAction", "AttachAction": "AttachAction", "DetachAction": "DetachAction",
    "DeleteBulkAction": "DeleteBulkAction", "RestoreBulkAction": "RestoreBulkAction",
    "ForceDeleteBulkAction": "ForceDeleteBulkAction", "DetachBulkAction": "DetachBulkAction",
    "ActionGroup": "ActionGroup", "BulkActionGroup": "BulkActionGroup",
}
BULK = {"DeleteBulkAction", "RestoreBulkAction", "ForceDeleteBulkAction", "DetachBulkAction", "BulkActionGroup",
        "BulkAction", "ExportBulkAction", "DissociateBulkAction"}
ACTION_NOTES = {
    "Action": "custom action: write its code with tungsten.actions.Action",
    "BulkAction": "custom bulk action: write its code with tungsten.actions.BulkAction",
    "ExportAction": "export: Tungsten has export built in, see docs/import-export.md",
    "ImportAction": "import: Tungsten has import built in, see docs/import-export.md",
    "ExportBulkAction": "export: Tungsten has export built in, see docs/import-export.md",
    "AssociateAction": "AssociateAction has no Tungsten match yet",
    "DissociateAction": "DissociateAction has no Tungsten match yet",
    "DissociateBulkAction": "DissociateBulkAction has no Tungsten match yet",
}
ENTRIES = {"TextEntry": "TextEntry", "IconEntry": "IconEntry", "ImageEntry": "ImageEntry", "ColorEntry": "ColorEntry",
           "KeyValueEntry": "KeyValueEntry", "RepeatableEntry": "RepeatableEntry",
           "SpatieMediaLibraryImageEntry": "ImageEntry"}
SUMMARIZERS = {"Sum": "Sum", "Average": "Average", "Count": "Count", "Min": "Min", "Max": "Max", "Range": None}

# Filament method -> Tungsten method, where the snake_case name is not the answer
RENAMES = {
    "reactive": "live", "dateTime": "datetime", "isToggledHiddenByDefault": "hidden_by_default",
    "decimalPlaces": "decimals", "divideBy": "divide_by", "onBlur": "on_blur", "ignoreRecord": "ignore_record",
    "recordActions": "actions", "bulkActions": "bulk_actions", "groupedBulkActions": "bulk_actions",
    "headerActions": "header_actions", "emptyStateActions": "empty_state_actions", "titleAttribute": "title_attribute",
    "isIndividual": "is_individual", "isGlobal": "is_global", "autosize": "autosize",
    "searchPlaceholder": "search_placeholder", "trueIcon": "true_icon", "falseIcon": "false_icon",
    "trueColor": "true_color", "falseColor": "false_color", "onColor": "on_color", "offColor": "off_color",
    "onIcon": "on_icon", "offIcon": "off_icon", "multiple": "multiple", "dehydrateStateUsing": "dehydrate_state_using",
    "formatStateUsing": "format_state_using", "afterStateUpdated": "after_state_updated",
    "getOptionLabelUsing": None, "relationshipTitle": None,
}

# calls that only tune Filament's own UI or Livewire: dropped with an "info" note
COSMETIC = {
    "deferLoading", "persistFiltersInSession", "persistSearchInSession", "persistSortInSession",
    "persistColumnSearchesInSession", "filtersTriggerAction", "filtersFormColumns", "filtersFormWidth",
    "filtersFormMaxHeight", "recordClasses", "extraAttributes", "extraInputAttributes", "extraFieldWrapperAttributes",
    "inlineLabel", "hiddenLabel", "grow", "verticallyAlignStart", "verticallyAlignCenter", "toggledHiddenByDefault",
    "iconPosition", "iconSize", "badgeTooltip", "paginatedWhileReordering", "selectCurrentPageOnly",
    "striped", "contentGrid", "extremePaginationLinks", "defaultPaginationPageOption", "queryStringIdentifier",
    "loadingIndicator", "native", "closeOnDateSelection", "imagePreviewHeight", "panelLayout", "loadingIndicatorPosition",
    "imageEditor", "imageEditorAspectRatios", "imageResizeMode", "imageCropAspectRatio", "imageResizeTargetWidth",
    "imageResizeTargetHeight", "openable", "downloadable", "previewable", "preserveFilenames", "uploadingMessage",
    "minimal", "aside", "compact", "persistTab", "persistTabInQueryString", "skippable", "startOnStep",
    "persistStepInQueryString", "contained", "visibility", "itemLabel", "cloneable", "collapsed",
    "deletable", "addActionLabel", "addable", "reorderableWithButtons", "reorderableWithDragAndDrop", "simple",
    "wrapHeader", "alignEnd", "alignCenter", "alignStart", "alignment", "searchDebounce", "inline",
    "suffixIconColor", "prefixIconColor", "extraImgAttributes", "stacked", "ring", "overlap", "limitedRemainingText",
    "checkFileExistence", "visibleFrom", "hiddenFrom", "html", "markdown", "fontFamily", "copyMessage",
    "copyMessageDuration", "lineClamp", "searchPrompt", "noSearchResultsMessage", "loadingMessage", "optionsLimit",
    "allowHtml", "selectablePlaceholder", "default_sort_direction", "selectable",
}
FILAMENT_ENUM_VALUES = {
    "FontWeight": {"Thin": "thin", "ExtraLight": "extralight", "Light": "light", "Normal": "normal", "Medium": "medium",
                   "SemiBold": "semibold", "Bold": "bold", "ExtraBold": "extrabold", "Black": "black"},
    "TextColumnSize": {"ExtraSmall": "xs", "Small": "sm", "Medium": "md", "Large": "lg"},
    "TextSize": {"ExtraSmall": "xs", "Small": "sm", "Medium": "md", "Large": "lg"},
    "IconSize": {"ExtraSmall": "xs", "Small": "sm", "Medium": "md", "Large": "lg", "ExtraLarge": "xl"},
    "Alignment": {"Start": "start", "Center": "center", "End": "end", "Left": "start", "Right": "end"},
    "FiltersLayout": {"AboveContent": "above", "AboveContentCollapsible": "above", "BelowContent": "below",
                      "Dropdown": "dropdown", "Modal": "dropdown", "Hidden": "dropdown"},
}


# ------------------------------------------------------------------ icons
HEROICON_TO_LUCIDE = {
    "rectangle-stack": "layers", "document": "file", "document-text": "file-text", "cube": "box", "tag": "tag",
    "banknotes": "banknote", "currency-dollar": "circle-dollar-sign", "currency-rupee": "indian-rupee",
    "building-office": "building", "building-office-2": "building-2", "building-storefront": "store",
    "clipboard-document-list": "clipboard-list", "clipboard-document": "clipboard", "envelope": "mail",
    "lock-closed": "lock", "photo": "image", "wrench": "wrench", "wrench-screwdriver": "wrench",
    "academic-cap": "graduation-cap", "chat-bubble-left-right": "messages-square",
    "chat-bubble-left": "message-square", "chat-bubble-oval-left": "message-circle", "globe-alt": "globe",
    "light-bulb": "lightbulb", "puzzle-piece": "puzzle", "user-circle": "circle-user", "video-camera": "video",
    "receipt-percent": "receipt", "receipt-refund": "receipt", "squares-2x2": "layout-grid", "list-bullet": "list",
    "archive-box": "archive", "bolt": "zap", "beaker": "flask-conical", "circle-stack": "database",
    "cpu-chip": "cpu", "identification": "id-card", "musical-note": "music", "paper-airplane": "send",
    "presentation-chart-line": "presentation", "presentation-chart-bar": "presentation", "table-cells": "table",
    "chart-pie": "chart-pie", "chart-bar-square": "chart-column", "arrow-trending-up": "trending-up",
    "arrow-path": "refresh-cw", "map-pin": "map-pin", "calendar-days": "calendar-days", "user-plus": "user-plus",
    "users": "users", "user": "user", "home-modern": "house", "shopping-cart": "shopping-cart", "truck": "truck",
    "credit-card": "credit-card", "gift": "gift", "megaphone": "megaphone", "ticket": "ticket", "star": "star",
    "bell": "bell", "bell-alert": "bell-ring", "bookmark": "bookmark", "book-open": "book-open", "folder": "folder",
    "folder-open": "folder-open", "inbox-stack": "inbox", "inbox": "inbox", "key": "key", "shield-check": "shield-check",
    "server": "server", "server-stack": "server", "sparkles": "sparkles", "wallet": "wallet", "scale": "scale",
    "film": "film", "flag": "flag", "funnel": "funnel", "link": "link", "phone": "phone", "pencil": "pencil",
    "queue-list": "list", "newspaper": "newspaper", "briefcase": "briefcase", "calculator": "calculator",
    "clock": "clock", "command-line": "terminal", "computer-desktop": "monitor", "device-phone-mobile": "smartphone",
    "document-duplicate": "files", "document-chart-bar": "file-chart-column", "face-smile": "smile",
    "fire": "flame", "hand-thumb-up": "thumbs-up", "heart": "heart", "lifebuoy": "life-buoy", "map": "map",
    "moon": "moon", "sun": "sun", "printer": "printer", "qr-code": "qr-code", "rocket-launch": "rocket",
    "rss": "rss", "scissors": "scissors", "signal": "signal", "square-3-stack-3d": "layers", "swatch": "palette",
    "trophy": "trophy", "tv": "tv", "variable": "variable", "wifi": "wifi", "window": "app-window",
    "adjustments-horizontal": "sliders-horizontal", "adjustments-vertical": "sliders-vertical",
    "cog": "settings", "cog-6-tooth": "settings", "cog-8-tooth": "settings", "user-group": "users",
    "shopping-bag": "shopping-bag", "home": "house", "chart-bar": "chart-column", "document-arrow-down": "file-down",
}


def icon_name(value: str | None) -> str | None:
    """A Lucide icon name Tungsten draws for a Heroicon name (``heroicon-o-users`` -> ``users``)."""
    if not value:
        return None
    from tungsten.support.icons import exists, normalize

    name = value
    for prefix in ("heroicon-o-", "heroicon-s-", "heroicon-m-", "heroicon-c-", "lucide-", "heroicons-"):
        name = name.removeprefix(prefix)
    m = re.match(r"^(Outlined|Solid|Mini|Micro)?([A-Z].*)$", value)
    if m and "-" not in value:  # Heroicon::OutlinedShoppingBag (Filament 4)
        name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Za-z])(?=[0-9])", "-", m.group(2)).lower()
    if name in HEROICON_TO_LUCIDE and exists(HEROICON_TO_LUCIDE[name]):
        return HEROICON_TO_LUCIDE[name]
    if exists(name):
        return normalize(name)
    return "file-text"


# ------------------------------------------------------------------ values
def py_value(node: Node | None, ctx: Ctx, allow_closure: bool = True) -> str | None:
    """The Python source for a PHP argument, or ``None`` when it cannot be carried over."""
    if node is None:
        return None
    if isinstance(node, (Str, Num)):
        return repr(node.value)
    if isinstance(node, Const):
        low = node.name.lower()
        return {"true": "True", "false": "False", "null": "None"}.get(low)
    if isinstance(node, Arr):
        if all(k is None for k, _ in node.items):
            parts = [py_value(v, ctx, allow_closure) for _, v in node.items]
            return None if any(p is None for p in parts) else "[" + ", ".join(parts) + "]"
        parts = []
        for k, v in node.items:
            kk = py_value(k, ctx, False) if k is not None else None
            vv = py_value(v, ctx, allow_closure)
            if kk is None or vv is None:
                return None
            parts.append(f"{kk}: {vv}")
        return "{" + ", ".join(parts) + "}"
    if isinstance(node, Call) and node.func.lower() in ("__", "trans", "_") and node.args:
        return py_value(node.args[0].value, ctx, False)
    if isinstance(node, ClassConst):
        cls = short(ctx.resolve(node.cls))
        if node.name == "class":
            if cls in ctx.project.enums:
                ctx.imports.add("..models", cls)
                return cls
            return None
        if cls in FILAMENT_ENUM_VALUES:
            return repr(FILAMENT_ENUM_VALUES[cls].get(node.name, snake(node.name)))
        if cls in ("Color",):  # Filament\Support\Colors\Color::Amber
            return repr(node.name.lower())
        if cls == "Heroicon":
            return repr(icon_name(node.name))
        value = ctx.enum_value(node.cls, node.name)
        return None if value is None else repr(value)
    if isinstance(node, Prop) and isinstance(node.obj, ClassConst) and node.name == "value":
        return py_value(node.obj, ctx)
    if isinstance(node, Closure) and allow_closure:
        out = closures.translate(node, ctx.enum_value)
        if out is None:
            return None
        code, uses = out
        if "datetime" in uses:
            ctx.imports.plain.add("import datetime as dt")
        if "random" in uses:
            ctx.imports.plain.add("import random")
        if "slug" in uses:
            ctx.imports.add("tungsten_filament.runtime", "slug")
        return code
    return None


def _now_value(node: Node | None, ctx: Ctx) -> str | None:
    """``now()``, ``today()`` and ``auth()->id()`` defaults become lambdas."""
    if isinstance(node, Call) and node.func.lower() in ("now", "today") and not node.args:
        ctx.imports.plain.add("import datetime as dt")
        return "dt.datetime.now" if node.func.lower() == "now" else "dt.date.today"
    is_auth = isinstance(node, MethodCall) and (
        (isinstance(node.obj, Call) and node.obj.func.lower() == "auth")
        or (isinstance(node.obj, StaticCall) and node.obj.cls.endswith("Auth")))
    if is_auth and node.method == "id":
        return "lambda user: user.id if user else None"
    return None


def php_date_format(fmt: str) -> str:
    table = {"d": "%d", "j": "%-d", "D": "%a", "l": "%A", "N": "%u", "w": "%w", "z": "%j", "W": "%W", "F": "%B",
             "M": "%b", "m": "%m", "n": "%-m", "Y": "%Y", "y": "%y", "a": "%p", "A": "%p", "g": "%-I", "G": "%-H",
             "h": "%I", "H": "%H", "i": "%M", "s": "%S", "T": "%Z", "e": "%Z", "U": "%s"}
    out, i = [], 0
    while i < len(fmt):
        c = fmt[i]
        if c == "\\" and i + 1 < len(fmt):
            out.append(fmt[i + 1])
            i += 2
            continue
        out.append(table.get(c, c.replace("%", "%%")))
        i += 1
    return "".join(out)


# ------------------------------------------------------------------ rendering helpers
def indent(text: str, by: str = "    ") -> str:
    return "\n".join(by + line if line else line for line in text.split("\n"))


@dataclass
class Item:
    code: str | None
    notes: list[str] = field(default_factory=list)


def render_list(items: list[Item]) -> str:
    if not items:
        return "[]"
    lines = []
    for item in items:
        lines.extend(item.notes)
        if item.code is not None:
            lines.append(item.code + ",")
    if not any(i.code for i in items):
        return "[\n" + indent("\n".join(lines)) + "\n]"
    return "[\n" + indent("\n".join(lines)) + "\n]"


def _signature_ok(cls: Any, method: str, args: list[str], kwargs: dict[str, str]) -> bool:
    fn = getattr(cls, method, None)
    if fn is None and getattr(cls, "column_class", None) is not None:  # infolist entry -> its column
        fn = getattr(cls.column_class, method, None)
    if fn is None or not callable(fn):
        return False
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return True
    try:
        sig.bind(None, *args, **kwargs)
    except TypeError:
        return False
    return True


def _has(cls: Any, method: str) -> bool:
    if method.startswith("_"):
        return False
    column_class = getattr(cls, "column_class", None)
    if column_class is not None and any("__getattr__" in k.__dict__ for k in cls.__mro__[:-1]):
        # an infolist entry passes column methods on to its column
        return method in dir(cls) or hasattr(column_class, method)
    return hasattr(cls, method)


def _make_name(base: StaticCall, ctx: Ctx) -> tuple[str | None, list[Arg]]:
    name = None
    rest = list(base.args)
    for i, a in enumerate(base.args):
        if a.name in (None, "name", "label", "heading", "columns", "id") and isinstance(a.value, (Str, Num, Call)):
            v = py_value(a.value, ctx, False)
            if v is not None:
                name = v
                rest = base.args[:i] + base.args[i + 1:]
                break
    return name, rest


# ------------------------------------------------------------------ converter
class Converter:
    """Convert one Filament class's form/table/infolist into Tungsten code."""

    def __init__(self, ctx: Ctx) -> None:
        self.ctx = ctx
        self._calls: list[MethodCall] = []

    # ---- lists
    def items(self, node: Node | None, kind: str) -> list[Item]:
        if isinstance(node, Arr):
            out = []
            for _, value in node.items:
                out.extend(self.item(value, kind))
            return out
        if node is None:
            return []
        return self.item(node, kind)

    def item(self, node: Node, kind: str) -> list[Item]:
        ctx = self.ctx
        base, calls = chain(node)
        if isinstance(base, StaticCall) and base.method == "make":
            fil = short(ctx.resolve(base.cls))
            if kind == "action" and fil in BULK:
                kind = "bulk"
            # a BulkActionGroup's actions flatten into bulk_actions for Filament 2 style groups
            return [self.component(fil, base, calls, kind, node)]
        if isinstance(base, StaticCall) and base.method in ("configure", "schema", "components", "getFormSchema"):
            # MyForm::schema() style reuse of a static helper: inline it when we can find it
            inlined = self.inline_helper(base)
            if inlined is not None:
                return self.items(inlined, kind)
        if isinstance(base, New):
            return [Item(None, [ctx.todo(node, "`new` object not converted").comment()])]
        return [Item(None, [ctx.todo(node, "not converted (not a Filament component call)").comment()])]

    def missing_relation(self, name: str | None, calls: list[MethodCall], kind: str) -> str | None:
        """The relation a component names (``company.name``, ``->relationship('company')``) when the model lacks it."""
        names = []
        if kind in ("column", "entry") and name and name[:1] in "'\"" and "." in name:
            names.append(name.strip("'\"").split(".", 1)[0])
        for c in calls:
            if c.method == "relationship" and c.args:
                rel = next((a.value for a in c.args if a.name == "name"), c.args[0].value)
                if isinstance(rel, Str):
                    names.append(rel.value)
        return next((n for n in names if not self.ctx.has_relation(n)), None)

    def inline_helper(self, call: StaticCall) -> Node | None:
        cls = self.ctx.project.classes.get(short(self.ctx.resolve(call.cls)))
        if cls is None:
            return None
        rets = cls.returns(call.method)
        if not rets:
            return None
        node = rets[0]
        base, calls = chain(node)
        if isinstance(base, Var) and calls and calls[0].method in ("schema", "components", "columns") and calls[0].args:
            return calls[0].args[0].value
        return node if isinstance(node, Arr) else None

    # ---- one component
    def component(self, fil: str, base: StaticCall, calls: list[MethodCall], kind: str, node: Node) -> Item:
        ctx = self.ctx
        notes: list[str] = []
        spec = self.lookup(fil, kind)
        if spec is None:
            reason = ACTION_NOTES.get(fil) if kind in ("action", "bulk", "header") else None
            reason = reason or f"Filament {fil} has no Tungsten match"
            if kind in ("action", "bulk", "header") and fil == "Action":
                name = _make_name(base, ctx)[0]
                reason = f"custom action {name or ''} not converted: rebuild it with tungsten.actions.Action".replace("  ", " ")
            return Item(None, [ctx.todo(node, reason).comment()])
        module, py = spec
        cls = tw(module, py)
        ctx.imports.add(module, py)
        if fil in FIELD_NOTES:
            notes.append(ctx.todo(node, FIELD_NOTES[fil]).comment())

        # constructor
        name, _ = _make_name(base, ctx)
        missing = self.missing_relation(name, calls, kind)
        if missing:
            # code naming a relation the model lacks fails at runtime (a 500 on the list page): leave it out
            return Item(None, [ctx.todo(node, f"{fil} uses relation `{missing}`, which {ctx.model} does not have in "
                                              f"models.py: add the relation there, then add this back").comment()])
        layout = py in FORM_LAYOUTS.values() and kind in ("form", "entry")
        ctor_args: list[str] = []
        children_from_make: Node | None = None
        if py in ("ActionGroup", "BulkActionGroup"):
            arr = base.args[0].value if base.args else None
            child_kind = "bulk" if py == "BulkActionGroup" else "action"
            head = f"{py}(" + render_list(self.items(arr, child_kind)) + ")"
        else:
            if py == "Grid" and fil in ("Split", "Flex"):
                arr = base.args[0].value if base.args else None
                children_from_make = arr
                name = str(max(2, len(arr.items))) if isinstance(arr, Arr) else "2"
            elif fil == "Grid" and name is None and base.args:
                cols = self._responsive(base.args[0].value)
                if cols is not None:
                    name = str(cols)
            elif fil in ("Section", "Fieldset", "Card") and base.args and isinstance(base.args[0].value, Arr):
                children_from_make = base.args[0].value
            if name is not None:
                ctor_args.append(name)
            elif py in ("Tab", "Step"):
                ctor_args.append('""')
            elif not layout and py not in ACTIONS.values() and py not in ("TrashedFilter",) and \
                    module != "tungsten.tables" and py not in SUMMARIZERS.values():
                return Item(None, [ctx.todo(node, f"{fil} without a field name").comment()])
            elif module == "tungsten.tables" and py not in ("TrashedFilter",) and kind in ("column", "filter") \
                    and name is None:
                return Item(None, [ctx.todo(node, f"{fil} without a column name").comment()])
            head = f"{py}({', '.join(ctor_args)})"
        if fil in COLUMN_EXTRA and kind == "column":
            head += COLUMN_EXTRA[fil]
        enum_parts: list[str] = []
        enum = self.enum_for(name) if kind in ("column", "entry") and py in ("TextColumn", "TextEntry") else None
        if enum is not None:
            ctx.imports.add("..models", enum.name)
            if enum.labels and not any(c.method == "formatStateUsing" for c in calls):
                enum_parts.append(f".format_state_using(lambda state: {enum.name}(state).label() "
                                  f"if state in {enum.name}._value2member_map_ else state)")
            if enum.colors and not any(c.method in ("color", "colors") for c in calls):
                enum_parts.append(
                    f'.color(lambda state: {enum.name}.colors().get(getattr(state, "value", state), "gray"))')
        if fil == "MarkdownEditor":
            head += ".rows(10)" if _has(cls, "rows") else ""

        parts = [head] + enum_parts
        if children_from_make is not None:
            parts.append(".schema(" + render_list(self.items(children_from_make, "form" if kind == "form" else kind)) + ")")
        empty_state: dict[str, str] = {}
        self._calls = calls
        # Filament's disabled()->dehydrated(): shown locked but still saved. A disabled input is not
        # sent by the browser, so text-like fields become read-only inputs instead.
        flags = {c.method: c for c in calls if c.method in ("disabled", "dehydrated") and
                 (not c.args or (isinstance(c.args[0].value, Const) and c.args[0].value.name.lower() == "true"))}
        if len(flags) == 2 and py in ("TextInput", "Textarea", "DatePicker", "DateTimePicker", "TimePicker",
                                      "ColorPicker", "TagsInput"):
            calls = [c for c in calls if c not in flags.values()]
            parts.append(".extra_attributes({'readonly': True})")
        for call in calls:
            piece = self.call(fil, py, cls, call, kind, notes, empty_state)
            if piece and piece not in parts:
                parts.append(piece)
        if py == "Filter" and not any(p.startswith(".query(") for p in parts):
            # a filter without its query would show up and do nothing: leave it out
            query = next((c for c in calls if c.method == "query"), None)
            notes.append(ctx.todo(query or node, f"filter {name} left out: write its query by hand as "
                                                 ".query(lambda query, data, model: ...)").comment())
            return Item(None, notes)
        return Item(self.join(parts), notes)

    def enum_for(self, name: str | None) -> Any:
        """The PHP enum a model column is cast to (``'status' => OrderStatus::class``)."""
        if not name or not self.ctx.model:
            return None
        model = self.ctx.project.models.get(self.ctx.model)
        column = name.strip("'\"")
        if model is None or "." in column:
            return None
        cast = model.casts.get(column, "")
        return self.ctx.project.enums.get(cast[5:]) if cast.startswith("enum:") else None

    def lookup(self, fil: str, kind: str) -> tuple[str, str] | None:
        if kind == "form":
            if fil in FORM_FIELDS:
                py = FORM_FIELDS[fil]
                return ("tungsten.forms", py) if py else None
            if fil in FORM_LAYOUTS:
                return "tungsten.forms", FORM_LAYOUTS[fil]
            return None
        if kind == "entry":
            if fil in ENTRIES:
                return "tungsten.infolists", ENTRIES[fil]
            if fil in FORM_LAYOUTS:
                return "tungsten.forms", FORM_LAYOUTS[fil]
            return None
        if kind == "column":
            py = COLUMNS.get(fil)
            return ("tungsten.tables", py) if py else None
        if kind == "filter":
            py = FILTERS.get(fil)
            return ("tungsten.tables", py) if py else None
        if kind in ("action", "bulk", "header"):
            py = ACTIONS.get(fil)
            return ("tungsten.actions", py) if py else None
        if kind == "summarizer":
            py = SUMMARIZERS.get(fil)
            return ("tungsten.tables", py) if py else None
        return None

    @staticmethod
    def join(parts: list[str]) -> str:
        one = "".join(parts)
        if "\n" not in one and len(one) <= 100:
            return one
        out = parts[0]
        for p in parts[1:]:
            out += "\n" + indent(p) if ("\n" in p or len(out.split("\n")[-1]) + len(p) > 100) else p
        return out

    def _responsive(self, node: Node | None) -> int | None:
        if isinstance(node, Num) and isinstance(node.value, int):
            return node.value
        if isinstance(node, Arr) and is_literal(node):
            value = literal(node)
            if isinstance(value, dict):
                for key in ("lg", "md", "xl", "default", "sm"):
                    if isinstance(value.get(key), int):
                        return value[key]
        if isinstance(node, Str) and node.value == "full":
            return None
        return None

    # ---- one method call
    def call(self, fil: str, py: str, cls: Any, call: MethodCall, kind: str, notes: list[str],
             empty_state: dict[str, str]) -> str | None:
        ctx = self.ctx
        m = call.method
        args = call.args

        def skip(reason: str) -> None:
            notes.append(ctx.todo(call_node, reason).comment())

        call_node = Raw(src="->" + m + "(" + ", ".join(a.src for a in args) + ")", line=call.line)

        # children
        if m in ("schema", "components") and kind in ("form", "entry"):
            arr = args[0].value if args else None
            if isinstance(arr, Closure):
                skip("children built by a closure")
                return None
            child_kind = kind
            return ".schema(" + render_list(self.items(arr, child_kind)) + ")"
        if m in ("tabs", "steps") and py in ("Tabs", "Wizard"):
            arr = args[0].value if args else None
            return f".{m}(" + render_list(self.items(arr, kind)) + ")"
        if m == "blocks" and py == "Builder":
            arr = args[0].value if args else None
            return ".blocks(" + render_list(self.items(arr, "form")) + ")"
        if m in ("summarize",) and kind == "column":
            node = args[0].value if args else None
            items = self.items(node, "summarizer")
            codes = [i.code for i in items if i.code]
            for i in items:
                notes.extend(i.notes)
            if not codes:
                return None
            return f".summarize({codes[0]})" if not isinstance(node, Arr) else ".summarize([" + ", ".join(codes) + "])"
        if m in ("actions",) and kind in ("action", "bulk") and py in ("ActionGroup", "BulkActionGroup"):
            return None

        # fixed translations
        if m == "columnSpanFull":
            return '.column_span("full")' if _has(cls, "column_span") else None
        if m == "columnSpan" and args:
            v = args[0].value
            if isinstance(v, Str) and v.value == "full":
                return '.column_span("full")'
            n = self._responsive(v)
            if n is not None:
                return f".column_span({n})"
        if m == "columns" and args and kind in ("form", "entry"):
            n = self._responsive(args[0].value)
            if n is not None and _has(cls, "columns"):
                return f".columns({n})"
        if m in ("reactive",):
            return ".live()"
        if m == "lazy":
            return ".live(on_blur=True)"
        if m in ("hiddenOn", "visibleOn", "disabledOn") and args:
            ops = literal(args[0].value) if is_literal(args[0].value) else None
            if ops is None:
                skip(f"{m} with a page class")
                return None
            ops = ops if isinstance(ops, list) else [ops]
            target = {"hiddenOn": "hidden", "visibleOn": "visible", "disabledOn": "disabled"}[m]
            test = f'operation == {ops[0]!r}' if len(ops) == 1 else f"operation in {tuple(ops)!r}"
            return f".{target}(lambda operation: {test})"
        if m == "default" and args:
            special = _now_value(args[0].value, ctx)
            if special:
                return f".default({special})"
        if m in ("dateTime", "date", "time") and kind in ("column", "entry"):
            target = {"dateTime": "datetime", "date": "date", "time": "time"}[m]
            if not _has(cls, target):
                if m == "time":
                    return '.datetime("%H:%M")' if _has(cls, "datetime") else None
                skip(f"{m}() not on {py}")
                return None
            fmt = args[0].value if args else None
            if isinstance(fmt, Str):
                return f".{target}({php_date_format(fmt.value)!r})"
            return f".{target}()"
        if m == "money" and kind in ("column", "entry"):
            cur = args[0].value if args and args[0].name in (None, "currency") else None
            code = (cur.value.upper() if isinstance(cur, Str) else "USD")
            extra = ""
            for a in args:
                if a.name == "divideBy" and isinstance(a.value, Num):
                    extra = f", divide_by={a.value.value}"
            return f".money({code!r}{extra})"
        if m in ("rules", "rule") and args and kind == "form":
            return self.laravel_rules(args[0].value, cls, notes, call_node, numeric="numeric" in "".join(
                c.method for c in self._calls) or "integer" in "".join(c.method for c in self._calls))
        if m == "orderColumn" and py == "Repeater":
            return None  # folded into relationship()
        if m == "options" and args and not isinstance(args[0].value, (Arr, ClassConst, Closure)):
            lam = self.pluck(args[0].value)
            if lam is not None:
                return f".options({lam})"
        if m == "options" and args and isinstance(args[0].value, ClassConst) and args[0].value.name == "class":
            enum = short(ctx.resolve(args[0].value.cls))
            if enum in ctx.project.enums:
                ctx.imports.add("..models", enum)
                return f".options({enum})"
        if m == "relationship" and py in ("Select", "CheckboxList", "Radio", "ToggleButtons", "SelectFilter"):
            rel = args[0].value if args else None
            title = None
            extra = []
            positional = [a for a in args if a.name is None]
            for a in args:
                if a.name == "name":
                    rel = a.value
                elif a.name == "titleAttribute" or (a.name is None and len(positional) > 1 and a is positional[1]):
                    title = a.value
                elif a.name in ("modifyQueryUsing",) or (a.name is None and len(positional) > 2 and a is positional[2]):
                    extra.append(a)
            if not isinstance(rel, Str):
                skip("relationship name is not plain text")
                return None
            if title is None and py == "SelectFilter":
                title = Str(value="name")
                notes.append(ctx.todo(call_node, "relationship filter without a title column: used `name`").comment())
            if extra:
                skip("relationship query change (modifyQueryUsing) not converted")
            title_py = py_value(title, ctx, False) if title is not None else None
            return f".relationship({rel.value!r}" + (f", {title_py}" if title_py else "") + ")"
        if m == "relationship" and py in ("Repeater", "Builder"):
            rel = args[0].value if args else None
            order = next((c.args[0].value for c in self._calls if c.method == "orderColumn" and c.args), None)
            out = [py_value(rel, ctx, False)] if isinstance(rel, Str) else []
            if isinstance(order, Str) and py == "Repeater":
                out.append(f"order_column={order.value!r}")
            return ".relationship(" + ", ".join(out) + ")"
        if m == "unique" and kind == "form":
            kwargs = []
            for a in args:
                if a.name in ("column",) and isinstance(a.value, Str):
                    kwargs.append(f"column={a.value.value!r}")
                elif a.name in ("ignoreRecord",):
                    pass
                elif a.name is None and isinstance(a.value, Str) and "column=" not in "".join(kwargs) and \
                        a is not args[0]:
                    kwargs.append(f"column={a.value.value!r}")
                elif a.name == "table" or (a.name is None and a is args[0]):
                    pass
                elif a.name == "modifyRuleUsing" or isinstance(a.value, Closure):
                    skip("unique rule change (modifyRuleUsing) not converted")
            return ".unique(" + ", ".join(kwargs) + ")"
        if m == "query" and py == "Filter":
            lam = self.filter_query(args[0].value if args else None)
            if lam is None:
                return None
            return f".query({lam})"
        if m in ("toggle", "checkbox") and py == "Filter":
            return None
        if m == "form" and py == "Filter":
            skip("filter form not converted")
            return None
        if m in ("emptyStateHeading", "emptyStateDescription", "emptyStateIcon"):
            return None
        if m in ("weight", "size", "alignment", "iconPosition") and args and isinstance(args[0].value, ClassConst):
            v = py_value(args[0].value, ctx)
            target = snake(m)
            if v and _has(cls, target):
                return f".{target}({v})"
        if m == "color" and args and isinstance(args[0].value, ClassConst):
            cc = args[0].value
            if short(ctx.resolve(cc.cls)) == "Color":
                return f".color({cc.name.lower()!r})" if _has(cls, "color") else None
        if m in ("icon", "prefixIcon", "suffixIcon", "trueIcon", "falseIcon", "onIcon", "offIcon",
                 "activeIcon") and args:
            v = args[0].value
            if isinstance(v, (Str, ClassConst)):
                raw = v.value if isinstance(v, Str) else v.name
                target = RENAMES.get(m) or snake(m)
                if _has(cls, target):
                    return f".{target}({icon_name(raw)!r})"
        if m in ("label", "heading", "description", "placeholder", "helperText", "hint", "tooltip") and args and \
                isinstance(args[0].value, Call) and args[0].value.func in ("__", "trans"):
            target = snake(m)
            v = py_value(args[0].value, ctx)
            if v and _has(cls, target):
                return f".{target}({v})"

        # generic: same method in snake_case
        target = RENAMES.get(m, snake(m)) if m in RENAMES else snake(m)
        if target is None:
            skip(f"{m}() has no Tungsten match")
            return None
        if keyword.iskeyword(target) or not _has(cls, target):
            if m not in COSMETIC:
                skip(f"{m}() is not available on Tungsten {py}")
            return None
        pos, kw = [], {}
        for a in args:
            v = py_value(a.value, ctx)
            if v is None and m in ("minDate", "maxDate", "default"):
                v = _now_value(a.value, ctx)
            if v is None:
                what = "closure" if isinstance(a.value, Closure) else "value"
                skip(f"{m}() uses a {what} that was not converted")
                return None
            if a.name:
                key = RENAMES.get(a.name) or snake(a.name)
                kw[key] = v
            else:
                pos.append(v)
        if not _signature_ok(cls, target, pos, kw):
            if kw and _signature_ok(cls, target, pos, {}):
                notes.append(ctx.todo(call_node, f"{m}() options {', '.join(kw)} dropped").comment())
                kw = {}
            else:
                skip(f"{m}() arguments do not fit Tungsten {py}.{target}()")
                return None
        rendered = ", ".join(pos + [f"{k}={v}" for k, v in kw.items()])
        return f".{target}({rendered})"

    # ---- Laravel validation rules: ->rules(['integer', 'min:0'])
    def laravel_rules(self, node: Node, cls: Any, notes: list[str], call_node: Node, numeric: bool) -> str | None:
        ctx = self.ctx
        if isinstance(node, Str):
            rules = node.value.split("|")
        elif isinstance(node, Arr) and is_literal(node) and all(isinstance(v, str) for v in literal(node)):
            rules = [r for v in literal(node) for r in v.split("|")]
        else:
            notes.append(ctx.todo(call_node, "validation rule objects not converted: use .rule(lambda value: ...)").comment())
            return None
        numeric = numeric or any(r in ("integer", "numeric", "decimal") for r in rules)
        out = []
        for rule in rules:
            name, _, arg = rule.partition(":")
            params = arg.split(",") if arg else []
            if name in ("nullable", "string", "sometimes", "present", "bail", "array"):
                continue
            if name == "required":
                if not any(c.method == "required" for c in self._calls):
                    out.append(".required()")
            elif name == "integer" and _has(cls, "integer"):
                out.append(".integer()")
            elif name == "numeric" and _has(cls, "numeric"):
                out.append(".numeric()")
            elif name in ("email", "url") and _has(cls, name):
                out.append(f".{name}()")
            elif name in ("min", "max") and params and re.fullmatch(r"-?\d+(\.\d+)?", params[0]):
                target = f"{name}_value" if numeric else f"{name}_length"
                if _has(cls, target):
                    out.append(f".{target}({params[0]})")
            elif name == "in" and params:
                out.append(f".rule(lambda value: not value or value in {params!r}, 'Pick one of: {', '.join(params)}')")
            elif name == "digits" and params and params[0].isdigit():
                out.append(f".regex(r'^\\d{{{params[0]}}}$')")
            elif name == "alpha_dash":
                out.append(".regex(r'^[A-Za-z0-9_-]+$')")
            elif name == "alpha_num":
                out.append(".regex(r'^[A-Za-z0-9]+$')")
            elif name == "regex" and arg:
                pattern = arg.strip()
                if len(pattern) > 2 and pattern[0] == pattern[-1] == "/":
                    out.append(f".regex({pattern[1:-1]!r})")
                else:
                    notes.append(ctx.todo(call_node, f"rule `{rule}` not converted").comment())
            else:
                notes.append(ctx.todo(call_node, f"rule `{rule}` not converted").comment())
        return "".join(out) or None

    # ---- options: Product::query()->pluck('name', 'id')
    def pluck(self, node: Node) -> str | None:
        base, calls = chain(node)
        if not isinstance(base, StaticCall) or not calls or calls[-1].method != "pluck":
            return None
        model = short(self.ctx.resolve(base.cls))
        if model not in self.ctx.project.models:
            return None
        middle = ([MethodCall(method=base.method, args=base.args)] if base.method not in ("query", "all") else []) \
            + calls[:-1]
        conds = []
        for c in middle:
            if c.method in ("query", "all", "get"):
                continue
            vals = [py_value(a.value, self.ctx, False) for a in c.args]
            col = c.args[0].value if c.args else None
            if c.method == "where" and len(vals) == 2 and isinstance(col, Str) and vals[1] is not None:
                conds.append(f"{model}.{col.value} == {vals[1]}")
            elif c.method == "orderBy" and isinstance(col, Str):
                continue
            else:
                return None
        args = calls[-1].args
        label = args[0].value if args else None
        key = args[1].value if len(args) > 1 else Str(value="id")
        if not isinstance(label, Str) or not isinstance(key, Str):
            return None
        self.ctx.imports.add("sqlalchemy", "select")
        self.ctx.imports.add("..models", model)
        query = f"select({model})" + (f".where({', '.join(conds)})" if conds else "") + \
            f".order_by({model}.{label.value})"
        return f"lambda db: {{r.{key.value}: r.{label.value} for r in db.scalars({query})}}"

    # ---- filter queries: $query->where('is_featured', true)
    def filter_query(self, node: Node | None) -> str | None:
        if not isinstance(node, Closure):
            return None
        src = node.src
        m = re.search(r"=>\s*(.*)$", src, re.DOTALL) if src.lstrip().startswith(("fn", "static fn")) else \
            re.search(r"\{\s*return\s+(.*);\s*\}\s*$", src, re.DOTALL)
        if not m:
            return None
        from .php import parse_expr

        expr = parse_expr(m.group(1).strip().rstrip(";"))
        base, calls = chain(expr)
        if not isinstance(base, Var) or base.name != "query" or not calls:
            return None
        conds = []
        for c in calls:
            vals = [py_value(a.value, self.ctx, False) for a in c.args]
            col = c.args[0].value if c.args else None
            if not isinstance(col, Str) or "." in col.value or any(v is None for v in vals):
                return None
            attr = f"model.{col.value}"
            name = c.method
            if name == "where" and len(vals) == 2:
                conds.append(f"{attr} == {vals[1]}")
            elif name == "where" and len(vals) == 3 and c.args[1].value and isinstance(c.args[1].value, Str):
                op = {"=": "==", "<>": "!=", "!=": "!=", ">": ">", "<": "<", ">=": ">=", "<=": "<="}.get(
                    c.args[1].value.value)
                if op is None:
                    if c.args[1].value.value.lower() == "like":
                        conds.append(f"{attr}.like({vals[2]})")
                        continue
                    return None
                conds.append(f"{attr} {op} {vals[2]}")
            elif name == "whereNull" and len(vals) == 1:
                conds.append(f"{attr}.is_(None)")
            elif name == "whereNotNull" and len(vals) == 1:
                conds.append(f"{attr}.is_not(None)")
            elif name == "whereIn" and len(vals) == 2:
                conds.append(f"{attr}.in_({vals[1]})")
            elif name == "whereNotIn" and len(vals) == 2:
                conds.append(f"{attr}.not_in({vals[1]})")
            else:
                return None
        return "lambda query, model: query.where(" + ", ".join(conds) + ")"

    # ---- whole form / table / infolist
    def form(self, node: Node | None, arg: str = "form", kind: str = "form") -> str | None:
        if node is None:
            return None
        base, calls = chain(node)
        if not isinstance(base, Var) or not calls:
            if isinstance(node, Arr):  # v2: return $form->schema(static::getFormSchema())
                return f"{arg}.schema(" + render_list(self.items(node, kind)) + ")"
            return None
        parts = [arg]
        for c in calls:
            if c.method in ("schema", "components"):
                value = c.args[0].value if c.args else None
                if isinstance(value, StaticCall):
                    inlined = self.inline_helper(value)
                    value = inlined if inlined is not None else value
                parts.append(".schema(" + render_list(self.items(value, kind)) + ")")
            elif c.method == "columns" and c.args:
                n = self._responsive(c.args[0].value)
                if n is not None:
                    parts.append(f".columns({n})")
            elif c.method in ("statePath", "model", "operation", "inlineLabel", "disabled"):
                if c.method == "disabled":
                    parts.append(".disabled()")
            else:
                self.ctx.todo(Raw(src=c.src, line=c.line), f"{arg}->{c.method}() not converted")
        return "".join(parts[:1]) + "".join(parts[1:])

    def table(self, node: Node | None) -> str | None:
        if node is None:
            return None
        base, calls = chain(node)
        if not isinstance(base, Var) or not calls:
            return None
        ctx = self.ctx
        lines: list[str] = []
        notes: list[str] = []
        empty: dict[str, str] = {}
        table_cls = _tungsten_table()
        for c in calls:
            m = c.method
            arg = c.args[0].value if c.args else None
            if m == "columns":
                lines.append(".columns(" + render_list(self.items(arg, "column")) + ")")
            elif m == "filters":
                items = self.items(arg, "filter")
                layout = next((a.value for a in c.args[1:] if a.name in (None, "layout")), None)
                extra = ""
                if isinstance(layout, ClassConst):
                    v = FILAMENT_ENUM_VALUES["FiltersLayout"].get(layout.name)
                    if v and _signature_ok(table_cls, "filters", ["[]"], {"layout": repr(v)}):
                        extra = f", layout={v!r}"
                lines.append(".filters(" + render_list(items) + extra + ")")
            elif m in ("actions", "recordActions"):
                lines.append(".actions(" + render_list(self.items(arg, "action")) + ")")
            elif m in ("bulkActions", "groupedBulkActions"):
                lines.append(".bulk_actions(" + render_list(self.items(arg, "bulk")) + ")")
            elif m == "toolbarActions":
                bulk, header = [], []
                for _, v in (arg.items if isinstance(arg, Arr) else []):
                    b, _calls = chain(v)
                    fil = short(ctx.resolve(b.cls)) if isinstance(b, StaticCall) else ""
                    (bulk if fil in BULK else header).append(v)
                if bulk:
                    lines.append(".bulk_actions(" + render_list(
                        [i for v in bulk for i in self.item(v, "bulk")]) + ")")
                if header:
                    lines.append(".header_actions(" + render_list(
                        [i for v in header for i in self.item(v, "header")]) + ")")
            elif m == "headerActions":
                lines.append(".header_actions(" + render_list(self.items(arg, "header")) + ")")
            elif m == "emptyStateActions":
                lines.append(".empty_state_actions(" + render_list(self.items(arg, "header")) + ")")
            elif m == "defaultSort" and c.args:
                col = py_value(arg, ctx, False)
                direction = py_value(c.args[1].value, ctx, False) if len(c.args) > 1 else None
                if col is None:
                    notes.append(ctx.todo(c, "defaultSort with a closure not converted").comment())
                    continue
                lines.append(f".default_sort({col}" + (f", {direction.lower()}" if direction else "") + ")")
            elif m == "paginated":
                v = py_value(arg, ctx, False) if arg is not None else None
                if arg is None or v is not None:
                    lines.append(f".paginated({v or ''})")
            elif m == "striped":
                lines.append(".striped()")
            elif m == "poll":
                v = py_value(arg, ctx, False)
                lines.append(f".poll({v or ''})")
            elif m in ("emptyStateHeading", "emptyStateDescription", "emptyStateIcon"):
                v = py_value(arg, ctx, False)
                if v is not None:
                    key = {"emptyStateHeading": "heading", "emptyStateDescription": "description",
                           "emptyStateIcon": "icon"}[m]
                    empty[key] = repr(icon_name(literal(arg))) if key == "icon" and isinstance(arg, Str) else v
            elif m == "searchPlaceholder":
                v = py_value(arg, ctx, False)
                if v:
                    lines.append(f".search_placeholder({v})")
            elif m == "reorderable":
                v = py_value(arg, ctx, False)
                lines.append(f".reorderable({v or ''})")
            elif m == "defaultGroup":
                v = py_value(arg, ctx, False)
                if v:
                    lines.append(f".default_group({v})")
            elif m == "groups":
                v = py_value(arg, ctx, False)
                if v and v.startswith("[") and all(isinstance(x, str) for x in literal(arg)):
                    lines.append(f".groups({v})")
                else:
                    notes.append(ctx.todo(c, "table groups with Group objects not converted").comment())
            elif m in ("heading", "description"):
                v = py_value(arg, ctx)
                if v and _has(table_cls, m):
                    lines.append(f".{m}({v})")
            elif m == "recordUrl":
                v = py_value(arg, ctx)
                if v and v.startswith("lambda"):
                    lines.append(f".record_url({v})")
                elif isinstance(arg, Const) and arg.name.lower() == "null":
                    lines.append(".record_url(None)")
                else:
                    notes.append(ctx.todo(c, "recordUrl not converted").comment())
            elif m == "modifyQueryUsing":
                notes.append(ctx.todo(c, "table query change not converted: put it in the resource's query()").comment())
            elif m == "searchable" and isinstance(arg, Const) and arg.name.lower() == "false":
                notes.append(ctx.todo(c, "table search turned off in Filament: leave columns unsearchable").comment())
            elif m in COSMETIC or m in ("recordTitleAttribute", "inverseRelationship", "allowDuplicates"):
                continue
            else:
                notes.append(ctx.todo(c, f"table->{m}() not converted").comment())
        if empty:
            lines.append(".empty_state(" + ", ".join(f"{k}={v}" for k, v in empty.items()) + ")")
        if not lines:
            return None
        body = "\n".join(notes + ["table"]) + "".join("\n" + line for line in lines)
        return "(\n" + indent(body) + "\n)"


def _tungsten_table() -> Any:
    from tungsten.tables import Table

    return Table
