---
title: CLI
description: The tungsten command line tool, with generators for resources, pages, widgets and plugins, and commands for users and translations.
---

Tungsten installs a `tungsten` command. It writes starter files for you (resources, pages, widgets and more), creates users, and collects text for translation.

## Overview

```bash
tungsten init                                            # admin/panel.py
tungsten make:resource Product -m app.models:Product -g  # -g builds fields and columns from the model
tungsten make:resource Tag --simple
tungsten make:relation-manager Customer orders
tungsten make:page Settings --form
tungsten make:widget Sales --type chart                  # stats, chart, table or progress
tungsten make:plugin Blog
tungsten make:user --panel app.admin:panel --role "Super Admin"
tungsten lang:extract hi --path app                      # collect text to translate into lang/hi.json
tungsten version
```

Run `tungsten --help` for the list, or `tungsten <command> --help` for one command's options.

Some rules apply to every generator:

- Run it from your project's root folder. Files are written relative to where you are.
- It never overwrites a file that already exists. Add `--force` (or `-f`) to replace it.
- Each one has a `--dir` (or `-d`) option to change the folder it writes to.
- If the target folder has no `__init__.py`, one is created, so you can import from it right away.
- After writing the file, it prints the line you need to register the new class.

## init

Creates an `admin/` package with a ready-to-mount panel.

```bash
tungsten init
```

This writes `admin/panel.py`. It sets up a SQLAlchemy engine from the `DATABASE_URL` environment variable (default `sqlite:///app.db`), a `Panel` with `secret_key` from `SECRET_KEY`, and calls `panel.create_tables(engine)`. Lines for `auth=Auth(User)`, resources and roles are there as comments, ready to switch on.

Then mount it in your FastAPI app:

```python
from admin.panel import panel

panel.mount(app)
```

| Option | Default | What it does |
| --- | --- | --- |
| `--dir`, `-d` | `admin` | The folder to create the package in. |
| `--force`, `-f` | off | Overwrite an existing `panel.py`. |

## make:resource

Creates a [resource](resources) class for a model.

```bash
tungsten make:resource Product
```

This writes `admin/resources/product_resource.py` with a `ProductResource` class, a form with one `name` field, a table with a `name` column, edit and delete actions, and a bulk delete. You can pass `Product` or `ProductResource`; both give the same class name.

| Argument or option | Default | What it does |
| --- | --- | --- |
| `NAME` | (required) | The model name, e.g. `Product`. |
| `--model`, `-m` | `app.models:<Name>` | Where to import the model from, as `module:Class`. |
| `--generate`, `-g` | off | Build the form fields and table columns from the model's columns. |
| `--simple` | off | Make a "simple" resource that creates and edits in pop-ups on one page. |
| `--dir`, `-d` | `admin/resources` | The folder to write to. |
| `--force`, `-f` | off | Overwrite an existing file. |

### Generating from the model

With `--generate`, Tungsten imports your model and looks at its columns:

```bash
tungsten make:resource Product -m app.models:Product -g
```

```python
class ProductResource(Resource):
    model = Product
    icon = "file-text"
    # navigation_group = "Shop"
    global_search_attributes = ['name']

    @classmethod
    def form(cls, form):
        return form.schema([
            Section("Product").schema([
                TextInput("name").required().max_length(150),
                TextInput("price").numeric(),
                Toggle("is_featured"),
                Select("category_id").label("Category").relationship("category", 'name').searchable(),
            ]),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("name").searchable().sortable(),
                TextColumn("price").numeric(2).sortable(),
                IconColumn("is_featured").boolean(),
                TextColumn("category.name").label("Category").sortable(),
            ])
            .actions([EditAction(), DeleteAction()])
            .bulk_actions([DeleteBulkAction()])
        )
```

Each column type becomes a matching field and table column:

