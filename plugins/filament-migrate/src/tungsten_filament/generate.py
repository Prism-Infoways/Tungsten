"""Write the Tungsten admin: models, resources, the panel app and a migration report."""

from __future__ import annotations

import copy
import datetime as dt
import keyword
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .convert import Converter, Ctx, Imports, Todo, icon_name, indent, py_value
from .filament import FilamentProject, PanelInfo, ResourceInfo, delegated, first_return, read_filament
from .laravel import (
    NO_DEFAULT,
    ColumnDef,
    LaravelProject,
    ModelDef,
    RelationDef,
    ScopeDef,
    TableDef,
    database_url,
    read_project,
    snake,
    studly,
    table_for,
)
from .php import ClassConst, Const, Node, PhpClass, Str, chain, is_literal, literal

RESERVED_ATTRS = {"metadata", "registry", "query", "__table__", "__tablename__", "__mapper__"}


@dataclass
class Result:
    files: dict[str, str]  # relative path -> content
    todos: list[Todo]
    project: LaravelProject
    filament: FilamentProject
    summary: dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------ reflection
def reflect_tables(url: str) -> dict[str, TableDef]:
    """Tables read from the live database (more exact than the migrations)."""
    from sqlalchemy import create_engine, inspect, types

    engine = create_engine(url)
    out: dict[str, TableDef] = {}
    try:
        insp = inspect(engine)
        for name in insp.get_table_names():
            table = TableDef(name, source="database")
            pk = insp.get_pk_constraint(name).get("constrained_columns") or []
            fks = {}
            for fk in insp.get_foreign_keys(name):
                if len(fk["constrained_columns"]) == 1 and fk.get("referred_table"):
                    fks[fk["constrained_columns"][0]] = (fk["referred_table"], fk["referred_columns"][0])
            uniques = {u["column_names"][0] for u in insp.get_unique_constraints(name) if len(u["column_names"]) == 1}
            for col in insp.get_columns(name):
                t = col["type"]
                try:
                    generic = t.as_generic()
                except NotImplementedError:
                    generic = t
                kind, length, precision, scale = "text", None, None, None
                if isinstance(generic, types.Boolean) or (
                        getattr(t, "display_width", None) == 1 and isinstance(generic, types.Integer)):
                    kind = "bool"
                elif isinstance(generic, types.BigInteger):
                    kind = "bigint"
                elif isinstance(generic, types.SmallInteger):
                    kind = "smallint"
                elif isinstance(generic, types.Integer):
                    kind = "int"
                elif isinstance(generic, types.Numeric) and not isinstance(generic, types.Float):
                    kind, precision, scale = "decimal", generic.precision, generic.scale
                elif isinstance(generic, types.Float):
                    kind = "float"
                elif isinstance(generic, types.DateTime):
                    kind = "datetime"
                elif isinstance(generic, types.Date):
                    kind = "date"
                elif isinstance(generic, types.Time):
                    kind = "time"
                elif isinstance(generic, types.JSON):
                    kind = "json"
                elif isinstance(generic, types.LargeBinary):
                    kind = "binary"
                elif isinstance(generic, types.String) and not isinstance(generic, types.Text):
                    kind, length = "string", getattr(generic, "length", None)
                table.add(ColumnDef(
                    name=col["name"], type=kind, length=length, precision=precision, scale=scale,
                    nullable=bool(col.get("nullable", True)), primary=col["name"] in pk,
                    autoincrement=col["name"] in pk and len(pk) == 1 and kind in ("int", "bigint", "smallint"),
                    fk=fks.get(col["name"]), unique=col["name"] in uniques,
                ))
            table.primary = list(pk)
            out[name] = table
    finally:
        engine.dispose()
    return out


# ------------------------------------------------------------------ models.py
_SA_TYPE = {
    "bigint": "BigInt", "int": "Integer", "smallint": "SmallInteger", "text": "Text", "bool": "Boolean",
    "float": "Float", "date": "Date", "datetime": "DateTime", "time": "Time", "json": "JSON", "binary": "LargeBinary",
}


def _attr(name: str) -> str:
    attr = re.sub(r"\W", "_", name)
    if attr[:1].isdigit():
        attr = "_" + attr
    if keyword.iskeyword(attr) or attr in RESERVED_ATTRS:
        attr += "_"
    return attr


def _sa_type(col: ColumnDef, cast: str | None) -> str:
    if cast:
        c = cast.lower().split(":")[0]
        if c in ("bool", "boolean"):
            return "Boolean"
        if c in ("array", "json", "object", "collection", "asarrayobject", "ascollection", "asenumcollection"):
            return "JSON"
        if c in ("datetime", "immutable_datetime", "timestamp", "custom_datetime"):
            return "DateTime"
        if c in ("date", "immutable_date"):
            return "Date"
        if c in ("int", "integer") and col.type not in ("bigint", "int", "smallint"):
            return "Integer"
        if c in ("float", "double", "real"):
            return "Float"
        if c == "decimal" and col.type != "decimal":
            places = cast.split(":")[1] if ":" in cast else "2"
            return f"Numeric(20, {places})"
    if col.type == "string":
        return f"String({col.length})" if col.length else "String(255)"
    if col.type == "decimal":
        p, s = col.precision, col.scale
        return f"Numeric({p}, {s})" if p is not None and s is not None else "Numeric"
    return _SA_TYPE.get(col.type, "Text")


