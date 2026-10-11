"""Writing and checking backup zips. No panel code here, so scripts can use it too.

A backup is one zip file::

    manifest.json           what is inside, row counts, versions, the sha256 of each part
    database.sqlite         SQLite: an exact copy made with SQLite's own backup API
    database.sql            PostgreSQL / MySQL: the output of pg_dump / mysqldump
    tables/<name>.jsonl     any other database (or no dump tool): every row as JSON, one per line
    files/<folder>/...      uploaded files, when asked for
"""

from __future__ import annotations

import base64
import datetime as dt
import decimal
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import uuid
import zipfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

FORMAT = 1
#: these are already packed, so zipping them again only costs time
STORED = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".heic", ".mp4", ".mov", ".webm", ".mkv", ".mp3",
          ".m4a", ".ogg", ".zip", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".pdf", ".docx", ".xlsx", ".pptx",
          ".woff", ".woff2"}
CHUNK = 1024 * 1024


class BackupError(Exception):
    """A problem worth showing to the admin as it is (no stack trace)."""


# ====================================================================== helpers
def human_size(n: float | None) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"  # pragma: no cover


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def sync_engine_of(engine: Any) -> Any:
    return getattr(engine, "sync_engine", engine)


def is_async(engine: Any) -> bool:
    return hasattr(engine, "sync_engine")


def dialect_of(engine: Any) -> str:
    return sync_engine_of(engine).dialect.name


def sqlite_path(engine: Any) -> Path | None:
    """The database file of a SQLite engine, or None for an in-memory database."""
    database = sync_engine_of(engine).url.database
    if not database or database == ":memory:" or "mode=memory" in database:
        return None
    if database.startswith("file:"):
        database = database[5:].split("?", 1)[0]
    return Path(database)


def database_size(engine: Any) -> int:
    """A rough size of the database, to check there is room for the backup (0 when unknown)."""
    if dialect_of(engine) == "sqlite":
        path = sqlite_path(engine)
        if path is None:
            return 0
        return sum(p.stat().st_size for p in (path, Path(f"{path}-wal")) if p.exists())
    return 0


def folder_size(path: Path, skip: Iterable[Path] = ()) -> tuple[int, int]:
    """(bytes, files) of a folder, without following links."""
    total = count = 0
    for file in walk(path, skip):
        try:
            total += file.stat().st_size
            count += 1
        except OSError:
            continue
    return total, count


def walk(root: Path, skip: Iterable[Path] = ()) -> Iterator[Path]:
    """Every regular file under ``root``. Links are never followed, so nothing outside leaks in."""
    skip = [s.resolve() for s in skip]
    for folder, dirs, files in os.walk(root, followlinks=False):
        here = Path(folder)
        dirs[:] = sorted(d for d in dirs if not (here / d).is_symlink()
                         and not any(_inside((here / d).resolve(), s) for s in skip))
        for name in sorted(files):
            path = here / name
            if not path.is_symlink() and path.is_file():
                yield path


def _inside(path: Path, folder: Path) -> bool:
    return path == folder or folder in path.parents


def free_space(path: Path) -> int:
    """Free bytes on the disk of ``path`` (or of its nearest folder that exists yet)."""
    path = Path(path)
    while not path.exists() and path.parent != path:
        path = path.parent
    return shutil.disk_usage(path).free


# ====================================================================== the database part
def _json_default(value: Any) -> Any:
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"$b64": base64.b64encode(bytes(value)).decode()}
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (set, frozenset)):
        return list(value)
    return str(value)


def _write_member(zf: zipfile.ZipFile, name: str, source: Path, compress: bool = True) -> str:
    """Copy a file into the zip in chunks and return its sha256 (the file is read only once)."""
    info = zipfile.ZipInfo.from_file(source, name)
    info.compress_type = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
    h = hashlib.sha256()
    with open(source, "rb") as src, zf.open(info, "w", force_zip64=True) as dst:
        for block in iter(lambda: src.read(CHUNK), b""):
            h.update(block)
            dst.write(block)
    return h.hexdigest()