| Column type | Form field | Table column |
| --- | --- | --- |
| Foreign key (many-to-one) | `Select(...).relationship(...).searchable()` | The related record's `name`, `title`, `label` or `email` |
| `Boolean` | `Toggle` | `IconColumn(...).boolean()` |
| `Enum` | `Select(...).options(...)` | `TextColumn(...).badge()` |
| `DateTime` | `DateTimePicker` | `TextColumn(...).datetime()` |
| `Date` | `DatePicker` | `TextColumn(...).date()` |
| `Time` | `TimePicker` | `TextColumn(...).time()` |
| `Integer` | `TextInput(...).integer()` | `TextColumn(...).numeric()` |
| `Numeric`, `Float` | `TextInput(...).numeric()` | `TextColumn(...).numeric(2)` |
| `JSON` | `TagsInput` (for list type hints) or `KeyValue` | (none) |
| `Text` | `Textarea` | (none) |
| `String` | `TextInput`, with `.email()`, `.tel()`, `.url()` or `.password()` based on the column name | `TextColumn(...).searchable().sortable()` |

Some more details:

- Columns that cannot be empty and have no default get `.required()`. String lengths become `.max_length(...)`.
- The primary key and the columns `created_at`, `updated_at`, `deleted_at`, `password_hash` and `remember_token` are left out of the form. A `created_at` column is added to the table as a hideable date column.
- Up to three string columns become `global_search_attributes`.
- If the model has a `deleted_at` column, the resource also gets a `TrashedFilter` and restore and force-delete actions, for [soft deletes](resources).

The model must be importable from the folder you run the command in.

> [!TIP]
> The generated file is a starting point. Read it through, then add sections, filters and labels to suit your screens.

## make:relation-manager

Creates a [relation manager](relation-managers) for a relationship on a record page.

```bash
tungsten make:relation-manager Customer orders
```

This writes `admin/resources/customer_orders_relation_manager.py` with an `OrdersRelationManager` class. It has a small form and table, a create button, edit and delete row actions, and a bulk delete. Add it to the resource:

```python
class CustomerResource(Resource):
    model = Customer
    relations = [OrdersRelationManager]
```

For a many-to-many relationship, add `--attach` to get **Attach** and **Detach** actions instead of delete:

```bash
tungsten make:relation-manager Product tags --attach
```

| Argument or option | Default | What it does |
| --- | --- | --- |
| `RESOURCE` | (required) | The owner resource, e.g. `Customer`. Used in the file name. |
| `RELATIONSHIP` | (required) | The relationship name on the model, e.g. `orders`. |
| `--attach` | off | Many-to-many: add Attach and Detach actions. |
| `--dir`, `-d` | `admin/resources` | The folder to write to. |
| `--force`, `-f` | off | Overwrite an existing file. |

## make:page

Creates a [custom page](custom-pages).

```bash
tungsten make:page Reports
tungsten make:page Settings --form
```

Without `--form`, the page shows a small block of HTML from `content()`. With `--form`, it has a form with `mount()` (to load the starting values) and `save()` (called with the checked data on submit). The file goes to `admin/pages/<name>.py`. Register it with `panel.pages([Settings])`.

| Argument or option | Default | What it does |
| --- | --- | --- |
| `NAME` | (required) | The page class name, e.g. `Settings`. |
| `--form` | off | Include a form with `mount()` and `save()`. |
| `--dir`, `-d` | `admin/pages` | The folder to write to. |
| `--force`, `-f` | off | Overwrite an existing file. |

## make:widget

Creates a dashboard [widget](widgets).

```bash
tungsten make:widget SalesChart --type chart
```

The file goes to `admin/widgets/<name>.py`, with sample data you can replace. Register it with `panel.widgets([SalesChart])`.

| `--type` | Creates |
| --- | --- |
| `stats` (default) | A `StatsOverviewWidget` with four sample stats cards. |
| `chart` | A `ChartWidget` (line chart) with filter choices. |
| `table` | A `TableWidget` showing records of a model. |
| `progress` | A `ProgressListWidget` with progress bars. |

