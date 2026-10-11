"""Media library logic, kept apart from the screens so other code (and tests) can use it."""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
import struct
from pathlib import PurePosixPath
from typing import Any, BinaryIO

from sqlalchemy import String, cast, or_, select

from .models import MediaItem

log = logging.getLogger("tungsten.media")

KINDS: dict[str, tuple[str, str, str]] = {
    # key: (label, badge color, icon)
    "image": ("Image", "success", "image"),
    "video": ("Video", "info", "film"),
    "audio": ("Audio", "warning", "music"),
    "document": ("Document", "primary", "file-text"),
    "other": ("Other", "gray", "file"),
}

DOCUMENT_EXTENSIONS = {
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp", "txt", "csv", "rtf", "md", "json",
}

# some systems don't know these, and the picker filters by type
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("image/avif", ".avif")


def guess_mime(name: str, fallback: str = "") -> str:
    return mimetypes.guess_type(name or "")[0] or fallback or "application/octet-stream"


def kind_of(mime: str, name: str = "") -> str:
    """image, video, audio, document or other."""
    mime = (mime or "").lower()
    for kind in ("image", "video", "audio"):
        if mime.startswith(kind + "/"):
            return kind
    ext = PurePosixPath(name or "").suffix.lower().lstrip(".")
    if ext in DOCUMENT_EXTENSIONS or mime == "application/pdf" or mime.startswith("text/"):
        return "document"
    return "other"


def human_size(size: int | None) -> str:
    size = int(size or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size} {unit}" if unit == "B" else f"{size:.1f} {unit}".replace(".0 ", " ")
        size /= 1024  # type: ignore[assignment]
    return f"{size} B"  # pragma: no cover