def _sqlite_copy(engine: Any, target: Path) -> None:
    """A consistent copy, even while the app keeps writing (SQLite's online backup API)."""
    path = sqlite_path(engine)
    dst = sqlite3.connect(target)
    try:
        if path is None:
            if is_async(engine):
                raise BackupError("An in-memory SQLite database can't be backed up from an async engine.")
            raw = sync_engine_of(engine).raw_connection()
            try:
                raw.driver_connection.backup(dst)
            finally:
                raw.close()
        else:
            if not path.exists():
                raise BackupError(f"The database file {path} was not found.")
            src = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=30)
            try:
                src.backup(dst, pages=4096)  # in steps, so writers are not blocked for long
            finally:
                src.close()
        ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise BackupError(f"SQLite says the copy is damaged: {ok}")
    except sqlite3.Error as exc:
        raise BackupError(f"SQLite could not copy the database: {exc}") from exc
    finally:
        dst.close()


def _sqlite_counts(path: Path) -> dict[str, int]:
    con = sqlite3.connect(path)
    try:
        names = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {n: con.execute(f'SELECT COUNT(*) FROM "{n.replace(chr(34), chr(34) * 2)}"').fetchone()[0]
                for n in names}
    finally:
        con.close()


def _tool_command(engine: Any, out: Path) -> tuple[str, list[str], dict[str, str]] | None:
    """(method, argv, env) for pg_dump / mysqldump, or None when the tool is not installed.

    The password goes in the environment, never on the command line where ``ps`` shows it."""
    url = sync_engine_of(engine).url
    env = dict(os.environ)
    name = dialect_of(engine)
    if name == "postgresql" and shutil.which("pg_dump"):
        argv = ["pg_dump", "--no-owner", "--no-privileges", "--format=plain", "--file", str(out)]
        if url.host:
            argv += ["--host", url.host]
        if url.port:
            argv += ["--port", str(url.port)]
        if url.username:
            argv += ["--username", url.username]
        argv += ["--dbname", url.database or ""]
        if url.password:
            env["PGPASSWORD"] = str(url.password)
        return "pg_dump", argv, env
    if name in ("mysql", "mariadb"):
        tool = shutil.which("mysqldump") or shutil.which("mariadb-dump")
        if not tool:
            return None
        argv = [tool, "--single-transaction", "--quick", "--routines", "--triggers", "--result-file", str(out)]
        if url.host:
            argv += ["--host", url.host]
        if url.port:
            argv += ["--port", str(url.port)]
        if url.username:
            argv += ["--user", url.username]
        argv += [url.database or ""]
        if url.password:
            env["MYSQL_PWD"] = str(url.password)
        return "mysqldump", argv, env
    return None


