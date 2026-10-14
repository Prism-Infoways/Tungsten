"""Small helpers the generated admin uses at run time.

* :class:`LaravelHasher` checks Laravel's bcrypt (and argon2) passwords, so people
  sign in to Tungsten with the password they already have. New passwords are
  saved as bcrypt too, so the Laravel app keeps working with them.
* :func:`laravel_database_url` and :func:`laravel_secret_key` read the Laravel
  ``.env`` each time the admin starts, so no password is copied into Python code.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import time
import unicodedata
import uuid
from pathlib import Path

from tungsten.auth import hash_password, verify_password

from .laravel import database_url, read_env


class LaravelHasher:
    """Password hasher for ``Auth(User, hasher=LaravelHasher())``."""

    def __init__(self, rounds: int | None = None) -> None:
        self.rounds = rounds or int(os.environ.get("BCRYPT_ROUNDS", "12"))

    def hash(self, password: str) -> str:
        try:
            import bcrypt
        except ImportError:  # pragma: no cover - bcrypt is a dependency
            return hash_password(password)
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt(self.rounds)).decode()
        return "$2y$" + hashed[4:]  # the prefix Laravel writes

    def verify(self, password: str, hashed: str | None) -> bool:
        if not password or not hashed:
            return False
        if hashed.startswith(("$2y$", "$2a$", "$2b$", "$2x$")):
            try:
                import bcrypt
            except ImportError:  # pragma: no cover
                return False
            try:
                return bcrypt.checkpw(password.encode(), ("$2b$" + hashed[4:]).encode())
            except ValueError:
                return False
        if hashed.startswith("$argon2"):
            try:
                from argon2 import PasswordHasher
                from argon2.exceptions import Argon2Error
            except ImportError:
                return False
            try:
                return PasswordHasher().verify(hashed, password)
            except Argon2Error:
                return False
        return verify_password(password, hashed)


def laravel_database_url(laravel_path: str | Path) -> str:
    """The SQLAlchemy URL for the database in a Laravel ``.env``."""
    root = Path(laravel_path)
    url, hint = database_url(read_env(root), root)
    if url is None:
        raise RuntimeError(f"Could not build a database URL from {root / '.env'}: {hint}. Set DATABASE_URL.")
    return url


def laravel_secret_key(laravel_path: str | Path) -> str:
    """A session key derived from Laravel's ``APP_KEY`` (never the key itself)."""
    key = read_env(Path(laravel_path)).get("APP_KEY")
    if not key:
        raise RuntimeError("No APP_KEY in the Laravel .env: set TUNGSTEN_SECRET_KEY instead.")
    return hashlib.sha256(b"tungsten-session:" + key.encode()).hexdigest()


def slug(value: object, separator: str = "-") -> str:
    """Laravel's ``Str::slug``: ``"Hello World!"`` -> ``"hello-world"``."""
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-_\s]+", separator, text).strip(separator)


_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid() -> str:
    """A new ULID, as Laravel's ``HasUlids`` makes them (26 characters, sortable by time)."""
    value = (int(time.time() * 1000) << 80) | secrets.randbits(80)
    out = []
    for _ in range(26):
        out.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(out)).lower()


def new_uuid() -> str:
    """A new UUID for ``HasUuids`` models."""
    return str(uuid.uuid4())
