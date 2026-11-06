"""Object API for generated code: `CobolDecimal` (numeric item) and `PicX` (alphanumeric item).

Every statement method returns True when a size error occurred, so
`ADD A TO B ON SIZE ERROR ... NOT ON SIZE ERROR ...` becomes
`if b.add(a, size=SizeError.ON): ... else: ...`.
"""

from __future__ import annotations

from typing import Union

from cobolrt import alnum, codec
from cobolrt.num import (
    Dec, Stored, bcd_add, field_fits_int, gc_digits, literal_fits_int, move_literal, move_num, packed_int_add,
    parse_literal, shift, store, tdiv,
)
from cobolrt.pic import AlnumPic, NumPic, Round, SizeError, Usage, parse_pic

INT_MIN, INT_MAX = -(2**31), 2**31 - 1


class CobolDecimal:
    """A numeric elementary item: unscaled integer + PIC (digits, scale, signed, usage).

    Besides the value it tracks the storage details GnuCOBOL can leave behind and that only
    show in the record bytes: `negzero` (negative zero in a DISPLAY/COMP-3 item), and for
    COMP-3 `fnib` (sign nibble F in a signed item) and `pad` (garbage digit in the pad nibble).
    """

    __slots__ = ("fnib", "negzero", "pad", "pic", "u")

    def __init__(self, pic: NumPic | str, usage: str | Usage = Usage.DISPLAY, sign: str = "",
                 value: Operand | None = None) -> None:
        if isinstance(pic, str):
            p = parse_pic(pic, usage, sign)
            if not isinstance(p, NumPic):
                raise ValueError(f"{pic!r} is not a numeric PICTURE")
            pic = p
        self.pic: NumPic = pic
        self.u = 0
        self.negzero = False
        self.fnib = False
        self.pad = 0
        if value is not None:
            self.move(value)

    # ---- state -------------------------------------------------------------------------------
    @property
    def unscaled(self) -> int:
        return self.u

    @property
    def scale(self) -> int:
        return self.pic.scale

    def dec(self) -> Dec:
        """The value as an exact intermediate (for COMPUTE expressions)."""
        return Dec(self.u, self.pic.scale)

    def set_unscaled(self, u: int, negzero: bool = False) -> None:
        """Set the raw state (no truncation; the caller guarantees the value fits)."""
        self._set(u, negzero and u == 0)

    def _set(self, u: int, negzero: bool = False, fnib: bool = False, pad: int = 0) -> None:
        self.u, self.negzero, self.fnib, self.pad = u, negzero, fnib, pad

    def _apply(self, r: Stored) -> bool:
        if r.stored:
            self._set(r.u, r.negzero)
        return r.size_error

    @property
    def _dneg(self) -> bool:
        """COMP-3 sign nibble is D."""
        return self.pic.signed and (self.u < 0 or self.negzero) and not self.fnib

    @property
    def _full(self) -> int:
        """Magnitude including a garbage pad digit (what the BCD routines see)."""
        return abs(self.u) + (self.pad * 10**self.pic.digits if self.pic.usage == Usage.COMP3 else 0)

    # ---- MOVE --------------------------------------------------------------------------------
    def move(self, src: Operand | PicX | bytes) -> None:
        """MOVE src TO self (numeric item, numeric literal text/int, or alphanumeric data)."""
        if isinstance(src, CobolDecimal):
            self._move_item(src)
        elif isinstance(src, PicX):
            self._set(*alnum.alnum_to_num(src.data, self.pic))
        elif isinstance(src, (bytes, bytearray)):
            self._set(*alnum.alnum_to_num(bytes(src), self.pic))
        elif isinstance(src, Dec):
            self.store(src)
        else:
            self._move_literal(str(src))

    def _move_literal(self, text: str) -> None:
        d = self.pic
        if d.usage == Usage.COMP3 and d.scale >= 0 and literal_fits_int(text):
            # cobc converts small integer literals at compile time (cob_set_packed_int)
            u, _s, _neg = parse_literal(text)
            ndig = len(text.strip().lstrip("+-"))
            if ndig + d.scale <= 9:
                self._set_packed_int(u * 10**d.scale)
                return
        self._set(*move_literal(text, d))

    def _set_packed_int(self, val: int) -> None:
        """cob_set_packed_int: zero is +0; digits beyond the item spill into the pad nibble."""
        d = self.pic
        if val == 0:
            self._set(0)
            return
        full = abs(val) % 10 ** (2 * d.byte_length - 1)
        mag = full % 10**d.digits
        neg = val < 0 and d.signed
        self._set(-mag if neg else mag, neg and mag == 0, False, full // 10**d.digits)

    def _move_item(self, src: CobolDecimal) -> None:
        d = self.pic
        if src.pic == d:  # identical descriptions: cobc copies the bytes
            self._set(src.u, src.negzero, src.fnib, src.pad)
            return
        if src.pic.usage == Usage.COMP3 and d.usage == Usage.COMP3 and src.pic.scale >= 0 and d.scale >= 0:
            # cob_move_bcd: digits are copied, the sign nibble is copied as is (C, D or F)
            mag = shift(src._full, d.scale - src.pic.scale) % 10**d.digits
            if not d.signed:
                self._set(mag)
            elif src._dneg:
                self._set(-mag, mag == 0)
            else:
                self._set(mag, False, not src.pic.signed or src.fnib)
            return
        if src.pic.is_binary and d.usage == Usage.COMP3:
            # binary -> packed: small values go through cob_set_packed_int, which writes all the
            # digits it can fit, so an even-digit item may get a digit in its pad nibble
            diff = src.pic.scale - d.scale
            if src.pic.digits < 19 and src.pic.digits - diff < 19:
                val = tdiv(src.u, 10**diff) if diff > 0 else src.u * 10**-diff
                if INT_MIN <= val <= INT_MAX:
                    self._set_packed_int(val)
                    return
        self._set(*move_num(src.u, src.negzero, src.pic, d))

    # ---- arithmetic statements ---------------------------------------------------------------
    def store(self, value: Dec, rounded: Round = Round.TRUNCATION, size: SizeError = SizeError.NONE) -> bool:
        """Store an intermediate result with optional ROUNDED / SIZE ERROR handling."""
        return self._apply(store(value.value, value.scale, self.pic, rounded, size, nan=value.nan,
                                 old_u=self.u, old_negzero=self.negzero))

    def compute(self, value: Operand, rounded: Round = Round.TRUNCATION,
                size: SizeError = SizeError.NONE) -> bool:
        """COMPUTE self [ROUNDED] = value (also the GIVING forms of ADD/SUBTRACT/...)."""
        return self.store(operand(value), rounded, size)

    def add(self, x: Operand, rounded: Round = Round.TRUNCATION, size: SizeError = SizeError.NONE) -> bool:
        """ADD x TO self."""
        return self._addsub(x, rounded, size, False)

    def subtract(self, x: Operand, rounded: Round = Round.TRUNCATION,
                 size: SizeError = SizeError.NONE) -> bool:
        """SUBTRACT x FROM self."""
        return self._addsub(x, rounded, size, True)

    def multiply(self, x: Operand, rounded: Round = Round.TRUNCATION,
                 size: SizeError = SizeError.NONE) -> bool:
        """MULTIPLY x BY self."""
        return self.store(self.dec().mul(operand(x)), rounded, size)

    def divide(self, x: Operand, rounded: Round = Round.TRUNCATION, size: SizeError = SizeError.NONE) -> bool:
        """DIVIDE x INTO self."""
        return self.store(self.dec().div(operand(x)), rounded, size)

    def _addsub(self, x: Operand, rounded: Round, size: SizeError, sub: bool) -> bool:
        """ADD/SUBTRACT x TO/FROM self, following the code path cobc selects (cb_build_add)."""
        p = self.pic
        opt0 = (rounded == Round.TRUNCATION and p.usage != Usage.COMP
                and (size == SizeError.NONE or (p.usage == Usage.COMP5 and size == SizeError.NOT_ONLY)))
        n = int_operand(x)
        if opt0 and n is not None:
            if (sub and p.usage == Usage.COMP3 and p.scale == 0 and 10 <= gc_digits(p) <= 18
                    and isinstance(x, CobolDecimal) and x.pic.is_binary and not x.pic.signed
                    and x.pic.byte_length == 4 and n != 0):
                # cobc negates the operand as a C unsigned int before widening it to 64 bits
                # (CB_CAST_NEGATIVE_LONG_INT): the item is increased by 2**32 - n (measured)
                n = 2**32 - n
            else:
                n = -n if sub else n
            if n == 0:
                return False  # cob_add_int / native add of 0: item untouched
            if p.scale < 0:  # cob_add_int on 9(n)P(m): n is truncated to the item's unit first
                val = tdiv(n, 10**-p.scale)
                if val == 0:
                    return False
                return self._apply(store(self.u + val, p.scale, p, Round.TRUNCATION, SizeError.NONE))
            if p.scale == 0 and p.usage == Usage.COMP5:  # native C arithmetic: wraps, no size error
                bits = 8 * p.byte_length
                w = (self.u + n) % (1 << bits)
                if p.signed and w >= 1 << (bits - 1):
                    w -= 1 << bits
                self._set(w)
                return False
            if p.scale == 0 and p.usage == Usage.COMP3:
                r = packed_int_add(self._full, self._dneg, n, p)
                if r is not None:
                    mag, pad = r
                    if self._dneg:
                        self._set(-mag, mag == 0, False, pad)
                    else:
                        self._set(mag, False, self.fnib, pad)
                    return False
            d = self.dec().add(Dec(n, 0))
            return self._apply(store(d.value, d.scale, p, Round.TRUNCATION, SizeError.NONE,
                                     old_u=self.u, old_negzero=self.negzero))
        if p.usage == Usage.COMP3 and not isinstance(x, Dec):
            xm, xneg, xs = bcd_operand(x)
            r2 = bcd_add(self._full, self._dneg, p.scale, xm, xneg, xs, p, rounded, size, sub)
            if r2.stored:
                self._set(r2.u, r2.negzero, False, r2.pad)
            return r2.size_error
        o = operand(x)
        return self.store(self.dec().sub(o) if sub else self.dec().add(o), rounded, size)

    # ---- output ------------------------------------------------------------------------------
    def display(self) -> bytes:
        return codec.display(self.u, self.pic)

    def __str__(self) -> str:
        return self.display().decode("latin-1")

    def __repr__(self) -> str:
        return f"CobolDecimal({self.pic.picture()} {self.pic.usage.name} = {self})"

    def encode(self) -> bytes:
        return codec.encode(self.u, self.pic, self.negzero, self.fnib, self.pad)

    def decode(self, data: bytes) -> None:
        self._set(*codec.decode_state(data, self.pic))

    def compare(self, other: Operand) -> int:
        """Numeric comparison self <=> other (-1, 0, 1), as in `IF self < other`."""
        o = operand(other)
        p = self.pic
        if (p.is_binary and not p.signed and p.scale == 0 and p.byte_length == 8 and o.value < 0
                and fits_long_long(other)):
            return -1  # cobc compares as C unsigned long long (cob_cmp_u64): negatives look huge
        a = self.dec().sub(o)
        return (a.value > 0) - (a.value < 0)

    def accept(self, line: str | bytes | None) -> None:
        """ACCEPT self (line without newline; None at end of input)."""
        self._set(*alnum.accept_num(line, self.pic))


class PicX:
    """PIC X(n) [JUSTIFIED RIGHT] held as `length` bytes (ISO-8859-1), initially spaces."""

    __slots__ = ("data", "justified", "length")

    def __init__(self, length: int | AlnumPic, justified: bool = False,
                 value: str | bytes | None = None) -> None:
        if isinstance(length, AlnumPic):
            justified, length = length.justified, length.length
        self.length = length
        self.justified = justified
        self.data = b" " * length
        if value is not None:
            # a VALUE clause is not justified (measured)
            self.data = alnum.move(value, length, False)

    def move(self, src: PicX | CobolDecimal | str | bytes) -> None:
        """MOVE src TO self."""
        if isinstance(src, PicX):
            self.data = alnum.move(src.data, self.length, self.justified)
        elif isinstance(src, CobolDecimal):
            self.data = alnum.num_to_alnum(src.u, src.pic, self.length, self.justified)
        else:
            self.data = alnum.move(src, self.length, self.justified)

    def accept(self, line: str | bytes | None) -> None:
        self.data = alnum.accept_alnum(line, AlnumPic(self.length, self.justified))

    def compare(self, other: PicX | str | bytes) -> int:
        return alnum.compare(self.data, other.data if isinstance(other, PicX) else other)

    def refmod(self, start: int, length: int | None = None) -> bytes:
        return alnum.refmod(self.data, start, length)

    def set_refmod(self, start: int, length: int | None, value: str | bytes) -> None:
        self.data = alnum.set_refmod(self.data, start, length, value)

    def display(self) -> bytes:
        return self.data

    def encode(self) -> bytes:
        return self.data

    def __str__(self) -> str:
        return self.data.decode("latin-1")

    def __repr__(self) -> str:
        return f"PicX({self.length}, {self.data!r})"


Operand = Union[CobolDecimal, Dec, str, int]


def operand(x: Operand) -> Dec:
    """A statement operand as an intermediate: item, literal text (`"1.5"`), int or Dec."""
    if isinstance(x, CobolDecimal):
        return x.dec()
    if isinstance(x, Dec):
        return x
    if isinstance(x, int):
        return Dec(x, 0)
    u, s, _ = parse_literal(x)
    return Dec(u, s)


def int_operand(x: Operand) -> int | None:
    """The operand's value when cobc treats it as a C int (cb_fits_int), else None."""
    if isinstance(x, CobolDecimal):
        if not field_fits_int(x.pic):
            return None
        return x.u * 10**-x.pic.scale
    if isinstance(x, Dec):
        return None
    if isinstance(x, int):
        return x if INT_MIN <= x <= INT_MAX else None
    return parse_literal(x)[0] if literal_fits_int(x) else None


def fits_long_long(x: Operand) -> bool:
    """cb_fits_long_long for a statement operand."""
    if isinstance(x, CobolDecimal):
        p = x.pic
        if p.scale > 0:
            return False
        if p.usage == Usage.DISPLAY:
            return p.byte_length < 19
        if p.usage == Usage.COMP3:
            return gc_digits(p) < 19
        return True
    if isinstance(x, Dec):
        return False
    if isinstance(x, int):
        return -(2**63) <= x < 2**63
    u, s, _ = parse_literal(x)
    return s == 0 and -(2**63) <= u < 2**63


def bcd_operand(x: CobolDecimal | str | int) -> tuple[int, bool, int]:
    """(magnitude, D sign nibble, scale) of the packed temporary cob_add_bcd works on."""
    if isinstance(x, CobolDecimal):
        if x.pic.usage == Usage.COMP3:
            return x._full, x._dneg, x.pic.scale
        if x.pic.is_binary:
            size = x.pic.digits // 2 + 1
            return abs(x.u) % 10 ** (2 * size - 1), x.u < 0, x.pic.scale
        mag = abs(x.u)
        if x.pic.scale < 0:
            # the packed temporary has GnuCOBOL's digit count (P included) but
            # cob_move_display_to_packed fills it as if it had only the stored digits:
            # the value lands shifted left (measured)
            size = gc_digits(x.pic) // 2 + 1
            i0 = 1 - x.pic.digits % 2
            mag *= 10 ** ((2 * size - 1) - (i0 + x.pic.digits))
        return mag, x.u < 0 or x.negzero, x.pic.scale
    u, s, neg = parse_literal(str(x))
    return abs(u), neg, s


def divide_remainder(dividend: Operand, divisor: Operand, quotient: CobolDecimal, remainder: CobolDecimal,
                     rounded: Round = Round.TRUNCATION, size: SizeError = SizeError.NONE) -> bool:
    """DIVIDE dividend BY divisor GIVING quotient [ROUNDED] REMAINDER remainder.

    (`DIVIDE a INTO b GIVING q REMAINDER r` is `divide_remainder(b, a, q, r)`.) The remainder is
    dividend - q' * divisor where q' is the quotient truncated to the quotient's scale but *not*
    rounded or high-order truncated; it is stored even when the quotient raised a size error.
    Division by zero leaves both items unchanged.
    """
    a, b = operand(dividend), operand(divisor)
    q = a.div(b)
    if q.nan:
        quotient.store(q, rounded, size)
        remainder.store(q, Round.TRUNCATION, size)
        return True
    e1 = quotient.store(q, rounded, size)
    qt = Dec(0, 0) if q.value == 0 else Dec(shift(q.value, quotient.pic.scale - q.scale), quotient.pic.scale)
    rem = a.sub(qt.mul(b))
    e2 = remainder.store(rem, Round.TRUNCATION, size)
    return e1 or e2


def display_line(*items: CobolDecimal | PicX | str | bytes) -> bytes:
    """The bytes `DISPLAY item item ...` writes (including the newline)."""
    out = b""
    for it in items:
        if isinstance(it, (CobolDecimal, PicX)):
            out += it.display()
        else:
            out += alnum.to_bytes(it)
    return out + b"\n"


__all__ = ["CobolDecimal", "Operand", "PicX", "display_line", "divide_remainder", "operand"]
