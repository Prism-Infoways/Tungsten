"""Color palettes (CSS variables) and the literal class names used for each color.

Class strings are written out in full so the Tailwind build can find them.
"""

from __future__ import annotations

SHADES = (50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950)
COLOR_NAMES = ("primary", "success", "danger", "warning", "info", "gray", "purple", "teal", "pink", "indigo")

DEFAULT_COLORS = {
    "primary": "orange",
    "success": "green",
    "danger": "red",
    "warning": "amber",
    "info": "blue",
    "gray": "zinc",
    "sidebar": "zinc",
    "purple": "violet",
    "teal": "teal",
    "pink": "pink",
    "indigo": "indigo",
}


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))  # type: ignore[return-value]


def palette_from_hex(value: str) -> dict[int, tuple[int, int, int]]:
    """Make an 11-shade palette (50-950) from one brand color (used as 500)."""
    base = _hex_to_rgb(value)
    white, black = (255, 255, 255), (0, 0, 0)
    tints = {50: 0.95, 100: 0.9, 200: 0.75, 300: 0.6, 400: 0.3}
    shades = {600: 0.12, 700: 0.28, 800: 0.42, 900: 0.55, 950: 0.72}
    out: dict[int, tuple[int, int, int]] = {}
    for s, t in tints.items():
        out[s] = _mix(base, white, t)
    out[500] = base
    for s, t in shades.items():
        out[s] = _mix(base, black, t)
    return out


def resolve_palette(value: str | dict) -> dict[int, tuple[int, int, int]]:
    """Accept a Tailwind palette name (``"indigo"``), a hex color, or a dict of shades."""
    from .palettes import PALETTES

    if isinstance(value, dict):
        return {int(k): _hex_to_rgb(v) if isinstance(v, str) else tuple(v) for k, v in value.items()}
    if value in PALETTES:
        return {int(k): _hex_to_rgb(v) for k, v in PALETTES[value].items()}
    return palette_from_hex(value)


def css_variables(colors: dict[str, str | dict]) -> str:
    merged = {**DEFAULT_COLORS, **(colors or {})}
    lines = []
    for name, value in merged.items():
        pal = resolve_palette(value)
        for shade in SHADES:
            r, g, b = pal.get(shade, pal.get(500, (128, 128, 128)))
            lines.append(f"--tw-c-{name}-{shade}:{r} {g} {b};")
    return ":root{" + "".join(lines) + "}"


BADGE = {
    "primary": "bg-primary-50 text-primary-700 ring-primary-600/20 dark:bg-primary-400/10 dark:text-primary-400 dark:ring-primary-400/30",
    "success": "bg-success-50 text-success-700 ring-success-600/20 dark:bg-success-400/10 dark:text-success-400 dark:ring-success-400/30",
    "danger": "bg-danger-50 text-danger-700 ring-danger-600/20 dark:bg-danger-400/10 dark:text-danger-400 dark:ring-danger-400/30",
    "warning": "bg-warning-50 text-warning-700 ring-warning-600/20 dark:bg-warning-400/10 dark:text-warning-400 dark:ring-warning-400/30",
    "info": "bg-info-50 text-info-700 ring-info-600/20 dark:bg-info-400/10 dark:text-info-400 dark:ring-info-400/30",
    "gray": "bg-gray-50 text-gray-600 ring-gray-600/20 dark:bg-gray-400/10 dark:text-gray-400 dark:ring-gray-400/20",
    "purple": "bg-purple-50 text-purple-700 ring-purple-600/20 dark:bg-purple-400/10 dark:text-purple-400 dark:ring-purple-400/30",
    "teal": "bg-teal-50 text-teal-700 ring-teal-600/20 dark:bg-teal-400/10 dark:text-teal-400 dark:ring-teal-400/30",
    "pink": "bg-pink-50 text-pink-700 ring-pink-600/20 dark:bg-pink-400/10 dark:text-pink-400 dark:ring-pink-400/30",
    "indigo": "bg-indigo-50 text-indigo-700 ring-indigo-600/20 dark:bg-indigo-400/10 dark:text-indigo-400 dark:ring-indigo-400/30",
}

