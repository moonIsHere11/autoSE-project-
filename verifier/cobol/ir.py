"""Typed IR for the COBOL subset the semantic model supports (spec section 6, T2b.1).

`lower_program(prog)` turns the parser's generic `Statement`s into typed IR nodes. The lowering
mirrors how GnuCOBOL 3.2 (`cobc -std=default`) builds its own trees, because the interpreter
(`interp.py`) reproduces the code cobc generates:

* COMPUTE expressions use cobc's LALR arithmetic grammar (`**` is right-associative, unary minus
  binds to an atom and becomes `0 - x`, constant folding of literal pairs);
* conditions use a port of cobc's shift/reduce expression builder (`build_expr_*` in typeck.c),
  which also defines abbreviated combined relations (`A = 1 OR 2`, `A > 1 AND NOT < 5`) and
  `NOT` handling;
* ADD/SUBTRACT/MULTIPLY/DIVIDE keep the distinction cobc makes between a single operand (one
  `cob_add`/`cob_sub`/`cob_mul`/`cob_div` call per target) and an operand list or GIVING
  (decimal expression assigned to every target).

Every construct that is not modelled exactly becomes `Unsupported(construct, file, line)`; nothing
is guessed. Constructs the interpreter executes exactly but that are outside the T2b subset (GO TO,
PERFORM THRU, I/O statements) are interpretable but make the paragraph T2-ineligible.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal

from verifier.cobol.datadiv import FIGURATIVES, DataItem, PicInfo, parse_pic
from verifier.cobol.lexer import HEX, NUM, OP, STR, WORD, Token
from verifier.cobol.syntax import Branch, Paragraph, Program, Statement

# ---------------------------------------------------------------------------------------------
# operands and expressions
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Loc:
    file: str
    line: int

    def __str__(self) -> str:
        return f"{self.file}:{self.line}"


@dataclass(eq=False)
class Ref:
    """A data reference: item + subscripts (outermost OCCURS first) + optional reference modification."""

    item: DataItem
    subs: list[Expr] = field(default_factory=list)
    refmod: tuple[Expr, Expr | None] | None = None
    text: str = ""

    def __str__(self) -> str:
        return self.text or self.item.name


@dataclass(eq=False)
class Lit:
    """Numeric literal as cobc stores it: unsigned digit string, scale, sign."""

    text: str
    digits: str  # without sign and decimal point, leading zeros kept as written
    scale: int
    negative: bool
    signed: bool  # written with an explicit sign

    @property
    def value(self) -> int:
        """Unscaled integer value."""
        v = int(self.digits) if self.digits else 0
        return -v if self.negative else v

    def __str__(self) -> str:
        return self.text


@dataclass(eq=False)
class StrLit:
    value: bytes

    def __str__(self) -> str:
        return '"' + self.value.decode("latin-1") + '"'


FigName = Literal["ZERO", "SPACE", "HIGH-VALUE", "LOW-VALUE", "QUOTE"]


@dataclass(eq=False)
class Fig:
    """Figurative constant (ZERO, SPACE, ...) or `ALL literal` (name 'ALL', value = the literal)."""

    name: str
    value: bytes = b""

    def __str__(self) -> str:
        return f"ALL {self.value!r}" if self.name == "ALL" else self.name


@dataclass(eq=False)
class Bin:
    op: str  # + - * / ^
    left: Expr
    right: Expr

    def __str__(self) -> str:
        return f"({self.left} {'**' if self.op == '^' else self.op} {self.right})"


Expr = Ref | Lit | StrLit | Fig | Bin

# ---------------------------------------------------------------------------------------------
# conditions
# ---------------------------------------------------------------------------------------------
RelOp = Literal["=", "~", "<", ">", "[", "]"]  # cobc codes: ~ <>, [ <=, ] >=
REL_TEXT = {"=": "=", "~": "<>", "<": "<", ">": ">", "[": "<=", "]": ">="}


@dataclass(eq=False)
class Rel:
    op: str
    left: Expr
    right: Expr

    def __str__(self) -> str:
        return f"{self.left} {REL_TEXT[self.op]} {self.right}"


@dataclass(eq=False)
class ClassTest:
    kind: str  # NUMERIC | ALPHABETIC | ALPHABETIC-LOWER | ALPHABETIC-UPPER
    operand: Expr

    def __str__(self) -> str:
        return f"{self.operand} IS {self.kind}"


@dataclass(eq=False)
class CondName:
    """88-level condition-name; `parent` carries the subscripts of the conditional variable."""

    cond: DataItem
    parent: Ref
    test: Cond | None = None  # the relation cobc builds for it (build_cond_88), constant-folded

    def __str__(self) -> str:
        return self.cond.name


@dataclass(eq=False)
class Not:
    cond: Cond

    def __str__(self) -> str:
        return f"NOT ({self.cond})"


@dataclass(eq=False)
class And:
    left: Cond
    right: Cond

    def __str__(self) -> str:
        return f"({self.left} AND {self.right})"


@dataclass(eq=False)
class Or:
    left: Cond
    right: Cond

    def __str__(self) -> str:
        return f"({self.left} OR {self.right})"


@dataclass(eq=False)
class BoolConst:
    value: bool

    def __str__(self) -> str:
        return "TRUE" if self.value else "FALSE"


Cond = Rel | ClassTest | CondName | Not | And | Or | BoolConst

# ---------------------------------------------------------------------------------------------
# statements
# ---------------------------------------------------------------------------------------------


@dataclass(eq=False)
class Stmt:
    loc: Loc
    verb: str

    def children(self) -> list[list[Stmt]]:
        return []

    def walk(self) -> Iterator[Stmt]:
        yield self
        for block in self.children():
            for s in block:
                yield from s.walk()


@dataclass(eq=False)
class Target:
    ref: Ref
    rounded: bool = False


@dataclass(eq=False)
class Move(Stmt):
    src: Expr
    dsts: list[Ref]


@dataclass(eq=False)
class SizeErrorMixin:
    size_error: list[Stmt] | None = None
    not_size_error: list[Stmt] | None = None


@dataclass(eq=False)
class ArithOp(Stmt):
    """ADD x TO t... / SUBTRACT x FROM t... / MULTIPLY x BY t... / DIVIDE x INTO t...

    cobc emits one `cob_add/cob_sub/cob_mul/cob_div(target, x, opt)` per target (or an optimised
    integer add for `ADD/SUBTRACT literal-or-small-integer`)."""

    op: str  # + - * /
    src: Expr
    targets: list[Target]
    size_error: list[Stmt] | None = None
    not_size_error: list[Stmt] | None = None

    @property
    def handler(self) -> bool:
        return self.size_error is not None or self.not_size_error is not None

    def children(self) -> list[list[Stmt]]:
        return [b for b in (self.size_error, self.not_size_error) if b is not None]


@dataclass(eq=False)
class ArithAssign(Stmt):
    """Decimal assignment (cobc build_decimal_assign): COMPUTE, GIVING forms, operand lists.

    op None: target = expr. op '+'/'-'/'*'/'/': target = target op expr (expr evaluated once)."""

    op: str | None
    expr: Expr
    targets: list[Target]
    size_error: list[Stmt] | None = None
    not_size_error: list[Stmt] | None = None

    @property
    def handler(self) -> bool:
        return self.size_error is not None or self.not_size_error is not None

    def children(self) -> list[list[Stmt]]:
        return [b for b in (self.size_error, self.not_size_error) if b is not None]


@dataclass(eq=False)
class DivRem(Stmt):
    """DIVIDE ... GIVING q REMAINDER r (cob_div_quotient + cob_div_remainder)."""

    dividend: Expr
    divisor: Expr
    quotient: Target
    remainder: Ref
    size_error: list[Stmt] | None = None
    not_size_error: list[Stmt] | None = None

    @property
    def handler(self) -> bool:
        return self.size_error is not None or self.not_size_error is not None

    def children(self) -> list[list[Stmt]]:
        return [b for b in (self.size_error, self.not_size_error) if b is not None]


@dataclass(eq=False)
class If(Stmt):
    cond: Cond
    then: list[Stmt]
    els: list[Stmt] | None = None

    def children(self) -> list[list[Stmt]]:
        return [self.then] + ([self.els] if self.els is not None else [])


@dataclass(eq=False)
class When:
    cond: Cond  # the combined test cobc builds for this WHEN group
    body: list[Stmt]
    line: int


@dataclass(eq=False)
class Evaluate(Stmt):
    whens: list[When]
    other: list[Stmt] | None = None

    def children(self) -> list[list[Stmt]]:
        return [w.body for w in self.whens] + ([self.other] if self.other is not None else [])


@dataclass(eq=False)
class Varying:
    var: Ref
    start: Expr
    by: Expr
    until: Cond


@dataclass(eq=False)
class Perform(Stmt):
    """Out-of-line (proc != None) or inline (body != None) PERFORM.

    mode: once | times | until | varying. For `until`/`varying`, `test_after` selects WITH TEST
    AFTER. `varying` holds the VARYING clause and its AFTER clauses, outermost first."""

    proc: tuple[str, str] | None  # (first, last) procedure names; last == first unless THRU
    body: list[Stmt] | None
    mode: str = "once"
    times: Expr | None = None
    until: Cond | None = None
    test_after: bool = False
    varying: list[Varying] = field(default_factory=list)

    @property
    def thru(self) -> bool:
        return self.proc is not None and self.proc[0] != self.proc[1]

    def children(self) -> list[list[Stmt]]:
        return [self.body] if self.body is not None else []


@dataclass(eq=False)
class SetCond(Stmt):
    """SET condition-name ... TO TRUE (value moved: the first VALUE of the 88)."""

    conds: list[CondName]


@dataclass(eq=False)
class Initialize(Stmt):
    targets: list[Ref]


@dataclass(eq=False)
class Continue(Stmt):
    pass


@dataclass(eq=False)
class ExitStmt(Stmt):
    """EXIT (no-op), EXIT PARAGRAPH / EXIT SECTION / EXIT PERFORM [CYCLE] / EXIT PROGRAM."""

    kind: str  # plain | paragraph | section | perform | perform-cycle | program


@dataclass(eq=False)
class StopRun(Stmt):
    pass


@dataclass(eq=False)
class GoBack(Stmt):
    pass


@dataclass(eq=False)
class GoTo(Stmt):
    target: str


@dataclass(eq=False)
class Accept(Stmt):
    target: Ref
    source: str  # stdin
    exception: list[Stmt] | None = None
    not_exception: list[Stmt] | None = None

    def children(self) -> list[list[Stmt]]:
        return [b for b in (self.exception, self.not_exception) if b is not None]


@dataclass(eq=False)
class Display(Stmt):
    operands: list[Expr]
    upon: str  # SYSOUT | SYSERR
    advancing: bool = True


@dataclass(eq=False)
class Open(Stmt):
    entries: list[tuple[str, str]]  # (mode, file name)


@dataclass(eq=False)
class Close(Stmt):
    files: list[str]


@dataclass(eq=False)
class Read(Stmt):
    file: str
    into: Ref | None = None
    at_end: list[Stmt] | None = None
    not_at_end: list[Stmt] | None = None

    def children(self) -> list[list[Stmt]]:
        return [b for b in (self.at_end, self.not_at_end) if b is not None]


@dataclass(eq=False)
class Write(Stmt):
    record: Ref
    file: str
    src: Expr | None = None


@dataclass(eq=False)
class Unsupported(Stmt):
    construct: str

    @property
    def reason(self) -> str:
        return f"unsupported construct {self.construct} at {self.loc.file}:{self.loc.line}"


IO_VERBS = (Accept, Display, Open, Close, Read, Write)

# ---------------------------------------------------------------------------------------------
# program
# ---------------------------------------------------------------------------------------------


@dataclass(eq=False)
class IrParagraph:
    name: str
    section: str | None
    loc: Loc
    end_line: int
    body: list[Stmt]
    t2_eligibility: str | None = None  # None = eligible, else the exact reason

    def walk(self) -> Iterator[Stmt]:
        for s in self.body:
            yield from s.walk()

    @property
    def t2_eligible(self) -> bool:
        return self.t2_eligibility is None


@dataclass(eq=False)
class IrProgram:
    program: Program
    paragraphs: list[IrParagraph]
    sections: list[str]
    return_code: DataItem
    issues: list[str] = field(default_factory=list)  # program-level reasons it cannot be interpreted

    def paragraph(self, name: str) -> IrParagraph | None:
        up = name.upper()
        for p in self.paragraphs:
            if p.name == up:
                return p
        return None

    def walk(self) -> Iterator[Stmt]:
        for p in self.paragraphs:
            yield from p.walk()

    def unsupported(self) -> list[Unsupported]:
        return [s for s in self.walk() if isinstance(s, Unsupported)]

    @property
    def interpretable(self) -> bool:
        return not self.issues and not self.unsupported()

    def interpretability(self) -> str | None:
        """None when the whole program can be interpreted, else the first reason."""
        if self.issues:
            return self.issues[0]
        uns = self.unsupported()
        if uns:
            return uns[0].reason
        return None

    def section_paragraphs(self, section: str) -> list[IrParagraph]:
        return [p for p in self.paragraphs if p.section == section]


class LowerError(Exception):
    def __init__(self, construct: str) -> None:
        super().__init__(construct)
        self.construct = construct


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------
RETURN_CODE_NAME = "RETURN-CODE"


def item_key(prog: Program, item: DataItem) -> str:
    """Normalised name of a data item, shared by dataflow and the interpreter state dicts: the data
    name, qualified as `NAME OF PARENT [OF ...]` only as far as needed to be unique. FILLER items
    get `FILLER@<line>`; the RETURN-CODE special register is `RETURN-CODE`."""
    if item.name == RETURN_CODE_NAME and item.section == "SPECIAL-REGISTER":
        return RETURN_CODE_NAME
    if item.is_filler:
        return f"FILLER@{item.line}"
    others = [o for o in prog.find_items(item.name) if o is not item]
    path = item.path()  # item, parent, ..., root
    k = 1
    while others and k < len(path):
        q = path[k]
        others = [o for o in others if q in o.path()[1:]]
        k += 1
    return " OF ".join(path[:k])


def make_return_code() -> DataItem:
    """RETURN-CODE: GnuCOBOL's BINARY-LONG SIGNED special register (displays as S9(9) binary)."""
    item = DataItem(level=77, name=RETURN_CODE_NAME, file="", line=0, section="SPECIAL-REGISTER")
    item.pic = parse_pic("S9(9)")
    item.usage = "COMP"
    item.usage_explicit = True
    item.unit_size = item.size = 4
    return item


