"""The MCP tools: read and change the records of the panel's resources, as the token's user.

Every tool goes through the same checks as the panel pages: the resource's policy and the
user's roles, tenancy, the resource's own query, and its form (validation, hooks) for writes.
"""

from __future__ import annotations

import datetime as dt
import enum
import re
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy import inspect as sa_inspect

from tungsten.forms.form import ValidationError
from tungsten.support.state import set_path

#: columns never shown to the AI (password hashes, API keys ...); add your own with ``hidden_fields``
SENSITIVE = re.compile(r"password|passwd|secret|token|api_?key|two_factor|recovery_codes|otp", re.IGNORECASE)


class ToolError(Exception):
    """A problem the AI can fix (wrong name, missing permission, invalid data): sent back as the tool result."""

    def __init__(self, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.details = details


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}


class Tools:
    """The tool list and the code behind each tool, for one panel."""

    READ = ("list_resources", "describe_resource", "list_records", "get_record")
    WRITE = ("create_record", "update_record", "delete_record")

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin

    # ------------------------------------------------------------------ resources
    def resources(self, ctx: Any) -> list:
        """Resources this user may list, and the plugin exposes."""
        out = []
        for resource in ctx.panel.get_resources():
            if not self.plugin.exposes(resource):
                continue
            if resource.can(ctx, "view_any"):
                out.append(resource)
        return out

    def resource(self, ctx: Any, slug: Any) -> Any:
        for resource in self.resources(ctx):
            if resource.get_slug() == slug:
                return resource
        names = ", ".join(r.get_slug() for r in self.resources(ctx)) or "none"
        raise ToolError(f"Unknown resource {slug!r}. Resources you can use: {names}.")

    # ------------------------------------------------------------------ definitions
    def definitions(self, ctx: Any, can_write: bool) -> list[dict]:
        slugs = [r.get_slug() for r in self.resources(ctx)]
        res = {"type": "string", "description": "The resource name, from list_resources.", "enum": slugs}
        rid = {"type": ["string", "integer"], "description": "The record's id."}
        data = {"type": "object", "description": "Field values by field name, as describe_resource lists them."}
        tools = [
            {
                "name": "list_resources",
                "title": "List resources",
                "description": "List the kinds of records in this admin panel (for example products or orders), "
                               "with what you are allowed to do with each.",
                "inputSchema": _schema({}),
                "annotations": {"readOnlyHint": True},
            },
            {
                "name": "describe_resource",
                "title": "Describe a resource",
                "description": "Show the columns of a resource, and the form fields to use with "
                               "create_record and update_record (types, required, allowed options).",
                "inputSchema": _schema({"resource": res}, ["resource"]),
                "annotations": {"readOnlyHint": True},
            },
            {
                "name": "list_records",
                "title": "List records",
                "description": "Find records of a resource. Search text, filter by exact column values, sort "
                               "and page through. Returns the total count and one page of records.",
                "inputSchema": _schema({
                    "resource": res,
                    "search": {"type": "string", "description": "Text to look for in the searchable columns."},
                    "filters": {"type": "object", "description": "Exact column values, e.g. {\"status\": \"paid\"}. "
                                                                 "A list matches any of its values; null matches empty."},
                    "sort": {"type": "string", "description": "Column to sort by. Start with - for newest/largest "
                                                              "first, e.g. \"-created_at\"."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": self.plugin.max_limit,
                              "description": f"Records per page (default 25, at most {self.plugin.max_limit})."},
                    "offset": {"type": "integer", "minimum": 0, "description": "Records to skip."},
                }, ["resource"]),
                "annotations": {"readOnlyHint": True},
            },
            {
                "name": "get_record",
                "title": "Get a record",
                "description": "Get one record of a resource by its id.",
                "inputSchema": _schema({"resource": res, "id": rid}, ["resource", "id"]),
                "annotations": {"readOnlyHint": True},
            },
        ]
        if can_write:
            tools += [
                {
                    "name": "create_record",
                    "title": "Create a record",
                    "description": "Create a record with the resource's form. Unset fields get their defaults. "
                                   "Call describe_resource first to see the fields.",
                    "inputSchema": _schema({"resource": res, "data": data}, ["resource", "data"]),
                    "annotations": {"readOnlyHint": False, "destructiveHint": False},
                },
                {
                    "name": "update_record",
                    "title": "Update a record",
                    "description": "Change some fields of a record. Fields you leave out keep their value.",
                    "inputSchema": _schema({"resource": res, "id": rid, "data": data}, ["resource", "id", "data"]),
                    "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True},
                },
                {
                    "name": "delete_record",
                    "title": "Delete a record",
                    "description": "Delete a record (moved to trash when the resource has one).",
                    "inputSchema": _schema({"resource": res, "id": rid}, ["resource", "id"]),
                    "annotations": {"readOnlyHint": False, "destructiveHint": True},
                },
            ]
        return tools

    def call(self, ctx: Any, name: str, args: dict) -> Any:
        return getattr(self, name)(ctx, **args)

    # ------------------------------------------------------------------ reading
    def list_resources(self, ctx: Any) -> dict:
        out = []
        for r in self.resources(ctx):
            soft = r.get_soft_delete_column()
            out.append({
                "name": r.get_slug(),
                "label": r.get_plural_label(),
                "description": r.description or None,
                "can": {"create": r.can(ctx, "create"), "update": r.can(ctx, "update"),
                        "delete": r.can(ctx, "delete")},
                "trash": bool(soft),
            })
        return {"resources": out}

    def describe_resource(self, ctx: Any, resource: str) -> dict:
        r = self.resource(ctx, resource)
        columns = []
        for col in self.columns(r):
            columns.append({"name": col.key, "type": _type_name(col), "nullable": bool(col.nullable),
                            "primary_key": bool(col.primary_key)})
        fields = []
        if r.can(ctx, "create") or r.can(ctx, "update"):
            form = r.host().form(ctx, "create")
            form.fill()
            for field, path, _base in form.walk_fields():
                info = self._field_info(form, field, path)
                if info is not None:
                    fields.append(info)
        return {"name": r.get_slug(), "label": r.get_label(), "plural_label": r.get_plural_label(),
                "columns": columns, "form_fields": fields}

    def _field_info(self, form: Any, field: Any, path: str) -> dict | None:
        kind = type(field).__name__
        if kind in ("Placeholder", "Hidden") or "." in path:
            return None
        info: dict[str, Any] = {"name": path, "type": kind}
        try:
            info["label"] = field.get_label(form)
            info["required"] = field.is_required(form)
        except Exception:  # noqa: BLE001 - closures that need a live form
            info["label"] = path
        if kind == "FileUpload":
            info["note"] = "File uploads can't be set through MCP."
        if getattr(field, "_multiple", False):
            info["multiple"] = True
        if hasattr(field, "get_options"):
            try:
                options = field.get_options(form)
            except Exception:  # noqa: BLE001
                options = []
            if 0 < len(options) <= 100:
                info["options"] = [{"value": _jsonable(k), "label": str(v)} for k, v in options]
        helper = getattr(field, "_helper_text", None)
        if isinstance(helper, str):
            info["help"] = helper
        return info

    def list_records(self, ctx: Any, resource: str, search: str | None = None, filters: dict | None = None,
                     sort: str | None = None, limit: int = 25, offset: int = 0) -> dict:
        r = self.resource(ctx, resource)
        host = r.host()
        model = r.model
        columns = {c.key: c for c in self.columns(r)}
        query = host.scoped_query(ctx, with_trashed=False)
        if search:
            cond = self._search(ctx, r, str(search))
            if cond is not None:
                query = query.where(cond)
        for key, value in (filters or {}).items():
            if key not in columns:
                raise ToolError(f"Unknown column {key!r} in filters. Columns: {', '.join(columns)}.")
            attr = getattr(model, key)
            if value is None:
                query = query.where(attr.is_(None))
            elif isinstance(value, list):
                query = query.where(attr.in_([_coerce(columns[key], v) for v in value]))
            else:
                query = query.where(attr == _coerce(columns[key], value))
        total = ctx.db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
        if sort:
            name = sort.lstrip("-")
            if name not in columns:
                raise ToolError(f"Unknown column {name!r} to sort by. Columns: {', '.join(columns)}.")
            attr = getattr(model, name)
            query = query.order_by(attr.desc() if sort.startswith("-") else attr.asc(), host.primary_key())
        else:
            query = query.order_by(host.primary_key().desc())
        limit = max(1, min(int(limit or 25), self.plugin.max_limit))
        offset = max(0, int(offset or 0))
        rows = ctx.db.scalars(query.limit(limit).offset(offset)).all()
        return {"total": total, "offset": offset, "limit": limit,
                "records": [self.serialize(ctx, r, row) for row in rows]}

    def _search(self, ctx: Any, r: Any, term: str) -> Any:
        """The table's searchable columns, plus global search; any text column when there are none."""
        conds = []
        table = r.host().get_table(ctx)
        if table is not None:
            table.model = r.model
            try:
                cond = table._search_condition(term, [c for c in table._columns if c._global_searchable])
            except Exception:  # noqa: BLE001 - a custom search closure that needs a bound table
                cond = None
            if cond is not None:
                conds.append(cond)
        for attr in r.global_search_attributes:
            if "." not in attr and hasattr(r.model, attr):
                conds.append(cast(getattr(r.model, attr), String).ilike(f"%{term}%"))
        if not conds:
            for col in self.columns(r):
                if isinstance(col.type, String):
                    conds.append(getattr(r.model, col.key).ilike(f"%{term}%"))
        return or_(*conds) if conds else None

    def get_record(self, ctx: Any, resource: str, id: Any) -> dict:
        r = self.resource(ctx, resource)
        record = self._find(ctx, r, id)
        if not r.can(ctx, "view", record):
            raise ToolError("You are not allowed to see this record.")
        return self.serialize(ctx, r, record)

    # ------------------------------------------------------------------ writing
    def create_record(self, ctx: Any, resource: str, data: dict) -> dict:
        r = self.resource(ctx, resource)
        if not r.can(ctx, "create"):
            raise ToolError(f"You are not allowed to create {r.get_plural_label().lower()}.")
        host = r.host()
        form = host.form(ctx, "create")
        form.fill()
        clean = self._apply(form, data)
        record = host.create(ctx, clean, form)
        ctx.panel.log_activity(ctx, "created", record)
        ctx.db.commit()
        return {"created": True, "record": self.serialize(ctx, r, record)}

    def update_record(self, ctx: Any, resource: str, id: Any, data: dict) -> dict:
        r = self.resource(ctx, resource)
        host = r.host()
        record = self._find(ctx, r, id)
        if not r.can(ctx, "update", record):
            raise ToolError("You are not allowed to change this record.")
        if host.is_trashed(record):
            raise ToolError("This record is in the trash. Restore it in the panel first.")
        form = host.form(ctx, "edit", record)
        form.fill(record)
        clean = self._apply(form, data)
        host.update(ctx, record, clean, form)
        ctx.panel.log_activity(ctx, "updated", record)
        ctx.db.commit()
        ctx.db.refresh(record)
        return {"updated": True, "record": self.serialize(ctx, r, record)}

    def delete_record(self, ctx: Any, resource: str, id: Any) -> dict:
        r = self.resource(ctx, resource)
        host = r.host()
        record = self._find(ctx, r, id)
        if not r.can(ctx, "delete", record):
            raise ToolError("You are not allowed to delete this record.")
        if host.is_trashed(record):
            raise ToolError("This record is already in the trash.")
        key = host.record_key(record)
        ctx.panel.log_activity(ctx, "deleted", record)
        host.delete(ctx, record)
        return {"deleted": True, "id": key, "trashed": bool(host.soft_delete_column)}

    def _apply(self, form: Any, data: Any) -> dict:
        """Put the AI's values into the form state, then validate like a form post."""
        if not isinstance(data, dict):
            raise ToolError("data must be an object of field values.")
        fields = {path: field for field, path, _ in form.walk_fields() if "." not in path}
        writable = {p: f for p, f in fields.items() if type(f).__name__ not in ("Placeholder", "FileUpload")}
        unknown = [k for k in data if k not in writable]
        if unknown:
            raise ToolError(f"Unknown field(s): {', '.join(unknown)}. Fields you can set: {', '.join(writable)}.")
        for key, value in data.items():
            field = writable[key]
            state = value if isinstance(value, (list, dict)) else field.to_state(value)
            if isinstance(state, (int, float)) and not isinstance(state, bool):
                state = str(state)
            set_path(form.state, key, state)
        try:
            return form.validate()
        except ValidationError as exc:
            raise ToolError("Some values are not valid.", {"errors": exc.errors}) from None

    # ------------------------------------------------------------------ helpers
    def _find(self, ctx: Any, r: Any, key: Any) -> Any:
        record = r.host().find_record(ctx, str(key))
        if record is None:
            raise ToolError(f"No {r.get_label().lower()} with id {key!r}.")
        return record

    def columns(self, r: Any) -> list:
        hidden = self.plugin.hidden_for(r)
        return [c for c in sa_inspect(r.model).columns if not SENSITIVE.search(c.key) and c.key not in hidden]

    def serialize(self, ctx: Any, r: Any, record: Any) -> dict:
        host = r.host()
        out: dict[str, Any] = {"_id": host.record_key(record), "_title": r.get_record_title(record)}
        for col in self.columns(r):
            out[col.key] = _jsonable(getattr(record, col.key, None))
        if host.is_trashed(record):
            out["_trashed"] = True
        url = host.view_url(ctx, record) or host.edit_url(ctx, record)
        if url:
            out["_url"] = ctx.panel.absolute_url(ctx, url)
        return out


def _type_name(col: Any) -> str:
    try:
        return col.type.python_type.__name__
    except NotImplementedError:
        return type(col.type).__name__.lower()


def _coerce(col: Any, value: Any) -> Any:
    """Make a JSON value comparable with a column (``"5"`` for an integer column, ISO text for dates)."""
    try:
        kind = col.type.python_type
    except NotImplementedError:
        return value
    try:
        if kind is bool and isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        if kind in (int, float, Decimal) and isinstance(value, str):
            return kind(value)
        if kind is dt.datetime and isinstance(value, str):
            return dt.datetime.fromisoformat(value)
        if kind is dt.date and isinstance(value, str):
            return dt.date.fromisoformat(value[:10])
    except (ValueError, ArithmeticError):
        raise ToolError(f"{value!r} is not a valid value for {col.key}.") from None
    return value


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, enum.Enum):
        return _jsonable(value.value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    return str(value)
