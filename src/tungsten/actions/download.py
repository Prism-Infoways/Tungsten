"""A ready-made action that downloads (or streams) a file.

    DownloadAction("invoice").icon("file-down")
        .file(lambda record: f"invoices/{record.number}.pdf")
        .filename(lambda record: f"invoice-{record.number}.pdf")

    DownloadAction("report").form([DatePicker("from"), DatePicker("to")])
        .stream(lambda data, db: report_rows(db, data["from"], data["to"]))
        .filename("report.csv")

When it runs, the browser is sent to a signed link that is good for a few
minutes and only for the same user, and the file is built there.
"""

from __future__ import annotations

import datetime as dt
import inspect
import json
import mimetypes
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from starlette.responses import FileResponse, Response, StreamingResponse

from ..support.evaluate import call, evaluate
from .action import Action, BulkAction

if TYPE_CHECKING:  # pragma: no cover
    from ..context import Context
    from ..hosts import Host

#: how long a download link works, in seconds (change it app-wide, or per action with ``link_lifetime()``)
TOKEN_MAX_AGE = 300


def _serializer(panel: Any):
    from itsdangerous import URLSafeTimedSerializer

    return URLSafeTimedSerializer(panel.secret_key, salt="tungsten-download")


def make_token(panel: Any, payload: dict) -> str:
    return _serializer(panel).dumps(payload)


def read_token(panel: Any, token: str) -> dict | None:
    from itsdangerous import BadSignature

    if not token:
        return None
    try:
        payload, signed_at = _serializer(panel).loads(token, return_timestamp=True)
    except BadSignature:
        return None
    if not isinstance(payload, dict):
        return None
    lifetime = payload.get("ttl") or TOKEN_MAX_AGE  # signed with the payload, so it can't be stretched
    age = (dt.datetime.now(dt.timezone.utc) - signed_at).total_seconds()
    return payload if age <= lifetime else None


def _json_safe(data: dict) -> dict:
    return json.loads(json.dumps(data, default=str))


def safe_filename(name: str) -> str:
    name = re.sub(r'[\\/\r\n"]+', "-", str(name or "")).strip() or "download"
    return name[:150]


class DownloadMixin:
    """Shared by :class:`DownloadAction` and :class:`DownloadBulkAction`."""

    _is_download = True

    def _setup_download(self) -> None:
        self._file: Callable | None = None
        self._stream: Callable | None = None
        self._filename: Any = None
        self._mime: Any = None
        self._inline = False
        self._link_lifetime: int | None = None
        self._icon = self._icon or "download"
        self._deselect_after = False

    def file(self, fn: Any) -> Any:
        """What to send: a path (on disk, or in the panel's storage), ``bytes``, or a Response.
        A closure gets ``record``/``records``/``data``/``db``/``user`` like any action."""
        self._file = fn
        return self

    def stream(self, fn: Callable) -> Any:
        """Send what ``fn`` yields (``str`` or ``bytes`` pieces) as it is made, for big files.

        The generator runs after the request's database session is closed: read what it needs
        first, or open its own session."""
        self._stream = fn
        return self

    def filename(self, name: Any) -> Any:
        self._filename = name
        return self

    def mime_type(self, mime: Any) -> Any:
        self._mime = mime
        return self

    def link_lifetime(self, seconds: int) -> Any:
        """How long the download link works (default ``TOKEN_MAX_AGE``, 5 minutes)."""
        self._link_lifetime = int(seconds)
        return self

    def open_in_browser(self, condition: bool = True) -> Any:
        """Show the file in the browser (PDFs, images) instead of saving it."""
        self._inline = condition
        return self

    # ------------------------------------------------------------------ running
    def run(self, ctx: "Context", host: "Host | None", record: Any = None, records: Any = None,  # type: ignore[override]
            data: dict | None = None, form: Any = None) -> Any:
        payload = {
            "host": host.key if host else "",
            "scope": self.scope,
            "name": self.path,
            "record": host.record_key(record) if (host is not None and record is not None) else "",
            "keys": [host.record_key(r) for r in records or []] if host is not None else [],
            "data": _json_safe(data or {}),
            "arguments": _json_safe(self.arguments),
            "user": ctx.panel.auth.user_id(ctx.user) if ctx.user is not None else None,
        }
        if self._link_lifetime:
            payload["ttl"] = self._link_lifetime
        ctx.redirect(ctx.url("_tw", "download", token=make_token(ctx.panel, payload)))
        return None

    def response(self, ctx: "Context", host: "Host | None", record: Any = None, records: Any = None,
                 data: dict | None = None) -> Response:
        ev = {**self.ev(ctx, record, records), "data": data or {}, "host": host}
        name = evaluate(self._filename, **ev)
        if self._stream is not None:
            body = call(self._stream, **ev)
            return self._headers(StreamingResponse(_as_bytes(body), media_type=self._media(ev, name)), name)
        if self._file is None:
            return Response(status_code=404)
        value = call(self._file, **ev) if callable(self._file) else self._file
        if isinstance(value, Response):
            return value
        if isinstance(value, (bytes, bytearray)):
            return self._headers(Response(bytes(value), media_type=self._media(ev, name)), name)
        if inspect.isgenerator(value) or (hasattr(value, "__iter__") and not isinstance(value, (str, Path))):
            return self._headers(StreamingResponse(_as_bytes(value), media_type=self._media(ev, name)), name)
        if value is None:
            return Response(status_code=404)
        path = self._locate(ctx, str(value))
        if path is None:
            return Response(status_code=404)
        name = name or path.name
        return self._headers(FileResponse(path, media_type=self._media(ev, name)), name)

    def _locate(self, ctx: "Context", value: str) -> Path | None:
        path = Path(value)
        if path.is_absolute():
            return path if path.is_file() else None
        storage = ctx.panel.storage
        if hasattr(storage, "path"):
            try:
                found = storage.path(value)
            except ValueError:
                return None
            if found.is_file():
                return found
        return path if path.is_file() else None

    def _media(self, ev: dict, name: Any) -> str:
        mime = evaluate(self._mime, **ev)
        if mime:
            return str(mime)
        guessed = mimetypes.guess_type(str(name or ""))[0]
        return guessed or "application/octet-stream"

    def _headers(self, response: Response, name: Any) -> Response:
        name = safe_filename(name or "download")
        kind = "inline" if self._inline else "attachment"
        ascii_name = name.encode("ascii", "replace").decode().replace("?", "_")
        from urllib.parse import quote

        response.headers["Content-Disposition"] = f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response


async def _as_bytes(body: Any):
    from starlette.concurrency import iterate_in_threadpool

    if hasattr(body, "__aiter__"):
        async for piece in body:
            yield piece.encode() if isinstance(piece, str) else piece
        return
    async for piece in iterate_in_threadpool(iter(body)):
        yield piece.encode() if isinstance(piece, str) else piece


class DownloadAction(DownloadMixin, Action):
    """Download a file for a record, or for the page. See the module docs."""

    def __init__(self, name: str = "download") -> None:
        super().__init__(name)
        self._setup_download()
        self._color = "gray"


class DownloadBulkAction(DownloadMixin, BulkAction):
    """Download one file built from the selected records (the closure gets ``records``)."""

    def __init__(self, name: str = "download") -> None:
        super().__init__(name)
        self._setup_download()
