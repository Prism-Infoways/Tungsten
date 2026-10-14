# tungsten-filament

Move a Laravel [Filament](https://filamentphp.com/) admin to [Tungsten](https://tungsten.prisminfoways.com/), the Filament-style admin for Python and FastAPI.

```bash
pip install tungsten-filament
tungsten-filament scan path/to/laravel-app        # what converts, what needs a human (writes nothing)
tungsten-filament convert path/to/laravel-app     # writes tungsten_admin/
uvicorn tungsten_admin.app:app --reload
```

It reads your Laravel project (it does not run PHP) and writes a ready Tungsten admin:

- **Models** from your migrations (or from the live database with `--database-url`): columns, types, nulls, defaults, foreign keys, renames and drops in later migrations, `$casts`, soft deletes, UUID/ULID keys.
- **Relations** from your Eloquent models: `belongsTo`, `hasMany`, `hasOne`, `belongsToMany` with pivot tables, paired both ways.
- **PHP enums** as Python enums, with their `getLabel()` labels and `getColor()` badge colors.
- **Resources** (Filament 3 and 4): icon, group, sort, labels, pages, simple (modal) resources, global search.
- **Forms**: fields, sections, grids, tabs, wizards, repeaters with relationships, selects with relationships or enums, Laravel rules like `required|min:3`, and short closures such as `fn (Get $get) => $get('type') === 'company'`.
- **Tables**: columns, money and date formats, badges, filters (select, ternary, trashed, simple `where` queries), actions, bulk actions, default sort, empty state.
- **Infolists** and **relation managers**.
- **Panel settings**: path, brand name, colors, navigation groups.

The new admin uses the **same database** as the Laravel app, read from its `.env` (no data copy, no secrets in the code), and people sign in with the **same email and password** (Laravel bcrypt hashes work as they are).

Anything it cannot carry over is marked `# TODO(filament)` in the code and listed in `MIGRATION_REPORT.md`: custom pages, widgets, policies, Livewire, long closures, morph relations and Filament plugins (with the Tungsten plugin to use instead).

Guide: https://tungsten.prisminfoways.com/docs/filament-migration

## Tests

```bash
pip install -e ".[dev]" -e plugins/filament-migrate
pytest plugins/filament-migrate/tests
```

The tests convert two sample Laravel apps (`tests/fixtures/shop3` on Filament 3, `tests/fixtures/blog4` on Filament 4), then sign in to the result and list, create and edit records.
