"""Trusted reference functions, as the verifier would emit them from the COBOL model.

All decimal values are scaled integers: a PIC S9(5)V99 value 123.45 is the int 12345 (scale 2).
Only int arithmetic (no float, no Decimal) so CrossHair/z3 reason about them symbolically.
"""

P7 = 10**7  # PIC S9(7) capacity: |x| < 10**7


def ref_add_trunc(a: int, b: int) -> int:
    """ADD a TO b GIVING r, r PIC S9(7) (no ON SIZE ERROR): high-order digits truncated, sign kept."""
    s = a + b
    m = abs(s) % P7
    return m if s >= 0 else -m


def ref_round_drop2(v: int) -> int:
    """COMPUTE r ROUNDED = v where v has scale 4 and r has scale 2: drop 2 digits, half away from 0."""
    q, r = divmod(abs(v), 100)
    if r >= 50:
        q += 1
    return q if v >= 0 else -q
