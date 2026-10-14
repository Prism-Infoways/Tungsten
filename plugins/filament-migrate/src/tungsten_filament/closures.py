"""Turn small Filament closures into Python lambdas.

Filament code is full of short closures such as::

    ->visible(fn (Get $get) => $get('type') === 'company')
    ->color(fn (string $state): string => $state === 'paid' ? 'success' : 'gray')
    ->default(fn () => now())

Tungsten calls closures with the same argument names (``get``, ``set``, ``state``,
``record``, ``operation``), so the simple ones translate one to one. Anything
bigger (method calls on models, ``match``, loops, Livewire) returns ``None`` and is
left for a human.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from .php import Closure, Token, tokenize

#: Filament's injected argument -> the name Tungsten passes
PARAMS = {"get": "get", "set": "set", "state": "state", "record": "record", "operation": "operation",
          "context": "operation", "model": "model", "user": "user"}


class _Fail(Exception):
    pass


_BINARY = {
    "or": 1, "||": 2, "and": 3, "&&": 3, "??": 5,
    "===": 6, "==": 6, "!==": 6, "!=": 6, "<>": 6,
    "<": 7, ">": 7, "<=": 7, ">=": 7,
    ".": 8, "+": 8, "-": 8,
    "*": 9, "/": 9, "%": 9,
}
_PY_OP = {"||": "or", "&&": "and", "or": "or", "and": "and", "===": "==", "!==": "!=", "<>": "!="}


class _Translator:
    def __init__(self, toks: list[Token], names: dict[str, str], enum_value: Callable[[str, str], Any] | None,
                 uses: set[str]) -> None:
        self.toks = toks
        self.i = 0
        self.names = names
        self.enum_value = enum_value
        self.uses = uses  # helper imports the lambda needs ("datetime")

    @property
    def tok(self) -> Token:
        return self.toks[self.i]

    def next(self) -> Token:
        t = self.toks[self.i]
        self.i += 1
        return t

    def at(self, value: str) -> bool:
        return self.tok.kind in ("op", "name") and str(self.tok.value).lower() == value

    def expect(self, value: str) -> None:
        if not self.at(value):
            raise _Fail(value)
        self.next()

    def expr(self, min_prec: int = 0) -> str:
        left = self.unary()
        while True:
            t = self.tok
            op = str(t.value).lower() if t.kind in ("op", "name") else None
            if op == "?":
                if min_prec > 0:
                    return left
                self.next()
                if self.at(":"):  # a ?: b
                    self.next()
                    right = self.expr(1)
                    left = f"({left} or {right})"
                    continue
                yes = self.expr(1)
                self.expect(":")
                no = self.expr(0)
                left = f"({yes} if {left} else {no})"
                continue
            if op not in _BINARY:
                return left
            prec = _BINARY[op]
            if prec < min_prec:
                return left
            self.next()
            right = self.expr(prec if op == "??" else prec + 1)
            if op == "??":
                left = f"({left} if {left} is not None else {right})"
            elif op == ".":
                left = f"(str({left}) + str({right}))"
            else:
                left = f"({left} {_PY_OP.get(op, op)} {right})"

    def unary(self) -> str:
        if self.at("!"):
            self.next()
            return f"(not {self.unary()})"
        if self.at("-"):
            self.next()
            return f"(-{self.unary()})"
        if self.at("("):
            self.next()
            inner = self.expr()
            self.expect(")")
            return self.postfix(inner, None)
        return self.primary()

    def primary(self) -> str:
        t = self.next()
        if t.kind in ("str", "num"):
            return repr(t.value)
        if t.kind == "var":
            name = self.names.get(t.value)
            if name is None:
                raise _Fail(f"${t.value}")
            if self.at("("):  # $get('field') / $set('field', value)
                if name not in ("get", "set"):
                    raise _Fail("call")
                return self.postfix(f"{name}({self.args()})", None)
            return self.postfix(name, t.value)
        if t.kind == "op" and t.value == "[":
            items = []
            while not self.at("]"):
                key = self.expr()
                if self.at("=>"):
                    raise _Fail("dict")
                items.append(key)
                if self.at(","):
                    self.next()
            self.next()
            return "[" + ", ".join(items) + "]"
        if t.kind == "name":
            low = t.value.lower()
            if low in ("true", "false", "null"):
                return {"true": "True", "false": "False", "null": "None"}[low]
            if self.at("::"):
                self.next()
                case = self.next()
                if case.kind == "name" and self.at("(") and t.value.rsplit("\\", 1)[-1] == "Str":
                    return self.str_helper(case.value.lower())
                if case.kind != "name" or self.at("("):
                    raise _Fail("static call")
                if self.enum_value is None:
                    raise _Fail("enum")
                value = self.enum_value(t.value, case.value)
                if value is None:
                    raise _Fail("constant")
                out = repr(value)
                if self.at("->") and self.toks[self.i + 1].value == "value":
                    self.i += 2
                return out
            if low == "match" and self.at("("):
                return self.match()
            if self.at("("):
                return self.function(low)
        raise _Fail(str(t.value))

    def match(self) -> str:
        """``match ($state) { 'a', 'b' => 'x', default => 'y' }`` -> ``{'a': 'x', 'b': 'x'}.get(state, 'y')``."""
        self.expect("(")
        subject = self.expr()
        self.expect(")")
        self.expect("{")
        arms: list[tuple[str, str]] = []
        default = "None"
        while not self.at("}"):
            if self.at("default"):
                self.next()
                self.expect("=>")
                default = self.expr()
            else:
                keys = [self.expr()]
                while self.at(","):
                    self.next()
                    keys.append(self.expr())
                self.expect("=>")
                value = self.expr()
                arms.extend((k, value) for k in keys)
            if self.at(","):
                self.next()
        self.next()
        if any(not re.fullmatch(r"'[^']*'|\"[^\"]*\"|-?\d+(\.\d+)?|True|False|None", k) for k, _ in arms):
            raise _Fail("match on expressions")
        mapping = "{" + ", ".join(f"{k}: {v}" for k, v in arms) + "}"
        return f"{mapping}.get({subject}, {default})"

    def args(self) -> str:
        self.expect("(")
        out = []
        while not self.at(")"):
            out.append(self.expr())
            if self.at(","):
                self.next()
            elif not self.at(")"):
                raise _Fail("args")
        self.next()
        return ", ".join(out)

    def arg_list(self) -> list[str]:
        self.expect("(")
        out = []
        while not self.at(")"):
            out.append(self.expr())
            if self.at(","):
                self.next()
            elif not self.at(")"):
                raise _Fail("args")
        self.next()
        return out

    def str_helper(self, name: str) -> str:
        """Laravel's ``Str::`` helpers."""
        args = self.arg_list()
        if name == "slug" and len(args) == 1:
            self.uses.add("slug")
            return f"slug({args[0]})"
        if name in ("upper", "lower", "title") and len(args) == 1:
            return f"str({args[0]} or '').{name}()"
        if name == "ucfirst" and len(args) == 1:
            return f"str({args[0]} or '').capitalize()"
        if name == "limit" and len(args) == 2:
            return f"str({args[0]} or '')[:{args[1]}]"
        raise _Fail(f"Str::{name}")

    def function(self, name: str) -> str:
        args = self.arg_list()
        if name in ("random_int", "rand", "mt_rand") and len(args) == 2:
            self.uses.add("random")
            return f"random.randint({args[0]}, {args[1]})"
        if name in ("now",) and not args:
            self.uses.add("datetime")
            return "dt.datetime.now()"
        if name == "today" and not args:
            self.uses.add("datetime")
            return "dt.date.today()"
        if name == "in_array" and len(args) >= 2:
            return f"({args[0]} in {args[1]})"
        if name == "filled" and len(args) == 1:
            return f"bool({args[0]})"
        if name == "blank" and len(args) == 1:
            return f"(not {args[0]})"
        if name in ("empty",) and len(args) == 1:
            return f"(not {args[0]})"
        if name in ("isset", "is_null") and len(args) == 1:
            return f"({args[0]} {'is not' if name == 'isset' else 'is'} None)"
        if name in ("strtoupper", "mb_strtoupper") and len(args) == 1:
            return f"str({args[0]}).upper()"
        if name in ("strtolower", "mb_strtolower") and len(args) == 1:
            return f"str({args[0]}).lower()"
        if name in ("ucfirst",) and len(args) == 1:
            return f"str({args[0]}).capitalize()"
        if name in ("trim",) and len(args) == 1:
            return f"str({args[0]}).strip()"
        if name in ("count",) and len(args) == 1:
            return f"len({args[0]} or [])"
        if name in ("strlen", "mb_strlen") and len(args) == 1:
            return f"len(str({args[0]}))"
        if name in ("__", "trans") and len(args) == 1:
            return args[0]
        if name == "number_format" and 1 <= len(args) <= 2:
            places = args[1] if len(args) == 2 else "0"
            if not places.isdigit():
                raise _Fail("number_format")
            return f"f\"{{float({args[0]} or 0):,.{places}f}}\""
        if name in ("intval", "floatval", "strval", "boolval"):
            py = {"intval": "int", "floatval": "float", "strval": "str", "boolval": "bool"}[name]
            return f"{py}({args[0]})"
        raise _Fail(name)

    def postfix(self, out: str, var: str | None) -> str:
        while self.tok.kind == "op" and self.tok.value in ("->", "?->"):
            nullsafe = self.tok.value == "?->"
            if var not in ("record", "state", "get") and not out.startswith("get("):
                raise _Fail("property")
            self.next()
            prop = self.next()
            if prop.kind != "name" or self.at("("):
                raise _Fail("method")
            out = f"getattr({out}, {prop.value!r}, None)" if nullsafe else f"{out}.{prop.value}"
        return out


