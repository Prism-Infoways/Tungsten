"""The ``tungsten`` command line tool.

    tungsten make:resource User --model app.models:User --generate
    tungsten make:relation-manager Customer orders
    tungsten make:page Settings
    tungsten make:widget SalesChart --type chart
    tungsten make:plugin Blog
    tungsten make:user --panel app.admin:panel
    tungsten lang:extract hi --path app
    tungsten init

Built on the standard library's ``argparse``, so the package needs no CLI dependency.
"""

from __future__ import annotations

import argparse
import getpass
import importlib
import inspect
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from . import stubs


class BadParameter(Exception):
    """A bad value on the command line: shown with the command's usage, exit code 2."""


# ---------------------------------------------------------------------- output
_COLORS = {"red": 31, "green": 32, "yellow": 33}


def secho(message: str, fg: Optional[str] = None) -> None:
    """Print a line, coloured when stdout is a terminal (and ``NO_COLOR`` is not set)."""
    stream = sys.stdout
    if fg and stream.isatty() and not os.environ.get("NO_COLOR"):
        message = f"\033[{_COLORS[fg]}m{message}\033[0m"
    print(message, file=stream)


def prompt(text: str, hide_input: bool = False, confirmation_prompt: bool = False) -> str:
    """Ask for a value until one is given; hidden input and a second confirmation are optional."""
    ask: Callable[[str], str] = getpass.getpass if hide_input else input
    try:
        while True:
            value = ask(f"{text}: ")
            if not value:
                continue
            if confirmation_prompt and ask("Repeat for confirmation: ") != value:
                print("Error: The two entered values do not match.")
                continue
            return value
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.", file=sys.stderr)
        raise SystemExit(1) from None


# ---------------------------------------------------------------------- helpers
def snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower().replace("-", "_")


def studly(name: str) -> str:
    return "".join(p[:1].upper() + p[1:] for p in re.split(r"[_\-\s]+", name) if p)


def load(target: str) -> Any:
    """Import ``package.module:attribute``."""
    if ":" not in target:
        raise BadParameter(f"Use the form module:attribute (got {target!r})")
    module_name, attr = target.split(":", 1)
    sys.path.insert(0, str(Path.cwd()))
    module = importlib.import_module(module_name)
    obj = module
    for part in attr.split("."):
        obj = getattr(obj, part)
    return obj


def write(path: Path, content: str, force: bool) -> None:
    if path.exists() and not force:
        secho(f"  {path} already exists (use --force to overwrite)", fg="yellow")
        raise SystemExit(1)
    path.parent.mkdir(parents=True, exist_ok=True)
    init = path.parent / "__init__.py"
    if not init.exists():
        init.write_text("")
    path.write_text(content)
    secho(f"  created {path}", fg="green")


