"""The ``tungsten`` command line tool.

    tungsten make:resource User --model app.models:User --generate
    tungsten make:relation-manager Customer orders
    tungsten make:page Settings
    tungsten make:widget SalesChart --type chart
    tungsten make:plugin Blog
    tungsten make:user --panel app.admin:panel
    tungsten init
"""

from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path
from typing import Any, Optional

import typer

from . import stubs

app = typer.Typer(help="Tungsten admin panel tools.", no_args_is_help=True, add_completion=False)


# ---------------------------------------------------------------------- helpers
def snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower().replace("-", "_")


def studly(name: str) -> str:
    return "".join(p[:1].upper() + p[1:] for p in re.split(r"[_\-\s]+", name) if p)


def load(target: str) -> Any:
    """Import ``package.module:attribute``."""
    if ":" not in target:
        raise typer.BadParameter(f"Use the form module:attribute (got {target!r})")
    module_name, attr = target.split(":", 1)
    sys.path.insert(0, str(Path.cwd()))
    module = importlib.import_module(module_name)
    obj = module
    for part in attr.split("."):
        obj = getattr(obj, part)
    return obj


def write(path: Path, content: str, force: bool) -> None:
    if path.exists() and not force:
        typer.secho(f"  {path} already exists (use --force to overwrite)", fg=typer.colors.YELLOW)
        raise typer.Exit(1)
    path.parent.mkdir(parents=True, exist_ok=True)
    init = path.parent / "__init__.py"
    if not init.exists():
        init.write_text("")
    path.write_text(content)
    typer.secho(f"  created {path}", fg=typer.colors.GREEN)


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
@app.command("make:resource")
def make_resource(
    name: str = typer.Argument(..., help="Model name, e.g. User"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Import path of the model, e.g. app.models:User"),
    generate: bool = typer.Option(False, "--generate", "-g", help="Build the form and table from the model columns"),
    simple: bool = typer.Option(False, "--simple", help="Manage records in modals on one page"),
    directory: Path = typer.Option(Path("admin/resources"), "--dir", "-d", help="Where to write the file"),
    force: bool = typer.Option(False, "--force", "-f"),
) -> None:
    """Create a Resource class (list/create/edit/view pages for a model)."""
    cls = studly(name.removesuffix("Resource"))
    model_path = model or f"app.models:{cls}"
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
    typer.echo(f"\nRegister it:  panel.resources([{cls}Resource])")


@app.command("make:relation-manager")
def make_relation_manager(
    resource: str = typer.Argument(..., help="Owner resource, e.g. Customer"),
    relationship: str = typer.Argument(..., help="Relationship name on the model, e.g. orders"),
    attach: bool = typer.Option(False, "--attach", help="Many-to-many: add Attach/Detach actions"),
    directory: Path = typer.Option(Path("admin/resources"), "--dir", "-d"),
    force: bool = typer.Option(False, "--force", "-f"),
) -> None:
    """Create a RelationManager to manage related records on a record page."""
    cls = studly(relationship) + "RelationManager"
    content = stubs.relation_manager(cls=cls, relationship=relationship, attach=attach)
    write(directory / f"{snake(studly(resource))}_{snake(relationship)}_relation_manager.py", content, force)
    typer.echo(f"\nAdd it to the resource:  relations = [{cls}]")


@app.command("make:page")
def make_page(
    name: str = typer.Argument(..., help="Page class name, e.g. Settings"),
    form: bool = typer.Option(False, "--form", help="Include a form with save()"),
    directory: Path = typer.Option(Path("admin/pages"), "--dir", "-d"),
    force: bool = typer.Option(False, "--force", "-f"),
) -> None:
    """Create a custom Page."""
    cls = studly(name)
    write(directory / f"{snake(cls)}.py", stubs.page(cls=cls, form=form), force)
    typer.echo(f"\nRegister it:  panel.pages([{cls}])")


@app.command("make:widget")
def make_widget(
    name: str = typer.Argument(..., help="Widget class name, e.g. SalesChart"),
    type: str = typer.Option("stats", "--type", "-t", help="stats, chart, table or progress"),
    directory: Path = typer.Option(Path("admin/widgets"), "--dir", "-d"),
    force: bool = typer.Option(False, "--force", "-f"),
) -> None:
    """Create a dashboard widget."""
    if type not in ("stats", "chart", "table", "progress"):
        raise typer.BadParameter("type must be stats, chart, table or progress")
    cls = studly(name)
    write(directory / f"{snake(cls)}.py", stubs.widget(cls=cls, kind=type), force)
    typer.echo(f"\nRegister it:  panel.widgets([{cls}])")


@app.command("make:plugin")
def make_plugin(
    name: str = typer.Argument(..., help="Plugin name, e.g. Blog"),
    directory: Path = typer.Option(Path("admin/plugins"), "--dir", "-d"),
    force: bool = typer.Option(False, "--force", "-f"),
) -> None:
    """Create a plugin skeleton."""
    cls = studly(name.removesuffix("Plugin")) + "Plugin"
    write(directory / f"{snake(cls)}.py", stubs.plugin(cls=cls, plugin_id=snake(name.removesuffix("Plugin"))), force)
    typer.echo(f"\nUse it:  panel.plugin({cls}())")


@app.command("make:user")
def make_user(
    panel: str = typer.Option(..., "--panel", "-p", help="Import path of your panel, e.g. app.admin:panel"),
    name: str = typer.Option(..., prompt=True),
    email: str = typer.Option(..., prompt=True),
    password: str = typer.Option(..., prompt=True, hide_input=True, confirmation_prompt=True),
    role: Optional[str] = typer.Option(None, help="Give this role (e.g. 'Super Admin'); created with * if missing"),
    extra: list[str] = typer.Option([], "--set", help="Extra attributes, e.g. --set is_admin=true"),
) -> None:
    """Create a user who can sign in to the panel."""
    from sqlalchemy import select

    from ..models import Role

    p = load(panel)
    auth = p.auth
    if not auth.enabled:
        typer.secho("This panel has no auth user model.", fg=typer.colors.RED)
        raise typer.Exit(1)
    with p.session_factory() as db:
        if auth.find_by_email(db, email):
            typer.secho(f"A user with email {email} already exists.", fg=typer.colors.RED)
            raise typer.Exit(1)
        user = auth.user_model()
        setattr(user, auth.name_field, name)
        setattr(user, auth.email_field, email)
        setattr(user, auth.password_field, auth.hash(password))
        for item in extra:
            key, _, value = item.partition("=")
            parsed: Any = {"true": True, "false": False}.get(value.lower(), value)
            setattr(user, key, parsed)
        db.add(user)
        db.commit()
        if role:
            p.create_tables()
            if not db.scalars(select(Role).where(Role.name == role)).first():
                db.add(Role(name=role, permissions=["*"] if "admin" in role.lower() else []))
                db.commit()
            auth.assign_role(db, user, role)
    typer.secho(f"User {email} created.", fg=typer.colors.GREEN)


@app.command("init")
def init(
    directory: Path = typer.Option(Path("admin"), "--dir", "-d"),
    force: bool = typer.Option(False, "--force", "-f"),
) -> None:
    """Create an admin/ package with a ready-to-mount panel."""
    write(directory / "panel.py", stubs.panel(), force)
    typer.echo("\nIn your FastAPI app:\n\n    from admin.panel import panel\n    panel.mount(app)\n")


@app.command("version")
def version() -> None:
    """Show the Tungsten version."""
    from ..panel import VERSION

    typer.echo(f"Tungsten {VERSION}")


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
