"""The rich text editor (Trix) with a configurable toolbar, file attachments,
@mentions and custom blocks, plus :func:`render_rich_content` to show the result."""

from __future__ import annotations

import html as htmllib
import json
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Any, Callable

from markupsafe import Markup

from ..i18n import translate as __
from ..support.evaluate import call, evaluate
from ..support.html import BLOCK_TYPE, MENTION_TYPE, clean_attachment, default_attachment_content, sanitize
from .fields import TAG_RE, Block, Field, normalize_options

if TYPE_CHECKING:  # pragma: no cover
    from .form import Form

#: toolbar buttons: name -> (group, trix attribute or action, icon class or text, shortcut key, label)
BUTTONS: dict[str, tuple[str, str, str, str | None, str]] = {
    "bold": ("text", "attribute:bold", "icon-bold", "b", "Bold"),
    "italic": ("text", "attribute:italic", "icon-italic", "i", "Italic"),
    "underline": ("text", "attribute:underline", "text:U", "u", "Underline"),
    "strike": ("text", "attribute:strike", "icon-strike", None, "Strikethrough"),
    "link": ("text", "attribute:href", "icon-link", "k", "Link"),
    "h1": ("block", "attribute:heading1", "icon-heading-1", None, "Heading"),
    "h2": ("block", "attribute:heading2", "text:H2", None, "Heading 2"),
    "h3": ("block", "attribute:heading3", "text:H3", None, "Heading 3"),
    "blockquote": ("block", "attribute:quote", "icon-quote", None, "Quote"),
    "codeBlock": ("block", "attribute:code", "icon-code", None, "Code"),
    "bulletList": ("block", "attribute:bullet", "icon-bullet-list", None, "Bullets"),
    "orderedList": ("block", "attribute:number", "icon-number-list", None, "Numbers"),
    "outdent": ("block", "action:decreaseNestingLevel", "icon-decrease-nesting-level", None, "Decrease level"),
    "indent": ("block", "action:increaseNestingLevel", "icon-increase-nesting-level", None, "Increase level"),
    "attachFiles": ("file", "action:attachFiles", "icon-attach", None, "Attach files"),
    "undo": ("history", "action:undo", "icon-undo", "z", "Undo"),
    "redo": ("history", "action:redo", "icon-redo", "shift+z", "Redo"),
}
DEFAULT_TOOLBAR = ["bold", "italic", "strike", "link", "h1", "blockquote", "codeBlock", "bulletList", "orderedList",
                   "outdent", "indent", "attachFiles", "undo", "redo"]
IMAGE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"]


class MentionProvider:
    """Who or what can be mentioned after a trigger character::

        RichEditor("body").mentions(MentionProvider("@").items(lambda db: {u.id: u.name for u in ...}))
    """

    def __init__(self, trigger: str = "@") -> None:
        self.trigger = (trigger or "@")[:1]
        self._items: Any = None
        self._search: Callable | None = None
        self._url: Callable | None = None

    def items(self, items: Any) -> "MentionProvider":
        """A dict ``{id: label}``, a list, or a closure returning one."""
        self._items = items
        return self

    def search_using(self, fn: Callable) -> "MentionProvider":
        """Search on the server while typing: ``fn(search)`` returns ``{id: label}`` (for long lists)."""
        self._search = fn
        return self

    def url(self, fn: Callable) -> "MentionProvider":
        """Link mentions when shown with :func:`render_rich_content`: ``fn(id, label)`` returns a URL."""
        self._url = fn
        return self

    def search(self, form: "Form", search: str, limit: int = 20) -> list[tuple[Any, str]]:
        if self._search is not None:
            found = normalize_options(call(self._search, **{**form.ev(), "search": search}))
            return found[:limit]
        s = search.lower()
        return [o for o in normalize_options(evaluate(self._items, **form.ev())) if s in o[1].lower()][:limit]


