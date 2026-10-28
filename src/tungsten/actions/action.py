"""Actions: buttons that run code, open a confirmation box or a modal form."""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from typing import TYPE_CHECKING, Any, Callable, Iterable

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


#: how many modals can sit on top of each other (an action's modal plus nested ones)
MAX_MODAL_LEVEL = 2


class RateLimiter:
    """Counts attempts per key in memory (per server process)."""

    def __init__(self) -> None:
        self._hits: dict[Any, deque] = {}
        self._lock = threading.Lock()

    def hit(self, key: Any, max_attempts: int, seconds: float) -> float:
        """Record an attempt. Returns 0 when allowed, else the seconds to wait."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - seconds:
                hits.popleft()
            if len(hits) >= max_attempts:
                return max(hits[0] + seconds - now, 0.001)
            hits.append(now)
            if len(self._hits) > 10000:  # forget idle keys
                for k in [k for k, v in self._hits.items() if not v or v[-1] <= now - seconds]:
                    self._hits.pop(k, None)
            return 0

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()


rate_limiter = RateLimiter()


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
        self._modal_submit = True
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
        self._log_activity: bool | None = None
        self._parent: Action | None = None
        self._nested: list[Action] = []
        self._footer_actions: list[str] = []
        self._extra_submits: list[dict[str, Any]] = []
        self._then: Any = None
        self._cancel_parents = False
        self._wizard = False
        self._before: list[Callable] = []
        self._after: list[Callable] = []
        self._rate_limit: tuple[int, float, str] | None = None
        self._rate_limit_message: Any = None
        self._sticky_header = True
        self._sticky_footer = True
        #: ``arguments`` of the extra submit button that was pressed (see ``extra_modal_submit_action``)
        self.arguments: dict[str, Any] = {}

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

    def modal_submit_action(self, condition: bool = True) -> "Action":
        """``modal_submit_action(False)`` hides the submit button, for a popup that only shows something."""
        self._modal_submit = condition
        return self

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
        """HTML shown in the modal (``Markup`` or a closure returning it). The action then opens a modal."""
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
        """Toast shown when the action fails: it returns ``False``, or raises an error (the database
        changes are rolled back). Without a title an error is raised as usual."""
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

    # ------------------------------------------------------------------ modals, chaining, hooks
    def steps(self, steps: list, skippable: bool = False) -> "Action":
        """Show the modal form as a wizard: ``steps([Step("Details").schema([...]), Step("Price")...])``.

        Each "Next" checks that step; the last step's button runs the action."""
        from ..forms.layout import Wizard

        wizard = Wizard(list(steps)).horizontal().skippable(skippable)
        self._form = [wizard]
        self._wizard = True
        return self

    def extra_modal_footer_actions(self, actions: list["Action"]) -> "Action":
        """More buttons in the modal footer. Each is a full action: one with a form or confirmation
        opens its own modal on top of this one; the rest run straight away."""
        for action in actions:
            self._add_nested(action)
            self._footer_actions.append(action.name)
        return self

    modal_footer_actions = extra_modal_footer_actions

    def extra_modal_submit_action(self, name: str, label: Any = None, arguments: dict | None = None,
                                  color: str = "gray") -> "Action":
        """Another submit button that runs this action with ``arguments`` (the closure gets
        ``arguments``), e.g. ``extra_modal_submit_action("draft", "Save as draft", {"draft": True})``."""
        self._extra_submits.append({"name": name, "label": label or headline(name), "arguments": dict(arguments or {}),
                                    "color": color})
        return self

    def then(self, next_action: Any) -> "Action":
        """Open (or run) another action when this one succeeds, on the same record.

        ``next_action`` is an :class:`Action`, the name of one of the page's/table's actions, or a
        closure returning either (or None to stop): ``then(lambda result: "notify" if result else None)``.
        A name can also be an action higher up the chain this one was opened from (a "Back" step), or a
        full path such as ``"import/map"``."""
        if isinstance(next_action, Action):
            self._add_nested(next_action)
        self._then = next_action
        return self

    def cancel_parent_actions(self, condition: bool = True) -> "Action":
        """For an action in another action's modal: close every modal when it finishes, not only its own."""
        self._cancel_parents = condition
        return self

    def before(self, fn: Callable) -> "Action":
        """Run ``fn`` before the action (after the form is checked). Raise :class:`Halt` to stop."""
        self._before.append(fn)
        return self

    def after(self, fn: Callable) -> "Action":
        """Run ``fn`` after the action succeeded. It also gets ``result``."""
        self._after.append(fn)
        return self

    def rate_limit(self, max_attempts: int, per_seconds: float = 60, by: str = "user") -> "Action":
        """Allow at most ``max_attempts`` runs per ``per_seconds`` for each user (``by="user"``),
        each client address (``by="ip"``) or everyone together (``by="action"``). Counted per server process."""
        self._rate_limit = (max(1, int(max_attempts)), float(per_seconds), by)
        return self

    def rate_limited_notification_title(self, title: Any) -> "Action":
        self._rate_limit_message = title
        return self

    def sticky_modal_header(self, condition: bool = True) -> "Action":
        """Keep the modal heading in view while the content scrolls (on by default)."""
        self._sticky_header = condition
        return self

    def sticky_modal_footer(self, condition: bool = True) -> "Action":
        """Keep the modal buttons in view while the content scrolls (on by default)."""
        self._sticky_footer = condition
        return self

    def _add_nested(self, action: "Action") -> None:
        action._parent = self
        self._nested = [a for a in self._nested if a.name != action.name] + [action]

    def find_nested(self, name: str) -> "Action | None":
        return next((a for a in self._nested if a.name == name), None)

    @property
    def path(self) -> str:
        """The name used to find this action again: ``parent/child`` for nested actions."""
        return f"{self._parent.path}/{self.name}" if self._parent is not None else self.name

    def check_rate_limit(self, ctx: "Context", host: "Host | None") -> float:
        """0 when the action may run now, else the seconds to wait. Counts this attempt."""
        if self._rate_limit is None:
            return 0
        max_attempts, seconds, by = self._rate_limit
        if by == "ip":
            who = ctx.request.client.host if ctx.request.client else ""
        elif by == "action":
            who = ""
        else:
            who = ctx.panel.auth.user_id(ctx.user) if ctx.user is not None else (
                ctx.request.client.host if ctx.request.client else "")
        key = (ctx.panel.id, host.key if host else "", self.path, by, who)
        return rate_limiter.hit(key, max_attempts, seconds)

    def rate_limited_notification(self, ctx: "Context", wait: float):
        from ..notifications import Notification

        title = evaluate(self._rate_limit_message, **self.ev(ctx)) or "Too many attempts"
        return Notification(title).body(__("Please try again in :seconds seconds.", seconds=max(1, round(wait + 0.49)))
                                        ).danger()

    def call_hooks(self, kind: str, ctx: "Context", host: "Host | None", record: Any = None, records: Any = None,
                   data: dict | None = None, **extra: Any) -> None:
        for fn in self._before if kind == "before" else self._after:
            call(fn, **{**self.ev(ctx, record, records), "data": data or {}, "host": host, **extra})

    def execute(self, ctx: "Context", host: "Host | None", record: Any = None, records: Any = None,
                data: dict | None = None, form: "Form | None" = None) -> Any:
        """``before`` hooks, the action, then ``after`` hooks when it did not fail."""
        self.call_hooks("before", ctx, host, record, records, data, form=form)
        result = self.run(ctx, host, record, records, data, form)
        if result is not False:
            self.call_hooks("after", ctx, host, record, records, data, form=form, result=result)
        return result

    def next_action(self, ctx: "Context", record: Any = None, records: Any = None, result: Any = None) -> Any:
        """The action to open after this one (see :meth:`then`): an Action, a name, or None."""
        target = self._then
        if target is None or isinstance(target, (Action, str)):
            return target
        return call(target, **{**self.ev(ctx, record, records), "result": result})

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
            "arguments": self.arguments,
            **extra,
        }

    def get_label(self, ev: dict | None = None) -> str:
        if self._label is None:
            return __(headline(self.name))
        return __(str(evaluate(self._label, **(ev or {}))))

    def log_activity(self, enabled: bool = True) -> "Action":
        """Write a row to the activity log each time the action runs (on by default with ``activity_log=True``)."""
        self._log_activity = enabled
        return self

    def logs_activity(self) -> bool:
        if self._log_activity is not None:
            return self._log_activity
        return not self.logged_by_host()

    def logged_by_host(self) -> bool:
        """True when the host already logs what this action does (create, edit, delete ...)."""
        return False

    def needs_modal(self) -> bool:
        return bool(self._requires_confirmation or self._form is not None or self._modal_content is not None)

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

    def is_disabled(self, host: "Host | None", ctx: "Context", record: Any = None) -> bool:
        """``disabled()`` is true for this record: the button is greyed out and posting it is refused."""
        return bool(evaluate(self._disabled, **self.ev(ctx, record, host=host)))

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
        if self._wizard and self._modal_submit_label is not None:
            for component in form._schema:
                if hasattr(component, "submit_label"):
                    component.submit_label(self._modal_submit_label)
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

    def modal_footer_view(self, ctx: "Context", host: "Host | None", record: Any = None, level: int = 0,
                          record_keys: list | None = None) -> dict:
        """Buttons for the modal footer: nested actions (opening one level up) and extra submits."""
        ev = self.ev(ctx, record)
        actions = []
        for name in self._footer_actions:
            nested = self.find_nested(name)
            if nested is None or not nested.is_available(host, ctx, record):
                continue
            nested.scope = self.scope
            view = nested.view_data(ctx, host, record, style=nested._style or "button", level=level + 1)
            if record_keys:
                view["vals"]["records"] = list(record_keys)
            if level + 1 > MAX_MODAL_LEVEL:  # no room for another modal: replace this one
                view["target"] = modal_target(level)
                view["vals"]["_tw_level"] = str(level)
            actions.append(view)
        submits = [{**s, "label": __(str(evaluate(s["label"], **ev)))} for s in self._extra_submits]
        return {"actions": actions, "submits": submits}

    def success_notification(self, ctx: "Context", record: Any = None, records: Any = None):
        from ..notifications import Notification

        title = evaluate(self._success_title, **self.ev(ctx, record, records))
        if not title:
            return None
        body = evaluate(self._success_body, **self.ev(ctx, record, records))
        return Notification(title).body(body).success()

    def failure_notification(self, ctx: "Context", record: Any = None, records: Any = None):
        from ..notifications import Notification

        title = evaluate(self._failure_title, **self.ev(ctx, record, records))
        if not title:
            return None
        return Notification(title).danger()

    # ------------------------------------------------------------------ render
    def view_data(self, ctx: "Context", host: "Host | None", record: Any = None, *, style: str | None = None,
                  table_id: str | None = None, level: int = 0) -> dict[str, Any]:
        ev = self.ev(ctx, record, host=host)
        style = style or self._style or self.default_style
        color = evaluate(self._color, **ev) or "primary"
        url = self.get_url(ctx, record)
        record_key = host.record_key(record) if (host is not None and record is not None) else None
        endpoint = ctx.panel.url("_tw", "action")
        vals = {"_tw_host": host.key if host else "", "_tw_scope": self.scope, "_tw_name": self.path}
        if record_key is not None:
            vals["_tw_record"] = record_key
        level = max(0, min(level, MAX_MODAL_LEVEL))
        if level:
            vals["_tw_level"] = str(level)
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
            "level": level,
            "target": modal_target(level),
        }

    def render(self, ctx: "Context", host: "Host | None", record: Any = None, *, style: str | None = None,
               table_id: str | None = None) -> Markup:
        if not self.is_available(host, ctx, record):
            return Markup("")
        return ctx.panel.renderer.render(
            "tungsten/actions/button.html",
            a=self.view_data(ctx, host, record, style=style, table_id=table_id),
        )


