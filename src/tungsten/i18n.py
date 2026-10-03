"""Translations.

Text is looked up by its English wording, like gettext. Language files are
JSON objects in ``tungsten/lang/<locale>.json`` (built in) and in any folder
you pass as ``Panel(lang_dirs=[...])``. Your files win, so you can also
change Tungsten's own wording::

    # lang/hi.json
    {"Products": "उत्पाद", "Welcome back, :name": "फिर से स्वागत है, :name"}

Use ``__()`` (or ``_``) in your own code and templates::

    from tungsten import __
    Notification(__("Order shipped")).send(ctx)
    TextInput("name").label(__("Full name"))   # or let Tungsten translate the label at render time

Placeholders use ``:name``. The current language comes from the user's
choice (language switcher), then the browser's ``Accept-Language`` header,
then ``Panel(locale=...)``.
"""

from __future__ import annotations

import contextvars
import json
import re
from pathlib import Path
from typing import Any, Iterable

BUILTIN_DIR = Path(__file__).with_name("lang")

#: language names shown in the switcher
LANGUAGE_NAMES = {
    "en": "English", "hi": "हिन्दी", "gu": "ગુજરાતી", "mr": "मराठी", "ta": "தமிழ்", "te": "తెలుగు",
    "bn": "বাংলা", "kn": "ಕನ್ನಡ", "es": "Español", "fr": "Français", "de": "Deutsch", "pt": "Português",
    "it": "Italiano", "nl": "Nederlands", "ar": "العربية", "he": "עברית", "fa": "فارسی", "ur": "اردو",
    "ja": "日本語", "zh": "中文", "ko": "한국어", "ru": "Русский", "tr": "Türkçe", "id": "Bahasa Indonesia",
}
RTL_LOCALES = {"ar", "he", "fa", "ur"}

_current: contextvars.ContextVar[str | None] = contextvars.ContextVar("tungsten_locale", default=None)
_PLACEHOLDER = re.compile(r":([a-zA-Z_][a-zA-Z0-9_]*)")


class Translator:
    """Loads language files and translates text."""

    def __init__(self, default: str = "en", dirs: Iterable[str | Path] = ()) -> None:
        self.default = default
        self.dirs = [BUILTIN_DIR, *[Path(d) for d in dirs]]
        self._cache: dict[str, dict[str, str]] = {}
        #: set this to ``set()`` to record text that has no translation (handy for finding gaps)
        self.missing: set[str] | None = None

    def add_dir(self, path: str | Path) -> None:
        self.dirs.append(Path(path))
        self._cache.clear()

    def messages(self, locale: str) -> dict[str, str]:
        if locale not in self._cache:
            merged: dict[str, str] = {}
            # "pt" first, then "pt_BR" on top
            names = [locale.split("_")[0], locale] if "_" in locale else [locale]
            for directory in self.dirs:
                for name in names:
                    file = directory / f"{name}.json"
                    if file.is_file():
                        merged.update(json.loads(file.read_text(encoding="utf-8")))
            self._cache[locale] = merged
        return self._cache[locale]

    def available(self) -> list[str]:
        found = {"en"}
        for directory in self.dirs:
            if directory.is_dir():
                found.update(f.stem for f in directory.glob("*.json"))
        return sorted(found)

    def translate(self, text: Any, locale: str | None = None, **params: Any) -> str:
        if text is None:
            return ""
        if hasattr(text, "__html__"):  # Markup is HTML the app built itself; keep it as is
            return text
        text = str(text)
        locale = locale or current_locale() or self.default
        if locale != "en":
            found = self.messages(locale).get(text)
            if not found and self.missing is not None and re.search(r"[A-Za-z]{2,}", text):
                self.missing.add(text)
            text = found or text
        if params:
            text = _PLACEHOLDER.sub(lambda m: str(params[m.group(1)]) if m.group(1) in params else m.group(0), text)
        return text

    def negotiate(self, header: str | None, allowed: Iterable[str]) -> str | None:
        """Pick the best allowed locale from an ``Accept-Language`` header."""
        allowed = list(allowed)
        if not header:
            return None
        ranked = []
        for part in header.split(","):
            lang, _, q = part.strip().partition(";q=")
            try:
                ranked.append((float(q or 1), lang.strip().replace("-", "_")))
            except ValueError:
                continue
        for _, lang in sorted(ranked, key=lambda x: -x[0]):
            for candidate in (lang, lang.split("_")[0]):
                if candidate in allowed:
                    return candidate
        return None


