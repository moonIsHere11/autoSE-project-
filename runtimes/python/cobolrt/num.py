"""Pure integer core: COBOL numeric semantics on scaled Python ints (no `decimal`, no floats).

A numeric value is an *unscaled* integer `u` plus a scale `s` (value = u * 10**-s). Field state is
`(u, negzero)`: GnuCOBOL can leave a DISPLAY or COMP-3 field holding a *negative zero* (sign
overpunch / D nibble with all-zero digits) after high-order truncation, and that is visible in the
record bytes, so it is tracked explicitly. Everything here mirrors libcob 3.2 (numeric.c, move.c)
and is validated against GnuCOBOL by `tests/runtimes` (docs/RUNTIME_API.md).
"""

from __future__ import annotations

from dataclasses import dataclass

from cobolrt.pic import NumPic, Round, SizeError, Usage

MAX_DIGITS = 38  # COB_MAX_DIGITS: extra fractional digits kept by a COMPUTE division


def pow10(n: int) -> int:
    return 10**n


def tdiv(a: int, b: int) -> int:
    """Division truncating toward zero (C / mpz_tdiv_q)."""
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def trem(a: int, b: int) -> int:
    """Remainder with the sign of the dividend (C % / mpz_tdiv_r)."""
    return a - b * tdiv(a, b)


def shift(v: int, n: int) -> int:
    """v * 10**n, truncating toward zero when n < 0."""
    if n >= 0:
        return v * 10**n
    return tdiv(v, 10**-n)


def rescale(v: int, from_scale: int, to_scale: int) -> int:
    return shift(v, to_scale - from_scale)


def sign(v: int) -> int:
    return (v > 0) - (v < 0)


# ---------------------------------------------------------------------------------------------
# rounding (cob_decimal_do_round)
# ---------------------------------------------------------------------------------------------
def round_to(v: int, vscale: int, tscale: int, mode: Round) -> tuple[int, int] | None:
    """Apply a ROUNDED mode before the final truncation to `tscale`.

    Returns the adjusted `(value, scale)` (the caller still truncates to `tscale`), or None for
    ROUNDED MODE PROHIBITED when digits would be lost (an EC-SIZE-TRUNCATION size error).
    """
    sg = sign(v)
    if sg == 0 or tscale >= vscale or mode in (Round.TRUNCATION, Round.MODE_TRUNCATION):
        return v, vscale
    if mode == Round.PROHIBITED:
        return None
    adj = vscale - tscale
    if mode == Round.AWAY_FROM_ZERO:
        if trem(v, 10**adj) != 0:
            v += sg * 10**adj
        return v, vscale
    if mode == Round.TOWARD_GREATER:
        if trem(v, 10**adj) != 0 and sg > 0:
            v += 10**adj
        return v, vscale
    if mode == Round.TOWARD_LESSER:
        if trem(v, 10**adj) != 0 and sg < 0:
            v -= 10**adj
        return v, vscale
    if mode == Round.NEAREST_TOWARD_ZERO:
        r = trem(v, 5 * 10 ** (adj - 1))
        v = shift(v, tscale - vscale + 1)
        if r != 0:
            v += 5 * sg
        return v, tscale + 1
    if mode == Round.NEAREST_EVEN:
        r = trem(v, 5 * 10 ** (adj - 1))
        v = shift(v, tscale - vscale + 1)
        if r == 0 and abs(v) % 100 in (5, 25, 45, 65, 85):
            return v, tscale + 1
        return v + 5 * sg, tscale + 1
    # NEAREST_AWAY_FROM_ZERO (plain ROUNDED)
    v = shift(v, tscale - vscale + 1)
    return v + 5 * sg, tscale + 1


# ---------------------------------------------------------------------------------------------
# store an exact intermediate into a field (cob_decimal_get_field)
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Stored:
    """Result of storing into a field: new state, whether a size error was raised, and whether
    the field was written (False: left unchanged because of ON SIZE ERROR / PROHIBITED / NaN)."""

    u: int
    negzero: bool
    size_error: bool
    stored: bool


def keeps_on_overflow(pic: NumPic, size: SizeError) -> bool:
    """Whether an overflow leaves the target unchanged (cobc build_store_option)."""
    if pic.usage == Usage.COMP5:
        return size == SizeError.ON  # COMP-5 ignores a lone NOT ON SIZE ERROR
    return size != SizeError.NONE


