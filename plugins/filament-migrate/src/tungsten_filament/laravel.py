"""Read a Laravel project: ``.env``, migrations (tables), Eloquent models and PHP enums."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .php import (
    Arg,
    Arr,
    Call,
    ClassConst,
    Closure,
    MethodCall,
    Node,
    PhpClass,
    PhpFile,
    Raw,
    Str,
    Var,
    chain,
    closure_statements,
    is_literal,
    literal,
    short,
    tokenize,
)

NO_DEFAULT = object()


# ------------------------------------------------------------------ naming
_IRREGULAR = {"person": "people", "child": "children", "man": "men", "woman": "women", "mouse": "mice",
              "goose": "geese", "foot": "feet", "tooth": "teeth", "ox": "oxen", "leaf": "leaves"}
_UNCOUNTABLE = {"equipment", "information", "rice", "money", "species", "series", "fish", "sheep", "media",
                "news", "data", "feedback", "staff", "metadata", "audio", "software", "hardware", "settings"}


def snake(name: str) -> str:
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", name)
    return re.sub(r"[\s\-]+", "_", s).lower()


def studly(name: str) -> str:
    return "".join(p[:1].upper() + p[1:] for p in re.split(r"[_\-\s.]+", name) if p)


def plural(word: str) -> str:
    low = word.lower()
    if low in _UNCOUNTABLE or low.endswith("s") and low in _IRREGULAR.values():
        return word
    if low in _IRREGULAR:
        return _IRREGULAR[low]
    if re.search(r"[^aeiou]y$", low):
        return word[:-1] + "ies"
    if re.search(r"(s|x|z|ch|sh)$", low):
        return word + "es"
    if low.endswith("fe"):
        return word[:-2] + "ves"
    return word + "s"


def singular(word: str) -> str:
    low = word.lower()
    for one, many in _IRREGULAR.items():
        if low == many:
            return one
    if low in _UNCOUNTABLE:
        return word
    if low.endswith("ies") and len(low) > 3:
        return word[:-3] + "y"
    if re.search(r"(ss|x|z|ch|sh)es$", low):
        return word[:-2]
    if low.endswith("ses"):
        return word[:-1]
    if low.endswith("s") and not low.endswith("ss"):
        return word[:-1]
    return word


def table_for(model: str) -> str:
    """Laravel's default table: ``OrderItem`` -> ``order_items``."""
    parts = snake(model).split("_")
    parts[-1] = plural(parts[-1])
    return "_".join(parts)


# ------------------------------------------------------------------ .env
def read_env(root: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    path = root / ".env"
    if not path.exists():
        path = root / ".env.example"
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if value[:1] in "\"'" and value[-1:] == value[:1] and len(value) > 1:
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].strip()
        env[key] = value
    return env


def database_url(env: dict[str, str], root: Path, mask_password: bool = False) -> tuple[str | None, str | None]:
    """A SQLAlchemy URL for the Laravel database, and a note about the driver to install."""
    if env.get("DB_URL") or env.get("DATABASE_URL"):
        url = env.get("DB_URL") or env["DATABASE_URL"]
        url = re.sub(r"^mysql://", "mysql+pymysql://", url)
        url = re.sub(r"^(pgsql|postgres)://", "postgresql+psycopg://", url)
        if mask_password:
            url = re.sub(r"(://[^:/@]+:)[^@]+@", r"\1***@", url)
        return url, None
    driver = (env.get("DB_CONNECTION") or "sqlite").lower()
    if driver == "sqlite":
        db = env.get("DB_DATABASE") or "database/database.sqlite"
        if db == ":memory:":
            return "sqlite://", None
        path = Path(db)
        if not path.is_absolute():
            path = (root / path).resolve()
        return f"sqlite:///{path}", None
    host = env.get("DB_HOST") or "127.0.0.1"
    user = env.get("DB_USERNAME") or "root"
    password = env.get("DB_PASSWORD") or ""
    name = env.get("DB_DATABASE") or "laravel"
    shown = "***" if mask_password and password else quote(password, safe="")
    auth = quote(user, safe="") + (f":{shown}" if password else "")
    if driver in ("mysql", "mariadb"):
        port = env.get("DB_PORT") or "3306"
        return f"mysql+pymysql://{auth}@{host}:{port}/{name}", "pip install pymysql"
    if driver in ("pgsql", "postgres", "postgresql"):
        port = env.get("DB_PORT") or "5432"
        return f"postgresql+psycopg://{auth}@{host}:{port}/{name}", 'pip install "psycopg[binary]"'
    if driver == "sqlsrv":
        port = env.get("DB_PORT") or "1433"
        return (f"mssql+pyodbc://{auth}@{host}:{port}/{name}?driver=ODBC+Driver+18+for+SQL+Server",
                "pip install pyodbc (and the Microsoft ODBC driver)")
    return None, f"Unknown DB_CONNECTION {driver!r}: set DATABASE_URL yourself"


