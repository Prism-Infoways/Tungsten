import datetime as dt
import io
import json
import os
import sqlite3
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from tungsten_backups import DONE, FAILED, RUNNING, Backup, BackupError, BackupsPlugin, Busy, service, verify_backup
from tungsten_backups import engine as backup_engine
from tungsten_backups.cli import main as cli_main
from tungsten_backups.engine import write_backup

from tungsten.models import ActivityLog, DatabaseNotification

ACTION = "/admin/_tw/action"


def back_up(admin, kind="database", note=""):
    admin.get("/admin/backups")
    r = admin.post(ACTION, {"_tw_host": "resource:backups", "_tw_scope": "page", "_tw_name": "backup",
                            "kind": kind, "note": note})
    assert r.status_code in (200, 204), r.text
    # the page reloads after the action and shows the toast there
    return r.headers.get("HX-Trigger", "") + admin.get("/admin/backups").text


def rows(panel):
    with panel.db() as db:
        out = db.scalars(select(Backup).order_by(Backup.id)).all()
        for row in out:
            db.expunge(row)
        return out


# ====================================================================== the screen
def test_back_up_from_the_panel_and_download(admin, panel, plugin):
    page = admin.get("/admin/backups")
    assert page.status_code == 200 and "No backups yet" in page.text and "Back up now" in page.text

    r = back_up(admin, note="Before the price update")
    assert "Backup ready" in r
    [row] = rows(panel)
    assert row.status == DONE and row.kind == "database" and row.method == "sqlite"
    assert row.note == "Before the price update" and row.user_id == "1" and row.size > 0
    assert row.tables >= 3 and row.rows >= 4  # users, roles, role assignments...
    path = plugin.folder / row.name
    assert path.is_file() and oct(path.stat().st_mode & 0o777) == "0o600"
    assert not list(plugin.folder.glob("*.part")) and not list(plugin.folder.glob(".work-*"))
    assert (plugin.folder / ".htaccess").read_text().startswith("# Backups hold all your data")

    page = admin.get("/admin/backups").text
    assert "Ready" in page and "Download" in page

    file = admin.get(f"/admin/backups-download/{row.id}")
    assert file.status_code == 200 and file.headers["content-type"] == "application/zip"
    assert "no-store" in file.headers["cache-control"] and row.name in file.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(file.content)) as zf:
        assert {"manifest.json", "database.sqlite"} <= set(zf.namelist())
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["database"]["tables"]["users"] == 2 and manifest["kind"] == "database"

    with panel.db() as db:
        events = [a.event for a in db.scalars(select(ActivityLog).where(ActivityLog.subject_type == "Backup"))]
        bell = db.scalars(select(DatabaseNotification)).all()
    assert "created" in events and "downloaded" in events
    assert bell and bell[0].data["title"] == "Backup ready"


def test_the_copy_is_a_working_database(admin, panel, plugin, tmp_path):
    back_up(admin)
    [row] = rows(panel)
    with zipfile.ZipFile(plugin.folder / row.name) as zf:
        zf.extract("database.sqlite", tmp_path / "out")
    con = sqlite3.connect(tmp_path / "out" / "database.sqlite")
    assert [r[0] for r in con.execute("SELECT email FROM users ORDER BY id")] == ["admin@example.com",
                                                                                   "staff@example.com"]
    con.close()


def test_full_backup_saves_uploaded_files(admin, panel, plugin, tmp_path):
    storage = Path(panel.storage.root)
    (storage / "products").mkdir(parents=True)
    (storage / "products" / "photo.jpg").write_bytes(b"\xff\xd8" + b"x" * 5000)
    (storage / "notes.txt").write_text("hello")
    outside = tmp_path / "secret.txt"
    outside.write_text("not for the zip")
    os.symlink(outside, storage / "link.txt")  # links are never followed
    back_up(admin, kind="full")
    [row] = rows(panel)
    assert row.status == DONE and row.kind == "full" and row.files == 2
    with zipfile.ZipFile(plugin.folder / row.name) as zf:
        names = set(zf.namelist())
        assert {"files/storage/products/photo.jpg", "files/storage/notes.txt"} <= names
        assert "files/storage/link.txt" not in names
        assert zf.getinfo("files/storage/products/photo.jpg").compress_type == zipfile.ZIP_STORED
        assert zf.getinfo("files/storage/notes.txt").compress_type == zipfile.ZIP_DEFLATED
        assert not any(n.startswith("files/") and "backups" in n for n in names)
    assert verify_backup(plugin.folder / row.name, row.sha256) == []


