"""DATA DIVISION: PICTURE strings, data items, byte lengths and offsets.

Sizes follow GnuCOBOL 3.2 with `-std=default` (`binary-size: 1-2-4-8`), as measured in spike S6,
and are validated per program against GnuCOBOL by an auto-generated probe (`layout_probe.py`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from verifier.cobol.lexer import HEX, NUM, PERIOD, PIC, STR, WORD, Token

Category = Literal["numeric", "alphanumeric", "alphabetic", "numeric-edited", "alphanumeric-edited"]

FIGURATIVES = {
    "ZERO": "ZERO", "ZEROS": "ZERO", "ZEROES": "ZERO",
    "SPACE": "SPACE", "SPACES": "SPACE",
    "HIGH-VALUE": "HIGH-VALUE", "HIGH-VALUES": "HIGH-VALUE",
    "LOW-VALUE": "LOW-VALUE", "LOW-VALUES": "LOW-VALUE",
    "QUOTE": "QUOTE", "QUOTES": "QUOTE",
    "NULL": "NULL", "NULLS": "NULL",
}

USAGE_WORDS = {
    "DISPLAY": "DISPLAY",
    "COMP": "COMP", "COMPUTATIONAL": "COMP", "COMP-4": "COMP", "COMPUTATIONAL-4": "COMP",
    "BINARY": "COMP",
    "COMP-3": "COMP-3", "COMPUTATIONAL-3": "COMP-3", "PACKED-DECIMAL": "COMP-3",
    "COMP-5": "COMP-5", "COMPUTATIONAL-5": "COMP-5",
    "COMP-1": "COMP-1", "COMPUTATIONAL-1": "COMP-1",
    "COMP-2": "COMP-2", "COMPUTATIONAL-2": "COMP-2",
    "COMP-6": "COMP-6", "COMPUTATIONAL-6": "COMP-6",
    "COMP-X": "COMP-X", "COMPUTATIONAL-X": "COMP-X",
    "INDEX": "INDEX", "POINTER": "POINTER", "NATIONAL": "NATIONAL",
    "BINARY-CHAR": "BINARY-CHAR", "BINARY-SHORT": "BINARY-SHORT", "BINARY-LONG": "BINARY-LONG",
    "BINARY-DOUBLE": "BINARY-DOUBLE", "FLOAT-SHORT": "COMP-1", "FLOAT-LONG": "COMP-2",
}
SUPPORTED_USAGES = {"DISPLAY", "COMP", "COMP-3", "COMP-5"}


class DataDivisionError(ValueError):
    pass


# ---------------------------------------------------------------------------------------------
# PICTURE
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class PicInfo:
    raw: str
    expanded: str
    category: Category
    digits: int = 0  # number of digit positions (9s) for numeric
    scale: int = 0  # digits right of the implied decimal point (negative for trailing P)
    signed: bool = False
    length: int = 0  # character positions in DISPLAY form (excluding S, V, P)

    @property
    def integer_digits(self) -> int:
        return self.digits - self.scale if self.scale >= 0 else self.digits

    def describe(self) -> str:
        if self.category == "numeric":
            return f"{'signed ' if self.signed else ''}decimal({self.digits},{self.scale})"
        return f"{self.category}({self.length})"


_REPEAT = re.compile(r"(CR|DB|.)\((\d+)\)")


def expand_pic(pic: str) -> str:
    s = pic.upper()

    def rep(m: re.Match[str]) -> str:
        return m.group(1) * int(m.group(2))

    prev = None
    while prev != s:
        prev, s = s, _REPEAT.sub(rep, s)
    return s


def parse_pic(pic: str) -> PicInfo:
    s = expand_pic(pic)
    if not s:
        raise DataDivisionError("empty PICTURE")
    signed = s.startswith("S")
    body = s[1:] if signed else s
    if "S" in body:
        raise DataDivisionError(f"PICTURE {pic}: S must be the first symbol")
    chars = set(body)
    if chars <= set("9VP") and "9" in chars:
        if body.count("V") > 1:
            raise DataDivisionError(f"PICTURE {pic}: more than one V")
        digits = body.count("9")
        if "P" in body:
            stripped = body.replace("V", "")
            if stripped.startswith("P"):  # PP99 == VPP99: all digits are fractional
                scale = stripped.count("P") + digits
            elif stripped.endswith("P"):  # 999PP: scaling positions to the left of the point
                scale = -stripped.count("P")
            else:
                raise DataDivisionError(f"PICTURE {pic}: P must be at an end")
        elif "V" in body:
            scale = body.split("V", 1)[1].count("9")
        else:
            scale = 0
        return PicInfo(pic, s, "numeric", digits=digits, scale=scale, signed=signed, length=digits)
    if signed:
        raise DataDivisionError(f"PICTURE {pic}: S in a non-numeric picture")
    if chars <= {"A", "B"} and "A" in chars:
        return PicInfo(pic, s, "alphabetic", length=len(body))
    if chars <= set("XA9"):
        return PicInfo(pic, s, "alphanumeric", length=len(body))
    if chars & set("XA") and chars <= set("XA9B0/"):
        return PicInfo(pic, s, "alphanumeric-edited", length=len(body))
    # numeric-edited: digits counted from 9 Z * and floating symbols beyond the first
    length = len(body.replace("V", "").replace("P", ""))
    digit_pos = sum(body.count(ch) for ch in "9Z*")
    for ch in "+-$":
        n = body.count(ch)
        if n > 1:
            digit_pos += n - 1
    after_point = body.split(".", 1)[1] if "." in body else (body.split("V", 1)[1] if "V" in body else "")
    scale = sum(after_point.count(ch) for ch in "9Z*")
    return PicInfo(pic, s, "numeric-edited", digits=digit_pos, scale=scale,
                   signed=bool(chars & {"+", "-"} or "CR" in body or "DB" in body), length=length)


def binary_bytes(digits: int) -> int:
    """`binary-size: 1-2-4-8` (spike S6)."""
    if digits <= 2:
        return 1
    if digits <= 4:
        return 2
    if digits <= 9:
        return 4
    if digits <= 18:
        return 8
    raise DataDivisionError(f"binary item with {digits} digits exceeds 18")


# ---------------------------------------------------------------------------------------------
# Data items
# ---------------------------------------------------------------------------------------------
@dataclass
class ValueLit:
    kind: Literal["num", "str", "fig", "all"]
    text: str  # numeric text, string value, or figurative name

    def __str__(self) -> str:
        if self.kind == "str":
            return '"' + self.text + '"'
        if self.kind == "all":
            return f'ALL "{self.text}"'
        return self.text


@dataclass
class DataItem:
    level: int
    name: str
    file: str
    line: int
    section: str
    pic: PicInfo | None = None
    usage: str = "DISPLAY"
    usage_explicit: bool = False
    sign: str | None = None  # LEADING / TRAILING
    sign_separate: bool = False
    occurs: int | None = None
    occurs_min: int | None = None
    depending_on: str | None = None
    redefines: str | None = None
    value: ValueLit | None = None
    values_88: list[tuple[ValueLit, ValueLit | None]] = field(default_factory=list)
    justified: bool = False
    blank_when_zero: bool = False
    sync: bool = False
    renames: tuple[str, str | None] | None = None
    external: bool = False
    children: list[DataItem] = field(default_factory=list)
    conditions: list[DataItem] = field(default_factory=list)  # attached 88-levels
    parent: DataItem | None = field(default=None, repr=False, compare=False)
    fd: str | None = None
    # layout (computed)
    offset: int = 0
    unit_size: int = 0  # size of one occurrence
    size: int = 0  # total size (unit_size * occurs)
    issues: list[str] = field(default_factory=list)

    @property
    def is_group(self) -> bool:
        return bool(self.children)

    @property
    def is_elementary(self) -> bool:
        return not self.children and self.level not in (66, 88)

    @property
    def is_filler(self) -> bool:
        return self.name.upper() == "FILLER"

    @property
    def is_numeric(self) -> bool:
        return self.pic is not None and self.pic.category == "numeric"

    def path(self) -> list[str]:
        out = []
        cur: DataItem | None = self
        while cur is not None:
            out.append(cur.name)
            cur = cur.parent
        return out

    def occurs_dims(self) -> int:
        n = 0
        cur: DataItem | None = self
        while cur is not None:
            if cur.occurs:
                n += 1
            cur = cur.parent
        return n

    def walk(self) -> list[DataItem]:
        out = [self]
        for c in self.children:
            out.extend(c.walk())
        return out

    def pic_text(self) -> str:
        parts = []
        if self.pic:
            parts.append(self.pic.raw)
        if self.usage != "DISPLAY":
            parts.append(self.usage)
        if self.sign:
            parts.append(f"SIGN {self.sign}{' SEPARATE' if self.sign_separate else ''}")
        return " ".join(parts) if parts else "group"

    def declared_type(self) -> dict[str, object]:
        """The `declared` structure used by the manifest and the data-mapping check."""
        if self.pic is None:
            return {"kind": "group", "length": self.unit_size}
        p = self.pic
        if p.category == "numeric":
            return {"kind": "decimal", "digits": p.digits, "scale": p.scale, "signed": p.signed,
                    "usage": self.usage}
        if p.category == "alphabetic":
            return {"kind": "alpha", "length": p.length}
        return {"kind": "alnum", "length": p.length, "category": p.category}


def storage_size(item: DataItem) -> int:
    u = item.usage
    if u == "COMP-1":
        return 4
    if u == "COMP-2":
        return 8
    if u in ("INDEX", "BINARY-LONG"):
        return 4
    if u in ("POINTER", "BINARY-DOUBLE"):
        return 8
    if u == "BINARY-CHAR":
        return 1
    if u == "BINARY-SHORT":
        return 2
    if item.pic is None:
        raise DataDivisionError(f"{item.name}: elementary item without PICTURE")
    p = item.pic
    if u == "DISPLAY":
        if p.category == "numeric":
            return p.digits + (1 if item.sign_separate else 0)
        return p.length
    if p.category != "numeric":
        raise DataDivisionError(f"{item.name}: USAGE {u} needs a numeric PICTURE")
    if u == "COMP-3":
        return p.digits // 2 + 1
    if u == "COMP-6":
        return (p.digits + 1) // 2
    if u in ("COMP", "COMP-5"):
        return binary_bytes(p.digits)
    if u == "NATIONAL":
        return 2 * p.length
    raise DataDivisionError(f"{item.name}: unsupported USAGE {u}")


def compute_layout(item: DataItem, offset: int = 0) -> None:
    item.offset = offset
    if item.level in (66, 88):
        item.unit_size = item.size = 0
        return
    if not item.children:
        try:
            item.unit_size = storage_size(item)
        except DataDivisionError as exc:
            item.issues.append(str(exc))
            item.unit_size = 0
    else:
        cur = offset
        by_name: dict[str, DataItem] = {}
        for child in item.children:
            if child.redefines:
                target = by_name.get(child.redefines.upper())
                base = target.offset if target is not None else cur
                compute_layout(child, base)
                if target is not None and child.size > target.size:
                    child.issues.append(f"REDEFINES {child.redefines} is larger than the redefined item")
                    cur = max(cur, base + child.size)
            else:
                compute_layout(child, cur)
                cur += child.size
            if not child.is_filler:
                by_name[child.name.upper()] = child
        item.unit_size = cur - offset
    item.size = item.unit_size * (item.occurs or 1)


# ---------------------------------------------------------------------------------------------
# Entry parser
# ---------------------------------------------------------------------------------------------
class EntryParser:
    """Parses data description entries from a token slice (one section)."""

    def __init__(self, toks: list[Token], section: str) -> None:
        self.toks = toks
        self.pos = 0
        self.section = section

    def _peek(self, k: int = 0) -> Token | None:
        i = self.pos + k
        return self.toks[i] if i < len(self.toks) else None

    def _next(self) -> Token:
        t = self.toks[self.pos]
        self.pos += 1
        return t

    def _accept_word(self, *words: str) -> bool:
        t = self._peek()
        if t is not None and t.is_word(*words):
            self.pos += 1
            return True
        return False

    def _literal(self) -> ValueLit:
        t = self._next()
        if t.kind == NUM:
            return ValueLit("num", t.text)
        if t.kind in (STR, HEX):
            return ValueLit("str", t.value)
        if t.kind == WORD and t.up == "ALL":
            lit = self._next()
            return ValueLit("all", lit.value if lit.kind in (STR, HEX) else lit.text)
        if t.kind == WORD and t.up in FIGURATIVES:
            return ValueLit("fig", FIGURATIVES[t.up])
        if t.kind == "OP" and t.text in "+-":
            nxt = self._next()
            return ValueLit("num", t.text + nxt.text)
        raise DataDivisionError(f"line {t.line}: expected a literal, got {t.text!r}")

    def parse_entry(self) -> DataItem:
        lvl_tok = self._next()
        if lvl_tok.kind != NUM:
            raise DataDivisionError(f"line {lvl_tok.line}: expected level number, got {lvl_tok.text!r}")
        level = int(lvl_tok.text)
        name = "FILLER"
        t = self._peek()
        if t is not None and t.kind == WORD and t.up not in _CLAUSE_WORDS:
            name = self._next().text.upper()
        item = DataItem(level=level, name=name, file=lvl_tok.file, line=lvl_tok.line, section=self.section)
        while True:
            t = self._peek()
            if t is None:
                raise DataDivisionError(f"line {lvl_tok.line}: entry {name} not terminated by a period")
            if t.kind == PERIOD:
                self.pos += 1
                break
            self._clause(item)
        return item

    def _clause(self, item: DataItem) -> None:
        t = self._next()
        w = t.up if t.kind == WORD else ""
        if w in ("PIC", "PICTURE"):
            self._accept_word("IS")
            p = self._next()
            if p.kind != PIC:
                raise DataDivisionError(f"line {t.line}: bad PICTURE")
            item.pic = parse_pic(p.text)
        elif w == "USAGE":
            self._accept_word("IS")
            u = self._next()
            if u.up not in USAGE_WORDS:
                raise DataDivisionError(f"line {u.line}: unknown USAGE {u.text}")
            item.usage, item.usage_explicit = USAGE_WORDS[u.up], True
            self._accept_word("SIGNED", "UNSIGNED")
        elif w in USAGE_WORDS:
            item.usage, item.usage_explicit = USAGE_WORDS[w], True
            self._accept_word("SIGNED", "UNSIGNED")
        elif w == "SIGN":
            self._accept_word("IS")
            s = self._next()
            item.sign = s.up
            if self._accept_word("SEPARATE"):
                item.sign_separate = True
                self._accept_word("CHARACTER")
        elif w in ("LEADING", "TRAILING"):
            item.sign = w
            if self._accept_word("SEPARATE"):
                item.sign_separate = True
                self._accept_word("CHARACTER")
        elif w == "OCCURS":
            n1 = self._next()
            if self._accept_word("TO"):
                n2 = self._next()
                item.occurs_min, item.occurs = int(n1.text), int(n2.text)
            else:
                item.occurs = int(n1.text)
            self._accept_word("TIMES")
            while True:
                if self._accept_word("DEPENDING"):
                    self._accept_word("ON")
                    item.depending_on = self._next().text.upper()
                elif self._accept_word("ASCENDING", "DESCENDING"):
                    self._accept_word("KEY")
                    self._accept_word("IS")
                    while self._peek() is not None and self._peek().kind == WORD and self._peek().up not in _CLAUSE_WORDS | {"ASCENDING", "DESCENDING", "INDEXED"}:  # type: ignore[union-attr]
                        self.pos += 1
                elif self._accept_word("INDEXED"):
                    self._accept_word("BY")
                    while self._peek() is not None and self._peek().kind == WORD and self._peek().up not in _CLAUSE_WORDS:  # type: ignore[union-attr]
                        self.pos += 1
                else:
                    break
        elif w == "REDEFINES":
            item.redefines = self._next().text.upper()
        elif w in ("VALUE", "VALUES"):
            self._accept_word("IS", "ARE")
            if item.level == 88:
                while True:
                    lo = self._literal()
                    hi = None
                    if self._accept_word("THRU", "THROUGH"):
                        hi = self._literal()
                    item.values_88.append((lo, hi))
                    nxt = self._peek()
                    if nxt is None or nxt.kind == PERIOD or (nxt.kind == WORD and nxt.up in _CLAUSE_WORDS and nxt.up not in FIGURATIVES and nxt.up != "ALL"):
                        break
            else:
                item.value = self._literal()
        elif w in ("JUSTIFIED", "JUST"):
            item.justified = True
            self._accept_word("RIGHT")
        elif w == "BLANK":
            self._accept_word("WHEN")
            self._next()
            item.blank_when_zero = True
        elif w in ("SYNCHRONIZED", "SYNC"):
            item.sync = True
            self._accept_word("LEFT", "RIGHT")
        elif w == "RENAMES":
            a = self._next().text.upper()
            b = None
            if self._accept_word("THRU", "THROUGH"):
                b = self._next().text.upper()
            item.renames = (a, b)
        elif w in ("EXTERNAL", "GLOBAL", "IS"):
            if w == "EXTERNAL":
                item.external = True
        elif w in ("BASED", "ANY", "LENGTH", "GROUP-USAGE", "DYNAMIC", "VOLATILE", "CONSTANT", "AS", "TYPEDEF"):
            item.issues.append(f"unsupported clause {w}")
        else:
            raise DataDivisionError(f"line {t.line}: unexpected {t.text!r} in data entry {item.name}")


_CLAUSE_WORDS = {
    "PIC", "PICTURE", "USAGE", "SIGN", "LEADING", "TRAILING", "OCCURS", "REDEFINES", "VALUE",
    "VALUES", "JUSTIFIED", "JUST", "BLANK", "SYNCHRONIZED", "SYNC", "RENAMES", "EXTERNAL",
    "GLOBAL", "IS", "BASED", "ANY", "GROUP-USAGE", "DYNAMIC", "VOLATILE", "CONSTANT", "TYPEDEF",
    *USAGE_WORDS.keys(),
}


def build_tree(entries: list[DataItem]) -> list[DataItem]:
    """Nest entries by level number; returns the 01/77 roots (66 and 88 attached)."""
    roots: list[DataItem] = []
    stack: list[DataItem] = []
    last: DataItem | None = None
    for e in entries:
        if e.level == 88:
            if last is None:
                raise DataDivisionError(f"line {e.line}: 88-level without a preceding item")
            e.parent = last
            last.conditions.append(e)
            continue
        if e.level == 66:
            if not roots:
                raise DataDivisionError(f"line {e.line}: 66-level without a record")
            e.parent = roots[-1]
            roots[-1].conditions.append(e)
            continue
        if e.level in (1, 77):
            roots.append(e)
            stack = [e]
            last = e
            continue
        while stack and stack[-1].level >= e.level:
            stack.pop()
        if not stack:
            raise DataDivisionError(f"line {e.line}: level {e.level} item {e.name} outside any record")
        parent = stack[-1]
        e.parent = parent
        parent.children.append(e)
        stack.append(e)
        last = e
    for r in roots:
        _inherit(r)
        compute_layout(r, 0)
    return roots


def _inherit(item: DataItem) -> None:
    for c in item.children:
        if not c.usage_explicit and item.usage_explicit:
            c.usage, c.usage_explicit = item.usage, True
        if c.sign is None and item.sign is not None:
            c.sign, c.sign_separate = item.sign, item.sign_separate
        _inherit(c)
    if item.children:
        # a group's own USAGE only describes its subordinates; the group itself is alphanumeric
        pass


def parse_entries(toks: list[Token], section: str) -> list[DataItem]:
    p = EntryParser(toks, section)
    out: list[DataItem] = []
    while p.pos < len(toks):
        out.append(p.parse_entry())
    return out
