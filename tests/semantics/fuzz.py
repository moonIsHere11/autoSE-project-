"""Random COBOL programs for differential testing of the interpreter against GnuCOBOL.

Each generated program declares random numeric (DISPLAY / COMP / COMP-3 / COMP-5, signed or not,
sign clauses, decimal scales), numeric-edited and alphanumeric items, each wrapped in its own group
so that `DISPLAY G-n` shows the item's raw bytes. Every statement (MOVE, ADD, SUBTRACT, MULTIPLY,
DIVIDE [REMAINDER], COMPUTE with nested expressions, ROUNDED, ON SIZE ERROR, IF with relations)
is followed by a DISPLAY of the raw bytes and the formatted value of its receiving items, so one
run compares hundreds of operations byte for byte. `accept_program` builds a program that ACCEPTs
random text into random items (de-editing rules) for use with random stdin cases.

Used by `python -m tools.validate_interp --fuzz N` and tests/semantics/test_fuzz.py.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class Item:
    name: str
    kind: str  # num | edit | alnum
    pic: str
    usage: str = "DISPLAY"
    signed: bool = False
    int_digits: int = 0
    scale: int = 0
    clause: str = ""

    @property
    def digits(self) -> int:
        return self.int_digits + self.scale

    def decl(self) -> str:
        parts = [f"PIC {self.pic}"]
        if self.usage != "DISPLAY":
            parts.append(self.usage)
        if self.clause:
            parts.append(self.clause)
        return " ".join(parts)


def _num_item(rng: random.Random, name: str, usage: str | None = None) -> Item:
    usage = usage or rng.choice(["DISPLAY", "DISPLAY", "COMP", "COMP-3", "COMP-3", "COMP-5"])
    total = rng.randint(1, 18 if usage != "COMP-5" else 9)
    scale = rng.randint(0, min(total, 6)) if rng.random() < 0.6 else 0
    ints = total - scale
    signed = rng.random() < 0.6
    pic = ("S" if signed else "") + (f"9({ints})" if ints else "") + (f"V9({scale})" if scale else "")
    clause = ""
    if usage == "DISPLAY" and signed and rng.random() < 0.3:
        clause = rng.choice(["SIGN LEADING", "SIGN TRAILING", "SIGN LEADING SEPARATE", "SIGN TRAILING SEPARATE"])
    return Item(name, "num", pic, usage, signed, ints, scale, clause)


def _edit_item(rng: random.Random, name: str) -> Item:
    ints = rng.randint(1, 7)
    scale = rng.choice([0, 0, 1, 2, 3])
    lead = rng.choice(["Z", "Z", "*", "+", "-", "$", "9"])
    head = lead * max(1, ints - 1) + "9"
    if lead in "+-$" and ints >= 2:
        head = lead * ints + "9"
    if rng.random() < 0.3 and len(head) > 4:
        head = head[:-4] + "," + head[-4:]
    pic = head + ("." + "9" * scale if scale else "")
    tail = rng.choice(["", "", "", "-", "+", "CR", "DB"]) if lead not in "+-" else ""
    pic += tail
    return Item(name, "edit", pic, signed=bool(tail) or lead in "+-", int_digits=ints, scale=scale)


def _alnum_item(rng: random.Random, name: str) -> Item:
    n = rng.randint(1, 12)
    just = rng.random() < 0.2
    return Item(name, "alnum", f"X({n})", clause="JUSTIFIED RIGHT" if just else "")


def _literal(rng: random.Random, it: Item | None, big: bool = False) -> str:
    """A numeric literal, usually within the item's PICTURE, sometimes overflowing it."""
    ints = it.int_digits if it is not None else rng.randint(0, 6)
    scale = it.scale if it is not None else rng.randint(0, 3)
    if big or rng.random() < 0.15:
        ints += rng.randint(1, 3)
        scale += rng.randint(0, 2)
    ints = min(ints, 17)
    scale = min(scale, 18 - max(ints, 1)) if ints + scale > 18 else scale
    ip = str(rng.randint(0, 10 ** ints - 1)) if ints else "0"
    if rng.random() < 0.2:
        ip = "0"
    fp = "".join(rng.choice("0123456789") for _ in range(scale))
    if rng.random() < 0.15 and fp:
        fp = fp[:-1] + "5"
    sign = "-" if (rng.random() < 0.35) else ""
    if rng.random() < 0.05:
        sign = "+"
    return f"{sign}{ip}{'.' + fp if fp else ''}"