# ---------------------------------------------------------------------- introspection
def introspect(model: Any) -> tuple[list[str], list[str], list[str], set[str]]:
    """Return (form field lines, table column lines, searchable attrs, imports) for a model."""
    from sqlalchemy import JSON, Boolean, Date, DateTime, Enum, Float, Integer, Numeric, String, Text, Time
    from sqlalchemy import inspect as sa_inspect

    mapper = sa_inspect(model)
    fk_to_rel = {}
    for rel in mapper.relationships:
        if rel.direction.name == "MANYTOONE":
            for col in rel.local_columns:
                fk_to_rel[col.key] = rel
    fields: list[str] = []
    columns: list[str] = []
    search: list[str] = []
    imports: set[str] = set()
    skip = {"created_at", "updated_at", "deleted_at", "password_hash", "remember_token"}
    for attr in mapper.column_attrs:
        col = attr.columns[0]
        name = attr.key
        if col.primary_key or name in skip:
            continue
        required = "" if col.nullable or col.default is not None or col.server_default is not None else ".required()"
        typ = col.type
        if name in fk_to_rel:
            rel = fk_to_rel[name]
            target = rel.mapper.class_
            title = next((a for a in ("name", "title", "label", "email") if a in sa_inspect(target).columns), None)
            fields.append(f'Select("{name}").label("{rel.key.replace("_", " ").title()}")'
                          f'.relationship("{rel.key}"{", " + repr(title) if title else ""}).searchable(){required}')
            imports.add("Select")
            if title:
                columns.append(f'TextColumn("{rel.key}.{title}").label("{rel.key.replace("_", " ").title()}").sortable()')
            continue
        if isinstance(typ, Boolean):
            fields.append(f'Toggle("{name}")')
            imports.add("Toggle")
            columns.append(f'IconColumn("{name}").boolean()')
        elif isinstance(typ, Enum) and typ.enum_class is not None:
            fields.append(f'Select("{name}").options({typ.enum_class.__name__}){required}')
            imports.add("Select")
            columns.append(f'TextColumn("{name}").badge().sortable()')
        elif isinstance(typ, Enum):
            fields.append(f'Select("{name}").options({list(typ.enums)!r}){required}')
            imports.add("Select")
            columns.append(f'TextColumn("{name}").badge().sortable()')
        elif isinstance(typ, DateTime):
            fields.append(f'DateTimePicker("{name}"){required}')
            imports.add("DateTimePicker")
            columns.append(f'TextColumn("{name}").datetime().sortable()')
        elif isinstance(typ, Date):
            fields.append(f'DatePicker("{name}"){required}')
            imports.add("DatePicker")
            columns.append(f'TextColumn("{name}").date().sortable()')
        elif isinstance(typ, Time):
            fields.append(f'TimePicker("{name}"){required}')
            imports.add("TimePicker")
            columns.append(f'TextColumn("{name}").time()')
        elif isinstance(typ, (Integer,)):
            fields.append(f'TextInput("{name}").integer(){required}')
            imports.add("TextInput")
            columns.append(f'TextColumn("{name}").numeric().sortable()')
        elif isinstance(typ, (Numeric, Float)):
            fields.append(f'TextInput("{name}").numeric(){required}')
            imports.add("TextInput")
            columns.append(f'TextColumn("{name}").numeric(2).sortable()')
        elif isinstance(typ, JSON):
            hint = str(getattr(model, "__annotations__", {}).get(name, ""))
            if "list" in hint.lower():
                fields.append(f'TagsInput("{name}").column_span("full")')
                imports.add("TagsInput")
            else:
                fields.append(f'KeyValue("{name}").column_span("full")')
                imports.add("KeyValue")
        elif isinstance(typ, Text):
            fields.append(f'Textarea("{name}").column_span("full"){required}')
            imports.add("Textarea")
        elif isinstance(typ, String):
            extra = ""
            if "email" in name:
                extra = ".email()"
            elif "phone" in name:
                extra = ".tel()"
            elif "url" in name or "website" in name:
                extra = ".url()"
            elif "password" in name:
                extra = ".password().revealable()"
            length = f".max_length({typ.length})" if typ.length else ""
            fields.append(f'TextInput("{name}"){extra}{required}{length}')
            imports.add("TextInput")
            if "password" not in name:
                columns.append(f'TextColumn("{name}").searchable().sortable()')
                search.append(name)
        else:
            fields.append(f'TextInput("{name}"){required}')
            imports.add("TextInput")
            columns.append(f'TextColumn("{name}")')
    if "created_at" in mapper.columns:
        columns.append('TextColumn("created_at").date().sortable().toggleable()')
    return fields, columns, search[:3], imports


# ---------------------------------------------------------------------- commands
def make_resource(
    name: str,
    model: Optional[str] = None,
    generate: bool = False,
    simple: bool = False,
    directory: Path = Path("admin/resources"),
    force: bool = False,
) -> None:
    """Create a Resource class (list/create/edit/view pages for a model)."""
    cls = studly(name.removesuffix("Resource"))
    model_path = model or f"app.models:{cls}"
    if ":" not in model_path:
        raise BadParameter(f"--model: use the form module:Class (got {model_path!r})")
    module_name, model_attr = model_path.split(":", 1)
    fields = ['TextInput("name").required().max_length(255)']
    columns = ['TextColumn("name").searchable().sortable()']
    search = ["name"]
    imports = {"TextInput"}
    soft = False
    if generate:
        model_cls = load(model_path)
        fields, columns, search, imports = introspect(model_cls)
        from sqlalchemy import inspect as sa_inspect

        soft = "deleted_at" in sa_inspect(model_cls).columns
    content = stubs.resource(
        cls=cls, model_module=module_name, model=model_attr, fields=fields, columns=columns,
        search=search, imports=sorted(imports), simple=simple, soft_deletes=soft,
    )
    write(directory / f"{snake(cls)}_resource.py", content, force)
    print(f"\nRegister it:  panel.resources([{cls}Resource])")