_SPECIAL_REGISTERS = {"TALLY", "SORT-RETURN", "WHEN-COMPILED", "LINAGE-COUNTER", "NUMBER-OF-CALL-PARAMETERS",
                      "ADDRESS", "LENGTH", "DEBUG-ITEM", "SORT-CORE-SIZE", "SORT-FILE-SIZE", "SORT-MESSAGE",
                      "SORT-MODE-SIZE", "XML-CODE", "JSON-CODE", "EXCEPTION-STATUS", "COB-CRT-STATUS"}

_FIG_NAMES: dict[str, str] = {k: v for k, v in FIGURATIVES.items() if v != "NULL"}

_SUPPORTED_USAGES = ("DISPLAY", "COMP", "COMP-3", "COMP-5")


def numeric_literal(tok: Token) -> Lit:
    text = tok.text
    neg = text.startswith("-")
    signed = text[:1] in "+-"
    body = text[1:] if signed else text
    if "." in body:
        ip, fp = body.split(".", 1)
    else:
        ip, fp = body, ""
    return Lit(text, ip + fp, len(fp), neg, signed)


def item_category(item: DataItem) -> str:
    """group | numeric | alphanumeric | alphabetic | numeric-edited | alphanumeric-edited."""
    if item.children:
        return "group"
    if item.pic is None:
        return "unknown"
    return item.pic.category


class _Toks:
    """A cursor over a token slice."""

    def __init__(self, toks: list[Token]) -> None:
        self.toks = toks
        self.i = 0

    def peek(self, k: int = 0) -> Token | None:
        j = self.i + k
        return self.toks[j] if 0 <= j < len(self.toks) else None

    def at(self, *words: str, k: int = 0) -> bool:
        t = self.peek(k)
        return t is not None and t.is_word(*words)

    def at_op(self, *ops: str, k: int = 0) -> bool:
        t = self.peek(k)
        return t is not None and t.kind == OP and t.text in ops

    def next(self) -> Token:
        if self.i >= len(self.toks):
            raise LowerError("incomplete statement")
        t = self.toks[self.i]
        self.i += 1
        return t

    def eof(self) -> bool:
        return self.i >= len(self.toks)

    def accept(self, *words: str) -> bool:
        if self.at(*words):
            self.i += 1
            return True
        return False

    def expect(self, *words: str) -> Token:
        if not self.at(*words):
            t = self.peek()
            raise LowerError(f"expected {'/'.join(words)} but found {t.text if t else 'end of statement'}")
        return self.next()


