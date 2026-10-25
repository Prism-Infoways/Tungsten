"""Content blocks and extra layouts for forms: ``Actions``, ``Text``, ``Html``, ``Icon``,
``Image``, ``UnorderedList``, ``Callout``, ``Flex`` (alias ``Split``), ``FusedGroup`` and
``ViewField``/``View`` for your own templates.

None of the content blocks hold a value; they are skipped when the form is saved.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from markupsafe import Markup

from ..i18n import maybe
from ..support.evaluate import evaluate
from ..support.html import sanitize
from .fields import Field
from .layout import Layout

if TYPE_CHECKING:  # pragma: no cover
    from .form import Form

# Written out in full so the Tailwind build keeps these classes.
CALLOUT = {
    "primary": "bg-primary-50 text-primary-900 ring-primary-600/20 dark:bg-primary-500/10 dark:text-primary-100 dark:ring-primary-400/30",
    "success": "bg-success-50 text-success-900 ring-success-600/20 dark:bg-success-500/10 dark:text-success-100 dark:ring-success-400/30",
    "danger": "bg-danger-50 text-danger-900 ring-danger-600/20 dark:bg-danger-500/10 dark:text-danger-100 dark:ring-danger-400/30",
    "warning": "bg-warning-50 text-warning-900 ring-warning-600/20 dark:bg-warning-500/10 dark:text-warning-100 dark:ring-warning-400/30",
    "info": "bg-info-50 text-info-900 ring-info-600/20 dark:bg-info-500/10 dark:text-info-100 dark:ring-info-400/30",
    "gray": "bg-gray-50 text-gray-900 ring-gray-950/10 dark:bg-white/5 dark:text-gray-100 dark:ring-white/10",
}
CALLOUT_ICONS = {"success": "circle-check", "danger": "circle-x", "warning": "triangle-alert", "info": "info"}
TEXT_SIZES = {"xs": "text-xs", "sm": "text-sm", "md": "text-base", "lg": "text-lg"}
TEXT_WEIGHTS = {"normal": "font-normal", "medium": "font-medium", "semibold": "font-semibold", "bold": "font-bold"}
JUSTIFY = {"start": "justify-start", "center": "justify-center", "end": "justify-end", "between": "justify-between"}
ITEMS = {"start": "md:items-start", "center": "md:items-center", "end": "md:items-end"}
FLEX_FROM = {"sm": "sm:flex-row", "md": "md:flex-row", "lg": "lg:flex-row", "xl": "xl:flex-row"}
ICON_SIZES = {"xs": "h-3.5 w-3.5", "sm": "h-4 w-4", "md": "h-5 w-5", "lg": "h-6 w-6", "xl": "h-8 w-8"}
IMAGE_SIZES = {"xs": "h-8", "sm": "h-12", "md": "h-24", "lg": "h-40", "xl": "h-64", "full": "w-full"}


class Static(Field):
    """A form block that shows something but holds no value. Gets an automatic name."""

    _auto_name = True

    def __init__(self, name: str | None = None) -> None:
        super().__init__(name or "_static")
        self._auto_name = name is None
        self._dehydrated = False
        self._hidden_label = True

    def fill_state(self, form: "Form", base: str, record: Any) -> None:
        return None

    def load_state(self, form: "Form", formdata: Any, base: str) -> None:
        return None

    def process(self, form: "Form", base: str, data: dict, errors: dict) -> None:
        return None

    def fill_record(self, form: "Form", record: Any, data: dict) -> None:
        return None


class Actions(Static):
    """A row of action buttons inside a form::

        Actions([
            Action("fill_address").label("Copy billing address")
                .action(lambda get, set: set("shipping", get("billing"))),
        ]).alignment("end")
    """

    template = "tungsten/forms/components/actions.html"

    def __init__(self, actions: list | None = None, name: str | None = None) -> None:
        super().__init__(name)
        self._actions: list = list(actions or [])
        self._alignment = "start"
        self._full_width = False
        self._column_span = "full"

    def actions(self, actions: list) -> "Actions":
        self._actions = list(actions)
        return self

    def alignment(self, value: str) -> "Actions":
        """start, center, end or between"""
        self._alignment = value
        return self

    def full_width(self, condition: bool = True) -> "Actions":
        self._full_width = condition
        return self

    def form_actions(self, form: "Form", base: str) -> list:
        return [*super().form_actions(form, base), *self._actions]

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        from .actions import render_action

        v = super().view_data(form, base)
        buttons = [render_action(a, form, self, base) for a in self._actions]
        v.update(buttons=[b for b in buttons if b], justify=JUSTIFY.get(self._alignment, JUSTIFY["start"]),
                 full_width=self._full_width)
        return v


class Text(Static):
    """Plain text in a form: ``Text("Prices include GST.").color("gray").size("sm")``."""

    template = "tungsten/forms/components/text.html"

    def __init__(self, content: Any = None, name: str | None = None) -> None:
        super().__init__(name)
        self._content = content
        self._color: Any = None
        self._size = "sm"
        self._weight: str | None = None
        self._icon: Any = None
        self._badge = False
        self._tooltip: Any = None

    def content(self, content: Any) -> "Text":
        self._content = content
        return self

    def color(self, color: Any) -> "Text":
        self._color = color
        return self

    def size(self, size: str) -> "Text":
        """xs, sm, md or lg"""
        self._size = size
        return self

    def weight(self, weight: str) -> "Text":
        """normal, medium, semibold or bold"""
        self._weight = weight
        return self

    def icon(self, icon: Any) -> "Text":
        self._icon = icon
        return self

    def badge(self, condition: bool = True) -> "Text":
        """Show the text as a small colored badge."""
        self._badge = condition
        return self

    def tooltip(self, text: Any) -> "Text":
        self._tooltip = text
        return self

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        v = super().view_data(form, base)
        ev = self.field_ev(form, base)
        v.update(content=maybe(evaluate(self._content, **ev)), color=evaluate(self._color, **ev),
                 size=TEXT_SIZES.get(self._size, "text-sm"), weight=TEXT_WEIGHTS.get(self._weight or "", ""),
                 icon=evaluate(self._icon, **ev), badge=self._badge, tooltip=maybe(evaluate(self._tooltip, **ev)))
        return v


class Html(Static):
    """HTML in a form. A ``Markup`` value (or a closure returning one) is shown as is;
    a plain string is cleaned first, so user data can't add scripts."""

    template = "tungsten/forms/components/html.html"

    def __init__(self, content: Any = None, name: str | None = None) -> None:
        super().__init__(name)
        self._content = content
        self._column_span = "full"

    def content(self, content: Any) -> "Html":
        self._content = content
        return self

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        v = super().view_data(form, base)
        content = evaluate(self._content, **self.field_ev(form, base))
        if content is None:
            content = ""
        v["content"] = content if isinstance(content, Markup) else Markup(sanitize(str(content)))
        return v