| Argument or option | Default | What it does |
| --- | --- | --- |
| `NAME` | (required) | The widget class name, e.g. `SalesChart`. |
| `--type`, `-t` | `stats` | `stats`, `chart`, `table` or `progress`. |
| `--dir`, `-d` | `admin/widgets` | The folder to write to. |
| `--force`, `-f` | off | Overwrite an existing file. |

## make:plugin

Creates a [plugin](plugins-and-hooks) skeleton.

```bash
tungsten make:plugin Blog
```

This writes `admin/plugins/blog_plugin.py` with a `BlogPlugin` class (plugin id `blog`) and empty `register()` and `boot()` methods. Use it with `panel.plugin(BlogPlugin())`.

| Argument or option | Default | What it does |
| --- | --- | --- |
| `NAME` | (required) | The plugin name, e.g. `Blog`. |
| `--dir`, `-d` | `admin/plugins` | The folder to write to. |
| `--force`, `-f` | off | Overwrite an existing file. |

## make:user

Creates a user who can sign in to the panel.

```bash
tungsten make:user --panel app.admin:panel
```

`--panel` tells the command where your panel is, as `module:attribute`. It must be importable from the current folder. The command asks for the name, email and password (twice, hidden), hashes the password with the panel's hasher, and saves the user using the field names from your `Auth` settings.

You can pass everything on the command line instead, for example in a setup script:

```bash
tungsten make:user --panel app.admin:panel --name "Asha Rao" --email asha@example.com \
  --password "change-me-now" --role "Super Admin" --set is_admin=true
```

| Option | What it does |
| --- | --- |
| `--panel`, `-p` | Required. Import path of your panel, e.g. `app.admin:panel`. |
| `--name` | The user's name. Asked for if left out. |
| `--email` | The user's email. Asked for if left out. |
| `--password` | The password. Asked for (twice) if left out. |
| `--role` | Give the user this role. See below. |
| `--set` | Set another attribute, as `key=value`. Repeat it for more. `true` and `false` become booleans; other values are saved as text. |

About `--role`:

- The command first creates Tungsten's tables if needed.
- If the role does not exist yet, it is created. A role whose name contains "admin" (like "Super Admin") gets every permission (`*`); any other new role starts with no permissions.
- Roles only matter when the panel uses `panel.rbac()`. See [Roles and permissions](roles-and-permissions).

The command stops with an error if the panel has no `Auth` user model, or if a user with that email already exists.

> [!NOTE]
> If your `Auth` uses `can_access` or `active_field`, make sure the new user passes those checks, for example with `--set is_admin=true` or `--set is_active=true`. Otherwise they cannot sign in.

## lang:extract

Collects the text in your code into a JSON file, ready to translate.

```bash
tungsten lang:extract hi --path app
```

This scans the `.py` and `.html` files under `app/` and writes `lang/hi.json`. It finds labels, headings, descriptions, notification titles, option labels and anything wrapped in `__("...")`. New text is added with an empty value, and translations you already have are kept, so you can run it again whenever you add screens:

```text
  lang/hi.json: 42 new, 42 still to translate
```

Fill in the values, then point the panel at the folder:

```python
panel = Panel(..., locales=["en", "hi"], lang_dirs=["lang"])
```

Text with an empty value shows in English until you translate it. For a language Tungsten ships (such as Hindi), text that Tungsten already translates is left out, unless you use `--builtin`.

| Argument or option | Default | What it does |
| --- | --- | --- |
| `LOCALE` | (required) | The language code, e.g. `hi`, `gu`, `fr`. |
| `--path`, `-p` | `.` | Code to scan. Repeat it to scan more than one folder. |
| `--out`, `-o` | `lang` | The folder for `<locale>.json`. |
| `--builtin` | off | Also list Tungsten's own text, so you can override its translations. |

See [Translations](translations).

## version

Shows the installed Tungsten version.

```bash
tungsten version
```

```text
Tungsten 0.1.0
```
