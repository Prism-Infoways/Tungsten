"""Find the environment name, its label and color, and the git branch. No Tungsten imports here."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

#: checked in this order; the first one that is set wins
ENV_VARS = ("TUNGSTEN_ENV", "APP_ENV", "ENVIRONMENT", "ENV", "FASTAPI_ENV", "PYTHON_ENV")

#: other spellings people use, mapped to one name
ALIASES = {
    "prod": "production", "live": "production", "prd": "production",
    "stage": "staging", "stg": "staging", "preprod": "staging", "pre-production": "staging", "uat": "staging",
    "dev": "development", "develop": "development",
    "test": "testing", "tests": "testing", "qa": "testing", "ci": "testing",
    "localhost": "local",
}

LABELS = {"production": "Live", "staging": "Staging", "development": "Development", "local": "Local",
          "testing": "Testing"}

#: Tailwind 600 shades: white text stays readable on all of them
PALETTE = {
    "red": "#dc2626", "orange": "#ea580c", "amber": "#d97706", "yellow": "#ca8a04", "lime": "#65a30d",
    "green": "#16a34a", "emerald": "#059669", "teal": "#0d9488", "cyan": "#0891b2", "sky": "#0284c7",
    "blue": "#2563eb", "indigo": "#4f46e5", "violet": "#7c3aed", "purple": "#9333ea", "fuchsia": "#c026d3",
    "pink": "#db2777", "rose": "#e11d48", "slate": "#475569", "gray": "#4b5563", "zinc": "#52525b",
    "neutral": "#525252", "stone": "#57534e",
    # Tungsten's color names
    "danger": "#dc2626", "warning": "#d97706", "success": "#16a34a", "info": "#2563eb", "primary": "#4f46e5",
}

COLORS = {"production": "red", "staging": "amber", "development": "blue", "local": "green", "testing": "violet"}
FALLBACK_COLOR = "gray"

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "[::1]"}
LOCAL_SUFFIXES = (".localhost", ".local", ".test", ".internal", ".lan")

_HEX = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})")
_NAME = re.compile(r"[^a-z0-9._-]+")


@dataclass(frozen=True)
class Environment:
    """What the badge shows. Other plugins read this to show the same thing."""

    #: normalised name: ``production``, ``staging``, ``development``, ``local``, ``testing``, or your own
    name: str
    label: str
    #: background color as ``#rrggbb``
    color: str
    #: ``#ffffff`` or ``#111827``, whichever reads better on ``color``
    text_color: str
    #: the git branch (or short commit) when ``git_branch=True``, else ``None``
    branch: str | None = None
    #: True when the app runs with ``FastAPI(debug=True)``
    debug: bool = False

    @property
    def is_production(self) -> bool:
        return self.name == "production"


def normalise(name: object) -> str:
    """``" PROD "`` -> ``"production"``. Anything empty becomes ``""``."""
    text = _NAME.sub("-", str(name or "").strip().lower()).strip("-")
    return ALIASES.get(text, text)


def from_env_vars(environ: dict[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    for key in ENV_VARS:
        value = normalise(env.get(key))
        if value:
            return value
    return ""


def is_local_host(host: str | None) -> bool:
    host = (host or "").strip().lower().rstrip(".")
    if not host:
        return False
    if host.startswith("["):  # [::1]:8000
        host = host.split("]")[0] + "]"
    elif host.count(":") == 1:  # localhost:8000
        host = host.split(":")[0]
    return host in LOCAL_HOSTS or host.endswith(LOCAL_SUFFIXES) or host.startswith("127.")


def host_of(url: str | None) -> str:
    if not url:
        return ""
    try:
        return urlsplit(url if "//" in url else "//" + url).hostname or ""
    except ValueError:
        return ""


def color_value(color: object) -> str:
    """A palette name or a ``#hex`` color, as ``#rrggbb``. Anything else raises ``ValueError``."""
    text = str(color or "").strip()
    if text.lower() in PALETTE:
        return PALETTE[text.lower()]
    if _HEX.fullmatch(text):
        if len(text) == 4:
            text = "#" + "".join(ch * 2 for ch in text[1:])
        return text.lower()
    raise ValueError(f"Unknown color {color!r}: use a name like 'red' or a hex color like '#dc2626'")


def text_color_for(hex_color: str) -> str:
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))

    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    luminance = 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
    # contrast with white vs. with near-black (#111827, luminance ~0.012)
    return "#ffffff" if (1.05 / (luminance + 0.05)) >= ((luminance + 0.05) / 0.062) else "#111827"


def default_label(name: str) -> str:
    return LABELS.get(name) or name.replace("-", " ").replace("_", " ").title() or "Unknown"


def git_branch(start: str | Path | None = None) -> str | None:
    """The branch in ``.git/HEAD`` above ``start`` (default: the working folder), or a short commit.

    Reads the file only: no ``git`` command runs. ``None`` when there is no repository.
    """
    try:
        folder = Path(start or os.getcwd()).resolve()
    except (OSError, RuntimeError):
        return None
    for path in (folder, *folder.parents):
        dot_git = path / ".git"
        try:
            if dot_git.is_file():  # worktrees and submodules: "gitdir: /path/to/real/git/dir"
                text = dot_git.read_text(encoding="utf-8", errors="replace").strip()
                if not text.startswith("gitdir:"):
                    return None
                git_dir = Path(text[7:].strip())
                dot_git = git_dir if git_dir.is_absolute() else (path / git_dir)
            head_file = dot_git / "HEAD"
            if not head_file.is_file():
                continue
            head = head_file.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return None
        if head.startswith("ref:"):
            ref = head[4:].strip()
            return ref.removeprefix("refs/heads/") or None
        return head[:7] or None
    return None