class RichEditor(Field):
    """Rich text (HTML). Options, all optional::

        RichEditor("body")
            .toolbar_buttons(["bold", "italic", "link", "h2", "bulletList", "attachFiles", "blocks"])
            .file_attachments_directory("posts")
            .mentions([MentionProvider("@").items({1: "Asha", 2: "Ravi"})])
            .blocks([Block("cta").label("Call to action").schema([TextInput("text"), TextInput("url").url()])
                     .render_using(lambda config: f'<a class="btn" href="{config["url"]}">{config["text"]}</a>')])
    """

    template = "tungsten/forms/fields/rich-editor.html"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._max_length: int | None = None
        self._toolbar: list[str] | None = None
        self._disabled_buttons: set[str] = set()
        self._attachments: Any = False
        self._attachments_directory = "attachments"
        self._attachments_types: list[str] = list(IMAGE_TYPES)
        self._attachments_max_kb: int | None = 5120
        self._mentions: list[MentionProvider] = []
        self._blocks: list[Block] = []

    def max_length(self, n: int) -> "RichEditor":
        """Limit the text length. Only the text counts, not the HTML tags."""
        self._max_length = n
        return self

    # ---- toolbar
    def toolbar_buttons(self, buttons: list[str]) -> "RichEditor":
        """Which buttons to show, in order: bold, italic, underline, strike, link, h1, h2, h3,
        blockquote, codeBlock, bulletList, orderedList, outdent, indent, attachFiles, blocks, undo, redo."""
        unknown = [b for b in buttons if b not in BUTTONS and b != "blocks"]
        if unknown:
            raise ValueError(f"Unknown toolbar buttons: {', '.join(unknown)}")
        self._toolbar = list(buttons)
        return self

    def disable_toolbar_buttons(self, buttons: list[str]) -> "RichEditor":
        self._disabled_buttons |= set(buttons)
        return self

    def enable_toolbar_buttons(self, buttons: list[str]) -> "RichEditor":
        """Add buttons to the default toolbar, e.g. ``["underline", "h2", "h3"]``."""
        current = self._toolbar if self._toolbar is not None else list(DEFAULT_TOOLBAR)
        wanted = set(current) | set(buttons)
        order = [b for b in BUTTONS if b not in ("undo", "redo")] + ["blocks", "undo", "redo"]
        self._toolbar = [b for b in order if b in wanted]
        self._disabled_buttons -= set(buttons)
        return self

    def disable_all_toolbar_buttons(self, condition: bool = True) -> "RichEditor":
        self._toolbar = [] if condition else None
        return self

    # ---- attachments
    def file_attachments(self, condition: Any = True) -> "RichEditor":
        """Let users drop or attach files (images by default). They are saved in the panel storage."""
        self._attachments = condition
        return self

    def file_attachments_directory(self, directory: str) -> "RichEditor":
        self._attachments_directory = directory
        self._attachments = self._attachments or True
        return self

    def file_attachments_accepted_types(self, types: list[str]) -> "RichEditor":
        """MIME types such as ``["image/png", "application/pdf"]``; ``"image/*"`` works too."""
        self._attachments_types = list(types)
        self._attachments = self._attachments or True
        return self

    def file_attachments_max_size(self, kilobytes: int | None) -> "RichEditor":
        self._attachments_max_kb = kilobytes
        return self

    # ---- mentions and blocks
    def mentions(self, providers: Any, trigger: str = "@") -> "RichEditor":
        """A list of :class:`MentionProvider`, or the items for one provider (``{id: label}``)."""
        if isinstance(providers, MentionProvider):
            providers = [providers]
        elif not (isinstance(providers, list) and providers and isinstance(providers[0], MentionProvider)):
            providers = [MentionProvider(trigger).items(providers)]
        self._mentions.extend(providers)
        return self

    def blocks(self, blocks: list[Block]) -> "RichEditor":
        """Custom blocks users insert from the toolbar. A block with a schema opens a form first."""
        self._blocks = list(blocks)
        return self

    # ---- helpers
    @staticmethod
    def text_length(value: Any) -> int:
        """Length of the text in an HTML value (tags removed, entities decoded)."""
        return len(htmllib.unescape(TAG_RE.sub("", str(value or ""))))

    def get_toolbar(self, form: "Form", base: str) -> list[str]:
        buttons = self._toolbar if self._toolbar is not None else list(DEFAULT_TOOLBAR)
        if self._blocks and self._toolbar is None:
            buttons = buttons[:-2] + ["blocks"] + buttons[-2:]
        attach = self.attachments_enabled(form, base)
        return [b for b in buttons if b not in self._disabled_buttons
                and (b != "attachFiles" or attach) and (b != "blocks" or self._blocks)]

    def attachments_enabled(self, form: "Form", base: str = "") -> bool:
        return bool(evaluate(self._attachments, **form.ev(base)))

    def block(self, name: str) -> Block | None:
        return next((b for b in self._blocks if b.name == name), None)

    def check_attachment(self, filename: str, content_type: str, size: int) -> str | None:
        """An error message, or None when the file may be attached."""
        allowed = self._attachments_types
        ok = any(content_type == t or (t.endswith("/*") and content_type.startswith(t[:-1])) for t in allowed)
        if allowed and not ok:
            return __("This file type is not allowed.")
        if self._attachments_max_kb and size > self._attachments_max_kb * 1024:
            return __("The file may not be greater than :max kilobytes.", max=self._attachments_max_kb)
        return None

    def content_for(self, data: dict) -> str:
        """The HTML Trix shows for a block (its preview) or a mention."""
        if data.get("contentType") == BLOCK_TYPE:
            block = self.block(data.get("blockId", ""))
            config = data.get("blockConfig") or {}
            if block is not None and getattr(block, "_preview", None) is not None:
                return sanitize(str(call(block._preview, config=config, block=block)))
            label = block.get_label() if block is not None else data.get("blockLabel", "")
            summary = block.summary(config) if block is not None else ""
            return (f'<span class="tw-block"><strong>{htmllib.escape(label)}</strong>'
                    + (f' <span>{htmllib.escape(summary)}</span>' if summary else "") + "</span>")
        return default_attachment_content(data)

    def clean(self, value: Any) -> str:
        return sanitize(value, attachments=True, content_for=self.content_for)

    def search_options(self, form: "Form", search: str, limit: int = 20) -> list[tuple[Any, str]]:
        """Mention search (``search`` starts with the trigger character)."""
        trigger, query = (search[:1], search[1:]) if search else ("", "")
        provider = next((p for p in self._mentions if p.trigger == trigger), None)
        return provider.search(form, query, limit) if provider is not None else []

    # ---- block actions (insert / edit a block from the toolbar)
    def form_actions(self, form: "Form", base: str) -> list:
        return super().form_actions(form, base) + self._block_actions()

    def _block_actions(self) -> list:
        cached = getattr(self, "_block_actions_cache", None)
        if cached is not None:
            return cached
        from ..actions.action import Action

        out = []
        for block in self._blocks:
            action = (Action(f"block_{block.name}").label(block.get_label()).icon(block._icon)
                      .modal_heading(block.get_label()).modal_submit_label(__("Insert"))
                      .action(self._make_insert(block)))
            if block._schema:
                action.form(block._schema, block._columns)
                action.fill_form(self._make_fill(block))
            out.append(action)
        self._block_actions_cache = out
        return out

    def _editing(self, form: "Form", path: str, block: Block) -> dict | None:
        """The block being edited (sent by the editor), when it is this block."""
        try:
            data = json.loads(form.ui.get(f"{path}.edit") or "")
        except ValueError:
            return None
        if isinstance(data, dict) and data.get("id") == block.name:
            return data
        return None

    def _make_fill(self, block: Block) -> Callable:
        def fill(form: "Form", component: Any) -> dict:
            path = self._path_in(form)
            editing = self._editing(form, path, block) if path else None
            return dict(editing.get("config") or {}) if editing else {}
        return fill

    def _path_in(self, form: "Form") -> str | None:
        for field, path, _ in form.walk_fields():
            if field is self:
                return path
        return None

    def _make_insert(self, block: Block) -> Callable:
        def insert(form: "Form", data: dict) -> None:
            path = self._path_in(form)
            if path is None:
                return None
            config = json.loads(json.dumps(data, default=str))  # plain JSON (dates and decimals as text)
            attachment = {"contentType": BLOCK_TYPE, "blockId": block.name, "blockLabel": block.get_label(),
                          "blockConfig": config}
            attachment["content"] = self.content_for(attachment)
            editing = self._editing(form, path, block)
            try:
                cursor = int(form.ui.get(f"{path}.cursor") or -1)
            except ValueError:
                cursor = -1
            pos = editing.get("pos") if editing else cursor
            inserts = getattr(form, "_rich_inserts", None) or {}
            inserts[path] = {"attachment": attachment, "pos": pos if isinstance(pos, int) else -1,
                             "replace": bool(editing)}
            form._rich_inserts = inserts
            form.ui.pop(f"{path}.edit", None)
            return None
        return insert

    # ---- state
    def cast(self, state: Any) -> Any:
        value = super().cast(state)
        return self.clean(value) if value else None

    def validate_value(self, form: "Form", base: str, value: Any) -> list[str]:
        if self._max_length is not None and self.text_length(value) > self._max_length:
            label = self.get_label(form, base).lower()
            return [__("The :attribute may not be greater than :max characters.", attribute=label, max=self._max_length)]
        return []

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        from .actions import render_action

        v = super().view_data(form, base)
        path = v["path"]
        v["safe_html"] = Markup(self.clean(v["state"] or ""))
        v["maxlength"] = self._max_length
        v["length"] = self.text_length(v["safe_html"])
        # the editor sends "change" to the hidden input itself (after a pause or on blur)
        v["live"] = self.live_attrs(form, "change")
        v["live_delay"] = self._live_debounce
        v["live_on_blur"] = self._live_on_blur
        toolbar = self.get_toolbar(form, base)
        groups: list[tuple[str, list[dict]]] = []
        for name in toolbar:
            if name == "blocks":
                group = "blocks"
                button = {"name": name}
            else:
                group, command, look, key, label = BUTTONS[name]
                kind, _, value = command.partition(":")
                button = {"name": name, "kind": kind, "value": value, "icon": look[5:] if look.startswith("icon-") else None,
                          "text": look[5:] if look.startswith("text:") else None, "key": key, "label": __(label)}
            if not groups or groups[-1][0] != group:
                groups.append((group, []))
            groups[-1][1].append(button)
        v["toolbar"] = groups
        v["has_link"] = "link" in toolbar
        v["attach_url"] = (form.ctx.panel.url("_tw", "form", "attachment")
                           if form.ctx is not None and self.attachments_enabled(form, base) and not v["disabled"] else None)
        v["attach_types"] = ",".join(self._attachments_types)
        v["attach_max"] = self._attachments_max_kb
        mentions = []
        for p in self._mentions:
            entry: dict[str, Any] = {"trigger": p.trigger}
            if p._search is None:
                entry["items"] = [{"id": str(k), "label": label} for k, label in
                                  normalize_options(evaluate(p._items, **form.ev(base)))[:500]]
            mentions.append(entry)
        v["mentions"] = json.dumps(mentions) if mentions else None
        v["search_url"] = form.ctx.panel.url("_tw", "form", "options") if mentions and form.ctx else None
        v["blocks"] = [] if v["disabled"] else [
            {"name": b.name, "label": b.get_label(), "icon": b._icon,
             "button": render_action(a, form, self, base, style="dropdown")}
            for b, a in zip(self._blocks, self._block_actions())]
        v["cursor"] = form.ui.get(f"{path}.cursor", "")
        insert = (getattr(form, "_rich_inserts", None) or {}).get(path)
        v["insert"] = json.dumps(insert) if insert else None
        return v