# ---------------------------------------------------------------------- image size without Pillow
def image_size(fp: BinaryIO) -> tuple[int, int] | None:
    """(width, height) of a PNG, GIF, JPEG, WebP or BMP file, read from its header. None when unknown."""
    try:
        head = fp.read(32)
        if head.startswith(b"\x89PNG\r\n\x1a\n") and head[12:16] == b"IHDR":
            return struct.unpack(">II", head[16:24])
        if head[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", head[6:10])
        if head.startswith(b"BM") and len(head) >= 26:
            w, h = struct.unpack("<ii", head[18:26])
            return abs(w), abs(h)
        if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
            chunk = head[12:16]
            if chunk == b"VP8X":
                w = int.from_bytes(head[24:27], "little") + 1
                h = int.from_bytes(head[27:30], "little") + 1
                return w, h
            if chunk == b"VP8L":
                b = head[21:25]
                w = 1 + (((b[1] & 0x3F) << 8) | b[0])
                h = 1 + (((b[3] & 0xF) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
                return w, h
            if chunk == b"VP8 ":
                fp.seek(26)
                w, h = struct.unpack("<HH", fp.read(4))
                return w & 0x3FFF, h & 0x3FFF
            return None
        if head.startswith(b"\xff\xd8"):
            fp.seek(2)
            for _ in range(500):  # walk the segments up to the frame header
                marker = fp.read(2)
                if len(marker) < 2 or marker[0] != 0xFF:
                    return None
                while marker[1] == 0xFF:  # padding
                    marker = marker[:1] + fp.read(1)
                code = marker[1]
                if code in (0xD8, 0x01) or 0xD0 <= code <= 0xD7:
                    continue
                length_bytes = fp.read(2)
                if len(length_bytes) < 2:
                    return None
                length = struct.unpack(">H", length_bytes)[0]
                if code in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    data = fp.read(5)
                    if len(data) < 5:
                        return None
                    h, w = struct.unpack(">HH", data[1:5])
                    return w, h
                fp.seek(length - 2, os.SEEK_CUR)
    except (struct.error, OSError, ValueError, IndexError):
        return None
    return None


def file_facts(storage: Any, path: str) -> dict[str, Any]:
    """Size, checksum and image size of a stored file (only for storages with local files)."""
    facts: dict[str, Any] = {}
    if not hasattr(storage, "path"):
        return facts
    try:
        full = storage.path(path)
        if not full.is_file():
            return {"missing": True}
        digest = hashlib.sha256()
        with open(full, "rb") as f:
            while chunk := f.read(1024 * 1024):
                digest.update(chunk)
        facts["size"] = full.stat().st_size
        facts["checksum"] = digest.hexdigest()
        with open(full, "rb") as f:
            dims = image_size(f)
        if dims and dims[0] > 0 and dims[1] > 0:
            facts["width"], facts["height"] = dims
    except (OSError, ValueError):
        log.warning("Could not read %s", path, exc_info=True)
    return facts


def file_exists(storage: Any, path: str) -> bool | None:
    """True/False for local storages, None when the storage can't tell."""
    if not hasattr(storage, "path"):
        return None
    try:
        return storage.path(path).is_file()
    except ValueError:
        return False


# ---------------------------------------------------------------------- records
def find_item(db: Any, path: str) -> MediaItem | None:
    if not path:
        return None
    return db.scalars(select(MediaItem).where(MediaItem.path == str(path))).first()


def clean_folder(folder: Any) -> str:
    """``" Blog / Covers/ "`` -> ``"blog/covers"``: lower case, no empty parts, no dots."""
    parts = [p.strip().lower() for p in str(folder or "").replace("\\", "/").split("/")]
    return "/".join(p for p in parts if p and p not in (".", ".."))[:100]


def record_file(db: Any, storage: Any, path: str, name: str | None = None, content_type: str = "",
                size: int = 0, folder: str | None = None, user_id: Any = None, facts: dict | None = None) -> MediaItem:
    """Add a stored file to the library (or return the row it already has)."""
    item = find_item(db, path)
    if item is not None:
        return item
    name = (os.path.basename(name or "") or path.rsplit("/", 1)[-1])[:255]
    mime = guess_mime(name, content_type)
    if mime == "application/octet-stream":
        mime = guess_mime(path, content_type)
    facts = file_facts(storage, path) if facts is None else facts
    if folder is None:
        folder = path.rsplit("/", 1)[0] if "/" in path else ""
        # date folders (2026/10) say nothing about the file
        folder = "" if folder.replace("/", "").isdigit() else folder.split("/", 1)[0]
    item = MediaItem(path=path, name=name, mime=mime[:120], kind=kind_of(mime, name),
                     size=int(facts.get("size") or size or 0), width=facts.get("width"), height=facts.get("height"),
                     checksum=facts.get("checksum"), folder=clean_folder(folder),
                     uploaded_by=str(user_id) if user_id not in (None, "") else None,
                     missing=bool(facts.get("missing")))
    db.add(item)
    db.flush()
    return item


def duplicate_of(db: Any, storage: Any, checksum: str | None, size: int, path: str) -> MediaItem | None:
    """A library file with the same content whose file is still there."""
    if not checksum:
        return None
    rows = db.scalars(select(MediaItem).where(MediaItem.checksum == checksum, MediaItem.size == size,
                                              MediaItem.path != path, MediaItem.missing.is_(False)).limit(5)).all()
    return next((row for row in rows if file_exists(storage, row.path) is not False), None)


def check_files(db: Any, storage: Any, items: list[MediaItem] | None = None) -> tuple[int, int]:
    """Mark files that are gone from storage (and un-mark ones that came back). Returns (missing, found again)."""
    missing = found = 0
    rows = items if items is not None else db.scalars(select(MediaItem)).all()
    for item in rows:
        exists = file_exists(storage, item.path)
        if exists is None:
            continue
        if not exists and not item.missing:
            item.missing = True
            missing += 1
        elif exists and item.missing:
            item.missing = False
            found += 1
    db.flush()
    return missing, found


def accept_conditions(accepted: list[str] | None) -> list[Any]:
    """SQL conditions matching a file field's accepted types (``image/*``, ``.pdf``, ``application/pdf``)."""
    conditions = []
    for t in accepted or []:
        t = str(t).strip().lower()
        if not t:
            continue
        if t.endswith("/*"):
            conditions.append(MediaItem.mime.like(t[:-1] + "%"))
        elif t.startswith("."):
            conditions.append(MediaItem.path.ilike("%" + t.replace("%", "").replace("_", "\\_"), escape="\\"))
        else:
            conditions.append(MediaItem.mime == t)
    return conditions


def search_items(db: Any, q: str = "", accepted: list[str] | None = None, folder: str | None = None,
                 page: int = 1, per_page: int = 24) -> tuple[list[MediaItem], bool]:
    """Newest first. Returns (items, has_more)."""
    query = select(MediaItem).where(MediaItem.missing.is_(False))
    conditions = accept_conditions(accepted)
    if conditions:
        query = query.where(or_(*conditions))
    if folder:
        query = query.where(MediaItem.folder == folder)
    q = (q or "").strip()[:100]
    if q:
        like = "%" + q.replace("\\", "").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.where(or_(MediaItem.name.ilike(like, escape="\\"), MediaItem.title.ilike(like, escape="\\"),
                                MediaItem.alt.ilike(like, escape="\\"), MediaItem.folder.ilike(like, escape="\\")))
    page = max(1, page)
    rows = db.scalars(query.order_by(MediaItem.created_at.desc(), MediaItem.id.desc())
                      .offset((page - 1) * per_page).limit(per_page + 1)).all()
    return list(rows[:per_page]), len(rows) > per_page


# ---------------------------------------------------------------------- where a file is used
def contains(column: Any, path: str) -> Any:
    """``column`` (text or a JSON list) mentions ``path``."""
    escaped = path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return cast(column, String).like(f"%{escaped}%", escape="\\")
