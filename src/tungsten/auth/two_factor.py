"""Two-factor authentication with time-based one-time codes (TOTP, RFC 6238).

Works with Google Authenticator, Microsoft Authenticator, 1Password, Authy...
Turn it on with ``Auth(User, two_factor=True)`` (or ``two_factor_required=True``).
``Auth(two_factor_email=True)`` also lets users get a one-time code by email
instead of (or as a backup to) an app.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import secrets
import struct
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from sqlalchemy import select

if TYPE_CHECKING:  # pragma: no cover
    from ..context import Context

STEP = 30
DIGITS = 6


def generate_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    padded = secret.upper() + "=" * (-len(secret) % 8)
    return base64.b32decode(padded)


def totp(secret: str, step_number: int | None = None) -> str:
    counter = int(time.time() // STEP) if step_number is None else step_number
    digest = hmac.new(_key(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** DIGITS)
    return str(code).zfill(DIGITS)


def match_step(secret: str, code: str, window: int = 1, now: float | None = None) -> int | None:
    """Return the time step the code belongs to (allowing ±``window`` steps), or ``None``."""
    code = (code or "").replace(" ", "").strip()
    if not code.isdigit() or len(code) != DIGITS:
        return None
    current = int((now if now is not None else time.time()) // STEP)
    for step in range(max(0, current - window), current + window + 1):
        if hmac.compare_digest(totp(secret, step), code):
            return step
    return None


def otpauth_uri(secret: str, account: str, issuer: str) -> str:
    label = quote(f"{issuer}:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&digits={DIGITS}&period={STEP}"


def make_recovery_codes(n: int = 8) -> list[str]:
    return [f"{secrets.token_hex(3)}-{secrets.token_hex(3)}" for _ in range(n)]


def _hash(code: str) -> str:
    return hashlib.sha256(code.strip().lower().encode()).hexdigest()


class TwoFactor:
    """Read and change one user's two-factor settings."""

    def __init__(self, ctx: "Context", user: Any) -> None:
        self.ctx = ctx
        self.user = user
        self.user_id = ctx.panel.auth.user_id(user)

    @property
    def credential(self):
        from ..models import TwoFactorCredential

        return self.ctx.db.scalars(select(TwoFactorCredential).where(TwoFactorCredential.user_id == self.user_id)).first()

    @property
    def app_enabled(self) -> bool:
        """An authenticator app is set up and confirmed."""
        cred = self.credential
        return bool(cred and cred.confirmed_at)

    @property
    def email_row(self):
        from ..models import TwoFactorEmail

        return self.ctx.db.scalars(select(TwoFactorEmail).where(TwoFactorEmail.user_id == self.user_id)).first()

    @property
    def email_enabled(self) -> bool:
        """The user gets sign-in codes by email (only counts while the panel allows email codes)."""
        return bool(self.ctx.panel.auth.two_factor_email and self.email_row is not None)

    @property
    def enabled(self) -> bool:
        """Any second step is on, so signing in needs a code."""
        return self.app_enabled or self.email_enabled

    def enable_email(self) -> None:
        from ..models import TwoFactorEmail

        if self.email_row is None:
            self.ctx.db.add(TwoFactorEmail(user_id=self.user_id))
            self.ctx.db.commit()

    def disable_email(self) -> None:
        row = self.email_row
        if row is not None:
            self.ctx.db.delete(row)
            self.ctx.db.commit()

    def start(self) -> str:
        """Create (or reuse) an unconfirmed secret."""
        from ..models import TwoFactorCredential

        cred = self.credential
        if cred is None:
            cred = TwoFactorCredential(user_id=self.user_id, secret=generate_secret())
            self.ctx.db.add(cred)
        elif cred.confirmed_at is None:
            cred.secret = generate_secret()
        self.ctx.db.commit()
        return cred.secret

    def confirm(self, code: str) -> list[str] | None:
        """Check the first code. Returns fresh recovery codes, or ``None`` if the code is wrong."""
        cred = self.credential
        if cred is None:
            return None
        step = match_step(cred.secret, code)
        if step is None:
            return None
        codes = make_recovery_codes()
        cred.recovery_codes = [_hash(c) for c in codes]
        cred.confirmed_at = dt.datetime.now()
        cred.last_used_step = step
        self.ctx.db.commit()
        return codes

    def verify(self, code: str) -> bool:
        """Check a login code from the app (or a one-time recovery code)."""
        cred = self.credential
        if cred is None or cred.confirmed_at is None:
            return False
        step = match_step(cred.secret, code)
        if step is not None:
            if cred.last_used_step is not None and step <= cred.last_used_step:
                return False  # a code can only be used once
            cred.last_used_step = step
            self.ctx.db.commit()
            return True
        hashed = _hash(code)
        if hashed in (cred.recovery_codes or []):
            cred.recovery_codes = [c for c in cred.recovery_codes if c != hashed]
            self.ctx.db.commit()
            return True
        return False

    def regenerate_codes(self) -> list[str]:
        cred = self.credential
        codes = make_recovery_codes()
        cred.recovery_codes = [_hash(c) for c in codes]
        self.ctx.db.commit()
        return codes

    def disable(self) -> None:
        cred = self.credential
        if cred is not None:
            self.ctx.db.delete(cred)
            self.ctx.db.commit()


