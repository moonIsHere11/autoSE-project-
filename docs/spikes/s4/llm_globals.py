"""LLM-style Python translation following the INTERFACE.md convention: WORKING-STORAGE items are
module attributes (snake_case), paragraphs are module functions without parameters."""
from decimal import ROUND_HALF_UP, Decimal

# 01 WS.  05 WS-TOTAL PIC S9(5)V99.  05 WS-COUNT PIC 9(3).  05 WS-FLAG PIC X.  05 WS-AMT PIC S9(5)V99.
ws_total = Decimal("0.00")
ws_count = 0
ws_flag = "P"
ws_amt = Decimal("0.00")


def accum_para():
    """ADD WS-AMT TO WS-TOTAL ROUNDED... (here: plain truncating ADD), ADD 1 TO WS-COUNT, set flag."""
    global ws_total, ws_count, ws_flag
    t = ws_total + ws_amt
    sign = -1 if t < 0 else 1
    ws_total = sign * (abs(t) % Decimal("100000.00"))  # keep 5 integer digits
    ws_count = (ws_count + 1) % 1000
    ws_flag = "N" if ws_total < 0 else "P"


def accum_para_bug():
    """Bug: flag computed before the ADD; ROUNDED-style quantize misuse is not involved."""
    global ws_total, ws_count, ws_flag
    ws_flag = "N" if ws_total < 0 else "P"
    t = ws_total + ws_amt
    sign = -1 if t < 0 else 1
    ws_total = sign * (abs(t) % Decimal("100000.00"))
    ws_count = (ws_count + 1) % 1000


def accum_para_bug_round():
    """Bug: quantize with ROUND_HALF_UP to 1 decimal place (drops a digit of scale)."""
    global ws_total, ws_count, ws_flag
    t = (ws_total + ws_amt).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    sign = -1 if t < 0 else 1
    ws_total = sign * (abs(t) % Decimal("100000.00"))
    ws_count = (ws_count + 1) % 1000
    ws_flag = "N" if ws_total < 0 else "P"