# ---------------------------------------------------------------------------------------------
# lowering context
# ---------------------------------------------------------------------------------------------
class Lowerer:
    def __init__(self, prog: Program) -> None:
        self.prog = prog
        self.return_code = make_return_code()
        self.proc_names = {p.name for p in prog.paragraphs} | set(prog.sections)
        self.cond_names: dict[str, list[DataItem]] = {}
        for item in prog.all_items():
            for c in item.conditions:
                if c.level == 88:
                    self.cond_names.setdefault(c.name, []).append(c)

    # ---- data references -------------------------------------------------------------------
    def is_data_name(self, name: str) -> bool:
        up = name.upper()
        return bool(self.prog.find_items(up)) or up == RETURN_CODE_NAME or up in self.cond_names

    def _resolve(self, name: str, quals: list[str], tok: Token) -> DataItem:
        if name == RETURN_CODE_NAME and not quals:
            return self.return_code
        if name in _SPECIAL_REGISTERS:
            raise LowerError(f"special register {name}")
        item = self.prog.resolve(name, quals or None)
        if item is None:
            if not self.prog.find_items(name):
                raise LowerError(f"unknown data name {name}")
            raise LowerError(f"ambiguous or unresolvable reference {name}")
        return item

    def parse_ref(self, c: _Toks, allow_refmod: bool = True) -> Ref:
        """identifier [OF/IN qualifier]... [(subscripts)] [(start:length)]"""
        t = c.next()
        if t.kind != WORD:
            raise LowerError(f"expected a data name, found {t.text}")
        name = t.up
        if name in self.cond_names and not self.prog.find_items(name):
            raise LowerError(f"condition-name {name} used as data")
        quals: list[str] = []
        while c.at("OF", "IN") and c.peek(1) is not None and c.peek(1).kind == WORD:  # type: ignore[union-attr]
            c.next()
            quals.append(c.next().up)
        item = self._resolve(name, quals, t)
        start = c.i - 1 - 2 * len(quals)
        ref = Ref(item)
        self._check_item(item, t)
        dims = item.occurs_dims()
        if dims and c.at_op("("):
            ref.subs = self._subscripts(c)
        if len(ref.subs) != dims:
            if dims and not ref.subs:
                raise LowerError(f"table item {name} referenced without subscripts")
            raise LowerError(f"{name} needs {dims} subscript(s), found {len(ref.subs)}")
        if c.at_op("(") and allow_refmod:
            ref.refmod = self._refmod(c)
        ref.text = " ".join(x.text for x in c.toks[start : c.i])
        return ref

    def _check_item(self, item: DataItem, t: Token) -> None:
        if item.level == 66:
            raise LowerError("RENAMES (level 66)")
        if item.depending_on:
            raise LowerError(f"OCCURS DEPENDING ON ({item.name})")
        cur: DataItem | None = item
        while cur is not None:
            if cur.depending_on:
                raise LowerError(f"OCCURS DEPENDING ON ({cur.name})")
            cur = cur.parent
        for it in item.walk():
            if it.depending_on:
                raise LowerError(f"OCCURS DEPENDING ON ({it.name})")
            if it.children or it.level in (66, 88):
                continue
            if it.usage not in _SUPPORTED_USAGES:
                raise LowerError(f"USAGE {it.usage} ({it.name})")
            if it.pic is None:
                raise LowerError(f"item without PICTURE ({it.name})")
            if it.sync:
                raise LowerError(f"SYNCHRONIZED ({it.name})")
            if it.blank_when_zero:
                raise LowerError(f"BLANK WHEN ZERO ({it.name})")
            if it.pic.category == "numeric" and it.pic.digits > 18 and it.usage != "DISPLAY":
                raise LowerError(f"binary/packed item with more than 18 digits ({it.name})")
            if it.issues:
                raise LowerError(f"data item {it.name}: {it.issues[0]}")

    def _subscripts(self, c: _Toks) -> list[Expr]:
        c.next()  # (
        subs: list[Expr] = []
        while True:
            if c.at_op(")"):
                c.next()
                break
            if c.at("ALL"):
                raise LowerError("subscript ALL")
            e = self._subscript_expr(c)
            subs.append(e)
            if c.at_op(":"):
                raise LowerError("reference modification of a table without subscripts")
        return subs

    def _subscript_expr(self, c: _Toks) -> Expr:
        """subscript: integer, data-name [+/- integer] (also general arithmetic, as cobc allows)."""
        toks: list[Token] = []
        depth = 0
        while not c.eof():
            t = c.peek()
            assert t is not None
            if t.kind == OP and t.text == "(":
                depth += 1
            elif t.kind == OP and t.text == ")":
                if depth == 0:
                    break
                depth -= 1
            elif depth == 0 and t.kind == OP and t.text == ":":
                break
            toks.append(c.next())
            # a subscript list is space separated: stop after a complete operand
            if depth == 0 and self._subscript_complete(toks, c):
                break
        if not toks:
            raise LowerError("empty subscript")
        return self.arith_expr(toks)

    def _subscript_complete(self, toks: list[Token], c: _Toks) -> bool:
        nxt = c.peek()
        if nxt is None:
            return True
        last = toks[-1]
        if last.kind == OP and last.text in "+-*/":
            return False
        if nxt.kind == OP and nxt.text in ("+", "-", "*", "/", "**", "("):
            return nxt.text == "(" and last.kind == NUM
        if nxt.kind == NUM and nxt.text[:1] in "+-":
            return False
        return not (last.is_word("OF", "IN") or nxt.is_word("OF", "IN"))

    def _refmod(self, c: _Toks) -> tuple[Expr, Expr | None]:
        c.next()  # (
        start_toks: list[Token] = []
        depth = 0
        while not c.eof():
            t = c.peek()
            assert t is not None
            if depth == 0 and t.kind == OP and t.text == ":":
                break
            if t.kind == OP and t.text == "(":
                depth += 1
            if t.kind == OP and t.text == ")":
                depth -= 1
            start_toks.append(c.next())
        if not c.at_op(":"):
            raise LowerError("malformed reference modification")
        c.next()
        len_toks: list[Token] = []
        depth = 0
        while not c.eof():
            t = c.peek()
            assert t is not None
            if t.kind == OP and t.text == ")" and depth == 0:
                break
            if t.kind == OP and t.text == "(":
                depth += 1
            if t.kind == OP and t.text == ")":
                depth -= 1
            len_toks.append(c.next())
        if not c.at_op(")"):
            raise LowerError("malformed reference modification")
        c.next()
        if not start_toks:
            raise LowerError("reference modification without start")
        return self.arith_expr(start_toks), (self.arith_expr(len_toks) if len_toks else None)

    # ---- simple operands ---------------------------------------------------------------------
    def operand(self, c: _Toks) -> Expr:
        """identifier | literal | figurative constant (no arithmetic)."""
        t = c.peek()
        if t is None:
            raise LowerError("missing operand")
        if t.kind == NUM:
            c.next()
            return numeric_literal(t)
        if t.kind == STR:
            c.next()
            if t.text[:1].upper() in "NZ":
                raise LowerError(f"{t.text[:1].upper()}-literal")
            return StrLit(t.value.encode("latin-1"))
        if t.kind == HEX:
            c.next()
            return StrLit(t.value.encode("latin-1"))
        if t.kind == WORD:
            if t.up == "ALL":
                c.next()
                lit = c.next()
                if lit.kind in (STR, HEX):
                    return Fig("ALL", lit.value.encode("latin-1"))
                if lit.kind == WORD and lit.up in _FIG_NAMES:
                    return Fig(_FIG_NAMES[lit.up])
                raise LowerError("ALL with a non-literal operand")
            if t.up in _FIG_NAMES:
                c.next()
                return Fig(_FIG_NAMES[t.up])
            if t.up in ("NULL", "NULLS"):
                raise LowerError("NULL")
            if t.up == "FUNCTION":
                name = c.peek(1)
                raise LowerError(f"FUNCTION {name.up if name else ''}".strip())
            if t.up in ("LENGTH", "ADDRESS") and c.at("OF", k=1):
                raise LowerError(f"{t.up} OF")
            return self.parse_ref(c)
        if t.kind == OP and t.text in "+-" and c.peek(1) is not None and c.peek(1).kind == NUM:  # type: ignore[union-attr]
            c.next()
            n = c.next()
            nl = numeric_literal(n)
            if t.text == "-":
                return Lit("-" + n.text, nl.digits, nl.scale, not nl.negative, True)
            return Lit("+" + n.text, nl.digits, nl.scale, nl.negative, True)
        raise LowerError(f"unexpected {t.text!r}")

    # ---- arithmetic expressions (cobc `exp` grammar) -----------------------------------------
    def arith_expr(self, toks: list[Token]) -> Expr:
        c = _Toks(_split_signed_numbers(toks))
        e = self._exp(c)
        if not c.eof():
            raise LowerError(f"unexpected {c.peek().text!r} in arithmetic expression")  # type: ignore[union-attr]
        return e

    def _exp(self, c: _Toks) -> Expr:
        left = self._exp_term(c)
        while c.at_op("+", "-"):
            op = c.next().text
            right = self._exp_term(c)
            left = fold(Bin(op, left, right))
        return left

    def _exp_term(self, c: _Toks) -> Expr:
        left = self._exp_factor(c)
        while c.at_op("*", "/"):
            op = c.next().text
            right = self._exp_factor(c)
            left = fold(Bin(op, left, right))
        return left

    def _exp_factor(self, c: _Toks) -> Expr:
        base = self._exp_unary(c)
        if c.at_op("**"):
            c.next()
            return fold(Bin("^", base, self._exp_factor(c)))
        return base

    def _exp_unary(self, c: _Toks) -> Expr:
        if c.at_op("+"):
            c.next()
            return self._exp_atom(c)
        if c.at_op("-"):
            c.next()
            return fold(Bin("-", ZERO_CONST, self._exp_atom(c)))
        return self._exp_atom(c)

    def _exp_atom(self, c: _Toks) -> Expr:
        if c.at_op("("):
            c.next()
            e = self._exp(c)
            if not c.at_op(")"):
                raise LowerError("unbalanced parentheses")
            c.next()
            return e
        e = self.operand(c)
        _check_numeric_operand(e)
        return e

    # ---- conditions: port of cobc's build_expr_* shift/reduce --------------------------------
    def condition(self, toks: list[Token]) -> Cond:
        items = self._cond_tokens(toks)
        return _ExprBuilder(items).build()

    def _cond_tokens(self, toks: list[Token]) -> list[tuple[str, object]]:
        """Map COBOL condition words to cobc expression tokens (parser.y `expr_token`)."""
        c = _Toks(_split_signed_numbers(toks))
        out: list[tuple[str, object]] = []
        while not c.eof():
            t = c.peek()
            assert t is not None
            if t.kind == OP:
                txt = t.text
                c.next()
                mapping = {"(": "(", ")": ")", "+": "+", "-": "-", "*": "*", "/": "/", "**": "^",
                           "=": "=", ">": ">", "<": "<", ">=": "]", "<=": "[", "<>": "~"}
                if txt not in mapping:
                    raise LowerError(f"operator {txt} in condition")
                out.append((mapping[txt], None))
                continue
            if t.kind == WORD:
                w = t.up
                if w == "IS":
                    c.next()
                    continue
                if w == "NOT":
                    c.next()
                    out.append(("!", None))
                    continue
                if w == "AND":
                    c.next()
                    out.append(("&", None))
                    continue
                if w == "OR":
                    c.next()
                    out.append(("|", None))
                    continue
                if w in ("EQUAL", "EQUALS"):
                    c.next()
                    c.accept("TO")
                    out.append(("=", None))
                    continue
                if w in ("GREATER", "EXCEEDS"):
                    c.next()
                    c.accept("THAN")
                    if c.at("OR") and c.at("EQUAL", k=1):
                        c.next()
                        c.next()
                        c.accept("TO")
                        out.append(("]", None))
                    else:
                        out.append((">", None))
                    continue
                if w == "LESS":
                    c.next()
                    c.accept("THAN")
                    if c.at("OR") and c.at("EQUAL", k=1):
                        c.next()
                        c.next()
                        c.accept("TO")
                        out.append(("[", None))
                    else:
                        out.append(("<", None))
                    continue
                if w == "THAN" or w == "TO":
                    c.next()
                    continue
                if w in ("NUMERIC", "ALPHABETIC", "ALPHABETIC-LOWER", "ALPHABETIC-UPPER"):
                    c.next()
                    out.append(({"NUMERIC": "9", "ALPHABETIC": "A", "ALPHABETIC-LOWER": "L",
                                 "ALPHABETIC-UPPER": "U"}[w], None))
                    continue
                if w == "POSITIVE":
                    c.next()
                    out.append(("P", None))
                    continue
                if w == "NEGATIVE":
                    c.next()
                    out.append(("N", None))
                    continue
                if w in ("OMITTED",):
                    raise LowerError("OMITTED condition")
                if w in ("ZERO", "ZEROS", "ZEROES"):
                    c.next()
                    out.append(("x", ZERO_FIG))
                    continue
                if w in self.cond_names and not self.prog.find_items(w):
                    out.append(("x", self._cond_name(c)))
                    continue
                if w in ("TRUE", "FALSE"):
                    raise LowerError(f"{w} in a condition")
            out.append(("x", self.operand(c)))
        return out

    def _cond_name(self, c: _Toks) -> CondName:
        t = c.next()
        name = t.up
        quals: list[str] = []
        while c.at("OF", "IN") and c.peek(1) is not None and c.peek(1).kind == WORD:  # type: ignore[union-attr]
            c.next()
            quals.append(c.next().up)
        cands = self.cond_names.get(name, [])
        if quals:
            cands = [x for x in cands if x.parent is not None and all(q in x.parent.path() for q in quals)]
        if len(cands) != 1:
            raise LowerError(f"ambiguous condition-name {name}")
        cond = cands[0]
        parent = cond.parent
        assert parent is not None
        self._check_item(parent, t)
        ref = Ref(parent, text=parent.name)
        dims = parent.occurs_dims()
        if dims:
            if not c.at_op("("):
                raise LowerError(f"condition-name {name} of a table item without subscripts")
            ref.subs = self._subscripts(c)
            if len(ref.subs) != dims:
                raise LowerError(f"{name} needs {dims} subscript(s)")
        return CondName(cond, ref, cond88_test(cond, ref))


ZERO_CONST = Lit("0", "0", 0, False, False)
ZERO_FIG = Fig("ZERO")


def _check_numeric_operand(e: Expr) -> None:
    if isinstance(e, StrLit):
        raise LowerError("alphanumeric literal in arithmetic expression")
    if isinstance(e, Fig) and e.name != "ZERO":
        raise LowerError(f"figurative {e.name} in arithmetic expression")
    if isinstance(e, Ref):
        cat = item_category(e.item)
        if cat != "numeric" or e.refmod is not None:
            raise LowerError(f"non-numeric operand {e} in arithmetic expression")