def test_staff_without_permission_cannot_see_or_download(admin, staff, panel):
    back_up(admin)
    [row] = rows(panel)
    assert staff.get("/admin/backups").status_code == 403
    assert staff.get(f"/admin/backups-download/{row.id}").status_code == 403
    r = staff.post(ACTION, {"_tw_host": "resource:backups", "_tw_scope": "page", "_tw_name": "backup",
                            "kind": "database"})
    assert r.status_code == 403 or len(rows(panel)) == 1
    assert len(rows(panel)) == 1
    assert "Last backup" not in staff.get("/admin/").text  # no dashboard card either


def test_download_needs_login(http, admin, panel):
    back_up(admin)
    [row] = rows(panel)
    http.cookies.clear()
    r = http.get(f"/admin/backups-download/{row.id}", follow_redirects=False)
    assert r.status_code in (302, 303) and "login" in r.headers["location"]


def test_download_permission_alone(panel, admin, http, user_model):
    """A role with backups.manage but not backups.download sees the list but can't download."""
    from tungsten.models import Role, RoleAssignment

    back_up(admin)
    [row] = rows(panel)
    with panel.db() as db:
        role = Role(name="Backup viewer", permissions=["backups.manage"])
        db.add(role)
        db.flush()
        db.add(RoleAssignment(role_id=role.id, user_id="2"))
        db.commit()
    from conftest import PanelClient
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    panel.mount(app)
    client = PanelClient(TestClient(app))
    client.login("staff@example.com")
    page = client.get("/admin/backups")
    assert page.status_code == 200 and "Ready" in page.text
    assert client.get(f"/admin/backups-download/{row.id}").status_code == 403


@pytest.mark.parametrize("options", [{"allow": lambda ctx: False}])
def test_allow_rule(admin, panel):
    assert admin.get("/admin/backups").status_code == 403


def test_missing_and_unknown_files_are_404(admin, panel, plugin):
    back_up(admin)
    [row] = rows(panel)
    assert admin.get("/admin/backups-download/999").status_code == 404
    (plugin.folder / row.name).unlink()
    assert admin.get(f"/admin/backups-download/{row.id}").status_code == 404
    with panel.db() as db:  # a row pointing outside the folder is refused
        db.get(Backup, row.id).name = "../app.db"
        db.commit()
    assert admin.get(f"/admin/backups-download/{row.id}").status_code == 404


