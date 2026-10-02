"""Two-factor authentication with time-based one-time codes (TOTP, RFC 6238).

Works with Google Authenticator, Microsoft Authenticator, 1Password, Authy...
Turn it on with ``Auth(User, two_factor=True)`` (or ``two_factor_required=True``).
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
    def enabled(self) -> bool:
        cred = self.credential
        return bool(cred and cred.confirmed_at)

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
        """Check a login code (or a one-time recovery code)."""
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
