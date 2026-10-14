"""A small, forgiving PHP reader.

It is not a full PHP parser. It understands the parts of PHP that Laravel models,
migrations and Filament resources are written in: classes, properties, methods,
``use`` imports, enums, arrays, strings, ``Foo::make('x')->bar()`` chains and
named arguments. Anything else (closures, ``match``, maths, string joins) is kept
as :class:`Raw` source text, so the converter can say "this part needs a human"
instead of failing.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# --------------------------------------------------------------------- tokens
@dataclass
class Token:
    kind: str  # str, num, var, name, op, eof
    value: Any
    start: int
    end: int
    line: int


_OPS = sorted(
    ["?->", "===", "!==", "<=>", "**=", "...", "??=", "::", "->", "=>", "==", "!=", "<=", ">=", "&&", "||",
     "??", "++", "--", "+=", "-=", ".=", "*=", "/=", "<<", ">>", "**"],
    key=len, reverse=True,
)
_NAME = re.compile(r"[A-Za-z_\\\x80-￿][A-Za-z0-9_\\\x80-￿]*")
_NUM = re.compile(r"0[xX][0-9a-fA-F_]+|0[bB][01_]+|(?:\d[\d_]*)?\.?\d[\d_]*(?:[eE][+-]?\d+)?")
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "v": "\v", "e": "\x1b", "f": "\f", "0": "\0",
            "\\": "\\", "$": "$", '"': '"'}


def tokenize(src: str) -> list[Token]:
    out: list[Token] = []
    i, n, line = 0, len(src), 1
    if src.startswith("<?php"):
        i = 5
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c in " \t\r\f\v":
            i += 1
            continue
        if src.startswith("<?php", i):
            i += 5
            continue
        if src.startswith("?>", i):
            i += 2
            continue
        if src.startswith("#[", i):  # PHP 8 attribute: skip it with its brackets
            depth, j = 0, i + 1
            while j < n:
                if src[j] == "[":
                    depth += 1
                elif src[j] == "]":
                    depth -= 1
                    if depth == 0:
                        break
                elif src[j] in "'\"":
                    j = _skip_string(src, j)
                    continue
                j += 1
            line += src.count("\n", i, j)
            i = j + 1
            continue
        if c == "#" or src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            line += src.count("\n", i, j)
            i = j
            continue
        start, start_line = i, line
        if c == "'":
            j, buf = i + 1, []
            while j < n and src[j] != "'":
                if src[j] == "\\" and j + 1 < n and src[j + 1] in "'\\":
                    buf.append(src[j + 1])
                    j += 2
                    continue
                buf.append(src[j])
                j += 1
            text = "".join(buf)
            line += text.count("\n")
            out.append(Token("str", text, start, j + 1, start_line))
            i = j + 1
            continue
        if c == '"':
            j, buf, interpolated = i + 1, [], False
            while j < n and src[j] != '"':
                if src[j] == "\\" and j + 1 < n:
                    nxt = src[j + 1]
                    buf.append(_ESCAPES.get(nxt, "\\" + nxt))
                    j += 2
                    continue
                if src[j] == "$" and j + 1 < n and (src[j + 1] == "{" or src[j + 1].isalpha() or src[j + 1] == "_"):
                    interpolated = True
                if src[j] == "{" and j + 1 < n and src[j + 1] == "$":
                    interpolated = True
                buf.append(src[j])
                j += 1
            text = "".join(buf)
            line += text.count("\n")
            out.append(Token("istr" if interpolated else "str", text, start, j + 1, start_line))
            i = j + 1
            continue
        if src.startswith("<<<", i):  # heredoc / nowdoc
            m = re.match(r"<<<[ \t]*(['\"]?)([A-Za-z_]\w*)\1\r?\n", src[i:])
            if m:
                label = m.group(2)
                body_start = i + m.end()
                end = re.compile(r"^[ \t]*" + re.escape(label) + r"\b", re.MULTILINE).search(src, body_start)
                stop = end.start() if end else n
                text = src[body_start:stop].rstrip("\n")
                j = end.end() if end else n
                line += src.count("\n", i, j)
                out.append(Token("istr" if m.group(1) != "'" and "$" in text else "str", text, start, j, start_line))
                i = j
                continue
        if c == "$" and i + 1 < n and (src[i + 1].isalpha() or src[i + 1] == "_"):
            m = _NAME.match(src, i + 1)
            assert m
            out.append(Token("var", m.group(0), start, m.end(), line))
            i = m.end()
            continue
        if c.isdigit() or (c == "." and i + 1 < n and src[i + 1].isdigit()):
            m = _NUM.match(src, i)
            if m and m.group(0):
                text = m.group(0).replace("_", "")
                try:
                    value: Any = int(text, 0) if not re.search(r"[.eE]", text) or text[:2].lower() == "0x" else float(text)
                except ValueError:
                    value = float(text) if re.search(r"[.eE]", text) else int(text.lstrip("0") or "0")
                out.append(Token("num", value, start, m.end(), line))
                i = m.end()
                continue
        m = _NAME.match(src, i)
        if m:
            out.append(Token("name", m.group(0), start, m.end(), line))
            i = m.end()
            continue
        for op in _OPS:
            if src.startswith(op, i):
                out.append(Token("op", op, start, i + len(op), line))
                i += len(op)
                break
        else:
            out.append(Token("op", c, start, i + 1, line))
            i += 1
    out.append(Token("eof", None, n, n, line))
    return out


def _skip_string(src: str, i: int) -> int:
    quote, j = src[i], i + 1
    while j < len(src) and src[j] != quote:
        j += 2 if src[j] == "\\" else 1
    return j + 1


# ------------------------------------------------------------------------ AST
@dataclass
class Node:
    src: str = field(default="", repr=False, compare=False)
    line: int = field(default=0, repr=False, compare=False)


@dataclass
class Str(Node):
    value: str = ""


@dataclass
class Num(Node):
    value: Any = 0


@dataclass
class Const(Node):
    """``true``, ``false``, ``null`` or a bare constant name."""
    name: str = ""


@dataclass
class Arr(Node):
    items: list = field(default_factory=list)  # [(key Node | None, value Node)]


@dataclass
class Arg(Node):
    name: str | None = None
    value: Node | None = None


@dataclass
class StaticCall(Node):
    cls: str = ""
    method: str = ""
    args: list = field(default_factory=list)


@dataclass
class ClassConst(Node):
    """``Foo::class``, ``Foo::BAR`` or ``Status::Active`` (an enum case)."""
    cls: str = ""
    name: str = ""


@dataclass
class Call(Node):
    func: str = ""
    args: list = field(default_factory=list)


@dataclass
class MethodCall(Node):
    obj: Node | None = None
    method: str = ""
    args: list = field(default_factory=list)


@dataclass
class Prop(Node):
    obj: Node | None = None
    name: str = ""


@dataclass
class Var(Node):
    name: str = ""


@dataclass
class New(Node):
    cls: str = ""
    args: list = field(default_factory=list)


@dataclass
class Closure(Node):
    pass


@dataclass
class Raw(Node):
    pass


class ParseError(Exception):
    pass


_STOP = {",", ")", "]", "}", ";", "=>"}
_OPEN = {"(": ")", "[": "]", "{": "}"}


class Parser:
    def __init__(self, src: str, tokens: list[Token] | None = None, pos: int = 0) -> None:
        self.src = src
        self.toks = tokens if tokens is not None else tokenize(src)
        self.i = pos

    # ---- helpers
    @property
    def tok(self) -> Token:
        return self.toks[self.i]

    def peek(self, k: int = 1) -> Token:
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def at(self, value: str, kind: str = "op") -> bool:
        t = self.tok
        return t.kind == kind and t.value == value

    def at_name(self, *names: str) -> bool:
        return self.tok.kind == "name" and self.tok.value.lower() in names

    def next(self) -> Token:
        t = self.toks[self.i]
        if t.kind != "eof":
            self.i += 1
        return t

    def expect(self, value: str) -> Token:
        if not self.at(value):
            raise ParseError(f"expected {value!r} on line {self.tok.line}, got {self.tok.value!r}")
        return self.next()

    def text(self, start: int) -> str:
        """Source text from token ``start`` up to the current token."""
        if start >= self.i:
            return ""
        return self.src[self.toks[start].start:self.toks[self.i - 1].end]

    def skip_balanced(self) -> None:
        """Skip one bracketed group starting at the current ``(``, ``[`` or ``{``."""
        close = _OPEN[self.tok.value]
        opener = self.tok.value
        depth = 0
        while self.tok.kind != "eof":
            t = self.next()
            if t.kind == "op" and t.value == opener:
                depth += 1
            elif t.kind == "op" and t.value in _OPEN:
                self.i -= 1
                self.skip_balanced()
            elif t.kind == "op" and t.value == close:
                depth -= 1
                if depth == 0:
                    return

    def skip_to_stop(self) -> None:
        """Skip tokens up to the next ``, ) ] } ; =>`` at this depth."""
        while self.tok.kind != "eof":
            t = self.tok
            if t.kind == "op" and t.value in _STOP:
                return
            if t.kind == "op" and t.value in _OPEN:
                self.skip_balanced()
                continue
            self.next()

    # ---- expressions
    def expr(self) -> Node:
        start = self.i
        try:
            node = self._unary()
        except ParseError:
            self.i = start
            node = None
        if node is None or not self._at_stop():
            # an operator, a ternary or something we do not read: keep the source
            self.i = start
            self.skip_to_stop()
            if self.i == start:  # always move forward
                self.next()
            return Raw(src=self.text(start), line=self.toks[start].line)
        return node

    def _at_stop(self) -> bool:
        t = self.tok
        return t.kind == "eof" or (t.kind == "op" and t.value in _STOP)

    def _unary(self) -> Node:
        if self.at("-") and self.peek().kind == "num":
            start = self.i
            self.next()
            t = self.next()
            return self._postfix(Num(value=-t.value, src=self.text(start), line=t.line), start)
        if self.at("&"):  # by-reference
            self.next()
        return self._postfix(self._primary(), self.i)

    def _primary(self) -> Node:
        start = self.i
        t = self.tok
        if t.kind == "str":
            self.next()
            return Str(value=t.value, src=self.text(start), line=t.line)
        if t.kind == "istr":
            self.next()
            return Raw(src=self.text(start), line=t.line)
        if t.kind == "num":
            self.next()
            return Num(value=t.value, src=self.text(start), line=t.line)
        if t.kind == "var":
            self.next()
            return Var(name=t.value, src=self.text(start), line=t.line)
        if t.kind == "op" and t.value == "[":
            return self._array("]", start)
        if t.kind == "op" and t.value == "(":
            self.next()
            inner = self.expr()
            self.expect(")")
            return inner
        if t.kind == "name":
            low = t.value.lower()
            if low == "static" and self.peek().kind == "name" and self.peek().value.lower() in ("fn", "function"):
                self.next()
                return self._primary()
            if low == "fn" and self.peek().value == "(":
                self.next()
                self.skip_balanced()
                if self.at(":"):
                    self.next()
                    self._skip_type()
                self.expect("=>")
                self.expr()
                return Closure(src=self.text(start), line=t.line)
            if low == "function" and self.peek().value == "(":
                self.next()
                self.skip_balanced()
                if self.at_name("use"):
                    self.next()
                    self.skip_balanced()
                if self.at(":"):
                    self.next()
                    self._skip_type()
                if not self.at("{"):
                    raise ParseError("closure without body")
                self.skip_balanced()
                return Closure(src=self.text(start), line=t.line)
            if low == "match" and self.peek().value == "(":
                self.next()
                self.skip_balanced()
                if self.at("{"):
                    self.skip_balanced()
                return Raw(src=self.text(start), line=t.line)
            if low == "array" and self.peek().value == "(":
                self.next()
                return self._array(")", start)
            if low == "new":
                self.next()
                if self.tok.kind != "name":
                    raise ParseError("new without class")
                cls = self.next().value
                args = self._args() if self.at("(") else []
                return New(cls=cls, args=args, src=self.text(start), line=t.line)
            self.next()
            if self.at("::"):
                self.next()
                m = self.next()
                if m.kind not in ("name", "var"):
                    raise ParseError("bad static access")
                if self.at("("):
                    args = self._args()
                    return StaticCall(cls=t.value, method=m.value, args=args, src=self.text(start), line=t.line)
                if m.kind == "var":
                    return Raw(src=self.text(start), line=t.line)
                return ClassConst(cls=t.value, name=m.value, src=self.text(start), line=t.line)
            if self.at("("):
                args = self._args()
                return Call(func=t.value, args=args, src=self.text(start), line=t.line)
            return Const(name=t.value, src=self.text(start), line=t.line)
        raise ParseError(f"unexpected {t.value!r} on line {t.line}")

    def _skip_type(self) -> None:
        while self.tok.kind == "name" or (self.tok.kind == "op" and self.tok.value in ("?", "|", "&", "\\")):
            self.next()

    def _postfix(self, node: Node, start: int) -> Node:
        while True:
            if self.tok.kind == "op" and self.tok.value in ("->", "?->"):
                self.next()
                name_tok = self.next()
                if name_tok.kind != "name":
                    raise ParseError("dynamic property")
                if self.at("("):
                    args = self._args()
                    node = MethodCall(obj=node, method=name_tok.value, args=args, src=self.text(start), line=name_tok.line)
                else:
                    node = Prop(obj=node, name=name_tok.value, src=self.text(start), line=name_tok.line)
                continue
            if self.at("[") or self.at("::"):
                raise ParseError("index or static access on an expression")
            return node

    def _array(self, close: str, start: int) -> Arr:
        line = self.tok.line
        self.next()  # [ or (
        items = []
        while not self.at(close):
            if self.tok.kind == "eof":
                raise ParseError("unclosed array")
            if self.at("..."):
                self.next()
                v = self.expr()
                items.append((None, Raw(src="..." + v.src, line=v.line)))
            else:
                v = self.expr()
                if self.at("=>"):
                    self.next()
                    items.append((v, self.expr()))
                else:
                    items.append((None, v))
            if self.at(","):
                self.next()
            elif not self.at(close):
                raise ParseError(f"expected , or {close} in array on line {self.tok.line}")
        self.next()
        return Arr(items=items, src=self.text(start), line=line)

    def _args(self) -> list[Arg]:
        self.expect("(")
        args = []
        while not self.at(")"):
            if self.tok.kind == "eof":
                raise ParseError("unclosed call")
            a_start = self.i
            name = None
            if self.tok.kind == "name" and self.peek().kind == "op" and self.peek().value == ":":
                name = self.next().value
                self.next()
            if self.at("..."):
                self.next()
                v = self.expr()
                v = Raw(src=self.text(a_start), line=v.line)
            else:
                v = self.expr()
            args.append(Arg(name=name, value=v, src=self.text(a_start), line=v.line))
            if self.at(","):
                self.next()
            elif not self.at(")"):
                raise ParseError(f"expected , or ) in call on line {self.tok.line}")
        self.next()
        return args


def parse_expr(src: str) -> Node:
    return Parser(src).expr()


# ------------------------------------------------------------------ files
@dataclass
class Method:
    name: str
    is_static: bool
    params: str
    body_start: int  # token index just after "{"
    body_end: int  # token index of the closing "}"
    line: int


@dataclass
class Property:
    name: str
    value: Node | None
    is_static: bool
    line: int


@dataclass
class PhpClass:
    name: str
    kind: str  # class, enum, trait, interface
    extends: str | None
    implements: list[str]
    traits: list[str]
    properties: dict[str, Property]
    methods: dict[str, Method]
    constants: dict[str, Node]
    cases: list[tuple[str, Node | None]]
    backing: str | None  # enum backing type
    file: PhpFile
    line: int

    @property
    def fqn(self) -> str:
        return f"{self.file.namespace}\\{self.name}" if self.file.namespace else self.name

    def prop(self, name: str) -> Node | None:
        p = self.properties.get(name)
        return p.value if p else None

    def method(self, name: str) -> Method | None:
        return self.methods.get(name) or self.methods.get(name.lower()) or next(
            (m for k, m in self.methods.items() if k.lower() == name.lower()), None)

    def returns(self, method: str) -> list[Node]:
        """Every ``return <expr>;`` in a method (closures inside it included)."""
        m = self.method(method)
        if m is None:
            return []
        return list(self.file.returns_in(m.body_start, m.body_end))

    def statements(self, method: str) -> list[Node]:
        m = self.method(method)
        return [] if m is None else self.file.statements(m.body_start, m.body_end)

    def resolve(self, name: str) -> str:
        return self.file.resolve(name)


class PhpFile:
    def __init__(self, src: str, path: Path | None = None) -> None:
        self.src = src
        self.path = path
        self.toks = tokenize(src)
        self.namespace = ""
        self.uses: dict[str, str] = {}
        self.classes: list[PhpClass] = []
        self._scan()

    @classmethod
    def read(cls, path: Path) -> PhpFile:
        return cls(path.read_text(encoding="utf-8", errors="replace"), path)

    # ---- names
    def resolve(self, name: str) -> str:
        """The full class name for ``name`` as written in this file."""
        if not name:
            return name
        if name.startswith("\\"):
            return name[1:]
        if name.lower() in ("self", "static", "parent"):
            return name
        head, _, rest = name.partition("\\")
        if head in self.uses:
            return self.uses[head] + ("\\" + rest if rest else "")
        return f"{self.namespace}\\{name}" if self.namespace else name

    # ---- scanning
    def _scan(self) -> None:
        p = Parser(self.src, self.toks)
        while p.tok.kind != "eof":
            t = p.tok
            if t.kind == "name" and t.value.lower() == "namespace":
                p.next()
                if p.tok.kind == "name":
                    self.namespace = p.next().value.lstrip("\\")
                continue
            if t.kind == "name" and t.value.lower() == "use":
                p.next()
                self._use(p)
                continue
            if t.kind == "name" and t.value.lower() in ("class", "enum", "trait", "interface") and \
                    p.peek().kind == "name":
                prev = self.toks[p.i - 1] if p.i else None
                if prev is not None and prev.kind == "op" and prev.value in ("::", "->"):
                    p.next()
                    continue
                self._class(p)
                continue
            if t.kind == "op" and t.value == "{":
                p.skip_balanced()
                continue
            p.next()

    def _use(self, p: Parser) -> None:
        if p.at_name("function", "const"):
            p.next()
        if p.tok.kind != "name":
            return
        base = p.next().value.lstrip("\\")
        if p.at("{") or base.endswith("\\"):
            if p.at("\\"):
                p.next()
            p.expect("{")
            while not p.at("}") and p.tok.kind != "eof":
                if p.tok.kind == "name":
                    name = p.next().value
                    alias = name.rsplit("\\", 1)[-1]
                    if p.at_name("as"):
                        p.next()
                        alias = p.next().value
                    self.uses[alias] = base.rstrip("\\") + "\\" + name
                else:
                    p.next()
            p.next()
            return
        alias = base.rsplit("\\", 1)[-1]
        if p.at_name("as"):
            p.next()
            alias = p.next().value
        self.uses[alias] = base
        while p.at(","):
            p.next()
            if p.tok.kind == "name":
                other = p.next().value.lstrip("\\")
                a = other.rsplit("\\", 1)[-1]
                if p.at_name("as"):
                    p.next()
                    a = p.next().value
                self.uses[a] = other

    def _class(self, p: Parser) -> None:
        kind = p.next().value.lower()
        extends, implements, backing = None, [], None
        if p.at_name("extends", "implements"):  # anonymous class: ``new class extends Migration``
            name_tok = Token("name", "__anonymous__", p.tok.start, p.tok.start, p.tok.line)
        else:
            name_tok = p.next()
        if kind == "enum" and p.at(":"):
            p.next()
            backing = p.next().value
        while not p.at("{") and p.tok.kind != "eof":
            if p.at_name("extends"):
                p.next()
                extends = p.next().value
                while p.at(","):  # interfaces extend several
                    p.next()
                    p.next()
            elif p.at_name("implements"):
                p.next()
                while p.tok.kind == "name":
                    implements.append(p.next().value)
                    if p.at(","):
                        p.next()
            else:
                p.next()
        cls = PhpClass(name=name_tok.value, kind=kind, extends=extends, implements=implements, traits=[],
                       properties={}, methods={}, constants={}, cases=[], backing=backing, file=self,
                       line=name_tok.line)
        if p.tok.kind == "eof":
            return
        p.next()  # {
        self._body(p, cls)
        self.classes.append(cls)

    def _body(self, p: Parser, cls: PhpClass) -> None:
        mods: list[str] = []
        while not p.at("}") and p.tok.kind != "eof":
            t = p.tok
            if t.kind == "name":
                low = t.value.lower()
                if low == "use":
                    p.next()
                    while p.tok.kind == "name":
                        cls.traits.append(p.next().value)
                        if p.at(","):
                            p.next()
                    if p.at("{"):
                        p.skip_balanced()
                    elif p.at(";"):
                        p.next()
                    mods = []
                    continue
                if low == "case" and cls.kind == "enum":
                    p.next()
                    case = p.next().value
                    value = None
                    if p.at("="):
                        p.next()
                        value = p.expr()
                    cls.cases.append((case, value))
                    if p.at(";"):
                        p.next()
                    continue
                if low == "const":
                    p.next()
                    if p.tok.kind == "name" and p.peek().kind == "name":  # typed constant
                        p.next()
                    cname = p.next().value
                    if p.at("="):
                        p.next()
                        cls.constants[cname] = p.expr()
                    while not p.at(";") and p.tok.kind != "eof":
                        p.next()
                    p.next()
                    mods = []
                    continue
                if low == "function":
                    p.next()
                    name_tok = p.next()
                    if name_tok.kind == "op" and name_tok.value == "&":
                        name_tok = p.next()
                    pstart = p.i
                    if p.at("("):
                        p.skip_balanced()
                    params = p.text(pstart)
                    while not p.at("{") and not p.at(";") and p.tok.kind != "eof":
                        p.next()
                    if p.at(";"):  # abstract or interface method
                        p.next()
                    else:
                        body_start = p.i + 1
                        p.skip_balanced()
                        cls.methods[name_tok.value] = Method(
                            name=name_tok.value, is_static="static" in mods, params=params,
                            body_start=body_start, body_end=p.i - 1, line=name_tok.line)
                    mods = []
                    continue
                mods.append(low)
                p.next()
                continue
            if t.kind == "var":
                p.next()
                value = None
                if p.at("="):
                    p.next()
                    value = p.expr()
                cls.properties[t.value] = Property(name=t.value, value=value, is_static="static" in mods, line=t.line)
                if p.at(","):  # several properties in one statement
                    p.next()
                    continue
                if p.at(";"):
                    p.next()
                mods = []
                continue
            if t.kind == "op" and t.value in _OPEN:
                p.skip_balanced()
                continue
            p.next()
        p.next()

    # ---- method bodies
    def returns_in(self, start: int, end: int) -> Iterator[Node]:
        i = start
        while i < end:
            t = self.toks[i]
            if t.kind == "name" and t.value.lower() == "return":
                p = Parser(self.src, self.toks, i + 1)
                if p.at(";"):
                    i += 1
                    continue
                yield p.expr()
                i = max(p.i, i + 1)
                continue
            i += 1

    def statements(self, start: int, end: int) -> list[Node]:
        """Top-level expression statements of a block, each parsed as an expression."""
        out = []
        p = Parser(self.src, self.toks, start)
        while p.i < end and p.tok.kind != "eof":
            if p.at(";"):
                p.next()
                continue
            if p.at("{"):
                p.skip_balanced()
                continue
            if p.at_name("return"):
                p.next()
            before = p.i
            node = p.expr()
            out.append(node)
            if p.i == before:
                p.next()
            if p.at(";") or p.at(")") or p.at("]") or p.at("}") or p.at(",") or p.at("=>"):
                p.next()
        return out

    def find_calls(self, cls_name: str, methods: tuple[str, ...], start: int = 0,
                   end: int | None = None) -> Iterator[StaticCall]:
        """Every ``Cls::method(...)`` call in the file, or in tokens ``start..end`` (``Schema::create(...)``)."""
        lowered = {m.lower() for m in methods}
        stop = len(self.toks) if end is None else end
        for i in range(start, stop):
            t = self.toks[i]
            if t.kind == "name" and t.value.rsplit("\\", 1)[-1] == cls_name and i + 2 < len(self.toks):
                a, b = self.toks[i + 1], self.toks[i + 2]
                if a.kind == "op" and a.value == "::" and b.kind == "name" and b.value.lower() in lowered:
                    p = Parser(self.src, self.toks, i)
                    try:
                        node = p._primary()
                    except ParseError:
                        continue
                    if isinstance(node, StaticCall):
                        yield node


def closure_statements(node: Closure) -> list[Node]:
    holder = PhpFile("<?php class __Holder__ { function body() " + node.src[node.src.find("{"):] + " }") \
        if "{" in node.src else None
    if holder is None or not holder.classes:
        return []
    return holder.classes[0].statements("body")


# ------------------------------------------------------------------ helpers
def literal(node: Node | None) -> Any:
    """The Python value of a literal node, or raise ``ValueError``."""
    if isinstance(node, Str):
        return node.value
    if isinstance(node, Num):
        return node.value
    if isinstance(node, Const):
        low = node.name.lower()
        if low == "true":
            return True
        if low == "false":
            return False
        if low == "null":
            return None
        raise ValueError(node.name)
    if isinstance(node, Arr):
        if all(k is None for k, _ in node.items):
            return [literal(v) for _, v in node.items]
        return {literal(k): literal(v) for k, v in node.items}
    raise ValueError(type(node).__name__)


def is_literal(node: Node | None) -> bool:
    try:
        literal(node)
        return True
    except ValueError:
        return False


def chain(node: Node) -> tuple[Node, list[MethodCall]]:
    """Split ``A::make()->b()->c()`` into the base and its method calls in order."""
    calls = []
    while isinstance(node, MethodCall):
        calls.append(node)
        node = node.obj  # type: ignore[assignment]
    calls.reverse()
    return node, calls


def short(name: str) -> str:
    return name.rsplit("\\", 1)[-1]