BUTTON = {
    "primary": "bg-primary-600 text-white shadow-sm hover:bg-primary-500 focus-visible:ring-primary-500/50 dark:bg-primary-500 dark:hover:bg-primary-400",
    "success": "bg-success-600 text-white shadow-sm hover:bg-success-500 focus-visible:ring-success-500/50 dark:bg-success-500 dark:hover:bg-success-400",
    "danger": "bg-danger-600 text-white shadow-sm hover:bg-danger-500 focus-visible:ring-danger-500/50 dark:bg-danger-500 dark:hover:bg-danger-400",
    "warning": "bg-warning-500 text-white shadow-sm hover:bg-warning-400 focus-visible:ring-warning-500/50",
    "info": "bg-info-600 text-white shadow-sm hover:bg-info-500 focus-visible:ring-info-500/50 dark:bg-info-500 dark:hover:bg-info-400",
    "gray": "bg-white text-gray-950 shadow-sm ring-1 ring-gray-950/10 hover:bg-gray-50 dark:bg-white/5 dark:text-white dark:ring-white/20 dark:hover:bg-white/10",
    "purple": "bg-purple-600 text-white shadow-sm hover:bg-purple-500 focus-visible:ring-purple-500/50 dark:bg-purple-500 dark:hover:bg-purple-400",
    "teal": "bg-teal-600 text-white shadow-sm hover:bg-teal-500 focus-visible:ring-teal-500/50 dark:bg-teal-500 dark:hover:bg-teal-400",
    "pink": "bg-pink-600 text-white shadow-sm hover:bg-pink-500 focus-visible:ring-pink-500/50 dark:bg-pink-500 dark:hover:bg-pink-400",
    "indigo": "bg-indigo-600 text-white shadow-sm hover:bg-indigo-500 focus-visible:ring-indigo-500/50 dark:bg-indigo-500 dark:hover:bg-indigo-400",
}

LINK = {
    "primary": "text-primary-600 hover:text-primary-500 dark:text-primary-400 dark:hover:text-primary-300",
    "success": "text-success-600 hover:text-success-500 dark:text-success-400",
    "danger": "text-danger-600 hover:text-danger-500 dark:text-danger-400",
    "warning": "text-warning-600 hover:text-warning-500 dark:text-warning-400",
    "info": "text-info-600 hover:text-info-500 dark:text-info-400",
    "gray": "text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200",
    "purple": "text-purple-600 hover:text-purple-500 dark:text-purple-400",
    "teal": "text-teal-600 hover:text-teal-500 dark:text-teal-400",
    "pink": "text-pink-600 hover:text-pink-500 dark:text-pink-400",
    "indigo": "text-indigo-600 hover:text-indigo-500 dark:text-indigo-400",
}

ICON_BUTTON = {
    "primary": "text-primary-600 hover:bg-primary-50 dark:text-primary-400 dark:hover:bg-primary-400/10",
    "success": "text-success-600 hover:bg-success-50 dark:text-success-400 dark:hover:bg-success-400/10",
    "danger": "text-danger-600 hover:bg-danger-50 dark:text-danger-400 dark:hover:bg-danger-400/10",
    "warning": "text-warning-600 hover:bg-warning-50 dark:text-warning-400 dark:hover:bg-warning-400/10",
    "info": "text-info-600 hover:bg-info-50 dark:text-info-400 dark:hover:bg-info-400/10",
    "gray": "text-gray-500 hover:bg-gray-100 hover:text-gray-700 dark:text-gray-400 dark:hover:bg-white/5",
    "purple": "text-purple-600 hover:bg-purple-50 dark:text-purple-400 dark:hover:bg-purple-400/10",
    "teal": "text-teal-600 hover:bg-teal-50 dark:text-teal-400 dark:hover:bg-teal-400/10",
    "pink": "text-pink-600 hover:bg-pink-50 dark:text-pink-400 dark:hover:bg-pink-400/10",
    "indigo": "text-indigo-600 hover:bg-indigo-50 dark:text-indigo-400 dark:hover:bg-indigo-400/10",
}

TEXT = {
    "primary": "text-primary-600 dark:text-primary-400",
    "success": "text-success-600 dark:text-success-400",
    "danger": "text-danger-600 dark:text-danger-400",
    "warning": "text-warning-600 dark:text-warning-400",
    "info": "text-info-600 dark:text-info-400",
    "gray": "text-gray-500 dark:text-gray-400",
    "purple": "text-purple-600 dark:text-purple-400",
    "teal": "text-teal-600 dark:text-teal-400",
    "pink": "text-pink-600 dark:text-pink-400",
    "indigo": "text-indigo-600 dark:text-indigo-400",
}