def _params(text: str) -> dict[str, str]:
    names: dict[str, str] = {}
    for var in re.findall(r"\$(\w+)", text):
        if var not in PARAMS:
            raise _Fail(f"${var}")
        names[var] = PARAMS[var]
    return names


def translate(node: Closure, enum_value: Callable[[str, str], Any] | None = None) -> tuple[str, set[str]] | None:
    """A Python lambda for a short PHP closure, with the imports it needs, or ``None``."""
    src = node.src.strip()
    src = re.sub(r"^static\s+", "", src)
    try:
        m = re.match(r"(fn|function)\s*\(", src)
        if not m:
            return None
        # parameters run to the matching ")"
        depth, j = 0, m.end() - 1
        while j < len(src):
            if src[j] == "(":
                depth += 1
            elif src[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        names = _params(src[m.end():j])
        rest = src[j + 1:]
        if m.group(1) == "fn":
            arrow = rest.find("=>")
            if arrow < 0:
                return None
            body = rest[arrow + 2:]
        else:
            if re.match(r"\s*use\b", rest):
                return None
            mm = re.search(r"\{\s*return\b(.*);\s*\}\s*$", rest, re.DOTALL)
            if not mm or ";" in mm.group(1):
                return None
            body = mm.group(1)
        toks = tokenize("<?php " + body)
        uses: set[str] = set()
        tr = _Translator(toks, names, enum_value, uses)
        out = tr.expr()
        if tr.tok.kind != "eof":
            return None
        params = ", ".join(dict.fromkeys(names.values()))
        return f"lambda {params}: {out}" if params else f"lambda: {out}", uses
    except (_Fail, IndexError, KeyError):
        return None