def _split_signed_numbers(toks: list[Token]) -> list[Token]:
    """`A -1` lexes as A, NUM(-1): cobc's scanner treats a sign glued to a literal after an
    operand as a binary operator. Split such literals back into operator + literal."""
    out: list[Token] = []
    for t in toks:
        if t.kind == NUM and t.text[:1] in "+-" and out:
            prev = out[-1]
            prev_is_operand = prev.kind in (NUM, STR, HEX) or (prev.kind == WORD and prev.up not in (
                "IS", "NOT", "AND", "OR", "EQUAL", "EQUALS", "GREATER", "LESS", "THAN", "TO", "EXCEEDS"))\
                or (prev.kind == OP and prev.text == ")")
            if prev_is_operand:
                out.append(Token(OP, t.text[0], t.file, t.line, t.col))
                out.append(Token(NUM, t.text[1:], t.file, t.line, t.col + 1))
                continue
        out.append(t)
    return out


# ---------------------------------------------------------------------------------------------
# relations decided at compile time (tree.c cb_build_binary_op / compare_field_literal)
# ---------------------------------------------------------------------------------------------
_MIRROR = {">": "<", "]": "[", "<": ">", "[": "]"}


def _lit_data(e: Expr) -> tuple[bytes, int] | None:
    """(data, scale) of a literal as cobc stores it (numeric: unsigned digits), or None."""
    if isinstance(e, Lit):
        return e.digits.encode(), e.scale
    if isinstance(e, StrLit):
        return e.value, 0
    if isinstance(e, Fig) and e.name == "ZERO":
        return b"0", 0  # cb_zero_lit
    return None


def _refmod_length(ref: Ref) -> int | None:
    """0 when not reference-modified, the literal length, or None when known only at run time."""
    if ref.refmod is None:
        return 0
    start, length = ref.refmod
    if isinstance(length, Lit):
        return length.value
    if length is None and isinstance(start, Lit):
        return ref.item.unit_size - start.value + 1
    return None


def _compare_field_literal(swap: bool, ref: Ref, op: str, data: bytes, lscale: int) -> Cond | None:
    item = ref.item
    if item.pic is not None:
        category, fscale = item.pic.category, item.pic.scale
    else:
        category, fscale = "alphabetic", 0
    refmod_length = _refmod_length(ref)
    if refmod_length is None:
        return None
    lit_length = len(data.rstrip(b" "))
    alph_lit = any(not 0x30 <= c <= 0x39 for c in data)
    zero_val = not alph_lit and all(c == 0x30 for c in data)
    if category not in ("numeric", "numeric-edited") or refmod_length:
        if not refmod_length:
            refmod_length = item.unit_size
        if lit_length > refmod_length:
            if op == "=":
                return BoolConst(False)
            if op == "~":
                return BoolConst(True)
        return None
    if fscale < 0 or alph_lit:
        return None
    if zero_val:
        scale = i = 0
    else:
        lit_start = 0
        while lit_start < len(data) and data[lit_start] == 0x30:
            lit_start += 1
        lit_length -= lit_start
        scale = lscale
        i = lit_length
        j = len(data)
        while scale > 0 and j > 0 and data[j - 1] == 0x30:
            j -= 1
            i -= 1
            scale -= 1
    if scale > 0 and fscale < scale:
        if op == "=":
            return BoolConst(False)
        if op == "~":
            return BoolConst(True)
    if swap:
        op = _MIRROR.get(op, op)
    size = item.unit_size
    if i - scale > 0 and size - fscale >= 0 and i - scale > size - fscale:
        if op == "=":
            return BoolConst(False)
        if op == "~":
            return BoolConst(True)
        if category == "numeric":
            if op in (">", "]"):
                return BoolConst(False)
            if op in ("<", "["):
                return BoolConst(True)
    return None


def fold_rel(op: str, x: Expr, y: Expr) -> Cond:
    """A relation as cobc builds it. Some DISPLAY-item/literal relations are decided at compile
    time from the literal's digits alone (its sign is ignored), so GnuCOBOL's result can differ
    from the arithmetic truth: an unsigned PIC 9V9 item is always `< -607.57` (see S7)."""
    xl, yl = _lit_data(x), _lit_data(y)
    folded: Cond | None = None
    if isinstance(y, Ref) and y.item.usage == "DISPLAY" and xl is not None:
        folded = _compare_field_literal(True, y, op, xl[0], xl[1])
    elif isinstance(x, Ref) and x.item.usage == "DISPLAY" and yl is not None:
        folded = _compare_field_literal(False, x, op, yl[0], yl[1])
    elif isinstance(x, Lit) and isinstance(y, Lit) and x.scale == 0 and y.scale == 0 \
            and not x.signed and not y.signed and not x.negative and not y.negative:
        a, b = int(x.digits or "0"), int(y.digits or "0")
        folded = BoolConst({"=": a == b, "~": a != b, ">": a > b, "<": a < b, "]": a >= b,
                            "[": a <= b}[op])
    elif isinstance(x, StrLit) and isinstance(y, StrLit):
        raise LowerError("relation between two alphanumeric literals")
    return folded if folded is not None else Rel(op, x, y)


def value_literal(v: object) -> Expr:
    """An 88-level / VALUE literal (datadiv.ValueLit) as an IR operand."""
    kind = getattr(v, "kind", "")
    text = str(getattr(v, "text", ""))
    if kind == "num":
        t = text.strip()
        neg = t.startswith("-")
        signed = t[:1] in "+-"
        body = t[1:] if signed else t
        ip, _, fp = body.partition(".")
        return Lit(t, ip + fp, len(fp), neg, signed)
    if kind == "str":
        return StrLit(text.encode("latin-1"))
    if kind == "fig":
        return Fig(text)
    raise LowerError(f"88-level VALUE {v}")


def cond88_test(cond: DataItem, parent: Ref) -> Cond:
    """typeck.c build_cond_88: (x >= lo AND x <= hi) / x = v for each VALUE, OR'ed in order."""
    out: Cond | None = None
    for lo, hi in cond.values_88:
        if hi is not None:
            c2: Cond = And(fold_rel("]", parent, value_literal(lo)), fold_rel("[", parent, value_literal(hi)))
        else:
            c2 = fold_rel("=", parent, value_literal(lo))
        out = c2 if out is None else Or(out, c2)
    if out is None:
        raise LowerError(f"88-level {cond.name} without VALUE")
    return out


# ---------------------------------------------------------------------------------------------
# cobc constant folding (tree.c cb_build_binary_op), value preserving within signed 64 bits
# ---------------------------------------------------------------------------------------------
_I64 = 1 << 63


def _lit_from_int(v: int, scale: int) -> Lit:
    neg = v < 0
    digits = str(abs(v))
    return Lit(("-" if neg else "") + digits, digits, scale, neg, neg)


def fold(e: Bin) -> Expr:
    x, y = e.left, e.right
    op = e.op
    if isinstance(x, Lit) and isinstance(y, Lit):
        # cobc: `xl->llit == 0 && size >= scale` hold for ordinary literals
        xval, yval = x.value, y.value
        xs, ys = x.scale, y.scale
        rscale = 0
        rslt = 0
        if op in "+-":
            while xs < ys:
                xval *= 10
                xs += 1
            while xs > ys:
                yval *= 10
                ys += 1
            rscale = xs
            rslt = xval + yval if op == "+" else xval - yval
        elif op == "*":
            rscale = xs + ys
            rslt = xval * yval
        elif op == "/" and yval != 0:
            while ys > 0:
                xval *= 10
                ys -= 1
            rscale = xs
            if _c_mod(xval, yval) == 0:
                rslt = _c_div(xval, yval)
        if op in "+-*":
            if abs(rslt) >= _I64 or abs(xval) >= _I64 or abs(yval) >= _I64:
                raise LowerError("constant expression overflows 64 bits")
            while rscale > 0 and rslt != 0 and rslt % 10 == 0:
                rslt //= 10
                rscale -= 1
            return _lit_from_int(rslt, rscale)
        if op == "/":
            if yval == 0:
                return e
            if rslt != 0:
                while rscale > 0 and rslt % 10 == 0:
                    rslt = _c_div(rslt, 10)
                    rscale -= 1
                return _lit_from_int(rslt, rscale)
            if x.scale != 0 or y.scale != 0:
                return e
            if _c_mod(xval, yval) == 0:
                return _lit_from_int(_c_div(xval, yval), rscale)
            return e
        if op == "^":
            if x.scale != 0 or y.scale != 0 or yval < 0:
                return e
            if yval == 0 or xval == 1:
                return _lit_from_int(1, 0)
            r = xval
            n = yval
            while n - 1 > 0:
                r *= xval
                n -= 1
                if abs(r) >= _I64:
                    raise LowerError("constant expression overflows 64 bits")
            return _lit_from_int(r, 0)
        return e
    if isinstance(y, Lit) and y.scale == 0:
        yv = int(y.digits) if y.digits else 0
        if op in "+-" and yv == 0:
            return x
        if op in "*/" and yv == 1 and not y.negative:
            return x
        if op == "*" and yv == 0:
            return Lit("0", "0", 0, False, False)
    return e