def make_relation_manager(
    resource: str,
    relationship: str,
    attach: bool = False,
    directory: Path = Path("admin/resources"),
    force: bool = False,
) -> None:
    """Create a RelationManager to manage related records on a record page."""
    cls = studly(relationship) + "RelationManager"
    content = stubs.relation_manager(cls=cls, relationship=relationship, attach=attach)
    write(directory / f"{snake(studly(resource))}_{snake(relationship)}_relation_manager.py", content, force)
    print(f"\nAdd it to the resource:  relations = [{cls}]")


def make_page(name: str, form: bool = False, directory: Path = Path("admin/pages"), force: bool = False) -> None:
    """Create a custom Page."""
    cls = studly(name)
    write(directory / f"{snake(cls)}.py", stubs.page(cls=cls, form=form), force)
    print(f"\nRegister it:  panel.pages([{cls}])")


def make_widget(name: str, type: str = "stats", directory: Path = Path("admin/widgets"), force: bool = False) -> None:
    """Create a dashboard widget."""
    if type not in ("stats", "chart", "table", "progress"):
        raise BadParameter("type must be stats, chart, table or progress")
    cls = studly(name)
    write(directory / f"{snake(cls)}.py", stubs.widget(cls=cls, kind=type), force)
    print(f"\nRegister it:  panel.widgets([{cls}])")


def make_plugin(name: str, directory: Path = Path("admin/plugins"), force: bool = False) -> None:
    """Create a plugin skeleton."""
    cls = studly(name.removesuffix("Plugin")) + "Plugin"
    write(directory / f"{snake(cls)}.py", stubs.plugin(cls=cls, plugin_id=snake(name.removesuffix("Plugin"))), force)
    print(f"\nUse it:  panel.plugin({cls}())")


def _attribute_value(model: Any, key: str, value: str) -> Any:
    """Turn ``--set key=value`` text into the column's type (bool, number, date, ``null``)."""
    import datetime as dt
    import decimal

    from sqlalchemy import inspect as sa_inspect

    lowered = value.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if lowered in ("null", "none"):
        return None
    try:
        python_type = sa_inspect(model).columns[key].type.python_type
    except Exception:  # noqa: BLE001 - not a column, or no python type: keep the text
        return value
    try:
        if python_type is dt.datetime:
            return dt.datetime.now() if lowered == "now" else dt.datetime.fromisoformat(value)
        if python_type is dt.date:
            return dt.date.today() if lowered in ("now", "today") else dt.date.fromisoformat(value)
        if python_type in (int, float, decimal.Decimal):
            return python_type(value)
    except (ValueError, decimal.InvalidOperation):
        raise BadParameter(f"--set {key}: {value!r} is not a valid {python_type.__name__}") from None
    return value


def make_user(
    panel: str,
    name: Optional[str] = None,
    email: Optional[str] = None,
    password: Optional[str] = None,
    role: Optional[str] = None,
    extra: Sequence[str] = (),
    verified: bool = True,
) -> None:
    """Create a user who can sign in to the panel."""
    import datetime as dt

    from sqlalchemy import select

    from ..models import Role

    if name is None:
        name = prompt("Name")
    if email is None:
        email = prompt("Email")
    if password is None:
        password = prompt("Password", hide_input=True, confirmation_prompt=True)

    p = load(panel)
    auth = p.auth
    if not auth.enabled:
        secho("This panel has no auth user model.", fg="red")
        raise SystemExit(1)
    if role:
        p.create_tables()

    def create(db: Any) -> bool:
        if auth.find_by_email(db, email):
            return False
        user = auth.user_model()
        setattr(user, auth.name_field, name)
        setattr(user, auth.email_field, email)
        setattr(user, auth.password_field, auth.hash(password))
        if auth.email_verification and verified:
            setattr(user, auth.verified_field, dt.datetime.now())  # the admin vouches for this address
        for item in extra:
            key, _, value = item.partition("=")
            setattr(user, key, _attribute_value(auth.user_model, key, value))
        db.add(user)
        db.commit()
        if role:
            if not db.scalars(select(Role).where(Role.name == role)).first():
                db.add(Role(name=role, permissions=["*"] if "admin" in role.lower() else []))
                db.commit()
            auth.assign_role(db, user, role)
        return True

    if not p.with_session(create):
        secho(f"A user with email {email} already exists.", fg="red")
        raise SystemExit(1)
    secho(f"User {email} created.", fg="green")