# ---------------------------------------------------------------------- output
class _ContentRenderer(HTMLParser):
    def __init__(self, blocks: dict[str, Block], mention: Callable | None) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.blocks = blocks
        self.mention = mention
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs_):
        if self.skip_depth:
            if tag == "figure":
                self.skip_depth += 1
            return
        if tag == "figure":
            data = clean_attachment(dict(attrs_).get("data-trix-attachment"))
            if data and data.get("contentType") in (BLOCK_TYPE, MENTION_TYPE):
                self.out.append(self.replacement(data))
                self.skip_depth = 1
                return
        self.out.append(self.get_starttag_text() or "")

    def handle_startendtag(self, tag, attrs_):
        if not self.skip_depth:
            self.out.append(self.get_starttag_text() or "")

    def handle_endtag(self, tag):
        if self.skip_depth:
            if tag == "figure":
                self.skip_depth -= 1
            return
        self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.skip_depth:
            self.out.append(htmllib.escape(data, quote=False))

    def replacement(self, data: dict) -> str:
        if data["contentType"] == MENTION_TYPE:
            text = htmllib.escape(data["mentionTrigger"] + data["mentionLabel"])
            url = self.mention(data["mentionTrigger"], data["mentionId"], data["mentionLabel"]) if self.mention else None
            ident = htmllib.escape(data["mentionId"])
            if url:
                return f'<a href="{htmllib.escape(str(url))}" class="tw-mention" data-mention="{ident}">{text}</a>'
            return f'<span class="tw-mention" data-mention="{ident}">{text}</span>'
        block = self.blocks.get(data["blockId"])
        if block is None or getattr(block, "_render", None) is None:
            return ""
        return str(call(block._render, config=data.get("blockConfig") or {}, block=block))


