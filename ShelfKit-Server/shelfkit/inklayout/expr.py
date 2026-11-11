"""The expression language inside {{ ... }}, if= and each=.

Deliberately tiny and side-effect free - it reads values, it cannot call anything:

    data.count                      a path into the context (dicts and lists only)
    d.items[0].name                 list index
    'text'  "text"  12  1.5  true false none
    a == b   a != b   a < b   a <= b   a > b   a >= b
    not x    x and y    x or y      ( ... )
    cond ? 'yes' : 'no'
    value | upper | default:"-"     filters, see FILTERS

A path that does not exist evaluates to MISSING (rendered as "", false in a
condition) and is recorded, so the renderer can report it instead of failing.
"""

from __future__ import annotations

import re
from datetime import datetime


class _Missing:
    def __bool__(self) -> bool:
        return False

    def __str__(self) -> str:
        return ""

    def __repr__(self) -> str:
        return "MISSING"


MISSING = _Missing()


class ExprError(ValueError):
    pass


_TOKEN = re.compile(r"""
    \s*(?:
      (?P<num>-?\d+(?:\.\d+)?)
    | (?P<str>'[^']*'|"[^"]*")
    | (?P<op>==|!=|<=|>=|<|>|\?|:|\||\.|\[|\]|\(|\))
    | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
    )""", re.X)


def _tokens(src: str) -> list[tuple[str, str]]:
    out, pos = [], 0
    src = src.strip()
    while pos < len(src):
        m = _TOKEN.match(src, pos)
        if not m or m.end() == pos:
            raise ExprError(f"cannot read {src[pos:pos + 12]!r} in {src!r}")
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
        pos = m.end()
        while pos < len(src) and src[pos].isspace():
            pos += 1
    return out


def _as_time(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _f_time(value, fmt="%H:%M"):
    t = _as_time(value)
    return t.strftime(fmt) if t else MISSING


def _f_date(value, fmt="%Y-%m-%d"):
    return _f_time(value, fmt)


def _f_round(value, n=0):
    try:
        n = int(n)
        r = round(float(value), n)
        return int(r) if n == 0 else r
    except (TypeError, ValueError):
        return MISSING


def _f_count(value):
    try:
        return len(value)
    except TypeError:
        return 0


def _f_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return MISSING


FILTERS = {
    "upper": lambda v: str(v).upper(),
    "lower": lambda v: str(v).lower(),
    "title": lambda v: str(v).title(),
    "time": _f_time,                       # time:"%H:%M"
    "date": _f_date,                       # date:"%a %d %b"
    "round": _f_round,                     # round:1
    "default": lambda v, d="": v if v not in (MISSING, None, "") else d,
    "count": _f_count,
    "int": _f_int,
}


class _Parser:
    def __init__(self, src: str, ctx: dict, missing: list[str]) -> None:
        self.src = src
        self.toks = _tokens(src)
        self.i = 0
        self.ctx = ctx
        self.missing = missing

    def peek(self, value: str | None = None, kind: str | None = None) -> bool:
        if self.i >= len(self.toks):
            return False
        k, v = self.toks[self.i]
        return (value is None or v == value) and (kind is None or k == kind)

    def take(self, value: str | None = None, kind: str | None = None) -> str:
        if not self.peek(value, kind):
            got = self.toks[self.i][1] if self.i < len(self.toks) else "the end"
            raise ExprError(f"expected {value or kind} but found {got!r} in {self.src!r}")
        self.i += 1
        return self.toks[self.i - 1][1]

    def parse(self):
        value = self.ternary()
        if self.i != len(self.toks):
            raise ExprError(f"unexpected {self.toks[self.i][1]!r} in {self.src!r}")
        return value

    def ternary(self):
        cond = self.or_()
        if self.peek("?", "op"):
            self.take("?")
            yes = self.ternary()
            self.take(":")
            no = self.ternary()
            return yes if cond else no
        return cond

    def or_(self):
        left = self.and_()
        while self.peek("or", "name"):
            self.take()
            right = self.and_()
            left = left or right
        return left

    def and_(self):
        left = self.not_()
        while self.peek("and", "name"):
            self.take()
            right = self.not_()
            left = left and right
        return left

    def not_(self):
        if self.peek("not", "name"):
            self.take()
            return not self.not_()
        return self.compare()

    def compare(self):
        left = self.pipe()
        for op in ("==", "!=", "<=", ">=", "<", ">"):
            if self.peek(op, "op"):
                self.take()
                right = self.pipe()
                if op == "==":
                    return left == right
                if op == "!=":
                    return left != right
                try:
                    return {"<": left < right, "<=": left <= right,
                            ">": left > right, ">=": left >= right}[op]
                except TypeError:
                    return False
        return left

    def pipe(self):
        value = self.primary()
        while self.peek("|", "op"):
            self.take()
            name = self.take(kind="name")
            fn = FILTERS.get(name)
            if fn is None:
                raise ExprError(f"unknown filter {name!r}; filters: {', '.join(FILTERS)}")
            args = []
            if self.peek(":", "op"):
                self.take()
                args.append(self.literal())
            if value is MISSING and name != "default":
                continue
            value = fn(value, *args)
        return value

    def literal(self):
        if self.peek(kind="str"):
            return self.take()[1:-1]
        if self.peek(kind="num"):
            text = self.take()
            return float(text) if "." in text else int(text)
        raise ExprError(f"a filter argument must be a quoted text or a number in {self.src!r}")

    def primary(self):
        if self.peek("(", "op"):
            self.take()
            value = self.ternary()
            self.take(")")
            return value
        if self.peek(kind="str") or self.peek(kind="num"):
            return self.literal()
        name = self.take(kind="name")
        if name in ("true", "false", "none"):
            return {"true": True, "false": False, "none": None}[name]
        path = name
        value = self.ctx.get(name, MISSING)
        while self.peek(".", "op") or self.peek("[", "op"):
            if self.take() == ".":
                key = self.take(kind="name")
                path += "." + key
                value = value.get(key, MISSING) if isinstance(value, dict) else MISSING
            else:
                index = int(self.take(kind="num"))
                self.take("]")
                path += f"[{index}]"
                value = (value[index] if isinstance(value, (list, tuple))
                         and -len(value) <= index < len(value) else MISSING)
        if value is MISSING:
            self.missing.append(path)
        return value


def evaluate(src: str, ctx: dict, missing: list[str] | None = None):
    """The value of one expression (no braces)."""
    return _Parser(src, ctx, missing if missing is not None else []).parse()


# one {{ ... }} that does not itself contain a closing }} (so "{{a}}: {{b}}" is two)
_BRACES = re.compile(r"\{\{((?:(?!\}\}).)*)\}\}", re.S)


def interpolate(text: str, ctx: dict, missing: list[str] | None = None):
    """Fill every {{ expr }} in text. A value that is exactly one {{ expr }} keeps its
    type (a list for each=, a number for value=); otherwise the result is text."""
    missing = missing if missing is not None else []
    whole = _BRACES.fullmatch(text.strip())
    if whole:
        return evaluate(whole.group(1), ctx, missing)
    return _BRACES.sub(lambda m: _text(evaluate(m.group(1), ctx, missing)), text)


def _text(value) -> str:
    if value is MISSING or value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def as_text(value) -> str:
    return _text(value)