def open_from_url(ctx: "Context", host: "Host | None", actions: Iterable[Any], record: Any = None,
                  table_id: str | None = None) -> Markup:
    """For ``?action=<name>`` in a page's address (Filament's ``?action=``): opens that action's modal as the
    page loads, when it is one of ``actions`` and the user may run it."""
    name = ctx.request.query_params.get("action") if ctx is not None and ctx.request is not None else None
    if not name:
        return Markup("")
    for action in flatten_actions(list(actions)):
        if action.name != name or not action.needs_modal() or not action.is_available(host, ctx, record) \
                or action.is_disabled(host, ctx, record):
            continue
        a = action.view_data(ctx, host, record, table_id=table_id)
        return Markup('<div hidden hx-get="{}" hx-vals="{}" hx-target="#tw-modal" hx-swap="innerHTML" '
                      'hx-trigger="load"></div>').format(a["endpoint"], json.dumps(a["vals"]))
    return Markup("")


def modal_target(level: int) -> str:
    """The element a modal of this nesting level is drawn into."""
    return "#tw-modal" if level <= 0 else f"#tw-modal-{level}"


class BulkAction(Action):
    """An action run on the selected table rows. The closure gets ``records``.

    ``chunk_selected_records(100)`` calls it once per 100 records; ``background()`` runs it after
    the response and sends the user a notification when it is done."""

    scope = "bulk"
    default_style = "soft"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._color = "gray"
        self._chunk_size: int | None = None
        self._background: Any = False
        self._background_message: Any = None

    def chunk_selected_records(self, size: int = 100) -> "BulkAction":
        """Load and process the selected records ``size`` at a time (the closure runs once per chunk)."""
        self._chunk_size = max(1, int(size))
        return self

    def background(self, condition: Any = True, chunk_size: int | None = None) -> "BulkAction":
        """Run after the response, in chunks, and notify the user when done. ``condition`` may be a
        closure, e.g. ``background(lambda keys: len(keys) > 500)``."""
        self._background = condition
        if chunk_size is not None:
            self._chunk_size = max(1, int(chunk_size))
        elif self._chunk_size is None:
            self._chunk_size = 100
        return self

    def runs_in_background(self, ctx: "Context", keys: list) -> bool:
        return bool(evaluate(self._background, **{**self.ev(ctx), "keys": keys}))

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