# ------------------------------------------------------------------ tables
@dataclass
class ColumnDef:
    name: str
    type: str  # bigint, int, smallint, string, text, bool, decimal, float, date, datetime, time, json, binary, uuid
    length: int | None = None
    precision: int | None = None
    scale: int | None = None
    nullable: bool = False
    default: Any = NO_DEFAULT
    server_now: bool = False
    unique: bool = False
    primary: bool = False
    autoincrement: bool = False
    fk: tuple[str, str] | None = None  # (table, column); table may be "model:Customer" until resolved
    choices: list[str] | None = None


@dataclass
class TableDef:
    name: str
    columns: dict[str, ColumnDef] = field(default_factory=dict)
    primary: list[str] = field(default_factory=list)
    source: str = ""

    def add(self, col: ColumnDef) -> None:
        self.columns[col.name] = col
        if col.primary and col.name not in self.primary:
            self.primary.append(col.name)

    @property
    def primary_keys(self) -> list[str]:
        return self.primary or [c.name for c in self.columns.values() if c.primary]


_INT_TYPES = {
    "integer": "int", "tinyinteger": "smallint", "smallinteger": "smallint", "mediuminteger": "int",
    "biginteger": "bigint", "unsignedinteger": "int", "unsignedtinyinteger": "smallint",
    "unsignedsmallinteger": "smallint", "unsignedmediuminteger": "int", "unsignedbiginteger": "bigint",
    "year": "int",
}
_INCREMENTS = {"increments": "int", "tinyincrements": "smallint", "smallincrements": "smallint",
               "mediumincrements": "int", "bigincrements": "bigint"}
_TEXT_TYPES = {"text", "tinytext", "mediumtext", "longtext"}
_DATETIME = {"datetime", "datetimetz", "timestamp", "timestamptz"}
_STRINGISH = {"ipaddress": 45, "macaddress": 17, "geometry": None, "point": None, "linestring": None,
              "polygon": None, "geography": None, "multipoint": None, "multipolygon": None,
              "multilinestring": None, "geometrycollection": None}


def _arg(args: list[Arg], i: int, name: str | None = None, default: Any = None) -> Any:
    if name:
        for a in args:
            if a.name == name:
                return literal(a.value) if is_literal(a.value) else default
    positional = [a for a in args if a.name is None]
    if i < len(positional) and is_literal(positional[i].value):
        return literal(positional[i].value)
    return default


def _class_arg(args: list[Arg], i: int, file: PhpFile) -> str | None:
    positional = [a for a in args if a.name is None]
    if i < len(positional) and isinstance(positional[i].value, ClassConst) and positional[i].value.name == "class":
        return short(file.resolve(positional[i].value.cls))
    if i < len(positional) and isinstance(positional[i].value, Str):  # 'App\Models\Customer'
        return short(positional[i].value.value)
    return None


def _guess_table(column: str) -> str:
    base = column.removesuffix("_id")
    return table_for(studly(base))