# ---------------------------------------------------------------------- codes sent by email
EMAIL_RESEND_SECONDS = 60
EMAIL_CODE_TRIES = 5  # wrong guesses per user and purpose while a code is valid


# The code itself lives in the signed session cookie, but a client can replay an old cookie. So the resend wait,
# the wrong guesses and the used codes are also counted in ``Auth.throttle`` on the server, keyed by user and
# purpose, where a replayed cookie cannot reset them (issue #122).
def _sent_key(purpose: str, user_id: str) -> str:
    return f"2fa-mail-sent|{purpose}|{user_id}"


def _tries_key(purpose: str, user_id: str) -> str:
    return f"2fa-mail-tries|{purpose}|{user_id}"


def _used_key(digest: str) -> str:
    return f"2fa-mail-used|{digest}"


def _email_slot(purpose: str) -> str:
    return f"tw_2fa_mail_{purpose}"


def _email_digest(ctx: "Context", user_id: str, purpose: str, code: str, expires: float) -> str:
    # the session cookie is signed, not encrypted, so it only ever holds a keyed hash of the code
    message = f"{purpose}|{user_id}|{code}|{expires}".encode()
    return hmac.new(ctx.panel.secret_key.encode(), message, hashlib.sha256).hexdigest()


def mask_email(email: str) -> str:
    """``asha@example.com`` -> ``a•••@example.com``."""
    name, at, domain = str(email or "").partition("@")
    if not at:
        return email
    return f"{name[:1]}•••@{domain}"


def send_email_code(ctx: "Context", user: Any, purpose: str = "login") -> bool:
    """Email a fresh 6-digit code. Returns False when one was sent less than a minute ago."""
    from ..i18n import translate as __
    from ..support.evaluate import call

    panel = ctx.panel
    auth = panel.auth
    user_id = auth.user_id(user)
    slot = ctx.session.get(_email_slot(purpose)) or {}
    now = time.time()
    if slot.get("uid") == user_id and now - slot.get("sent", 0) < EMAIL_RESEND_SECONDS:
        return False
    if auth.throttle.failures(_sent_key(purpose, user_id), EMAIL_RESEND_SECONDS) > 0:
        return False  # sent less than a minute ago, from another (or an older) session cookie
    auth.throttle.fail(_sent_key(purpose, user_id))
    code = str(secrets.randbelow(10 ** DIGITS)).zfill(DIGITS)
    expires = now + auth.two_factor_email_minutes * 60
    ctx.session[_email_slot(purpose)] = {"uid": user_id, "h": _email_digest(ctx, user_id, purpose, code, expires),
                                         "exp": expires, "sent": now}
    call(auth.mailer, to=getattr(user, auth.email_field),
         subject=__("Your :app sign-in code: :code", app=panel.brand_name, code=code),
         body=__("Hello :name,\n\nYour sign-in code is :code\n\nIt works for :minutes minutes. "
                 "If you did not try to sign in, change your password.",
                 name=auth.display_name(user), code=code, minutes=auth.two_factor_email_minutes),
         code=code, user=user, kind="two_factor_code")
    return True


def email_code_sent(ctx: "Context", user: Any, purpose: str = "login") -> bool:
    slot = ctx.session.get(_email_slot(purpose)) or {}
    return slot.get("uid") == ctx.panel.auth.user_id(user) and time.time() < slot.get("exp", 0)


def check_email_code(ctx: "Context", user: Any, code: str, purpose: str = "login") -> bool:
    """True (and the code is used up) when ``code`` is the last one emailed for ``purpose``.

    After ``EMAIL_CODE_TRIES`` wrong guesses no code is taken for that user and purpose until the code's lifetime
    has passed, even with a replayed session cookie.
    """
    auth = ctx.panel.auth
    slot = ctx.session.get(_email_slot(purpose)) or {}
    user_id = auth.user_id(user)
    code = (code or "").replace(" ", "").strip()
    if slot.get("uid") != user_id or time.time() > slot.get("exp", 0):
        return False
    lifetime = auth.two_factor_email_minutes * 60
    tries = _tries_key(purpose, user_id)
    if auth.throttle.failures(tries, lifetime) >= EMAIL_CODE_TRIES:
        return False
    digest = _email_digest(ctx, user_id, purpose, code, slot["exp"]) if code.isdigit() else ""
    if not digest or not hmac.compare_digest(digest, slot.get("h", "")):
        auth.throttle.fail(tries)
        return False
    if auth.throttle.failures(_used_key(digest), lifetime) > 0:
        return False  # already used, sent again in a saved cookie
    auth.throttle.fail(_used_key(digest))
    auth.throttle.clear(tries)
    ctx.session.pop(_email_slot(purpose), None)
    return True


def forget_email_code(ctx: "Context", purpose: str = "login") -> None:
    ctx.session.pop(_email_slot(purpose), None)
