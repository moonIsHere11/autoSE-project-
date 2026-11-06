"""Python driver: interpret a difftest op script with the Python cobolrt (in-process).

The Java and Go drivers (tests/runtimes/drivers/) implement the same interpreter; all three must
print exactly what the GnuCOBOL program prints.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[2] / "runtimes" / "python"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from cobolrt import CobolDecimal, Dec, NumPic, PicX, Round, SizeError, Usage, divide_remainder  # noqa: E402

REC_LEN = 40
Item = CobolDecimal | PicX


def parse_field(spec: str) -> Item:
    parts = spec.split(",")
    if parts[0] == "N":
        d, s, sg, us, ld, sp = (int(x) for x in parts[1:7])
        pic = NumPic(d, s, bool(sg), Usage(us), bool(ld), bool(sp))
        item = CobolDecimal(pic)
        item.move(parts[7])
        return item
    ln, js = int(parts[1]), int(parts[2])
    x = PicX(ln, bool(js))
    x.move(b"" if parts[3] == "-" else bytes.fromhex(parts[3]))
    return x


def _round(code: int) -> Round:
    return Round(code)


def _size(code: int) -> SizeError:
    return {0: SizeError.NONE, 1: SizeError.ON, 2: SizeError.NOT_ONLY, 3: SizeError.ON}[code]


def _show(out: list[bytes], cid: str, tag: str, item: Item) -> None:
    data = item.display()
    raw = item.encode()
    out.append(f"#{cid} {tag} ".encode() + data + b"|" + raw.hex().upper().encode() + b"\n")


def _num(item: Item) -> CobolDecimal:
    assert isinstance(item, CobolDecimal)
    return item


def _alnum(item: Item) -> PicX:
    assert isinstance(item, PicX)
    return item


def eval_rpn(rpn: list[str], items: list[Item]) -> Dec:
    stack: list[Dec] = []
    for t in rpn:
        if t.startswith("$"):
            stack.append(_num(items[int(t[1:])]).dec())
        elif t.startswith("#"):
            stack.append(Dec.literal(t[1:]))
        elif t == "~":
            stack.append(stack.pop().neg())
        else:
            b = stack.pop()
            a = stack.pop()
            stack.append({"+": a.add, "-": a.sub, "*": a.mul, "/": a.div}[t](b))
    return stack[0]


def run_case(line: str, stdin: Iterator[bytes], records: list[bytes]) -> list[bytes]:
    head, _, extra_s = line.partition(" -- ")
    toks = head.split()
    cid, op, rc, sc = toks[0], toks[1], int(toks[2]), int(toks[3])
    items = [parse_field(s) for s in toks[4:]]
    extra = extra_s.split() if extra_s else []
    rnd, size = _round(rc), _size(sc)
    out: list[bytes] = []

    def status(err: bool) -> None:
        if err and sc in (1, 3):
            out.append(f"#{cid} SE\n".encode())
        if not err and sc in (1, 2):
            out.append(f"#{cid} NSE\n".encode())

    if op == "MOVE":
        items[1].move(_num(items[0]))
        _show(out, cid, "R1", items[1])
    elif op == "MOVEL":
        _num(items[0]).move(extra[0])
        _show(out, cid, "R1", items[0])
    elif op == "DISP":
        _show(out, cid, "R1", items[0])
    elif op == "ENC":
        a = _num(items[0])
        records.append(a.encode() + b"*" * (REC_LEN - a.pic.byte_length))
        _show(out, cid, "R1", a)
    elif op in ("ADD", "SUB", "MUL", "DIVI"):
        a, b = _num(items[0]), _num(items[1])
        fn = {"ADD": b.add, "SUB": b.subtract, "MUL": b.multiply, "DIVI": b.divide}[op]
        status(fn(a, rnd, size))
        _show(out, cid, "R1", b)
    elif op in ("ADDG", "SUBG", "MULG", "DIVIG", "DIVBG"):
        a, b, c = _num(items[0]), _num(items[1]), _num(items[2])
        da, db = a.dec(), b.dec()
        val = {"ADDG": lambda: da.add(db), "SUBG": lambda: db.sub(da), "MULG": lambda: da.mul(db),
               "DIVIG": lambda: db.div(da), "DIVBG": lambda: da.div(db)}[op]()
        status(c.compute(val, rnd, size))
        _show(out, cid, "R1", c)
    elif op in ("DIVBR", "DIVIR"):
        a, b, q, r = (_num(x) for x in items)
        dividend, divisor = (a, b) if op == "DIVBR" else (b, a)
        status(divide_remainder(dividend, divisor, q, r, rnd, size))
        _show(out, cid, "R1", q)
        _show(out, cid, "R2", r)
    elif op == "COMP":
        t = _num(items[0])
        status(t.compute(eval_rpn(extra, items), rnd, size))
        _show(out, cid, "R1", t)
    elif op == "NX":
        _alnum(items[1]).move(_num(items[0]))
        _show(out, cid, "R1", items[1])
    elif op == "XN":
        _num(items[1]).move(_alnum(items[0]))
        _show(out, cid, "R1", items[1])
    elif op == "XX":
        _alnum(items[1]).move(_alnum(items[0]))
        _show(out, cid, "R1", items[1])
    elif op == "XL":
        _alnum(items[0]).move(bytes.fromhex(extra[0]))
        _show(out, cid, "R1", items[0])
    elif op in ("CMP", "XCMP"):
        x, y = items
        r = _num(x).compare(_num(y)) if op == "CMP" else _alnum(x).compare(_alnum(y))
        out.append(f"#{cid} {'LT' if r < 0 else 'EQ' if r == 0 else 'GT'}\n".encode())
    elif op in ("ACC", "ACCX"):
        items[0].accept(next(stdin, None))
        _show(out, cid, "R1", items[0])
    else:
        raise ValueError(op)
    return out


def run_script(script: str, stdin: bytes) -> tuple[bytes, bytes]:
    """Returns (stdout bytes, ENC.DAT bytes)."""
    lines = stdin.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    it = iter(lines)
    records: list[bytes] = []
    out: list[bytes] = []
    for line in script.splitlines():
        if line.strip():
            out += run_case(line, it, records)
    return b"".join(out), b"".join(records)
