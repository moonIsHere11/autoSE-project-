"""JML contract generation for Java T3 (spec section 6, T3; spike S3 "contract-generation rules").

Contracts come **only from the COBOL side** (IR + PICs), expressed over the candidate's mapped fields:

* `requires`  — every numeric field the unit touches holds a value of its PIC (integer-scaled range);
* `ensures`   — every numeric field the unit writes holds a value of its PIC afterwards;
* `ensures`   — for loop-free units, the exact functional postcondition obtained by symbolically
  evaluating the IR (`\\old(...)` of the inputs; ROUNDED / truncation / sign / size-error handling as
  integer expressions);
* `assignable` — the COBOL write set (mapped fields) plus the candidate's own non-COBOL fields.

Division and exponentiation are not given functional postconditions (cobc's intermediate precision is
not expressed in JML here); such units still get range + frame contracts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from verifier.cobol import ir
from verifier.cobol.datadiv import DataItem
from verifier.langpacks.java.emit import EmitUnsupported, RefField, classify_item


class ContractUnsupported(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class FieldMap:
    cobol: str
    rf: RefField
    jfield: str  # candidate field name
    jtype: str


@dataclass
class Contract:
    requires: list[str]
    ensures: list[str]
    assignable: list[str]
    functional: bool
    notes: list[str] = field(default_factory=list)

    def jml(self, indent: str = "    ") -> str:
        lines = [f"{indent}/*@ private normal_behavior"]
        for r in self.requires or ["true"]:
            lines.append(f"{indent}  @   requires {r};")
        frame = ", ".join(self.assignable) if self.assignable else "\\nothing"
        lines.append(f"{indent}  @   assignable {frame};")
        for e in self.ensures:
            lines.append(f"{indent}  @   ensures {e};")
        lines.append(f"{indent}  @*/")
        return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
def write_set(irp: ir.IrProgram, closure: list[str]) -> set[str]:
    out: set[str] = set()

    def items(r: ir.Ref) -> list[str]:
        if r.item.is_group:
            return [i.name for i in r.item.walk() if i.is_elementary and not i.is_filler]
        return [r.item.name]

    for name in closure:
        p = irp.paragraph(name)
        if p is None:
            continue
        for s in p.walk():
            if isinstance(s, ir.Move):
                for d in s.dsts:
                    out.update(items(d))
            elif isinstance(s, ir.ArithAssign | ir.ArithOp):
                for t in s.targets:
                    out.update(items(t.ref))
            elif isinstance(s, ir.DivRem):
                out.update(items(s.quotient.ref))
                out.update(items(s.remainder))
            elif isinstance(s, ir.Initialize):
                for r in s.targets:
                    out.update(items(r))
            elif isinstance(s, ir.SetCond):
                for c in s.conds:
                    out.update(items(c.parent))
            elif isinstance(s, ir.Perform):
                for v in s.varying:
                    out.update(items(v.var))
    return out


def touched(irp: ir.IrProgram, closure: list[str]) -> set[str]:
    """Every elementary item referenced (read or written) in the closure."""
    out: set[str] = set()

    def visit(x: object) -> None:
        if isinstance(x, ir.Ref):
            if x.item.is_group:
                out.update(i.name for i in x.item.walk() if i.is_elementary and not i.is_filler)
            else:
                out.add(x.item.name)
            for sub in x.subs:
                visit(sub)
        elif isinstance(x, ir.CondName):
            visit(x.parent)
        elif isinstance(x, list):
            for y in x:
                visit(y)
        elif isinstance(x, tuple):
            for y in x:
                visit(y)
        elif hasattr(x, "__dataclass_fields__") and not isinstance(x, DataItem):
            for k in x.__dataclass_fields__:  # type: ignore[attr-defined]
                if k in ("loc", "item"):
                    continue
                visit(getattr(x, k))

    for name in closure:
        p = irp.paragraph(name)
        if p is not None:
            visit(p.body)
    return out


def _range(fm: FieldMap, old: bool = False) -> str:
    lim = 10**fm.rf.digits - 1
    v = f"\\old(this.{fm.jfield})" if old else f"this.{fm.jfield}"
    lo = -lim if fm.rf.signed else 0
    return f"{lo}L <= {v} && {v} <= {lim}L"


# ---------------------------------------------------------------------------------------------
class SymEval:
    """Symbolic execution of a loop-free IR closure into JML expressions over \\old(fields)."""

    def __init__(self, irp: ir.IrProgram, fmap: dict[str, FieldMap], closure: list[str]) -> None:
        self.irp, self.fmap, self.closure = irp, fmap, closure
        self.env: dict[str, str] = {}

    def val(self, name: str) -> str:
        if name in self.env:
            return self.env[name]
        fm = self.fmap.get(name)
        if fm is None:
            raise ContractUnsupported(f"{name} is not mapped to a candidate field")
        return f"\\old(this.{fm.jfield})"

    def num(self, e: ir.Expr) -> tuple[str, int]:
        if isinstance(e, ir.Lit):
            return f"({e.value}L)", e.scale
        if isinstance(e, ir.Fig) and e.name == "ZERO":
            return "0L", 0
        if isinstance(e, ir.Ref):
            if e.subs or e.refmod:
                raise ContractUnsupported("subscripts/reference modification in a functional postcondition")
            fm = self.fmap.get(e.item.name)
            if fm is None or fm.rf.kind != "num":
                raise ContractUnsupported(f"{e.item.name} is not a mapped numeric field")
            return self.val(e.item.name), fm.rf.scale
        if isinstance(e, ir.Bin) and e.op in ("+", "-", "*"):
            a, sa = self.num(e.left)
            b, sb = self.num(e.right)
            if e.op == "*":
                return f"({a} * {b})", sa + sb
            s = max(sa, sb)
            return f"({_scale(a, s - sa)} {e.op} {_scale(b, s - sb)})", s
        raise ContractUnsupported(f"expression {e} (division/exponentiation) has no functional postcondition")

    def store(self, fm: FieldMap, value: str, vscale: int, rounded: bool) -> tuple[str, str]:
        """(stored value expression, overflow condition) for assigning value@vscale to fm."""
        ts = fm.rf.scale
        lim = 10**fm.rf.digits
        c = _cint(value)
        if c is not None:  # constant folding with Java semantics (truncating division)
            if ts >= vscale:
                cv = c * 10 ** (ts - vscale)
            else:
                d = 10 ** (vscale - ts)
                adj = (d // 2) * (-1 if c < 0 else 1) if rounded else 0
                cv = _jdiv(c + adj, d)
            return f"({cv}L)", ("true" if abs(cv) >= lim else "false")
        if ts >= vscale:
            v = _scale(value, ts - vscale)
        else:
            d = 10 ** (vscale - ts)
            if rounded:
                h = d // 2
                v = f"(({value}) < 0 ? (({value}) - {h}L) / {d}L : (({value}) + {h}L) / {d}L)"
            else:
                v = f"(({value}) / {d}L)"
        ovf = f"(({v}) >= {lim}L || ({v}) <= -{lim}L)"
        return v, ovf

    def finish(self, fm: FieldMap, v: str) -> str:
        lim = 10**fm.rf.digits
        c = _cint(v)
        if c is not None:
            t_c = c - _jdiv(c, lim) * lim
            return f"({t_c if fm.rf.signed else abs(t_c)}L)"
        t = f"(({v}) % {lim}L)"
        return t if fm.rf.signed else f"(({t}) < 0 ? -({t}) : ({t}))"

    def cond(self, c: ir.Cond) -> str:
        if isinstance(c, ir.BoolConst):
            return "true" if c.value else "false"
        if isinstance(c, ir.Not):
            return f"!({self.cond(c.cond)})"
        if isinstance(c, ir.And):
            return f"({self.cond(c.left)} && {self.cond(c.right)})"
        if isinstance(c, ir.Or):
            return f"({self.cond(c.left)} || {self.cond(c.right)})"
        if isinstance(c, ir.Rel):
            op = {"=": "==", "~": "!=", "<": "<", ">": ">", "[": "<=", "]": ">="}[c.op]
            a, sa = self.num(c.left)
            b, sb = self.num(c.right)
            s = max(sa, sb)
            return f"({_scale(a, s - sa)} {op} {_scale(b, s - sb)})"
        if isinstance(c, ir.CondName):
            fm = self.fmap.get(c.parent.item.name)
            if fm is None or fm.rf.kind != "num" or c.parent.subs:
                raise ContractUnsupported(f"88-level {c.cond.name} on a non-numeric or subscripted item")
            v = self.val(c.parent.item.name)
            tests = []
            for lo, hi in c.cond.values_88:
                lo_t = _lit_scaled(lo.text, fm.rf.scale)
                if hi is None:
                    tests.append(f"({v} == {lo_t}L)")
                else:
                    tests.append(f"({lo_t}L <= {v} && {v} <= {_lit_scaled(hi.text, fm.rf.scale)}L)")
            return "(" + " || ".join(tests or ["false"]) + ")"
        raise ContractUnsupported(f"condition {c} in a functional postcondition")

    def block(self, stmts: list[ir.Stmt] | None) -> None:
        for s in stmts or []:
            self.stmt(s)

    def branch(self, c: str, then: list[ir.Stmt] | None, els: list[ir.Stmt] | None) -> None:
        base = dict(self.env)
        self.block(then)
        t_env = self.env
        self.env = dict(base)
        self.block(els)
        e_env = self.env
        merged = {}
        for k in set(t_env) | set(e_env):
            a = t_env.get(k, base.get(k) or self.val_old(k))
            b = e_env.get(k, base.get(k) or self.val_old(k))
            merged[k] = a if a == b else f"({c} ? {a} : {b})"
        self.env = merged

    def val_old(self, k: str) -> str:
        return f"\\old(this.{self.fmap[k].jfield})"

    def stmt(self, s: ir.Stmt) -> None:
        if isinstance(s, ir.Move):
            v, sc = self.num(s.src)
            for d in s.dsts:
                fm = self._target(d)
                stored, _ = self.store(fm, v, sc, False)
                self.env[fm.cobol] = self.finish(fm, stored)
            return
        if isinstance(s, ir.ArithAssign | ir.ArithOp):
            if s.op not in (None, "+", "-", "*"):
                raise ContractUnsupported("DIVIDE has no functional postcondition")
            src = s.expr if isinstance(s, ir.ArithAssign) else s.src
            ev, es = self.num(src)
            flag_parts = []
            for t in s.targets:
                fm = self._target(t.ref)
                if s.op is None:
                    v, vs = ev, es
                else:
                    cur = self.val(fm.cobol)
                    if s.op == "*":
                        v, vs = f"({cur} * {ev})", fm.rf.scale + es
                    else:
                        sc = max(fm.rf.scale, es)
                        v, vs = f"({_scale(cur, sc - fm.rf.scale)} {s.op} {_scale(ev, sc - es)})", sc
                stored, ovf = self.store(fm, v, vs, t.rounded)
                if s.handler:
                    keep = self.val(fm.cobol)
                    nv = stored if fm.rf.signed else f"(({stored}) < 0 ? -({stored}) : ({stored}))"
                    self.env[fm.cobol] = f"({ovf} ? {keep} : {nv})"
                    flag_parts.append(ovf)
                else:
                    self.env[fm.cobol] = self.finish(fm, stored)
            if s.handler:
                flag = " || ".join(flag_parts) or "false"
                self.branch(flag, s.size_error, s.not_size_error)
            return
        if isinstance(s, ir.If):
            self.branch(self.cond(s.cond), s.then, s.els)
            return
        if isinstance(s, ir.Evaluate):
            self._evaluate(s.whens, s.other)
            return
        if isinstance(s, ir.Perform):
            if s.mode != "once" or s.thru:
                raise ContractUnsupported("loop in the unit: needs a loop invariant for a functional postcondition")
            if s.proc is not None:
                p = self.irp.paragraph(s.proc[0])
                if p is None:
                    raise ContractUnsupported(f"PERFORM {s.proc[0]} not found")
                self.block(p.body)
            else:
                self.block(s.body)
            return
        if isinstance(s, ir.SetCond):
            for c in s.conds:
                fm = self._target(c.parent)
                self.env[fm.cobol] = f"{_lit_scaled(c.cond.values_88[0][0].text, fm.rf.scale)}L"
            return
        if isinstance(s, ir.Initialize):
            for r in s.targets:
                names = [i.name for i in r.item.walk() if i.is_elementary and not i.is_filler] \
                    if r.item.is_group else [r.item.name]
                for n in names:
                    fm = self.fmap.get(n)
                    if fm is None or fm.rf.kind != "num":
                        raise ContractUnsupported(f"INITIALIZE of non-numeric {n}")
                    self.env[n] = "0L"
            return
        if isinstance(s, ir.Continue) or (isinstance(s, ir.ExitStmt) and s.kind == "plain"):
            return
        raise ContractUnsupported(f"{s.verb} at line {s.loc.line} has no functional postcondition")

    def _evaluate(self, whens: list[ir.When], other: list[ir.Stmt] | None) -> None:
        if not whens:
            self.block(other)
            return
        first, rest = whens[0], whens[1:]
        c = self.cond(first.cond)
        base = dict(self.env)
        self.block(first.body)
        t_env = self.env
        self.env = dict(base)
        self._evaluate(rest, other)
        e_env = self.env
        merged = {}
        for k in set(t_env) | set(e_env):
            a = t_env.get(k, base.get(k) or self.val_old(k))
            b = e_env.get(k, base.get(k) or self.val_old(k))
            merged[k] = a if a == b else f"({c} ? {a} : {b})"
        self.env = merged

    def _target(self, r: ir.Ref) -> FieldMap:
        if r.subs or r.refmod:
            raise ContractUnsupported("subscripted/reference-modified target in a functional postcondition")
        fm = self.fmap.get(r.item.name)
        if fm is None or fm.rf.kind != "num":
            raise ContractUnsupported(f"{r.item.name} is not a mapped numeric field")
        return fm


def _scale(expr: str, k: int) -> str:
    c = _cint(expr)
    if c is not None:
        return f"({c * 10**k}L)"
    return expr if k == 0 else f"({expr} * {10**k}L)"


_CONST = re.compile(r"^\(*(-?\d+)L\)*$")


def _cint(expr: str) -> int | None:
    m = _CONST.match(expr.strip())
    if m is None or expr.count("(") != expr.count(")"):
        return None
    return int(m.group(1))


def _jdiv(a: int, b: int) -> int:
    """Java/JML integer division (truncates toward zero)."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def share_post_state(exprs: dict[str, str], fields: dict[str, str]) -> dict[str, str]:
    """Replace, inside each field's postcondition expression, any occurrence of another written field's
    complete final expression by `this.<field>` (its post-state value) — an equality-preserving rewrite
    that keeps chained computations (TOTAL then DISC from TOTAL) linear in size."""
    out = dict(exprs)
    order = sorted(exprs, key=lambda k: -len(exprs[k]))
    for name in out:
        e = out[name]
        for other in order:
            if other == name or len(exprs[other]) < 12 or _cint(exprs[other]) is not None:
                continue
            if exprs[other] in e:
                e = e.replace(exprs[other], f"this.{fields[other]}")
        out[name] = e
    return out