class Schema:
    """Tables built by replaying the migrations in order."""

    def __init__(self) -> None:
        self.tables: dict[str, TableDef] = {}
        self.notes: list[str] = []

    def replay(self, migrations_dir: Path) -> None:
        files = sorted(p for p in migrations_dir.rglob("*.php")) if migrations_dir.exists() else []
        for path in sorted(files, key=lambda p: p.name):
            try:
                php = PhpFile.read(path)
            except Exception as exc:  # noqa: BLE001
                self.notes.append(f"{path.name}: could not read ({exc})")
                continue
            for cls in php.classes:
                up = cls.method("up")
                if up is None:
                    continue
                for call in php.find_calls("Schema", ("create", "table", "drop", "dropIfExists", "rename"),
                                           up.body_start, up.body_end):
                    self._apply(call, php, path.name)

    def _apply(self, call: Any, php: PhpFile, source: str) -> None:
        method = call.method.lower()
        args = call.args
        name = _arg(args, 0)
        if not isinstance(name, str):
            self.notes.append(f"{source}: Schema::{call.method} with a table name that is not plain text, skipped")
            return
        if method in ("drop", "dropifexists"):
            self.tables.pop(name, None)
            return
        if method == "rename":
            to = _arg(args, 1)
            if isinstance(to, str) and name in self.tables:
                table = self.tables.pop(name)
                table.name = to
                self.tables[to] = table
            return
        closure = next((a.value for a in args[1:] if isinstance(a.value, Closure)), None)
        if closure is None:
            return
        if method == "create":
            table = self.tables[name] = TableDef(name, source=source)
        else:
            table = self.tables.setdefault(name, TableDef(name, source=source))
        for stmt in closure_statements(closure):
            try:
                self._statement(table, stmt, php, source)
            except Exception as exc:  # noqa: BLE001 - one odd line must not stop the migration
                self.notes.append(f"{source}: {table.name}: skipped `{stmt.src.strip()[:80]}` ({exc})")

    def _statement(self, table: TableDef, stmt: Node, php: PhpFile, source: str) -> None:
        base, calls = chain(stmt)
        if not isinstance(base, Var) or not calls:
            return
        first, mods = calls[0], calls[1:]
        kind = first.method.lower()
        args = first.args
        cols: list[ColumnDef] = []
        name = _arg(args, 0)

        if kind == "id":
            cols = [ColumnDef(name or "id", "bigint", primary=True, autoincrement=True)]
        elif kind in _INCREMENTS:
            cols = [ColumnDef(name, _INCREMENTS[kind], primary=True, autoincrement=True)]
        elif kind in ("string", "char"):
            cols = [ColumnDef(name, "string", length=_arg(args, 1, "length", 255))]
        elif kind in _TEXT_TYPES:
            cols = [ColumnDef(name, "text")]
        elif kind in _INT_TYPES:
            cols = [ColumnDef(name, _INT_TYPES[kind])]
            if _arg(args, 1, "autoIncrement", False):
                cols[0].primary = cols[0].autoincrement = True
        elif kind == "boolean":
            cols = [ColumnDef(name, "bool")]
        elif kind in ("decimal", "unsigneddecimal"):
            cols = [ColumnDef(name, "decimal", precision=_arg(args, 1, "total", 8), scale=_arg(args, 2, "places", 2))]
        elif kind in ("float", "double"):
            cols = [ColumnDef(name, "float")]
        elif kind == "date":
            cols = [ColumnDef(name, "date")]
        elif kind in _DATETIME:
            cols = [ColumnDef(name, "datetime")]
        elif kind in ("time", "timetz"):
            cols = [ColumnDef(name, "time")]
        elif kind in ("json", "jsonb"):
            cols = [ColumnDef(name, "json")]
        elif kind == "binary":
            cols = [ColumnDef(name, "binary")]
        elif kind in ("uuid", "foreignuuid"):
            cols = [ColumnDef(name or "uuid", "string", length=36)]
        elif kind in ("ulid", "foreignulid"):
            cols = [ColumnDef(name or "ulid", "string", length=26)]
        elif kind in ("enum", "set"):
            choices = _arg(args, 1, "allowed", None)
            cols = [ColumnDef(name, "string", length=255, choices=choices if isinstance(choices, list) else None)]
        elif kind in _STRINGISH:
            length = _STRINGISH[kind]
            cols = [ColumnDef(name, "string" if length else "text", length=length)]
        elif kind == "foreignid":
            cols = [ColumnDef(name, "bigint")]
        elif kind == "foreignidfor":
            model = _class_arg(args, 0, php)
            column = _arg(args, 1, "column", None) or (snake(model or "model") + "_id")
            cols = [ColumnDef(column, "bigint", fk=(f"model:{model}", "id") if model else None)]
        elif kind in ("morphs", "nullablemorphs", "uuidmorphs", "nullableuuidmorphs", "ulidmorphs",
                      "nullableulidmorphs"):
            nullable = kind.startswith("nullable")
            id_type = "string" if "uuid" in kind or "ulid" in kind else "bigint"
            cols = [ColumnDef(f"{name}_type", "string", length=255, nullable=nullable),
                    ColumnDef(f"{name}_id", id_type, length=36 if "uuid" in kind else 26 if "ulid" in kind else None,
                              nullable=nullable)]
        elif kind in ("timestamps", "nullabletimestamps", "timestampstz"):
            cols = [ColumnDef("created_at", "datetime", nullable=True), ColumnDef("updated_at", "datetime", nullable=True)]
        elif kind in ("softdeletes", "softdeletestz"):
            cols = [ColumnDef(name or "deleted_at", "datetime", nullable=True)]
        elif kind == "remembertoken":
            cols = [ColumnDef("remember_token", "string", length=100, nullable=True)]
        elif kind == "foreign":
            columns = name if isinstance(name, list) else [name]
            ref_col, ref_table = "id", None
            for m in mods:
                if m.method == "references":
                    ref_col = _arg(m.args, 0, None, "id")
                    ref_col = ref_col[0] if isinstance(ref_col, list) else ref_col
                elif m.method == "on":
                    ref_table = _arg(m.args, 0)
            if len(columns) == 1 and columns[0] in table.columns and ref_table:
                table.columns[columns[0]].fk = (ref_table, ref_col)
            return
        elif kind == "primary":
            keys = name if isinstance(name, list) else [name]
            table.primary = [k for k in keys if isinstance(k, str)]
            for k in table.primary:
                if k in table.columns:
                    table.columns[k].primary = True
            return
        elif kind == "unique":
            keys = name if isinstance(name, list) else [name]
            if len(keys) == 1 and keys[0] in table.columns:
                table.columns[keys[0]].unique = True
            return
        elif kind in ("dropcolumn", "dropcolumns"):
            names = []
            for a in args:
                v = literal(a.value) if is_literal(a.value) else None
                names.extend(v if isinstance(v, list) else [v])
            for n in names:
                table.columns.pop(n, None)
            return
        elif kind == "renamecolumn":
            to = _arg(args, 1)
            if name in table.columns and isinstance(to, str):
                col = table.columns.pop(name)
                col.name = to
                table.columns[to] = col
            return
        elif kind == "droptimestamps":
            table.columns.pop("created_at", None)
            table.columns.pop("updated_at", None)
            return
        elif kind == "dropsoftdeletes":
            table.columns.pop(name or "deleted_at", None)
            return
        elif kind == "dropremembertoken":
            table.columns.pop("remember_token", None)
            return
        elif kind == "dropmorphs":
            table.columns.pop(f"{name}_type", None)
            table.columns.pop(f"{name}_id", None)
            return
        elif kind in ("index", "dropindex", "dropunique", "dropforeign", "dropprimary", "fulltext", "spatialindex",
                      "engine", "charset", "collation", "comment", "temporary", "rawindex", "dropconstrainedforeignid",
                      "dropforeignidfor", "dropconstrainedforeignidfor"):
            if kind.startswith("dropconstrained") and isinstance(name, str):
                table.columns.pop(name, None)
            return
        else:
            self.notes.append(f"{source}: {table.name}: column type `{first.method}` not known, read as text")
            if isinstance(name, str):
                cols = [ColumnDef(name, "text")]
        if not cols or not all(isinstance(c.name, str) for c in cols):
            return

        target = cols[-1]
        change = False
        for m in mods:
            mm = m.method.lower()
            if mm == "nullable":
                target.nullable = bool(_arg(m.args, 0, "value", True))
            elif mm == "default":
                if m.args and is_literal(m.args[0].value):
                    target.default = literal(m.args[0].value)
            elif mm == "unique":
                target.unique = True
            elif mm == "primary":
                target.primary = True
            elif mm == "autoincrement":
                target.autoincrement = True
                target.primary = True
            elif mm == "change":
                change = True
            elif mm in ("usecurrent",):
                target.server_now = True
            elif mm == "constrained":
                ref_table = _arg(m.args, 0, "table", None) or _guess_table(target.name)
                ref_col = _arg(m.args, 1, "column", "id")
                target.fk = (ref_table, ref_col)
            elif mm == "references":
                ref = _arg(m.args, 0, None, "id")
                target.fk = (target.fk[0] if target.fk else _guess_table(target.name), ref)
            elif mm == "on":
                ref_table = _arg(m.args, 0)
                if isinstance(ref_table, str):
                    target.fk = (ref_table, target.fk[1] if target.fk else "id")
        for col in cols:
            if change and col.name in table.columns:
                old = table.columns[col.name]
                col.fk = col.fk or old.fk
                col.primary = col.primary or old.primary
            table.add(col)


