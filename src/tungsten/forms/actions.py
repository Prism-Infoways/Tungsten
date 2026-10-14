"""Actions inside forms: buttons in hints, prefixes/suffixes, an ``Actions`` row,
and the create/edit buttons of a ``Select``.

They are ordinary :class:`~tungsten.actions.Action` objects. A click posts the form
to the live-refresh endpoint. An action without a modal runs at once; one with a
form, a confirmation or modal content opens a modal drawn *inside* the form, so it
also works in a form that is already in a modal. Closures get the form helpers::

    TextInput("slug").suffix_action(
        Action("generate").icon("refresh-cw")
            .action(lambda get, set: set("slug", slugify(get("title"))))
    )
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from markupsafe import Markup

from ..i18n import maybe
from ..i18n import translate as __
from ..support.evaluate import call, evaluate
from ..support.state import Getter, Setter

if TYPE_CHECKING:  # pragma: no cover
    from ..actions.action import Action
    from .fields import Field
    from .form import Form

#: state path of the fields of an open modal
MODAL_BASE = "__modal"
#: ``form.ui`` key that remembers which action's modal is open
MODAL_KEY = "_modal"


def action_ev(action: "Action", form: "Form", field: "Field", base: str, /, **extra: Any) -> dict[str, Any]:
    """Closure arguments: the action's own (``record``, ``user`` ...) plus the form's (``get``, ``set``, ``state``)."""
    ev = action.ev(form.ctx, form.record)
    ev.update({
        "get": Getter(form.state, base),
        "set": Setter(form.state, base),
        "state": field.get_state(form, base),
        "component": field,
        "form": form,
        "operation": form.operation,
        "model": form.get_model(),
    })
    ev.update(extra)
    return ev


def is_action_available(action: "Action", form: "Form", field: "Field", base: str) -> bool:
    ev = action_ev(action, form, field, base)
    if not action.is_visible(**ev):
        return False
    if action._authorize is None:
        return True
    if isinstance(action._authorize, str):
        return form.ctx is not None and form.ctx.can(action._authorize, form.record)
    return bool(evaluate(action._authorize, **ev))


def render_action(action: "Action", form: "Form", field: "Field", base: str, *, style: str = "button",
                  size: str = "md") -> Markup:
    """One action button for a form component (empty when hidden or not usable here)."""
    if not is_action_available(action, form, field, base):
        return Markup("")
    ev = action_ev(action, form, field, base)
    url = evaluate(action._url, **ev) if action._url is not None else None
    if url is None and (form.is_disabled or form.parent is not None):
        # a read-only form runs nothing, and a modal can't open another modal
        return Markup("")
    label = action.get_label(ev)
    style = action._style or style
    disabled = bool(evaluate(action._disabled, **ev))
    path = field.path(base)
    a = {
        "label": label,
        "icon": evaluate(action._icon, **ev),
        "color": evaluate(action._color, **ev) or "primary",
        "style": style,
        "size": action._size if action._size != "md" else size,
        "outlined": action._outlined,
        "url": url,
        "new_tab": action._new_tab,
        "disabled": disabled,
        "tooltip": maybe(evaluate(action._tooltip, **ev)) or (label if style == "icon" else None),
        "hidden_label": action._hidden_label,
        "badge": evaluate(action._badge, **ev),
        "ui_action": f"faction.call:{path}:{action.name}",
    }
    return form.renderer.render("tungsten/forms/action.html", form=form, a=a)


def render_actions(actions: list, form: "Form", field: "Field", base: str, **kw: Any) -> Markup:
    return Markup("").join(render_action(a, form, field, base, **kw) for a in actions)


# ---------------------------------------------------------------------- running
def _visible_fields(form: "Form", components: list, base: str):
    """Like ``form.walk_fields()``, but skips hidden fields and anything inside a hidden layout,
    so an action can only be run when its button could be shown."""
    from ..support.state import join
    from .fields import Field, Repeater
    from .layout import Layout

    for comp in components:
        if isinstance(comp, Layout):
            if comp.is_layout_visible(form, base):
                yield from _visible_fields(form, comp.child_components(), base)
        elif isinstance(comp, Field):
            if not comp.is_field_visible(form, base):
                continue
            yield comp, comp.path(base), base
            if isinstance(comp, Repeater):
                comp._prepare(form)
                for i, row in enumerate(comp.rows(form, base)):
                    yield from _visible_fields(form, comp._schema_for(row), join(comp.path(base), i))


def find_action(form: "Form", path: str, name: str) -> tuple["Action", "Field", str] | None:
    found = next(((f, p, b) for f, p, b in _visible_fields(form, form.get_schema(), form.base) if p == path), None)
    if found is None:
        return None
    field, _, base = found
    for action in field.form_actions(form, base):
        if action.name == name:
            return action, field, base
    return None


def _build_modal_form(form: "Form", action: "Action", field: "Field", base: str) -> "Form | None":
    from .form import Form

    if action._form is None:
        return None
    sub = Form()
    sub.columns(action._form_columns)
    ev = action_ev(action, form, field, base, form=sub)
    if callable(action._form) and not isinstance(action._form, list):
        result = call(action._form, **ev)
        if isinstance(result, Form):
            sub = result
        elif isinstance(result, list):
            sub.schema(result)
    else:
        sub.schema(list(action._form))
    model = getattr(action, "_modal_model", None)
    if model is None and getattr(action, "_modal_model_fn", None) is not None:
        model = action._modal_model_fn(form)
    if model is not None and sub._model is None:
        sub.model(model)
    sub.base = MODAL_BASE
    sub.parent = form
    sub.bind(form.ctx, operation=getattr(action, "_modal_operation", "create"),
             record=getattr(action, "_modal_record", None), id=form.id, refresh_url=form.refresh_url)
    for comp in sub._walk_components(sub.get_schema()):  # keep tab/wizard keys apart from the outer form's
        if getattr(comp, "_ui_key", None):
            comp._ui_key = f"{MODAL_BASE}.{comp._ui_key}"
    sub.ui = form.ui
    return sub


class OpenModal:
    """The modal of a form component action that is open right now."""

    def __init__(self, form: "Form", action: "Action", field: "Field", base: str, sub: "Form | None") -> None:
        self.form = form
        self.action = action
        self.field = field
        self.base = base
        self.sub = sub

    @property
    def key(self) -> str:
        return f"{self.field.path(self.base)}:{self.action.name}"

    def ev(self, **extra: Any) -> dict[str, Any]:
        return action_ev(self.action, self.form, self.field, self.base, **extra)

    def view_data(self) -> dict[str, Any]:
        action = self.action
        ev = self.ev()
        heading = maybe(evaluate(action._modal_heading, **ev)) or action.get_label(ev)
        description = maybe(evaluate(action._modal_description, **ev))
        content = evaluate(action._modal_content, **ev)
        confirm_only = self.sub is None and (content is None or bool(action._requires_confirmation))
        if description is None and confirm_only:
            description = __("Are you sure you would like to do this?")
        submit = maybe(evaluate(action._modal_submit_label, **ev)) if action._modal_submit_label is not None else (
            __("Confirm") if self.sub is None else __("Submit"))
        color = evaluate(action._color, **ev) or "primary"
        return {
            "key": self.key,
            "heading": heading,
            "description": description,
            "content": content,
            "icon": evaluate(action._modal_icon, **ev),
            "icon_color": evaluate(action._modal_icon_color, **ev) or color,
            "submit_label": submit if action._modal_submit else None,
            "cancel_label": maybe(evaluate(action._modal_cancel_label, **ev)) or __("Cancel"),
            "color": color if color != "gray" else "primary",
            "width": action._modal_width,
            "slide_over": action._slide_over,
            "confirm_only": confirm_only,
        }


def open_modal(form: "Form") -> OpenModal | None:
    """The modal named in ``form.ui`` (built once per request)."""
    if form._modal is not None:
        return form._modal or None
    form._modal = False
    key = form.ui.get(MODAL_KEY) or ""
    path, _, name = key.rpartition(":")
    found = find_action(form, path, name) if path else None
    if found is None:
        return None
    action, field, base = found
    if not is_action_available(action, form, field, base):
        return None
    if getattr(action, "_prepare_modal", None):
        action._prepare_modal(form, field, base)
    sub = _build_modal_form(form, action, field, base)
    if sub is not None:
        if form.formdata is not None and any(k.startswith(MODAL_BASE + ".") for k in form.formdata.keys()):
            sub.load(form.formdata)
        else:
            sub.fill()
            fill = getattr(action, "_fill_form", None)
            if fill is not None:
                data = call(fill, **action_ev(action, form, field, base, modal_form=sub)) or {}
                for k, v in data.items():
                    found_field = sub.find(f"{MODAL_BASE}.{k}")
                    sub.set(f"{MODAL_BASE}.{k}", found_field[0].to_state(v) if found_field else v)
    form._modal = OpenModal(form, action, field, base, sub)
    return form._modal


def close_modal(form: "Form") -> None:
    form.ui.pop(MODAL_KEY, None)
    form._modal = False


def handle(form: "Form", kind: str, target: str, arg: str) -> None:
    """``faction.call:<path>:<name>``, ``faction.submit`` and ``faction.close``."""
    from ..actions.action import Halt
    from .form import ValidationError

    if kind == "close":
        close_modal(form)
        return
    if kind == "call":
        found = find_action(form, target, arg)
        if found is None:
            return
        action, field, base = found
        if form.is_disabled or not is_action_available(action, form, field, base):
            return
        if evaluate(action._disabled, **action_ev(action, form, field, base)):
            return
        if action.needs_modal():
            form.ui[MODAL_KEY] = f"{field.path(base)}:{action.name}"
            form._modal = None
            form.formdata = None  # start the modal from its defaults
            open_modal(form)
            return
        _run(form, action, field, base, {}, None)
        return
    if kind == "submit":
        modal = open_modal(form)
        if modal is None:
            close_modal(form)
            return
        data: dict = {}
        if modal.sub is not None:
            try:
                data = modal.sub.validate()
            except ValidationError:
                return
        try:
            ok = _run(form, modal.action, modal.field, modal.base, data, modal.sub)
        except Halt:
            return
        except ValidationError as exc:
            if modal.sub is not None:
                modal.sub.errors = exc.errors
            return
        if ok:
            close_modal(form)


def _run(form: "Form", action: "Action", field: "Field", base: str, data: dict, sub: "Form | None") -> bool:
    from ..notifications import Notification

    ctx = form.ctx
    result = None
    if action._action is not None:
        result = call(action._action, **action_ev(action, form, field, base, data=data, modal_form=sub))
    ev = action.ev(ctx, form.record)
    if result is False:
        title = evaluate(action._failure_title, **ev)
        if title and ctx is not None:
            Notification(title).danger().send(ctx)
        return False
    title = evaluate(action._success_title, **ev)
    if title and ctx is not None:
        Notification(title).body(evaluate(action._success_body, **ev)).success().send(ctx)
    return True