def test_check_and_delete(admin, panel, plugin):
    back_up(admin)
    [row] = rows(panel)
    r = admin.post(ACTION, {"_tw_host": "resource:backups", "_tw_scope": "row", "_tw_name": "verify",
                            "_tw_record": str(row.id)})
    assert "Backup is fine" in r.headers["HX-Trigger"]
    assert rows(panel)[0].verified_at is not None

    path = plugin.folder / row.name
    data = bytearray(path.read_bytes())
    data[len(data) // 3] ^= 0xFF  # damage the file
    path.write_bytes(bytes(data))
    r = admin.post(ACTION, {"_tw_host": "resource:backups", "_tw_scope": "row", "_tw_name": "verify",
                            "_tw_record": str(row.id)})
    assert "Backup has problems" in r.headers["HX-Trigger"]

    view = admin.get(f"{ACTION}?_tw_host=resource:backups&_tw_scope=row&_tw_name=view&_tw_record={row.id}",
                     headers={"HX-Request": "true"})
    assert view.status_code == 200 and "SHA-256" in view.text and row.sha256 in view.text

    r = admin.post(ACTION, {"_tw_host": "resource:backups", "_tw_scope": "row", "_tw_name": "remove",
                            "_tw_record": str(row.id)})
    assert "Deleted" in r.headers["HX-Trigger"]
    assert rows(panel) == [] and not path.exists()


def test_bulk_delete(admin, panel, plugin):
    back_up(admin)
    back_up(admin)
    ids = [str(r.id) for r in rows(panel)]
    admin.post(ACTION, {"_tw_host": "resource:backups", "_tw_scope": "bulk", "_tw_name": "remove_many",
                        "records": ids})
    assert rows(panel) == [] and not list(plugin.folder.glob("*.zip"))


# ====================================================================== failures and edge cases
def test_failed_backup_leaves_no_file_and_shows_the_error(admin, panel, plugin, monkeypatch):
    def boom(*a, **kw):
        raise BackupError("Database went away")

    monkeypatch.setattr(service, "write_backup", boom)
    r = back_up(admin)
    assert "Backup failed" in r
    [row] = rows(panel)
    assert row.status == FAILED and row.error == "Database went away" and row.finished_at
    assert not list(plugin.folder.glob("*.zip"))
    assert not (plugin.folder / ".lock").exists()  # the next backup can run
    page = admin.get("/admin/backups").text
    assert "Failed" in page and "Database went away" in page
    with panel.db() as db:
        assert db.scalars(select(DatabaseNotification)).first().data["title"] == "Backup failed"


def test_unexpected_error_is_caught(admin, panel, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("kaput")

    monkeypatch.setattr(service, "write_backup", boom)
    back_up(admin)
    [row] = rows(panel)
    assert row.status == FAILED and "RuntimeError: kaput" in row.error


def test_disk_full_while_writing(plugin, monkeypatch, panel):
    real_write = backup_engine._write_member

    def full(*a, **kw):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(backup_engine, "_write_member", full)
    row = plugin.backup()
    assert row.status == FAILED and "disk got full" in row.error
    assert not [p for p in plugin.folder.iterdir() if p.name not in (".htaccess",)]
    monkeypatch.setattr(backup_engine, "_write_member", real_write)
    assert plugin.backup().status == DONE


def test_not_enough_disk_space(admin, panel, plugin, monkeypatch):
    monkeypatch.setattr(service, "free_space", lambda path: 10)
    r = back_up(admin)
    assert "Backup not started" in r and "Not enough disk space" in r
    assert rows(panel) == [] and not (plugin.folder / ".lock").exists()


def test_one_backup_at_a_time(plugin, panel):
    service.prepare_folder(plugin.folder)
    lock = service.Lock(plugin.folder)
    lock.acquire()
    with pytest.raises(Busy):
        plugin.backup()
    lock.release()
    assert plugin.backup().status == DONE


def test_stale_lock_and_running_rows_are_cleaned(plugin, panel):
    service.prepare_folder(plugin.folder)
    (plugin.folder / ".lock").write_text("123")
    old = dt.datetime.now().timestamp() - 700
    os.utime(plugin.folder / ".lock", (old, old))
    (plugin.folder / "backup-x.zip.part").write_bytes(b"half")
    with panel.db() as db:
        db.add(Backup(name="crashed.zip", status=RUNNING))
        db.commit()
    assert plugin.backup().status == DONE
    crashed = next(r for r in rows(panel) if r.name == "crashed.zip")
    assert crashed.status == FAILED and "Stopped before it finished" in crashed.error
    assert not (plugin.folder / "backup-x.zip.part").exists()


def test_background_backup_and_table_polls(admin, panel, plugin, monkeypatch):
    import threading

    gate = threading.Event()
    real = service.write_backup

    def slow(*a, **kw):
        gate.wait(10)
        return real(*a, **kw)

    monkeypatch.setattr(service, "write_backup", slow)
    row = plugin.backup(background=True)
    assert row.status == RUNNING
    page = admin.get("/admin/backups").text
    assert "every 3s" in page and "Running" in page
    assert "already running" in back_up(admin)
    gate.set()
    for t in threading.enumerate():
        if t.name == f"tungsten-backup-{row.id}":
            t.join(10)
    assert rows(panel)[0].status == DONE
    assert "every 3s" not in admin.get("/admin/backups").text


def test_keep_prunes_old_backups_but_never_the_newest(panel, plugin):
    plugin.keep = 2
    made = [plugin.backup() for _ in range(4)]
    left = rows(panel)
    assert [r.id for r in left] == [made[2].id, made[3].id]
    assert sorted(p.name for p in plugin.folder.glob("*.zip")) == sorted(r.name for r in left)

    plugin.keep, plugin.keep_days = 0, 1
    with panel.db() as db:
        for r in db.scalars(select(Backup)):
            r.created_at = dt.datetime.now() - dt.timedelta(days=5)
        db.commit()
        service.prune(plugin, db)
    assert len(rows(panel)) == 1  # the newest stays even though it is old


def test_deleting_a_running_backup_is_refused(panel, plugin):
    with panel.db() as db:
        row = Backup(name="x.zip", status=RUNNING)
        db.add(row)
        db.commit()
        with pytest.raises(BackupError):
            service.delete_backup(plugin, db, row)


def test_folder_inside_upload_folder_is_refused(tmp_path):
    from tungsten import LocalStorage, Panel

    panel = Panel(path="/admin", storage=LocalStorage(tmp_path / "public"), secret_key="x" * 40)
    with pytest.raises(ValueError, match="inside the panel's upload folder"):
        panel.plugin(BackupsPlugin(folder=tmp_path / "public" / "backups"))
    with pytest.raises(ValueError, match="copy itself"):
        BackupsPlugin(folder=tmp_path / "b", folders={"all": tmp_path})
    with pytest.raises(ValueError):
        BackupsPlugin(every_hours=0)


def test_in_memory_sqlite(tmp_path):
    from sqlalchemy.pool import StaticPool

    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)"))
        conn.execute(text("INSERT INTO t (name) VALUES ('a'), ('b')"))
    manifest = write_backup(tmp_path / "m.zip", engine)
    assert manifest["database"]["tables"] == {"t": 2}
    assert verify_backup(tmp_path / "m.zip") == []


def test_json_fallback_for_other_databases(tmp_path, monkeypatch):
    """A database without a dump tool is saved as JSON lines, in batches, with odd types kept."""
    engine = create_engine(f"sqlite:///{tmp_path / 'j.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, price NUMERIC, data BLOB, at TIMESTAMP)"))
        for i in range(2500):
            conn.execute(text("INSERT INTO items (name, price, data, at) VALUES (:n, :p, :d, :a)"),
                         {"n": f"item {i} ✓", "p": "9.99", "d": b"\x00\x01", "a": "2026-01-01 00:00:00"})
    monkeypatch.setattr(backup_engine, "dialect_of", lambda e: "oracle")
    manifest = write_backup(tmp_path / "j.zip", engine)
    assert manifest["database"]["method"] == "json" and manifest["database"]["tables"] == {"items": 2500}
    with zipfile.ZipFile(tmp_path / "j.zip") as zf:
        lines = zf.read("tables/items.jsonl").decode().splitlines()
        assert len(lines) == 2500
        first = json.loads(lines[0])
        assert first["name"] == "item 0 ✓" and first["data"] == {"$b64": "AAE="}
        assert json.loads(zf.read("tables/_schema.json"))["items"][0]["name"] == "id"
    assert verify_backup(tmp_path / "j.zip") == []