# ------------------------------------------------------------------ models
RELATION_KINDS = {
    "belongsto", "hasmany", "hasone", "belongstomany", "morphto", "morphmany", "morphone", "morphtomany",
    "morphedbymany", "hasmanythrough", "hasonethrough",
}


@dataclass
class RelationDef:
    name: str
    kind: str  # belongsTo, hasMany, hasOne, belongsToMany, ...
    related: str | None
    foreign_key: str | None = None
    other_key: str | None = None  # owner key (belongsTo) / local key (hasMany)
    pivot_table: str | None = None
    pivot_fk: str | None = None
    pivot_rk: str | None = None
    src: str = ""
    line: int = 0


@dataclass
class ModelDef:
    name: str
    table: str
    file: Path | None
    primary_key: str = "id"
    casts: dict[str, str] = field(default_factory=dict)
    fillable: list[str] = field(default_factory=list)
    relations: list[RelationDef] = field(default_factory=list)
    soft_deletes: bool = False
    is_user: bool = False
    timestamps: bool = True
    unique_ids: str | None = None  # "uuid" or "ulid" (HasUuids / HasUlids)
    notes: list[str] = field(default_factory=list)


@dataclass
class EnumDef:
    name: str
    backing: str | None
    cases: list[tuple[str, Any]]
    labels: dict[str, str] = field(default_factory=dict)
    colors: dict[str, str] = field(default_factory=dict)
    icons: dict[str, str] = field(default_factory=dict)
    file: Path | None = None


