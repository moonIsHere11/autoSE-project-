"""Q3: paragraphs that mutate WORKING-STORAGE.

Paragraph (COBOL):
    ACCUM-PARA.
        ADD WS-AMT TO WS-TOTAL.            *> WS-TOTAL PIC S9(7), truncating
        ADD 1 TO WS-COUNT.                 *> WS-COUNT PIC 9(3), truncating, unsigned
        IF WS-TOTAL < 0  MOVE 'N' TO WS-FLAG ELSE MOVE 'P' TO WS-FLAG.
"""
from dataclasses import dataclass

import cobol_ref as R


# ---- state as a dataclass (has generated __eq__)
@dataclass
class WS:
    total: int
    count: int
    flag: str


def ref_para(ws: WS, amt: int) -> None:
    ws.total = R.ref_add_trunc(ws.total, amt)
    ws.count = (ws.count + 1) % 1000
    ws.flag = "N" if ws.total < 0 else "P"


def llm_para_ok(ws: WS, amt: int) -> None:
    t = ws.total + amt
    t = -(abs(t) % 10_000_000) if t < 0 else t % 10_000_000
    ws.total = t
    ws.count = ws.count + 1 if ws.count < 999 else 0
    ws.flag = "P" if t >= 0 else "N"


def llm_para_bug_count(ws: WS, amt: int) -> None:
    """Bug only visible in post-state: WS-COUNT not wrapped at 1000 (PIC 9(3))."""
    ws.total = R.ref_add_trunc(ws.total, amt)
    ws.count = ws.count + 1
    ws.flag = "N" if ws.total < 0 else "P"


def llm_para_bug_flag(ws: WS, amt: int) -> None:
    """Bug only visible in post-state: flag computed from the old total."""
    old = ws.total
    ws.total = R.ref_add_trunc(ws.total, amt)
    ws.count = (ws.count + 1) % 1000
    ws.flag = "N" if old < 0 else "P"


# ---- state as a plain class (identity __eq__): does diffbehavior still see mutations?
class WSPlain:
    def __init__(self, total: int, count: int, flag: str):
        self.total = total
        self.count = count
        self.flag = flag

    def __repr__(self):
        return f"WSPlain(total={self.total!r}, count={self.count!r}, flag={self.flag!r})"


def ref_para_plain(ws: WSPlain, amt: int) -> None:
    ws.total = R.ref_add_trunc(ws.total, amt)
    ws.count = (ws.count + 1) % 1000
    ws.flag = "N" if ws.total < 0 else "P"


def llm_para_plain_bug_count(ws: WSPlain, amt: int) -> None:
    ws.total = R.ref_add_trunc(ws.total, amt)
    ws.count = ws.count + 1
    ws.flag = "N" if ws.total < 0 else "P"


# ---- recommended: flat wrapper over primitives, domain guard, returns ALL fields
FLAGS = ("N", "P")


def _dom(total: int, count: int, flag: str, amt: int) -> bool:
    return -10**7 < total < 10**7 and 0 <= count < 1000 and flag in FLAGS and -10**7 < amt < 10**7


def h_ref(total: int, count: int, flag: str, amt: int):
    if not _dom(total, count, flag, amt):
        return None
    ws = WS(total, count, flag)
    rv = ref_para(ws, amt)
    return (rv, ws.total, ws.count, ws.flag)


def h_llm_ok(total: int, count: int, flag: str, amt: int):
    if not _dom(total, count, flag, amt):
        return None
    ws = WS(total, count, flag)
    rv = llm_para_ok(ws, amt)
    return (rv, ws.total, ws.count, ws.flag)


def h_llm_bug_count(total: int, count: int, flag: str, amt: int):
    if not _dom(total, count, flag, amt):
        return None
    ws = WS(total, count, flag)
    rv = llm_para_bug_count(ws, amt)
    return (rv, ws.total, ws.count, ws.flag)


def h_llm_bug_flag(total: int, count: int, flag: str, amt: int):
    if not _dom(total, count, flag, amt):
        return None
    ws = WS(total, count, flag)
    rv = llm_para_bug_flag(ws, amt)
    return (rv, ws.total, ws.count, ws.flag)


# ---- variant: flag passed as an index into its 88-level value set (no symbolic str)
def _dom_i(total: int, count: int, fi: int, amt: int) -> bool:
    return -10**7 < total < 10**7 and 0 <= count < 1000 and 0 <= fi < 2 and -10**7 < amt < 10**7


def _run_i(para, total: int, count: int, fi: int, amt: int):
    if not _dom_i(total, count, fi, amt):
        return None
    ws = WS(total, count, FLAGS[fi])
    rv = para(ws, amt)
    return (rv, ws.total, ws.count, ws.flag)


def hi_ref(total: int, count: int, fi: int, amt: int):
    return _run_i(ref_para, total, count, fi, amt)


def hi_llm_ok(total: int, count: int, fi: int, amt: int):
    return _run_i(llm_para_ok, total, count, fi, amt)


def hi_llm_bug_count(total: int, count: int, fi: int, amt: int):
    return _run_i(llm_para_bug_count, total, count, fi, amt)


def hi_llm_bug_flag(total: int, count: int, fi: int, amt: int):
    return _run_i(llm_para_bug_flag, total, count, fi, amt)


# ---- variant: equivalence as asserts (preconditions handled natively by `crosshair check`)
def eq_state_bug_count(total: int, count: int, flag: str, amt: int) -> None:
    assert -10**7 < total < 10**7
    assert 0 <= count < 1000
    assert flag in FLAGS
    assert -10**7 < amt < 10**7
    assert h_ref(total, count, flag, amt) == h_llm_bug_count(total, count, flag, amt)


def eq_state_bug_flag(total: int, count: int, flag: str, amt: int) -> None:
    assert -10**7 < total < 10**7
    assert 0 <= count < 1000
    assert flag in FLAGS
    assert -10**7 < amt < 10**7
    assert h_ref(total, count, flag, amt) == h_llm_bug_flag(total, count, flag, amt)


def eq_state_ok(total: int, count: int, flag: str, amt: int) -> None:
    assert -10**7 < total < 10**7
    assert 0 <= count < 1000
    assert flag in FLAGS
    assert -10**7 < amt < 10**7
    assert h_ref(total, count, flag, amt) == h_llm_ok(total, count, flag, amt)