def _c_div(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def _c_mod(a: int, b: int) -> int:
    return a - b * _c_div(a, b)


# ---------------------------------------------------------------------------------------------
# cobc build_expr_* (typeck.c) — shift/reduce over expression tokens
# ---------------------------------------------------------------------------------------------
_PRIO = {"x": 0, "^": 1, "*": 2, "/": 2, "+": 3, "-": 3, "=": 4, "~": 4, "<": 4, ">": 4, "[": 4, "]": 4,
         "!": 5, "&": 6, "|": 7, ")": 8, "(": 9, "": 10}
_NOT_REL = {"=": "~", "~": "=", "<": "]", ">": "[", "[": ">", "]": "<"}
_RELS = ("=", "~", "<", ">", "[", "]")



def _is_bool(v: object) -> bool:
    return isinstance(v, (Rel, ClassTest, CondName, Not, And, Or, BoolConst))


class _ExprBuilder:
    def __init__(self, items: list[tuple[str, object]]) -> None:
        self.items = items
        # stack slots; TOPSTACK holds a sentinel (cobc starts at index 4 with zeroed tokens)
        self.tok: list[str] = ["", "", "", ""]
        self.val: list[object] = [None, None, None, None]
        self.lh: object = None
        self.op: str = ""

    # stack access relative to the top (TOKEN(-1) is the last pushed)
    def T(self, k: int) -> str:
        j = len(self.tok) + k
        return self.tok[j] if j >= 0 else ""

    def V(self, k: int) -> object:
        j = len(self.val) + k
        return self.val[j] if j >= 0 else None

    def setT(self, k: int, v: str) -> None:
        self.tok[len(self.tok) + k] = v

    def setV(self, k: int, v: object) -> None:
        self.val[len(self.val) + k] = v

    def pop(self, n: int) -> None:
        for _ in range(n):
            self.tok.pop()
            self.val.pop()

    def build_value(self) -> object:
        """cb_build_expr: shift every token, reduce, return the single remaining value."""
        for op, v in self.items:
            if op in ("9", "A", "L", "U"):
                self.shift_class(op)
                continue
            if op == "P":
                self.shift_sign(">")
                continue
            if op == "N":
                self.shift_sign("<")
                continue
            if self.T(-1) == "!" and op in _NOT_REL:
                self.setT(-1, _NOT_REL[op])
                continue
            self.shift(op, v)
        if self.reduce("") < 0:
            raise LowerError("invalid condition")
        if len(self.tok) != 5 or self.T(-1) != "x":
            raise LowerError("invalid condition (unfinished expression)")
        return self.V(-1)

    def build(self) -> Cond:
        result = self.build_value()
        if not _is_bool(result):
            raise LowerError("condition expected")
        return result  # type: ignore[return-value]

    def _binop(self, x: object, op: str, y: object) -> object:
        if op in _RELS:
            if _is_bool(x) or _is_bool(y):
                raise LowerError("condition where a value was expected")
            if x is None or y is None:
                raise LowerError("invalid relation")
            return fold_rel(op, x, y)  # type: ignore[arg-type]
        if op == "&":
            return And(_need_cond(x), _need_cond(y))
        if op == "|":
            return Or(_need_cond(x), _need_cond(y))
        if _is_bool(x) or _is_bool(y):
            raise LowerError("condition in arithmetic expression")
        assert isinstance(x, (Ref, Lit, StrLit, Fig, Bin)) and isinstance(y, (Ref, Lit, StrLit, Fig, Bin))
        if op in "+-*/^":
            _check_numeric_operand(x)
            _check_numeric_operand(y)
        return fold(Bin(op, x, y))

    def reduce(self, token: str) -> int:
        while _PRIO[self.T(-2)] <= _PRIO[token]:
            op = self.T(-2)
            if op in ("x", "(", ")", ""):
                return 0
            if op in ("+", "-", "*", "/", "^"):
                if self.T(-1) != "x" or self.T(-3) != "x":
                    return -1
                self.setT(-3, "x")
                self.setV(-3, self._binop(self.V(-3), op, self.V(-1)))
                self.pop(2)
            elif op == "!":
                if self.T(-1) != "x":
                    return -1
                if self.lh is not None and not _is_bool(self.V(-1)):
                    self.setV(-1, self._binop(self.lh, self.op, self.V(-1)))
                self.setT(-2, "x")
                self.setV(-2, Not(_need_cond(self.V(-1))))
                self.pop(1)
            elif op in ("&", "|"):
                if self.T(-1) != "x" or self.T(-3) != "x":
                    return -1
                if self.lh is not None:
                    if not _is_bool(self.V(-1)):
                        self.setV(-1, self._binop(self.lh, self.op, self.V(-1)))
                    if not _is_bool(self.V(-3)):
                        self.setV(-3, self._binop(self.lh, self.op, self.V(-3)))
                self.setT(-3, "x")
                self.setV(-3, self._binop(self.V(-3), op, self.V(-1)))
                self.pop(2)
            else:
                # relational operators
                if self.T(-1) != "x":
                    return -1
                lhs = self.V(-1)
                if self.T(-3) == "!":
                    new = _NOT_REL.get(op)
                    if new is not None:
                        op = new
                        # cobc: expr_index -= 1 (drops the top slot, re-reading lhs saved above)
                        self.pop(1)
                t3 = self.T(-3)
                if t3 == "x":
                    self.lh = self.V(-3)
                    if _is_bool(self.lh) and not _is_bool(lhs):
                        raise LowerError("invalid condition")
                    self.op = op
                    self.setT(-3, "x")
                    if not _is_bool(lhs):
                        self.setV(-3, self._binop(self.lh, op, lhs))
                    else:
                        self.setV(-3, lhs)
                    self.pop(2)
                elif t3 in ("&", "|"):
                    self.op = op
                    self.setT(-2, "x")
                    if not _is_bool(lhs) and self.lh is not None:
                        self.setV(-2, self._binop(self.lh, op, lhs))
                    else:
                        self.setV(-2, lhs)
                    self.pop(1)
                else:
                    return -1
        if token == "&" and self.T(-2) == "|" and not _is_bool(self.V(-1)):
            if self.lh is None:
                raise LowerError("missing left-hand expression")
            self.setT(-1, "x")
            self.setV(-1, self._binop(self.lh, self.op, self.V(-1)))
        return 0

    def shift_sign(self, op: str) -> None:
        have_not = False
        if self.T(-1) == "!":
            have_not = True
            self.pop(1)
        self.reduce("=")
        if self.T(-1) == "x":
            v: object = self._binop(self.V(-1), op, ZERO_FIG)
            if have_not:
                v = Not(_need_cond(v))
            self.setV(-1, v)

    def shift_class(self, kind: str) -> None:
        have_not = False
        if self.T(-1) == "!":
            have_not = True
            self.pop(1)
        self.reduce("=")
        if self.T(-1) == "x":
            operand = self.V(-1)
            if _is_bool(operand) or operand is None:
                raise LowerError("class condition on a condition")
            names = {"9": "NUMERIC", "A": "ALPHABETIC", "L": "ALPHABETIC-LOWER", "U": "ALPHABETIC-UPPER"}
            v: object = ClassTest(names[kind], operand)  # type: ignore[arg-type]
            if have_not:
                v = Not(_need_cond(v))
            self.setV(-1, v)

    def shift(self, token: str, value: object) -> None:
        if token == "x":
            if value is ZERO_FIG and self.T(-1) in ("x", "!"):
                self.shift_sign("=")
                return
            if self.T(-1) in ("+", "-") and self.T(-2) != "x":
                if self.T(-1) == "-":
                    if _is_bool(value):
                        raise LowerError("unary minus on a condition")
                    value = self._binop(ZERO_CONST, "-", value)
                self.pop(1)
        elif token == "(":
            if self.T(-1) in _RELS:
                self.op = self.T(-1)
                if self.T(-2) == "x":
                    self.lh = self.V(-2)
        elif token == ")":
            self.reduce(token)
            v1 = self.V(-1)
            if isinstance(v1, Rel):
                self.lh = None
            if self.T(-2) == "(":
                self.pop(2)
                self.shift("x", v1)
                return
        if self.reduce(token) > 0:
            return
        self.tok.append(token)
        self.val.append(value)


def _need_cond(v: object) -> Cond:
    if not _is_bool(v):
        raise LowerError("value where a condition was expected")
    return v  # type: ignore[return-value]


# ---------------------------------------------------------------------------------------------
# statement lowering
# ---------------------------------------------------------------------------------------------
_ARITH_STOP = ("TO", "FROM", "BY", "INTO", "GIVING", "REMAINDER", "ROUNDED")


class StatementLowerer(Lowerer):
    def block(self, stmts: list[Statement]) -> list[Stmt]:
        return [self.statement(s) for s in stmts]

    def statement(self, st: Statement) -> Stmt:
        loc = Loc(st.file, st.line)
        try:
            return self._statement(st, loc)
        except LowerError as exc:
            return Unsupported(loc, st.verb, exc.construct if exc.construct.startswith(st.verb) else
                               f"{st.verb}: {exc.construct}")

    def _branch(self, st: Statement, kind: str) -> list[Stmt] | None:
        for b in st.branches:
            if b.kind == kind:
                return self.block(b.body)
        return None

    def _only_branches(self, st: Statement, allowed: tuple[str, ...]) -> None:
        for b in st.branches:
            if b.kind not in allowed:
                raise LowerError(f"{' '.join(t.text for t in b.tokens) or b.kind} phrase")

    def _statement(self, st: Statement, loc: Loc) -> Stmt:
        v = st.verb
        handler = getattr(self, "_lower_" + v.replace("-", "_").lower(), None)
        if handler is None:
            raise LowerError(v)
        result: Stmt = handler(st, loc)
        return result

    # ---- MOVE --------------------------------------------------------------------------------
    def _lower_move(self, st: Statement, loc: Loc) -> Stmt:
        self._only_branches(st, ())
        c = _Toks(st.tokens[1:])
        if c.at("CORRESPONDING", "CORR"):
            raise LowerError("MOVE CORRESPONDING")
        src = self.operand(c)
        c.expect("TO")
        dsts: list[Ref] = []
        while not c.eof():
            dsts.append(self._receiving(c))
        if not dsts:
            raise LowerError("MOVE without receiving item")
        for d in dsts:
            self._check_move(src, d)
        return Move(loc, "MOVE", src, dsts)

    def _receiving(self, c: _Toks) -> Ref:
        e = self.operand(c)
        if not isinstance(e, Ref):
            raise LowerError(f"receiving operand {e} is not a data item")
        return e

    def _check_move(self, src: Expr, dst: Ref) -> None:
        dcat = item_category(dst.item) if dst.refmod is None else "alphanumeric"
        if dcat == "alphanumeric-edited":
            raise LowerError("alphanumeric-edited receiving item")
        if isinstance(src, Ref):
            scat = item_category(src.item) if src.refmod is None else "alphanumeric"
            if scat in ("alphanumeric-edited",):
                raise LowerError("alphanumeric-edited sending item")
            if scat == "numeric-edited" and dcat not in ("group", "alphanumeric", "alphabetic"):
                raise LowerError("de-editing MOVE (numeric-edited to numeric)")
        if isinstance(src, Lit) and dcat in ("alphanumeric", "alphabetic") and src.scale > 0:
            raise LowerError("non-integer numeric literal to alphanumeric")
        if isinstance(src, Lit) and dcat in ("alphanumeric", "alphabetic") and src.negative:
            raise LowerError("negative numeric literal to alphanumeric")
        if isinstance(src, Fig) and src.name in ("SPACE", "HIGH-VALUE", "LOW-VALUE", "QUOTE") and dcat in (
                "numeric", "numeric-edited"):
            raise LowerError(f"MOVE {src.name} to a numeric item")
        if isinstance(src, Fig) and src.name == "ALL" and dcat in ("numeric", "numeric-edited"):
            raise LowerError("MOVE ALL literal to a numeric item")
        if isinstance(src, StrLit) and dcat == "numeric-edited":
            raise LowerError("alphanumeric literal to numeric-edited item")
        if dst.item is self.return_code and not isinstance(src, (Lit, Ref)):
            raise LowerError("MOVE to RETURN-CODE from a non-numeric operand")
        if dcat == "numeric-edited" and dst.item.pic is not None:
            _check_edited_pic(dst.item.pic)

    # ---- arithmetic --------------------------------------------------------------------------
    def _targets(self, c: _Toks, allow_rounded: bool = True) -> list[Target]:
        out: list[Target] = []
        while not c.eof() and not c.at("GIVING", "REMAINDER"):
            ref = self._receiving(c)
            if ref.refmod is not None:
                raise LowerError("reference-modified arithmetic target")
            cat = item_category(ref.item)
            if cat not in ("numeric", "numeric-edited"):
                raise LowerError(f"non-numeric arithmetic target {ref}")
            if cat == "numeric-edited" and ref.item.pic is not None:
                _check_edited_pic(ref.item.pic)
            rounded = False
            if c.accept("ROUNDED"):
                if not allow_rounded:
                    raise LowerError("ROUNDED here")
                rounded = True
                if c.at("MODE"):
                    raise LowerError("ROUNDED MODE")
            out.append(Target(ref, rounded))
        if not out:
            raise LowerError("missing receiving item")
        return out

    def _arith_sources(self, c: _Toks, stops: tuple[str, ...]) -> list[Expr]:
        out: list[Expr] = []
        while not c.eof() and not c.at(*stops):
            e = self.operand(c)
            _check_numeric_operand(e)
            out.append(e)
        return out

    def _size_branches(self, st: Statement) -> tuple[list[Stmt] | None, list[Stmt] | None]:
        self._only_branches(st, ("size_error", "not_size_error"))
        return self._branch(st, "size_error"), self._branch(st, "not_size_error")

    def _lower_compute(self, st: Statement, loc: Loc) -> Stmt:
        toks = st.tokens[1:]
        eq = next((i for i, t in enumerate(toks) if (t.kind == OP and t.text == "=") or t.is_word("EQUAL")), None)
        if eq is None:
            raise LowerError("COMPUTE without =")
        targets = self._targets(_Toks(toks[:eq]))
        expr = self.arith_expr(toks[eq + 1:])
        se, nse = self._size_branches(st)
        return ArithAssign(loc, "COMPUTE", None, expr, targets, se, nse)

    def _lower_add(self, st: Statement, loc: Loc) -> Stmt:
        return self._add_sub(st, loc, "+")

    def _lower_subtract(self, st: Statement, loc: Loc) -> Stmt:
        return self._add_sub(st, loc, "-")

    def _add_sub(self, st: Statement, loc: Loc, op: str) -> Stmt:
        c = _Toks(st.tokens[1:])
        if c.at("CORRESPONDING", "CORR"):
            raise LowerError(f"{st.verb} CORRESPONDING")
        key = "TO" if op == "+" else "FROM"
        srcs = self._arith_sources(c, (key, "GIVING"))
        if not srcs:
            raise LowerError(f"{st.verb} without operands")
        se, nse = self._size_branches(st)
        if c.accept(key):
            if any(t.is_word("GIVING") for t in c.toks[c.i:]):
                # ADD a b TO c GIVING d     -> d = (a + b) + c        (parser.y add_body)
                # SUBTRACT a b FROM c GIVING d -> d = (c - a) - b     (subtract_body)
                base = self.operand(c)
                _check_numeric_operand(base)
                c.expect("GIVING")
                targets = self._targets(c)
                expr = _sum([*srcs, base]) if op == "+" else _binary_list([base, *srcs], "-")
                return ArithAssign(loc, st.verb, None, expr, targets, se, nse)
            targets = self._targets(c)
            total = _sum(srcs)
            if not isinstance(total, Bin):
                return ArithOp(loc, st.verb, op, total, targets, se, nse)
            return ArithAssign(loc, st.verb, op, total, targets, se, nse)
        if op == "+" and c.accept("GIVING"):
            # ADD a b GIVING c (no TO)
            targets = self._targets(c)
            if len(srcs) < 2:
                raise LowerError("ADD GIVING with a single operand")
            return ArithAssign(loc, st.verb, None, _sum(srcs), targets, se, nse)
        raise LowerError(f"{st.verb} without {key}")

    def _lower_multiply(self, st: Statement, loc: Loc) -> Stmt:
        c = _Toks(st.tokens[1:])
        a = self.operand(c)
        _check_numeric_operand(a)
        c.expect("BY")
        se, nse = self._size_branches(st)
        if any(t.is_word("GIVING") for t in c.toks[c.i:]):
            b = self.operand(c)
            _check_numeric_operand(b)
            c.expect("GIVING")
            targets = self._targets(c)
            return ArithAssign(loc, "MULTIPLY", None, fold(Bin("*", a, b)), targets, se, nse)
        targets = self._targets(c)
        return ArithOp(loc, "MULTIPLY", "*", a, targets, se, nse)

    def _lower_divide(self, st: Statement, loc: Loc) -> Stmt:
        c = _Toks(st.tokens[1:])
        a = self.operand(c)
        _check_numeric_operand(a)
        se, nse = self._size_branches(st)
        if c.accept("INTO"):
            if not any(t.is_word("GIVING") for t in c.toks[c.i:]):
                targets = self._targets(c)
                return ArithOp(loc, "DIVIDE", "/", a, targets, se, nse)
            b = self.operand(c)
            _check_numeric_operand(b)
            dividend, divisor = b, a
        elif c.accept("BY"):
            b = self.operand(c)
            _check_numeric_operand(b)
            dividend, divisor = a, b
        else:
            raise LowerError("DIVIDE without INTO/BY")
        c.expect("GIVING")
        targets = self._targets(c)
        if c.accept("REMAINDER"):
            if len(targets) != 1:
                raise LowerError("DIVIDE REMAINDER with several GIVING items")
            rem = self._receiving(c)
            if item_category(rem.item) not in ("numeric", "numeric-edited") or rem.refmod is not None:
                raise LowerError("non-numeric REMAINDER item")
            if item_category(rem.item) == "numeric-edited" and rem.item.pic is not None:
                _check_edited_pic(rem.item.pic)
            if not c.eof():
                raise LowerError("unexpected tokens after REMAINDER")
            return DivRem(loc, "DIVIDE", dividend, divisor, targets[0], rem, se, nse)
        return ArithAssign(loc, "DIVIDE", None, fold(Bin("/", dividend, divisor)), targets, se, nse)

    # ---- control flow ------------------------------------------------------------------------
    def _lower_if(self, st: Statement, loc: Loc) -> Stmt:
        cond = self.condition(st.tokens[1:])
        then = self._branch(st, "then") or []
        els = self._branch(st, "else")
        return If(loc, "IF", cond, then, els)

    def _lower_evaluate(self, st: Statement, loc: Loc) -> Stmt:
        subj_toks = _split_also(st.tokens[1:])
        subjects: list[object] = []
        for part in subj_toks:
            if len(part) == 1 and part[0].is_word("TRUE"):
                subjects.append(True)
            elif len(part) == 1 and part[0].is_word("FALSE"):
                subjects.append(False)
            else:
                subjects.append(self._eval_subject(part))
        whens: list[When] = []
        other: list[Stmt] | None = None
        pending: list[Cond] = []
        for b in st.branches:
            if b.kind == "other":
                other = self.block(b.body)
                continue
            # a branch holds one or more WHEN phrases sharing a body
            groups = _split_when(b.tokens)
            conds: list[Cond] = []
            for g in groups:
                objs = _split_also(g)
                if len(objs) != len(subjects):
                    raise LowerError("wrong number of WHEN objects")
                c2: Cond | None = None
                for s, o in zip(subjects, objs, strict=True):
                    c3 = self._eval_test(s, o)
                    c2 = c3 if c2 is None else And(c2, c3)
                assert c2 is not None
                conds.append(c2)
            c1 = conds[0]
            for extra in conds[1:]:
                c1 = Or(c1, extra)
            pending.append(c1)
            whens.append(When(c1, self.block(b.body), b.tokens[0].line if b.tokens else st.line))
        return Evaluate(loc, "EVALUATE", whens, other)

    def _eval_subject(self, toks: list[Token]) -> object:
        """A subject is an expression (value) or a condition."""
        return ("subject", _ExprBuilder(self._cond_tokens(toks)).build_value())

    def _eval_test(self, subj: object, otoks: list[Token]) -> Cond:
        # objects: ANY | TRUE | FALSE | [NOT] partial-expr [THRU expr]
        if len(otoks) == 1 and otoks[0].is_word("ANY"):
            return BoolConst(True)
        s_val: object = None
        if isinstance(subj, tuple):
            s_val = subj[1]
        if len(otoks) == 1 and otoks[0].is_word("TRUE", "FALSE"):
            want = otoks[0].is_word("TRUE")
            if isinstance(subj, bool):
                return BoolConst(want == subj)
            if not _is_bool(s_val):
                raise LowerError("TRUE/FALSE object with a non-condition subject")
            sc = _need_cond(s_val)
            return sc if want else Not(sc)
        thru_idx = next((i for i, t in enumerate(otoks) if t.is_word("THRU", "THROUGH")), None)
        e_toks = otoks if thru_idx is None else otoks[:thru_idx]
        e2_toks = None if thru_idx is None else otoks[thru_idx + 1:]
        items = self._cond_tokens(e_toks)
        negate = False
        if not isinstance(subj, bool) and not _is_bool(s_val):
            if items and items[0][0] == "!":
                negate = True
                items = items[1:]
            if items and items[0][0] in (*_RELS, "9", "A", "L", "U", "P", "N"):
                if e2_toks is not None:
                    raise LowerError("invalid THRU usage")
                if negate:
                    items = [("!", None), *items]
                    negate = False
                items = [("x", s_val), *items]
                return _ExprBuilder(items).build()
        b = _ExprBuilder(items)
        x = b.build_value()
        if isinstance(subj, bool):
            if not _is_bool(x):
                raise LowerError("WHEN object is not a condition for EVALUATE TRUE/FALSE")
            c: Cond = x  # type: ignore[assignment]
            if subj:
                return Not(c) if negate else c
            return c if negate else Not(c)
        if _is_bool(s_val):
            raise LowerError("condition subject with a value object")
        if _is_bool(x):
            raise LowerError("condition object for a value subject")
        if e2_toks is not None:
            y = _ExprBuilder(self._cond_tokens(e2_toks)).build_value()
            if _is_bool(y):
                raise LowerError("invalid THRU operand")
            t: Cond = And(fold_rel("[", x, s_val), fold_rel("[", s_val, y))  # type: ignore[arg-type]
            return Not(t) if negate else t
        if isinstance(x, Ref) and x.item.level == 88:
            raise LowerError("88 level in WHEN")
        return fold_rel("~" if negate else "=", s_val, x)  # type: ignore[arg-type]

    def _lower_perform(self, st: Statement, loc: Loc) -> Stmt:
        c = _Toks(st.tokens[1:])
        inline = bool(st.branches)
        proc: tuple[str, str] | None = None
        if not inline:
            t = c.next()
            first = t.up
            if first not in self.proc_names:
                raise LowerError(f"PERFORM of unknown procedure {first}")
            last = first
            if c.accept("THRU", "THROUGH"):
                last = c.next().up
                if last not in self.proc_names:
                    raise LowerError(f"PERFORM THRU unknown procedure {last}")
            proc = (first, last)
        body = self.block(st.branches[0].body) if inline else None
        p = Perform(loc, "PERFORM", proc, body)
        if c.eof():
            return p
        if c.at("WITH") or c.at("TEST"):
            c.accept("WITH")
            c.expect("TEST")
            if c.accept("AFTER"):
                p.test_after = True
            else:
                c.expect("BEFORE")
        if c.at("VARYING"):
            c.next()
            p.mode = "varying"
            p.varying.append(self._varying(c))
            while c.accept("AFTER"):
                p.varying.append(self._varying(c))
            if not c.eof():
                raise LowerError("unexpected tokens after PERFORM VARYING")
            return p
        if c.at("UNTIL"):
            c.next()
            if c.at("EXIT"):
                raise LowerError("PERFORM UNTIL EXIT")
            p.mode = "until"
            p.until = self.condition(c.toks[c.i:])
            return p
        # PERFORM n TIMES
        times_idx = next((i for i, t in enumerate(c.toks) if t.is_word("TIMES")), None)
        if times_idx is not None and times_idx == len(c.toks) - 1:
            e = self.operand(c)
            if not isinstance(e, (Ref, Lit)):
                raise LowerError("PERFORM TIMES operand")
            _check_numeric_operand(e)
            c.expect("TIMES")
            p.mode = "times"
            p.times = e
            if p.test_after:
                raise LowerError("WITH TEST in PERFORM TIMES")
            return p
        raise LowerError("PERFORM form")

    def _varying(self, c: _Toks) -> Varying:
        var = self._receiving(c)
        if item_category(var.item) != "numeric" or var.refmod is not None:
            raise LowerError("non-numeric PERFORM VARYING identifier")
        c.expect("FROM")
        start = self.operand(c)
        _check_numeric_operand(start)
        c.expect("BY")
        by = self.operand(c)
        _check_numeric_operand(by)
        c.expect("UNTIL")
        rest: list[Token] = []
        while not c.eof() and not c.at("AFTER"):
            rest.append(c.next())
        return Varying(var, start, by, self.condition(rest))

    def _lower_set(self, st: Statement, loc: Loc) -> Stmt:
        toks = st.tokens[1:]
        if len(toks) >= 2 and toks[-1].is_word("TRUE") and toks[-2].is_word("TO"):
            c = _Toks(toks[:-2])
            conds: list[CondName] = []
            while not c.eof():
                t = c.peek()
                assert t is not None
                if t.kind != WORD or t.up not in self.cond_names:
                    raise LowerError("SET ... TO TRUE on a non-condition-name")
                conds.append(self._cond_name(c))
            for cn in conds:
                lo, _hi = cn.cond.values_88[0]
                if lo.kind == "all":
                    raise LowerError("SET TO TRUE of an 88 with ALL value")
                cat = item_category(cn.parent.item)
                if cat == "numeric-edited" or cat == "alphanumeric-edited":
                    raise LowerError("SET TO TRUE on an edited item")
            return SetCond(loc, "SET", conds)
        if len(toks) >= 2 and toks[-1].is_word("FALSE"):
            raise LowerError("SET TO FALSE")
        raise LowerError("SET (index/pointer/switch forms)")

    def _lower_initialize(self, st: Statement, loc: Loc) -> Stmt:
        c = _Toks(st.tokens[1:])
        refs: list[Ref] = []
        while not c.eof():
            if c.at("REPLACING", "WITH", "TO", "ALL", "THEN", "DEFAULT", "VALUE", "FILLER"):
                raise LowerError(f"INITIALIZE {c.peek().up} phrase")  # type: ignore[union-attr]
            r = self._receiving(c)
            if r.refmod is not None:
                raise LowerError("INITIALIZE of a reference-modified item")
            for it in r.item.walk():
                if it.pic is not None and it.pic.category == "alphanumeric-edited":
                    raise LowerError("INITIALIZE of alphanumeric-edited items")
            refs.append(r)
        return Initialize(loc, "INITIALIZE", refs)

    def _lower_continue(self, st: Statement, loc: Loc) -> Stmt:
        if len(st.tokens) > 1:
            raise LowerError("CONTINUE AFTER")
        return Continue(loc, "CONTINUE")

    def _lower_exit(self, st: Statement, loc: Loc) -> Stmt:
        words = [t.up for t in st.tokens[1:]]
        if not words:
            return ExitStmt(loc, "EXIT", "plain")
        if words == ["PARAGRAPH"]:
            return ExitStmt(loc, "EXIT", "paragraph")
        if words == ["SECTION"]:
            return ExitStmt(loc, "EXIT", "section")
        if words == ["PERFORM"]:
            return ExitStmt(loc, "EXIT", "perform")
        if words == ["PERFORM", "CYCLE"]:
            return ExitStmt(loc, "EXIT", "perform-cycle")
        if words == ["PROGRAM"]:
            return ExitStmt(loc, "EXIT", "program")
        raise LowerError("EXIT " + " ".join(words))

    def _lower_stop(self, st: Statement, loc: Loc) -> Stmt:
        words = [t.up for t in st.tokens[1:]]
        if words == ["RUN"]:
            return StopRun(loc, "STOP")
        raise LowerError("STOP " + " ".join(words))

    def _lower_goback(self, st: Statement, loc: Loc) -> Stmt:
        if len(st.tokens) > 1:
            raise LowerError("GOBACK RETURNING")
        return GoBack(loc, "GOBACK")

    def _lower_go(self, st: Statement, loc: Loc) -> Stmt:
        c = _Toks(st.tokens[1:])
        c.accept("TO")
        if c.eof():
            raise LowerError("GO TO without target (ALTER)")
        t = c.next()
        if not c.eof():
            raise LowerError("GO TO DEPENDING ON")
        if t.up not in self.proc_names:
            raise LowerError(f"GO TO unknown procedure {t.up}")
        return GoTo(loc, "GO", t.up)

    # ---- I/O -----------------------------------------------------------------------------------
    def _lower_accept(self, st: Statement, loc: Loc) -> Stmt:
        self._only_branches(st, ("exception", "not_exception"))
        if st.branches:
            raise LowerError("ACCEPT ON EXCEPTION")
        c = _Toks(st.tokens[1:])
        if c.at("OMITTED"):
            raise LowerError("ACCEPT OMITTED")
        target = self._receiving(c)
        if not c.eof():
            if c.accept("FROM"):
                src = c.next().up
                if src not in ("SYSIN", "STDIN", "CONSOLE", "KEYBOARD") or not c.eof():
                    raise LowerError(f"ACCEPT FROM {src}")
            else:
                raise LowerError("ACCEPT with screen/AT phrases")
        cat = item_category(target.item) if target.refmod is None else "alphanumeric"
        if cat in ("numeric-edited", "alphanumeric-edited"):
            raise LowerError("ACCEPT into an edited item")
        if target.item is self.return_code:
            raise LowerError("ACCEPT RETURN-CODE")
        return Accept(loc, "ACCEPT", target, "stdin")

    def _lower_display(self, st: Statement, loc: Loc) -> Stmt:
        self._only_branches(st, ())
        c = _Toks(st.tokens[1:])
        ops: list[Expr] = []
        upon = "SYSOUT"
        advancing = True
        while not c.eof():
            if c.at("UPON"):
                c.next()
                dev = c.next().up
                if dev in ("SYSOUT", "STDOUT"):
                    upon = "SYSOUT"
                elif dev in ("SYSERR", "STDERR"):
                    upon = "SYSERR"
                else:
                    raise LowerError(f"DISPLAY UPON {dev}")
                continue
            if c.at("WITH", "NO"):
                c.accept("WITH")
                c.expect("NO")
                c.expect("ADVANCING")
                advancing = False
                continue
            if c.at("AT", "LINE", "COLUMN", "COL", "POSITION", "ERASE", "CONVERSION", "BEFORE", "AFTER"):
                raise LowerError(f"DISPLAY {c.peek().up} phrase")  # type: ignore[union-attr]
            e = self.operand(c)
            if isinstance(e, Fig) and e.name == "ALL":
                raise LowerError("DISPLAY ALL literal")
            if isinstance(e, Ref) and e.refmod is None and item_category(e.item) == "numeric" \
                    and e.item.usage == "COMP-5":
                pass
            ops.append(e)
        if not ops:
            raise LowerError("DISPLAY without operands")
        return Display(loc, "DISPLAY", ops, upon, advancing)

    def _file_name(self, t: Token) -> str:
        name = t.up
        sel = self.prog.select(name)
        if sel is None:
            raise LowerError(f"unknown file {name}")
        if sel.organization not in ("SEQUENTIAL", "LINE SEQUENTIAL"):
            raise LowerError(f"{sel.organization} file {name}")
        if sel.access != "SEQUENTIAL":
            raise LowerError(f"ACCESS {sel.access} file {name}")
        if sel.assign_kind not in ("literal", "name"):
            raise LowerError(f"file {name} with ASSIGN {sel.assign_kind}")
        fd = self.prog.fd(name)
        if fd is None or not fd.records:
            raise LowerError(f"file {name} without FD record")
        if fd.record_varying:
            raise LowerError(f"RECORD VARYING file {name}")
        for r in fd.records:
            self._check_item(r, t)
        return name

    def _lower_open(self, st: Statement, loc: Loc) -> Stmt:
        c = _Toks(st.tokens[1:])
        entries: list[tuple[str, str]] = []
        mode = ""
        while not c.eof():
            if c.at("INPUT", "OUTPUT", "EXTEND", "I-O"):
                mode = c.next().up
                continue
            if c.at("WITH", "NO", "REWIND", "LOCK", "SHARING", "ALL", "OTHER", "READ", "ONLY"):
                raise LowerError(f"OPEN {c.peek().up} phrase")  # type: ignore[union-attr]
            if not mode:
                raise LowerError("OPEN without mode")
            if mode == "I-O":
                raise LowerError("OPEN I-O")
            entries.append((mode, self._file_name(c.next())))
        if not entries:
            raise LowerError("OPEN without files")
        return Open(loc, "OPEN", entries)

    def _lower_close(self, st: Statement, loc: Loc) -> Stmt:
        c = _Toks(st.tokens[1:])
        files: list[str] = []
        while not c.eof():
            if c.at("WITH", "LOCK", "NO", "REWIND", "UNIT", "REEL", "FOR", "REMOVAL"):
                raise LowerError(f"CLOSE {c.peek().up} phrase")  # type: ignore[union-attr]
            files.append(self._file_name(c.next()))
        return Close(loc, "CLOSE", files)

    def _lower_read(self, st: Statement, loc: Loc) -> Stmt:
        self._only_branches(st, ("at_end", "not_at_end"))
        c = _Toks(st.tokens[1:])
        name = self._file_name(c.next())
        c.accept("NEXT")
        c.accept("RECORD")
        into: Ref | None = None
        if c.accept("INTO"):
            into = self._receiving(c)
        if not c.eof():
            raise LowerError(f"READ {c.peek().up} phrase")  # type: ignore[union-attr]
        return Read(loc, "READ", name, into, self._branch(st, "at_end"), self._branch(st, "not_at_end"))

    def _lower_write(self, st: Statement, loc: Loc) -> Stmt:
        self._only_branches(st, ())
        c = _Toks(st.tokens[1:])
        rec = self._receiving(c)
        if rec.subs or rec.refmod is not None:
            raise LowerError("WRITE of a subscripted record")
        fdname = rec.item.fd
        if fdname is None or rec.item.level != 1:
            raise LowerError(f"WRITE of {rec} which is not a file record")
        src: Expr | None = None
        if c.accept("FROM"):
            src = self.operand(c)
            if isinstance(src, Ref):
                pass
            else:
                raise LowerError("WRITE FROM literal")
        if not c.eof():
            raise LowerError(f"WRITE {c.peek().up} phrase")  # type: ignore[union-attr]
        name = fdname
        sel = self.prog.select(name)
        if sel is None:
            raise LowerError(f"no SELECT for FD {name}")
        self._file_name(Token(WORD, name, st.file, st.line, 0))
        return Write(loc, "WRITE", rec, name, src)


def _check_edited_pic(pic: PicInfo) -> None:
    body = pic.expanded.upper()
    for tail in ("CR", "DB"):
        if body.endswith(tail):
            body = body[:-2]
    allowed = set("9Z*+-.,VB0/$")
    if not set(body) <= allowed:
        raise LowerError(f"numeric-edited PICTURE {pic.raw}")
    if "P" in body:
        raise LowerError(f"numeric-edited PICTURE {pic.raw} with P")


def _binary_list(srcs: list[Expr], op: str) -> Expr:
    """cobc cb_build_binary_list: operand lists fold left to right, ((a op b) op c)."""
    acc = srcs[0]
    for s in srcs[1:]:
        acc = fold(Bin(op, acc, s))
    return acc


def _sum(srcs: list[Expr]) -> Expr:
    return _binary_list(srcs, "+")


def _split_also(toks: list[Token]) -> list[list[Token]]:
    parts: list[list[Token]] = [[]]
    depth = 0
    for t in toks:
        if t.kind == OP and t.text == "(":
            depth += 1
        elif t.kind == OP and t.text == ")":
            depth -= 1
        if depth == 0 and t.is_word("ALSO"):
            parts.append([])
        else:
            parts[-1].append(t)
    return parts


def _split_when(toks: list[Token]) -> list[list[Token]]:
    groups: list[list[Token]] = []
    for t in toks:
        if t.is_word("WHEN"):
            groups.append([])
        elif groups:
            groups[-1].append(t)
    return groups


# ---------------------------------------------------------------------------------------------
# program lowering and eligibility
# ---------------------------------------------------------------------------------------------
def lower_program(prog: Program) -> IrProgram:
    lw = StatementLowerer(prog)
    paragraphs: list[IrParagraph] = []
    for p in prog.paragraphs:
        body = lw.block(p.statements)
        _mark_next_sentence(p, body)
        paragraphs.append(IrParagraph(p.name, p.section, Loc(p.file, p.line), p.end_line, body))
    ir = IrProgram(prog, paragraphs, list(prog.sections), lw.return_code)
    ir.issues = _program_issues(prog, lw)
    _compute_eligibility(ir)
    return ir


def _mark_next_sentence(p: Paragraph, body: list[Stmt]) -> None:
    """NEXT SENTENCE is lowered as Unsupported (its target is the end of the sentence)."""
    del p, body


def _program_issues(prog: Program, lw: StatementLowerer) -> list[str]:
    from verifier.cobol.analysis import out_of_scope

    issues = [f"program {r}" for r in out_of_scope(prog)]
    if prog.parse_errors:
        issues.append(f"parse errors: {prog.parse_errors[0]}")
    if prog.linkage or prog.using:
        issues.append("LINKAGE SECTION / PROCEDURE DIVISION USING")
    if prog.local_storage:
        issues.append("LOCAL-STORAGE SECTION")
    if any(f.startswith("DECLARATIVES") for f in prog.features):
        issues.append("DECLARATIVES")
    if prog.special_names:
        issues.append(f"SPECIAL-NAMES {prog.special_names[0]}")
    if any(f == "multiple programs in one source" or f == "user-defined FUNCTION" for f in prog.features):
        issues.append("nested/multiple programs")
    for rec in prog.records():
        for it in rec.walk():
            if it.depending_on:
                issues.append(f"OCCURS DEPENDING ON ({it.name})")
            if it.is_elementary and it.usage not in _SUPPORTED_USAGES:
                issues.append(f"USAGE {it.usage} ({it.name})")
            if it.external:
                issues.append(f"EXTERNAL ({it.name})")
            if it.renames is not None or any(c.level == 66 for c in it.conditions):
                issues.append(f"RENAMES ({it.name})")
            if it.is_elementary and it.pic is not None and it.pic.category == "numeric" and it.pic.digits > 18 \
                    and it.usage != "DISPLAY":
                issues.append(f"binary/packed item with more than 18 digits ({it.name})")
            if it.issues:
                issues.append(f"data item {it.name}: {it.issues[0]}")
            if it.is_elementary and it.value is not None and not _value_ok(it):
                issues.append(f"VALUE clause of {it.name} ({it.value})")
            if it.is_group and it.value is not None and it.value.kind not in ("str", "fig", "all"):
                issues.append(f"VALUE clause of group {it.name}")
            if it.sync:
                issues.append(f"SYNCHRONIZED ({it.name})")
            if it.blank_when_zero:
                issues.append(f"BLANK WHEN ZERO ({it.name})")
            if it.pic is not None and it.pic.category == "numeric-edited":
                try:
                    _check_edited_pic(it.pic)
                except LowerError as exc:
                    issues.append(exc.construct)
            if it.pic is not None and it.pic.category == "alphanumeric-edited":
                issues.append(f"alphanumeric-edited item {it.name}")
    for sel in prog.selects:
        if sel.organization not in ("SEQUENTIAL", "LINE SEQUENTIAL"):
            issues.append(f"{sel.organization} file {sel.name}")
        if sel.optional:
            issues.append(f"OPTIONAL file {sel.name}")
    for fd in prog.fds:
        if fd.kind != "FD":
            issues.append(f"{fd.kind} {fd.name}")
    return sorted(set(issues), key=issues.index)


def _value_ok(it: DataItem) -> bool:
    v = it.value
    assert v is not None
    cat = item_category(it)
    if v.kind == "num":
        return cat in ("numeric", "numeric-edited", "alphanumeric") if cat != "alphanumeric" else False
    if v.kind == "str":
        return cat in ("alphanumeric", "alphabetic", "numeric-edited")
    if v.kind == "fig":
        if cat == "numeric":
            return v.text == "ZERO"
        return v.text in ("SPACE", "ZERO", "HIGH-VALUE", "LOW-VALUE", "QUOTE")
    if v.kind == "all":
        return cat in ("alphanumeric", "alphabetic")
    return False


def _direct_targets(ir: IrProgram, s: Stmt) -> list[str]:
    if isinstance(s, Perform) and s.proc is not None:
        return expand_range(ir, s.proc[0], s.proc[1])
    return []


def expand_range(ir: IrProgram, first: str, last: str) -> list[str]:
    """Paragraph names covered by PERFORM first [THRU last] (sections expand to their paragraphs)."""
    names = [p.name for p in ir.paragraphs]
    lo_name = first
    if first in ir.sections:
        sec = ir.section_paragraphs(first)
        if not sec:
            return []
        lo_name = sec[0].name
    hi_name = last
    if last in ir.sections:
        sec = ir.section_paragraphs(last)
        if not sec:
            return []
        hi_name = sec[-1].name
    if lo_name not in names or hi_name not in names:
        return []
    a, b = names.index(lo_name), names.index(hi_name)
    if b < a:
        return []
    return names[a: b + 1]


def perform_closure(ir: IrProgram, name: str) -> list[str]:
    """`name` plus every paragraph it reaches through PERFORM (transitively), in discovery order."""
    seen: list[str] = []
    todo = [name]
    while todo:
        n = todo.pop(0)
        if n in seen:
            continue
        p = ir.paragraph(n)
        if p is None:
            continue
        seen.append(n)
        for s in p.walk():
            for t in _direct_targets(ir, s):
                if t not in seen:
                    todo.append(t)
    return seen


def _local_reason(ir: IrProgram, p: IrParagraph) -> str | None:
    for s in p.walk():
        if isinstance(s, Unsupported):
            return s.reason
        if isinstance(s, IO_VERBS):
            return f"I/O statement {s.verb} at {s.loc.file}:{s.loc.line}"
        if isinstance(s, GoTo):
            return f"GO TO at {s.loc.file}:{s.loc.line}"
        if isinstance(s, Perform) and s.thru:
            return f"PERFORM THRU at {s.loc.file}:{s.loc.line}"
        if isinstance(s, Perform) and s.proc is not None and s.proc[0] in ir.sections:
            return f"PERFORM of a section at {s.loc.file}:{s.loc.line}"
        if isinstance(s, ExitStmt) and s.kind in ("section", "program"):
            return f"EXIT {s.kind.upper()} at {s.loc.file}:{s.loc.line}"
    return None


def _compute_eligibility(ir: IrProgram) -> None:
    prog_reason = ir.issues[0] if ir.issues else None
    local = {p.name: _local_reason(ir, p) for p in ir.paragraphs}
    for p in ir.paragraphs:
        if prog_reason is not None:
            p.t2_eligibility = prog_reason
            continue
        reason = None
        for n in perform_closure(ir, p.name):
            r = local.get(n)
            if r is not None:
                reason = r if n == p.name else f"performs {n}: {r}"
                break
        p.t2_eligibility = reason


def eligibility_report(ir: IrProgram) -> dict[str, str | None]:
    return {p.name: p.t2_eligibility for p in ir.paragraphs}


__all__ = [
    "Accept",
    "And",
    "ArithAssign",
    "ArithOp",
    "Bin",
    "BoolConst",
    "Branch",
    "ClassTest",
    "Close",
    "Cond",
    "CondName",
    "Continue",
    "Display",
    "DivRem",
    "Evaluate",
    "ExitStmt",
    "Expr",
    "Fig",
    "GoBack",
    "GoTo",
    "If",
    "Initialize",
    "IrParagraph",
    "IrProgram",
    "Lit",
    "Loc",
    "Move",
    "Not",
    "Open",
    "Or",
    "Perform",
    "Read",
    "Ref",
    "Rel",
    "SetCond",
    "Stmt",
    "StopRun",
    "StrLit",
    "Target",
    "Unsupported",
    "Varying",
    "When",
    "Write",
    "eligibility_report",
    "expand_range",
    "lower_program",
    "perform_closure",
]