class Icon(Static):
    """A Lucide icon on its own: ``Icon("sparkles").color("warning").size("lg").tooltip("New")``."""

    template = "tungsten/forms/components/icon.html"

    def __init__(self, icon: Any = None, name: str | None = None) -> None:
        super().__init__(name)
        self._icon = icon
        self._color: Any = None
        self._size = "md"
        self._tooltip: Any = None
        self._column_span = 1

    def icon(self, icon: Any) -> "Icon":
        self._icon = icon
        return self

    def color(self, color: Any) -> "Icon":
        self._color = color
        return self

    def size(self, size: str) -> "Icon":
        """xs, sm, md, lg or xl"""
        self._size = size
        return self

    def tooltip(self, text: Any) -> "Icon":
        self._tooltip = text
        return self

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        v = super().view_data(form, base)
        ev = self.field_ev(form, base)
        v.update(icon=evaluate(self._icon, **ev), color=evaluate(self._color, **ev),
                 size=ICON_SIZES.get(self._size, ICON_SIZES["md"]), tooltip=maybe(evaluate(self._tooltip, **ev)))
        return v


class Image(Static):
    """A picture in a form or infolist: ``Image("/media/map.png", "Office map").size("lg").rounded()``.

    ``url`` can be a closure (``lambda record: record.cover``). ``.circular()`` makes an avatar.
    """

    template = "tungsten/forms/components/image.html"

    def __init__(self, url: Any = None, alt: Any = None, name: str | None = None) -> None:
        super().__init__(name)
        self._url = url
        self._alt = alt
        self._size = "md"
        self._width: str | None = None
        self._height: str | None = None
        self._rounded = "rounded-xl"
        self._alignment = "start"
        self._tooltip: Any = None
        self._link: Any = None
        self._column_span = "full"

    def url(self, url: Any) -> "Image":
        self._url = url
        return self

    def alt(self, alt: Any) -> "Image":
        self._alt = alt
        return self

    def size(self, size: str) -> "Image":
        """xs, sm, md, lg, xl or full (the height; the width follows)"""
        self._size = size
        return self

    def width(self, value: str) -> "Image":
        """A CSS width like ``"200px"`` or ``"50%"``."""
        self._width = value
        return self

    def height(self, value: str) -> "Image":
        self._height = value
        return self

    def rounded(self, condition: bool = True) -> "Image":
        self._rounded = "rounded-xl" if condition else "rounded-none"
        return self

    def circular(self, condition: bool = True) -> "Image":
        self._rounded = "rounded-full object-cover aspect-square" if condition else "rounded-xl"
        return self

    def alignment(self, value: str) -> "Image":
        """start, center or end"""
        self._alignment = value
        return self

    def tooltip(self, text: Any) -> "Image":
        self._tooltip = text
        return self

    def link(self, url: Any) -> "Image":
        """Open this URL when the picture is clicked."""
        self._link = url
        return self

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        v = super().view_data(form, base)
        ev = self.field_ev(form, base)
        style = ";".join(p for p in (f"width:{self._width}" if self._width else "", f"height:{self._height}" if self._height else "") if p)
        v.update(url=evaluate(self._url, **ev), alt=maybe(evaluate(self._alt, **ev)) or "",
                 size="" if style else IMAGE_SIZES.get(self._size, IMAGE_SIZES["md"]), style=style, rounded=self._rounded,
                 justify=JUSTIFY.get(self._alignment, JUSTIFY["start"]), tooltip=maybe(evaluate(self._tooltip, **ev)),
                 link=evaluate(self._link, **ev))
        return v