#: the translator used when no panel is active (e.g. in scripts)
default_translator = Translator()
_active: contextvars.ContextVar[Translator | None] = contextvars.ContextVar("tungsten_translator", default=None)


def current_locale() -> str | None:
    return _current.get()


def set_locale(locale: str | None, translator: Translator | None = None) -> tuple[Any, Any]:
    """Set the language for the current request (returns tokens for :func:`reset_locale`)."""
    return _current.set(locale), _active.set(translator)


def reset_locale(tokens: tuple[Any, Any]) -> None:
    try:
        _current.reset(tokens[0])
        _active.reset(tokens[1])
    except ValueError:  # pragma: no cover - set in another context
        pass


def translate(text: Any, **params: Any) -> str:
    """Translate ``text`` into the current language, filling ``:placeholders``."""
    translator = _active.get() or default_translator
    return translator.translate(text, **params)


#: text shown by tungsten.js; sent to the browser in the user's language
JS_STRINGS = (
    "Page expired", "Not allowed", "Something went wrong", "Please refresh the page and try again.",
    "The server could not complete the request (:status).", "Connection lost", "Check your internet connection.",
    "You have unsaved changes. Leave this page?", "Copied",
)


def js_translations() -> dict[str, str]:
    return {text: translate(text) for text in JS_STRINGS}


def maybe(value: Any) -> Any:
    """Translate plain strings; leave ``Markup``, None and other values alone."""
    if isinstance(value, str) and not hasattr(value, "__html__"):
        return translate(value)
    return value


# ---------------------------------------------------------------------- extraction
#: calls whose first string argument is UI text
_TEXT_CALLS = {
    "__", "_", "translate", "Notification", "Section", "Tab", "Step", "Fieldset", "Block", "ListTab",
    "NavigationItem", "NavigationGroup", "label", "body", "title", "placeholder", "helper_text", "hint",
    "description", "heading", "subheading", "true_label", "false_label", "modal_heading", "modal_description",
    "modal_submit_action_label", "modal_submit_label", "modal_cancel_action_label", "success_notification_title",
    "success_notification_body", "failure_notification_title", "add_action_label", "key_label", "value_label",
    "submit_label", "search_placeholder", "empty_state", "action", "tooltip", "link_label",
}
#: attributes / class variables that hold UI text
_TEXT_NAMES = {
    "label", "plural_label", "navigation_label", "navigation_group", "title", "heading", "description",
    "subheading", "link_label", "save_label", "default_label", "_label", "_title", "_heading", "_description",
    "_placeholder", "_success_title", "_modal_submit_label", "_modal_cancel_label", "_modal_heading",
    "_modal_description", "_true_label", "_false_label", "_key_label", "_value_label", "_add_label",
    "_submit_label",
}
_TEMPLATE_CALL = re.compile(r"""\b__\(\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")""")


def _is_text(value: Any) -> bool:
    if not isinstance(value, str) or not re.search(r"[A-Za-z]{2,}", value) or "{{" in value:
        return False
    if value in LANGUAGE_NAMES.values():
        return False
    if re.fullmatch(r"[a-z0-9_.:/\-\[\]#&*]+", value) and re.search(r"[_.:/\-\[\]#&*]", value):
        return False  # identifiers and paths
    words = value.split()
    return not (len(words) > 1 and all(re.fullmatch(r"[a-z0-9:/\-\[\]._!%&>]+", w) for w in words)
                and any("-" in w for w in words))  # css classes


