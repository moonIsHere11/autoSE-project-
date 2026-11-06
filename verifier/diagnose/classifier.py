"""Likely-cause classification of a mismatch. Always hedged ("likely"); never used for verdicts."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from verifier.cobol.datadiv import DataItem
from verifier.diagnose.compare import Mismatch
from verifier.report.schema import Classification


def _num(item: DataItem | None, text: str) -> Decimal | None:
    s = text.strip()
    if not s or s.startswith("raw:"):
        return None
    neg = s.startswith("-") or s.endswith("-")
    body = s.strip("+-").strip()
    try:
        d = Decimal(body)
    except InvalidOperation:
        return None
    return -d if neg else d


def _c(label: str, text: str) -> Classification:
    return Classification(label=label, explanation=f"likely {text}")


def classify(m: Mismatch, size_error_in_writers: bool = False) -> Classification | None:
    if m.kind == "TARGET_TIMEOUT":
        return _c("ITERATION_COUNT", "a loop in the target does not terminate where the COBOL loop does")
    if m.kind == "TARGET_CRASH":
        return _c("SIZE_ERROR_HANDLING" if "Arithmetic" in m.signature else "MISSING_OR_EXTRA_OUTPUT",
                  f"the target throws ({m.signature.split(' ', 1)[-1]}) where COBOL continues")
    if m.kind == "RETURN_CODE":
        return _c("RETURN_CODE", "RETURN-CODE / exit status is not propagated like STOP RUN does")
    if m.kind in ("LINE_COUNT", "RECORD_COUNT"):
        exp, act = (int(m.diffs[0].expected), int(m.diffs[0].actual)) if m.diffs else (0, 0)
        if exp and act and (exp % max(1, act) == 0 or act % max(1, exp) == 0 or abs(exp - act) == 1):
            return _c("ITERATION_COUNT", f"a loop runs a different number of times ({act} vs {exp} lines/records): check PERFORM VARYING/UNTIL bounds (COBOL tests UNTIL before each iteration)")
        return _c("MISSING_OR_EXTRA_OUTPUT", f"output {act} vs expected {exp} lines/records")
    if m.kind in ("FILE_MISSING", "FILE_EXTRA"):
        return _c("MISSING_OR_EXTRA_OUTPUT", f"{m.location} is {m.diffs[0].actual} on the target side")
    for d in m.diffs:
        if d.expected.startswith("raw:") or d.actual.startswith("raw:") or any(ord(c) > 126 for c in d.actual + d.expected):
            return _c("ENCODING", f"{d.field or 'the output'} bytes are encoded differently (zoned overpunch / packed sign nibble / binary byte order)")
        item = next((i for i in m.items if i.name == d.field), None)
        if item is not None and item.pic is not None and item.pic.category == "numeric":
            c = _numeric(item, d.expected, d.actual, size_error_in_writers)
            if c is not None:
                return c
        if d.expected.rstrip() == d.actual.rstrip() or d.expected.strip() == d.actual.strip():
            return _c("PADDING_OR_JUSTIFICATION", f"{d.field or 'the line'} differs only in padding/justification (spaces)")
        if (item is not None and item.pic is not None and item.pic.category != "numeric"
                and (d.actual.startswith(d.expected.rstrip()) or d.expected.startswith(d.actual.rstrip()))):
            return _c("PADDING_OR_JUSTIFICATION", f"alphanumeric {item.name} PIC {item.pic.raw} is truncated/padded differently (COBOL pads with spaces on the right and truncates on the right)")
        e, a = _num(None, d.expected), _num(None, d.actual)
        if e is not None and a is not None and e == a:
            return _c("DISPLAY_FORMAT", f"same numeric value, different DISPLAY formatting ('{d.actual}' vs '{d.expected}')")
    return None


def _numeric(item: DataItem, exp_s: str, act_s: str, size_err: bool) -> Classification | None:
    pic = item.pic
    assert pic is not None
    e, a = _num(item, exp_s), _num(item, act_s)
    if e is None or a is None:
        return None
    u = Decimal(1).scaleb(-pic.scale)
    name = f"{item.name} ({pic.raw}{' ' + item.usage if item.usage != 'DISPLAY' else ''})"
    if e == a:
        if e == 0 and (exp_s.strip()[:1] != act_s.strip()[:1]):
            return _c("NEGATIVE_ZERO", f"{name}: sign of zero differs (COBOL never yields -0 from arithmetic but DISPLAYs +0)")
        return _c("DISPLAY_FORMAT", f"{name}: same value, formatted differently (GnuCOBOL shows sign, all digits and the implied decimal point)")
    if a == -e:
        return _c("SIGN_LOST",
                  f"{name}: sign handling differs ({act_s.strip()} vs {exp_s.strip()}); unsigned COBOL fields drop the sign on MOVE")
    mod = Decimal(10) ** pic.integer_digits if pic.scale >= 0 else Decimal(10) ** (pic.digits - pic.scale)
    if abs(a) >= mod and (abs(a) % mod) * (1 if a >= 0 else -1) == e:
        if size_err:
            return _c("SIZE_ERROR_HANDLING", f"{name}: the result overflows {pic.integer_digits} integer digits; with ON SIZE ERROR COBOL leaves the target unchanged and runs the error branch")
        return _c("MISSING_HIGH_ORDER_TRUNCATION", f"{name}: the value is not truncated to {pic.integer_digits} integer digits (COBOL drops high-order digits)")
    if abs(a) >= mod and size_err:
        return _c("SIZE_ERROR_HANDLING", f"{name}: overflow handling differs (ON SIZE ERROR leaves the target unchanged)")
    for k in range(1, 5):
        f = Decimal(10) ** k
        if e != 0 and (a == e * f or a * f == e):
            return _c("SCALE_OFF_BY_POWER_OF_10", f"{name}: off by a factor 10^{k} — implied decimal point (V, scale {pic.scale}) misplaced")
    if abs(a - e) == u:
        if abs(a) < abs(e):
            return _c("ROUNDING_MISSING", f"{name}: truncated where COBOL ROUNDED rounds half away from zero (or vice versa)")
        return _c("ROUNDING_MODE", f"{name}: rounds differently by one unit in the last place (COBOL ROUNDED = half away from zero; truncation otherwise)")
    if abs(a - e) < u * 10 and pic.scale > 0:
        return _c("ROUNDING_MODE", f"{name}: small difference in the last digits — intermediate precision or rounding of intermediates (COBOL computes intermediates exactly)")
    if size_err:
        return _c("SIZE_ERROR_HANDLING", f"{name}: value differs where ON SIZE ERROR is involved")
    return None