class UnorderedList(Static):
    """A bullet list of short lines, each with an optional icon::

        UnorderedList([
            Text("Free shipping").icon("truck"),
            Text("30 day returns").icon("undo"),
            "Secure checkout",
        ]).size("sm")

    Items are strings or :class:`Text` blocks. ``.ordered()`` numbers them instead of bullets.
    """

    template = "tungsten/forms/components/unordered-list.html"

    def __init__(self, items: Any = None, name: str | None = None) -> None:
        super().__init__(name)
        self._items = items
        self._size = "sm"
        self._ordered = False
        self._column_span = "full"

    def items(self, items: Any) -> "UnorderedList":
        """A list, or a closure returning one (``lambda record: [...]``)."""
        self._items = items
        return self

    def schema(self, items: Any) -> "UnorderedList":
        return self.items(items)

    def size(self, size: str) -> "UnorderedList":
        """xs, sm, md or lg"""
        self._size = size
        return self

    def ordered(self, condition: bool = True) -> "UnorderedList":
        self._ordered = condition
        return self

    def form_actions(self, form: "Form", base: str) -> list:
        out = list(super().form_actions(form, base))
        for item in (self._items if isinstance(self._items, (list, tuple)) else []):
            if hasattr(item, "form_actions"):
                out.extend(item.form_actions(form, base))
        return out

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        v = super().view_data(form, base)
        ev = self.field_ev(form, base)
        entries = []
        for item in evaluate(self._items, **ev) or []:
            if isinstance(item, Text):
                if item._size == "sm" and self._size != "sm":
                    item._size = self._size
                html = item.render(form, base)
                if html:
                    entries.append(html)
            else:
                entries.append(Markup('<p class="{size} text-gray-700 dark:text-gray-300">{text}</p>').format(
                    size=TEXT_SIZES.get(self._size, "text-sm"), text=maybe(item)))
        v.update(entries=entries, ordered=self._ordered, size=TEXT_SIZES.get(self._size, "text-sm"))
        return v


class Callout(Static):
    """A colored box with a heading, text, an icon and optional action buttons::

        Callout("Stock is low").description("Only 3 left.").color("warning")
    """

    template = "tungsten/forms/components/callout.html"

    def __init__(self, heading: Any = None, name: str | None = None) -> None:
        super().__init__(name)
        self._heading = heading
        self._description: Any = None
        self._icon: Any = None
        self._color: Any = "info"
        self._actions: list = []
        self._column_span = "full"

    def heading(self, heading: Any) -> "Callout":
        self._heading = heading
        return self

    def description(self, text: Any) -> "Callout":
        self._description = text
        return self

    def icon(self, icon: Any) -> "Callout":
        self._icon = icon
        return self

    def color(self, color: Any) -> "Callout":
        """primary, success, danger, warning, info or gray"""
        self._color = color
        return self

    status = color

    def actions(self, actions: list) -> "Callout":
        self._actions = list(actions)
        return self

    def form_actions(self, form: "Form", base: str) -> list:
        return [*super().form_actions(form, base), *self._actions]

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        from .actions import render_actions

        v = super().view_data(form, base)
        ev = self.field_ev(form, base)
        color = evaluate(self._color, **ev) or "info"
        icon = evaluate(self._icon, **ev)
        v.update(heading=maybe(evaluate(self._heading, **ev)), description=maybe(evaluate(self._description, **ev)),
                 color=color, box=CALLOUT.get(color, CALLOUT["gray"]),
                 icon=icon if icon is not None else CALLOUT_ICONS.get(color),
                 buttons=render_actions(self._actions, form, self, base, size="sm") if self._actions else Markup(""))
        return v


