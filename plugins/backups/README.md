# tungsten-backups

Back up your database from your [Tungsten](https://tungsten.prisminfoways.com/) panel and download it as a zip. Press **Back up now**, wait a moment, press **Download**. Like Spatie Backup for Filament, made for Tungsten.

Backups hold all your data, so they are kept in a **private folder** on the server and only signed-in admins can download them. There is never a public link.

## What it does

- **Back up now**: the database alone, or the database **and uploaded files** (images, documents).
- **Works with your database**: SQLite (an exact copy, safe while the app keeps writing), PostgreSQL (`pg_dump`), MySQL / MariaDB (`mysqldump`). No dump tool installed, or another database? Every table is saved as JSON instead.
- **Runs in the background**: the page doesn't wait; the list updates itself when the backup is ready.
- **Download, Check, Delete**: Check reads the whole zip back and compares every part with its SHA-256.
- **Keeps the last 10** (you choose), deletes older ones, and never deletes the newest good one.
- **Automatic backups** every few hours while your app runs, or from cron with `python -m tungsten_backups`.
- **Safe on failure**: a backup that fails (disk full, database down) leaves no half file, shows the error on its row and in the bell.
- **Checks disk space first**, and only one backup runs at a time, even with many workers.
- **Dashboard card**: when the last backup was made, how many you keep, free disk space.
- **Works with other plugins**: with [`tungsten-security-audit`](../security-audit) the audit gets a "Recent backup" check. Other plugins can add their folders to full backups.

## Install

```bash
pip install tungsten-backups
```

```python
from tungsten_backups import BackupsPlugin

panel.plugin(BackupsPlugin(folder="storage/backups"))
panel.create_tables(engine)
panel.mount(app)
```

This adds **Backups** under **Settings** and a card on the dashboard. It needs `tungsten-admin` 0.1.4 or newer.

## Options

```python
BackupsPlugin(
    folder="storage/backups",   # private folder for the zips (never inside a folder your web server serves)
    keep=10,                    # good backups to keep (0 keeps all)
    keep_days=0,                # also delete backups older than this (0: never)
    every_hours=None,           # e.g. 24 for a daily backup while the app runs
    schedule_kind="database",   # or "full" for automatic backups
    folders={},                 # more folders for full backups: {"invoices": "data/invoices"}
    include_storage=True,       # save the panel's upload folder in full backups
    use_tools=True,             # use pg_dump / mysqldump when installed
    timeout=3600,               # seconds a dump tool may run
    min_free_mb=100,            # don't start when the disk would drop below this
    max_age_days=7,             # warn when the newest backup is older
    allow=None,                 # fn(ctx) -> bool, an extra rule for who may use backups
    dashboard_widget=True,
)
```

## Who can use it

With roles on, users need the **backups.manage** permission to see the screen and **Download backups** (`backups.download`) to download. Super admins have both. Without roles every signed-in user is an admin, so use `allow=` to narrow it:

```python
BackupsPlugin(allow=lambda ctx: ctx.user.email == "owner@example.com")
```

On a panel with no login, downloads are off (anyone reaching the panel could take your data). Turn them on with `allow_without_login=True` only on a panel that is already protected another way.

Every download and delete is written to the activity log when `activity_log=True`.

## From the command line (cron)

```bash
python -m tungsten_backups myapp:panel            # back up the database
python -m tungsten_backups myapp:panel --full     # database and uploaded files
python -m tungsten_backups myapp:panel --list     # list backups
python -m tungsten_backups myapp:panel --verify   # check the newest backup
```

A daily cron line: `0 2 * * * cd /srv/app && .venv/bin/python -m tungsten_backups myapp:panel`.

## From your code

```python
backups = panel.get_plugin("backups")
backup = backups.backup("full", note="Before the import")   # waits and returns the row

@backups.on_backup
def copy_off_server(backup, plugin):
    if backup.status == "done":
        upload_to_s3(plugin.folder / backup.name)
```

Another plugin can add its own folder to full backups by having a `backup_folders()` method:

```python
class MediaLibraryPlugin(Plugin):
    id = "media-library"

    def backup_folders(self):
        return {"media": self.root}
```

## What is in the zip

```
manifest.json          what is inside, row counts, versions, and a SHA-256 for every part
database.sqlite        SQLite copy (open it with any SQLite tool)
database.sql           pg_dump / mysqldump output
tables/<name>.jsonl    every row as JSON, one per line (when no dump tool was used)
files/storage/...      uploaded files (full backups)
```

## Restoring

Restoring is done outside the panel on purpose, so a wrong click can't wipe your data. Stop the app first, then:

- **SQLite**: unzip and put `database.sqlite` in place of your database file.
- **PostgreSQL**: `psql -d mydb -f database.sql` on an empty database.
- **MySQL**: `mysql mydb < database.sql`.
- **Files**: copy `files/storage/` back into your upload folder.

## Docs

Full guide: <https://tungsten.prisminfoways.com/docs/backups>