def _cast_text(node: Node | None, php: PhpFile) -> str | None:
    if isinstance(node, Str):
        return node.value
    if isinstance(node, ClassConst) and node.name == "class":
        return "enum:" + short(php.resolve(node.cls))
    if isinstance(node, Call | MethodCall | Raw):
        return None
    return None


def read_model(cls: PhpClass) -> ModelDef:
    php = cls.file
    table_node = cls.prop("table")
    model = ModelDef(name=cls.name, table=table_node.value if isinstance(table_node, Str) else table_for(cls.name),
                     file=php.path)
    pk = cls.prop("primaryKey")
    if isinstance(pk, Str):
        model.primary_key = pk.value
    ts = cls.prop("timestamps")
    if ts is not None and is_literal(ts) and literal(ts) is False:
        model.timestamps = False
    traits = {short(php.resolve(t)) for t in cls.traits}
    model.soft_deletes = "SoftDeletes" in traits
    model.unique_ids = "uuid" if "HasUuids" in traits else "ulid" if "HasUlids" in traits else None
    parent = short(php.resolve(cls.extends or ""))
    model.is_user = parent in ("Authenticatable", "User") or any(short(i) == "FilamentUser" for i in cls.implements)
    fillable = cls.prop("fillable")
    if isinstance(fillable, Arr) and is_literal(fillable):
        model.fillable = [v for v in literal(fillable) if isinstance(v, str)]
    casts_nodes: list[Node] = []
    if cls.prop("casts") is not None:
        casts_nodes.append(cls.prop("casts"))  # type: ignore[arg-type]
    casts_nodes.extend(cls.returns("casts"))
    for node in casts_nodes:
        if isinstance(node, Arr):
            for k, v in node.items:
                if isinstance(k, Str):
                    text = _cast_text(v, php)
                    if text:
                        model.casts[k.value] = text
    for mname in cls.methods:
        if mname.startswith("__") or mname in ("casts", "boot", "booted"):
            continue
        for node in cls.returns(mname):
            rel = _relation(mname, node, php)
            if rel:
                model.relations.append(rel)
            break
    return model


def _relation(name: str, node: Node, php: PhpFile) -> RelationDef | None:
    base, calls = chain(node)
    if not isinstance(base, Var) or base.name != "this" or not calls:
        return None
    first = calls[0]
    kind = first.method
    if kind.lower() not in RELATION_KINDS:
        return None
    args = first.args
    rel = RelationDef(name=name, kind=kind, related=_class_arg(args, 0, php), src=node.src, line=node.line)
    k = kind.lower()
    if k == "belongsto":
        rel.foreign_key = _arg(args, 1, "foreignKey")
        rel.other_key = _arg(args, 2, "ownerKey")
    elif k in ("hasmany", "hasone"):
        rel.foreign_key = _arg(args, 1, "foreignKey")
        rel.other_key = _arg(args, 2, "localKey")
    elif k == "belongstomany":
        rel.pivot_table = _arg(args, 1, "table")
        rel.pivot_fk = _arg(args, 2, "foreignPivotKey")
        rel.pivot_rk = _arg(args, 3, "relatedPivotKey")
        if rel.pivot_table and "\\" in str(rel.pivot_table):  # a Pivot model class name
            rel.pivot_table = table_for(short(rel.pivot_table))
        positional = [a for a in args if a.name is None]
        if len(positional) > 1 and isinstance(positional[1].value, ClassConst):
            rel.pivot_table = table_for(short(php.resolve(positional[1].value.cls)))
    return rel