def _default(col: ColumnDef, sa: str) -> str | None:
    if col.default is NO_DEFAULT:
        return None
    v = col.default
    if sa == "Boolean" and isinstance(v, (int, str)) and str(v) in ("0", "1"):
        return repr(bool(int(v)))
    if sa == "JSON" and isinstance(v, str):
        return None
    if isinstance(v, (str, int, float, bool)) or v is None:
        return repr(v) if v is not None else None
    return None


@dataclass
class _Rel:
    attr: str
    target: str
    kind: str
    fk_model: str | None = None  # model holding the FK column (for foreign_keys=)
    fk_col: str | None = None
    secondary: str | None = None
    back: str | None = None
    uselist: bool = True
    src: RelationDef | None = None


class ModelWriter:
    def __init__(self, project: LaravelProject, tables: dict[str, TableDef], todos: list[Todo]) -> None:
        self.project = project
        self.tables = {k: copy.deepcopy(v) for k, v in tables.items()}
        self.todos = todos
        self.models: dict[str, ModelDef] = {}
        self.rels: dict[str, list[_Rel]] = {}
        self.pivots: dict[str, TableDef] = {}
        self.skipped: list[str] = []
        self.runtime: set[str] = set()  # helpers the models import from tungsten_filament.runtime

    def _todo(self, model: ModelDef | None, line: int, code: str, reason: str) -> None:
        where = str(model.file.relative_to(self.project.root)) if model and model.file else "app/Models"
        self.todos.append(Todo(where, line, code, reason))

    def plan(self) -> None:
        for name, model in sorted(self.project.models.items()):
            if model.table not in self.tables:
                self.skipped.append(name)
                self._todo(model, 0, "", f"model {name}: table `{model.table}` not found in the migrations "
                                         f"(run again with --database-url to read it from the database)")
                continue
            self.models[name] = model
            self.rels[name] = []
        by_table = {m.table: n for n, m in self.models.items()}
        # resolve foreignIdFor(Model::class)
        for table in self.tables.values():
            for col in table.columns.values():
                if col.fk and col.fk[0].startswith("model:"):
                    target = col.fk[0][6:]
                    m = self.project.models.get(target)
                    col.fk = (m.table if m else table_for(target), col.fk[1])
        for name, model in self.models.items():
            for rel in model.relations:
                self._relation(name, model, rel, by_table)
        self._pair()
        self.project.converted_relations = {n: {r.src.name for r in rels if r.src} for n, rels in self.rels.items()}
        for name, model in self.models.items():
            for scope in model.scopes:
                where = str(scope.file.relative_to(self.project.root)) if scope.file else "app/Models"
                self.todos.append(Todo(where, scope.line, scope.src, scope_reason(name, scope, self.project)))
        # FKs to tables we do not generate would break the mapper: drop them
        known = set(by_table) | set(self.pivots)
        for t in list(by_table) + list(self.pivots):
            table = self.pivots.get(t) or self.tables[t]
            for col in table.columns.values():
                if col.fk and col.fk[0] not in known:
                    col.fk = None

    def _rel_todo(self, model: ModelDef, rel: RelationDef, reason: str) -> None:
        if rel.file is None:
            self._todo(model, rel.line, rel.src, reason)
        else:  # the relation is defined in a trait: point at the trait's file
            self.todos.append(Todo(str(rel.file.relative_to(self.project.root)), rel.line, rel.src, reason))

    def _relation(self, name: str, model: ModelDef, rel: RelationDef, by_table: dict[str, str]) -> None:
        kind = rel.kind.lower()
        target = rel.related
        if target not in self.models:
            reason = (f"relation {name}.{rel.name}: {rel.kind} is not converted yet" if kind not in
                      ("belongsto", "hasmany", "hasone", "belongstomany")
                      else f"relation {name}.{rel.name}: related model {target or '?'} was not converted")
            self._rel_todo(model, rel, reason)
            return
        tm = self.models[target]
        own_table, target_table = self.tables[model.table], self.tables[tm.table]
        attr = _attr(rel.name)
        if attr in own_table.columns:
            self._rel_todo(model, rel, f"relation {name}.{rel.name} has the same name as a column, skipped")
            return
        if kind == "belongsto":
            fk = rel.foreign_key or f"{snake(rel.name)}_id"
            col = own_table.columns.get(fk)
            if col is None:
                self._rel_todo(model, rel, f"relation {name}.{rel.name}: column {fk} not found")
                return
            col.fk = (tm.table, rel.other_key or tm.primary_key)
            self.rels[name].append(_Rel(attr, target, "belongsto", name, fk, uselist=False, src=rel))
        elif kind in ("hasmany", "hasone"):
            fk = rel.foreign_key or f"{snake(name)}_id"
            col = target_table.columns.get(fk)
            if col is None:
                self._rel_todo(model, rel, f"relation {name}.{rel.name}: column {tm.table}.{fk} not found")
                return
            col.fk = (model.table, rel.other_key or model.primary_key)
            self.rels[name].append(_Rel(attr, target, kind, target, fk, uselist=kind == "hasmany", src=rel))
        elif kind == "belongstomany":
            pivot = rel.pivot_table or "_".join(sorted([snake(name), snake(target)]))
            fpk = rel.pivot_fk or f"{snake(name)}_id"
            rpk = rel.pivot_rk or f"{snake(target)}_id"
            if pivot in by_table:  # the pivot has its own model: that model maps the table
                table = self.tables[pivot]
            else:
                table = self.pivots.get(pivot) or copy.deepcopy(self.tables.get(pivot)) or TableDef(pivot)
                self.pivots[pivot] = table
            for key, ref in ((fpk, model), (rpk, tm)):
                c = table.columns.get(key)
                if c is None:
                    c = ColumnDef(key, "bigint", primary=True)
                    table.add(c)
                c.fk = (ref.table, ref.primary_key)
            if not table.primary_keys:
                table.primary = [fpk, rpk]
                for k in (fpk, rpk):
                    table.columns[k].primary = True
            required = [c.name for c in table.columns.values() if not c.nullable and c.default is NO_DEFAULT
                        and not c.primary and not c.autoincrement and c.name not in (fpk, rpk)]
            if required:
                self._rel_todo(model, rel, f"pivot `{pivot}` has required columns {', '.join(required)}: "
                                                     f"adding links from the panel will fail until they get defaults")
            self.rels[name].append(_Rel(attr, target, "belongstomany", secondary=pivot, src=rel))

    def _pair(self) -> None:
        for name, rels in self.rels.items():
            for r in rels:
                if r.back:
                    continue
                for other in self.rels.get(r.target, []):
                    if other.back or other is r or other.target != name:
                        continue
                    same = (r.kind == "belongstomany" and other.kind == "belongstomany" and r.secondary == other.secondary) \
                        or (r.kind == "belongsto" and other.kind in ("hasmany", "hasone") and
                            other.fk_col == r.fk_col and other.fk_model == r.fk_model) \
                        or (r.kind in ("hasmany", "hasone") and other.kind == "belongsto" and
                            other.fk_col == r.fk_col and other.fk_model == r.fk_model)
                    if same:
                        r.back, other.back = other.attr, r.attr
                        break

    def source(self) -> str:
        lines = ['"""SQLAlchemy models for the Laravel database, made by tungsten-filament.',
                 "",
                 "They map the tables Laravel already has: nothing is created or changed in them.",
                 '"""',
                 "",
                 "from __future__ import annotations",
                 "",
                 "import datetime as dt",
                 "import enum",
                 "",
                 "from sqlalchemy import (",
                 "    JSON, BigInteger, Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, Numeric,",
                 "    SmallInteger, String, Table, Text, Time,",
                 ")",
                 "from sqlalchemy.orm import DeclarativeBase, mapped_column, relationship",
                 "",
                 "# BIGINT ids, as Laravel makes them (INTEGER on SQLite, so ids still count up there)",
                 'BigInt = BigInteger().with_variant(Integer, "sqlite")',
                 "",
                 "",
                 "def _now() -> dt.datetime:",
                 '    """Laravel saves timestamps in UTC without a time zone."""',
                 "    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)",
                 "",
                 "",
                 "class Base(DeclarativeBase):",
                 "    pass",
                 ""]
        for enum in sorted(self.project.enums.values(), key=lambda e: e.name):
            if not enum.cases:
                continue
            lines += ["", f"class {enum.name}({'str, ' if enum.backing != 'int' else 'int, '}enum.Enum):"]
            for case, value in enum.cases:
                member = _attr(case)
                lines.append(f"    {member} = {value!r}")
            if enum.labels:
                labels = {v: enum.labels[c] for c, v in enum.cases if c in enum.labels}
                lines += ["", "    def label(self) -> str:", f"        return {labels!r}.get(self.value, self.name)"]
            if enum.colors:
                colors = {v: enum.colors[c] for c, v in enum.cases if c in enum.colors}
                lines += ["", "    @classmethod", "    def colors(cls) -> dict:",
                          '        """Badge colors, for TextColumn(...).badge().color(...)."""',
                          f"        return {colors!r}"]
            lines.append("")
        for pivot, table in sorted(self.pivots.items()):
            var = _attr(pivot) + "_table"
            lines += ["", f"{var} = Table(", f"    {pivot!r},", "    Base.metadata,"]
            for col in table.columns.values():
                lines.append("    " + self._column(col, None, plain=True) + ",")
            lines += [")", ""]
        for name, model in sorted(self.models.items()):
            lines += [""] + self._model(name, model)
        if self.runtime:
            at = lines.index("from sqlalchemy.orm import DeclarativeBase, mapped_column, relationship") + 1
            lines.insert(at, f"from tungsten_filament.runtime import {', '.join(sorted(self.runtime))}")
        return "\n".join(lines).rstrip() + "\n"

    def _column(self, col: ColumnDef, cast: str | None, plain: bool = False, timestamps: bool = False,
                unique_ids: str | None = None) -> str:
        sa = _sa_type(col, cast)
        args = [sa]
        if unique_ids and col.primary and col.type == "string":
            self.runtime.add("new_uuid" if unique_ids == "uuid" else "new_ulid")
            args.append("default=" + ("new_uuid" if unique_ids == "uuid" else "new_ulid"))
        if col.fk:
            args.append(f"ForeignKey({col.fk[0] + '.' + col.fk[1]!r})")
        if col.primary:
            args.append("primary_key=True")
            if col.autoincrement and col.type in ("bigint", "int", "smallint"):
                args.append("autoincrement=True")
        else:
            args.append(f"nullable={col.nullable}")
        default = _default(col, sa)
        if default is not None:
            args.append(f"default={default}")
        elif timestamps and col.name in ("created_at", "updated_at") and sa == "DateTime":
            args.append("default=_now")
        if timestamps and col.name == "updated_at" and sa == "DateTime":
            args.append("onupdate=_now")
        if col.unique and not col.primary:
            args.append("unique=True")
        if plain:
            return f"Column({col.name!r}, " + ", ".join(args) + ")"
        attr = _attr(col.name)
        if attr != col.name:
            args.insert(0, repr(col.name))
        return f"{attr} = mapped_column(" + ", ".join(args) + ")"

    def _model(self, name: str, model: ModelDef) -> list[str]:
        table = self.tables[model.table]
        out = [f"class {name}(Base):", f"    __tablename__ = {model.table!r}", ""]
        if not table.primary_keys:
            pk = table.columns.get(model.primary_key)
            if pk is not None:
                pk.primary = True
            else:
                self._todo(model, 0, "", f"model {name}: table `{model.table}` has no primary key; mapped `id`")
                table.add(ColumnDef("id", "bigint", primary=True, autoincrement=True))
        for col in table.columns.values():
            cast = model.casts.get(col.name)
            if cast and cast.lower().startswith("encrypted"):
                self._todo(model, 0, "", f"{name}.{col.name} is encrypted by Laravel (APP_KEY): it shows as "
                                         "scrambled text in the panel")
            out.append("    " + self._column(col, cast, timestamps=model.timestamps, unique_ids=model.unique_ids))
        rels = self.rels.get(name, [])
        if rels:
            out.append("")
        for r in rels:
            args = [repr(r.target)]
            if r.secondary:
                args.append(f"secondary={r.secondary!r}")
            elif r.fk_model and r.fk_col:
                args.append(f"foreign_keys={'[' + r.fk_model + '.' + _attr(r.fk_col) + ']'!r}")
            if not r.uselist:
                args.append("uselist=False")
            if r.back:
                args.append(f"back_populates={r.back!r}")
            out.append(f"    {r.attr} = relationship({', '.join(args)})")
        title = next((c for c in ("name", "title", "label", "email", "number", "code", "slug") if c in table.columns),
                     None)
        if title:
            out += ["", "    def __str__(self) -> str:", f"        return str(self.{_attr(title)} or self.{_attr(table.primary_keys[0])})"]
        return out + [""]


