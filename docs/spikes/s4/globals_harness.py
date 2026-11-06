"""Harness for module-global WORKING-STORAGE (INTERFACE.md Python convention).

Inputs: every WS field the paragraph reads/writes, as scaled ints (or an index for PIC X with a
known value set). The harness writes them into the module, calls the paragraph, and returns
(outcome, all fields after) as scaled ints -> diffbehavior / asserts compare all post-state."""
from decimal import Decimal

import llm_globals as G

P5V2 = 10**7  # |scaled| < 10**7 for S9(5)V99
FLAGS = ("N", "P")


def _dom(total: int, count: int, fi: int, amt: int) -> bool:
    return -P5V2 < total < P5V2 and 0 <= count < 1000 and 0 <= fi < 2 and -P5V2 < amt < P5V2


def _ref(total: int, count: int, fi: int, amt: int):
    """Trusted reference on scaled ints (what the verifier emits from the COBOL IR)."""
    s = total + amt
    m = abs(s) % P5V2
    t = m if s >= 0 else -m
    return ("ok", t, (count + 1) % 1000, "N" if t < 0 else "P")


def _llm(para, total: int, count: int, fi: int, amt: int):
    G.ws_total = Decimal(total).scaleb(-2)
    G.ws_count = count
    G.ws_flag = FLAGS[fi]
    G.ws_amt = Decimal(amt).scaleb(-2)
    try:
        para()
    except Exception as e:
        return ("exc", type(e).__name__)
    return ("ok", int(G.ws_total.scaleb(2)), G.ws_count, G.ws_flag)


# diffbehavior pair(s)
def d_ref(total: int, count: int, fi: int, amt: int):
    return _ref(total, count, fi, amt) if _dom(total, count, fi, amt) else None


def d_llm_ok(total: int, count: int, fi: int, amt: int):
    return _llm(G.accum_para, total, count, fi, amt) if _dom(total, count, fi, amt) else None


def d_llm_bug(total: int, count: int, fi: int, amt: int):
    return _llm(G.accum_para_bug, total, count, fi, amt) if _dom(total, count, fi, amt) else None


def d_llm_bug_round(total: int, count: int, fi: int, amt: int):
    return _llm(G.accum_para_bug_round, total, count, fi, amt) if _dom(total, count, fi, amt) else None


# asserts-mode equivalence functions
def eq_ok(total: int, count: int, fi: int, amt: int) -> None:
    assert _dom(total, count, fi, amt)
    assert _ref(total, count, fi, amt) == _llm(G.accum_para, total, count, fi, amt)


def eq_bug(total: int, count: int, fi: int, amt: int) -> None:
    assert _dom(total, count, fi, amt)
    assert _ref(total, count, fi, amt) == _llm(G.accum_para_bug, total, count, fi, amt)


def eq_bug_round(total: int, count: int, fi: int, amt: int) -> None:
    assert _dom(total, count, fi, amt)
    assert _ref(total, count, fi, amt) == _llm(G.accum_para_bug_round, total, count, fi, amt)
