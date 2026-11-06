"""Tree-sitter based mutation engine.

Each operator plants one COBOL-semantic bug class from spec section 9 into a *correct* translation:

| category      | spec wording                                   | how it is planted (Java)                              |
|---------------|------------------------------------------------|-------------------------------------------------------|
| rounding      | drop ROUNDED, or use HALF_EVEN instead         | `RoundingMode.HALF_UP` → `HALF_EVEN` / `DOWN`;         |
|               |                                                | `(x + 5) / 10` → `x / 10` (manual half-up rounding)    |
| truncation    | remove truncation, or use a wider field        | `x % 10^k` → `x`; `x % 10^k` → `x % 10^(k+1)`          |
| sign          | drop the sign (abs)                            | `-x` → `x`; `x.negate()` → `x`; `Math.abs` insertion   |
| scale         | shift the scale by one place                   | `* 10^k`, `/ 10^k`, `setScale(n)`, `movePointLeft(n)` ±1 |
| loop_bound    | off-by-one in a loop bound                     | `<` ↔ `<=`, `>` ↔ `>=` in loop conditions              |
| comparison    | flip a comparison                              | relational operator flipped in other conditions        |
| padding       | pad on the wrong side                          | `%-Ns` ↔ `%Ns`; `padRight` ↔ `padLeft` (if both exist) |
| size_error    | ignore ON SIZE ERROR                           | `if (x > 99999)`-style overflow guards → `if (false)`  |
| double        | replace a decimal with double                  | `a * b` → `(long) ((double) a * b)`; BigDecimal ops via |
|               |                                                | `doubleValue()`                                        |
| branch_swap   | swap two branches                              | `if (c) A else B` → `if (c) B else A`                  |

Mutants that do not compile are "stillborn" and are excluded from catch-rate denominators by the
self-test (they would be caught by T0a trivially, which says nothing about the verifier).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from tree_sitter import Node

from verifier.langpacks import ts

CATEGORIES: dict[str, str] = {
    "rounding": "drop ROUNDED, or use HALF_EVEN instead",
    "truncation": "remove truncation, or use a wider field",
    "sign": "drop the sign (abs)",
    "scale": "shift the scale by one place",
    "loop_bound": "off-by-one in a loop bound",
    "comparison": "flip a comparison",
    "padding": "pad on the wrong side",
    "size_error": "ignore ON SIZE ERROR",
    "double": "replace a decimal with double",
    "branch_swap": "swap two branches",
}

SUFFIXES = {"java": (".java",), "python": (".py",), "go": (".go",)}
_SKIP_DIRS = ("/test/", "/tests/", "/src/test/", "/.verifier-build/", "/vendor/", "/__pycache__/")


@dataclass(frozen=True)
class Mutant:
    id: str
    lang: str
    operator: str
    category: str
    file: str
    line: int
    start: int
    end: int
    original: str
    replacement: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Mutant:
        return Mutant(**d)


@dataclass(frozen=True)
class Edit:
    start: int
    end: int
    replacement: str
    operator: str
    category: str
    description: str
    line: int


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------
def int_literal(raw: str) -> int | None:
    s = raw.strip().replace("_", "").rstrip("lL")
    if not s or not s.isdigit():
        return None
    return int(s)


def pow10_exp(n: int | None) -> int | None:
    """k if n == 10**k with k >= 1."""
    if n is None or n < 10:
        return None
    s = str(n)
    return len(s) - 1 if s[0] == "1" and set(s[1:]) == {"0"} else None


def nines_exp(n: int | None) -> int | None:
    """k if n == 10**k - 1 with k >= 1."""
    if n is None or n < 9:
        return None
    s = str(n)
    return len(s) if set(s) == {"9"} else None


def five_scaled(n: int | None) -> bool:
    if n is None or n < 5:
        return False
    s = str(n)
    return s[0] == "5" and set(s[1:]) <= {"0"}


def unparen(n: Node) -> Node:
    while n.type in ("parenthesized_expression",) and n.named_child_count == 1:
        child = n.named_children[0]
        n = child
    return n


def _lit_suffix(raw: str) -> str:
    return "L" if raw.rstrip().endswith(("L", "l")) else ""


_FLIP = {"<": ">=", "<=": ">", ">": "<=", ">=": "<", "==": "!=", "!=": "=="}
_OFF_BY_ONE = {"<": "<=", "<=": "<", ">": ">=", ">=": ">"}


# ---------------------------------------------------------------------------------------------
# Java
# ---------------------------------------------------------------------------------------------
_JAVA_INT = ("decimal_integer_literal",)


def _java_lit(n: Node | None) -> int | None:
    if n is None:
        return None
    n = unparen(n)
    return int_literal(ts.text(n)) if n.type in _JAVA_INT else None


def _in_loop_condition(node: Node) -> bool:
    cur: Node | None = node
    while cur is not None and cur.parent is not None:
        par = cur.parent
        if par.type in ("for_statement", "while_statement", "do_statement"):
            cond = par.child_by_field_name("condition")
            return cond is not None and cond.start_byte <= node.start_byte and node.end_byte <= cond.end_byte
        if par.type in ("block", "method_declaration", "class_body", "lambda_expression"):
            return False
        cur = par
    return False


def _java_edits(root: Node, src: bytes, methods: set[str]) -> Iterator[Edit]:
    for n in ts.walk(root):
        t = n.type
        ln = ts.line(n)
        if t == "binary_expression":
            op_node = n.child_by_field_name("operator")
            left, right = n.child_by_field_name("left"), n.child_by_field_name("right")
            if op_node is None or left is None or right is None:
                continue
            op = ts.text(op_node)
            if op in _FLIP:
                if _in_loop_condition(n) and op in _OFF_BY_ONE:
                    yield Edit(op_node.start_byte, op_node.end_byte, _OFF_BY_ONE[op], "LOOP_BOUND_OFF_BY_ONE",
                               "loop_bound", f"loop condition `{op}` → `{_OFF_BY_ONE[op]}`", ln)
                else:
                    yield Edit(op_node.start_byte, op_node.end_byte, _FLIP[op], "COMPARISON_FLIP", "comparison",
                               f"comparison `{op}` → `{_FLIP[op]}`", ln)
            rlit = _java_lit(right)
            llit = _java_lit(left)
            if op == "%" and pow10_exp(rlit) is not None:
                yield Edit(n.start_byte, n.end_byte, f"({ts.text(left)})", "TRUNCATION_REMOVED", "truncation",
                           f"`{ts.text(n)}` → `{ts.text(left)}` (no high-order truncation)", ln)
                yr = unparen(right)
                yield Edit(yr.start_byte, yr.end_byte, f"{(rlit or 0) * 10}{_lit_suffix(ts.text(yr))}",
                           "TRUNCATION_WIDER", "truncation", f"modulus {rlit} → {(rlit or 0) * 10} (wider field)", ln)
            if op in ("*", "/"):
                for lit, side in ((rlit, right), (llit, left)):
                    if pow10_exp(lit) is not None:
                        s = unparen(side)
                        yield Edit(s.start_byte, s.end_byte, f"{(lit or 0) * 10}{_lit_suffix(ts.text(s))}",
                                   "SCALE_SHIFT", "scale", f"scale factor {lit} → {(lit or 0) * 10}", ln)
                        break
                if rlit is None and llit is None:
                    yield Edit(n.start_byte, n.end_byte,
                               f"((long) ((double) ({ts.text(left)}) {op} ({ts.text(right)})))",
                               "DOUBLE_ARITHMETIC", "double", f"`{ts.text(n)}` evaluated in double", ln)
            if op == "/":
                inner = unparen(left)
                if inner.type == "binary_expression":
                    iop = inner.child_by_field_name("operator")
                    il, ir = inner.child_by_field_name("left"), inner.child_by_field_name("right")
                    if iop is not None and il is not None and ts.text(iop) in ("+", "-") and five_scaled(_java_lit(ir)):
                        yield Edit(inner.start_byte, inner.end_byte, ts.text(il), "ROUNDING_DROPPED", "rounding",
                                   f"half-up adjustment `{ts.text(inner)}` removed before division", ln)
        elif t == "unary_expression":
            op_node = n.child_by_field_name("operator")
            operand = n.child_by_field_name("operand")
            if op_node is not None and operand is not None and ts.text(op_node) == "-" \
                    and unparen(operand).type not in (*_JAVA_INT, "decimal_floating_point_literal"):
                yield Edit(n.start_byte, n.end_byte, f"({ts.text(operand)})", "SIGN_DROPPED", "sign",
                           f"`{ts.text(n)}` → `{ts.text(operand)}`", ln)
        elif t == "field_access":
            txt = ts.text(n)
            if txt in ("RoundingMode.HALF_UP", "java.math.RoundingMode.HALF_UP", "BigDecimal.ROUND_HALF_UP"):
                yield Edit(n.start_byte, n.end_byte, txt.replace("HALF_UP", "HALF_EVEN"), "ROUNDING_HALF_EVEN",
                           "rounding", "HALF_UP → HALF_EVEN", ln)
                yield Edit(n.start_byte, n.end_byte, txt.replace("HALF_UP", "DOWN"), "ROUNDING_DROPPED", "rounding",
                           "HALF_UP → DOWN (ROUNDED dropped)", ln)
        elif t == "method_invocation":
            name = ts.text(n.child_by_field_name("name"))
            obj = n.child_by_field_name("object")
            args = n.child_by_field_name("arguments")
            argv = list(args.named_children) if args is not None else []
            if name == "negate" and obj is not None and not argv:
                yield Edit(n.start_byte, n.end_byte, ts.text(obj), "SIGN_DROPPED", "sign", "`.negate()` removed", ln)
            elif name in ("setScale", "movePointLeft", "movePointRight", "scaleByPowerOfTen") and argv:
                v = _java_lit(argv[0])
                if v is not None:
                    a0 = unparen(argv[0])
                    yield Edit(a0.start_byte, a0.end_byte, str(v + 1), "SCALE_SHIFT", "scale",
                               f"`{name}({v}…)` → `{name}({v + 1}…)`", ln)
            elif name == "multiply" and obj is not None and len(argv) == 1:
                yield Edit(n.start_byte, n.end_byte,
                           f"new java.math.BigDecimal(({ts.text(obj)}).doubleValue() * ({ts.text(argv[0])}).doubleValue())",
                           "DOUBLE_ARITHMETIC", "double", "BigDecimal multiply done in double", ln)
            elif name == "divide" and obj is not None and len(argv) == 3:
                yield Edit(n.start_byte, n.end_byte,
                           f"new java.math.BigDecimal(({ts.text(obj)}).doubleValue() / ({ts.text(argv[0])}).doubleValue())"
                           f".setScale({ts.text(argv[1])}, {ts.text(argv[2])})",
                           "DOUBLE_ARITHMETIC", "double", "BigDecimal divide done in double", ln)
            for a, b in (("padRight", "padLeft"), ("rightPad", "leftPad"), ("padEnd", "padStart")):
                for x, y in ((a, b), (b, a)):
                    if name == x and y in methods:
                        nm = n.child_by_field_name("name")
                        assert nm is not None
                        yield Edit(nm.start_byte, nm.end_byte, y, "PAD_WRONG_SIDE", "padding", f"`{x}` → `{y}`", ln)
        elif t == "string_literal":
            raw = ts.text(n)
            m = re.search(r"%(-?)(\d+)s", raw)
            if m:
                new = raw[: m.start()] + ("%" + m.group(2) + "s" if m.group(1) else "%-" + m.group(2) + "s") + raw[m.end():]
                yield Edit(n.start_byte, n.end_byte, new, "PAD_WRONG_SIDE", "padding",
                           f"format `{m.group(0)}` padded on the other side", ln)
        elif t == "if_statement":
            cond = n.child_by_field_name("condition")
            cons = n.child_by_field_name("consequence")
            alt = n.child_by_field_name("alternative")
            if cond is not None and _is_size_guard(cond):
                yield Edit(cond.start_byte, cond.end_byte, "(false)", "SIZE_ERROR_IGNORED", "size_error",
                           f"overflow guard `{ts.text(cond)}` never taken", ln)
            if cond is not None and cons is not None and alt is not None:
                new = f"if {ts.text(cond)} {{ {ts.text(alt)} }} else {{ {ts.text(cons)} }}"
                yield Edit(n.start_byte, n.end_byte, new, "BRANCHES_SWAPPED", "branch_swap",
                           f"then/else branches of the `if` at line {ln} swapped", ln)


def _is_size_guard(cond: Node) -> bool:
    """A condition that compares against 10^k or 10^k - 1, or names a size-error flag."""
    txt = ts.text(cond)
    if re.search(r"(?i)size_?err|overflow|onsizeerror", txt):
        return True
    for c in ts.walk(cond):
        if c.type in ("binary_expression", "comparison_operator"):
            ops = [ts.text(x) for x in c.children if not x.is_named]
            if not any(o in ("<", "<=", ">", ">=") for o in ops):
                continue
            for x in c.named_children:
                v = int_literal(ts.text(unparen(x)))
                if (pow10_exp(v) or 0) >= 2 or (nines_exp(v) or 0) >= 2:
                    return True
    return False


# ---------------------------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------------------------
def _py_lit(n: Node | None) -> int | None:
    if n is None:
        return None
    n = unparen(n)
    return int_literal(ts.text(n)) if n.type == "integer" else None


def _python_edits(root: Node, src: bytes, methods: set[str]) -> Iterator[Edit]:
    for n in ts.walk(root):
        t = n.type
        ln = ts.line(n)
        if t == "comparison_operator":
            in_loop = _py_in_loop_cond(n)
            for tok in [c for c in n.children if not c.is_named]:
                op = ts.text(tok)
                if op not in _FLIP:
                    continue
                if in_loop and op in _OFF_BY_ONE:
                    yield Edit(tok.start_byte, tok.end_byte, _OFF_BY_ONE[op], "LOOP_BOUND_OFF_BY_ONE",
                               "loop_bound", f"loop condition `{op}` → `{_OFF_BY_ONE[op]}`", ln)
                else:
                    yield Edit(tok.start_byte, tok.end_byte, _FLIP[op], "COMPARISON_FLIP", "comparison",
                               f"comparison `{op}` → `{_FLIP[op]}`", ln)
        elif t == "call" and ts.text(n.child_by_field_name("function")) == "range":
            args = n.child_by_field_name("arguments")
            argv = list(args.named_children) if args is not None else []
            if argv:
                end = argv[1] if len(argv) >= 2 else argv[0]
                yield Edit(end.start_byte, end.end_byte, f"({ts.text(end)}) + 1", "LOOP_BOUND_OFF_BY_ONE",
                           "loop_bound", "range end + 1", ln)
        elif t == "binary_operator":
            op_node = n.child_by_field_name("operator")
            left, right = n.child_by_field_name("left"), n.child_by_field_name("right")
            if op_node is None or left is None or right is None:
                continue
            op = ts.text(op_node)
            rlit, llit = _py_lit(right), _py_lit(left)
            if op == "%" and pow10_exp(rlit) is not None:
                yield Edit(n.start_byte, n.end_byte, f"({ts.text(left)})", "TRUNCATION_REMOVED", "truncation",
                           f"`{ts.text(n)}` → `{ts.text(left)}`", ln)
                r = unparen(right)
                yield Edit(r.start_byte, r.end_byte, str((rlit or 0) * 10), "TRUNCATION_WIDER", "truncation",
                           f"modulus {rlit} → {(rlit or 0) * 10}", ln)
            if op in ("*", "//", "/"):
                for lit, side in ((rlit, right), (llit, left)):
                    if pow10_exp(lit) is not None:
                        s = unparen(side)
                        yield Edit(s.start_byte, s.end_byte, str((lit or 0) * 10), "SCALE_SHIFT", "scale",
                                   f"scale factor {lit} → {(lit or 0) * 10}", ln)
                        break
                if rlit is None and llit is None and op in ("*", "//"):
                    expr = f"int(float({ts.text(left)}) {'*' if op == '*' else '/'} float({ts.text(right)}))"
                    yield Edit(n.start_byte, n.end_byte, f"({expr})", "DOUBLE_ARITHMETIC", "double",
                               f"`{ts.text(n)}` evaluated in float", ln)
            if op == "//":
                inner = unparen(left)
                if inner.type == "binary_operator":
                    iop = inner.child_by_field_name("operator")
                    il, ir = inner.child_by_field_name("left"), inner.child_by_field_name("right")
                    if iop is not None and il is not None and ts.text(iop) in ("+", "-") and five_scaled(_py_lit(ir)):
                        yield Edit(inner.start_byte, inner.end_byte, ts.text(il), "ROUNDING_DROPPED", "rounding",
                                   f"half-up adjustment `{ts.text(inner)}` removed", ln)
        elif t == "unary_operator":
            op_node = n.child_by_field_name("operator")
            arg = n.child_by_field_name("argument")
            if op_node is not None and arg is not None and ts.text(op_node) == "-" \
                    and unparen(arg).type not in ("integer", "float"):
                yield Edit(n.start_byte, n.end_byte, f"({ts.text(arg)})", "SIGN_DROPPED", "sign",
                           f"`{ts.text(n)}` → `{ts.text(arg)}`", ln)
        elif t in ("identifier", "attribute"):
            txt = ts.text(n)
            if txt in ("ROUND_HALF_UP", "decimal.ROUND_HALF_UP") and (n.parent is None or n.parent.type != "attribute"
                                                                       or t == "attribute"):
                yield Edit(n.start_byte, n.end_byte, txt.replace("HALF_UP", "HALF_EVEN"), "ROUNDING_HALF_EVEN",
                           "rounding", "ROUND_HALF_UP → ROUND_HALF_EVEN", ln)
                yield Edit(n.start_byte, n.end_byte, txt.replace("HALF_UP", "DOWN"), "ROUNDING_DROPPED", "rounding",
                           "ROUND_HALF_UP → ROUND_DOWN", ln)
        elif t == "string":
            raw = ts.text(n)
            m = re.search(r"([<>])(\d+)", raw) if raw.startswith(("f", "F")) or "{" in raw else None
            if m and "{" in raw:
                new = raw[: m.start()] + (">" if m.group(1) == "<" else "<") + m.group(2) + raw[m.end():]
                yield Edit(n.start_byte, n.end_byte, new, "PAD_WRONG_SIDE", "padding",
                           f"format alignment `{m.group(0)}` flipped", ln)
        elif t == "call":
            fn = n.child_by_field_name("function")
            if fn is not None and fn.type == "attribute":
                attr = fn.child_by_field_name("attribute")
                name = ts.text(attr)
                for x, y in (("ljust", "rjust"), ("rjust", "ljust")):
                    if name == x and attr is not None:
                        yield Edit(attr.start_byte, attr.end_byte, y, "PAD_WRONG_SIDE", "padding", f"`{x}` → `{y}`", ln)
        elif t == "if_statement":
            cond = n.child_by_field_name("condition")
            if cond is not None and _is_size_guard(cond):
                yield Edit(cond.start_byte, cond.end_byte, "False", "SIZE_ERROR_IGNORED", "size_error",
                           f"overflow guard `{ts.text(cond)}` never taken", ln)
            cons = n.child_by_field_name("consequence")
            alts = n.children_by_field_name("alternative")
            if cond is not None and cons is not None and len(alts) == 1 and alts[0].type == "else_clause":
                else_body = alts[0].child_by_field_name("body")
                if else_body is not None:
                    a, b = ts.text(cons), ts.text(else_body)
                    yield Edit(cons.start_byte, else_body.end_byte,
                               _swap_py(src, cons, else_body), "BRANCHES_SWAPPED", "branch_swap",
                               f"then/else branches of the `if` at line {ln} swapped ({len(a)}/{len(b)} chars)", ln)


def _py_in_loop_cond(node: Node) -> bool:
    par = node.parent
    while par is not None and par.type in ("parenthesized_expression", "boolean_operator", "not_operator"):
        par = par.parent
    return par is not None and par.type == "while_statement"


def _swap_py(src: bytes, cons: Node, else_body: Node) -> str:
    """Swap two indented blocks of an if/else, keeping the text between them (`else:`)."""
    a = src[cons.start_byte:cons.end_byte].decode("utf-8")
    mid = src[cons.end_byte:else_body.start_byte].decode("utf-8")
    b = src[else_body.start_byte:else_body.end_byte].decode("utf-8")
    return b + mid + a


# ---------------------------------------------------------------------------------------------
# Go
# ---------------------------------------------------------------------------------------------
def _go_lit(n: Node | None) -> int | None:
    if n is None:
        return None
    n = unparen(n)
    return int_literal(ts.text(n)) if n.type == "int_literal" else None


def _go_in_loop(node: Node) -> bool:
    cur: Node | None = node
    while cur is not None and cur.parent is not None:
        par = cur.parent
        if par.type in ("for_clause",):
            cond = par.child_by_field_name("condition")
            return cond is not None and cond.start_byte <= node.start_byte and node.end_byte <= cond.end_byte
        if par.type == "for_statement":
            return cur.type not in ("block",)
        if par.type in ("block", "function_declaration", "method_declaration"):
            return False
        cur = par
    return False


def _go_edits(root: Node, src: bytes, methods: set[str]) -> Iterator[Edit]:
    for n in ts.walk(root):
        t = n.type
        ln = ts.line(n)
        if t == "binary_expression":
            op_node = n.child_by_field_name("operator")
            left, right = n.child_by_field_name("left"), n.child_by_field_name("right")
            if op_node is None or left is None or right is None:
                continue
            op = ts.text(op_node)
            if op in _FLIP:
                if _go_in_loop(n) and op in _OFF_BY_ONE:
                    yield Edit(op_node.start_byte, op_node.end_byte, _OFF_BY_ONE[op], "LOOP_BOUND_OFF_BY_ONE",
                               "loop_bound", f"loop condition `{op}` → `{_OFF_BY_ONE[op]}`", ln)
                else:
                    yield Edit(op_node.start_byte, op_node.end_byte, _FLIP[op], "COMPARISON_FLIP", "comparison",
                               f"comparison `{op}` → `{_FLIP[op]}`", ln)
            rlit, llit = _go_lit(right), _go_lit(left)
            if op == "%" and pow10_exp(rlit) is not None:
                yield Edit(n.start_byte, n.end_byte, f"({ts.text(left)})", "TRUNCATION_REMOVED", "truncation",
                           f"`{ts.text(n)}` → `{ts.text(left)}`", ln)
                r = unparen(right)
                yield Edit(r.start_byte, r.end_byte, str((rlit or 0) * 10), "TRUNCATION_WIDER", "truncation",
                           f"modulus {rlit} → {(rlit or 0) * 10}", ln)
            if op in ("*", "/"):
                for lit, side in ((rlit, right), (llit, left)):
                    if pow10_exp(lit) is not None:
                        s = unparen(side)
                        yield Edit(s.start_byte, s.end_byte, str((lit or 0) * 10), "SCALE_SHIFT", "scale",
                                   f"scale factor {lit} → {(lit or 0) * 10}", ln)
                        break
                if rlit is None and llit is None:
                    yield Edit(n.start_byte, n.end_byte,
                               f"int64(float64({ts.text(left)}) {op} float64({ts.text(right)}))",
                               "DOUBLE_ARITHMETIC", "double", f"`{ts.text(n)}` evaluated in float64", ln)
            if op == "/":
                inner = unparen(left)
                if inner.type == "binary_expression":
                    iop = inner.child_by_field_name("operator")
                    il, ir = inner.child_by_field_name("left"), inner.child_by_field_name("right")
                    if iop is not None and il is not None and ts.text(iop) in ("+", "-") and five_scaled(_go_lit(ir)):
                        yield Edit(inner.start_byte, inner.end_byte, ts.text(il), "ROUNDING_DROPPED", "rounding",
                                   f"half-up adjustment `{ts.text(inner)}` removed", ln)
        elif t == "unary_expression":
            op_node = n.child_by_field_name("operator")
            operand = n.child_by_field_name("operand")
            if op_node is not None and operand is not None and ts.text(op_node) == "-" \
                    and unparen(operand).type not in ("int_literal", "float_literal"):
                yield Edit(n.start_byte, n.end_byte, f"({ts.text(operand)})", "SIGN_DROPPED", "sign",
                           f"`{ts.text(n)}` → `{ts.text(operand)}`", ln)
        elif t == "interpreted_string_literal":
            raw = ts.text(n)
            m = re.search(r"%(-?)(\d+)s", raw)
            if m:
                new = raw[: m.start()] + ("%" + m.group(2) + "s" if m.group(1) else "%-" + m.group(2) + "s") + raw[m.end():]
                yield Edit(n.start_byte, n.end_byte, new, "PAD_WRONG_SIDE", "padding",
                           f"format `{m.group(0)}` padded on the other side", ln)
        elif t == "call_expression":
            fn = n.child_by_field_name("function")
            name = ts.text(fn).split(".")[-1]
            for a, b in (("PadRight", "PadLeft"), ("padRight", "padLeft")):
                for x, y in ((a, b), (b, a)):
                    if name == x and y in methods and fn is not None:
                        yield Edit(fn.end_byte - len(x), fn.end_byte, y, "PAD_WRONG_SIDE", "padding",
                                   f"`{x}` → `{y}`", ln)
        elif t == "if_statement":
            cond = n.child_by_field_name("condition")
            cons = n.child_by_field_name("consequence")
            alt = n.child_by_field_name("alternative")
            if cond is not None and _is_size_guard(cond):
                yield Edit(cond.start_byte, cond.end_byte, "false", "SIZE_ERROR_IGNORED", "size_error",
                           f"overflow guard `{ts.text(cond)}` never taken", ln)
            if cond is not None and cons is not None and alt is not None and alt.type == "block":
                yield Edit(cons.start_byte, alt.end_byte, f"{ts.text(alt)} else {ts.text(cons)}", "BRANCHES_SWAPPED",
                           "branch_swap", f"then/else branches of the `if` at line {ln} swapped", ln)


# ---------------------------------------------------------------------------------------------
_EDITORS: dict[str, Callable[[Node, bytes, set[str]], Iterator[Edit]]] = {
    "java": _java_edits, "python": _python_edits, "go": _go_edits,
}
_METHOD_NODES = {"java": ("method_declaration",), "python": ("function_definition",),
                 "go": ("function_declaration", "method_declaration")}


def _source_files(root: Path, lang: str) -> list[str]:
    out = []
    for suffix in SUFFIXES[lang]:
        for p in sorted(root.rglob(f"*{suffix}")):
            r = p.relative_to(root).as_posix()
            if any(s in "/" + r for s in _SKIP_DIRS) or r.endswith("_test.go") or p.name.startswith("test_"):
                continue
            out.append(r)
    return sorted(set(out))


def find_mutants(root: Path, lang: str, files: list[str] | None = None,
                 line_ranges: dict[str, list[tuple[int, int]]] | None = None) -> list[Mutant]:
    """All mutation sites in the translation under `root` (optionally restricted to line ranges)."""
    parser = ts.parser_for(lang)
    out: list[Mutant] = []
    seen: set[tuple[str, int, int, str]] = set()
    for rel_path in files or _source_files(root, lang):
        if line_ranges is not None and rel_path not in line_ranges:
            continue
        src = (root / rel_path).read_bytes()
        tree = parser.parse(src)
        if tree.root_node.has_error:
            continue
        methods = {ts.text(n.child_by_field_name("name")) for n in ts.walk(tree.root_node)
                   if n.type in _METHOD_NODES[lang]}
        for e in _EDITORS[lang](tree.root_node, src, methods):
            if line_ranges is not None and not any(lo <= e.line <= hi for lo, hi in line_ranges[rel_path]):
                continue
            key = (rel_path, e.start, e.end, e.replacement)
            if key in seen:
                continue
            seen.add(key)
            original = src[e.start:e.end].decode("utf-8", errors="replace")
            if original == e.replacement:
                continue
            h = hashlib.sha256(f"{rel_path}:{e.start}:{e.end}:{e.replacement}".encode()).hexdigest()[:8]
            out.append(Mutant(f"{e.operator}@{rel_path}:{e.line}#{h}", lang, e.operator, e.category, rel_path,
                              e.line, e.start, e.end, original, e.replacement, e.description))
    return out


def apply_mutant(root: Path, m: Mutant) -> None:
    """Apply in place (callers apply to a copy of the translation, never the original)."""
    p = root / m.file
    src = p.read_bytes()
    if src[m.start:m.end].decode("utf-8", errors="replace") != m.original:
        raise ValueError(f"mutant {m.id} does not match the source any more")
    p.write_bytes(src[: m.start] + m.replacement.encode("utf-8") + src[m.end:])


def sample_mutants(mutants: list[Mutant], n: int, seed: int) -> list[Mutant]:
    """Deterministic stratified sample: round-robin over categories, seeded order inside each."""
    by_cat: dict[str, list[Mutant]] = {}
    for m in mutants:
        by_cat.setdefault(m.category, []).append(m)

    def key(m: Mutant) -> str:
        return hashlib.sha256(f"{seed}:{m.id}".encode()).hexdigest()

    queues = {c: sorted(v, key=key) for c, v in sorted(by_cat.items())}
    out: list[Mutant] = []
    while len(out) < n and any(queues.values()):
        for c in sorted(queues):
            if queues[c] and len(out) < n:
                out.append(queues[c].pop(0))
    return out