def store(v: int, vscale: int, pic: NumPic, mode: Round = Round.TRUNCATION,
          size: SizeError = SizeError.NONE, *, nan: bool = False,
          old_u: int = 0, old_negzero: bool = False) -> Stored:
    """Store the exact value `v * 10**-vscale` into a field described by `pic`.

    Mirrors cob_decimal_get_field: optional rounding, truncation to the field's scale, then
    high-order truncation (DISPLAY/COMP-3/COMP: modulo 10**digits keeping the sign, so a negative
    value can become a negative zero) or, for COMP-5, wrap-around at the binary width.
    `nan` marks a division by zero in the intermediate (size error, target unchanged).
    """
    unchanged = Stored(old_u, old_negzero, True, False)
    if nan:
        return unchanged
    keep = keeps_on_overflow(pic, size)
    if mode != Round.TRUNCATION:
        r = round_to(v, vscale, pic.scale, mode)
        if r is None:
            return unchanged  # PROHIBITED: EC-SIZE-TRUNCATION, target never written
        v, vscale = r
    if v != 0:
        v = shift(v, pic.scale - vscale)
    if v == 0:
        return Stored(0, False, False, True)
    sg = sign(v)
    mag = abs(v)
    if pic.usage in (Usage.DISPLAY, Usage.COMP3):
        err = mag >= 10**pic.digits
        if err:
            if keep:
                return unchanged
            mag %= 10**pic.digits
        if not pic.signed:
            return Stored(mag, False, err, True)
        return Stored(sg * mag, sg < 0 and mag == 0, err, True)
    # binary
    bits = 8 * pic.byte_length
    bitnum = bits - (1 if pic.signed else 0)
    if not pic.signed:
        sg = 1
    if mag.bit_length() > bitnum:
        if keep:
            return unchanged
        if pic.usage == Usage.COMP:  # COB_STORE_TRUNC_ON_OVERFLOW (binary-truncate)
            return Stored(sg * (mag % 10**pic.digits), False, True, True)
        w = (sg * mag) % (1 << bits)  # mpz_fdiv_r_2exp: two's complement wrap
        if pic.signed and w >= 1 << (bits - 1):
            w -= 1 << bits
        return Stored(w, False, True, True)
    if pic.usage == Usage.COMP and mag >= 10**pic.digits:
        if keep:
            return unchanged
        return Stored(sg * (mag % 10**pic.digits), False, True, True)
    return Stored(sg * mag, False, False, True)


def size_error(v: int, vscale: int, pic: NumPic, mode: Round = Round.TRUNCATION) -> bool:
    """Would storing this value into `pic` raise a size error (with an ON SIZE ERROR phrase)?"""
    return store(v, vscale, pic, mode, SizeError.ON).size_error


# ---------------------------------------------------------------------------------------------
# exact intermediates (cob_decimal) used by ADD/SUBTRACT/MULTIPLY/DIVIDE/COMPUTE
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Dec:
    """An intermediate result: value * 10**-scale, or NaN after a division by zero.

    Addition, subtraction and multiplication are exact. Division keeps 38 extra fractional
    digits and truncates (exactly like GnuCOBOL's cob_decimal_div), so `A / B * B` may differ from
    `A`. Build expressions in the same order as the COBOL source.
    """

    value: int
    scale: int = 0
    nan: bool = False

    @staticmethod
    def literal(text: str) -> Dec:
        u, s, _neg = parse_literal(text)
        return Dec(u, s)

    def _bad(self, other: Dec) -> bool:
        return self.nan or other.nan

    def add(self, other: Dec) -> Dec:
        if self._bad(other):
            return NAN
        if self.scale != other.scale:
            if other.value == 0:
                return self
            if self.value == 0:
                return other
            s = max(self.scale, other.scale)
            return Dec(shift(self.value, s - self.scale) + shift(other.value, s - other.scale), s)
        return Dec(self.value + other.value, self.scale)

    def sub(self, other: Dec) -> Dec:
        if self._bad(other):
            return NAN
        if self.scale != other.scale:
            if other.value == 0:
                return self
            s = max(self.scale, other.scale)
            return Dec(shift(self.value, s - self.scale) - shift(other.value, s - other.scale), s)
        return Dec(self.value - other.value, self.scale)

    def mul(self, other: Dec) -> Dec:
        if self._bad(other):
            return NAN
        return Dec(self.value * other.value, self.scale + other.scale)

    def div(self, other: Dec) -> Dec:
        if self._bad(other) or other.value == 0:
            return NAN
        if self.value == 0:
            return Dec(0, 0)
        s = self.scale - other.scale
        sh = MAX_DIGITS + (-s if s < 0 else 0)
        return Dec(tdiv(self.value * 10**sh, other.value), s + sh)

    def neg(self) -> Dec:
        """Unary minus (cobc builds `0 - x`)."""
        return ZERO.sub(self)

    __add__ = add
    __sub__ = sub
    __mul__ = mul
    __truediv__ = div
    __neg__ = neg


