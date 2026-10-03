"""Email verification: signed links that confirm a user owns their email address.

Turn it on with ``Auth(User, email_verification=True)``. The user model needs
a nullable datetime column, ``email_verified_at`` by default
(``Auth(verified_field=...)`` to rename it). Unverified users can sign in but
only see the "verify your email" page until they click the link.
"""

from __future__ import annotations

import datetime as dt
import time
from typing import TYPE_CHECKING, Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..i18n import translate as __
from ..support.evaluate import call

if TYPE_CHECKING:  # pragma: no cover
    from ..context import Context
    from ..panel import Panel

RESEND_SECONDS = 60


def _serializer(panel: "Panel") -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(panel.secret_key, salt=f"tungsten-verify-{panel.id}")


def is_verified(panel: "Panel", user: Any) -> bool:
    return getattr(user, panel.auth.verified_field, None) is not None


def needs_verification(panel: "Panel", user: Any) -> bool:
    return bool(panel.auth.email_verification and user is not None and not is_verified(panel, user))


def make_token(panel: "Panel", user: Any) -> str:
    auth = panel.auth
    # the email is part of the token, so changing it makes old links stop working
    return _serializer(panel).dumps({"id": auth.user_id(user), "email": str(getattr(user, auth.email_field, "")).lower()})


def verification_url(ctx: "Context", user: Any) -> str:
    panel = ctx.panel
    return panel.absolute_url(ctx, panel.url("email-verification", "verify", make_token(panel, user)))


def read_token(panel: "Panel", token: str) -> dict | None:
    """The token's payload, or None when it is forged or older than ``verification_minutes``."""
    try:
        data = _serializer(panel).loads(token, max_age=panel.auth.verification_minutes * 60)
    except (SignatureExpired, BadSignature):
        return None
    return data if isinstance(data, dict) and "id" in data and "email" in data else None


def token_matches(panel: "Panel", user: Any, data: dict) -> bool:
    auth = panel.auth
    return (str(data.get("id")) == auth.user_id(user)
            and str(data.get("email")) == str(getattr(user, auth.email_field, "")).lower())


def mark_verified(panel: "Panel", user: Any) -> None:
    if not is_verified(panel, user):
        setattr(user, panel.auth.verified_field, dt.datetime.now())


def send(ctx: "Context", user: Any) -> bool:
    """Email a fresh link. Returns False when one was sent less than a minute ago."""
    panel = ctx.panel
    auth = panel.auth
    last = ctx.session.get("tw_verify_sent", 0)
    if time.time() - last < RESEND_SECONDS:
        return False
    ctx.session["tw_verify_sent"] = time.time()
    url = verification_url(ctx, user)
    name = auth.display_name(user)
    call(auth.mailer, to=getattr(user, auth.email_field),
         subject=__("Verify your :app email address", app=panel.brand_name),
         body=__("Hello :name,\n\nPlease confirm your email address by opening this link:\n:url\n\n"
                 "The link works for :minutes minutes. If you did not create an account, you can ignore this email.",
                 name=name, url=url, minutes=auth.verification_minutes),
         url=url, user=user, kind="verification")
    return True


__all__ = ["is_verified", "make_token", "mark_verified", "needs_verification", "read_token", "send",
           "token_matches", "verification_url"]
