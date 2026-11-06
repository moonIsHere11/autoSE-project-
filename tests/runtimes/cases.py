"""Random, seeded test cases for the runtime differential test (GnuCOBOL is the oracle).

A case is one COBOL statement (or a tiny statement group) over a few fields with given initial
values. Each case is rendered twice: as COBOL source (`cobol_gen.py`, run under GnuCOBOL) and as
one line of a small *op script* that the Python/Java/Go drivers interpret with their cobolrt.

Script line grammar (whitespace separated, interpreted by every driver)::

    <id> <OP> <round> <size> <field>... [-- <extra>...]
    field := N,<digits>,<scale>,<signed 0|1>,<usage 0-3>,<lead 0|1>,<sep 0|1>,<literal>
           | X,<length>,<justified 0|1>,<hex bytes>

`round` is a cobolrt Round code (0-9); `size` is 0 none,
1 ON + NOT ON SIZE ERROR, 2 NOT ON SIZE ERROR only, 3 ON SIZE ERROR only.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

# ---- field descriptions -----------------------------------------------------------------------
DISPLAY, COMP, COMP3, COMP5 = 0, 1, 2, 3
USAGE_NAMES = {DISPLAY: "", COMP: "COMP", COMP3: "COMP-3", COMP5: "COMP-5"}


@dataclass(frozen=True)
class NumF:
    digits: int
    scale: int
    signed: bool
    usage: int
    lead: bool = False
    sep: bool = False

    @property
    def nbytes(self) -> int:
        if self.usage == DISPLAY:
            return self.digits + (1 if self.sep else 0)
        if self.usage == COMP3:
            return self.digits // 2 + 1
        d = self.digits
        return 1 if d <= 2 else 2 if d <= 4 else 4 if d <= 9 else 8

    def picture(self) -> str:
        s = "S" if self.signed else ""
        if self.scale <= 0:
            return f"{s}9({self.digits})" + "P" * (-self.scale)
        if self.scale >= self.digits:
            return f"{s}V" + "P" * (self.scale - self.digits) + f"9({self.digits})"
        return f"{s}9({self.digits - self.scale})V9({self.scale})"

    def clause(self) -> str:
        parts = [f"PIC {self.picture()}"]
        if self.usage != DISPLAY:
            parts.append(USAGE_NAMES[self.usage])
        if self.lead or self.sep:
            parts.append("SIGN " + ("LEADING" if self.lead else "TRAILING") + (" SEPARATE" if self.sep else ""))
        return " ".join(parts)

    def literal(self, u: int) -> str:
        """COBOL literal for unscaled value u."""
        return lit_text(u, self.scale)

    def max_u(self) -> int:
        return 10**self.digits - 1

    def spec(self, u: int) -> str:
        return (f"N,{self.digits},{self.scale},{int(self.signed)},{self.usage},{int(self.lead)},"
                f"{int(self.sep)},{self.literal(u)}")


@dataclass(frozen=True)
class AlnF:
    length: int
    justified: bool = False

    def clause(self) -> str:
        return f"PIC X({self.length})" + (" JUSTIFIED RIGHT" if self.justified else "")

    def spec(self, v: bytes) -> str:
        return f"X,{self.length},{int(self.justified)},{v.hex() or '-'}"


def lit_text(u: int, scale: int) -> str:
    neg = u < 0
    m = abs(u)
    if scale <= 0:
        t = str(m * 10**-scale)
    else:
        s = str(m).rjust(scale + 1, "0")
        t = s[:-scale] + "." + s[-scale:]
    return ("-" if neg else "") + t


# ---- cases ----------------------------------------------------------------------------------------
Field = tuple[NumF | AlnF, object]  # (description, initial value: int unscaled | bytes)


@dataclass
class Case:
    cid: int
    op: str
    fields: list[Field]
    round: int = 0
    size: int = 0
    extra: list[str] = field(default_factory=list)
    stdin: list[bytes | None] = field(default_factory=list)  # ACCEPT lines (None = no line: EOF)

    @property
    def name(self) -> str:
        return f"{self.cid:05d}"

    def script(self) -> str:
        specs = []
        for f, v in self.fields:
            if isinstance(f, NumF):
                assert isinstance(v, int)
                specs.append(f.spec(v))
            else:
                assert isinstance(v, bytes)
                specs.append(f.spec(v))
        line = f"{self.name} {self.op} {self.round} {self.size} " + " ".join(specs)
        if self.extra:
            line += " -- " + " ".join(self.extra)
        return line


ARITH_OPS = ["ADD", "SUB", "MUL", "DIVI", "ADDG", "SUBG", "MULG", "DIVIG", "DIVBG", "DIVBR", "DIVIR"]
ALL_OPS = ["MOVE", "MOVEL", "DISP", "ENC", *ARITH_OPS, "COMP", "NX", "XN", "XX", "XL", "CMP", "XCMP", "ACC", "ACCX"]

# relative weights of the generated operations
WEIGHTS = {
    "MOVE": 10, "MOVEL": 4, "DISP": 3, "ENC": 5,
    "ADD": 4, "SUB": 4, "MUL": 3, "DIVI": 3, "ADDG": 3, "SUBG": 3, "MULG": 3, "DIVIG": 2, "DIVBG": 3,
    "DIVBR": 4, "DIVIR": 2, "COMP": 10, "NX": 3, "XN": 4, "XX": 3, "XL": 2, "CMP": 3, "XCMP": 2,
    "ACC": 5, "ACCX": 2,
}

PRINTABLE = bytes(range(0x20, 0x7F))


class Gen:
    def __init__(self, seed: int, p_scaling: float = 0.06) -> None:
        self.r = random.Random(seed)
        self.p_scaling = p_scaling

    # ---- fields ---------------------------------------------------------------------------------
    def numf(self, usage: int | None = None, max_digits: int = 18, integer: bool = False) -> NumF:
        r = self.r
        if usage is None:
            usage = r.choices([DISPLAY, COMP, COMP3, COMP5], [40, 20, 25, 15])[0]
        digits = r.choice([1, 2, 3, 4, 5, 9, 10, 18] if r.random() < 0.35 else range(1, max_digits + 1))
        digits = min(digits, max_digits)
        if integer:
            scale = 0
            if usage == DISPLAY and r.random() < self.p_scaling:
                scale = -r.randint(1, 3)
        elif r.random() < self.p_scaling and usage == DISPLAY:
            # P scaling only on DISPLAY items: libcob mishandles P in COMP-3/binary items in
            # several paths (see docs/RUNTIME_API.md, limitations)
            scale = r.choice([-r.randint(1, 3), digits + r.randint(1, 3)])
        else:
            scale = r.choice([0, 0, digits, r.randint(0, digits)]) if r.random() < 0.5 else r.randint(0, digits)
        signed = r.random() < 0.55
        lead = sep = False
        if signed and usage == DISPLAY:
            k = r.choices([0, 1, 2, 3], [55, 15, 15, 15])[0]
            lead, sep = k in (1, 3), k in (2, 3)
        return NumF(digits, scale, signed, usage, lead, sep)

    def value(self, f: NumF, allow_zero: bool = True) -> int:
        """An unscaled value in the item's PIC domain, biased to boundaries."""
        r = self.r
        mx = f.max_u()
        k = r.random()
        if k < 0.08:
            v = 0
        elif k < 0.16:
            v = mx
        elif k < 0.22:
            v = 1
        elif k < 0.30:
            v = int("5" * r.randint(1, f.digits)) if r.random() < 0.5 else 5 * 10 ** r.randint(0, f.digits - 1)
        elif k < 0.40:
            v = r.randint(0, min(mx, 1000))
        else:
            n = r.randint(1, f.digits)
            v = r.randint(10 ** (n - 1), 10**n - 1)
        if f.signed and r.random() < 0.5:
            v = -v
        if v == 0 and not allow_zero:
            v = 1
        return v

    def alnf(self, max_len: int = 24) -> AlnF:
        return AlnF(self.r.randint(1, max_len), self.r.random() < 0.3)

    def text(self, n: int, digits_only: bool = False) -> bytes:
        r = self.r
        if digits_only:
            return bytes(r.choice(b"0123456789") for _ in range(n))
        k = r.random()
        if k < 0.1:
            return b""
        if k < 0.2:
            return b" " * n
        chars = b"0123456789" if k < 0.45 else b"ABCxyz 019-+.," if k < 0.6 else PRINTABLE.replace(b'"', b"")
        return bytes(r.choice(chars) for _ in range(n))

    def numtext(self, f: NumF) -> bytes:
        """Text for ACCEPT / alphanumeric->numeric: canonical, overlong, spaced or invalid."""
        r = self.r
        k = r.random()
        if k < 0.45:
            v = self.value(f)
            return lit_text(v, max(f.scale, 0) if r.random() < 0.8 else r.randint(0, 4)).encode()
        if k < 0.6:  # overlong / more digits
            ip = str(r.randint(0, 10 ** r.randint(1, 20)))
            fp = str(r.randint(0, 10 ** r.randint(0, 6))) if r.random() < 0.6 else ""
            s = ("-" if r.random() < 0.4 else "") + ip + ("." + fp if fp else "")
            return s.encode()
        if k < 0.75:  # spaces, signs, separators
            core = str(r.randint(0, 10**8))
            pieces = [" " * r.randint(0, 3), r.choice(["", "+", "-", " -"]), core[: r.randint(1, len(core))],
                      r.choice(["", ",5", ".", ".25", " ", ".1.2", "-", "5-"])]
            return "".join(pieces).encode()
        if k < 0.85:
            return r.choice([b"abc", b"1a2", b"1e3", b"--5", b"12.3.4", b"5-", b"+", b"-", b".", b"-0",
                             b"0", b"-0.00", b" 12 34", b"1,234.5"])
        return self.text(r.randint(0, 12))

    # ---- expressions --------------------------------------------------------------------------
    def expr(self, operands: int, depth: int = 0) -> list[str]:
        """RPN over $1..$n operands, numeric literals (#lit), + - * / and ~ (negate)."""
        r = self.r
        if depth >= 3 or (depth > 0 and r.random() < 0.35):
            if r.random() < 0.18:
                lit = r.choice(["1", "2", "3", "7", "10", "100", "0.5", "1.5", "0.01", "3.14159", "12.25", "0"])
                return ["#" + lit]
            return [f"${r.randint(1, operands)}"]
        op = r.choices(["+", "-", "*", "/", "~"], [30, 25, 25, 20, 5])[0]
        if op == "~":
            return [*self.expr(operands, depth + 1), "~"]
        a = self.expr(operands, depth + 1)
        b = self.expr(operands, depth + 1)
        if all(t.startswith("#") for t in a + b if t[0] in "#$"):
            b = [f"${r.randint(1, operands)}"]  # avoid literal-only subtrees (cobc folds constants)
        return [*a, *b, op]

    # ---- cases --------------------------------------------------------------------------------
    def case(self, cid: int, op: str | None = None) -> Case:
        r = self.r
        if op is None:
            op = r.choices(list(WEIGHTS), list(WEIGHTS.values()))[0]
        rnd = r.choices(range(10), [38, 22, 10, 4, 5, 4, 4, 4, 4, 5])[0]
        size = r.choices([0, 1, 2, 3], [45, 35, 10, 10])[0]
        if op in ("MOVE", "DISP", "ENC", "MOVEL"):
            a = self.numf()
            if op in ("MOVE", "MOVEL"):
                # GnuCOBOL reads past the source when a DISPLAY item/literal is moved to a
                # leading-P COMP-3 item (cob_move_display_to_packed): undefined, not generated
                while a.usage == COMP3 and a.scale > a.digits:
                    a = self.numf()
            if op == "MOVE":
                b = self.numf()
                while ((b.usage == COMP3 and b.scale > b.digits and a.usage == DISPLAY)
                       or (a.usage in (COMP, COMP5) and abs(a.scale - b.scale) > 18)):
                    # the second: libcob indexes its 10**n table past 10**18 (SIGFPE / garbage)
                    b = self.numf()
                return Case(cid, op, [(a, self.value(a)), (b, self.value(b))])
            if op == "MOVEL":
                b = self.numf()
                lit = lit_text(self.value(b) * (10 ** r.randint(0, 3)) if r.random() < 0.3 else self.value(b),
                               b.scale if r.random() < 0.7 else r.randint(0, 4))
                if r.random() < 0.05:
                    lit = r.choice(["-0", "0", "-0.0", "-0.5"])
                return Case(cid, op, [(a, self.value(a))], extra=[lit])
            return Case(cid, op, [(a, self.value(a))])
        if op in ("ADD", "SUB", "MUL", "DIVI", "ADDG", "SUBG", "MULG", "DIVIG", "DIVBG"):
            a, b = self.numf(), self.numf()
            fl: list[Field] = [(a, self.value(a)), (b, self.value(b))]
            if op.endswith("G"):
                c = self.numf()
                fl.append((c, self.value(c)))
            return Case(cid, op, fl, rnd, size)
        if op in ("DIVBR", "DIVIR"):
            a, b, c, d = self.numf(), self.numf(), self.numf(), self.numf()
            rnd = rnd if rnd != 8 else 1
            return Case(cid, op, [(a, self.value(a)), (b, self.value(b)), (c, self.value(c)), (d, self.value(d))],
                        rnd, size)
        if op == "COMP":
            n = r.randint(1, 4)
            fl = []
            t = self.numf()
            fl.append((t, self.value(t)))
            for _ in range(n):
                f = self.numf()
                fl.append((f, self.value(f)))
            return Case(cid, op, fl, rnd, size, extra=self.expr(n))
        if op == "NX":
            a = self.numf(integer=True)
            x = self.alnf()
            return Case(cid, op, [(a, self.value(a)), (x, self.text(x.length))])
        if op == "XN":
            x = self.alnf()
            b = self.numf()
            while b.scale > b.digits:  # leading-P targets read past the text in GnuCOBOL (undefined)
                b = self.numf()
            t = self.numtext(b)[: x.length]
            return Case(cid, op, [(x, t), (b, self.value(b))])
        if op == "XX":
            x, y = self.alnf(), self.alnf()
            return Case(cid, op, [(x, self.text(x.length)), (y, self.text(y.length))])
        if op == "XL":
            x = self.alnf()
            return Case(cid, op, [(x, self.text(x.length))], extra=[self.text(r.randint(1, 26)).hex() or "20"])
        if op == "CMP":
            a, b = self.numf(), self.numf()
            va = self.value(a)
            vb = self.value(b)
            if r.random() < 0.3 and b.scale == a.scale:
                vb = max(min(va, b.max_u()), -b.max_u() if b.signed else 0)
            return Case(cid, op, [(a, va), (b, vb)])
        if op == "XCMP":
            x, y = self.alnf(), self.alnf()
            tx = self.text(x.length)
            ty = tx[: y.length] if r.random() < 0.4 else self.text(y.length)
            return Case(cid, op, [(x, tx), (y, ty)])
        if op == "ACC":
            f = self.numf()
            while f.scale > f.digits:
                f = self.numf()
            line: bytes | None = self.numtext(f)
            return Case(cid, op, [(f, self.value(f))], stdin=[line])
        if op == "ACCX":
            x = self.alnf()
            return Case(cid, op, [(x, self.text(x.length))], stdin=[self.text(r.randint(0, 30))])
        raise ValueError(op)

    def batch(self, first_id: int, n: int, ops: list[str] | None = None) -> list[Case]:
        out = []
        for i in range(n):
            op = None if ops is None else ops[i % len(ops)]
            out.append(self.case(first_id + i, op))
        return out


def eof_cases(first_id: int) -> list[Case]:
    """ACCEPTs after stdin is exhausted (placed last in a program): the item is set to zero/spaces."""
    return [
        Case(first_id, "ACC", [(NumF(5, 2, True, DISPLAY), -12345)], stdin=[None]),
        Case(first_id + 1, "ACC", [(NumF(4, 0, True, COMP3), 77)], stdin=[None]),
        Case(first_id + 2, "ACCX", [(AlnF(6, False), b"ABCDEF")], stdin=[None]),
    ]
