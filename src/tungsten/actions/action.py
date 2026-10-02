"""Actions: buttons that run code, open a confirmation box or a modal form."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from markupsafe import Markup

from ..i18n import maybe
from ..i18n import translate as __
from ..support.component import Component, headline
from ..support.evaluate import call, evaluate

if TYPE_CHECKING:  # pragma: no cover
    from ..context import Context
    from ..forms.form import Form
    from ..hosts import Host


class Halt(Exception):
    """Raise inside an action to stop it quietly (the modal stays open)."""


class Action(Component):
    """A button. Examples::

        Action("approve").icon("check").color("success").requires_confirmation()
            .action(lambda record: record.approve())

        Action("email").form([TextInput("subject").required(), Textarea("body")])
            .action(lambda record, data: send_mail(record.email, **data))
    """

    #: where this action lives — set by the host when it is resolved
    scope = "page"
    #: shown as icon buttons in table rows when an icon exists
    default_style = "button"

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self._label: Any = None
        self._icon: Any = None
        self._color: Any = "primary"
        self._url: Any = None
        self._new_tab = False
        self._requires_confirmation = False
        self._modal_heading: Any = None
        self._modal_description: Any = None
        self._modal_submit_label: Any = None
        self._modal_cancel_label: Any = "Cancel"
        self._modal_icon: Any = None
        self._modal_icon_color: Any = None
        self._modal_width = "lg"
        self._slide_over = False
        self._form: Any = None
        self._form_columns = 1
        self._fill_form: Callable | None = None
        self._action: Callable | None = None
        self._success_title: Any = None
        self._success_body: Any = None
        self._failure_title: Any = None
        self._success_redirect: Any = None
        self._disabled: Any = False
        self._tooltip: Any = None
        self._style: str | None = None
        self._size = "md"
        self._badge: Any = None
        self._outlined = False
        self._authorize: Any = None
        self._hidden_label = False
        self._keyboard: str | None = None
        self._refresh_table = True
        self._modal_content: Any = None
        self._deselect_after = True

    # ------------------------------------------------------------------ config
    def label(self, label: Any) -> "Action":
        self._label = label
        return self

    def icon(self, icon: Any) -> "Action":
        self._icon = icon
        return self

    def color(self, color: Any) -> "Action":
        self._color = color
        return self

    def url(self, url: Any, open_in_new_tab: bool = False) -> "Action":
        """Make the action a link. ``url`` may be a closure: ``lambda record: ...``."""
        self._url = url
        self._new_tab = open_in_new_tab
        return self

    def requires_confirmation(self, condition: bool = True) -> "Action":
        self._requires_confirmation = condition
        return self

    def modal_heading(self, text: Any) -> "Action":
        self._modal_heading = text
        return self

    def modal_description(self, text: Any) -> "Action":
        self._modal_description = text
        return self

    def modal_submit_action_label(self, text: Any) -> "Action":
        self._modal_submit_label = text
        return self

    modal_submit_label = modal_submit_action_label

    def modal_cancel_action_label(self, text: Any) -> "Action":
        self._modal_cancel_label = text
        return self

    def modal_icon(self, icon: Any, color: Any = None) -> "Action":
        self._modal_icon = icon
        self._modal_icon_color = color
        return self

    def modal_width(self, width: str) -> "Action":
        """sm, md, lg, xl, 2xl, 3xl, 4xl, 5xl"""
        self._modal_width = width
        return self

    def modal_content(self, content: Any) -> "Action":
        """Extra HTML shown in the modal (``Markup`` or a closure returning it)."""
        self._modal_content = content
        return self

    def slide_over(self, condition: bool = True) -> "Action":
        self._slide_over = condition
        return self

    def form(self, schema: Any, columns: int = 1) -> "Action":
        """A list of fields (or ``lambda form: form.schema([...])``) shown in a modal."""
        self._form = schema
        self._form_columns = columns
        return self

    def fill_form(self, fn: Callable) -> "Action":
        """Initial modal data: ``fill_form(lambda record: {"status": record.status})``."""
        self._fill_form = fn
        return self

    def action(self, fn: Callable) -> "Action":
        """The code to run. Gets ``record``/``records``/``data``/``ctx``/``db``/``user``."""
        self._action = fn
        return self

    def success_notification_title(self, title: Any) -> "Action":
        self._success_title = title
        return self

    def success_notification_body(self, body: Any) -> "Action":
        self._success_body = body
        return self

    def failure_notification_title(self, title: Any) -> "Action":
        self._failure_title = title
        return self

    def success_redirect_url(self, url: Any) -> "Action":
        self._success_redirect = url
        return self

    def disabled(self, condition: Any = True) -> "Action":
        self._disabled = condition
        return self

    def tooltip(self, text: Any) -> "Action":
        self._tooltip = text
        return self

    def button(self) -> "Action":
        self._style = "button"
        return self

    def link(self) -> "Action":
        self._style = "link"
        return self

    def icon_button(self) -> "Action":
        self._style = "icon"
        return self

    def soft(self) -> "Action":
        """Light colored button (used for bulk actions)."""
        self._style = "soft"
        return self

    def outlined(self, condition: bool = True) -> "Action":
        self._outlined = condition
        return self

    def size(self, size: str) -> "Action":
        self._size = size
        return self

    def badge(self, badge: Any) -> "Action":
        self._badge = badge
        return self

    def hidden_label(self, condition: bool = True) -> "Action":
        self._hidden_label = condition
        return self

    def authorize(self, ability: Any) -> "Action":
        """A permission ability (``"delete"``), a closure, or a bool."""
        self._authorize = ability
        return self

    def keyboard_shortcut(self, keys: str) -> "Action":
        self._keyboard = keys
        return self

    def deselect_records_after_completion(self, condition: bool = True) -> "Action":
        self._deselect_after = condition
        return self

    # ------------------------------------------------------------------ resolve
    def ev(self, ctx: "Context | None", record: Any = None, records: Any = None, **extra: Any) -> dict[str, Any]:
        return {
            "ctx": ctx,
            "request": ctx.request if ctx else None,
            "user": ctx.user if ctx else None,
            "db": ctx.db if ctx else None,
            "tenant": ctx.tenant if ctx else None,
            "record": record,
            "records": records,
            "action": self,
            **extra,
        }

    def get_label(self, ev: dict | None = None) -> str:
        if self._label is None:
            return __(headline(self.name))
        return __(str(evaluate(self._label, **(ev or {}))))

    def needs_modal(self) -> bool:
        return bool(self._requires_confirmation or self._form is not None)

    def is_url(self) -> bool:
        return self._url is not None

    def is_authorized(self, host: "Host | None", ctx: "Context", record: Any = None) -> bool:
        if self._authorize is None:
            return True
        if isinstance(self._authorize, str):
            return host.can(ctx, self._authorize, record) if host else ctx.can(self._authorize, record)
        return bool(evaluate(self._authorize, **self.ev(ctx, record)))

    def is_available(self, host: "Host | None", ctx: "Context", record: Any = None) -> bool:
        ev = self.ev(ctx, record, host=host)
        return self.is_visible(**ev) and self.is_authorized(host, ctx, record)

    def get_url(self, ctx: "Context", record: Any = None) -> str | None:
        return evaluate(self._url, **self.ev(ctx, record)) if self._url is not None else None

    def build_form(self, ctx: "Context", host: "Host | None", record: Any = None, records: Any = None) -> "Form | None":
        from ..forms.form import Form

        if self._form is None:
            return None
        form = Form()
        form.columns(self._form_columns)
        if callable(self._form) and not isinstance(self._form, list):
            result = call(self._form, **{**self.ev(ctx, record, records), "form": form})
            if isinstance(result, Form):
                form = result
            elif isinstance(result, list):
                form.schema(result)
        else:
            form.schema(list(self._form))
        if host is not None and getattr(host, "model", None) is not None and form._model is None:
            form.model(host.model)
        return form

    def fill(self, form: "Form", ctx: "Context", record: Any = None, records: Any = None) -> None:
        form.fill(None)
        if self._fill_form is not None:
            data = call(self._fill_form, **self.ev(ctx, record, records, form=form)) or {}
            form.fill_from(data)

    def run(self, ctx: "Context", host: "Host | None", record: Any = None, records: Any = None,
            data: dict | None = None, form: "Form | None" = None) -> Any:
        if self._action is None:
            return None
        return call(self._action, **{**self.ev(ctx, record, records), "data": data or {}, "form": form, "host": host})

    def success_notification(self, ctx: "Context", record: Any = None, records: Any = None):
        from ..notifications import Notification

        title = evaluate(self._success_title, **self.ev(ctx, record, records))
        if not title:
            return None
        body = evaluate(self._success_body, **self.ev(ctx, record, records))
        return Notification(title).body(body).success()

    # ------------------------------------------------------------------ render
    def view_data(self, ctx: "Context", host: "Host | None", record: Any = None, *, style: str | None = None,
                  table_id: str | None = None) -> dict[str, Any]:
        ev = self.ev(ctx, record, host=host)
        style = style or self._style or self.default_style
        color = evaluate(self._color, **ev) or "primary"
        url = self.get_url(ctx, record)
        record_key = host.record_key(record) if (host is not None and record is not None) else None
        endpoint = ctx.panel.url("_tw", "action")
        vals = {"_tw_host": host.key if host else "", "_tw_scope": self.scope, "_tw_name": self.name}
        if record_key is not None:
            vals["_tw_record"] = record_key
        label = self.get_label(ev)
        return {
            "name": self.name,
            "label": label,
            "icon": evaluate(self._icon, **ev),
            "color": color,
            "style": style,
            "size": self._size,
            "url": url,
            "new_tab": self._new_tab,
            "modal": self.needs_modal(),
            "endpoint": endpoint,
            "vals": vals,
            "disabled": bool(evaluate(self._disabled, **ev)),
            "tooltip": maybe(evaluate(self._tooltip, **ev)) or (label if style == "icon" else None),
            "badge": evaluate(self._badge, **ev),
            "outlined": self._outlined,
            "hidden_label": self._hidden_label,
            "bulk": self.scope == "bulk",
            "table_id": table_id,
            "keyboard": self._keyboard,
        }

    def render(self, ctx: "Context", host: "Host | None", record: Any = None, *, style: str | None = None,
               table_id: str | None = None) -> Markup:
        if not self.is_available(host, ctx, record):
            return Markup("")
        return ctx.panel.renderer.render(
            "tungsten/actions/button.html",
            a=self.view_data(ctx, host, record, style=style, table_id=table_id),
        )


class BulkAction(Action):
    """An action run on the selected table rows. The closure gets ``records``."""

    scope = "bulk"
    default_style = "soft"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._color = "gray"

    def is_available(self, host: "Host | None", ctx: "Context", record: Any = None) -> bool:
        ev = self.ev(ctx, None, host=host)
        return self.is_visible(**ev) and self.is_authorized(host, ctx, None)


class ActionGroup(Component):
    """Several actions behind one dropdown button (``...``)."""

    def __init__(self, actions: list[Action]) -> None:
        super().__init__()
        self.actions = list(actions)
        self._label: Any = "More actions"
        self._icon: Any = "ellipsis"
        self._color = "gray"
        self._button = False
        self._style = None

    def label(self, label: Any) -> "ActionGroup":
        self._label = label
        return self

    def icon(self, icon: Any) -> "ActionGroup":
        self._icon = icon
        return self

    def color(self, color: str) -> "ActionGroup":
        self._color = color
        return self

    def button(self) -> "ActionGroup":
        """Show as a labelled button instead of an icon."""
        self._button = True
        return self

    def flatten(self) -> list[Action]:
        out: list[Action] = []
        for a in self.actions:
            out.extend(a.flatten() if isinstance(a, ActionGroup) else [a])
        return out

    def render(self, ctx: "Context", host: "Host | None", record: Any = None, *, style: str | None = None,
               table_id: str | None = None) -> Markup:
        items = [a.view_data(ctx, host, record, style="dropdown", table_id=table_id)
                 for a in self.flatten() if a.is_available(host, ctx, record)]
        if not items:
            return Markup("")
        return ctx.panel.renderer.render(
            "tungsten/actions/group.html",
            items=items,
            label=maybe(evaluate(self._label, record=record)),
            group_icon=self._icon,
            color=self._color,
            button=self._button or style == "soft",
            soft=style == "soft",
            table_id=table_id,
        )


class BulkActionGroup(ActionGroup):
    def __init__(self, actions: list[Action]) -> None:
        super().__init__(actions)
        self._button = True


def flatten_actions(actions: list) -> list[Action]:
    out: list[Action] = []
    for a in actions or []:
        out.extend(a.flatten() if isinstance(a, ActionGroup) else [a])
    return out


def _to_state(form: "Form", key: str, value: Any) -> Any:
    found = form.find(key)
    if found:
        return found[0].to_state(value)
    return value