ZERO = Dec(0, 0)
NAN = Dec(0, 0, True)


def parse_literal(text: str) -> tuple[int, int, bool]:
    """A COBOL numeric literal `[+-]digits[.digits]` -> (unscaled, scale, has_minus)."""
    t = text.strip()
    neg = t.startswith("-")
    if t[:1] in "+-":
        t = t[1:]
    if not t or t.count(".") > 1 or not t.replace(".", "").isdigit():
        raise ValueError(f"not a numeric literal: {text!r}")
    ip, _, fp = t.partition(".")
    u = int((ip + fp) or "0")
    return (-u if neg else u), len(fp), neg


# ---------------------------------------------------------------------------------------------
# MOVE numeric -> numeric (cob_move and friends)
# ---------------------------------------------------------------------------------------------
def move_value(v: int, vscale: int, neg: bool, from_binary: bool, dst: NumPic) -> tuple[int, bool]:
    """MOVE a source whose (unscaled, scale) is (v, vscale) and whose sign is `neg` into `dst`.

    Low-order digits are truncated, high-order digits dropped (DISPLAY/COMP-3/COMP) or the value
    wraps at the byte width (COMP-5); an unsigned target receives the magnitude. DISPLAY and
    COMP-3 targets take the *source* sign, so a negative source truncated to zero gives a negative
    zero; binary->COMP-3 takes the sign after scale truncation.
    """
    w = shift(v, dst.scale - vscale)
    mag = abs(w)
    if dst.usage in (Usage.DISPLAY, Usage.COMP3):
        mag %= 10**dst.digits
        if not dst.signed:
            return mag, False
        n = w < 0 if (from_binary and dst.usage == Usage.COMP3) else neg
        return (-mag if n else mag), (n and mag == 0)
    if dst.usage == Usage.COMP:
        mag %= 10**dst.digits
        return (-mag if (w < 0 and dst.signed) else mag), False
    bits = 8 * dst.byte_length
    x = (w if dst.signed else mag) % (1 << bits)
    if dst.signed and x >= 1 << (bits - 1):
        x -= 1 << bits
    return x, False


def move_num(u: int, negzero: bool, src: NumPic, dst: NumPic) -> tuple[int, bool]:
    """MOVE numeric field -> numeric field. Returns the target's (unscaled, negzero)."""
    return move_value(u, src.scale, u < 0 or negzero, src.is_binary, dst)


def move_literal(text: str, dst: NumPic) -> tuple[int, bool]:
    """MOVE numeric-literal -> numeric field (the literal behaves like a signed DISPLAY item)."""
    u, s, neg = parse_literal(text)
    return move_value(u, s, neg, False, dst)


# ---------------------------------------------------------------------------------------------
# ADD / SUBTRACT fast paths that GnuCOBOL 3.2 selects at compile time (cobc cb_build_add)
# ---------------------------------------------------------------------------------------------
def gc_digits(pic: NumPic) -> int:
    """GnuCOBOL's digit count of an item (P positions after the 9s are counted)."""
    return pic.digits - pic.scale if pic.scale < 0 else pic.digits


INT_MAX = 2**31 - 1


def literal_fits_int(text: str) -> bool:
    """cb_fits_int for a numeric literal: no decimal places and within a C int."""
    u, s, _ = parse_literal(text)
    return s == 0 and -INT_MAX - 1 <= u <= INT_MAX


def field_fits_int(pic: NumPic) -> bool:
    """cb_fits_int for a data item."""
    if pic.scale > 0:
        return False
    if pic.usage == Usage.DISPLAY:
        return pic.byte_length < 10
    if pic.usage == Usage.COMP3:
        return gc_digits(pic) < 10
    return pic.byte_length <= 4


@dataclass(frozen=True)
class Bcd:
    """Result of the BCD ADD/SUBTRACT (cob_add_bcd): new state + size error; `stored` False means
    the target was left unchanged."""

    u: int
    negzero: bool
    size_error: bool
    stored: bool
    pad: int = 0