SOFT_ICON = {
    "primary": "bg-primary-50 text-primary-600 dark:bg-primary-500/10 dark:text-primary-400",
    "success": "bg-success-50 text-success-600 dark:bg-success-500/10 dark:text-success-400",
    "danger": "bg-danger-50 text-danger-600 dark:bg-danger-500/10 dark:text-danger-400",
    "warning": "bg-warning-50 text-warning-600 dark:bg-warning-500/10 dark:text-warning-400",
    "info": "bg-info-50 text-info-600 dark:bg-info-500/10 dark:text-info-400",
    "gray": "bg-gray-100 text-gray-600 dark:bg-white/5 dark:text-gray-400",
    "purple": "bg-purple-50 text-purple-600 dark:bg-purple-500/10 dark:text-purple-400",
    "teal": "bg-teal-50 text-teal-600 dark:bg-teal-500/10 dark:text-teal-400",
    "pink": "bg-pink-50 text-pink-600 dark:bg-pink-500/10 dark:text-pink-400",
    "indigo": "bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-400",
}


def pick(table: dict[str, str], color: str | None) -> str:
    return table.get(color or "gray", table["gray"])

# Outlined/soft buttons (bulk action bar, secondary actions).
SOFT_BUTTON = {
    "primary": "bg-primary-50 text-primary-700 ring-1 ring-primary-600/20 hover:bg-primary-100 dark:bg-primary-500/10 dark:text-primary-400 dark:ring-primary-400/30 dark:hover:bg-primary-500/20",
    "success": "bg-success-50 text-success-700 ring-1 ring-success-600/20 hover:bg-success-100 dark:bg-success-500/10 dark:text-success-400 dark:ring-success-400/30 dark:hover:bg-success-500/20",
    "danger": "bg-danger-50 text-danger-700 ring-1 ring-danger-600/20 hover:bg-danger-100 dark:bg-danger-500/10 dark:text-danger-400 dark:ring-danger-400/30 dark:hover:bg-danger-500/20",
    "warning": "bg-warning-50 text-warning-700 ring-1 ring-warning-600/20 hover:bg-warning-100 dark:bg-warning-500/10 dark:text-warning-400 dark:ring-warning-400/30 dark:hover:bg-warning-500/20",
    "info": "bg-info-50 text-info-700 ring-1 ring-info-600/20 hover:bg-info-100 dark:bg-info-500/10 dark:text-info-400 dark:ring-info-400/30 dark:hover:bg-info-500/20",
    "gray": "bg-white text-gray-700 ring-1 ring-gray-950/10 hover:bg-gray-50 dark:bg-white/5 dark:text-gray-200 dark:ring-white/10 dark:hover:bg-white/10",
    "purple": "bg-purple-50 text-purple-700 ring-1 ring-purple-600/20 hover:bg-purple-100 dark:bg-purple-500/10 dark:text-purple-400 dark:ring-purple-400/30 dark:hover:bg-purple-500/20",
    "teal": "bg-teal-50 text-teal-700 ring-1 ring-teal-600/20 hover:bg-teal-100 dark:bg-teal-500/10 dark:text-teal-400 dark:ring-teal-400/30 dark:hover:bg-teal-500/20",
    "pink": "bg-pink-50 text-pink-700 ring-1 ring-pink-600/20 hover:bg-pink-100 dark:bg-pink-500/10 dark:text-pink-400 dark:ring-pink-400/30 dark:hover:bg-pink-500/20",
    "indigo": "bg-indigo-50 text-indigo-700 ring-1 ring-indigo-600/20 hover:bg-indigo-100 dark:bg-indigo-500/10 dark:text-indigo-400 dark:ring-indigo-400/30 dark:hover:bg-indigo-500/20",
}

# Raw hex-ish CSS var references for charts/sparklines.
def css_rgb(color: str, shade: int = 500) -> str:
    return f"rgb(var(--tw-c-{color if color in COLOR_NAMES else 'primary'}-{shade}))"