def _python_strings(source: str) -> set[str]:
    import ast

    found: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return found

    def add(node: Any, explicit: bool = False) -> None:
        # lowercase snippets ("or", "records") only count when written as __("...")
        if isinstance(node, ast.Constant) and _is_text(node.value) and (explicit or not node.value[:1].islower()):
            found.add(node.value)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if name in _TEXT_CALLS and node.args:
                add(node.args[0], explicit=name in ("__", "_", "translate"))
            if name in ("options", "true_label", "false_label") or name.endswith("_labels"):
                for arg in node.args:
                    if isinstance(arg, ast.Dict):
                        for v in arg.values:
                            add(v)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = {t.attr if isinstance(t, ast.Attribute) else t.id if isinstance(t, ast.Name) else "" for t in targets}
            if names & _TEXT_NAMES and node.value is not None:
                add(node.value)
            if names & {"labels", "LABELS", "login_hero", "JS_STRINGS"}:
                value = node.value
                if isinstance(value, ast.BoolOp):  # login_hero or {...}
                    value = value.values[-1]

                def add_nested(v: Any) -> None:  # dict values and list items, skipping icon names
                    if isinstance(v, ast.Dict):
                        for k, item in zip(v.keys, v.values):
                            if not (isinstance(k, ast.Constant) and k.value == "icon"):
                                add_nested(item)
                    elif isinstance(v, (ast.Tuple, ast.List)):
                        for item in v.elts:
                            add_nested(item)
                    else:
                        add(v)

                add_nested(value)
        elif isinstance(node, ast.Tuple) and len(node.elts) == 2:
            # ("Contains", "text") style operator tables
            first, second = node.elts
            if isinstance(second, ast.Constant) and (second.value is None or (
                    isinstance(second.value, str) and second.value.isalpha() and second.value.islower())):
                add(first)
    return found


def extract_strings(paths: Iterable[str | Path]) -> set[str]:
    """Find translatable text in ``.py`` files and ``__()`` calls in ``.html`` templates under ``paths``."""
    found: set[str] = set()
    for root in paths:
        root = Path(root)
        files = [root] if root.is_file() else [*root.rglob("*.py"), *root.rglob("*.html")]
        for file in files:
            if any(part in {".venv", "node_modules", "__pycache__", "tests"} for part in file.parts):
                continue
            text = file.read_text(encoding="utf-8", errors="ignore")
            if file.suffix == ".py":
                found |= _python_strings(text)
                continue
            for m in _TEMPLATE_CALL.finditer(text):
                value = m.group(1) if m.group(1) is not None else m.group(2)
                value = value.replace("\\'", "'").replace('\\"', '"')
                if _is_text(value):
                    found.add(value)
    return found


def update_language_file(file: str | Path, strings: Iterable[str]) -> tuple[int, int]:
    """Add missing keys (empty values) to a JSON language file. Returns (added, untranslated)."""
    file = Path(file)
    data: dict[str, str] = json.loads(file.read_text(encoding="utf-8")) if file.is_file() else {}
    added = 0
    for text in strings:
        if text not in data:
            data[text] = ""
            added += 1
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(dict(sorted(data.items(), key=lambda kv: kv[0].lower())), ensure_ascii=False,
                               indent=2) + "\n", encoding="utf-8")
    return added, sum(1 for v in data.values() if not v)


def is_rtl(locale: str | None) -> bool:
    return (locale or "").split("_")[0] in RTL_LOCALES


__ = translate
_ = translate

__all__ = ["LANGUAGE_NAMES", "Translator", "_", "__", "current_locale", "extract_strings", "is_rtl", "maybe", "set_locale",
           "translate", "update_language_file"]
