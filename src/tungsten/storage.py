"""File storage for uploads (local disk by default)."""

from __future__ import annotations

import datetime as dt
import os
import uuid
from pathlib import Path
from typing import Any, BinaryIO

#: never stored: files a browser would run as code when opened from the panel origin
BLOCKED_EXTENSIONS = {".html", ".htm", ".xhtml", ".svg", ".js", ".mjs", ".php", ".py", ".sh", ".exe", ".bat"}


class Storage:
    def save(self, file: BinaryIO, filename: str, directory: str = "") -> str:
        raise NotImplementedError

    def url(self, path: str) -> str:
        raise NotImplementedError

    def delete(self, path: str) -> None:
        raise NotImplementedError


class LocalStorage(Storage):
    """Store files under ``root`` and serve them from ``<panel>/storage/...``."""

    def __init__(self, root: str | Path = "storage/tungsten", base_url: str | None = None) -> None:
        self.root = Path(root)
        self.base_url = base_url
        self.panel: Any = None

    def safe_name(self, filename: str) -> str:
        ext = os.path.splitext(filename or "")[1].lower()[:10]
        if ext in BLOCKED_EXTENSIONS:
            raise ValueError("This file type is not allowed.")
        return f"{uuid.uuid4().hex}{ext}"

    def save(self, file: BinaryIO, filename: str, directory: str = "") -> str:
        directory = directory.strip("/").replace("..", "")
        rel_dir = Path(directory) if directory else Path(dt.date.today().strftime("%Y/%m"))
        target_dir = self.root / rel_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        name = self.safe_name(filename)
        with open(target_dir / name, "wb") as out:
            while chunk := file.read(1024 * 1024):
                out.write(chunk)
        return str(rel_dir / name).replace(os.sep, "/")

    def path(self, path: str) -> Path:
        full = (self.root / path).resolve()
        if not str(full).startswith(str(self.root.resolve())):
            raise ValueError("Invalid path")
        return full

    def url(self, path: str) -> str:
        if not path:
            return ""
        if str(path).startswith(("http://", "https://", "/")):
            return str(path)
        base = self.base_url or (self.panel.url("storage") if self.panel else "/storage")
        return f"{base.rstrip('/')}/{path}"

    def delete(self, path: str) -> None:
        try:
            self.path(path).unlink(missing_ok=True)
        except ValueError:
            pass