# ------------------------------------------------------------------ resources
class ResourceWriter:
    def __init__(self, project: LaravelProject, fil: FilamentProject, models: dict[str, ModelDef],
                 todos: list[Todo]) -> None:
        self.project = project
        self.fil = fil
        self.models = models
        self.todos = todos

    def where(self, cls: PhpClass) -> str:
        return str(cls.file.path.relative_to(self.project.root)) if cls.file.path else cls.name

    def resource(self, info: ResourceInfo) -> tuple[str, str] | None:
        cls = info.cls
        imports = Imports()
        ctx = Ctx(self.project, cls.file, self.where(cls), imports, self.todos, model=info.model)
        if info.model not in self.models:
            ctx.todo(cls.prop("model"), f"{cls.name}: model {info.model or '?'} was not converted, resource skipped")
            return None
        imports.add("tungsten", "Resource")
        imports.add("..models", info.model)
        body: list[str] = [f"model = {info.model}"]
        attrs = self._attrs(cls, ctx, resource=True)
        body += attrs
        pages = [p for p in ("index", "create", "edit", "view") if p in info.pages] or ["index", "create", "edit"]
        if info.simple:
            body.append("simple = True")
        elif tuple(pages) != ("index", "create", "edit", "view"):
            body.append(f"pages = {tuple(pages)!r}")
        for page in info.custom_pages:
            ctx.todo(None, f"custom page `{page}` not converted: build it with tungsten.Page (docs/custom-pages.md)")
        for hook in info.page_hooks:
            ctx.todo(None, f"page code not converted ({hook}): move it to the resource or a policy")
        for missing in info.missing_relation_managers:
            ctx.todo(None, f"relation manager {missing} not found")
        rm_sources = []
        rm_names = []
        for rm in info.relation_managers:
            src = self.relation_manager(rm, ctx)
            if src:
                rm_sources.append(src)
                rm_names.append(rm.name)
        if rm_names:
            body.append(f"relations = [{', '.join(rm_names)}]")
        for method in ("getEloquentQuery", "getNavigationBadge", "canCreate", "canEdit", "canDelete", "canView",
                       "canViewAny", "canAccess", "getGlobalSearchResultDetails", "getWidgets"):
            m = cls.method(method)
            if m is None:
                continue
            if method == "getEloquentQuery" and _only_soft_delete_scope(cls):
                continue
            ctx.todo(None, f"{method}() not converted" + {
                "getEloquentQuery": ": put the query change in `def query(cls, ctx)`",
                "getNavigationBadge": ": write `def navigation_badge(cls, ctx)`",
                "getWidgets": ": add the widgets with `widgets = [...]`",
            }.get(method, ": use a policy (docs/roles-and-permissions.md)"))
        methods = self.methods(cls, ctx, rm=False)
        doc = f'"""{cls.name}, converted from {ctx.where} by tungsten-filament."""'
        class_src = [f"class {cls.name}(Resource):"] + [indent(b) for b in body] + methods
        header = [doc, "", "from __future__ import annotations", ""] + imports.lines()
        source = "\n".join(header) + "\n\n\n" + "\n\n\n".join(rm_sources + ["\n".join(class_src)]) + "\n"
        return snake(cls.name), source

    def relation_manager(self, cls: PhpClass, parent_ctx: Ctx) -> str | None:
        ctx = Ctx(self.project, cls.file, self.where(cls), parent_ctx.imports, self.todos)
        rel = cls.prop("relationship")
        if not isinstance(rel, Str):
            ctx.todo(rel, f"{cls.name}: relationship name not found, relation manager skipped")
            return None
        ctx.imports.add("tungsten", "RelationManager")
        owner = self.project.models.get(parent_ctx.model or "")
        ctx.model = next((r.related for r in (owner.relations if owner else []) if r.name == rel.value), None)
        body = [f"relationship = {rel.value!r}"] + self._attrs(cls, ctx, resource=False)
        for method in ("canCreate", "canEdit", "canDelete", "canViewForRecord", "getTabComponents",
                       "getEloquentQuery"):
            if cls.method(method):
                ctx.todo(None, f"{cls.name}.{method}() not converted")
        methods = self.methods(cls, ctx, rm=True)
        if self._rm_title is not None and not any(b.startswith("record_title_attribute") for b in body):
            body.append(f"record_title_attribute = {self._rm_title!r}")
        return "\n".join([f"class {cls.name}(RelationManager):"] + [indent(b) for b in body] + methods)

    _rm_title: str | None = None

    def _attrs(self, cls: PhpClass, ctx: Ctx, resource: bool) -> list[str]:
        out = []
        mapping = [("slug", "slug"), ("modelLabel", "label"), ("pluralModelLabel", "plural_label"),
                   ("navigationIcon", "icon"), ("activeNavigationIcon", "active_icon"),
                   ("navigationGroup", "navigation_group"), ("navigationLabel", "navigation_label"),
                   ("navigationSort", "navigation_sort"), ("navigationParentItem", "navigation_parent"),
                   ("recordTitleAttribute", "record_title_attribute"), ("title", "title"), ("icon", "icon"),
                   ("label", "label"), ("pluralLabel", "plural_label")]
        seen = set()
        for php_name, py_name in mapping:
            if py_name in seen:
                continue
            node = cls.prop(php_name)
            if node is None:
                getter = "get" + php_name[0].upper() + php_name[1:]
                rets = cls.returns(getter)
                node = rets[0] if rets else None
            if node is None or (isinstance(node, Const) and node.name.lower() == "null"):
                continue
            if py_name in ("icon", "active_icon"):
                raw = node.value if isinstance(node, Str) else node.name if isinstance(node, ClassConst) else None
                if raw:
                    out.append(f"{py_name} = {icon_name(raw)!r}")
                    seen.add(py_name)
                continue
            if not resource and py_name in ("slug", "navigation_group", "navigation_sort", "navigation_label"):
                continue
            v = py_value(node, ctx, allow_closure=False)
            if v is None:
                ctx.todo(node, f"${php_name} not converted")
                continue
            out.append(f"{py_name} = {v}")
            seen.add(py_name)
        if resource:
            reg = cls.prop("shouldRegisterNavigation")
            if isinstance(reg, Const) and reg.name.lower() == "false":
                out.append("show_in_navigation = False")
            for node in cls.returns("getGloballySearchableAttributes"):
                if is_literal(node):
                    out.append(f"global_search_attributes = {literal(node)!r}")
                break
            tenant = cls.prop("tenantOwnershipRelationshipName")
            if isinstance(tenant, Str):
                out.append(f"tenant_ownership = {tenant.value!r}")
        return out

    def methods(self, cls: PhpClass, ctx: Ctx, rm: bool) -> list[str]:
        out = []
        conv = Converter(ctx)
        self._rm_title = None
        for php_name, arg, kind in (("form", "form", "form"), ("infolist", "infolist", "entry"),
                                    ("table", "table", "table")):
            node = first_return(cls, php_name)
            if node is None:
                continue
            target_cls = cls
            hop = delegated(node, self.project, cls)
            if hop is not None:
                node, target_cls = hop
                conv = Converter(Ctx(self.project, target_cls.file, self.where(target_cls), ctx.imports, self.todos,
                                     model=ctx.model))
            if kind == "table":
                code = conv.table(node)
                self._rm_title = self._rm_title or _record_title(node)
            else:
                code = conv.form(node, arg, kind)
            conv = Converter(ctx)
            if code is None:
                ctx.todo(node, f"{php_name}() not converted")
                continue
            out += ["", "    @classmethod", f"    def {php_name}(cls, {arg}):", indent(f"return {code}", "        ")]
        return out