def init(directory: Path = Path("admin"), force: bool = False) -> None:
    """Create an admin/ package with a ready-to-mount panel."""
    write(directory / "panel.py", stubs.panel(), force)
    print("\nIn your FastAPI app:\n\n    from admin.panel import panel\n    panel.mount(app)\n")


def lang_extract(
    locale: str,
    paths: Optional[Sequence[Path]] = None,
    out: Path = Path("lang"),
    builtin: bool = False,
) -> None:
    """Collect text from your code into lang/<locale>.json, ready to translate.

    Existing translations are kept; new text is added with an empty value.
    Point the panel at the folder with ``Panel(lang_dirs=["lang"], locales=["en", "<locale>"])``.
    """
    from ..i18n import BUILTIN_DIR, extract_strings, update_language_file

    strings = extract_strings(list(paths or [Path(".")]))
    if builtin:
        strings |= extract_strings([BUILTIN_DIR.parent])
    else:
        # Tungsten ships these already; only keep what your app adds
        shipped = BUILTIN_DIR / f"{locale}.json"
        if shipped.is_file():
            import json

            strings -= set(json.loads(shipped.read_text(encoding="utf-8")))
    file = out / f"{locale}.json"
    added, empty = update_language_file(file, strings)
    secho(f"  {file}: {added} new, {empty} still to translate", fg="green")


def version() -> None:
    """Show the Tungsten version."""
    from ..panel import VERSION

    print(f"Tungsten {VERSION}")


# ---------------------------------------------------------------------- argument parsing
class _HelpFormatter(argparse.RawDescriptionHelpFormatter):
    def __init__(self, prog: str) -> None:
        super().__init__(prog, max_help_position=32)

    def _format_action(self, action: argparse.Action) -> str:
        # list the commands one per line, without argparse's "{a,b,c}" header line
        if isinstance(action, argparse._SubParsersAction):
            return "".join(self._format_action(a) for a in action._get_subactions())
        return super()._format_action(action)


class _Toggle(argparse.Action):
    """A ``--on/--off`` flag pair sharing one destination, e.g. ``--verified/--unverified``."""

    def __init__(self, option_strings: list[str], dest: str, off: Sequence[str] = (), **kwargs: Any) -> None:
        self.off = tuple(off)
        super().__init__([*option_strings, *self.off], dest, nargs=0, **kwargs)

    def __call__(self, parser: Any, namespace: Any, values: Any, option_string: Optional[str] = None) -> None:
        setattr(namespace, self.dest, option_string not in self.off)


def _command(sub: Any, name: str, func: Callable[..., None]) -> argparse.ArgumentParser:
    doc = inspect.cleandoc(func.__doc__ or "")
    parser = sub.add_parser(
        name, help=doc.splitlines()[0] if doc else None, description=doc, formatter_class=_HelpFormatter,
        allow_abbrev=False,
    )
    parser.set_defaults(_func=func, _parser=parser)
    return parser


def _default(text: str, value: Any) -> str:
    return f"{text} [default: {value}]".strip()


def _dir_option(parser: argparse.ArgumentParser, default: str, help: str = "") -> None:
    parser.add_argument("--dir", "-d", dest="directory", type=Path, default=Path(default), metavar="PATH",
                        help=_default(help, default))


def _force_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--force", "-f", action="store_true", help="Overwrite an existing file")


