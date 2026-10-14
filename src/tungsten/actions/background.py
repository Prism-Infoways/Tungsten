"""Running a bulk action in the background (``BulkAction(...).background()``)."""

from __future__ import annotations

import logging
from typing import Any

from ..i18n import translate as __

log = logging.getLogger("tungsten")


def run_bulk_job(job: Any):
    """Job handler: run the bulk action on the saved record keys, a chunk at a time, then notify the user."""
    from starlette.datastructures import FormData

    from ..forms.form import ValidationError
    from ..jobs import chunks
    from ..notifications import Notification
    from ..routes import Forbidden, NotFound, Routes

    ctx = job.ctx
    panel = ctx.panel
    p = job.payload
    if ctx.user is None and panel.auth.enabled:
        raise PermissionError("The user who started this no longer exists.")
    routes = Routes(panel)
    src = FormData([tuple(pair) for pair in p.get("fields") or []])
    host = routes.resolve_host(ctx, p.get("host"))
    record = host.find_record(ctx, p["record"]) if p.get("record") else None
    if p.get("record") and record is None:
        raise NotFound()
    scope = p.get("scope") or "bulk"
    action = routes.find_action(ctx, host, scope, p.get("name") or "", record, params=src)
    if not routes.action_available(action, host, ctx, record):
        raise Forbidden()
    action.arguments = dict(p.get("arguments") or {})
    form = routes._action_form(ctx, host, action, record, None, scope)
    data: dict = {}
    if form is not None:
        form.load(src)
        try:
            data = form.validate()
        except ValidationError as exc:
            raise ValueError("The form is no longer valid: " + "; ".join(
                f"{k}: {v}" for k, v in list(exc.errors.items())[:3])) from None

    keys = list(p.get("keys") or [])
    size = getattr(action, "_chunk_size", None) or 100
    total = len(keys)
    done = failed = 0
    job.progress(0, total=total, failed=0)
    action.call_hooks("before", ctx, host, record, None, data, form=form)
    for chunk in chunks(keys, size):
        records = host.find_records(ctx, chunk)
        failed += len(chunk) - len(records)  # gone, or no longer allowed
        try:
            result = action.run(ctx, host, record, records, data, form)
        except Exception:  # noqa: BLE001 - count the chunk as failed and go on
            log.exception("Bulk action %r failed on a chunk", action.path)
            ctx.db.rollback()
            failed += len(records)
        else:
            if result is False:
                ctx.db.rollback()
                failed += len(records)
            else:
                ctx.db.commit()
                done += len(records)
        job.progress(done + failed, failed=failed)
        yield
    summary = {"processed": done, "failed": failed, "total": total}
    action.call_hooks("after", ctx, host, record, None, data, form=form, result=summary)
    ctx.db.commit()
    if panel.database_notifications and job.job.user_id is not None:
        label = action.get_label(action.ev(ctx, host=host))
        note = Notification(__(":action finished", action=label))
        if failed:
            note.body(__(":done of :total records done, :failed failed.", done=done, total=total, failed=failed)
                      ).warning()
        else:
            note.body(__(":done of :total records done.", done=done, total=total)).success()
        note.send_to_database(job.job.user_id, job.db)
    return summary
