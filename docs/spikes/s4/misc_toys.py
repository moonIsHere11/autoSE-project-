"""Q4/Q5: exceptions, error cases, side effects, nondeterminism."""
import time

import cobol_ref as R


# ---- exceptions: DIVIDE a BY b GIVING q (q truncated toward zero)
def ref_div(a: int, b: int) -> int:
    q = abs(a) // abs(b)  # b == 0 -> ZeroDivisionError('integer division or modulo by zero')
    return q if (a >= 0) == (b > 0) else -q


def llm_div_msg(a: int, b: int) -> int:
    """Same exception type, different message."""
    if b == 0:
        raise ZeroDivisionError("SIZE ERROR on DIVIDE")
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


def llm_div_type(a: int, b: int) -> int:
    """Different exception type."""
    if b == 0:
        raise ValueError("SIZE ERROR on DIVIDE")
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


# ---- error cases
def unannotated(a, b):
    return R.ref_add_trunc(a, b)


def llm_add_side_effect(a: int, b: int) -> int:
    with open("/tmp/s4_side_effect.txt", "w") as f:  # side effect: CrossHair's audit wall blocks it
        f.write("x")
    return R.ref_add_trunc(a, b)


def llm_add_nondet(a: int, b: int) -> int:
    if a == 1234567 and int(time.monotonic_ns()) % 2 == 0:  # nondeterministic branch
        return 0
    return R.ref_add_trunc(a, b)


def llm_add_slow(a: int, b: int) -> int:
    """Data-dependent loop: makes path explosion / per-path timeouts visible."""
    s = 0
    for _ in range(abs(a) % 50):
        s += b
    return R.ref_add_trunc(a, b) + (s - s)