class _Gen:
    def __init__(self, seed: int, n_stmts: int) -> None:
        self.rng = random.Random(seed)
        self.seed = seed
        self.n = n_stmts
        self.items: list[Item] = []
        self.lines: list[str] = []
        self.k = 0

    def item(self, kind: str) -> Item:
        name = f"F{len(self.items):03d}"
        if kind == "num":
            it = _num_item(self.rng, name)
        elif kind == "edit":
            it = _edit_item(self.rng, name)
        else:
            it = _alnum_item(self.rng, name)
        self.items.append(it)
        return it

    def show(self, *its: Item) -> None:
        self.k += 1
        parts = [f'"S{self.k:03d} "']
        for it in its:
            parts += [f"G{it.name[1:]}", '"|"', it.name, '"|"']
        self.emit("DISPLAY " + " ".join(parts))

    def emit(self, stmt: str) -> None:
        self.lines.append(stmt)

    def setv(self, it: Item) -> None:
        if it.kind == "alnum":
            txt = "".join(self.rng.choice("AB12 -.x") for _ in range(self.rng.randint(0, 8)))
            self.emit(f'MOVE "{txt}" TO {it.name}')
        else:
            self.emit(f"MOVE {_literal(self.rng, it)} TO {it.name}")

    def opnd(self) -> tuple[str, Item | None]:
        if self.rng.random() < 0.45:
            return _literal(self.rng, None), None
        it = self.item("num")
        self.setv(it)
        return it.name, it

    def expr(self, depth: int = 0) -> str:
        r = self.rng.random()
        if depth >= 3 or r < 0.35:
            s, _ = self.opnd()
            if s.startswith("-") and depth > 0:
                s = f"({s})"
            return s
        op = self.rng.choice(["+", "-", "*", "/", "*", "+", "**"])
        if op == "**":
            base = self.expr(depth + 1)
            return f"({base}) ** {self.rng.choice(['0', '1', '2', '3', '-1', '2'])}"
        return f"({self.expr(depth + 1)} {op} {self.expr(depth + 1)})"

    def stmt(self) -> None:
        rng = self.rng
        kind = rng.choice(["move", "move", "add", "add", "sub", "mul", "div", "divrem", "compute", "compute",
                           "compute", "addlist", "giving", "if", "if"])
        size_err = rng.random() < 0.3
        rounded = " ROUNDED" if rng.random() < 0.35 else ""
        se = ' ON SIZE ERROR DISPLAY "SE" NOT ON SIZE ERROR DISPLAY "OK"' if size_err else ""
        if kind == "move":
            src_kind = rng.choice(["num", "num", "alnum", "lit", "lit"])
            dst = self.item(rng.choice(["num", "num", "edit", "alnum"]))
            if dst.kind == "alnum" and src_kind == "num":
                src_kind = "intnum"
            if src_kind == "lit":
                src = _literal(rng, dst if dst.kind == "num" else None, big=rng.random() < 0.3)
                if dst.kind == "alnum":
                    src = src.lstrip("+-").split(".")[0]
            elif src_kind == "intnum":
                s_it = self.item("num")
                if s_it.scale:
                    s_it.pic = ("S" if s_it.signed else "") + f"9({s_it.int_digits or 1})"
                    s_it.int_digits, s_it.scale = s_it.int_digits or 1, 0
                self.setv(s_it)
                src = s_it.name
            else:
                s_it = self.item(src_kind)
                if s_it.kind == "alnum" and dst.kind != "alnum":
                    txt = rng.choice(["123", " 12", "-4.5", "1.2.3", "+7", "  ", "9" * rng.randint(1, 12),
                                      "12a", "0.05", "-0"])
                    self.emit(f'MOVE "{txt}" TO {s_it.name}')
                else:
                    self.setv(s_it)
                src = s_it.name
            self.emit(f"MOVE {src} TO {dst.name}")
            self.show(dst)
        elif kind in ("add", "sub", "mul", "div"):
            t = self.item("num")
            self.setv(t)
            s, _ = self.opnd()
            verb = {"add": f"ADD {s} TO", "sub": f"SUBTRACT {s} FROM", "mul": f"MULTIPLY {s} BY",
                    "div": f"DIVIDE {s} INTO"}[kind]
            self.emit(f"{verb} {t.name}{rounded}{se}")
            self.show(t)
        elif kind == "divrem":
            q = self.item("num")
            r = self.item("num")
            a, _ = self.opnd()
            b, _ = self.opnd()
            self.setv(q)
            self.setv(r)
            self.emit(f"DIVIDE {a} BY {b} GIVING {q.name}{rounded} REMAINDER {r.name}{se}")
            self.show(q, r)
        elif kind == "compute":
            t = self.item(rng.choice(["num", "num", "num", "edit"]))
            if t.kind == "num":
                self.setv(t)
            e = self.expr()
            self.emit(f"COMPUTE {t.name}{rounded} = {e}{se}")
            self.show(t)
        elif kind == "addlist":
            t = self.item("num")
            self.setv(t)
            a, _ = self.opnd()
            b, _ = self.opnd()
            verb = rng.choice(["ADD", "SUBTRACT"])
            self.emit(f"{verb} {a} {b} {'TO' if verb == 'ADD' else 'FROM'} {t.name}{rounded}{se}")
            self.show(t)
        elif kind == "giving":
            t = self.item(rng.choice(["num", "num", "edit"]))
            a, _ = self.opnd()
            b, _ = self.opnd()
            verb = rng.choice(["ADD {a} TO {b}", "SUBTRACT {a} FROM {b}", "MULTIPLY {a} BY {b}",
                               "DIVIDE {a} INTO {b}", "DIVIDE {a} BY {b}"]).format(a=a, b=b)
            self.emit(f"{verb} GIVING {t.name}{rounded}{se}")
            self.show(t)
        else:
            lhs = self.item(rng.choice(["num", "num", "alnum"]))
            self.setv(lhs)
            if lhs.kind == "num":
                b, _ = self.opnd()
            else:
                b = rng.choice(['"AB"', "SPACES", '"12"', "ZERO", '" "'])
            op = rng.choice(["=", "<", ">", "NOT =", ">=", "<=", "NOT >"])
            self.emit(f'IF {lhs.name} {op} {b} DISPLAY "T" ELSE DISPLAY "F" END-IF')

    def program(self, pid: str) -> str:
        for _ in range(self.n):
            self.stmt()
        ws = []
        for it in self.items:
            ws.append(f"       01 G{it.name[1:]}.")
            ws.append(f"          05 {it.name} {it.decl()}.")
        proc = ["           " + ln for ln in self.lines]
        return "\n".join([
            "       IDENTIFICATION DIVISION.",
            f"       PROGRAM-ID. {pid}.",
            "       DATA DIVISION.",
            "       WORKING-STORAGE SECTION.",
            *ws,
            "       PROCEDURE DIVISION.",
            "       MAIN-PARA.",
            *_wrap(proc),
            "           STOP RUN.",
            "",
        ])


