---
title: Migrate from Filament
description: Convert a Laravel Filament admin panel to Tungsten with one command. Models, resources, forms, tables, filters, actions and relation managers are converted, on the same database and the same logins.
---

The `tungsten-filament` tool moves a Laravel [Filament](https://filamentphp.com/) admin panel to Tungsten. It reads your Laravel project and writes a Tungsten admin that works on the **same database** with the **same user logins**. Nothing in your Laravel app or its data is changed.

Tungsten copies Filament's way of building panels (`TextInput("name").required()`), so most of your Filament code has a direct match.

## Install

```bash
pip install tungsten-filament
```

It installs `tungsten-admin` too. It needs Python 3.10 or newer. PHP is not needed: the tool reads your PHP files, it does not run them.

## Check first

```bash
tungsten-filament scan path/to/laravel-app
```

This writes nothing. It prints how many models and resources it found, how many it can convert, and every part that needs a human.

## Convert

```bash
tungsten-filament convert path/to/laravel-app
```

This writes a `tungsten_admin/` folder (pick another name with `--out`):

| File | What is in it |
| --- | --- |
| `models.py` | SQLAlchemy models for your tables, your PHP enums, and the pivot tables |
| `resources/*.py` | One file per Filament resource, with its relation managers |
| `app.py` | The FastAPI app and the Tungsten panel |
| `MIGRATION_REPORT.md` | What was converted and what still needs you |

Run it:

```bash
pip install uvicorn pymysql        # pymysql for MySQL, "psycopg[binary]" for PostgreSQL
uvicorn tungsten_admin.app:app --reload
```

Open `http://127.0.0.1:8000/admin` and sign in with the email and password you use in Filament.

## Same database, same logins

- `app.py` reads `DB_CONNECTION`, `DB_HOST`, `DB_DATABASE` and the rest from the Laravel `.env` each time it starts. No password is written into the Python code. Set `DATABASE_URL` to use another database, and `LARAVEL_PATH` if the Laravel folder moves.
- The session key comes from Laravel's `APP_KEY` (hashed, never the key itself). Set `TUNGSTEN_SECRET_KEY` to use your own.
- Laravel saves passwords as bcrypt. `LaravelHasher` checks them as they are, and saves new passwords as bcrypt too, so the Laravel app keeps working with them.
- Tungsten only adds its own small tables (names start with `tungsten_`) for roles, notifications and password resets. Your Laravel tables are not created, changed or migrated.

Both apps can run side by side on the same database while you move over.

## What it converts

| Filament / Laravel | Tungsten |
| --- | --- |
| Migrations (`Schema::create`, later `Schema::table` changes, renames, drops) | Models with the right types, nulls, defaults, unique and foreign keys |
| Eloquent `belongsTo`, `hasMany`, `hasOne`, `belongsToMany` | `relationship(...)`, paired both ways, pivot tables |
| `$casts` (boolean, array, json, date, decimal, enum) | Column types; enums keep their labels and badge colors |
| `HasUuids`, `HasUlids`, `SoftDeletes`, timestamps | New ids, soft delete, `created_at` / `updated_at` filled on save |
| Resource icon, group, sort, labels, pages, `ManageRecords` | Resource settings, `pages`, `simple = True` |
| Form fields, `Section`, `Grid`, `Tabs`, `Wizard`, `Repeater`, `Builder` | The same fields and layouts |
| `->relationship('customer', 'name')`, `->options(Status::class)` | The same |
| `->rules('required|min:3')`, `->unique(ignoreRecord: true)` | `.required().min_length(3)`, `.unique()` |
| Short closures (`fn (Get $get) => $get('type') === 'company'`, `match ($state) {...}`) | Python lambdas |
| `->hiddenOn('create')`, `->default(now())`, `->default(auth()->id())` | The same as lambdas |
| Table columns, `money()`, `date('d/m/Y')`, `badge()`, `toggleable()` | The same |
| `SelectFilter`, `TernaryFilter`, `TrashedFilter`, `Filter` with a simple `where` | The same |
| Actions, bulk actions, action groups (Filament 3 and 4 names) | The same |
| Infolists and relation managers | The same |
| Panel path, brand name, colors, navigation groups | `Panel(...)` settings |

Filament 4's layout, with forms and tables in their own `Schemas/` and `Tables/` classes, is followed too.

Tables come from your migrations. If your repo has no migrations (or they are out of date), read the tables from the database itself:

```bash
tungsten-filament convert path/to/laravel-app --database-url "mysql+pymysql://user:pass@host/db"
```

## What needs you

Every part that is not converted is marked `# TODO(filament)` next to the code it belongs to, and listed in `MIGRATION_REPORT.md` with the file and line of the PHP it came from. The usual ones:

- **Long closures** and closures that call PHP code (`$record->update(...)`, `Product::where(...)`). Short ones are converted.
- **Custom actions** (`Action::make('publish')->action(...)`): rebuild them with `tungsten.actions.Action`. See [Actions](actions).
- **Custom pages and widgets**: rebuild them with `tungsten make:page` and `tungsten make:widget`. See [Custom pages](custom-pages) and [Widgets](widgets).
- **Policies and `canAccessPanel()`**: use roles and permissions or `Auth(can_access=...)`. See [Roles and permissions](roles-and-permissions).
- **Page hooks** like `mutateFormDataBeforeCreate()` and the resource's `getEloquentQuery()`.
- **Global scopes** (`addGlobalScope()` in `booted()` or in a trait's `boot<Trait>()`, and `#[ScopedBy]`). Many apps keep tenants apart this way. The converted admin does not filter those rows, so the report lists every scope first, under "Security: check these first", and suggests the matching `Tenancy(...)` when the scope is the usual `where(company_id, auth()->user()->company_id)`. See [Multi-tenancy](multi-tenancy).
- **Morph relations** (`morphTo`, `morphMany`) and has-many-through relations.
- **Laravel model events, observers, accessors and mutators** do not run when the panel saves a record.
- **Filament plugins**: the report names the Tungsten plugin to use instead, for example Shield (built-in roles), Breezy (built-in two-factor), FullCalendar ([Calendar](calendar)), Spatie backup ([Backups](backups)), Spatie media library ([Media library](media-library)) and Spatie tags ([Tags](tags)).

A filter whose query could not be converted is left out, so the panel never shows a filter that does nothing. In the same way, a column, field or filter that names a relation the model does not have is left out and listed, instead of making the page fail. Relations defined in the app's own traits (for example a `BelongsToCompany` trait) are converted like the model's own.

## Command reference

```text
tungsten-filament scan PATH [--database-url URL]
tungsten-filament convert PATH [--out FOLDER] [--database-url URL] [--force]
```

| Option | Meaning |
| --- | --- |
| `--out`, `-o` | The folder to write, a Python package (default `tungsten_admin`) |
| `--database-url` | Read tables from this database instead of the migrations |
| `--force`, `-f` | Write into a folder that is not empty |

You can also call it from Python:

```python
from tungsten_filament import build, write

result = build("path/to/laravel-app", "tungsten_admin")
print(result.summary, len(result.todos))
write(result, "tungsten_admin")
```