def render_rich_content(value: Any, blocks: list[Block] | None = None, mentions: list[MentionProvider] | None = None,
                        editor: RichEditor | None = None) -> Markup:
    """Turn a RichEditor value into HTML for a page: blocks are drawn with their
    ``render_using`` and mentions become links (``MentionProvider.url``)::

        render_rich_content(post.body, editor=PostResource.body_editor())
    """
    if editor is not None:
        blocks = blocks if blocks is not None else editor._blocks
        mentions = mentions if mentions is not None else editor._mentions
    providers = {p.trigger: p for p in mentions or []}

    def mention_url(trigger: str, ident: str, label: str) -> Any:
        p = providers.get(trigger)
        return call(p._url, id=ident, label=label) if p is not None and p._url is not None else None

    clean = sanitize(value, attachments=True)
    renderer = _ContentRenderer({b.name: b for b in blocks or []}, mention_url)
    renderer.feed(clean)
    renderer.close()
    return Markup("".join(renderer.out))


def mentions_in(value: Any, trigger: str | None = None) -> list[dict]:
    """The mentions in a RichEditor value: ``[{"trigger", "id", "label"}]`` (e.g. to notify people)."""
    found: list[dict] = []

    class _Finder(HTMLParser):
        def handle_starttag(self, tag, attrs_):
            if tag == "figure":
                data = clean_attachment(dict(attrs_).get("data-trix-attachment"))
                if data and data.get("contentType") == MENTION_TYPE and (trigger is None or data["mentionTrigger"] == trigger):
                    found.append({"trigger": data["mentionTrigger"], "id": data["mentionId"], "label": data["mentionLabel"]})

    finder = _Finder(convert_charrefs=True)
    finder.feed(str(value or ""))
    finder.close()
    return found


__all__ = ["MentionProvider", "RichEditor", "mentions_in", "render_rich_content"]