def _record_title(node: Node | None) -> str | None:
    if node is None:
        return None
    _, calls = chain(node)
    for c in calls:
        if c.method == "recordTitleAttribute" and c.args and isinstance(c.args[0].value, Str):
            return c.args[0].value.value
    return None


def _only_soft_delete_scope(cls: PhpClass) -> bool:
    rets = cls.returns("getEloquentQuery")
    return bool(rets) and all("SoftDeletingScope" in r.src and "where" not in r.src.lower() for r in rets)


def tenancy_hint(model: str, scope: ScopeDef, project: LaravelProject) -> str | None:
    """``Tenancy(Company, ownership="company_id", tenants=...)`` when the scope is the usual tenant filter."""
    if not scope.column:
        return None
    attr = scope.column.removesuffix("_id")
    tenant = studly(attr) if studly(attr) in project.models else "<TenantModel>"
    return f"Tenancy({tenant}, ownership={scope.column!r}, tenants=lambda user: [user.{attr}])"


def scope_reason(model: str, scope: ScopeDef, project: LaravelProject) -> str:
    hint = tenancy_hint(model, scope, project)
    reason = (f"SECURITY: global scope {scope.name} on {model} is not converted, so the rows it hid are shown "
              f"(if it keeps tenants apart, every user now sees every tenant's rows). Use Tenancy(...) on the panel "
              f"or the resource's `query()`")
    return reason + (f", for example `{hint}`" if hint else "")


