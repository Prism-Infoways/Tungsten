"""Verified email changes: a new address typed on the profile page only takes
effect after its owner clicks the link we email to it.

The old address gets a notice with a link to block the change, in case
someone else got into the account. On by default with
``Auth(email_verification=True)``; set ``Auth(email_change_verification=...)``
to choose yourself.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
import time
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from ..i18n import translate as __
from ..support.evaluate import call

if TYPE_CHECKING:  # pragma: no cover
    from ..context import Context
    from ..panel import Panel

RESEND_SECONDS = 60


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def pending(ctx: "Context", user: Any) -> Any:
    """The change waiting for confirmation, if any (expired ones are dropped)."""
    from ..models import EmailChange

    row = ctx.db.scalars(select(EmailChange).where(EmailChange.user_id == ctx.panel.auth.user_id(user))).first()
    if row is not None and _expired(ctx.panel, row):
        ctx.db.delete(row)
        ctx.db.commit()
        return None
    return row


def _expired(panel: "Panel", row: Any) -> bool:
    return row.created_at < dt.datetime.now() - dt.timedelta(minutes=panel.auth.verification_minutes)


def can_send(ctx: "Context") -> bool:
    return time.time() - ctx.session.get("tw_email_change_sent", 0) >= RESEND_SECONDS


def start(ctx: "Context", user: Any, new_email: str) -> None:
    """Remember the new address and email both the new one (confirm link) and the old one (block link)."""
    from ..models import EmailChange

    panel = ctx.panel
    auth = panel.auth
    uid = auth.user_id(user)
    for old in ctx.db.scalars(select(EmailChange).where(EmailChange.user_id == uid)):
        ctx.db.delete(old)
    ctx.db.flush()
    token, block = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    old_email = str(getattr(user, auth.email_field, "") or "")
    ctx.db.add(EmailChange(user_id=uid, old_email=old_email, new_email=new_email.strip(),
                           token_hash=_hash(token), block_token_hash=_hash(block)))
    ctx.db.commit()
    ctx.session["tw_email_change_sent"] = time.time()
    name = auth.display_name(user)
    url = panel.absolute_url(ctx, panel.url("email-change", token))
    call(auth.mailer, to=new_email.strip(),
         subject=__("Confirm your new :app email address", app=panel.brand_name),
         body=__("Hello :name,\n\nPlease confirm that this is your new email address by opening this link:\n:url\n\n"
                 "The link works for :minutes minutes. Until then your account keeps using :old.",
                 name=name, url=url, minutes=auth.verification_minutes, old=old_email),
         url=url, user=user, kind="email_change")
    if old_email:
        block_url = panel.absolute_url(ctx, panel.url("email-change", block, "block"))
        call(auth.mailer, to=old_email,
             subject=__("Your :app email address is being changed", app=panel.brand_name),
             body=__("Hello :name,\n\nSomeone asked to change the email address of your account to :new.\n\n"
                     "If this was not you, open this link to stop the change, then change your password:\n:url",
                     name=name, new=new_email.strip(), url=block_url),
             url=block_url, user=user, kind="email_change_notice")


def find(ctx: "Context", token: str, block: bool = False) -> Any:
    from ..models import EmailChange

    column = EmailChange.block_token_hash if block else EmailChange.token_hash
    row = ctx.db.scalars(select(EmailChange).where(column == _hash(token))).first()
    if row is None:
        return None
    if _expired(ctx.panel, row):
        ctx.db.delete(row)
        ctx.db.commit()
        return None
    return row


def confirm(ctx: "Context", row: Any) -> tuple[Any, str | None]:
    """Apply the change. Returns ``(user, error)``."""
    panel = ctx.panel
    auth = panel.auth
    user = auth.find_by_id(ctx.db, row.user_id)
    current = str(getattr(user, auth.email_field, "") or "") if user is not None else ""
    if user is None or current.lower() != row.old_email.lower():
        ctx.db.delete(row)
        ctx.db.commit()
        return None, "This link is no longer valid."
    column = getattr(auth.user_model, auth.email_field)
    taken = ctx.db.scalars(select(auth.user_model).where(func.lower(column) == row.new_email.lower())).first()
    if taken is not None and taken is not user:
        ctx.db.delete(row)
        ctx.db.commit()
        return None, "That email address is already used by another account."
    setattr(user, auth.email_field, row.new_email)
    if auth.email_verification:
        setattr(user, auth.verified_field, dt.datetime.now())  # clicking the link proves they own it
    ctx.db.delete(row)
    ctx.db.commit()
    return user, None


def cancel(ctx: "Context", row: Any) -> None:
    ctx.db.delete(row)
    ctx.db.commit()


__all__ = ["can_send", "cancel", "confirm", "find", "pending", "start"]