def test_postgres_without_pg_dump_says_so(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'p.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY)"))
    monkeypatch.setattr(backup_engine, "dialect_of", lambda e: "postgresql")
    monkeypatch.setattr(backup_engine.shutil, "which", lambda name: None)
    manifest = write_backup(tmp_path / "p.zip", engine)
    assert manifest["database"]["method"] == "json" and "pg_dump is not installed" in manifest["database"]["note"]


def test_dump_tool_command_keeps_the_password_off_the_command_line(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_engine.shutil, "which", lambda name: f"/usr/bin/{name}")
    from sqlalchemy.engine import make_url

    class Fake:  # just enough of an engine: the command is built from the URL only
        def __init__(self, url):
            self.url = make_url(url)
            self.dialect = type("D", (), {"name": self.url.get_backend_name()})()

    pg = Fake("postgresql://app:s3cret@db.local:5433/shop")
    method, argv, env = backup_engine._tool_command(pg, tmp_path / "o.sql")
    assert method == "pg_dump" and "s3cret" not in " ".join(argv) and env["PGPASSWORD"] == "s3cret"
    assert argv[argv.index("--port") + 1] == "5433" and argv[-1] == "shop"
    my = Fake("mysql://app:s3cret@db.local/shop")
    method, argv, env = backup_engine._tool_command(my, tmp_path / "o.sql")
    assert method == "mysqldump" and "s3cret" not in " ".join(argv) and env["MYSQL_PWD"] == "s3cret"


def test_dump_tool_failure_hides_the_password(monkeypatch):
    class Done:
        returncode = 1
        stderr = b"pg_dump: error: password authentication failed for s3cret\n"

    monkeypatch.setattr(backup_engine.subprocess, "run", lambda *a, **kw: Done())
    with pytest.raises(BackupError) as exc:
        backup_engine._run_tool(["pg_dump"], {}, 10, "s3cret")
    assert "s3cret" not in str(exc.value) and "authentication failed" in str(exc.value)


def test_verify_finds_problems(tmp_path):
    assert verify_backup(tmp_path / "nope.zip") == ["The file is missing from the backups folder."]
    (tmp_path / "bad.zip").write_bytes(b"not a zip")
    assert "can't be read" in verify_backup(tmp_path / "bad.zip")[0]


# ====================================================================== working with other plugins
def test_other_plugins_add_folders_and_hooks_run(tmp_path, panel, plugin):
    media = tmp_path / "media"
    media.mkdir()
    (media / "a.png").write_bytes(b"png")

    class MediaPlugin:
        id = "media-library"

        def backup_folders(self):
            return {"media": media}

    class Broken:
        id = "broken"

        def backup_folders(self):
            raise RuntimeError("nope")

    panel._plugins += [MediaPlugin(), Broken()]
    seen = []
    plugin.on_backup(lambda backup, p: seen.append(backup.status))
    plugin.on_backup(lambda backup, p: 1 / 0)  # a broken hook doesn't break the backup
    row = plugin.backup("full")
    assert row.status == DONE and seen == [DONE]
    with zipfile.ZipFile(plugin.folder / row.name) as zf:
        assert "files/media-library-media/a.png" in zf.namelist()


def test_security_audit_gets_a_backup_check(tmp_path):
    pytest.importorskip("tungsten_security_audit")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from tungsten_security_audit import SecurityAuditPlugin
    from tungsten_security_audit.checks import Audit

    from tungsten import Panel

    engine = create_engine(f"sqlite:///{tmp_path / 'a.db'}")
    panel = Panel(path="/admin", session_factory=sessionmaker(engine), secret_key="x" * 40)
    audit_plugin = SecurityAuditPlugin()
    panel.plugin(audit_plugin)
    backups = BackupsPlugin(folder=tmp_path / "backups", background=False, min_free_mb=0)
    panel.plugin(backups)
    panel.create_tables(engine)
    app = FastAPI()
    panel.mount(app)
    TestClient(app).get("/admin/")  # boots the panel
    check = audit_plugin.checks[-1]
    assert check.__name__ == "check_backups"

    class Ctx:
        pass

    def result():
        with sessionmaker(engine)() as db:
            ctx = Ctx()
            ctx.panel, ctx.db, ctx.request = panel, db, None
            return check(Audit(ctx, audit_plugin))

    assert result().status == "fail"
    backups.backup()
    assert result().status == "pass"
    with sessionmaker(engine)() as db:
        for r in db.scalars(select(Backup)):
            r.created_at = dt.datetime.now() - dt.timedelta(days=30)
        db.commit()
    assert result().status == "warn" and "30 days old" in result().detail


# ====================================================================== the dashboard and schedule
def test_dashboard_card(admin, panel):
    page = admin.get("/admin/").text
    assert "Last backup" in page and "Never" in page
    back_up(admin)
    page = admin.get("/admin/").text
    assert "just now" in page and "Backups kept" in page


def test_schedule_runs_when_due_and_backs_off_after_a_failure(panel, plugin, monkeypatch):
    plugin.every_hours = 24
    assert plugin.scheduler.due()
    row = plugin.scheduler.tick()
    assert row.status == DONE and row.source == "schedule"
    assert not plugin.scheduler.due() and plugin.scheduler.tick() is None

    with panel.db() as db:
        db.query(Backup).delete()
        db.add(Backup(name="f.zip", status=FAILED, created_at=dt.datetime.now()))
        db.commit()
    assert not plugin.scheduler.due()  # waits an hour after a failure


def test_cli(panel, plugin, monkeypatch, capsys):
    import sys
    import types

    module = types.ModuleType("backup_test_app")
    module.panel = panel
    monkeypatch.setitem(sys.modules, "backup_test_app", module)
    assert cli_main(["backup_test_app:panel", "--verify"]) == 1  # nothing yet
    assert cli_main(["backup_test_app:panel", "--note", "nightly"]) == 0
    assert ".zip" in capsys.readouterr().out
    assert cli_main(["backup_test_app:panel", "--list"]) == 0
    assert "done" in capsys.readouterr().out
    assert cli_main(["backup_test_app:panel", "--verify"]) == 0
    assert rows(panel)[0].source == "cli" and rows(panel)[0].note == "nightly"
    assert cli_main(["nope_module:panel"]) == 2


def test_no_login_panel_has_no_downloads(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    from tungsten import Panel

    engine = create_engine(f"sqlite:///{tmp_path / 'n.db'}")
    panel = Panel(path="/admin", session_factory=sessionmaker(engine), secret_key="x" * 40)
    backups = BackupsPlugin(folder=tmp_path / "backups", background=False, min_free_mb=0)
    panel.plugin(backups)
    panel.create_tables(engine)
    row = backups.backup()
    app = FastAPI()
    panel.mount(app)
    client = TestClient(app)
    assert client.get(f"/admin/backups-download/{row.id}").status_code == 403
    assert "Download" not in client.get("/admin/backups").text


def test_async_panel(tmp_path):
    """Async panels run actions on the event loop; the backup still works from there."""
    pytest.importorskip("aiosqlite")
    import asyncio
    import re

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from tungsten import Panel

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'a.db'}")
    panel = Panel(path="/admin", session_factory=async_sessionmaker(engine), secret_key="x" * 40)
    backups = BackupsPlugin(folder=tmp_path / "backups", min_free_mb=0, background=False,
                            allow_without_login=True)
    panel.plugin(backups)
    panel.create_tables()
    app = FastAPI()
    panel.mount(app)
    client = TestClient(app)
    token = re.search(r'"X-CSRF-Token": "([^"]+)"', client.get("/admin/backups").text).group(1)
    r = client.post(ACTION, data={"_tw_host": "resource:backups", "_tw_scope": "page", "_tw_name": "backup",
                                  "kind": "database"}, headers={"HX-Request": "true", "X-CSRF-Token": token})
    assert r.status_code == 204
    [row] = panel.with_session(lambda db: [service.detach(db, b) for b in db.scalars(select(Backup))])
    assert row.status == DONE and row.method == "sqlite"
    assert client.get(f"/admin/backups-download/{row.id}").status_code == 200
    asyncio.run(engine.dispose())


def test_quick_create_menu_gets_a_backup_link(tmp_path):
    pytest.importorskip("tungsten_quick_create")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from tungsten_quick_create import QuickCreatePlugin

    from tungsten import Panel

    engine = create_engine(f"sqlite:///{tmp_path / 'q.db'}")
    panel = Panel(path="/admin", session_factory=sessionmaker(engine), secret_key="x" * 40)
    quick = QuickCreatePlugin()
    panel.plugin(quick)
    panel.plugin(BackupsPlugin(folder=tmp_path / "backups"))
    panel.create_tables(engine)
    app = FastAPI()
    panel.mount(app)
    TestClient(app).get("/admin/")
    assert "backups" in quick.links and quick.links["backups"].label == "Backup"