def _run_tool(argv: list[str], env: dict[str, str], timeout: int, secret: str | None) -> None:
    try:
        done = subprocess.run(argv, env=env, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise BackupError(f"{Path(argv[0]).name} took longer than {timeout} seconds and was stopped.") from exc
    except OSError as exc:
        raise BackupError(f"Could not start {Path(argv[0]).name}: {exc}") from exc
    if done.returncode != 0:
        text = (done.stderr or b"").decode(errors="replace").strip().splitlines()
        message = text[-1] if text else f"exit code {done.returncode}"
        if secret:
            message = message.replace(secret, "***")
        raise BackupError(f"{Path(argv[0]).name} failed: {message}")


def _json_tables(conn: Any, zf: zipfile.ZipFile, hashes: dict[str, str]) -> dict[str, int]:
    """Every table as JSON lines, read in batches so a big table never sits in memory."""
    from sqlalchemy import MetaData, select

    meta = MetaData()
    meta.reflect(conn)
    counts: dict[str, int] = {}
    schema: dict[str, list[dict[str, Any]]] = {}
    for table in meta.sorted_tables:
        schema[table.name] = [{"name": c.name, "type": str(c.type), "nullable": c.nullable,
                               "primary_key": c.primary_key} for c in table.columns]
        name = f"tables/{table.name}.jsonl"
        h = hashlib.sha256()
        n = 0
        result = conn.execution_options(stream_results=True, yield_per=1000).execute(select(table))
        info = zipfile.ZipInfo(name, dt.datetime.now().timetuple()[:6])
        info.compress_type = zipfile.ZIP_DEFLATED
        with zf.open(info, "w", force_zip64=True) as out:
            for part in result.mappings().partitions(1000):
                chunk = "".join(json.dumps(dict(row), default=_json_default, ensure_ascii=False) + "\n"
                                for row in part).encode()
                h.update(chunk)
                out.write(chunk)
                n += len(part)
        hashes[name] = h.hexdigest()
        counts[table.name] = n
    data = json.dumps(schema, indent=1).encode()
    zf.writestr("tables/_schema.json", data, compress_type=zipfile.ZIP_DEFLATED)
    hashes["tables/_schema.json"] = hashlib.sha256(data).hexdigest()
    return counts


def _json_dump(engine: Any, zf: zipfile.ZipFile, hashes: dict[str, str]) -> dict[str, int]:
    if not is_async(engine):
        with engine.connect() as conn:
            return _json_tables(conn, zf, hashes)
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    async def go() -> dict[str, int]:
        # a private engine: the app's pooled connections belong to the app's own event loop
        private = create_async_engine(engine.url, poolclass=NullPool)
        try:
            async with private.connect() as conn:
                return await conn.run_sync(lambda c: _json_tables(c, zf, hashes))
        finally:
            await private.dispose()

    return asyncio.run(go())


def dump_database(engine: Any, zf: zipfile.ZipFile, work: Path, hashes: dict[str, str], *,
                  use_tools: bool = True, timeout: int = 3600) -> dict[str, Any]:
    """Put the database into the zip. Returns ``{"method", "counts", "note"}``."""
    name = dialect_of(engine)
    if name == "sqlite":
        copy = work / "database.sqlite"
        _sqlite_copy(engine, copy)
        counts = _sqlite_counts(copy)
        hashes["database.sqlite"] = _write_member(zf, "database.sqlite", copy)
        copy.unlink()
        return {"method": "sqlite", "counts": counts, "note": ""}
    note = ""
    if use_tools:
        out = work / "database.sql"
        found = _tool_command(engine, out)
        if found is not None:
            method, argv, env = found
            password = sync_engine_of(engine).url.password
            _run_tool(argv, env, timeout, str(password) if password else None)
            if not out.exists() or out.stat().st_size == 0:
                raise BackupError(f"{method} wrote an empty file.")
            hashes["database.sql"] = _write_member(zf, "database.sql", out)
            out.unlink()
            return {"method": method, "counts": {}, "note": ""}
        if name in ("postgresql", "mysql", "mariadb"):
            tool = "pg_dump" if name == "postgresql" else "mysqldump"
            note = f"{tool} is not installed, so every table was saved as JSON instead."
    return {"method": "json", "counts": _json_dump(engine, zf, hashes), "note": note}


# ====================================================================== the files part
def add_folders(zf: zipfile.ZipFile, folders: dict[str, Path], hashes: dict[str, str],
                skip: Iterable[Path] = ()) -> dict[str, Any]:
    """Copy each folder into ``files/<name>/``. Files that vanish or can't be read are listed, not fatal."""
    count = total = 0
    skipped: list[str] = []
    for label, root in folders.items():
        if not root.is_dir():
            skipped.append(f"{label}/ (folder not found)")
            continue
        for path in walk(root, skip):
            arc = f"files/{label}/{path.relative_to(root).as_posix()}"
            try:
                hashes[arc] = _write_member(zf, arc, path, compress=path.suffix.lower() not in STORED)
                count += 1
                total += path.stat().st_size
            except (FileNotFoundError, PermissionError, IsADirectoryError) as exc:
                skipped.append(f"{label}/{path.relative_to(root).as_posix()} ({type(exc).__name__})")
    return {"files": count, "bytes": total, "skipped": skipped}


# ====================================================================== the whole zip
def write_backup(target: Path, engine: Any, *, folders: dict[str, Path] | None = None, skip: Iterable[Path] = (),
                 use_tools: bool = True, timeout: int = 3600, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Write a backup zip to ``target`` (written as ``<target>.part`` first, so a half file never looks done).

    Returns the manifest."""
    target = Path(target)
    part = target.with_name(target.name + ".part")
    hashes: dict[str, str] = {}
    work = Path(tempfile.mkdtemp(prefix=".work-", dir=target.parent))
    try:
        fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh, zipfile.ZipFile(fh, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            db = dump_database(engine, zf, work, hashes, use_tools=use_tools, timeout=timeout) \
                if engine is not None else {"method": None, "counts": {}, "note": ""}
            files = add_folders(zf, folders or {}, hashes, skip) if folders else {"files": 0, "bytes": 0,
                                                                                     "skipped": []}
            manifest = {
                "format": FORMAT,
                "created_at": dt.datetime.now().isoformat(timespec="seconds"),
                "database": {"dialect": dialect_of(engine) if engine is not None else None,
                             "method": db["method"], "tables": db["counts"], "note": db["note"]},
                "files": {"folders": sorted((folders or {}).keys()), "count": files["files"],
                          "bytes": files["bytes"], "skipped": files["skipped"]},
                "versions": _versions(),
                "sha256": hashes,
                **(extra or {}),
            }
            zf.writestr("manifest.json", json.dumps(manifest, indent=1, default=str), zipfile.ZIP_DEFLATED)
        os.replace(part, target)
        return manifest
    except OSError as exc:
        if getattr(exc, "errno", None) == 28:  # ENOSPC
            raise BackupError("The disk got full while writing the backup. Free some space and try again.") from exc
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
        try:
            part.unlink()
        except FileNotFoundError:
            pass


def _versions() -> dict[str, str]:
    from importlib.metadata import PackageNotFoundError, version

    out = {}
    for name in ("tungsten-admin", "tungsten-backups", "sqlalchemy"):
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            continue
    return out


# ====================================================================== checking a zip
def read_manifest(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as zf:
        return json.loads(zf.read("manifest.json"))


def verify_backup(path: Path, sha256: str | None = None) -> list[str]:
    """Problems found in a backup file (an empty list means it is fine).

    Checks the whole-file sha256, that every part reads back without a CRC error, that every part
    matches the hash in the manifest, and that a SQLite copy passes SQLite's own integrity check."""
    path = Path(path)
    if not path.is_file():
        return ["The file is missing from the backups folder."]
    problems = []
    if sha256 and sha256_of(path) != sha256:
        problems.append("The file changed since it was made (its sha256 does not match).")
    try:
        with zipfile.ZipFile(path) as zf:
            manifest = json.loads(zf.read("manifest.json"))
            for name, expected in (manifest.get("sha256") or {}).items():
                h = hashlib.sha256()
                try:
                    with zf.open(name) as fh:
                        for block in iter(lambda: fh.read(CHUNK), b""):
                            h.update(block)
                except KeyError:
                    problems.append(f"{name} is missing from the zip.")
                    continue
                if h.hexdigest() != expected:
                    problems.append(f"{name} is damaged.")
            if "database.sqlite" in zf.namelist() and not problems:
                with tempfile.TemporaryDirectory(dir=path.parent, prefix=".verify-") as tmp:
                    copy = Path(tmp) / "check.sqlite"
                    with zf.open("database.sqlite") as src, open(copy, "wb") as dst:
                        shutil.copyfileobj(src, dst, CHUNK)
                    con = sqlite3.connect(copy)
                    try:
                        ok = con.execute("PRAGMA integrity_check").fetchone()[0]
                    finally:
                        con.close()
                    if ok != "ok":
                        problems.append(f"The SQLite copy is damaged: {ok}")
    except (zipfile.BadZipFile, KeyError, ValueError, zipfile.LargeZipFile) as exc:
        problems.append(f"The zip can't be read: {exc}")
    return problems