def bcd_add(y_full: int, y_neg: bool, y_scale: int, x_mag: int, x_neg: bool, x_scale: int,
            dst: NumPic, mode: Round, size: SizeError, subtract: bool) -> Bcd:
    """ADD x TO y / SUBTRACT x FROM y where y is COMP-3: GnuCOBOL's packed-decimal fast path.

    Magnitudes are added/subtracted digit-wise (`y_full` includes a garbage pad digit, if any);
    rounding happens on the magnitude at the first dropped digit, but **plain ROUNDED (no MODE),
    MODE TRUNCATION and no ROUNDED all truncate**, NEAREST-EVEN behaves like
    NEAREST-AWAY-FROM-ZERO, and PROHIBITED only fails when non-zero digits would be dropped.
    `x_neg`/`y_neg` are the D sign nibbles (negative or negative zero).
    """
    s = max(x_scale, y_scale)
    xm = x_mag * 10 ** (s - x_scale)
    ym = y_full * 10 ** (s - y_scale)
    xn = x_neg != subtract
    if xn == y_neg:
        m, positive = xm + ym, not xn
    elif xm < ym:
        m, positive = ym - xm, not y_neg
    elif xm > ym:
        m, positive = xm - ym, not xn
    else:
        return Bcd(0, False, False, True)
    k = s - y_scale  # digits dropped
    if k > 0:
        rounding = mode not in (Round.TRUNCATION, Round.ROUNDED, Round.MODE_TRUNCATION)
        if rounding:
            rd = m // 10 ** (k - 1) % 10
            rest = m % 10 ** (k - 1)
            inexact = rd != 0 or rest != 0
            if mode == Round.PROHIBITED:
                if inexact:
                    return Bcd(0, False, True, False)
                if k % 2 == 0:  # rounding digit in a low nibble: target untouched, no exception
                    return Bcd(0, False, False, False)
            elif mode in (Round.NEAREST_AWAY_FROM_ZERO, Round.NEAREST_EVEN):
                m += 5 * 10 ** (k - 1)
            elif mode == Round.NEAREST_TOWARD_ZERO:
                if rd > 5 or (rd == 5 and rest != 0):
                    m += 10**k
            elif (mode == Round.AWAY_FROM_ZERO or (mode == Round.TOWARD_GREATER and positive)
                  or (mode == Round.TOWARD_LESSER and not positive)):
                if inexact:
                    m += 10**k
        m //= 10**k
    # capacity check uses GnuCOBOL's digit count: for 9(n)P(m) items the P positions count, so
    # an "even" count makes the top stored digit look like a pad nibble (and vice versa)
    nib = 2 * dst.byte_length - (2 if gc_digits(dst) % 2 == 0 else 1)
    err = m >= 10**nib
    if err:
        if size != SizeError.NONE:
            return Bcd(0, False, True, False)
        m %= 10**nib
    pad, m = divmod(m, 10**dst.digits)
    if not dst.signed:
        return Bcd(m, False, err, True, pad)
    return Bcd(m if positive else -m, not positive and m == 0, err, True, pad)


def packed_int_add(full: int, neg: bool, n: int, dst: NumPic) -> tuple[int, int] | None:
    """cob_add_packed_int: ADD integer n TO a scale-0 COMP-3 item without ROUNDED/SIZE ERROR.

    When n has the item's sign the digits (including the pad nibble of an even digit count) are
    added in place and any carry out of the first byte is lost, so the pad nibble can receive a
    digit. Returns (new magnitude without pad, pad digit), or None when GnuCOBOL falls back to the
    ordinary decimal ADD (opposite signs).
    """
    if (n > 0 and neg) or (n < 0 and not neg):
        return None
    nib = 2 * dst.byte_length - 1
    total = (full + abs(n)) % 10**nib
    return total % 10**dst.digits, total // 10**dst.digits


def compare(u1: int, s1: int, u2: int, s2: int) -> int:
    """Numeric comparison (-1, 0, 1) of two scaled values; negative zero equals zero."""
    s = max(s1, s2)
    a, b = shift(u1, s - s1), shift(u2, s - s2)
    return (a > b) - (a < b)


def fits(u: int, pic: NumPic) -> bool:
    """Is `u` a value the field can hold (its PIC domain; for COMP-5 the binary range)?"""
    return pic.min_unscaled <= u <= pic.max_unscaled


__all__ = [
    "MAX_DIGITS", "NAN", "ZERO", "Dec", "Stored", "compare", "fits", "keeps_on_overflow", "move_literal",
    "move_num", "move_value", "parse_literal", "pow10", "rescale", "round_to", "shift", "sign", "size_error",
    "store", "tdiv", "trem",
]
