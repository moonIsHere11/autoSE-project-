"""Stage E: read/write sets per statement, rolled up to paragraphs.

Statements come from the verifier's typed IR (`ir.lower_program`), so names resolve exactly as the
checker resolves them. A statement the IR does not lower (`Unsupported`, e.g. INSPECT, CALL,
FUNCTION calls) falls back to the syntax tree: every resolvable identifier in it (and in nested
statements) is read, and `analysis.written_names` gives the writes. That fallback over-approximates
reads, which is safe (measured by E6), and is counted separately in coverage.

Every reference is expanded through the storage model (`storage.Storage.touched`): a group or
REDEFINES reference reads/writes every elementary item sharing its bytes. A write that does not
cover a whole item (subscripted, reference-modified, or partial overlap) also reads that item,
because the bytes it does not write pass through.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from phase0.stages.storage import Storage, occurs_chain
from verifier.cobol import ir as I
from verifier.cobol.analysis import parse_ident, written_names
from verifier.cobol.datadiv import DataItem
from verifier.cobol.lexer import WORD
from verifier.cobol.syntax import Program, Statement


@dataclass
class Effects:
    reads: set[int] = field(default_factory=set)  # id(DataItem) of elementary items
    writes: set[int] = field(default_factory=set)
    items: dict[int, DataItem] = field(default_factory=dict)
    fallback_lines: set[int] = field(default_factory=set)

    def merge(self, other: Effects) -> None:
        self.reads |= other.reads
        self.writes |= other.writes
        self.items.update(other.items)
        self.fallback_lines |= other.fallback_lines


# statements whose write set the syntax cannot bound: every operand may be written
OPAQUE_VERBS = frozenset({"CALL", "EXEC", "SORT", "MERGE", "RETURN", "RELEASE", "INVOKE", "XML", "JSON"})


class FlowAnalyser:
    def __init__(self, prog: Program, storage: Storage, return_code: DataItem) -> None:
        self.prog = prog
        self.storage = storage
        self.return_code = return_code

    # ---- primitive effects ---------------------------------------------------------------
    def _touch(self, fx: Effects, item: DataItem) -> list[tuple[DataItem, bool]]:
        if item is self.return_code:
            return [(item, True)]
        return self.storage.touched(item)

    def read_item(self, fx: Effects, item: DataItem) -> None:
        for other, _full in self._touch(fx, item):
            fx.reads.add(id(other))
            fx.items[id(other)] = other

    def write_item(self, fx: Effects, item: DataItem, partial: bool) -> None:
        for other, full in self._touch(fx, item):
            fx.writes.add(id(other))
            fx.items[id(other)] = other
            if partial or not full:
                fx.reads.add(id(other))

    def read_ref(self, fx: Effects, ref: I.Ref) -> None:
        self.read_item(fx, ref.item)
        for s in ref.subs:
            self.read_expr(fx, s)
        if ref.refmod is not None:
            self.read_expr(fx, ref.refmod[0])
            if ref.refmod[1] is not None:
                self.read_expr(fx, ref.refmod[1])

    def write_ref(self, fx: Effects, ref: I.Ref) -> None:
        partial = bool(ref.subs) or ref.refmod is not None or bool(occurs_chain(ref.item))
        self.write_item(fx, ref.item, partial)
        for s in ref.subs:
            self.read_expr(fx, s)
        if ref.refmod is not None:
            self.read_expr(fx, ref.refmod[0])
            if ref.refmod[1] is not None:
                self.read_expr(fx, ref.refmod[1])

    def read_expr(self, fx: Effects, e: I.Expr) -> None:
        if isinstance(e, I.Ref):
            self.read_ref(fx, e)
        elif isinstance(e, I.Bin):
            self.read_expr(fx, e.left)
            self.read_expr(fx, e.right)

    def read_cond(self, fx: Effects, c: I.Cond) -> None:
        if isinstance(c, I.Rel):
            self.read_expr(fx, c.left)
            self.read_expr(fx, c.right)
        elif isinstance(c, I.ClassTest):
            self.read_expr(fx, c.operand)
        elif isinstance(c, I.CondName):
            self.read_ref(fx, c.parent)
        elif isinstance(c, I.Not):
            self.read_cond(fx, c.cond)
        elif isinstance(c, I.And | I.Or):
            self.read_cond(fx, c.left)
            self.read_cond(fx, c.right)

    def file_status(self, fx: Effects, file_name: str) -> None:
        sel = self.prog.select(file_name)
        if sel is None or sel.file_status is None:
            return
        item = self.prog.resolve(sel.file_status)
        if item is not None:
            self.write_item(fx, item, False)

    def fd_records(self, file_name: str) -> list[DataItem]:
        fd = self.prog.fd(file_name)
        if fd is None:
            return []
        return list(fd.records)

    # ---- statements ----------------------------------------------------------------------
    def block(self, stmts: Iterable[I.Stmt], syntax: dict[tuple[str, int, str], Statement]) -> Effects:
        fx = Effects()
        for s in stmts:
            fx.merge(self.stmt(s, syntax))
        return fx

    def stmt(self, s: I.Stmt, syntax: dict[tuple[str, int, str], Statement]) -> Effects:
        fx = Effects()
        if isinstance(s, I.Unsupported):
            st = syntax.get((s.loc.file, s.loc.line, s.verb))
            if st is not None:
                return self.syntax_effects(st)
            fx.fallback_lines.add(s.loc.line)
            return fx
        self.direct(fx, s)
        for branch in s.children():
            fx.merge(self.block(branch, syntax))
        return fx

    def direct(self, fx: Effects, s: I.Stmt) -> None:
        """Effects of the statement itself (nested statement lists are walked by `stmt`)."""
        if isinstance(s, I.Move):
            self.read_expr(fx, s.src)
            for d in s.dsts:
                self.write_ref(fx, d)
        elif isinstance(s, I.ArithOp):
            self.read_expr(fx, s.src)
            for t in s.targets:
                self.read_ref(fx, t.ref)
                self.write_ref(fx, t.ref)
        elif isinstance(s, I.ArithAssign):
            self.read_expr(fx, s.expr)
            for t in s.targets:
                if s.op is not None:
                    self.read_ref(fx, t.ref)
                self.write_ref(fx, t.ref)
        elif isinstance(s, I.DivRem):
            self.read_expr(fx, s.dividend)
            self.read_expr(fx, s.divisor)
            self.write_ref(fx, s.quotient.ref)
            self.write_ref(fx, s.remainder)
        elif isinstance(s, I.If):
            self.read_cond(fx, s.cond)
        elif isinstance(s, I.Evaluate):
            for w in s.whens:
                self.read_cond(fx, w.cond)
        elif isinstance(s, I.Perform):
            self.perform(fx, s)
        elif isinstance(s, I.SetCond):
            for c in s.conds:
                self.write_ref(fx, c.parent)
        elif isinstance(s, I.Initialize):
            for ref in s.targets:
                self.write_ref(fx, ref)
        else:
            self.io(fx, s)

    def perform(self, fx: Effects, s: I.Perform) -> None:
        if s.times is not None:
            self.read_expr(fx, s.times)
        if s.until is not None:
            self.read_cond(fx, s.until)
        for v in s.varying:
            self.read_expr(fx, v.start)
            self.read_expr(fx, v.by)
            self.read_cond(fx, v.until)
            self.read_ref(fx, v.var)
            self.write_ref(fx, v.var)

    def io(self, fx: Effects, s: I.Stmt) -> None:
        if isinstance(s, I.Accept):
            self.write_ref(fx, s.target)
        elif isinstance(s, I.Display):
            for e in s.operands:
                self.read_expr(fx, e)
        elif isinstance(s, I.Open):
            for _mode, name in s.entries:
                self.file_status(fx, name)
        elif isinstance(s, I.Close):
            for name in s.files:
                self.file_status(fx, name)
        elif isinstance(s, I.Read):
            # a successful READ replaces the whole record area; at end of file it is untouched
            for rec in self.fd_records(s.file):
                self.write_item(fx, rec, False)
            if s.into is not None:
                self.write_ref(fx, s.into)
            self.file_status(fx, s.file)
        elif isinstance(s, I.Write):
            if s.src is not None:
                self.read_expr(fx, s.src)
                self.write_ref(fx, s.record)
            self.read_ref(fx, s.record)
            self.file_status(fx, s.file)

    # ---- syntax fallback -----------------------------------------------------------------
    def syntax_effects(self, st: Statement) -> Effects:
        fx = Effects()
        for sub in st.walk():
            fx.fallback_lines.add(sub.line)
            for item in self.idents(sub):
                self.read_item(fx, item)
            for name in written_names(self.prog, sub):
                for item in self.prog.find_items(name):
                    self.write_item(fx, item, True)
            if sub.verb in OPAQUE_VERBS:
                for item in self.idents(sub):
                    self.write_item(fx, item, True)
        return fx

    def idents(self, st: Statement) -> list[DataItem]:
        toks = st.tokens
        out: list[DataItem] = []
        i = 0
        while i < len(toks):
            if toks[i].kind != WORD:
                i += 1
                continue
            ident = parse_ident(toks, i)
            if ident is None:
                i += 1
                continue
            item = self.prog.resolve(ident.name, ident.qualifiers)
            if item is not None:
                out.append(item)
            cond = self.prog.condition_names().get(ident.name)
            if item is None and cond is not None and cond.parent is not None:
                out.append(cond.parent)
            i = max(ident.end, i + 1)
        return out


def syntax_index(statements: Iterable[Statement]) -> dict[tuple[str, int, str], Statement]:
    out: dict[tuple[str, int, str], Statement] = {}
    for top in statements:
        for st in top.walk():
            out.setdefault((st.file, st.line, st.verb), st)
    return out