def read_enum(cls: PhpClass) -> EnumDef:
    cases = []
    for name, value in cls.cases:
        cases.append((name, literal(value) if is_literal(value) else name))
    enum = EnumDef(name=cls.name, backing=cls.backing, cases=cases, file=cls.file.path)
    for method, target in (("getLabel", enum.labels), ("getColor", enum.colors), ("getIcon", enum.icons),
                           ("label", enum.labels)):
        for node in cls.returns(method):
            target.update(_match_map(node.src, cls.name))
            if target:
                break
    return enum


def _match_map(src: str, enum_name: str) -> dict[str, str]:
    """``match ($this) { self::A, self::B => 'x', static::C => __('y') }`` -> {A: x, B: x, C: y}."""
    out: dict[str, str] = {}
    if not src.lstrip().lower().startswith("match"):
        return out
    toks = tokenize("<?php " + src)
    pending: list[str] = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.kind == "name" and t.value in ("self", "static", enum_name) and i + 2 < len(toks) and \
                toks[i + 1].value == "::" and toks[i + 2].kind == "name":
            pending.append(toks[i + 2].value)
            i += 3
            continue
        if t.kind == "op" and t.value == "=>" and pending:
            j = i + 1
            # value: 'text', __('text'), 'heroicon-o-x', Color::Green (Filament color class)
            if toks[j].kind == "name" and toks[j].value in ("__", "trans", "_"):
                j += 2
            value = None
            if toks[j].kind == "str":
                value = toks[j].value
            elif toks[j].kind == "name" and j + 2 < len(toks) and toks[j + 1].value == "::":
                value = toks[j + 2].value.lower()
            if value is not None:
                for case in pending:
                    out[case] = value
            pending = []
        elif t.kind == "name" and t.value.lower() == "default":
            pending = []
        i += 1
    return out


# ------------------------------------------------------------------ project
@dataclass
class LaravelProject:
    root: Path
    env: dict[str, str]
    tables: dict[str, TableDef]
    models: dict[str, ModelDef]
    enums: dict[str, EnumDef]
    classes: dict[str, PhpClass]  # every class under app/, by short name
    notes: list[str]

    def model_for_table(self, table: str) -> ModelDef | None:
        return next((m for m in self.models.values() if m.table == table), None)


def _php_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    skip = {"vendor", "node_modules", "storage", ".git"}
    return sorted(p for p in folder.rglob("*.php") if not skip & set(p.relative_to(folder).parts))


def read_project(root: Path) -> LaravelProject:
    root = Path(root)
    notes: list[str] = []
    schema = Schema()
    schema.replay(root / "database" / "migrations")
    notes.extend(schema.notes)
    classes: dict[str, PhpClass] = {}
    models: dict[str, ModelDef] = {}
    enums: dict[str, EnumDef] = {}
    for path in _php_files(root / "app"):
        try:
            php = PhpFile.read(path)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{path.relative_to(root)}: could not read ({exc})")
            continue
        for cls in php.classes:
            classes.setdefault(cls.name, cls)
            if cls.kind == "enum":
                enums[cls.name] = read_enum(cls)
            elif cls.kind == "class" and _is_model(cls, path, root):
                try:
                    models[cls.name] = read_model(cls)
                except Exception as exc:  # noqa: BLE001
                    notes.append(f"{path.relative_to(root)}: model {cls.name} could not be read ({exc})")
    return LaravelProject(root=root, env=read_env(root), tables=schema.tables, models=models, enums=enums,
                          classes=classes, notes=notes)


def _is_model(cls: PhpClass, path: Path, root: Path) -> bool:
    parent = short(cls.file.resolve(cls.extends or ""))
    if parent in ("Model", "Authenticatable", "Pivot", "MorphPivot", "User"):
        return True
    in_models = "Models" in path.relative_to(root).parts
    return in_models and bool(cls.extends) and parent.endswith("Model")
