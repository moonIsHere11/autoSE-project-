"""Java reference emitter for T2b (spec section 6, T2b.3).

Produces a literal, non-idiomatic, JBMC-friendly Java translation of a set of paragraphs (a unit and
its PERFORM closure) from the COBOL IR:

* numeric items → `long` holding the value unscaled at the PIC scale; alphanumerics → `char[]` of
  the PIC length; one-dimensional OCCURS → `long[]` / `char[][]`;
* arithmetic in exact scaled `long`s with a conservative digit bound: any intermediate that could
  need more than 18 digits makes the unit NOT_APPLICABLE ("precision exceeds bound");
* no JDK calls, no String, no BigDecimal, no collections: only the emitted helper class `RT`
  (a self-contained copy of the static core; deliberately *not* the `cobolrt` library that the
  generated code may use, so the trusted reference cannot share a bug with the code under check).

Constructs outside this subset raise `EmitUnsupported(reason)`; the unit is then T2b
NOT_APPLICABLE with that reason (never guessed). Division and exponentiation are excluded because
JBMC cannot prove them in practice (spike S2, DECISIONS D15); such units rely on T1/T1u/T3.

Every emitted reference must pass the validation gate before it is trusted (t2_symbolic.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from verifier.cobol import ir
from verifier.cobol.datadiv import DataItem

MAX_DIGITS = 18


class EmitUnsupported(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class RefField:
    item: DataItem
    jname: str
    kind: str  # num | alnum
    digits: int = 0
    scale: int = 0
    signed: bool = False
    length: int = 0
    occurs: int | None = None

    @property
    def cobol(self) -> str:
        return self.item.name

    def describe(self) -> str:
        if self.kind == "num":
            return f"{'S' if self.signed else ''}9({self.digits - self.scale})" + (f"V9({self.scale})" if self.scale else "")
        return f"X({self.length})"


@dataclass
class EmittedRef:
    package: str
    class_name: str
    source: str
    fields: dict[str, RefField]
    methods: dict[str, str]  # paragraph -> java method
    loop_bound: int  # unwind bound that covers every loop with a literal bound (0 = no loops)
    unbounded_loops: bool  # some loop has a data-dependent bound
    lines: dict[int, str] = field(default_factory=dict)

    @property
    def qualified(self) -> str:
        return f"{self.package}.{self.class_name}" if self.package else self.class_name


def jident(cobol: str) -> str:
    return "f_" + re.sub(r"[^A-Za-z0-9]", "_", cobol)


def jmethod(para: str) -> str:
    return "p_" + re.sub(r"[^A-Za-z0-9]", "_", para)


# ---------------------------------------------------------------------------------------------
def classify_item(item: DataItem) -> RefField:
    if item.is_group:
        raise EmitUnsupported(f"group item {item.name} (group moves/REDEFINES are not modelled in the Java reference)")
    if item.redefines or any(p.redefines for p in _ancestors(item)):
        raise EmitUnsupported(f"{item.name} is part of a REDEFINES (byte aliasing not modelled in the Java reference)")
    dims = item.occurs_dims() if hasattr(item, "occurs_dims") else 0
    if dims > 1:
        raise EmitUnsupported(f"{item.name} has {dims}-dimensional OCCURS")
    occurs = None
    if dims == 1:
        holder = item if item.occurs else next(p for p in _ancestors(item) if p.occurs)
        if holder.depending_on:
            raise EmitUnsupported(f"{holder.name} uses OCCURS DEPENDING ON")
        occurs = holder.occurs
    pic = item.pic
    if pic is None:
        raise EmitUnsupported(f"{item.name} has no PICTURE")
    if pic.category == "numeric":
        if "P" in pic.expanded or pic.scale < 0 or pic.scale > pic.digits:
            raise EmitUnsupported(f"{item.name} PIC {pic.raw} uses P scaling")
        if item.usage.upper() in ("COMP-5", "BINARY-LONG", "BINARY-SHORT", "BINARY-CHAR", "BINARY-DOUBLE",
                                  "COMP-1", "COMP-2", "FLOAT-SHORT", "FLOAT-LONG", "INDEX", "POINTER"):
            raise EmitUnsupported(f"{item.name} USAGE {item.usage} is not modelled in the Java reference")
        if pic.digits > MAX_DIGITS:
            raise EmitUnsupported(f"precision exceeds bound: {item.name} has {pic.digits} digits")
        return RefField(item, jident(item.name), "num", pic.digits, pic.scale, pic.signed, occurs=occurs)
    if pic.category in ("alphanumeric", "alphabetic"):
        n = item.unit_size or pic.length
        return RefField(item, jident(item.name), "alnum", length=n, occurs=occurs)
    raise EmitUnsupported(f"{item.name} PIC {pic.raw} ({pic.category}) is not modelled in the Java reference")


def _ancestors(item: DataItem) -> list[DataItem]:
    out = []
    p = item.parent
    while p is not None:
        out.append(p)
        p = p.parent
    return out


# ---------------------------------------------------------------------------------------------
RT_SOURCE = """\
final class RT {
    static long pow10(int n) {
        long p = 1L;
        for (int i = 0; i < n; i++) {
            p = p * 10L;
        }
        return p;
    }
    static long abs(long v) {
        return v < 0 ? -v : v;
    }
    /** value at scale `from` -> scale `to`: exact when widening, truncation or half-away-from-zero rounding. */
    static long rescale(long v, int from, int to, boolean rounded) {
        if (to >= from) {
            return v * pow10(to - from);
        }
        long d = pow10(from - to);
        long q = v / d;
        if (rounded) {
            long r = v % d;
            if (abs(r) * 2L >= d) {
                q = q + (v < 0 ? -1L : 1L);
            }
        }
        return q;
    }
    static boolean overflow(long v, int digits) {
        return abs(v) >= pow10(digits);
    }
    /** high-order truncation to `digits`; unsigned targets keep the absolute value. */
    static long trunc(long v, int digits, boolean signed) {
        long t = v % pow10(digits);
        return signed ? t : abs(t);
    }
    static int cmp(long a, int sa, long b, int sb) {
        if (sa < sb) {
            a = a * pow10(sb - sa);
        } else if (sb < sa) {
            b = b * pow10(sa - sb);
        }
        return a < b ? -1 : (a == b ? 0 : 1);
    }
    static void moveX(char[] dst, char[] src, boolean justRight) {
        int n = dst.length;
        int m = src.length;
        if (!justRight) {
            for (int i = 0; i < n; i++) {
                dst[i] = i < m ? src[i] : ' ';
            }
        } else {
            for (int i = 0; i < n; i++) {
                int j = m - n + i;
                dst[i] = j >= 0 ? src[j] : ' ';
            }
        }
    }
    static void fill(char[] dst, char c) {
        for (int i = 0; i < dst.length; i++) {
            dst[i] = c;
        }
    }
    static int cmpX(char[] a, char[] b) {
        int n = a.length > b.length ? a.length : b.length;
        for (int i = 0; i < n; i++) {
            char x = i < a.length ? a[i] : ' ';
            char y = i < b.length ? b[i] : ' ';
            if (x != y) {
                return x < y ? -1 : 1;
            }
        }
        return 0;
    }
    static boolean allDigits(char[] a) {
        for (int i = 0; i < a.length; i++) {
            if (a[i] < '0' || a[i] > '9') {
                return false;
            }
        }
        return true;
    }
    static boolean alphabetic(char[] a, int mode) {
        for (int i = 0; i < a.length; i++) {
            char c = a[i];
            boolean lo = c >= 'a' && c <= 'z';
            boolean up = c >= 'A' && c <= 'Z';
            boolean ok = c == ' ' || (mode == 0 ? (lo || up) : (mode == 1 ? lo : up));
            if (!ok) {
                return false;
            }
        }
        return true;
    }
    /** unsigned integer digits of |v| as `width` characters (numeric -> alphanumeric MOVE). */
    static char[] digits(long v, int width) {
        char[] out = new char[width];
        long x = abs(v);
        for (int i = width - 1; i >= 0; i--) {
            out[i] = (char) ('0' + (int) (x % 10L));
            x = x / 10L;
        }
        return out;
    }
    static void outOfModel(boolean ok) {
        if (!ok) {
            throw new REFCLASS.OutOfModel();
        }
    }
}
"""


@dataclass
class _NExpr:
    code: str
    scale: int
    digits: int  # conservative bound on total digits of the value


class Emitter:
    def __init__(self, irp: ir.IrProgram, paragraphs: list[str], package: str, class_name: str) -> None:
        self.ir = irp
        self.paras = paragraphs
        self.package = package
        self.class_name = class_name
        self.fields: dict[str, RefField] = {}
        self.consts: dict[bytes, str] = {}
        self.tmp = 0
        self.loop_bound = 0
        self.unbounded = False
        self.in_loop = 0

    # ---- fields ---------------------------------------------------------------------------
    def fld(self, item: DataItem) -> RefField:
        if item.name not in self.fields:
            if sum(1 for i in self.ir.program.all_items() if i.name == item.name) > 1:
                raise EmitUnsupported(f"{item.name} is not a unique name (qualified references not modelled)")
            self.fields[item.name] = classify_item(item)
        return self.fields[item.name]

    def access(self, r: ir.Ref) -> tuple[RefField, str]:
        if r.refmod is not None:
            raise EmitUnsupported(f"reference modification on {r.item.name}")
        f = self.fld(r.item)
        if f.occurs is None:
            if r.subs:
                raise EmitUnsupported(f"subscript on non-OCCURS item {r.item.name}")
            return f, f"this.{f.jname}"
        if len(r.subs) != 1:
            raise EmitUnsupported(f"{r.item.name} referenced without exactly one subscript")
        idx = self.num(r.subs[0])
        if idx.scale != 0:
            raise EmitUnsupported(f"non-integer subscript on {r.item.name}")
        return f, f"this.{f.jname}[RT.sub({idx.code}, {f.occurs})]"

    def tmpname(self) -> str:
        self.tmp += 1
        return f"t{self.tmp}"

    # ---- numeric expressions ---------------------------------------------------------------
    def num(self, e: ir.Expr) -> _NExpr:
        if isinstance(e, ir.Lit):
            d = max(1, len(e.digits.lstrip("0")) or 1)
            return _NExpr(f"({e.value}L)", e.scale, max(d, e.scale))
        if isinstance(e, ir.Fig) and e.name == "ZERO":
            return _NExpr("0L", 0, 1)
        if isinstance(e, ir.Ref):
            f, code = self.access(e)
            if f.kind != "num":
                raise EmitUnsupported(f"alphanumeric {e.item.name} used as a number")
            return _NExpr(code, f.scale, f.digits)
        if isinstance(e, ir.Bin):
            if e.op in ("/", "^"):
                raise EmitUnsupported("division/exponentiation in an arithmetic expression (JBMC cannot prove it; "
                                      "spike S2) — unit left to T1/T1u/T3")
            a, b = self.num(e.left), self.num(e.right)
            if e.op in ("+", "-"):
                s = max(a.scale, b.scale)
                ia, ib = a.digits - a.scale, b.digits - b.scale
                d = max(ia, ib) + 1 + s
                self._bound(d, e)
                return _NExpr(f"({self._align(a, s)} {e.op} {self._align(b, s)})", s, d)
            if e.op == "*":
                d = a.digits + b.digits
                self._bound(d, e)
                return _NExpr(f"({a.code} * {b.code})", a.scale + b.scale, d)
        raise EmitUnsupported(f"expression {e} not modelled")

    def _bound(self, digits: int, e: object) -> None:
        if digits > MAX_DIGITS:
            raise EmitUnsupported(f"precision exceeds bound: {e} may need {digits} digits (> 18 in a 63-bit long)")

    def _align(self, x: _NExpr, s: int) -> str:
        return x.code if x.scale == s else f"({x.code} * {10 ** (s - x.scale)}L)"

    # ---- alphanumeric operands ---------------------------------------------------------------
    def const(self, data: bytes) -> str:
        if data not in self.consts:
            self.consts[data] = f"K{len(self.consts)}"
        return self.consts[data]

    def alnum(self, e: ir.Expr, width: int) -> str:
        """A char[] expression for an alphanumeric sending operand."""
        if isinstance(e, ir.StrLit):
            return self.const(e.value)
        if isinstance(e, ir.Fig):
            ch = {"SPACE": b" ", "ZERO": b"0", "QUOTE": b'"', "HIGH-VALUE": b"\xff", "LOW-VALUE": b"\x00"}.get(e.name)
            if e.name == "ALL":
                ch = e.value
            if not ch:
                raise EmitUnsupported(f"figurative constant {e}")
            return self.const((ch * (width // len(ch) + 1))[:width])
        if isinstance(e, ir.Ref):
            f, code = self.access(e)
            if f.kind == "alnum":
                return code
            if f.scale != 0:
                raise EmitUnsupported(f"MOVE of non-integer numeric {e.item.name} to an alphanumeric item")
            return f"RT.digits({code}, {f.digits})"
        if isinstance(e, ir.Lit):
            if e.scale != 0 or e.negative:
                raise EmitUnsupported(f"MOVE of non-integer or signed literal {e} to an alphanumeric item")
            return self.const(e.digits.encode())
        raise EmitUnsupported(f"alphanumeric operand {e}")

    # ---- stores ---------------------------------------------------------------------------
    def store_num(self, f: RefField, code: str, value: str, vscale: int, rounded: bool,
                  on_overflow: str | None) -> list[str]:
        """Assign a value at scale vscale to a numeric field: round/truncate, size check, sign."""
        t = self.tmpname()
        out = [f"long {t} = RT.rescale({value}, {vscale}, {f.scale}, {'true' if rounded else 'false'});"]
        sgn = "true" if f.signed else "false"
        if on_overflow is None:
            out.append(f"{code} = RT.trunc({t}, {f.digits}, {sgn});")
        else:
            out.append(f"if (RT.overflow({t}, {f.digits})) {{ {on_overflow} }} "
                       f"else {{ {code} = {t if f.signed else f'RT.abs({t})'}; }}")
        return out

    def move(self, src: ir.Expr, dst: ir.Ref) -> list[str]:
        f, code = self.access(dst)
        if f.kind == "num":
            if isinstance(src, ir.Fig) and src.name != "ZERO":
                raise EmitUnsupported(f"MOVE {src} to numeric {dst.item.name}")
            if isinstance(src, ir.Ref) and self.fld(src.item).kind != "num":
                raise EmitUnsupported(f"MOVE alphanumeric {src.item.name} to numeric {dst.item.name} (de-editing)")
            if isinstance(src, ir.StrLit):
                raise EmitUnsupported(f"MOVE string literal to numeric {dst.item.name}")
            v = self.num(src)
            return self.store_num(f, code, v.code, v.scale, False, None)
        just = "true" if f.item.justified else "false"
        return [f"RT.moveX({code}, {self.alnum(src, f.length)}, {just});"]

    # ---- conditions ---------------------------------------------------------------------------
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
            return self.rel(c.op, c.left, c.right)
        if isinstance(c, ir.ClassTest):
            if not isinstance(c.operand, ir.Ref):
                raise EmitUnsupported(f"class test on {c.operand}")
            f, code = self.access(c.operand)
            if f.kind == "num":
                if c.kind == "NUMERIC":
                    return "true"  # in-domain numeric DISPLAY data is always valid digits (domain assumption)
                raise EmitUnsupported(f"{c.kind} test on numeric {c.operand}")
            if c.kind == "NUMERIC":
                return f"RT.allDigits({code})"
            mode = {"ALPHABETIC": 0, "ALPHABETIC-LOWER": 1, "ALPHABETIC-UPPER": 2}.get(c.kind)
            if mode is None:
                raise EmitUnsupported(f"class test {c.kind}")
            return f"RT.alphabetic({code}, {mode})"
        if isinstance(c, ir.CondName):
            return self.condname(c)
        raise EmitUnsupported(f"condition {c}")

    def _is_num(self, e: ir.Expr) -> bool | None:
        if isinstance(e, ir.Lit):
            return True
        if isinstance(e, ir.Ref):
            return self.fld(e.item).kind == "num"
        if isinstance(e, ir.Bin):
            return True
        if isinstance(e, ir.StrLit):
            return False
        return None  # figurative: adapts to the other side

    def rel(self, op: str, left: ir.Expr, right: ir.Expr) -> str:
        jop = {"=": "==", "~": "!=", "<": "<", ">": ">", "[": "<=", "]": ">="}[op]
        ln, rn = self._is_num(left), self._is_num(right)
        if ln is None and rn is None:
            raise EmitUnsupported(f"comparison of two figurative constants {left} {right}")
        numeric = (ln if ln is not None else rn)
        if ln is not None and rn is not None and ln != rn:
            raise EmitUnsupported(f"mixed numeric/alphanumeric comparison {left} vs {right}")
        if numeric:
            a, b = self.num(left), self.num(right)
            self._bound(max(a.digits - a.scale, b.digits - b.scale) + max(a.scale, b.scale), f"{left} vs {right}")
            return f"(RT.cmp({a.code}, {a.scale}, {b.code}, {b.scale}) {jop} 0)"
        width = max(self._width(left), self._width(right))
        return f"(RT.cmpX({self.alnum(left, width)}, {self.alnum(right, width)}) {jop} 0)"

    def _width(self, e: ir.Expr) -> int:
        if isinstance(e, ir.Ref):
            return self.fld(e.item).length or 1
        if isinstance(e, ir.StrLit):
            return len(e.value)
        return 1

    def condname(self, c: ir.CondName) -> str:
        parent = c.parent
        f, code = self.access(parent)
        tests = []
        for lo, hi in c.cond.values_88:
            if f.kind == "num":
                lo_l = self._vlit(lo)
                if hi is None:
                    tests.append(f"(RT.cmp({code}, {f.scale}, {lo_l.value}L, {lo_l.scale}) == 0)")
                else:
                    hi_l = self._vlit(hi)
                    tests.append(f"(RT.cmp({code}, {f.scale}, {lo_l.value}L, {lo_l.scale}) >= 0 && "
                                 f"RT.cmp({code}, {f.scale}, {hi_l.value}L, {hi_l.scale}) <= 0)")
            else:
                if hi is not None or lo.kind not in ("str", "fig"):
                    raise EmitUnsupported(f"88-level {c.cond.name} on alphanumeric with a range or ALL value")
                tests.append(f"(RT.cmpX({code}, {self._alnum_value(lo, f.length)}) == 0)")
        if not tests:
            raise EmitUnsupported(f"88-level {c.cond.name} without values")
        return "(" + " || ".join(tests) + ")"

    def _alnum_value(self, v: object, width: int) -> str:
        kind, text = getattr(v, "kind", "str"), getattr(v, "text", str(v))
        if kind == "fig":
            canon = {"SPACES": "SPACE", "ZEROS": "ZERO", "ZEROES": "ZERO", "HIGH-VALUES": "HIGH-VALUE",
                     "LOW-VALUES": "LOW-VALUE", "QUOTES": "QUOTE"}
            return self.alnum(ir.Fig(canon.get(text.upper(), text.upper())), width)
        if kind != "str":
            raise EmitUnsupported(f"88-level VALUE {text} on an alphanumeric item")
        return self.const(text.encode("latin-1"))

    def _vlit(self, v: object) -> ir.Lit:
        text = getattr(v, "text", str(v))
        kind = getattr(v, "kind", "num")
        if kind == "str" or not re.fullmatch(r"[+-]?(\d+\.?\d*|\.\d+)", text):
            raise EmitUnsupported(f"88-level VALUE {text} is not a plain numeric literal")
        neg = text.startswith("-")
        body = text.lstrip("+-")
        ip, _, fp = body.partition(".")
        return ir.Lit(text, (ip + fp) or "0", len(fp), neg, text[0] in "+-")

    # ---- statements ---------------------------------------------------------------------------
    def block(self, stmts: list[ir.Stmt] | None) -> list[str]:
        out: list[str] = []
        for s in stmts or []:
            out.extend(self.stmt(s))
        return out

    def _handler(self, size_error: list[ir.Stmt] | None, not_size_error: list[ir.Stmt] | None,
                 flag: str) -> list[str]:
        out = []
        if size_error is not None:
            out.append(f"if ({flag}) {{")
            out += ["    " + x for x in self.block(size_error)]
            out.append("}")
        if not_size_error is not None:
            out.append(f"if (!{flag}) {{")
            out += ["    " + x for x in self.block(not_size_error)]
            out.append("}")
        return out

    def stmt(self, s: ir.Stmt) -> list[str]:
        if isinstance(s, ir.Move):
            out: list[str] = []
            for d in s.dsts:
                out += self.move(s.src, d)
            return out
        if isinstance(s, ir.ArithAssign | ir.ArithOp):
            return self.arith(s)
        if isinstance(s, ir.If):
            out = [f"if ({self.cond(s.cond)}) {{", *("    " + x for x in self.block(s.then)), "}"]
            if s.els is not None:
                out[-1] = "} else {"
                out += ["    " + x for x in self.block(s.els)] + ["}"]
            return out
        if isinstance(s, ir.Evaluate):
            out = []
            for i, w in enumerate(s.whens):
                kw = "if" if i == 0 else "} else if"
                out.append(f"{kw} ({self.cond(w.cond)}) {{")
                out += ["    " + x for x in self.block(w.body)]
            if s.other is not None:
                out.append("} else {" if s.whens else "{")
                out += ["    " + x for x in self.block(s.other)]
            if s.whens or s.other is not None:
                out.append("}")
            return out
        if isinstance(s, ir.Perform):
            return self.perform(s)
        if isinstance(s, ir.SetCond):
            out = []
            for c in s.conds:
                if not c.cond.values_88:
                    raise EmitUnsupported(f"SET {c.cond.name} TO TRUE without VALUE")
                lo, _hi = c.cond.values_88[0]
                f = self.fld(c.parent.item)
                if f.kind == "num":
                    out += self.move(self._vlit(lo), c.parent)
                else:
                    _f, code = self.access(c.parent)
                    just = "true" if f.item.justified else "false"
                    out.append(f"RT.moveX({code}, {self._alnum_value(lo, f.length)}, {just});")
            return out
        if isinstance(s, ir.Initialize):
            out = []
            for r in s.targets:
                items = [r.item] if not r.item.is_group else [
                    i for i in r.item.walk() if i.is_elementary and not i.is_filler]
                if r.item.is_group and r.subs:
                    raise EmitUnsupported(f"INITIALIZE of a subscripted group {r.item.name}")
                for it in items:
                    f = self.fld(it)
                    if f.occurs is not None and not r.subs:
                        rng = range(f.occurs)
                        for k in rng:
                            code = f"this.{f.jname}[{k}]"
                            out.append(f"{code} = 0L;" if f.kind == "num" else f"RT.fill({code}, ' ');")
                    else:
                        _f, code = self.access(r) if not r.item.is_group else (f, f"this.{f.jname}")
                        out.append(f"{code} = 0L;" if f.kind == "num" else f"RT.fill({code}, ' ');")
            return out
        if isinstance(s, ir.Continue):
            return []
        if isinstance(s, ir.ExitStmt):
            if s.kind == "plain":
                return []
            if s.kind == "paragraph":
                return ["return;"]
            raise EmitUnsupported(f"EXIT {s.kind.upper()}")
        if isinstance(s, ir.Unsupported):
            raise EmitUnsupported(s.reason)
        raise EmitUnsupported(f"{s.verb} at line {s.loc.line} is outside the T2b subset")

    def arith(self, s: ir.ArithAssign | ir.ArithOp) -> list[str]:
        flag = self.tmpname()
        handler = s.handler
        out = [f"boolean {flag} = false;"] if handler else []
        if isinstance(s, ir.ArithAssign):
            if s.op is not None and s.op not in ("+", "-", "*"):
                raise EmitUnsupported("DIVIDE (JBMC cannot prove division; spike S2)")
            e = self.num(s.expr)
            ev = self.tmpname()
            out.append(f"long {ev} = {e.code};")
            src = _NExpr(ev, e.scale, e.digits)
            ops: list[tuple[ir.Target, str | None]] = [(t, s.op) for t in s.targets]
        else:
            if s.op not in ("+", "-", "*"):
                raise EmitUnsupported("DIVIDE (JBMC cannot prove division; spike S2)")
            e = self.num(s.src)
            ev = self.tmpname()
            out.append(f"long {ev} = {e.code};")
            src = _NExpr(ev, e.scale, e.digits)
            ops = [(t, s.op) for t in s.targets]
        for t, op in ops:
            f, code = self.access(t.ref)
            if f.kind != "num":
                raise EmitUnsupported(f"arithmetic into alphanumeric {t.ref.item.name}")
            if op is None:
                val = src
            else:
                cur = _NExpr(code, f.scale, f.digits)
                if op == "*":
                    d = cur.digits + src.digits
                    self._bound(d, f"{t.ref.item.name} * …")
                    val = _NExpr(f"({cur.code} * {src.code})", cur.scale + src.scale, d)
                else:
                    sc = max(cur.scale, src.scale)
                    d = max(cur.digits - cur.scale, src.digits - src.scale) + 1 + sc
                    self._bound(d, f"{t.ref.item.name} {op} …")
                    val = _NExpr(f"({self._align(cur, sc)} {op} {self._align(src, sc)})", sc, d)
            out += self.store_num(f, code, val.code, val.scale, t.rounded, f"{flag} = true;" if handler else None)
        if handler:
            out += self._handler(s.size_error, s.not_size_error, flag)
        return out

    def perform(self, s: ir.Perform) -> list[str]:
        if s.thru:
            raise EmitUnsupported("PERFORM THRU")
        if s.proc is not None:
            if s.proc[0] not in self.paras:
                raise EmitUnsupported(f"PERFORM {s.proc[0]} outside the unit closure")
            body = [f"{jmethod(s.proc[0])}();"]
        else:
            self.in_loop += 1
            body = self.block(s.body)
            self.in_loop -= 1
        if s.mode == "once":
            return body if s.proc is not None else ["{", *("    " + x for x in body), "}"]
        if s.mode == "times":
            assert s.times is not None
            n = self.num(s.times)
            if n.scale != 0:
                raise EmitUnsupported("PERFORM n TIMES with non-integer n")
            if isinstance(s.times, ir.Lit):
                self.loop_bound = max(self.loop_bound, s.times.value)
            else:
                self.unbounded = True
            c, i = self.tmpname(), self.tmpname()
            return [f"long {c} = {n.code};", f"for (long {i} = 0; {i} < {c}; {i}++) {{",
                    *("    " + x for x in body), "}"]
        if s.mode == "until":
            assert s.until is not None
            self.unbounded = True
            if s.test_after:
                return ["do {", *("    " + x for x in body), f"}} while (!({self.cond(s.until)}));"]
            return [f"while (!({self.cond(s.until)})) {{", *("    " + x for x in body), "}"]
        if s.mode == "varying":
            if len(s.varying) != 1:
                raise EmitUnsupported("PERFORM VARYING … AFTER")
            v = s.varying[0]
            f, code = self.access(v.var)
            if f.kind != "num":
                raise EmitUnsupported("PERFORM VARYING an alphanumeric item")
            start, by = self.num(v.start), self.num(v.by)
            self._literal_trip(v)
            out = self.store_num(f, code, start.code, start.scale, False, None)
            test = "" if not s.test_after else "do"
            cur = _NExpr(code, f.scale, f.digits)
            sc = max(cur.scale, by.scale)
            d = max(cur.digits - cur.scale, by.digits - by.scale) + 1 + sc
            self._bound(d, f"VARYING {v.var.item.name}")
            step = self.store_num(f, code, f"({self._align(cur, sc)} + {self._align(by, sc)})", sc, False, None)
            if test:
                return [*out, "do {", *("    " + x for x in body), *("    " + x for x in step),
                        f"}} while (!({self.cond(v.until)}));"]
            return [*out, f"while (!({self.cond(v.until)})) {{", *("    " + x for x in body),
                    *("    " + x for x in step), "}"]
        raise EmitUnsupported(f"PERFORM mode {s.mode}")

    def _literal_trip(self, v: ir.Varying) -> None:
        """Trip count for `FROM lit BY lit UNTIL var > lit`-style loops; otherwise data-dependent."""
        c = v.until
        if (isinstance(v.start, ir.Lit) and isinstance(v.by, ir.Lit) and isinstance(c, ir.Rel)
                and isinstance(c.right, ir.Lit) and isinstance(c.left, ir.Ref) and c.left.item is v.var.item
                and v.by.value != 0):
            a, b, lim = v.start.value, v.by.value, c.right.value
            trips = abs((lim - a) // b) + 2
            self.loop_bound = max(self.loop_bound, trips)
        else:
            self.unbounded = True

    # ---- program ---------------------------------------------------------------------------
    def emit(self) -> EmittedRef:
        methods: dict[str, str] = {}
        bodies: list[str] = []
        for name in self.paras:
            p = self.ir.paragraph(name)
            if p is None:
                raise EmitUnsupported(f"paragraph {name} not found")
            lines = self.block(p.body)
            methods[name] = jmethod(name)
            bodies.append(f"    public void {jmethod(name)}() {{")
            bodies += ["        " + x for x in lines]
            bodies.append("    }")
            bodies.append("")
        decls = []
        for f in sorted(self.fields.values(), key=lambda x: x.cobol):
            if f.kind == "num":
                decls.append(f"    public long{'[]' if f.occurs else ''} {f.jname}"
                             + (f" = new long[{f.occurs}];" if f.occurs else ";") + f"  // {f.cobol} {f.describe()}")
            elif f.occurs:
                decls.append(f"    public char[][] {f.jname} = new char[{f.occurs}][{f.length}];  "
                             f"// {f.cobol} {f.describe()}")
            else:
                decls.append(f"    public char[] {f.jname} = new char[{f.length}];  // {f.cobol} {f.describe()}")
        consts = [f"    static final char[] {name} = {{{', '.join(_jchar(b) for b in data)}}};"
                  for data, name in self.consts.items()]
        pkg = f"package {self.package};\n\n" if self.package else ""
        oom = ("    /** Thrown when an execution leaves the modelled domain (e.g. subscript out of range). */\n"
               "    public static final class OutOfModel extends RuntimeException {\n"
               "        private static final long serialVersionUID = 1L;\n    }\n\n")
        rt = RT_SOURCE.replace("final class RT {", "final class RT {\n" + _SUB, 1).replace("REFCLASS", self.class_name)
        src = (pkg + f"/** Generated COBOL reference for {self.ir.program.program_id} ({', '.join(self.paras)}). */\n"
               f"public final class {self.class_name} {{\n" + oom + "\n".join(decls + consts) + "\n\n"
               + "\n".join(bodies) + "}\n\n" + rt)
        return EmittedRef(self.package, self.class_name, src, dict(self.fields), methods,
                          self.loop_bound, self.unbounded)


_SUB = """    /** 1-based COBOL subscript -> 0-based index; out-of-range subscripts are outside the model. */
    static int sub(long s, int n) {
        outOfModel(s >= 1 && s <= n);
        return (int) (s - 1);
    }
"""


def _jchar(b: int) -> str:
    c = chr(b)
    if c == "'":
        return "'\\''"
    if c == "\\":
        return "'\\\\'"
    if 32 <= b < 127:
        return f"'{c}'"
    return f"(char) {b}"


def emit_reference(irp: ir.IrProgram, paragraphs: list[str], package: str, class_name: str) -> EmittedRef:
    """Emit the reference for `paragraphs` (the unit first, then its PERFORM closure)."""
    for name in paragraphs:
        p = irp.paragraph(name)
        if p is None:
            raise EmitUnsupported(f"paragraph {name} not in the IR")
        if p.t2_eligibility is not None:
            raise EmitUnsupported(p.t2_eligibility)
    return Emitter(irp, paragraphs, package, class_name).emit()