class ViewField(Field):
    """A field drawn by your own Jinja template — the quick way to a custom field::

        ViewField("rating").view("myapp/star-rating.html").default(3)

    The template gets ``form``, ``field`` and ``v`` (``v.path`` is the input name,
    ``v.state`` the value, ``v.errors``, ``v.label`` ...) plus anything passed to
    ``view_data({...})``. Wrap it in the standard label/errors with::

        {% from "tungsten/forms/macros.html" import wrapper %}
        {% call wrapper(field, v) %}<input name="{{ v.path }}" value="{{ v.state }}">{% endcall %}

    For full control, subclass :class:`Field` instead (see the custom fields docs).
    """

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._view: str | None = None
        self._view_data: Any = None

    def view(self, template: str, data: Any = None) -> "ViewField":
        self.template = template
        self._view = template
        if data is not None:
            self._view_data = data
        return self

    def view_data_using(self, data: Any) -> "ViewField":
        """Extra template variables: a dict or a closure (``lambda get, record: {...}``)."""
        self._view_data = data
        return self

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        v = super().view_data(form, base)
        extra = evaluate(self._view_data, **self.field_ev(form, base))
        if extra:
            v.update(extra)
        return v

    def render(self, form: "Form", base: str) -> Markup:
        if self._view is None:
            raise RuntimeError(f"ViewField {self.name!r} needs .view('your/template.html').")
        return super().render(form, base)


class View(Static):
    """Your own template inside a form, without a value: ``View("myapp/notice.html")``."""

    def __init__(self, template: str, data: Any = None, name: str | None = None) -> None:
        super().__init__(name)
        self.template = template
        self._view_data = data
        self._column_span = "full"

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        v = super().view_data(form, base)
        extra = evaluate(self._view_data, **self.field_ev(form, base))
        if extra:
            v.update(extra)
        return v


class Flex(Layout):
    """Put components side by side in a row that sizes itself (Filament's ``Flex``/``Split``).

    A child takes the free space unless it is marked ``.grow(False)``::

        Flex([
            Section("Post").schema([...]),
            Section("Meta").schema([...]).grow(False),
        ]).from_breakpoint("md")
    """

    template = "tungsten/forms/layouts/flex.html"

    def __init__(self, schema: list | None = None) -> None:
        super().__init__(schema)
        self._column_span = "full"
        self._from = "md"
        self._align = "start"
        self._gap = "gap-6"

    def from_breakpoint(self, breakpoint: str) -> "Flex":
        """Below this screen size (sm, md, lg, xl) the children stack."""
        self._from = breakpoint
        return self

    def vertical_alignment(self, value: str) -> "Flex":
        """start, center or end"""
        self._align = value
        return self

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        children = []
        for c in self.child_components():
            html = c.render(form, base)
            if html:
                grow = getattr(c, "_grow", True)
                children.append({"html": html, "grow": grow})
        return {"base": base, "children": children, "row": FLEX_FROM.get(self._from, FLEX_FROM["md"]),
                "items": ITEMS.get(self._align, ITEMS["start"]), "gap": self._gap}


Split = Flex


class FusedGroup(Layout):
    """Join a few fields into one control that shares a border (Filament's ``FusedGroup``)::

        FusedGroup("Address").schema([
            TextInput("street").placeholder("Street"),
            TextInput("city").placeholder("City"),
            Select("country").options(COUNTRIES).placeholder("Country"),
        ]).columns(3)

    The fields' own labels are hidden, so give them placeholders. Text inputs, selects,
    textareas and date pickers fit; the group's own label is shown above once.
    """

    template = "tungsten/forms/layouts/fused-group.html"

    def __init__(self, label: Any = None, schema: list | None = None) -> None:
        super().__init__(schema)
        self._label = label
        self._columns = 1
        self._column_span = 1
        self._helper_text: Any = None

    def label(self, label: Any) -> "FusedGroup":
        self._label = label
        return self

    def helper_text(self, text: Any) -> "FusedGroup":
        self._helper_text = text
        return self

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        ev = form.ev(base)
        children = []
        errors: list[str] = []
        for c in self.child_components():
            if hasattr(c, "_hidden_label"):
                c._hidden_label = True
            html = c.render(form, base)
            if html:
                children.append(html)
            path = c.path(base) if hasattr(c, "path") else None
            if path and form.errors.get(path):
                errors.extend(form.errors[path])
        return {"base": base, "label": maybe(evaluate(self._label, **ev)), "children": children,
                "columns": self._columns if isinstance(self._columns, int) else 1,
                "helper_text": maybe(evaluate(self._helper_text, **ev)), "has_errors": bool(errors),
                "extra": self._extra_attributes}