def _lit_scaled(text: str, scale: int) -> int:
    neg = text.strip().startswith("-")
    body = text.strip().lstrip("+-")
    ip, _, fp = body.partition(".")
    fp = (fp + "0" * scale)[:scale]
    v = int((ip or "0") + fp)
    return -v if neg else v


# ---------------------------------------------------------------------------------------------
def build_contract(irp: ir.IrProgram, closure: list[str], cand_fields: dict[str, str],
                   mapping: dict[str, dict[str, object]], unmapped_cand_fields: list[str]) -> Contract:
    """Contract for one unit (its PERFORM closure) over the candidate's fields."""
    used = touched(irp, closure)
    writes = write_set(irp, closure)
    fmap: dict[str, FieldMap] = {}
    for name in sorted(used):
        item = irp.program.resolve(name)
        if item is None:
            continue
        try:
            rf = classify_item(item)
        except EmitUnsupported as exc:
            raise ContractUnsupported(exc.reason) from exc
        m = mapping.get(name)
        if not m or not m.get("target"):
            raise ContractUnsupported(f"COBOL field {name} used by the unit has no target counterpart")
        jf = str(m["target"])
        jt = (str(m.get("target_type") or cand_fields.get(jf, ""))).replace(" ", "")
        if rf.kind == "num" and jt.replace("[]", "") not in ("long", "int", "short", "byte"):
            raise ContractUnsupported(f"{name} is `{jt or '?'}` in the target; T3 needs integer-scaled numerics "
                                      "(BigDecimal value reasoning is not supported by OpenJML, spike S3)")
        fmap[name] = FieldMap(name, rf, jf, jt)
    requires = [_range(fm) for fm in fmap.values() if fm.rf.kind == "num" and not fm.rf.occurs]
    ensures = [_range(fm) for n, fm in fmap.items() if n in writes and fm.rf.kind == "num" and not fm.rf.occurs]
    assignable = sorted({f"this.{fmap[n].jfield}" + ("[*]" if fmap[n].rf.occurs or fmap[n].rf.kind == "alnum" else "")
                         for n in writes if n in fmap} | {f"this.{f}" for f in unmapped_cand_fields})
    functional = False
    notes: list[str] = []
    try:
        se = SymEval(irp, fmap, closure)
        p = irp.paragraph(closure[0])
        assert p is not None
        se.block(p.body)
        finals = {n: se.env[n] for n in sorted(writes) if n in se.env and n in fmap}
        shared = share_post_state(finals, {n: fmap[n].jfield for n in finals})
        for n, e in shared.items():
            ensures.append(f"this.{fmap[n].jfield} == {e}")
        functional = True
    except ContractUnsupported as exc:
        notes.append(f"no functional postcondition: {exc.reason}")
    return Contract(requires, ensures, assignable, functional, notes)