# ------------------------------------------------------------------ app.py
def app_source(project: LaravelProject, panel: PanelInfo | None, user: str | None, out_dir: Path,
               resources: list[str], driver_hint: str | None, fil: FilamentProject,
               models: dict[str, ModelDef] | None = None) -> str:
    models = project.models if models is None else models
    try:
        rel = os.path.relpath(project.root.resolve(), out_dir.resolve())
    except ValueError:
        rel = str(project.root.resolve())
    path = "/" + (panel.path.strip("/") if panel else "admin")
    brand = (panel.brand if panel and panel.brand else None) or project.env.get("APP_NAME") or "Admin"
    colors = dict(panel.colors) if panel else {}
    options = [f"path={path!r}", "engine=engine",
               'secret_key=os.environ.get("TUNGSTEN_SECRET_KEY") or laravel_secret_key(LARAVEL_PATH)',
               f"brand_name={brand!r}"]
    if colors:
        options.append(f"colors={colors!r}")
    if panel and panel.navigation_groups:
        options.append(f"navigation_groups={panel.navigation_groups!r}")
    if panel and "spa" in panel.features:
        options.append("spa=True")
    auth_line = None
    if user:
        auth_opts = [user, "hasher=LaravelHasher()"]
        if panel and "registration" in panel.features:
            auth_opts.append("registration=True")
        if panel and "emailVerification" in panel.features:
            auth_opts.append("email_verification=True")
        if panel and "passwordReset" not in panel.features:
            auth_opts.append("password_reset=False")
        if panel and "multiFactorAuthentication" in panel.features:
            auth_opts.append("two_factor=True")
        auth_line = "Auth(" + ", ".join(auth_opts) + ")"
        options.append("auth=auth")
    lines = [
        f'"""Tungsten admin for the Laravel app in {rel}, made by tungsten-filament.',
        "",
        "Run it from the folder above this one:",
        "",
        "    pip install tungsten-admin tungsten-filament uvicorn" + (f"  # and: {driver_hint}" if driver_hint else ""),
        f"    uvicorn {out_dir.name}.app:app --reload",
        "",
        f"then open http://127.0.0.1:8000{path} and sign in with a Laravel user's email and password.",
        "The database settings come from the Laravel .env, so nothing secret is stored here.",
        '"""',
        "",
        "import os",
        "from pathlib import Path",
        "",
        "from fastapi import FastAPI",
        "from sqlalchemy import create_engine",
        "from tungsten import Auth, Panel" if user else "from tungsten import Panel",
        "from tungsten_filament.runtime import LaravelHasher, laravel_database_url, laravel_secret_key"
        if user else "from tungsten_filament.runtime import laravel_database_url, laravel_secret_key",
        "",
    ]
    if user:
        lines.append(f"from .models import {user}")
    lines += ["from .resources import RESOURCES", "",
              f'LARAVEL_PATH = Path(os.environ.get("LARAVEL_PATH") or Path(__file__).resolve().parent / {rel!r})',
              'DATABASE_URL = os.environ.get("DATABASE_URL") or laravel_database_url(LARAVEL_PATH)',
              "",
              "engine = create_engine(DATABASE_URL, pool_pre_ping=True)"]
    scoped = [(name, sc) for name, m in sorted(project.models.items()) if name in models for sc in m.scopes]
    if scoped:
        lines += ["", "# TODO(filament): SECURITY: these Laravel global scopes are not converted, so their rows are",
                  "# no longer filtered and every user sees every row. Add Tenancy(...) to the Panel below",
                  "# (docs/multi-tenancy.md) or a `query()` on each resource:"]
        for name, sc in scoped:
            hint = tenancy_hint(name, sc, project)
            lines.append(f"#   {name}: {sc.name}" + (f" -> tenancy={hint}" if hint else ""))
    if auth_line:
        lines += ["", "# Laravel's bcrypt passwords work as they are; new ones are saved the Laravel way too.",
                  "# TODO(filament): Filament's canAccessPanel() rule is not copied: add can_access=lambda user: ...",
                  f"auth = {auth_line}"]
    lines += ["", "panel = Panel(", indent(",\n".join(options) + ","), ")", "panel.resources(RESOURCES)",
              "", "# Creates only Tungsten's own tables (tungsten_*). Your Laravel tables are not touched.",
              "panel.create_tables()", "", "app = FastAPI()", "panel.mount(app)", ""]
    return "\n".join(lines)