def _wrap(lines: list[str]) -> list[str]:
    """Keep every line inside columns 8-72 of fixed format."""
    out: list[str] = []
    for ln in lines:
        while len(ln) > 72:
            cut = ln.rfind(" ", 12, 72)
            while ln[:cut].count('"') % 2 == 1:
                cut = ln.rfind(" ", 12, cut)
            out.append(ln[:cut])
            ln = "               " + ln[cut + 1:]
        out.append(ln)
    return out


def random_program(seed: int, n_stmts: int = 120, pid: str | None = None) -> str:
    return _Gen(seed, n_stmts).program(pid or f"FZ{seed:06d}")


def accept_program(seed: int, n_items: int = 12, pid: str | None = None) -> tuple[str, list[Item]]:
    g = _Gen(seed, 0)
    its: list[Item] = []
    for _ in range(n_items):
        its.append(g.item(g.rng.choice(["num", "num", "num", "alnum"])))
    for it in its:
        g.emit(f"ACCEPT {it.name}")
        g.show(it)
    return g.program(pid or f"FA{seed:06d}"), its


def accept_stdin(seed: int, n_lines: int) -> bytes:
    rng = random.Random(seed)
    forms = ["{d}", "-{d}", "+{d}", " {d}", "{d}.{f}", "-{d}.{f}", ".{f}", "{d}-", "abc", "", "  ",
             "1,234", "{d}{d}{d}", "- {d}", "12.3.4", "{d}e1", "0", "-0"]
    lines = []
    for _ in range(n_lines):
        f = rng.choice(forms)
        lines.append(f.format(d=rng.randint(0, 99999), f=rng.randint(0, 999)))
    return ("\n".join(lines) + "\n").encode()
