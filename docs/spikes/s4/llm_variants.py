"""Stand-ins for LLM-generated translations (correct-but-different and buggy variants)."""
from decimal import ROUND_HALF_UP, Decimal

# ---------------------------------------------------------------- add_trunc (PIC S9(7))


def add_ok(a: int, b: int) -> int:
    """Correct, but structured differently from the reference."""
    s = a + b
    sign = -1 if s < 0 else 1
    return sign * ((sign * s) % 10_000_000)


def add_bug_pymod(a: int, b: int) -> int:
    """Bug: Python % on a negative sum yields a positive remainder."""
    return (a + b) % 10_000_000


def add_bug_abs(a: int, b: int) -> int:
    """Bug: loses the sign."""
    return abs(a + b) % 10_000_000


def add_bug_notrunc(a: int, b: int) -> int:
    """Bug: forgets the PIC S9(7) truncation entirely."""
    return a + b


def add_ok_in_domain(a: int, b: int) -> int:
    """Correct ONLY for |a|,|b| < 10**7 (then |a+b| < 2*10**7, one subtraction suffices).
    Differs from the reference outside the PIC domain -> spurious diff unless the domain is restricted."""
    s = a + b
    if s >= 10_000_000:
        s -= 10_000_000
    elif s <= -10_000_000:
        s += 10_000_000
    return s


# ---------------------------------------------------------------- ROUNDED rescale (scale 4 -> 2)


def round_ok(v: int) -> int:
    """Correct, different structure."""
    if v >= 0:
        return (v + 50) // 100
    return -((-v + 50) // 100)


def round_ok_decimal(v: int) -> int:
    """Correct, the way an LLM would most likely write it (decimal module)."""
    return int((Decimal(v) / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def round_bug_trunc(v: int) -> int:
    """Bug: truncation instead of rounding."""
    q = abs(v) // 100
    return q if v >= 0 else -q


def round_bug_banker(v: int) -> int:
    """Bug: Python's round() is banker's rounding (half to even), and goes through float."""
    return round(v / 100)


def round_bug_banker_int(v: int) -> int:
    """Bug: banker's rounding implemented with integers only (no float)."""
    q, r = divmod(v, 100)
    if r > 50 or (r == 50 and q % 2 == 1):
        q += 1
    return q


def round_bug_floor(v: int) -> int:
    """Bug: floor-based half-up ((v+50)//100) is wrong for negative halves (-150 -> -1, COBOL -2)."""
    return (v + 50) // 100