# ------------------------------------------------------------------ report
def report(result: Result, out_dir: Path, driver_hint: str | None, url_shown: str | None) -> str:
    project, fil, todos = result.project, result.filament, result.todos
    s = result.summary
    lines = [
        "# Filament to Tungsten migration report",
        "",
        f"Made by tungsten-filament on {dt.datetime.now(dt.timezone.utc):%d %b %Y} from `{project.root}` (Filament {fil.version}).",
        "",
        "## What was converted",
        "",
        f"- Models: {s['models']} of {len(project.models)}",
        f"- Resources: {s['resources']} of {len(fil.resources)}",
        f"- Relation managers: {s['relation_managers']}",
        f"- PHP enums: {len(project.enums)}",
        f"- Things to check by hand: {len(todos)} (listed below, and marked `# TODO(filament)` in the code)",
        "",
        "## Run it",
        "",
        "```bash",
        ("pip install tungsten-admin tungsten-filament uvicorn" + (f"\n{driver_hint}" if driver_hint else "")),
        f"uvicorn {out_dir.name}.app:app --reload",
        "```",
        "",
        (f"The admin uses the same database as Laravel: `{url_shown or 'set DATABASE_URL'}` (read from the "
         "Laravel `.env` each time it starts). No data is copied or changed. Tungsten adds its own small tables "
         "(names start with `tungsten_`) for roles, notifications and password resets."),
        "",
        "People sign in with the email and password they use in Filament today.",
        "",
    ]
    security = [t for t in todos if t.reason.startswith("SECURITY:")]
    if security:
        lines += ["## Security: check these first", "",
                  ("Laravel global scopes (often how tenants are kept apart) are not converted. Until you add "
                   "`Tenancy(...)` or a resource `query()`, these models show **every** row to every user "
                   "(also marked `# TODO(filament)` in `app.py`):"), ""]
        lines += [f"- {t.file}" + (f" line {t.line}" if t.line else "") + f": {t.reason.removeprefix('SECURITY: ')}"
                  for t in security]
        lines.append("")
    rest = [t for t in todos if not t.reason.startswith("SECURITY:")]
    if rest:
        lines += ["## Needs your attention", ""]
        by_file: dict[str, list[Todo]] = {}
        for t in rest:
            by_file.setdefault(t.file, []).append(t)
        for file, items in sorted(by_file.items()):
            lines += [f"### {file}", ""]
            for t in items:
                where = f"line {t.line}: " if t.line else ""
                code = " ".join(t.code.split())
                if len(code) > 160:
                    code = code[:157] + "..."
                lines.append(f"- {where}{t.reason}" + (f"  \n  `{code}`" if code else ""))
            lines.append("")
    extra = []
    for page in fil.pages:
        extra.append(f"- Page `{page.name}` ({page.file.path.relative_to(project.root)}): build it with "
                     "`tungsten make:page` (docs/custom-pages.md)")
    for widget in fil.widgets:
        extra.append(f"- Widget `{widget.name}` ({widget.file.path.relative_to(project.root)}): build it with "
                     "`tungsten make:widget` (docs/widgets.md)")
    for panel in fil.panels:
        for plugin, hint in panel.plugins:
            extra.append(f"- Filament plugin `{plugin}`: {hint}")
        for other in panel.other:
            extra.append(f"- Panel setting `->{other}()` in {panel.cls.name} was not copied")
    policies = [c for c in project.classes.values() if c.file.path and "Policies" in c.file.path.parts]
    for policy in sorted(policies, key=lambda c: c.name):
        extra.append(f"- Policy `{policy.name}`: Tungsten resources take a `policy` (docs/roles-and-permissions.md)")
    if extra:
        lines += ["## Not converted (build these in Tungsten)", ""] + extra + [""]
    if project.notes:
        lines += ["## Reading notes", ""] + [f"- {n}" for n in project.notes] + [""]
    lines += [
        "## What the converter does not do",
        "",
        "- It does not run PHP. Closures are copied only when they are short and simple; the rest are marked TODO.",
        "- Livewire components, custom Blade views, custom pages, widgets and policies need to be rebuilt.",
        "- Morph relations (morphTo, morphMany...) and has-many-through relations are not mapped yet.",
        "- Laravel global scopes (`addGlobalScope`, `#[ScopedBy]`) are not converted: they are listed above.",
        "- Laravel model events, observers, accessors and mutators do not run when the panel saves a record.",
        "",
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------ entry point
def build(laravel_root: str | Path, out_dir: str | Path = "tungsten_admin", database_url_override: str | None = None,
          ) -> Result:
    root = Path(laravel_root)
    out = Path(out_dir)
    if not (root / "app").exists():
        raise FileNotFoundError(f"{root} does not look like a Laravel project (no app/ folder)")
    project = read_project(root)
    fil = read_filament(project)
    todos: list[Todo] = []
    tables = dict(project.tables)
    if database_url_override:
        tables.update(reflect_tables(database_url_override))
    models = ModelWriter(project, tables, todos)
    models.plan()
    files: dict[str, str] = {"__init__.py": f'"""Tungsten admin converted from {root.name} by tungsten-filament."""\n',
                             "models.py": models.source()}
    writer = ResourceWriter(project, fil, models.models, todos)
    names = []
    rm_count = 0
    for info in fil.resources:
        made = writer.resource(info)
        if made is None:
            continue
        module, src = made
        files[f"resources/{module}.py"] = src
        names.append((module, info.cls.name))
        rm_count += sum(1 for _ in info.relation_managers)
    init = ['"""All converted resources."""', ""]
    init += [f"from .{module} import {name}" for module, name in names]
    init += ["", "RESOURCES = [" + ", ".join(n for _, n in names) + "]", ""]
    files["resources/__init__.py"] = "\n".join(init)
    users = [n for n, m in models.models.items() if m.is_user]
    user = "User" if "User" in users else (users[0] if users else None)
    if user is None:
        todos.append(Todo("app/Models", 0, "", "no user model found: the panel has no login (add auth=Auth(...))"))
    elif "email" not in models.tables[models.models[user].table].columns:
        todos.append(Todo("app/Models", 0, "", f"{user} has no email column: set Auth(email_field=...)"))
    panel = fil.panels[0] if fil.panels else None
    if len(fil.panels) > 1:
        todos.append(Todo(str(fil.panels[1].cls.file.path.relative_to(root)), 0, "",
                          f"{len(fil.panels)} Filament panels found; only `{panel.id}` was used for the settings"))
    url, hint = database_url(project.env, root, mask_password=True)
    if database_url_override:
        url = re.sub(r"(://[^:/@]+:)[^@]+@", r"\1***@", database_url_override)
    files["app.py"] = app_source(project, panel, user, out, [n for _, n in names], hint, fil, models.models)
    result = Result(files=files, todos=todos, project=project, filament=fil, summary={
        "models": len(models.models), "resources": len(names), "relation_managers": rm_count,
    })
    files["MIGRATION_REPORT.md"] = report(result, out, hint, url)
    return result


def write(result: Result, out_dir: str | Path, force: bool = False) -> list[Path]:
    out = Path(out_dir)
    written = []
    if out.exists() and any(out.iterdir()) and not force:
        raise FileExistsError(f"{out} is not empty: pass --force to overwrite")
    for rel, content in result.files.items():
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written