def build_parser() -> argparse.ArgumentParser:
    """The ``tungsten`` argument parser. ``parser.commands`` maps each command name to its sub-parser."""
    parser = argparse.ArgumentParser(
        prog="tungsten", description="Tungsten admin panel tools.", formatter_class=_HelpFormatter,
        allow_abbrev=False,
    )
    sub = parser.add_subparsers(title="commands", metavar="COMMAND", dest="_command")
    commands: dict[str, argparse.ArgumentParser] = {}

    p = commands["make:resource"] = _command(sub, "make:resource", make_resource)
    p.add_argument("name", metavar="NAME", help="Model name, e.g. User")
    p.add_argument("--model", "-m", metavar="TEXT", help="Import path of the model, e.g. app.models:User")
    p.add_argument("--generate", "-g", action="store_true", help="Build the form and table from the model columns")
    p.add_argument("--simple", action="store_true", help="Manage records in modals on one page")
    _dir_option(p, "admin/resources", "Where to write the file")
    _force_option(p)

    p = commands["make:relation-manager"] = _command(sub, "make:relation-manager", make_relation_manager)
    p.add_argument("resource", metavar="RESOURCE", help="Owner resource, e.g. Customer")
    p.add_argument("relationship", metavar="RELATIONSHIP", help="Relationship name on the model, e.g. orders")
    p.add_argument("--attach", action="store_true", help="Many-to-many: add Attach/Detach actions")
    _dir_option(p, "admin/resources")
    _force_option(p)

    p = commands["make:page"] = _command(sub, "make:page", make_page)
    p.add_argument("name", metavar="NAME", help="Page class name, e.g. Settings")
    p.add_argument("--form", action="store_true", help="Include a form with save()")
    _dir_option(p, "admin/pages")
    _force_option(p)

    p = commands["make:widget"] = _command(sub, "make:widget", make_widget)
    p.add_argument("name", metavar="NAME", help="Widget class name, e.g. SalesChart")
    p.add_argument("--type", "-t", default="stats", metavar="TEXT",
                   help=_default("stats, chart, table or progress", "stats"))
    _dir_option(p, "admin/widgets")
    _force_option(p)

    p = commands["make:plugin"] = _command(sub, "make:plugin", make_plugin)
    p.add_argument("name", metavar="NAME", help="Plugin name, e.g. Blog")
    _dir_option(p, "admin/plugins")
    _force_option(p)

    p = commands["make:user"] = _command(sub, "make:user", make_user)
    p.add_argument("--panel", "-p", required=True, metavar="TEXT",
                   help="Import path of your panel, e.g. app.admin:panel")
    p.add_argument("--name", metavar="TEXT", help="The user's name (asked for if left out)")
    p.add_argument("--email", metavar="TEXT", help="The user's email (asked for if left out)")
    p.add_argument("--password", metavar="TEXT", help="The password (asked for twice, hidden, if left out)")
    p.add_argument("--role", metavar="TEXT",
                   help="Give this role (e.g. 'Super Admin'). A missing role is created: with every permission (*) "
                        "when its name contains 'admin', otherwise with none")
    p.add_argument("--set", dest="extra", action="append", default=[], metavar="KEY=VALUE",
                   help="Extra attributes, e.g. --set is_admin=true or --set email_verified_at=now. "
                        "Values follow the column type (true/false, numbers, dates, now, null)")
    p.add_argument("--verified", dest="verified", action=_Toggle, off=["--unverified"], default=True,
                   help="With email verification on, mark the email as verified (default) or make the user verify it")

    p = commands["init"] = _command(sub, "init", init)
    _dir_option(p, "admin")
    p.add_argument("--force", "-f", action="store_true", help="Overwrite an existing panel.py")

    p = commands["lang:extract"] = _command(sub, "lang:extract", lang_extract)
    p.add_argument("locale", metavar="LOCALE", help="Language code, e.g. hi, gu, fr")
    p.add_argument("--path", "-p", dest="paths", action="append", type=Path, metavar="PATH",
                   help=_default("Code to scan (repeatable)", "."))
    p.add_argument("--out", "-o", type=Path, default=Path("lang"), metavar="PATH",
                   help=_default("Folder for <locale>.json", "lang"))
    p.add_argument("--builtin", action="store_true", help="Also list Tungsten's own text, to override it")

    commands["version"] = _command(sub, "version", version)

    parser.commands = commands  # type: ignore[attr-defined]
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the CLI with ``argv`` (default: ``sys.argv[1:]``). Errors raise ``SystemExit`` with a non-zero code."""
    parser = build_parser()
    args, unknown = parser.parse_known_args(sys.argv[1:] if argv is None else list(argv))
    if args._command is None:
        if unknown:
            parser.error(f"unrecognized arguments: {' '.join(unknown)}")
        parser.print_help()
        raise SystemExit(2)
    if unknown:  # report it against the command, with that command's usage
        args._parser.error(f"unrecognized arguments: {' '.join(unknown)}")
    options = {k: v for k, v in vars(args).items() if not k.startswith("_")}
    try:
        args._func(**options)
    except BadParameter as exc:
        args._parser.error(f"Invalid value: {exc}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
