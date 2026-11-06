"""Concrete interpreter for the COBOL IR over a byte-exact storage model (spec section 6, T2b.2).

The model reproduces GnuCOBOL 3.2 (`cobc -std=default`) exactly, not "COBOL in general":

* storage is byte-exact (sizes/offsets from datadiv; REDEFINES, group moves, OCCURS and encodings
  behave like the real memory);
* the runtime operations are a port of the libcob functions cobc's generated C calls
  (numeric.c `cob_decimal_*`, `cob_add_bcd`, move.c `cob_move` and its helpers, termio.c DISPLAY /
  ACCEPT, common.c comparisons and class tests, fileio.c sequential / line-sequential I/O);
* every statement takes the code path cobc 3.2 generates for it (e.g. `ADD 1 TO X` on a DISPLAY
  item is `cob_add_int`, on a short COMP-3 item the inline `cob_add_packed_int`, on COMP-5 a native
  C addition; operand lists and GIVING are decimal expressions; conditions use cobc's optimised
  compare selection).

Findings and probes are documented in docs/spikes/S7.md. Anything the model cannot reproduce raises
`InterpUnsupported` (a model limitation, never a guess).

Entry points:
    run_program(ir, stdin=b"", files={}, args=[], env={}) -> ProgramResult
    run_paragraph(ir, name, values={}) -> ParagraphResult
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from verifier.cobol import ir as I
from verifier.cobol.datadiv import DataItem

# =============================================================================================
# errors
# =============================================================================================


class InterpUnsupported(Exception):
    """The model cannot reproduce GnuCOBOL here (undefined behaviour or an unported path)."""


class CobolRuntimeError(Exception):
    """GnuCOBOL would stop with a `libcob: error` (T1 excludes such cases)."""


class _StopRun(Exception):
    pass


class _GoTo(Exception):
    def __init__(self, target: str) -> None:
        super().__init__(target)
        self.target = target


class _ExitPerform(Exception):
    def __init__(self, cycle: bool) -> None:
        super().__init__("EXIT PERFORM")
        self.cycle = cycle


class _ExitParagraph(Exception):
    def __init__(self, section: bool) -> None:
        super().__init__("EXIT PARAGRAPH")
        self.section = section


# =============================================================================================
# field model (cob_field / cob_field_attr)
# =============================================================================================
T_GROUP = 1
T_ALNUM = 2
T_ALL = 3  # figurative constant / ALL literal
T_DISP = 4  # COB_TYPE_NUMERIC_DISPLAY
T_BIN = 5  # COB_TYPE_NUMERIC_BINARY (COMP, and COMP-5 with real=True)
T_PACKED = 6  # COB_TYPE_NUMERIC_PACKED
T_EDIT = 7  # COB_TYPE_NUMERIC_EDITED

NUMERIC_TYPES = (T_DISP, T_BIN, T_PACKED)

# store options (common.h)
ST_ROUND = 1 << 0
ST_KEEP = 1 << 1
ST_TRUNC = 1 << 2
ST_NO_SIZE_ERROR = 1 << 15
ST_MASK = ST_ROUND | ST_KEEP | ST_TRUNC | ST_NO_SIZE_ERROR

# exceptions
EC_SIZE_OVERFLOW = 0x1004
EC_SIZE_TRUNCATION = 0x1005
EC_SIZE_ZERO_DIVIDE = 0x1007
EC_SIZE_EXPONENTIATION = 0x1002
EC_IMP_ACCEPT = 0x9999  # only tracked, never handled (ACCEPT ON EXCEPTION is unsupported)

NAN_SCALE = -32768
MAX_DIGITS = 38


@dataclass(frozen=True)
class Attr:
    type: int
    digits: int = 0
    scale: int = 0
    signed: bool = False
    sep: bool = False
    lead: bool = False
    just: bool = False
    trunc: bool = False  # COB_FLAG_BINARY_TRUNC
    real: bool = False  # COB_FLAG_REAL_BINARY (COMP-5)
    swap: bool = False  # COB_FLAG_BINARY_SWAP (big-endian COMP)
    pic: tuple[tuple[str, int], ...] = ()


class F:
    """A cob_field: `size` bytes of buffer `b` at offset `o`."""

    __slots__ = ("a", "b", "o", "size")

    def __init__(self, b: bytearray, o: int, size: int, a: Attr) -> None:
        self.b = b
        self.o = o
        self.size = size
        self.a = a

    def data(self) -> bytes:
        return bytes(self.b[self.o: self.o + self.size])

    def set(self, data: bytes) -> None:
        assert len(data) == self.size
        self.b[self.o: self.o + self.size] = data

    def __repr__(self) -> str:
        return f"F({self.data()!r}, type={self.a.type}, d={self.a.digits}, s={self.a.scale})"


def temp_field(a: Attr, size: int, fill: int = 0) -> F:
    return F(bytearray([fill]) * size, 0, size, a)


def fdata_start(f: F) -> int:
    """COB_FIELD_DATA offset."""
    return f.o + (1 if (f.a.sep and f.a.lead and f.a.signed) else 0)


def fdata_size(f: F) -> int:
    """COB_FIELD_SIZE."""
    return f.size - (1 if (f.a.sep and f.a.signed) else 0)


def _tdiv_q(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def _tdiv_r(a: int, b: int) -> int:
    return a - b * _tdiv_q(a, b)


# =============================================================================================
# signs (common.c cob_real_get_sign / cob_real_put_sign, ASCII, ebcdic-sign: no)
# =============================================================================================
def _locate_sign(f: F) -> int:
    return f.o if f.a.lead else f.o + f.size - 1


def get_sign(f: F) -> int:
    """COB_GET_SIGN: may un-punch the sign byte (it is re-punched by put_sign)."""
    if not f.a.signed:
        return 0
    if f.a.type == T_DISP:
        p = _locate_sign(f)
        c = f.b[p]
        if f.a.sep:
            return -1 if c == 0x2D else 1
        if 0x30 <= c <= 0x39 or c == 0x20:
            return 1
        if 0x70 <= c <= 0x79:
            f.b[p] = c & ~0x40
            return -1
        f.b[p] = 0x30
        return 1
    if f.a.type == T_PACKED:
        return -1 if (f.b[f.o + f.size - 1] & 0x0F) == 0x0D else 1
    return 0


def get_sign_adjust(f: F) -> int:
    """COB_GET_SIGN_ADJUST (ASCII: no modification of the data)."""
    if not f.a.signed:
        return 0
    if f.a.type == T_DISP:
        p = _locate_sign(f)
        c = f.b[p]
        if f.a.sep:
            return -1 if c == 0x2D else 1
        if 0x30 <= c <= 0x39 or c == 0x20:
            return 1
        return -1 if (c & 0xF0) == 0x70 else 1
    if f.a.type == T_PACKED:
        return -1 if (f.b[f.o + f.size - 1] & 0x0F) == 0x0D else 1
    return 0


def put_sign(f: F, sign: int) -> None:
    """COB_PUT_SIGN."""
    if not f.a.signed:
        return
    if f.a.type == T_DISP:
        if f.a.sep:
            f.b[_locate_sign(f)] = 0x2D if sign == -1 else 0x2B
        elif sign == -1:
            f.b[_locate_sign(f)] |= 0x40
        return
    if f.a.type == T_PACKED:
        p = f.o + f.size - 1
        f.b[p] = (f.b[p] & 0xF0) | (0x0D if sign == -1 else 0x0C)


# =============================================================================================
# decimals (numeric.c)
# =============================================================================================
class Dec:
    __slots__ = ("scale", "value")

    def __init__(self, value: int = 0, scale: int = 0) -> None:
        self.value = value
        self.scale = scale

    def copy(self) -> Dec:
        return Dec(self.value, self.scale)

    def __repr__(self) -> str:
        return f"Dec({self.value}, {self.scale})"


def shift_decimal(d: Dec, n: int) -> None:
    if n > 0:
        d.value *= 10 ** n
    else:
        d.value = _tdiv_q(d.value, 10 ** (-n))
    d.scale += n


def _align(d1: Dec, d2: Dec) -> None:
    if d1.scale < d2.scale:
        shift_decimal(d1, d2.scale - d1.scale)
    elif d1.scale > d2.scale:
        shift_decimal(d2, d1.scale - d2.scale)


PACK_TO_BIN = [
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
    10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25,
    20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 25,
    30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45,
    40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55,
    50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65,
    60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75,
    70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85,
    80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95,
    90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 103, 104, 105,
    100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115,
    110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125,
    120, 121, 122, 123, 124, 125, 126, 127, 128, 129, 130, 131, 132, 133, 134, 135,
    130, 131, 132, 133, 134, 135, 136, 137, 138, 139, 140, 141, 142, 143, 144, 145,
    140, 141, 142, 143, 144, 145, 146, 147, 148, 149, 150, 151, 152, 153, 154, 155,
    150, 151, 152, 153, 154, 155, 156, 157, 158, 159, 160, 161, 162, 163, 164, 165,
]


def _real_digits(f: F) -> int:
    return f.a.digits if f.a.scale >= 0 else f.a.digits + f.a.scale


def binary_get(f: F, signed: bool | None = None) -> int:
    """cob_binary_mget_sint64 / uint64."""
    raw = bytes(f.b[f.o: f.o + f.size])
    s = f.a.signed if signed is None else signed
    return int.from_bytes(raw, "big" if f.a.swap else "little", signed=s)


def binary_set(f: F, n: int) -> None:
    """cob_binary_mset_[su]int64: store the low `size` bytes of the 64-bit value."""
    n &= (1 << 64) - 1
    raw = n.to_bytes(8, "little")[: f.size]
    if f.a.swap:
        raw = raw[::-1]
    f.b[f.o: f.o + f.size] = raw


def dec_set_display(f: F) -> Dec:
    d0 = fdata_start(f)
    size = fdata_size(f)
    sign = get_sign_adjust(f)
    b = f.b
    if b[d0] == 255:
        return Dec(10 ** size, f.a.scale)
    if b[d0] == 0:
        return Dec(-(10 ** size), f.a.scale)
    p = d0
    while size > 1 and (b[p] & 0x0F) == 0:
        size -= 1
        p += 1
    n = 0
    if size < 20:
        for i in range(size):
            n = n * 10 + (b[p + i] & 0x0F)
        n &= (1 << 64) - 1
    else:
        digs = [b[p + i] & 0x0F for i in range(size)]
        if any(x > 9 for x in digs):
            raise InterpUnsupported("invalid digit data in a long DISPLAY item")
        n = int("".join(map(str, digs)))
    if sign < 0:
        n = -n
    return Dec(n, f.a.scale)


def dec_set_packed(f: F) -> Dec:
    b = f.b
    p = f.o
    endp = f.o + f.size - 1
    digits = _real_digits(f)
    if (digits & 1) == 0:
        val = b[p] & 0x0F
        p += 1
    else:
        val = 0
    while p < endp:
        val = val * 100 + PACK_TO_BIN[b[p]]
        p += 1
    val = val * 10 + (b[p] >> 4)
    if f.a.signed and (b[endp] & 0x0F) == 0x0D:
        val = -val
    return Dec(val, f.a.scale)


def dec_set_field(f: F) -> Dec:
    t = f.a.type
    if t == T_BIN:
        return Dec(binary_get(f), f.a.scale)
    if t == T_PACKED:
        return dec_set_packed(f)
    if t == T_DISP:
        return dec_set_display(f)
    raise InterpUnsupported(f"decimal value of a non-numeric field (type {t})")


class Rt:
    """Mutable runtime state shared by the libcob port (exception code)."""

    def __init__(self) -> None:
        self.exception = 0

    def set_exception(self, code: int) -> None:
        self.exception = code


def _do_round(d: Dec, f: F, opt: int) -> int:
    sign = (d.value > 0) - (d.value < 0)
    scale = f.a.scale
    if sign == 0 or scale >= d.scale:
        return 0
    mode = opt & ~ST_MASK
    if mode != 0:
        raise InterpUnsupported("ROUNDED MODE other than the default")
    n = scale - d.scale + 1
    if n != 0:
        shift_decimal(d, n)
    if sign == 1:
        d.value += 5
    else:
        d.value -= 5
    return 0


def dec_get_field(rt: Rt, d0: Dec, f: F, opt: int) -> int:
    """cob_decimal_get_field: store d into f; returns the exception code (0 = stored)."""
    if d0.scale == NAN_SCALE:
        if not rt.exception or rt.exception != EC_SIZE_ZERO_DIVIDE:
            rt.set_exception(EC_SIZE_OVERFLOW)
        return rt.exception
    d = d0.copy()
    if opt & ST_ROUND:
        _do_round(d, f, opt)
    n = f.a.scale - d.scale
    if n != 0:
        if d.value == 0:
            d.scale = 0
        else:
            shift_decimal(d, n)
    t = f.a.type
    if t == T_BIN:
        return _get_binary(rt, d, f, opt)
    if t == T_DISP:
        return _get_display(rt, d, f, opt)
    if t == T_PACKED:
        return _get_packed(rt, d, f, opt)
    if t == T_EDIT:
        # default: build a signed DISPLAY temporary with the field's digits/scale, then MOVE it
        tmp = temp_field(Attr(T_DISP, f.a.digits, f.a.scale, signed=True), f.a.digits, 0)
        if _get_display(rt, d, tmp, opt) != 0:
            return rt.exception
        cob_move(rt, tmp, f)
        return 0
    raise InterpUnsupported(f"store into field type {t}")


def _get_display(rt: Rt, d: Dec, f: F, opt: int) -> int:
    start = fdata_start(f)
    fsize = fdata_size(f)
    sign = (d.value > 0) - (d.value < 0)
    if sign == 0:
        f.b[start: start + fsize] = b"0" * fsize
        put_sign(f, 0)
        return 0
    v = abs(d.value)
    if fsize > MAX_DIGITS:
        raise InterpUnsupported("DISPLAY item with more than 38 digits")
    lim = 10 ** fsize
    if v >= lim:
        if not opt & ST_NO_SIZE_ERROR:
            rt.set_exception(EC_SIZE_OVERFLOW)
            if opt & ST_KEEP:
                return rt.exception
        v %= lim
    f.b[start: start + fsize] = str(v).rjust(fsize, "0").encode("ascii")
    put_sign(f, sign)
    return 0


def _set_packed_zero(f: F) -> None:
    f.b[f.o: f.o + f.size] = bytes(f.size)
    f.b[f.o + f.size - 1] = 0x0C if f.a.signed else 0x0F


def _pack_digits(f: F, n: int, sign: int) -> None:
    """cob_set_packed_u64 / string path: n (>= 0) right-aligned, sign nibble last."""
    nibbles = 2 * f.size - 1
    s = str(n)
    if len(s) > nibbles:
        s = s[-nibbles:]
    s = s.rjust(nibbles, "0")
    sn = 0x0F if not f.a.signed else (0x0D if sign == -1 else 0x0C)
    vals = [int(c) for c in s] + [sn]
    f.b[f.o: f.o + f.size] = bytes((vals[i] << 4) | vals[i + 1] for i in range(0, len(vals), 2))


def _get_packed(rt: Rt, d: Dec, f: F, opt: int) -> int:
    sign = (d.value > 0) - (d.value < 0)
    if sign == 0:
        _set_packed_zero(f)
        return 0
    v = abs(d.value)
    lim = 10 ** _real_digits(f)
    if v >= lim:
        if not opt & ST_NO_SIZE_ERROR:
            rt.set_exception(EC_SIZE_OVERFLOW)
            if opt & ST_KEEP:
                return rt.exception
        v %= lim
    _pack_digits(f, v, sign)
    return 0


def _get_binary(rt: Rt, d: Dec, f: F, opt: int) -> int:
    field_sign = 1 if f.a.signed else 0
    bitnum = f.size * 8 - field_sign
    v = d.value
    if v == 0:
        f.b[f.o: f.o + f.size] = bytes(f.size)
        return 0
    overflow = False
    if not field_sign and v < 0:
        v = -v
    if abs(v).bit_length() > bitnum:
        if opt & ST_KEEP:
            return _bin_overflow(rt, opt)
        overflow = True
        v = _tdiv_r(v, 10 ** _real_digits(f)) if opt & ST_TRUNC else v % (1 << f.size * 8)
    elif opt and f.a.trunc:
        lim = 10 ** _real_digits(f)
        if abs(v) >= lim:
            if opt & ST_KEEP:
                return _bin_overflow(rt, opt)
            overflow = True
            v = _tdiv_r(v, lim) if opt & ST_TRUNC else v % (1 << f.size * 8)
    if not field_sign or (overflow and not opt & ST_TRUNC):
        binary_set(f, abs(v) & ((1 << 64) - 1))  # mpz_get_ui: low bits of |v|
    else:
        binary_set(f, v)
    if not overflow:
        return 0
    return _bin_overflow(rt, opt)


def _bin_overflow(rt: Rt, opt: int) -> int:
    if not opt & ST_NO_SIZE_ERROR:
        rt.set_exception(EC_SIZE_OVERFLOW)
    return rt.exception


def dec_add(d1: Dec, d2: Dec) -> None:
    if d1.scale == NAN_SCALE or d2.scale == NAN_SCALE:
        d1.scale = NAN_SCALE
        return
    if d1.scale != d2.scale:
        if d2.value == 0:
            return
        if d1.value == 0:
            d1.value, d1.scale = d2.value, d2.scale
            return
        t2 = d2.copy()
        _align(d1, t2)
        d1.value += t2.value
    else:
        d1.value += d2.value


def dec_sub(d1: Dec, d2: Dec) -> None:
    if d1.scale == NAN_SCALE or d2.scale == NAN_SCALE:
        d1.scale = NAN_SCALE
        return
    if d1.scale != d2.scale:
        if d2.value == 0:
            return
        t2 = d2.copy()
        _align(d1, t2)
        d1.value -= t2.value
    else:
        d1.value -= d2.value


def dec_mul(d1: Dec, d2: Dec) -> None:
    if d1.scale == NAN_SCALE or d2.scale == NAN_SCALE:
        d1.scale = NAN_SCALE
        return
    d1.scale += d2.scale
    d1.value *= d2.value


def dec_div(rt: Rt, d1: Dec, d2: Dec) -> None:
    if d1.scale == NAN_SCALE or d2.scale == NAN_SCALE:
        d1.scale = NAN_SCALE
        return
    if d2.value == 0:
        d1.scale = NAN_SCALE
        rt.set_exception(EC_SIZE_ZERO_DIVIDE)
        return
    if d1.value == 0:
        d1.scale = 0
        return
    d1.scale -= d2.scale
    shift_decimal(d1, MAX_DIGITS + (-d1.scale if d1.scale < 0 else 0))
    d1.value = _tdiv_q(d1.value, d2.value)


def _trim(d: Dec) -> None:
    if d.value == 0:
        d.scale = 0
        return
    while d.scale > 0 and d.value % 10 == 0:
        d.value = _tdiv_q(d.value, 10)
        d.scale -= 1


def dec_pow(rt: Rt, pd1: Dec, pd2: Dec) -> None:
    """intrinsic.c cob_decimal_pow for integer exponents (others are computed with GMP floats and
    are not modelled). Like the C code it modifies `pd2`: cobc passes the *shared* decimal
    constant of a literal exponent, so after `X ** -1` that constant holds the base (see S7)."""
    if pd1.scale == NAN_SCALE:
        return
    if pd2.scale == NAN_SCALE:
        pd1.scale = NAN_SCALE
        return
    sign = (pd1.value > 0) - (pd1.value < 0)
    if pd2.value == 0:
        if sign == 0:
            rt.set_exception(EC_SIZE_EXPONENTIATION)
        pd1.value, pd1.scale = 1, 0
        return
    if sign == 0:
        pd1.scale = 0
        return
    _trim(pd2)
    if sign == -1 and pd2.scale:
        pd1.scale = NAN_SCALE
        rt.set_exception(EC_SIZE_EXPONENTIATION)
        return
    _trim(pd1)
    if pd2.scale:
        raise InterpUnsupported("exponentiation with a non-integer exponent (computed with GMP floats)")
    if pd2.value == 1:
        return
    n = abs(pd2.value)
    if n * max(1, len(str(abs(pd1.value)))) > 200_000:
        raise InterpUnsupported("exponentiation result too large to model")
    if pd2.value < 0:
        if n > (1 << 63):
            raise InterpUnsupported("exponent outside a signed long")
        pd2.value = n
        pd1.value = pd1.value ** n
        if pd1.scale:
            pd1.scale *= n
            _trim(pd1)
        pd2.value, pd2.scale = pd1.value, pd1.scale
        pd1.value, pd1.scale = 1, 0
        dec_div(rt, pd1, pd2)
        _trim(pd1)
        return
    if n >= (1 << 64):
        raise InterpUnsupported("exponent outside an unsigned long")
    pd1.value = pd1.value ** n
    if pd1.scale:
        pd1.scale *= n
        _trim(pd1)


def dec_cmp(d1: Dec, d2: Dec) -> int:
    a, b = d1.copy(), d2.copy()
    if a.scale != b.scale:
        _align(a, b)
    return (a.value > b.value) - (a.value < b.value)


# =============================================================================================
# MOVE (move.c)
# =============================================================================================
def _store_common_region(f: F, data: bytes, size: int, scale: int, verified: bool) -> None:
    fsize = fdata_size(f)
    fstart = fdata_start(f)
    lf1 = -scale
    lf2 = -f.a.scale
    lcf = max(lf1, lf2)
    hf1 = size + lf1
    hf2 = fsize + lf2
    gcf = min(hf1, hf2)
    f.b[fstart: fstart + fsize] = b"0" * fsize
    if gcf > lcf:
        src = hf1 - gcf
        dst = fstart + hf2 - gcf
        n = gcf - lcf
        for i in range(n):
            c = data[src + i]
            if verified:
                f.b[dst + i] = c
            elif c == 0x20 or c == 0:
                pass
            else:
                f.b[dst + i] = (0x30 + (c - 0x30)) & 0xFF


def _move_alphanum_to_display(f1: F, f2: F) -> None:
    s = bytes(f1.b[f1.o: f1.o + f1.size])
    e1 = len(s)
    s2 = fdata_start(f2)
    e2 = s2 + fdata_size(f2)
    f2.b[f2.o: f2.o + f2.size] = b"0" * f2.size
    i = 0
    while i < e1 and chr(s[i]) in " \t\n\v\f\r":
        i += 1
    sign = 0
    if i != e1 and s[i] in (0x2B, 0x2D):
        sign = 1 if s[i] == 0x2B else -1
        i += 1
    count = 0
    p = i
    while p < e1 and s[p] != 0x2E:
        if 0x30 <= s[p] <= 0x39:
            count += 1
        p += 1
    size = fdata_size(f2) - f2.a.scale
    if count < size:
        s2 += size - count
    else:
        while count > size:
            count -= 1
            while i < e1 and not (0x30 <= s[i] <= 0x39):
                i += 1
            i += 1
    count = 0
    while i < e1 and s2 < e2:
        c = s[i]
        if 0x30 <= c <= 0x39:
            f2.b[s2] = c
            s2 += 1
        elif c == 0x2E:
            if count > 0:
                f2.b[f2.o: f2.o + f2.size] = b"0" * f2.size
                put_sign(f2, 0)
                return
            count += 1
        elif not (chr(c) in " \t\n\v\f\r" or c == 0x2C):
            f2.b[f2.o: f2.o + f2.size] = b"0" * f2.size
            put_sign(f2, 0)
            return
        i += 1
    put_sign(f2, sign)


def _move_display_to_display(f1: F, f2: F) -> None:
    sign = get_sign(f1)
    start = fdata_start(f1)
    data = bytes(f1.b[start: start + fdata_size(f1)])
    _store_common_region(f2, data, fdata_size(f1), f1.a.scale, False)
    put_sign(f1, sign)
    put_sign(f2, sign)


def _move_display_to_alphanum(f1: F, f2: F) -> None:
    sign = get_sign(f1)
    start = fdata_start(f1)
    size1 = fdata_size(f1)
    data1 = bytes(f1.b[start: start + size1])
    size2 = f2.size
    zero_size = -f1.a.scale if f1.a.scale < 0 else 0
    out = bytearray(f2.b[f2.o: f2.o + f2.size])
    if f2.a.just:
        pos = 0
        if zero_size:
            zero_size = min(zero_size, size2)
            size2 -= zero_size
            out[size2: size2 + zero_size] = b"0" * zero_size
        if size2:
            diff = size2 - size1
            if diff > 0:
                out[pos: pos + diff] = b" " * diff
                pos += diff
                size2 -= diff
            out[pos: pos + size2] = data1[size1 - size2:]
    else:
        diff = size2 - size1
        if diff < 0:
            out[0:size2] = data1[:size2]
        else:
            out[0:size1] = data1
            if zero_size:
                zero_size = min(zero_size, diff)
                out[size1: size1 + zero_size] = b"0" * zero_size
                diff -= zero_size
            if diff:
                out[size1 + zero_size: size1 + zero_size + diff] = b" " * diff
    f2.b[f2.o: f2.o + f2.size] = out
    put_sign(f1, sign)


def _move_alphanum_to_alphanum(f1: F, f2: F) -> None:
    data1 = bytes(f1.b[f1.o: f1.o + f1.size])
    size1, size2 = f1.size, f2.size
    if size1 >= size2:
        f2.b[f2.o: f2.o + size2] = data1[size1 - size2:] if f2.a.just else data1[:size2]
    elif f2.a.just:
        f2.b[f2.o: f2.o + size2] = b" " * (size2 - size1) + data1
    else:
        f2.b[f2.o: f2.o + size2] = data1 + b" " * (size2 - size1)


def _move_display_to_packed(f1: F, f2: F) -> None:
    sign = get_sign_adjust(f1)
    start = fdata_start(f1)
    scale1, scale2 = f1.a.scale, f2.a.scale
    digits1 = f1.a.digits if scale1 >= 0 else f1.a.digits + scale1
    digits2 = f2.a.digits if scale2 >= 0 else f2.a.digits + scale2
    # source digits as nibble values (C reads one byte past the data; it is cleaned afterwards)
    i = 1 - digits2 % 2
    p = (digits1 - scale1) - (digits2 - scale2)
    while p < 0:
        p += 1
        i += 1
    out = bytearray(f2.size)
    src = f1.b
    end = digits1

    def sd(k: int) -> int:
        return src[start + k] if k < end + 1 and start + k < len(src) else 0

    q = i // 2
    if i % 2 == 1:
        if q < f2.size:
            out[q] = sd(p) & 0x0F
        q += 1
        p += 1
        i += 1
    i //= 2
    i_end = f2.size
    if i_end - i < (end - p + 1) // 2:
        while i < i_end:
            out[q] = ((sd(p) << 4) & 0xFF) + (sd(p + 1) & 0x0F)
            q += 1
            i += 1
            p += 2
    else:
        while p < end:
            out[q] = ((sd(p) << 4) & 0xFF) + (sd(p + 1) & 0x0F)
            q += 1
            p += 2
    if p > end:
        out[q - 1] &= 0xF0
    last = f2.size - 1
    if not f2.a.signed:
        out[last] |= 0x0F
    elif sign < 0:
        out[last] = (out[last] & 0xF0) | 0x0D
    else:
        out[last] = (out[last] & 0xF0) | 0x0C
    f2.b[f2.o: f2.o + f2.size] = out


def _move_packed_to_display(f1: F, f2: F) -> None:
    b = f1.b
    d = f1.o
    d_end = f1.o + f1.size - 1
    digits = _real_digits(f1)
    buff = bytearray()
    offset = 1 - digits % 2
    if offset == 1:
        start = b[d] & 0x0F
        d += 1
        if start:
            buff.append(0x30 + start)
        else:
            digits -= 1
            while d < d_end and b[d] == 0:
                digits -= 2
                d += 1
    else:
        while d < d_end and b[d] == 0:
            digits -= 2
            d += 1
    while d < d_end:
        buff.append((0x30 + (b[d] >> 4)) & 0xFF)
        buff.append((0x30 + (b[d] & 0x0F)) & 0xFF)
        d += 1
    buff.append((0x30 + (b[d] >> 4)) & 0xFF)
    data = bytes(buff[-digits:]) if digits < len(buff) else bytes(buff)
    if digits > len(data):
        data = b"0" * (digits - len(data)) + data
    _store_common_region(f2, data, digits, f1.a.scale, True)
    put_sign(f2, -1 if (b[d] & 0x0F) == 0x0D else 1)


def _move_binary_to_binary(f1: F, f2: F) -> None:
    exp = 10 ** _real_digits(f2)
    if f1.a.signed:
        s = binary_get(f1, True)
        sign = s < 0
        if f2.a.trunc:
            s = _tdiv_r(s, exp)
        if f2.a.signed:
            binary_set(f2, s)
        else:
            binary_set(f2, -s if sign else s)
    else:
        u = binary_get(f1, False)
        if f2.a.trunc:
            u %= exp
        binary_set(f2, u)


def _move_display_to_binary(rt: Rt, f1: F, f2: F) -> None:
    start = fdata_start(f1)
    size1 = fdata_size(f1)
    size = size1 - f1.a.scale + f2.a.scale
    if f2.a.trunc:
        scale, digits = f2.a.scale, f2.a.digits
        target = digits if scale > digits else digits if scale > 0 else digits + scale
        target = min(target, size)
    else:
        target = size
    b = f1.b
    i = size - target
    while i < size1:
        if (b[start + i] & 0x0F) != 0:
            break
        target -= 1
        i += 1
    if target > 19:
        opt = ST_TRUNC if (f2.a.trunc and not f2.a.real) else 0
        cob_decimal_setget_fld(rt, f1, f2, opt)
        return
    sign = get_sign_adjust(f1)
    val = 0
    while i < size:
        if i < size1:
            val = val * 10 + (b[start + i] & 0x0F)
        else:
            val *= 10
        i += 1
    val &= (1 << 64) - 1
    if f2.a.signed:
        binary_set(f2, -val if sign < 0 else val)
    else:
        binary_set(f2, val)


def _move_binary_to_display(f1: F, f2: F) -> None:
    sign = 1
    if f1.a.signed:
        v = binary_get(f1, True)
        if v < 0:
            sign = -1
            v = -v
    else:
        v = binary_get(f1, False)
    s = str(v).encode("ascii") if v else b""
    _store_common_region(f2, s, len(s), f1.a.scale, True)
    put_sign(f2, sign)


def cob_decimal_setget_fld(rt: Rt, src: F, dst: F, opt: int) -> None:
    d = dec_set_field(src)
    dec_get_field(rt, d, dst, opt | ST_NO_SIZE_ERROR)


def _set_packed_int(f: F, val: int) -> None:
    if val > 0:
        _pack_digits(f, val, 1)
    elif val != 0:
        _pack_digits(f, -val, -1)
    else:
        _set_packed_zero(f)


def _indirect_move(rt: Rt, func: Callable[[F, F], None], src: F, dst: F, size: int, scale: int) -> None:
    tmp = temp_field(Attr(T_DISP, size, scale, signed=True), size, 0)
    func(src, tmp)
    cob_move(rt, tmp, dst)


def _move_all(rt: Rt, src: F, dst: F) -> None:
    sdata = bytes(src.b[src.o: src.o + src.size])
    if dst.a.type in (T_ALNUM, T_GROUP):
        dst.b[dst.o: dst.o + dst.size] = bytes(sdata[i % len(sdata)] for i in range(dst.size))
        return
    if dst.a.type not in NUMERIC_TYPES:
        tmp = temp_field(Attr(T_ALNUM), dst.size)
        tmp.b[:] = bytes(sdata[i % len(sdata)] for i in range(dst.size))
        cob_move(rt, tmp, dst)
        return
    if len(sdata) == 1:
        tmp = temp_field(Attr(T_DISP, MAX_DIGITS, 0), MAX_DIGITS)
        tmp.b[:] = sdata * MAX_DIGITS
        cob_move(rt, tmp, dst)
        return
    tmp = temp_field(Attr(T_DISP, MAX_DIGITS, 0), MAX_DIGITS)
    tmp.b[:] = bytes(sdata[i % len(sdata)] for i in range(MAX_DIGITS))
    cob_move(rt, tmp, dst)


def cob_move(rt: Rt, src: F, dst: F) -> None:
    if src is dst:
        return
    if dst.size == 0:
        return
    if src.size == 0:
        src = F(bytearray(b" "), 0, 1, Attr(T_ALNUM))
    st, dt = src.a.type, dst.a.type
    if st == T_ALL:
        _move_all(rt, src, dst)
        return
    if st == T_GROUP or dt == T_GROUP:
        _move_alphanum_to_alphanum(src, dst)
        return
    opt = ST_TRUNC if (dt == T_BIN and dst.a.trunc and not dst.a.real) else 0
    if st == T_DISP:
        if dt == T_DISP:
            _move_display_to_display(src, dst)
        elif dt == T_PACKED:
            _move_display_to_packed(src, dst)
        elif dt == T_BIN:
            _move_display_to_binary(rt, src, dst)
        elif dt == T_EDIT:
            _move_display_to_edited(src, dst)
        else:
            _move_display_to_alphanum(src, dst)
        return
    if st == T_PACKED:
        if dt == T_DISP:
            _move_packed_to_display(src, dst)
        elif dt == T_BIN:
            cob_decimal_setget_fld(rt, src, dst, opt)
        elif dt == T_PACKED:
            if src.a.scale >= 0 and dst.a.scale >= 0:
                _move_bcd(src, dst)
            else:
                cob_decimal_setget_fld(rt, src, dst, 0)
        else:
            _indirect_move(rt, _move_packed_to_display, src, dst, src.a.digits, src.a.scale)
        return
    if st == T_BIN:
        if dt == T_BIN:
            ss, ds = src.a.scale, dst.a.scale
            if ss == ds:
                _move_binary_to_binary(src, dst)
                return
            digits = src.a.digits if ss >= 0 else src.a.digits + ss
            if digits < 19 and ds <= 0:
                adj = ds - ss
                if adj < 0:
                    v = _tdiv_q(binary_get(src, True), 10 ** (-adj))
                    tmp = F(bytearray(v.to_bytes(8, "little", signed=True)), 0, 8,
                            Attr(T_BIN, 18, 0, signed=True, real=True))
                    _move_binary_to_binary(tmp, dst)
                    return
                if digits + adj < 19:
                    v = binary_get(src, True) * 10 ** adj
                    v = ((v + (1 << 63)) % (1 << 64)) - (1 << 63)
                    tmp = F(bytearray(v.to_bytes(8, "little", signed=True)), 0, 8,
                            Attr(T_BIN, 18, 0, signed=True, real=True))
                    _move_binary_to_binary(tmp, dst)
                    return
            cob_decimal_setget_fld(rt, src, dst, opt)
            return
        if dt == T_DISP:
            _move_binary_to_display(src, dst)
            return
        if dt == T_PACKED:
            sd = src.a.digits
            if sd < 19:
                diff = src.a.scale - dst.a.scale
                if sd - diff < 19:
                    v = binary_get(src, True)
                    v = v * 10 ** (-diff) if diff <= 0 else _tdiv_q(v, 10 ** diff)
                    if -(1 << 31) <= v <= (1 << 31) - 1:
                        _set_packed_int(dst, v)
                        return
            cob_decimal_setget_fld(rt, src, dst, 0)
            return
        if dt == T_EDIT:
            _indirect_move(rt, _move_binary_to_display, src, dst, MAX_DIGITS, src.a.scale)
            return
        _indirect_move(rt, _move_binary_to_display, src, dst, src.a.digits, src.a.scale)
        return
    if st == T_EDIT:
        if dt in (T_GROUP, T_ALNUM):
            _move_alphanum_to_alphanum(src, dst)
            return
        raise InterpUnsupported("de-editing MOVE")
    # alphanumeric source
    if dt == T_DISP:
        _move_alphanum_to_display(src, dst)
    elif dt in (T_PACKED, T_BIN, T_EDIT):
        _indirect_move(rt, _move_alphanum_to_display, src, dst, 2 * MAX_DIGITS, MAX_DIGITS)
    else:
        _move_alphanum_to_alphanum(src, dst)


# ---- packed <-> packed (cob_move_bcd) -------------------------------------------------------
def _shift_left_nibble(buf: bytearray) -> None:
    v = (int.from_bytes(buf, "big") << 4) & ((1 << (8 * len(buf))) - 1)
    buf[:] = v.to_bytes(len(buf), "big")


def _shift_right_nibble(buf: bytearray) -> None:
    v = int.from_bytes(buf, "big") >> 4
    buf[:] = v.to_bytes(len(buf), "big")


def _move_bcd(f1: F, f2: F) -> None:
    fld1 = bytes(f1.b[f1.o: f1.o + f1.size])
    s1, s2 = f1.size, f2.size
    fld1_sign = fld1[-1] & 0x0F
    fld1_scale = f1.a.scale if not fld1_sign else f1.a.scale + 1
    fld2_scale = f2.a.scale + 1
    if fld1_scale > fld2_scale:
        move_left = False
        diff = fld1_scale - fld2_scale
    else:
        move_left = True
        diff = fld2_scale - fld1_scale
    out = bytearray(s2)
    if not diff & 1:
        offset = diff >> 1
        if move_left:
            llen = s2 - offset
            if s1 <= llen:
                out[llen - s1: llen] = fld1
                if fld1_sign:
                    out[s2 - offset - 1] &= 0xF0
            else:
                out[0:llen] = fld1[s1 - llen:]
                if fld1_sign:
                    out[llen - 1] &= 0xF0
        else:
            llen = s1 - offset
            if llen <= s2:
                out[s2 - llen:] = fld1[:llen]
            else:
                out[:] = fld1[s1 - offset - s2: s1 - offset]
    else:
        buff = bytearray(48)
        offset = diff >> 1
        if move_left:
            llen = 48 - offset
            pos = llen - s1
            buff[pos: pos + s1] = fld1
            if fld1_sign:
                buff[llen - 1] &= 0xF0
            _shift_left_nibble(buff)
        else:
            llen = s1 - offset
            pos = 48 - llen
            buff[pos:] = fld1[:llen]
            if fld1_sign:
                buff[llen - 1] &= 0xF0
            _shift_right_nibble(buff)
        out[:] = buff[48 - s2:]
    last = s2 - 1
    if f2.a.signed:
        out[last] = (out[last] & 0xF0) | (fld1_sign if fld1_sign else 0x0C)
    else:
        out[last] = (out[last] & 0xF0) | 0x0F
    if not f2.a.digits & 1:
        out[0] &= 0x0F
    f2.b[f2.o: f2.o + s2] = out


# ---- numeric edited (cob_move_display_to_edited) ----------------------------------------------
def _move_display_to_edited(f1: F, f2: F) -> None:
    sign = get_sign(f1)
    neg = sign < 0
    mn = fdata_start(f1)
    mx = mn + fdata_size(f1)
    src_b = f1.b
    size2 = f2.size
    out = bytearray(f2.b[f2.o: f2.o + size2])
    end = size2
    decimal_point: int | None = None
    count = 0
    count_sign = True
    count_curr = True
    trailing_sign = False
    trailing_curr = False
    is_zero = True
    suppress_zero = True
    sign_first = 0
    p_is_left = False
    has_b = False
    pad = 0x20
    sign_symbol = 0
    curr_symbol = 0
    currency = "$"
    floating_insertion = False
    last_fixed_pos: int | None = None
    last_fixed_char = ""
    pic = f2.a.pic
    for c, rep in pic:
        if c in "9Z*":
            count += rep
            count_sign = False
            count_curr = False
        elif (count_curr and c == currency) or (count_sign and c in "+-"):
            count += rep
        elif c == "P":
            if count == 0:
                p_is_left = True
                break
            count += rep
            count_sign = False
            count_curr = False
        elif c in ("V", "."):
            break
    src = mx - f1.a.scale - count
    dst = 0

    def take() -> int:
        nonlocal src
        x = src_b[src] if mn <= src < mx else 0x30
        src += 1
        return x

    for c, rep in pic:
        n = rep
        while n > 0:
            if c == "9":
                x = take()
                if x != 0x30:
                    is_zero = False
                suppress_zero = False
                trailing_sign = True
                trailing_curr = True
                out[dst] = x
            elif c in "Z*":
                x = take()
                if x != 0x30:
                    is_zero = suppress_zero = False
                trailing_sign = True
                trailing_curr = True
                pad = 0x2A if c == "*" else 0x20
                out[dst] = pad if suppress_zero else x
            elif c in "+-":
                x = take()
                if x != 0x30:
                    is_zero = suppress_zero = False
                if trailing_sign:
                    if neg and not is_zero:
                        out[dst] = 0x2D
                    elif c == "+":
                        out[dst] = 0x2B
                    else:
                        out[dst] = 0x20
                    end -= 1
                elif dst == 0 or suppress_zero:
                    out[dst] = pad
                    sign_symbol = ord(c)
                    if not curr_symbol:
                        sign_first += 1
                else:
                    out[dst] = x
                if n > 1 or last_fixed_char == c:
                    floating_insertion = True
                elif not trailing_sign:
                    if last_fixed_pos is not None:
                        out[last_fixed_pos] = ord(last_fixed_char)
                    last_fixed_pos = dst
                    last_fixed_char = c
            elif c in ".,":
                if c == ".":
                    out[dst] = 0x2E
                    decimal_point = dst
                else:
                    out[dst] = pad if suppress_zero else ord(c)
            elif c == "V":
                dst -= 1
                decimal_point = dst
            elif c in "0/":
                out[dst] = ord(c)
            elif c == "B":
                if suppress_zero:
                    out[dst] = pad
                else:
                    out[dst] = 0x42
                    has_b = True
            elif c == "P":
                if p_is_left:
                    src += 1
                    dst -= 1
            elif c in "CD":
                end = dst
                if neg and not is_zero:
                    out[dst: dst + 2] = b"CR" if c == "C" else b"DB"
                else:
                    out[dst: dst + 2] = b"  "
                dst += 1
            elif c == currency:
                x = take()
                if x != 0x30:
                    is_zero = suppress_zero = False
                if trailing_curr:
                    out[dst] = ord(currency)
                    end -= 1
                elif dst == 0 or suppress_zero:
                    out[dst] = pad
                    curr_symbol = ord(currency)
                else:
                    out[dst] = x
                if n > 1 or last_fixed_char == c:
                    floating_insertion = True
                elif not trailing_curr:
                    if last_fixed_pos is not None:
                        out[last_fixed_pos] = ord(last_fixed_char)
                    last_fixed_pos = dst
                    last_fixed_char = c
            else:
                raise InterpUnsupported(f"numeric-edited symbol {c}")
            n -= 1
            dst += 1
    if sign_symbol:
        if neg and not is_zero:
            sign_symbol = 0x2D
        elif sign_symbol != 0x2B:
            sign_symbol = 0x20
    if suppress_zero:
        if pad == 0x20:
            out[:] = b" " * size2
        else:
            for k in range(size2):
                if out[k] != 0x2E:
                    out[k] = pad
    else:
        if decimal_point is not None:
            for k in range(decimal_point + 1, end):
                if out[k] not in b"0123456789,.+-/B":
                    out[k] = 0x30
        if sign_symbol or curr_symbol:
            if floating_insertion:
                k = end - 1
                while k > 0:
                    if out[k] == 0x20:
                        break
                    k -= 1
                if sign_symbol and curr_symbol:
                    out[k] = curr_symbol if sign_first else sign_symbol
                elif sign_symbol:
                    out[k] = sign_symbol
                else:
                    out[k] = curr_symbol
            elif last_fixed_pos is not None:
                out[last_fixed_pos] = curr_symbol if last_fixed_char == currency else sign_symbol
        if has_b:
            leading = True
            for k in range(end):
                if out[k] == 0x42:
                    out[k] = pad if leading else 0x20
                else:
                    leading = False
    f2.b[f2.o: f2.o + size2] = out
    put_sign(f1, sign)


def edited_pic_symbols(expanded: str) -> tuple[tuple[str, int], ...]:
    """cobc picture string -> (symbol, times_repeated) runs (consecutive symbols merged;
    CR / DB are one symbol 'C' / 'D' occupying two positions)."""
    out: list[list[Any]] = []
    i = 0
    s = expanded.upper()
    while i < len(s):
        ch = s[i]
        if s.startswith("CR", i) or s.startswith("DB", i):
            out.append([ch, 1])
            i += 2
            continue
        if out and out[-1][0] == ch:
            out[-1][1] += 1
        else:
            out.append([ch, 1])
        i += 1
    return tuple((str(sym), int(n)) for sym, n in out)


# =============================================================================================
# comparisons (common.c / numeric.c)
# =============================================================================================
def _cmp_bytes(a: bytes, b: bytes) -> int:
    return (a > b) - (a < b)


def _compare_char(data: bytes, ch: bytes) -> int:
    for i in range(len(data)):
        c = ch[i % len(ch)]
        if data[i] != c:
            return data[i] - c
    return 0


def cmp_alnum(f1: F, f2: F) -> int:
    d1 = bytes(f1.b[fdata_start(f1): fdata_start(f1) + fdata_size(f1)])
    d2 = bytes(f2.b[fdata_start(f2): fdata_start(f2) + fdata_size(f2)])
    m = min(len(d1), len(d2))
    for i in range(m):
        if d1[i] != d2[i]:
            return d1[i] - d2[i]
    if len(d1) > len(d2):
        return _compare_char(d1[m:], b" ")
    if len(d1) < len(d2):
        return -_compare_char(d2[m:], b" ")
    return 0


def cmp_all(f1: F, f2: F) -> int:
    data1 = bytes(f1.b[fdata_start(f1): fdata_start(f1) + fdata_size(f1)])
    data2 = bytes(f2.b[f2.o: f2.o + f2.size])
    return _compare_char(data1, data2)


def cmp_int(f1: F, n: int) -> int:
    d = dec_set_field(f1)
    sign = (d.value > 0) - (d.value < 0)
    if sign == 0:
        return -n
    if sign == 1 and n <= 0:
        return 1
    if sign == -1 and n >= 0:
        return -1
    d2 = Dec(n, 0)
    if d.scale < 0:
        shift_decimal(d, -d.scale)
    elif d.scale > 0:
        shift_decimal(d2, d.scale)
    return (d.value > d2.value) - (d.value < d2.value)


def get_llint(f: F) -> int:
    """cob_get_llint (removes the decimal part)."""
    t = f.a.type
    if t == T_DISP:
        start = fdata_start(f)
        size = fdata_size(f)
        sign = get_sign_adjust(f)
        b = f.b
        i = 0
        while i < size and (b[start + i] & 0x0F) == 0:
            i += 1
        val = 0
        if f.a.scale < 0:
            while i < size:
                val = val * 10 + (b[start + i] & 0x0F)
                i += 1
            val *= 10 ** (-f.a.scale)
        else:
            size -= f.a.scale
            while i < size:
                val = val * 10 + (b[start + i] & 0x0F)
                i += 1
        return -val if sign < 0 else val
    if t == T_BIN:
        v = binary_get(f, True)
        s = f.a.scale
        if s == 0:
            return v
        if s > 0:
            return _tdiv_q(v, 10 ** s)
        return v * int(10 ** (-s))
    if t == T_PACKED:
        b = f.b
        d = f.o
        d_end = f.o + f.size - 1
        if 1 - f.a.digits % 2 == 1:
            val = b[d] & 0x0F
            d += 1
        else:
            val = 0
        while d < d_end:
            val = val * 100 + PACK_TO_BIN[b[d]]
            d += 1
        val = val * 10 + (b[d] >> 4)
        if (b[d] & 0x0F) == 0x0D:
            val = -val
        s = f.a.scale
        return val * 10 ** (-s) if s < 0 else _tdiv_q(val, 10 ** s)
    raise InterpUnsupported("integer value of a non-numeric field")


def numeric_cmp(f1: F, f2: F) -> int:
    if f1.a.type == T_PACKED and f2.a.type == T_PACKED and f1.a.scale >= 0 and f2.a.scale >= 0:
        return dec_cmp(dec_set_field(f1), dec_set_field(f2))
    if f1.a.scale == f2.a.scale and f1.a.digits < 19 and f2.a.digits < 19:
        if f1.a.scale == 0:
            a, b = get_llint(f1), get_llint(f2)
        else:
            c1 = F(f1.b, f1.o, f1.size, _with_scale0(f1.a))
            c2 = F(f2.b, f2.o, f2.size, _with_scale0(f2.a))
            a, b = get_llint(c1), get_llint(c2)
        return (a > b) - (a < b)
    return dec_cmp(dec_set_field(f1), dec_set_field(f2))


def _with_scale0(a: Attr) -> Attr:
    return Attr(a.type, a.digits, 0, a.signed, a.sep, a.lead, a.just, a.trunc, a.real, a.swap, a.pic)


def cob_cmp(f1: F, f2: F) -> int:
    n1 = f1.a.type in NUMERIC_TYPES
    n2 = f2.a.type in NUMERIC_TYPES
    if n1 and n2:
        return numeric_cmp(f1, f2)
    if f2.a.type == T_ALL:
        if f2.size == 1 and f2.b[f2.o] == 0x30 and n1:
            return cmp_int(f1, 0)
        return cmp_all(f1, f2)
    if f1.a.type == T_ALL:
        if f1.size == 1 and f1.b[f1.o] == 0x30 and n2:
            return -cmp_int(f2, 0)
        return -cmp_all(f2, f1)
    if n1 or n2:
        if n1 and f1.a.type != T_DISP:
            a = Attr(T_DISP, f1.a.digits, f1.a.scale, False, f1.a.sep, f1.a.lead)
            tmp = temp_field(a, f1.a.digits)
            cob_move(Rt(), f1, tmp)
            f1 = tmp
        if n2 and f2.a.type != T_DISP:
            a = Attr(T_DISP, f2.a.digits, f2.a.scale, False, f2.a.sep, f2.a.lead)
            tmp = temp_field(a, f2.a.digits)
            cob_move(Rt(), f2, tmp)
            f2 = tmp
        if f1.a.type == T_DISP and f1.a.signed:
            sign = get_sign(f1)
            r = cmp_alnum(f1, f2)
            put_sign(f1, sign)
            return r
        if f2.a.type == T_DISP and f2.a.signed:
            sign = get_sign(f2)
            r = cmp_alnum(f1, f2)
            put_sign(f2, sign)
            return r
        return cmp_alnum(f1, f2)
    return cmp_alnum(f1, f2)


# ---- class tests ----------------------------------------------------------------------------
def is_numeric(f: F) -> bool:
    t = f.a.type
    b = f.b
    if t == T_BIN:
        return True
    if t == T_PACKED:
        end = f.o + f.size - 1
        sign = b[end] & 0x0F
        if f.a.signed:
            if sign not in (0x0C, 0x0D):
                return False
        elif sign != 0x0F:
            return False
        if (b[end] & 0xF0) > 0x90:
            return False
        return all((x >> 4) <= 9 and (x & 0x0F) <= 9 for x in b[f.o: end])
    if t == T_DISP:
        p = f.o
        e = f.o + f.size
        if f.a.signed:
            if f.a.lead:
                c = b[p]
                p += 1
            else:
                e -= 1
                c = b[e]
            if f.a.sep:
                if c not in (0x2B, 0x2D):
                    return False
            elif not 0x30 <= c <= 0x39 and not 0x70 <= c <= 0x79:
                return False
        return all(0x30 <= x <= 0x39 for x in b[p:e])
    return all(0x30 <= x <= 0x39 for x in b[f.o: f.o + f.size])


def _isalpha(c: int) -> bool:
    return 0x41 <= c <= 0x5A or 0x61 <= c <= 0x7A


def is_alpha(f: F) -> bool:
    return all(c == 0x20 or _isalpha(c) for c in f.b[f.o: f.o + f.size])


def is_upper(f: F) -> bool:
    return all(c == 0x20 or 0x41 <= c <= 0x5A for c in f.b[f.o: f.o + f.size])


def is_lower(f: F) -> bool:
    return all(c == 0x20 or 0x61 <= c <= 0x7A for c in f.b[f.o: f.o + f.size])


# =============================================================================================
# DISPLAY (termio.c, pretty-display: yes)
# =============================================================================================
_BIN_DIGITS = [1, 3, 5, 8, 10, 13, 15, 17, 20]


def display_bytes(rt: Rt, f: F) -> bytes:
    if f.size == 0:
        return b""
    t = f.a.type
    if t in NUMERIC_TYPES:
        if t == T_BIN and f.a.real:
            n = _BIN_DIGITS[f.size]
            v = binary_get(f)
            return (("-" if v < 0 else "+") + str(abs(v)).rjust(n - 0, "0")).encode() if f.a.signed \
                else str(v).rjust(n, "0").encode()
        return _pretty_display(rt, f)
    return bytes(f.b[f.o: f.o + f.size])


def _pretty_display(rt: Rt, f: F) -> bytes:
    digits = f.a.digits
    scale = f.a.scale
    has_sign = 1 if f.a.signed else 0
    if scale == 0 or scale < 0:
        size = digits + has_sign
    else:
        if digits < scale:
            digits = scale
        size = digits + has_sign + 1
    pic: list[tuple[str, int]] = []
    if has_sign and not (f.a.sep and not f.a.lead):
        pic.append(("+", 1))
    if scale > 0:
        if digits - scale > 0:
            pic.append(("9", digits - scale))
        pic.append((".", 1))
        pic.append(("9", scale))
    else:
        pic.append(("9", digits))
    if has_sign and f.a.sep and not f.a.lead:
        pic.append(("+", 1))
    tmp = temp_field(Attr(T_EDIT, digits, scale, pic=tuple(pic)), size, 0)
    cob_move(rt, f, tmp)
    return bytes(tmp.b)


# =============================================================================================
# ACCEPT (termio.c cob_accept)
# =============================================================================================
COB_MEDIUM_MAX = 8191


class Stdin:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def getchar(self) -> int:
        if self.pos >= len(self.data):
            return -1
        c = self.data[self.pos]
        self.pos += 1
        return c


def cob_accept(rt: Rt, stdin: Stdin, f: F) -> None:
    buf = bytearray()
    while len(buf) < COB_MEDIUM_MAX:
        c = stdin.getchar()
        if c == -1:
            rt.set_exception(EC_IMP_ACCEPT)
            if not buf:
                buf = bytearray(b" ")
            break
        if c == 0x03:
            raise InterpUnsupported("ETX (^C) in stdin raises SIGINT")
        if c == 0x0A:
            break
        buf.append(c)
    size = len(buf)
    if f.a.type == T_DISP and size > f.size:
        size = f.size
    tmp = F(buf, 0, size, Attr(T_ALNUM))
    cob_move(rt, tmp, f)


# =============================================================================================
# attributes of data items (cobc codegen output_attr)
# =============================================================================================
def item_attr(item: DataItem) -> Attr:
    if item.children:
        return Attr(T_GROUP)
    pic = item.pic
    if pic is None:
        raise InterpUnsupported(f"{item.name}: item without PICTURE")
    cat = pic.category
    if cat in ("alphanumeric", "alphabetic"):
        return Attr(T_ALNUM, just=item.justified)
    if cat == "numeric-edited":
        return Attr(T_EDIT, pic.digits, pic.scale, signed=pic.signed, pic=edited_pic_symbols(pic.expanded))
    if cat != "numeric":
        raise InterpUnsupported(f"{item.name}: {cat} item")
    digits = pic.digits + (-pic.scale if pic.scale < 0 else 0)
    if item.usage == "DISPLAY":
        lead = item.sign == "LEADING"
        return Attr(T_DISP, digits, pic.scale, pic.signed, sep=pic.signed and item.sign_separate,
                    lead=pic.signed and lead)
    if item.usage == "COMP":
        return Attr(T_BIN, digits, pic.scale, pic.signed, trunc=True, swap=True)
    if item.usage == "COMP-5":
        return Attr(T_BIN, digits, pic.scale, pic.signed, real=True)
    if item.usage == "COMP-3":
        return Attr(T_PACKED, digits, pic.scale, pic.signed)
    raise InterpUnsupported(f"{item.name}: USAGE {item.usage}")


def literal_field(lit: I.Lit) -> F:
    digits = lit.digits or "0"
    if lit.signed or lit.negative:
        data = (b"-" if lit.negative else b"+") + digits.encode()
        a = Attr(T_DISP, len(digits), lit.scale, signed=True, sep=True, lead=True)
    else:
        data = digits.encode()
        a = Attr(T_DISP, len(digits), lit.scale)
    return F(bytearray(data), 0, len(data), a)


_FIG_BYTES = {"ZERO": b"0", "SPACE": b" ", "HIGH-VALUE": b"\xff", "LOW-VALUE": b"\x00", "QUOTE": b'"'}


def fig_field(fig: I.Fig) -> F:
    data = fig.value if fig.name == "ALL" else _FIG_BYTES[fig.name]
    if not data:
        raise InterpUnsupported("empty ALL literal")
    return F(bytearray(data), 0, len(data), Attr(T_ALL))


# =============================================================================================
# results
# =============================================================================================
@dataclass
class ProgramResult:
    stdout: bytes
    stderr: bytes
    return_code: int
    files: dict[str, bytes]
    runtime_error: str | None = None  # GnuCOBOL would abort with `libcob: error`
    statements: int = 0


@dataclass
class ParagraphResult:
    state: dict[str, bytes]  # root record name -> bytes after the paragraph
    fields: dict[str, str]  # elementary item (qualified name) -> decoded value after the paragraph
    size_errors: list[int]  # lines of arithmetic statements whose SIZE ERROR condition was raised
    flow: str  # return | stop
    return_code: int
    stdout: bytes = b""
    statements: int = 0


# =============================================================================================
# files
# =============================================================================================
@dataclass
class FileState:
    name: str
    path: str
    line_seq: bool
    status: F | None
    record: F
    record_min: int
    record_max: int
    open_mode: str = ""  # "" closed | INPUT | OUTPUT | EXTEND
    pos: int = 0
    end_of_file: bool = False
    rec_size: int = 0


def _is_bad_char(c: int) -> bool:
    return c < 0x20 and c not in (0x08, 0x1B, 0x0C, 0x0F, 0x09)


# =============================================================================================
# the machine
# =============================================================================================
STATEMENT_LIMIT = 5_000_000


class Machine:
    def __init__(self, ir: I.IrProgram, stdin: bytes = b"", files: dict[str, bytes] | None = None,
                 env: dict[str, str] | None = None, statement_limit: int = STATEMENT_LIMIT) -> None:
        reason = ir.interpretability()
        if reason is not None:
            raise InterpUnsupported(reason)
        self.ir = ir
        self.prog = ir.program
        self.rt = Rt()
        self.stdin = Stdin(stdin)
        self.out = bytearray()
        self.err = bytearray()
        self.fs: dict[str, bytearray] = {k: bytearray(v) for k, v in (files or {}).items()}
        self.env = dict(env or {})
        self.statement_limit = statement_limit
        self.count = 0
        self.size_error_lines: list[int] = []
        self.buffers: dict[int, bytearray] = {}
        self._attr_cache: dict[int, Attr] = {}
        self._lit_cache: dict[int, F] = {}
        self.dconst: dict[tuple[str, int, int], Dec] = {}
        self._setup_storage()
        self.files: dict[str, FileState] = {}
        self._setup_files()
        self.return_code_field = F(bytearray(4), 0, 4, item_attr(ir.return_code))
        self.buffers[id(ir.return_code)] = self.return_code_field.b
        self.paras = ir.paragraphs
        self.index = {p.name: i for i, p in enumerate(self.paras) if not _implicit(p)}
        self.frames: list[tuple[str, str]] = []

    # ---- storage ------------------------------------------------------------------------------
    def _setup_storage(self) -> None:
        prog = self.prog
        for fd in prog.fds:
            size = max((r.size for r in fd.records), default=0)
            buf = bytearray(size)  # FD record areas start as LOW-VALUES (probed, S7)
            for r in fd.records:
                self.buffers[id(r)] = buf
        by_name: dict[str, DataItem] = {}
        for r in prog.working_storage:
            if r.redefines and r.redefines.upper() in by_name:
                buf = self.buffers[id(by_name[r.redefines.upper()])]
                if r.size > len(buf):
                    raise InterpUnsupported(f"01 {r.name} REDEFINES a smaller record")
                self.buffers[id(r)] = buf
            elif r.redefines:
                raise InterpUnsupported(f"01 {r.name} REDEFINES unknown {r.redefines}")
            else:
                self.buffers[id(r)] = bytearray(r.size)
            if r.name != "FILLER":
                by_name[r.name.upper()] = r
        for r in prog.working_storage:
            if not r.redefines:
                self._init_storage(r, self.buffers[id(r)], 0)

    def root_of(self, item: DataItem) -> DataItem:
        cur = item
        while cur.parent is not None:
            cur = cur.parent
        return cur

    def attr(self, item: DataItem) -> Attr:
        a = self._attr_cache.get(id(item))
        if a is None:
            a = item_attr(item)
            self._attr_cache[id(item)] = a
        return a

    def _init_storage(self, item: DataItem, buf: bytearray, base: int) -> None:
        """WORKING-STORAGE initialisation (cobc STMT_INIT_STORAGE with VALUEs, FILLER included)."""
        occurs = item.occurs or 1
        unit = item.unit_size
        off = base + item.offset
        if item.value is not None:
            self._init_value(item, F(buf, off, unit, self.attr(item)))
        elif item.children:
            for c in item.children:
                if c.redefines or c.level in (66, 88):
                    continue
                self._init_storage(c, buf, base)
        else:
            self._init_default(F(buf, off, unit, self.attr(item)))
        for k in range(1, occurs):
            buf[off + k * unit: off + (k + 1) * unit] = buf[off: off + unit]

    def _init_default(self, f: F) -> None:
        t = f.a.type
        if t == T_DISP and not f.a.sep:
            f.b[f.o: f.o + f.size] = b"0" * f.size
        elif t == T_BIN:
            f.b[f.o: f.o + f.size] = bytes(f.size)
        elif t in (T_DISP, T_PACKED, T_EDIT):
            cob_move(self.rt, fig_field(I.Fig("ZERO")), f)
        else:
            f.b[f.o: f.o + f.size] = b" " * f.size

    def _init_value(self, item: DataItem, f: F) -> None:
        v = item.value
        assert v is not None
        if v.kind == "fig":
            ch = {"SPACE": b" ", "LOW-VALUE": b"\x00", "HIGH-VALUE": b"\xff", "QUOTE": b'"'}.get(v.text)
            if ch is not None:
                f.b[f.o: f.o + f.size] = ch * f.size
                return
            if v.text == "ZERO":
                if f.a.type == T_DISP and not f.a.sep:
                    f.b[f.o: f.o + f.size] = b"0" * f.size
                else:
                    cob_move(self.rt, fig_field(I.Fig("ZERO")), f)
                return
            raise InterpUnsupported(f"VALUE {v.text}")
        if v.kind == "num":
            cob_move(self.rt, literal_field(numeric_value_literal(v.text)), f)
            return
        if v.kind == "all":
            data = v.text.encode("latin-1")
            f.b[f.o: f.o + f.size] = bytes(data[i % len(data)] for i in range(f.size))
            return
        if v.kind == "str":
            data = v.text.encode("latin-1")
            if not data:
                cob_move(self.rt, fig_field(I.Fig("SPACE")), f)
            elif len(data) >= f.size:
                f.b[f.o: f.o + f.size] = data[: f.size]
            else:
                f.b[f.o: f.o + f.size] = data + b" " * (f.size - len(data))
            return
        raise InterpUnsupported(f"VALUE {v}")

    # ---- field resolution -----------------------------------------------------------------------
    def field(self, ref: I.Ref) -> F:
        item = ref.item
        if item is self.ir.return_code:
            return self.return_code_field
        root = self.root_of(item)
        buf = self.buffers.get(id(root))
        if buf is None:
            raise InterpUnsupported(f"no storage for {item.name}")
        off = item.offset
        if ref.subs:
            dims: list[DataItem] = []
            cur: DataItem | None = item
            while cur is not None:
                if cur.occurs:
                    dims.append(cur)
                cur = cur.parent
            dims.reverse()
            if len(dims) != len(ref.subs):
                raise InterpUnsupported(f"subscript count for {item.name}")
            for d, e in zip(dims, ref.subs, strict=True):
                k = self.int_value(e)
                off += (k - 1) * d.unit_size
        size = item.unit_size
        a = self.attr(item)
        if ref.refmod is not None:
            start = self.int_value(ref.refmod[0])
            length = self.int_value(ref.refmod[1]) if ref.refmod[1] is not None else size - start + 1
            off += start - 1
            size = length
            a = Attr(T_ALNUM)
            if size <= 0:
                raise InterpUnsupported(f"reference modification of {item.name} with length {size}")
        if off < 0 or off + size > len(buf):
            raise InterpUnsupported(f"subscript/reference modification of {item.name} outside its record")
        return F(buf, off, size, a)

    def operand_field(self, e: I.Expr) -> F:
        if isinstance(e, I.Ref):
            return self.field(e)
        if isinstance(e, I.Lit):
            f = self._lit_cache.get(id(e))
            if f is None:
                f = literal_field(e)
                self._lit_cache[id(e)] = f
            return F(bytearray(f.b), 0, f.size, f.a)
        if isinstance(e, I.StrLit):
            if not e.value:
                return F(bytearray(b" "), 0, 1, Attr(T_ALNUM))
            return F(bytearray(e.value), 0, len(e.value), Attr(T_ALNUM))
        if isinstance(e, I.Fig):
            return fig_field(e)
        raise InterpUnsupported(f"operand {e}")

    def int_value(self, e: I.Expr) -> int:
        """cobc cast to int (codegen.c output_integer)."""
        if isinstance(e, I.Lit):
            if e.scale > 0:
                return _c_int(_tdiv_q(e.value, 10 ** e.scale))
            return _c_int(e.value)
        if isinstance(e, I.Ref):
            return _c_int(self._cast_int_field(e.item, self.field(e)))
        if isinstance(e, I.Bin):
            if e.op == "^":
                raise InterpUnsupported("exponentiation in an integer expression")
            a = self.int_value(e.left)
            b = self.int_value(e.right)
            if e.op == "+":
                return _c_int(a + b)
            if e.op == "-":
                return _c_int(a - b)
            if e.op == "*":
                return _c_int(a * b)
            if b == 0:
                raise InterpUnsupported("division by zero in an integer expression")
            return _c_int(_tdiv_q(a, b))
        if isinstance(e, I.Fig) and e.name == "ZERO":
            return 0
        raise InterpUnsupported(f"integer value of {e}")

    def _cast_int_field(self, item: DataItem, f: F) -> int:
        a = f.a
        if a.type == T_DISP and a.scale >= 0 and 0 < f.size - a.scale <= 9 and item.sign is None:
            n = f.size - a.scale
            val = 0
            for i in range(n):
                val = val * 10 + (f.b[f.o + i] & 0x0F)
            if a.signed and f.b[f.o + n - 1] & 0x40:
                return -val
            return val
        if a.type == T_BIN and f.size in (1, 2, 4, 8):
            return binary_get(f)
        if a.type in (T_DISP, T_PACKED, T_BIN):
            return get_llint(f)
        tmp = F(bytearray(4), 0, 4, Attr(T_BIN, 9, 0, signed=True, real=True))
        cob_move(self.rt, f, tmp)
        return binary_get(tmp)

    def llint_value(self, e: I.Expr) -> int:
        """cobc cast to long long (cb_build_cast_llint)."""
        if isinstance(e, I.Lit):
            return e.value if e.scale == 0 else _tdiv_q(e.value, 10 ** e.scale)
        if isinstance(e, I.Fig) and e.name == "ZERO":
            return 0
        if isinstance(e, I.Ref):
            f = self.field(e)
            if f.a.type == T_BIN and f.size in (1, 2, 4, 8):
                return binary_get(f)
            return get_llint(f)
        raise InterpUnsupported(f"long value of {e}")

    # ---- decimal expressions (typeck.c decimal_expand) -------------------------------------
    def dec_expand(self, e: I.Expr) -> Dec:
        if isinstance(e, I.Lit):
            if len(e.digits) < 19 and e.scale == 0:
                return Dec(e.value, 0)
            return dec_set_field(self.operand_field(e))
        if isinstance(e, I.Fig):
            if e.name == "ZERO":
                return Dec(0, 0)
            raise InterpUnsupported(f"figurative {e.name} in arithmetic")
        if isinstance(e, I.Ref):
            f = self.field(e)
            if f.a.type == T_BIN and f.a.scale == 0 and f.size in (1, 2, 4, 8):
                return Dec(binary_get(f), 0)
            if f.a.type not in NUMERIC_TYPES:
                raise InterpUnsupported(f"non-numeric {e} in arithmetic")
            return dec_set_field(f)
        if isinstance(e, I.Bin):
            d = self.dec_expand(e.left)
            t = self._dconst(e.right) if isinstance(e.right, I.Lit) else self.dec_expand(e.right)
            self.dec_op(e.op, d, t)
            return d
        raise InterpUnsupported(f"expression {e}")

    def _dconst(self, lit: I.Lit) -> Dec:
        """The program-wide decimal constant cobc creates for a literal right operand
        (codegen.c cb_lookup_literal: one per distinct digits/scale/sign, initialised once)."""
        key = (lit.digits, lit.scale, -1 if lit.negative else (1 if lit.signed else 0))
        d = self.dconst.get(key)
        if d is None:
            d = dec_set_field(literal_field(lit))
            self.dconst[key] = d
        return d

    def dec_op(self, op: str, d: Dec, t: Dec) -> None:
        if op == "+":
            dec_add(d, t)
        elif op == "-":
            dec_sub(d, t)
        elif op == "*":
            dec_mul(d, t)
        elif op == "/":
            dec_div(self.rt, d, t)
        elif op == "^":
            dec_pow(self.rt, d, t)
        else:
            raise InterpUnsupported(f"operator {op}")

    # ---- store options (typeck.c build_store_option) ---------------------------------------
    def store_opt(self, f: F, rounded: bool, size_error: bool, handler: bool) -> int:
        opt = ST_ROUND if rounded else 0
        if f.a.type == T_BIN and f.a.real:
            if size_error:
                opt |= ST_KEEP
        elif handler:
            opt |= ST_KEEP
        elif f.a.type == T_BIN and f.a.trunc:
            opt |= ST_TRUNC
        return opt

    # ---- statements -------------------------------------------------------------------------
    def tick(self) -> None:
        self.count += 1
        if self.count > self.statement_limit:
            raise InterpUnsupported("statement limit exceeded (the program may loop forever)")

    def exec_block(self, stmts: list[I.Stmt]) -> None:
        for s in stmts:
            self.exec(s)

    def exec(self, s: I.Stmt) -> None:
        self.tick()
        handler = _DISPATCH.get(type(s))
        if handler is None:
            raise InterpUnsupported(f"statement {s.verb} at line {s.loc.line}")
        handler(self, s)

    def x_move(self, s: I.Move) -> None:
        for d in s.dsts:
            dst = self.field(d)
            if self._move_literal(s.src, dst):
                continue
            src = self.operand_field(s.src)
            _check_overlap(src, dst)
            cob_move(self.rt, src, dst)

    def _move_literal(self, src: I.Expr, f: F) -> bool:
        """typeck.c cb_build_move_literal: MOVEs of literals that cobc resolves at compile time.

        * numeric DISPLAY receiver with the literal's scale and no SEPARATE sign: the literal's
          characters are copied right-aligned (for an alphanumeric literal: raw, not de-edited) and
          the sign is overpunched for a negative numeric literal (also for -0);
        * COMP-3 receiver: `cob_set_packed_int (cb_get_int (literal))`, which does not truncate to
          the PICTURE digits (excess digits reach the pad nibble); for an alphanumeric literal
          cb_get_int adds up `c - '0'` over every character.
        Everything else goes through cob_move at run time. Returns False when not applicable."""
        if isinstance(src, I.Lit):
            data, lscale, lsign = src.digits.encode(), src.scale, (-1 if src.negative else (1 if src.signed else 0))
        elif isinstance(src, I.StrLit):
            data, lscale, lsign = src.value, 0, 0
        else:
            return False
        if not data:
            return False
        a = f.a
        if a.type == T_DISP and a.scale == lscale and not a.sep:
            diff = f.size - len(data)
            buf = bytearray(data[len(data) - f.size:]) if diff <= 0 else bytearray(b"0" * diff + data)
            if a.signed and lsign == -1:
                p = 0 if a.lead else f.size - 1
                buf[p] = (buf[p] + 0x40) & 0xFF
            f.b[f.o: f.o + f.size] = buf
            return True
        if a.type != T_PACKED or not _lit_fits_int(data, lscale, lsign):
            return False
        allzero = all(c == 0x30 for c in data)
        if (lsign == 0 or not a.signed) and allzero:
            _set_packed_zero(f)
            return True
        if a.scale < 0:
            return False
        n = a.scale - lscale
        if len(data) + n > 9:
            return False
        i = 0
        while i < len(data) and data[i] == 0x30:
            i += 1
        val = 0
        for c in data[i:]:
            val = _c_int(val * 10 + c - 0x30)
        if val and lsign < 0:
            val = -val
        while n > 0:
            val = _c_int(val * 10)
            n -= 1
        while n < 0:
            val = _tdiv_q(val, 10)
            n += 1
        if val == 0 and (lsign == 0 or not a.signed):
            _set_packed_zero(f)
            return True
        if val < 0 and not a.signed:
            val = -val
        _set_packed_int(f, val)
        return True

    # arithmetic --------------------------------------------------------------------------------
    def _run_size(self, s: Any, body: Callable[[], None]) -> None:
        handler = s.handler
        if handler:
            self.rt.exception = 0
        before = self.rt.exception
        body()
        raised = (self.rt.exception & 0xFF00) == 0x1000 and (handler or self.rt.exception != before)
        if raised:
            self.size_error_lines.append(s.loc.line)
        if handler:
            if raised:
                if s.size_error is not None:
                    self.exec_block(s.size_error)
            elif s.not_size_error is not None:
                self.exec_block(s.not_size_error)

    def x_arithop(self, s: I.ArithOp) -> None:
        def body() -> None:
            for t in s.targets:
                f = self.field(t.ref)
                opt = self.store_opt(f, t.rounded, s.size_error is not None, s.handler)
                n = s.src
                if f.a.type == T_EDIT:
                    raise InterpUnsupported("ADD/SUBTRACT/MULTIPLY/DIVIDE into a numeric-edited item")
                if s.op in "+-":
                    if opt == 0 and self._fits_int(n):
                        self._optim_add(f, n, s.op)
                    else:
                        self._cob_addsub(f, self.operand_field(n), opt, s.op)
                else:
                    d1 = dec_set_field(f)
                    d2 = Dec(0, 0) if isinstance(n, I.Fig) else dec_set_field(self.operand_field(n))
                    if s.op == "*":
                        dec_mul(d1, d2)
                    else:
                        dec_div(self.rt, d1, d2)
                    dec_get_field(self.rt, d1, f, opt)
        self._run_size(s, body)

    def _fits_int(self, n: I.Expr) -> bool:
        """tree.c cb_fits_int."""
        if isinstance(n, I.Lit):
            if n.scale > 0:
                return False
            d = n.digits.lstrip("0")
            if len(d) < 10:
                return True
            if len(d) > 10:
                return False
            return d <= ("2147483648" if n.negative else "2147483647")
        if isinstance(n, I.Fig):
            return n.name == "ZERO"
        if isinstance(n, I.Ref):
            item = n.item
            if item.children or n.refmod is not None:
                return False
            a = self.attr(item)
            if a.type == T_BIN:
                return a.scale <= 0 and item.unit_size <= 4
            if a.type == T_DISP:
                return item.unit_size < 10 and a.scale <= 0
            if a.type == T_PACKED:
                return a.scale <= 0 and a.digits < 10
        return False

    def _optim_add(self, f: F, n: I.Expr, op: str) -> None:
        """typeck.c cb_build_optim_add / cb_build_optim_sub (integer operand, no store option)."""
        val = self.int_value(n)
        if op == "-":
            val = _c_int(-val)
        a = f.a
        if a.scale != 0:
            self._cob_add_int(f, val)
            return
        if a.type == T_BIN:
            # native C addition (cob_add_s16, cob_addswp_s16, ...): wraps at the binary width
            binary_set(f, binary_get(f) + val)
            return
        if a.type == T_PACKED and a.digits < 19:
            self._add_packed_int(f, val)
            return
        self._cob_add_int(f, val)

    def _cob_add_int(self, f: F, n: int) -> None:
        if n == 0:
            return
        scale = f.a.scale
        val = n
        if scale < 0:
            if -scale < 10:
                while scale:
                    scale += 1
                    val = _tdiv_q(val, 10)
            else:
                val = 0
            scale = 0
            if not val:
                return
        d1 = dec_set_field(f)
        d1.value += val * (10 ** scale) if scale > 0 else val
        dec_get_field(self.rt, d1, f, 0)

    def _add_packed_int(self, f: F, val: int) -> None:
        """codeoptim.c cob_add_packed_int / cob_add_packed_int64."""
        if val == 0:
            return
        b = f.b
        p = f.o + f.size - 1
        if (b[p] & 0x0F) == 0x0D:
            if val > 0:
                self._cob_add_int(f, val)
                return
            n = -val
        else:
            if val < 0:
                self._cob_add_int(f, val)
                return
            n = val
        inc = (b[p] >> 4) + (n % 10)
        n //= 10
        carry = inc // 10
        b[p] = ((inc % 10) << 4) | (b[p] & 0x0F)
        p -= 1
        for _ in range(f.size - 1):
            if not carry and not n:
                break
            inc = ((b[p] >> 4) * 10) + (b[p] & 0x0F) + carry + (n % 100)
            carry = inc // 100
            n //= 100
            inc %= 100
            b[p] = ((inc // 10) << 4) | (inc % 10)
            p -= 1

    def _cob_addsub(self, f1: F, f2: F, opt: int, op: str) -> None:
        """numeric.c cob_add / cob_sub (cob_addsub_optimized for COMP-3 targets)."""
        if f1.a.type == T_PACKED and (f2.a.type in (T_PACKED, T_BIN)
                                       or (f2.a.type == T_DISP and f2.a.digits <= MAX_DIGITS)):
            if f2.a.type == T_PACKED:
                _add_bcd(self.rt, f1, f2, f1, opt, op)
                return
            tmp = temp_field(Attr(T_PACKED, f2.a.digits, f2.a.scale, signed=True), f2.a.digits // 2 + 1)
            if f2.a.type == T_DISP:
                _move_display_to_packed(f2, tmp)
            else:
                cob_move(self.rt, f2, tmp)
            _add_bcd(self.rt, f1, tmp, f1, opt, op)
            return
        d1 = dec_set_field(f1)
        d2 = Dec(0, 0) if f2.a.type == T_ALL else dec_set_field(f2)
        if op == "+":
            dec_add(d1, d2)
        else:
            dec_sub(d1, d2)
        dec_get_field(self.rt, d1, f1, opt)

    def x_arithassign(self, s: I.ArithAssign) -> None:
        def body() -> None:
            d = self.dec_expand(s.expr)
            for t in s.targets:
                f = self.field(t.ref)
                opt = self.store_opt(f, t.rounded, s.size_error is not None, s.handler)
                if s.op is None:
                    dec_get_field(self.rt, d, f, opt)
                else:
                    if f.a.type == T_EDIT:
                        raise InterpUnsupported("numeric-edited item as an arithmetic operand")
                    td = self.dec_expand(t.ref)
                    self.dec_op(s.op, td, d)
                    dec_get_field(self.rt, td, f, opt)
        self._run_size(s, body)

    def x_divrem(self, s: I.DivRem) -> None:
        def body() -> None:
            q = self.field(s.quotient.ref)
            optq = self.store_opt(q, s.quotient.rounded, s.size_error is not None, s.handler)
            d1 = Dec(0, 0) if isinstance(s.dividend, I.Fig) else dec_set_field(self.operand_field(s.dividend))
            d2 = Dec(0, 0) if isinstance(s.divisor, I.Fig) else dec_set_field(self.operand_field(s.divisor))
            rem = d1.copy()
            dec_div(self.rt, d1, d2)
            if d1.scale == NAN_SCALE:
                rem.scale = NAN_SCALE
            else:
                d3 = d1.copy()
                dec_get_field(self.rt, d1, q, optq)
                n = q.a.scale - d3.scale
                if n != 0:
                    if d3.value == 0:
                        d3.scale = 0
                    else:
                        shift_decimal(d3, n)
                dec_mul(d3, d2)
                dec_sub(rem, d3)
            r = self.field(s.remainder)
            optr = self.store_opt(r, False, s.size_error is not None, s.handler)
            if rem.scale == NAN_SCALE:
                return  # cob_div_remainder: early return after the zero divide
            dec_get_field(self.rt, rem, r, optr)
        self._run_size(s, body)

    # control flow ------------------------------------------------------------------------------
    def x_if(self, s: I.If) -> None:
        if self.cond(s.cond):
            self.exec_block(s.then)
        elif s.els is not None:
            self.exec_block(s.els)

    def x_evaluate(self, s: I.Evaluate) -> None:
        for w in s.whens:
            if self.cond(w.cond):
                self.exec_block(w.body)
                return
        if s.other is not None:
            self.exec_block(s.other)

    def x_perform(self, s: I.Perform) -> None:
        if s.mode == "once":
            self._perform_once(s)
        elif s.mode == "times":
            assert s.times is not None
            n = self.llint_value(s.times)
            while n > 0:
                self.tick()
                if self._perform_once(s):
                    break
                n -= 1
        elif s.mode == "until":
            assert s.until is not None
            while True:
                self.tick()
                if not s.test_after and self.cond(s.until):
                    break
                if self._perform_once(s):
                    break
                if s.test_after and self.cond(s.until):
                    break
        else:
            v0 = s.varying[0]
            self._move_value(v0.start, v0.var)
            self._perform_until(s, 0)

    def _perform_until(self, s: I.Perform, k: int) -> bool:
        """codegen.c output_perform_until; returns True when EXIT PERFORM left the loop."""
        if k >= len(s.varying):
            return self._perform_once(s)
        v = s.varying[k]
        nxt = s.varying[k + 1] if k + 1 < len(s.varying) else None
        while True:
            self.tick()
            if nxt is not None:
                self._move_value(nxt.start, nxt.var)
            if s.test_after and self._perform_until(s, k + 1):
                return True
            if self.cond(v.until):
                break
            if not s.test_after and self._perform_until(s, k + 1):
                return True
            self._step(v)
        return False

    def _step(self, v: I.Varying) -> None:
        """cb_build_add (var, by, cb_high): the optimised add, without binary truncation."""
        f = self.field(v.var)
        if self._fits_int(v.by):
            self._optim_add(f, v.by, "+")
        else:
            self._cob_addsub(f, self.operand_field(v.by), 0, "+")

    def _move_value(self, src: I.Expr, dst: I.Ref) -> None:
        cob_move(self.rt, self.operand_field(src), self.field(dst))

    def _perform_once(self, s: I.Perform) -> bool:
        """Run the body once. Returns True when EXIT PERFORM (not CYCLE) ended the loop."""
        if s.body is not None:
            try:
                self.exec_block(s.body)
            except _ExitPerform as ex:
                return not ex.cycle
            return False
        assert s.proc is not None
        self.perform_range(s.proc[0], s.proc[1])
        return False

    def perform_range(self, first: str, last: str) -> None:
        start = self._start_index(first)
        end = self._label(last)
        self.frames.append(end)
        try:
            self.run_from(start, end)
        finally:
            self.frames.pop()

    def _label(self, name: str) -> tuple[str, str]:
        if name in self.ir.sections:
            return ("section", name)
        if name in self.index:
            return ("para", name)
        raise InterpUnsupported(f"unknown procedure {name}")

    def _start_index(self, name: str) -> int:
        if name in self.ir.sections:
            for i, p in enumerate(self.paras):
                if p.section == name:
                    return i
            raise InterpUnsupported(f"empty section {name}")
        if name in self.index:
            return self.index[name]
        raise InterpUnsupported(f"unknown procedure {name}")

    def run_from(self, i: int, end: tuple[str, str] | None) -> None:
        """Execute paragraphs from index i with GnuCOBOL's perform-exit checks (perform-osvs: no).

        Returns when an end-of-paragraph/section check matches `end` (the innermost PERFORM frame);
        falling off the end of the procedure ends the program (raises _StopRun)."""
        n = len(self.paras)
        while i < n:
            p = self.paras[i]
            section_exit = False
            try:
                self.exec_block(p.body)
            except _GoTo as g:
                i = self._start_index(g.target)
                continue
            except _ExitParagraph as ex:
                if ex.section and p.section is not None:
                    while i + 1 < n and self.paras[i + 1].section == p.section:
                        i += 1
                    p = self.paras[i]
                    section_exit = True
            if not section_exit and not _implicit(p) and end == ("para", p.name):
                return
            last_in_section = p.section is not None and (i + 1 >= n or self.paras[i + 1].section != p.section)
            if last_in_section and end == ("section", p.section):
                return
            i += 1
        raise _StopRun()

    def x_goto(self, s: I.GoTo) -> None:
        raise _GoTo(s.target)

    def x_continue(self, s: I.Continue) -> None:
        return

    def x_exit(self, s: I.ExitStmt) -> None:
        if s.kind == "plain":
            return
        if s.kind == "paragraph":
            raise _ExitParagraph(False)
        if s.kind == "section":
            raise _ExitParagraph(True)
        if s.kind in ("perform", "perform-cycle"):
            raise _ExitPerform(s.kind == "perform-cycle")
        raise InterpUnsupported(f"EXIT {s.kind.upper()}")

    def x_stop(self, s: I.StopRun) -> None:
        raise _StopRun()

    def x_goback(self, s: I.GoBack) -> None:
        raise _StopRun()

    def x_setcond(self, s: I.SetCond) -> None:
        for cn in s.conds:
            lo, _hi = cn.cond.values_88[0]
            cob_move(self.rt, self.operand_field(_value_expr(lo)), self.field(cn.parent))

    def x_initialize(self, s: I.Initialize) -> None:
        for r in s.targets:
            f = self.field(r)
            self._initialize(r.item, f.b, f.o - r.item.offset, top=True)

    # INITIALIZE (codegen.c output_initialize; default phrases: no FILLER, no VALUE)
    def _init_type(self, item: DataItem, top: bool) -> str:
        if item.sign_separate and not item.children and item.pic is not None and item.pic.signed:
            return "one"
        if item.redefines and not top:
            return "none"
        if item.is_filler and not item.children:
            return "none"
        if item.children:
            kids = [c for c in item.children if c.level not in (66, 88)]
            t0 = self._init_type(kids[0], False)
            if t0 == "one":
                return "compound"
            for c in kids[1:]:
                if self._init_type(c, False) != t0:
                    return "compound"
            return t0
        if self.attr(item).type in (T_EDIT, T_PACKED):
            return "one"
        return "default"

    def _uniform_char(self, item: DataItem) -> int:
        if item.children:
            kids = [c for c in item.children if c.level not in (66, 88)]
            c0 = self._uniform_char(kids[0])
            for c in kids[1:]:
                if not c.redefines and self._uniform_char(c) != c0:
                    return -1
            return c0
        t = self.attr(item).type
        if t == T_BIN:
            return 0
        if t == T_DISP:
            return 0x30
        if t == T_ALNUM:
            return 0x20
        return -1

    def _init_one(self, f: F) -> None:
        if f.a.type in NUMERIC_TYPES or f.a.type == T_EDIT:
            cob_move(self.rt, fig_field(I.Fig("ZERO")), f)
        else:
            cob_move(self.rt, fig_field(I.Fig("SPACE")), f)

    def _initialize(self, item: DataItem, buf: bytearray, base: int, top: bool) -> None:
        t = self._init_type(item, top)
        size = item.unit_size
        f = F(buf, base + item.offset, size, self.attr(item))
        if t == "none":
            return
        if t == "one":
            self._init_one(f)
            return
        if t == "default":
            c = self._uniform_char(item)
            if c != -1:
                buf[f.o: f.o + size] = bytes([c]) * size
                return
        self._init_compound(item, buf, base)

    def _init_compound(self, group: DataItem, buf: bytearray, base: int) -> None:
        kids = [c for c in group.children if c.level not in (66, 88)]
        i = 0
        while i < len(kids):
            f = kids[i]
            t = self._init_type(f, False)
            if t == "none":
                i += 1
                continue
            if t == "default":
                c = self._uniform_char(f)
                if c != -1:
                    j = i
                    while j + 1 < len(kids):
                        sis = kids[j + 1]
                        if not sis.redefines and (self._init_type(sis, False) != "default"
                                                  or self._uniform_char(sis) != c):
                            break
                        j += 1
                    if j + 1 < len(kids):
                        size = kids[j + 1].offset - f.offset
                    else:
                        size = group.offset + group.unit_size - f.offset
                    o = base + f.offset
                    buf[o: o + size] = bytes([c]) * size
                    i = j + 1
                    continue
            o = base + f.offset
            if t == "one":
                self._init_one(F(buf, o, f.unit_size, self.attr(f)))
            else:
                self._init_compound(f, buf, base)
            for k in range(1, f.occurs or 1):
                buf[o + k * f.unit_size: o + (k + 1) * f.unit_size] = buf[o: o + f.unit_size]
            i += 1

    # conditions ----------------------------------------------------------------------------------
    def cond(self, c: I.Cond) -> bool:
        if isinstance(c, I.Rel):
            return self._rel(c)
        if isinstance(c, I.And):
            return self.cond(c.left) and self.cond(c.right)
        if isinstance(c, I.Or):
            return self.cond(c.left) or self.cond(c.right)
        if isinstance(c, I.Not):
            return not self.cond(c.cond)
        if isinstance(c, I.BoolConst):
            return c.value
        if isinstance(c, I.CondName):
            return self.cond(c.test if c.test is not None else I.cond88_test(c.cond, c.parent))
        if isinstance(c, I.ClassTest):
            if not isinstance(c.operand, I.Ref):
                raise InterpUnsupported("class test on a literal")
            f = self.field(c.operand)
            if c.kind == "NUMERIC":
                return is_numeric(f)
            if c.kind == "ALPHABETIC":
                return is_alpha(f)
            if c.kind == "ALPHABETIC-UPPER":
                return is_upper(f)
            return is_lower(f)
        raise InterpUnsupported(f"condition {c}")

    def _rel(self, c: I.Rel) -> bool:
        r = self._compare(c.left, c.right)
        op = c.op
        if op == "=":
            return r == 0
        if op == "~":
            return r != 0
        if op == "<":
            return r < 0
        if op == ">":
            return r > 0
        if op == "[":
            return r <= 0
        return r >= 0

    def _is_num_operand(self, e: I.Expr) -> bool:
        if isinstance(e, (I.Lit, I.Bin)):
            return True
        if isinstance(e, I.Fig):
            return e.name == "ZERO"
        if isinstance(e, I.Ref):
            return e.refmod is None and not e.item.children and self.attr(e.item).type in NUMERIC_TYPES
        return False

    def _compare(self, left: I.Expr, right: I.Expr) -> int:
        """typeck.c cb_build_cond / cb_build_cond_default: <0, 0, >0 for left vs right."""
        if isinstance(left, I.Bin) or isinstance(right, I.Bin):
            return dec_cmp(self.dec_expand(left), self.dec_expand(right))
        swapped = False
        if _is_const(left) and not _is_const(right):
            left, right = right, left
            swapped = True
        r = self._compare_ordered(left, right)
        return -r if swapped else r

    def _compare_ordered(self, left: I.Expr, right: I.Expr) -> int:
        lnum = self._is_num_operand(left)
        rnum = self._is_num_operand(right)
        if isinstance(left, I.Ref) and isinstance(right, I.Ref) and lnum and rnum:
            li, ri = left.item, right.item
            if li.usage == ri.usage == "DISPLAY":
                la, ra = self.attr(li), self.attr(ri)
                if not la.signed and not ra.signed and la.digits == ra.digits and la.scale == ra.scale:
                    return _cmp_bytes(self.field(left).data(), self.field(right).data())
        if lnum and rnum:
            r = self._optim_cond(left, right)
            if r is not None:
                return r
        return cob_cmp(self.operand_field(left), self.operand_field(right))

    def _fits_llint(self, e: I.Expr) -> bool:
        if isinstance(e, I.Lit):
            if e.scale > 0:
                return False
            d = e.digits.lstrip("0")
            if len(d) < 19:
                return True
            if len(d) > 19:
                return False
            return d <= ("9223372036854775808" if e.negative else "9223372036854775807")
        if isinstance(e, I.Fig):
            return e.name == "ZERO"
        if isinstance(e, I.Ref):
            item = e.item
            a = self.attr(item)
            if a.type == T_BIN:
                return a.scale <= 0 and item.unit_size <= 8
            if a.type == T_DISP:
                return item.unit_size < 19 and a.scale <= 0
            if a.type == T_PACKED:
                return a.scale <= 0 and a.digits < 19
        return False

    def _optim_cond(self, left: I.Expr, right: I.Expr) -> int | None:
        """typeck.c cb_build_optim_cond (both operands numeric)."""
        if not isinstance(left, I.Ref):
            if not self._fits_llint(right):
                return None
            return cmp_llint(self.operand_field(left), self.llint_value(right))
        fa = self.attr(left.item)
        if fa.type == T_PACKED and isinstance(right, I.Ref):
            ra = self.attr(right.item)
            if ra.type == T_PACKED and (fa.scale or fa.digits >= 19 or ra.scale or ra.digits >= 19) \
                    and fa.scale >= 0 and ra.scale >= 0:
                return dec_cmp(dec_set_field(self.field(left)), dec_set_field(self.field(right)))
        if not self._fits_llint(right):
            return None
        val = self.llint_value(right)
        f = self.field(left)
        if fa.scale:
            return cmp_llint(f, val)
        if fa.type == T_PACKED:
            n = get_llint(f)
            return (n > val) - (n < val)
        if fa.type == T_DISP and left.item.sign != "LEADING" and not left.item.sign_separate:
            if self._fits_llint(left):
                return cmp_numdisp(f, val)
            return cmp_llint(f, val)
        if fa.type == T_BIN:
            n = binary_get(f)
            return (n > val) - (n < val)
        return cmp_llint(f, val)

    # I/O ------------------------------------------------------------------------------------------
    def x_display(self, s: I.Display) -> None:
        out = self.out if s.upon == "SYSOUT" else self.err
        for e in s.operands:
            out += display_bytes(self.rt, self.operand_field(e))
        if s.advancing:
            out += b"\n"

    def x_accept(self, s: I.Accept) -> None:
        cob_accept(self.rt, self.stdin, self.field(s.target))

    def _setup_files(self) -> None:
        for sel in self.prog.selects:
            fd = self.prog.fd(sel.name)
            if fd is None or not fd.records:
                continue
            name = sel.assign or sel.name
            for k in (f"DD_{name}", f"dd_{name}", name):
                if k in self.env:
                    raise InterpUnsupported(f"file name {name} is remapped by environment variable {k}")
            status: F | None = None
            if sel.file_status:
                item = self.prog.resolve(sel.file_status)
                if item is None:
                    raise InterpUnsupported(f"FILE STATUS item {sel.file_status}")
                root = self.root_of(item)
                if id(root) not in self.buffers or item.fd is not None:
                    raise InterpUnsupported("FILE STATUS item outside WORKING-STORAGE")
                status = F(self.buffers[id(root)], item.offset, item.unit_size, self.attr(item))
            sizes = [r.size for r in fd.records]
            line_seq = sel.organization == "LINE SEQUENTIAL"
            if not line_seq and min(sizes) != max(sizes):
                raise InterpUnsupported(f"SEQUENTIAL file {sel.name} with records of different sizes")
            rec = F(self.buffers[id(fd.records[0])], 0, max(sizes), Attr(T_GROUP))
            self.files[sel.name] = FileState(sel.name, name, line_seq, status, rec, min(sizes), max(sizes),
                                             rec_size=max(sizes))
        paths = [f.path for f in self.files.values()]
        if len(set(paths)) != len(paths):
            raise InterpUnsupported("two SELECTs assigned to the same file")

    def _save_status(self, fs: FileState, status: int) -> None:
        if fs.status is not None:
            st = f"{status:02d}".encode()
            n = min(2, fs.status.size)
            fs.status.b[fs.status.o: fs.status.o + n] = st[:n]
        self.rt.exception = 0 if status < 10 else 0x0500 + status

    def _file_error(self, fs: FileState, status: int) -> None:
        """The standard error handler: fatal unless the file has a FILE STATUS clause."""
        if fs.status is None:
            raise CobolRuntimeError(f"libcob: error: file {fs.name} status {status:02d}")

    def x_open(self, s: I.Open) -> None:
        for mode, name in s.entries:
            fs = self.files[name]
            st = self._open(fs, mode)
            self._save_status(fs, st)
            if st >= 10:
                self._file_error(fs, st)

    def _open(self, fs: FileState, mode: str) -> int:
        if fs.open_mode:
            return 41
        if fs.path not in self.fs and mode != "OUTPUT":
            return 35
        if mode == "OUTPUT":
            self.fs[fs.path] = bytearray()
        fs.end_of_file = False
        fs.pos = 0
        fs.open_mode = mode
        return 0

    def x_close(self, s: I.Close) -> None:
        for name in s.files:
            fs = self.files[name]
            if not fs.open_mode:
                st = 42
            else:
                fs.open_mode = ""
                st = 0
            self._save_status(fs, st)
            if st >= 10:
                self._file_error(fs, st)

    def x_read(self, s: I.Read) -> None:
        fs = self.files[s.file]
        st = self._read(fs)
        self._save_status(fs, st)
        if st >= 10:
            if st == 10 and s.at_end is not None:
                self.exec_block(s.at_end)
            else:
                self._file_error(fs, st)
            return
        if s.into is not None:
            cob_move(self.rt, F(fs.record.b, 0, fs.record_max, Attr(T_GROUP)), self.field(s.into))
        if s.not_at_end is not None:
            self.exec_block(s.not_at_end)

    def _read(self, fs: FileState) -> int:
        if fs.open_mode != "INPUT":
            return 47
        if fs.end_of_file:
            return 46
        data = self.fs[fs.path]
        rec = fs.record
        n_data = len(data)
        if fs.line_seq:
            pos = fs.pos
            if pos >= n_data:
                fs.end_of_file = True
                return 10
            st = 0
            buf = bytearray()
            while pos < n_data:
                c = data[pos]
                pos += 1
                if c == 0x0D and pos < n_data and data[pos] == 0x0A:
                    pos += 1
                    break
                if c == 0x0A:
                    break
                if _is_bad_char(c):
                    st = 9
                if len(buf) < fs.record_max:
                    buf.append(c)
                    if len(buf) == fs.record_max:
                        # COB_LS_SPLIT: peek at the next character(s); getc at EOF does not move,
                        # but the fseek (fp, -k, SEEK_CUR) still happens (re-reads the last byte)
                        k = 1
                        nx = data[pos] if pos < n_data else -1
                        if nx != -1:
                            pos += 1
                        if nx == 0x0D:
                            nx = data[pos] if pos < n_data else -1
                            if nx != -1:
                                pos += 1
                            k += 1
                        if nx != 0x0A:
                            pos -= k
                            st = 6
                        break
            fs.pos = pos
            rec.b[0: fs.record_max] = bytes(buf) + b" " * (fs.record_max - len(buf))
            return st
        size = fs.rec_size
        chunk = data[fs.pos: fs.pos + size]
        if not chunk:
            fs.end_of_file = True
            return 10
        if len(chunk) < size:
            raise InterpUnsupported(f"short last record in fixed-length file {fs.name}")
        rec.b[0:size] = chunk
        fs.pos += size
        return 0

    def x_write(self, s: I.Write) -> None:
        fs = self.files[s.file]
        if s.src is not None:
            cob_move(self.rt, self.operand_field(s.src), self.field(s.record))
        st = self._write(fs, self.field(s.record))
        self._save_status(fs, st)
        if st >= 10:
            self._file_error(fs, st)

    def _write(self, fs: FileState, recf: F) -> int:
        if fs.open_mode not in ("OUTPUT", "EXTEND"):
            return 48
        size = recf.size
        if size < fs.record_min or size > fs.record_max:
            return 44
        data = bytes(recf.b[recf.o: recf.o + size])
        out = self.fs[fs.path]
        if fs.line_seq:
            body = data.rstrip(b" ")
            if any(_is_bad_char(c) for c in body):
                return 71
            out += body + b"\n"
            return 0
        out += data
        fs.rec_size = size
        return 0

    # ---- state ---------------------------------------------------------------------------------
    def snapshot(self) -> dict[str, bytes]:
        out: dict[str, bytes] = {}
        for r in self.prog.records():
            buf = self.buffers.get(id(r))
            if buf is not None:
                out[_record_key(r)] = bytes(buf[: r.size])
        out["RETURN-CODE"] = bytes(self.return_code_field.b)
        return out

    def return_code(self) -> int:
        return binary_get(self.return_code_field)


def _lit_fits_int(data: bytes, scale: int, sign: int) -> bool:
    """tree.c cb_fits_int for a literal (data as cobc stores it)."""
    if scale > 0:
        return False
    i = 0
    while i < len(data) and data[i] == 0x30:
        i += 1
    size = len(data) - i - scale
    if size < 10:
        return True
    if size > 10:
        return False
    return data[i:i + 10] <= (b"2147483648" if sign < 0 else b"2147483647")


def _record_key(r: DataItem) -> str:
    return r.name if r.name != "FILLER" else f"FILLER@{r.line}"


def _check_overlap(src: F, dst: F) -> None:
    if src.b is dst.b and src.o < dst.o + dst.size and dst.o < src.o + src.size \
            and (src.o, src.size) != (dst.o, dst.size) \
            and not (src.a.type in (T_ALNUM, T_GROUP) and dst.a.type in (T_ALNUM, T_GROUP)):
        raise InterpUnsupported("MOVE between overlapping numeric storage")


def _implicit(p: I.IrParagraph) -> bool:
    return p.name == "(MAIN)" or (p.section is not None and p.name == p.section)


def _is_const(e: I.Expr) -> bool:
    return isinstance(e, (I.Lit, I.StrLit, I.Fig))


def _c_int(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v >= (1 << 31) else v


def numeric_value_literal(text: str) -> I.Lit:
    t = text.strip()
    neg = t.startswith("-")
    signed = t[:1] in "+-"
    body = t[1:] if signed else t
    ip, _, fp = body.partition(".")
    return I.Lit(t, ip + fp, len(fp), neg, signed)


def _value_expr(v: Any) -> I.Expr:
    if v.kind == "num":
        return numeric_value_literal(v.text)
    if v.kind == "str":
        return I.StrLit(v.text.encode("latin-1"))
    if v.kind == "fig":
        return I.Fig(v.text)
    raise InterpUnsupported(f"88-level VALUE {v}")


def _cond88(c: I.CondName) -> I.Cond:
    """typeck.c build_cond_88: (x >= lo AND x <= hi) / x = v, OR'ed in VALUE order."""
    x = c.parent
    out: I.Cond | None = None
    for lo, hi in c.cond.values_88:
        if hi is not None:
            c2: I.Cond = I.And(I.Rel("]", x, _value_expr(lo)), I.Rel("[", x, _value_expr(hi)))
        else:
            c2 = I.Rel("=", x, _value_expr(lo))
        out = c2 if out is None else I.Or(out, c2)
    assert out is not None
    return out


def cmp_llint(f: F, n: int) -> int:
    """numeric.c cob_cmp_llint."""
    d = dec_set_field(f)
    sign = (d.value > 0) - (d.value < 0)
    if sign == 0:
        if n > (1 << 31) - 1:
            return -(1 << 31)
        if n < -(1 << 31):
            return (1 << 31) - 1
        return -n
    if sign == 1 and n <= 0:
        return 1
    if sign == -1 and n >= 0:
        return -1
    d2 = Dec(n, 0)
    if d.scale < 0:
        shift_decimal(d, -d.scale)
    elif d.scale > 0:
        shift_decimal(d2, d.scale)
    return (d.value > d2.value) - (d.value < d2.value)


def cmp_numdisp(f: F, n: int) -> int:
    """numeric.c cob_cmp_numdisp."""
    b = f.b
    size = f.size
    p = f.o
    if not f.a.signed:
        if n < 0:
            return 1
        val = 0
        for i in range(size):
            val = val * 10 + (b[p + i] & 0x0F)
        return (val > n) - (val < n)
    if not size:
        return 0
    val = 0
    for i in range(size - 1):
        val = val * 10 + (b[p + i] & 0x0F)
    val *= 10
    last = b[p + size - 1]
    if 0x30 <= last <= 0x39:
        val += last & 0x0F
    elif 0x70 <= last <= 0x79:
        val += last - 0x70
        val = -val
    return (val > n) - (val < n)


_DISPATCH: dict[type, Callable[[Machine, Any], None]] = {
    I.Move: Machine.x_move,
    I.ArithOp: Machine.x_arithop,
    I.ArithAssign: Machine.x_arithassign,
    I.DivRem: Machine.x_divrem,
    I.If: Machine.x_if,
    I.Evaluate: Machine.x_evaluate,
    I.Perform: Machine.x_perform,
    I.GoTo: Machine.x_goto,
    I.Continue: Machine.x_continue,
    I.ExitStmt: Machine.x_exit,
    I.StopRun: Machine.x_stop,
    I.GoBack: Machine.x_goback,
    I.SetCond: Machine.x_setcond,
    I.Initialize: Machine.x_initialize,
    I.Display: Machine.x_display,
    I.Accept: Machine.x_accept,
    I.Open: Machine.x_open,
    I.Close: Machine.x_close,
    I.Read: Machine.x_read,
    I.Write: Machine.x_write,
}


# =============================================================================================
# BCD addition (numeric.c cob_add_bcd), used by ADD/SUBTRACT with a COMP-3 target
# =============================================================================================
_H2B = [255] * 256
for _hi in range(10):
    for _lo in range(10):
        _H2B[(_hi << 4) | _lo] = _hi * 10 + _lo
_B2H = [0xFF] * 256
for _v in range(100):
    _B2H[_v] = ((_v // 10) << 4) | (_v % 10)


def _add_bcd(rt: Rt, fdst: F, fsrc1: F, fsrc2: F, opt: int, op: str) -> int:
    """cob_add_bcd (fdst, fsrc1, fsrc2, opt, stmt) as called from cob_add / cob_sub:
    cob_add_bcd (f1, f2, f1, ...) - fsrc1 is the operand, fsrc2 (= fdst) the target."""
    if opt & ~ST_MASK:
        raise InterpUnsupported("ROUNDED MODE in BCD addition")
    src1 = bytes(fsrc1.b[fsrc1.o: fsrc1.o + fsrc1.size])
    src2 = bytes(fsrc2.b[fsrc2.o: fsrc2.o + fsrc2.size])
    s1, s2, ds = fsrc1.size, fsrc2.size, fdst.size
    fld1_sign = src1[-1] & 0x0F
    fld2_sign = src2[-1] & 0x0F
    src1_scale, src2_scale, dst_scale = fsrc1.a.scale, fsrc2.a.scale, fdst.a.scale
    used_original_scale = max(src1_scale, src2_scale)
    fld1_scale = src1_scale if fld1_sign == 0 else src1_scale + 1
    fld2_scale = src2_scale if fld2_sign == 0 else src2_scale + 1
    dest_scale = dst_scale + 1
    used_scale = max(fld1_scale, fld2_scale)
    # rounding inside cob_add_bcd needs `opt & ~COB_STORE_MASK` (a ROUNDED MODE); the default
    # ROUNDED has no mode bits, so cob_add_bcd truncates (see S7)
    del used_original_scale
    b1 = bytearray(48)
    b2 = bytearray(48)
    if fld1_scale == fld2_scale:
        p1 = 48 - s1
        b1[p1:] = src1
        if fld1_sign:
            b1[47] &= 0xF0
        p2 = 48 - s2
        b2[p2:] = src2
        if fld2_sign:
            b2[47] &= 0xF0
    elif fld1_scale < fld2_scale:
        diff = fld2_scale - fld1_scale
        offset = diff >> 1
        p2 = 48 - s2
        b2[p2:] = src2
        if fld2_sign:
            b2[47] &= 0xF0
        p1 = 48 - s1 - offset
        b1[p1: p1 + s1] = src1
        if fld1_sign:
            b1[47 - offset] &= 0xF0
        if diff % 2 == 1:
            _shift_left_nibble(b1)
            p1 -= 1
    else:
        diff = fld1_scale - fld2_scale
        offset = diff >> 1
        p1 = 48 - s1
        b1[p1:] = src1
        if fld1_sign:
            b1[47] &= 0xF0
        p2 = 48 - s2 - offset
        b2[p2: p2 + s2] = src2
        if fld2_sign:
            b2[47 - offset] &= 0xF0
        if diff % 2 == 1:
            _shift_left_nibble(b2)
            p2 -= 1
    loop_limit = 48 - p2 + 1 if p1 > p2 else 48 - p1 + 1
    loop_limit = min(loop_limit, 48)
    if op == "-":
        fld1_sign = 0x0C if fld1_sign == 0x0D else 0x0D
    final_positive = True
    carry = 0
    if fld1_sign == fld2_sign or (fld1_sign != 0x0D and fld2_sign != 0x0D):
        if fld1_sign == 0x0D:
            final_positive = False
        for cntr in range(loop_limit):
            i1 = 47 - cntr
            h1, h2 = _H2B[b1[i1]], _H2B[b2[i1]]
            if h1 == 255 or h2 == 255:
                raise InterpUnsupported("invalid packed-decimal data in ADD/SUBTRACT")
            byte = carry + h1 + h2
            if byte >= 200:
                byte -= 200
                carry = 2
            elif byte >= 100:
                byte -= 100
                carry = 1
            else:
                carry = 0
            b2[i1] = _B2H[byte]
    else:
        lo = 48 - loop_limit
        c = _cmp_bytes(bytes(b1[lo:]), bytes(b2[lo:]))
        if c < 0:
            if fld1_sign != 0x0D:
                final_positive = False
            neg, pos = bytes(b1), bytes(b2)
        elif c > 0:
            if fld1_sign == 0x0D:
                final_positive = False
            neg, pos = bytes(b2), bytes(b1)
        else:
            _set_packed_zero(fdst)
            return 0
        for cntr in range(loop_limit):
            i1 = 47 - cntr
            h1, h2 = _H2B[pos[i1]], _H2B[neg[i1]]
            if h1 == 255 or h2 == 255:
                raise InterpUnsupported("invalid packed-decimal data in ADD/SUBTRACT")
            byte = carry + h1 - h2
            if byte < 0:
                byte += 100
                carry = -1
            elif byte >= 100:
                byte -= 100
                carry = 1
            else:
                carry = 0
            b2[i1] = _B2H[byte]
    start = 48 - loop_limit
    if used_scale > dest_scale:
        diff = used_scale - dest_scale
        offset = diff // 2
        seg = bytes(b2[start: start + loop_limit - offset])
        b2[start + offset: start + loop_limit] = seg
        b2[start: start + offset] = bytes(offset)
        start += offset
        if diff & 1:
            _shift_right_nibble(b2)
    elif used_scale < dest_scale:
        diff = dest_scale - used_scale
        offset = diff // 2
        seg = bytes(b2[start: start + loop_limit])
        b2[start - offset: start - offset + loop_limit] = seg
        b2[48 - offset: 48] = bytes(offset)
        if diff % 2 == 1:
            _shift_left_nibble(b2)
    # check_overflow_and_set_sign
    b2[47] &= 0xF0
    buff_size = 48 - start
    cmp_size = buff_size - ds
    if cmp_size >= 0:
        lead = 0
        while lead < buff_size and b2[start + lead] == 0:
            lead += 1
        has_pad = fdst.a.digits % 2 == 0
        cmp_size -= lead
        if cmp_size > 0 or (cmp_size == 0 and has_pad and b2[start + lead] > 0x0F):
            if not opt & ST_NO_SIZE_ERROR:
                rt.set_exception(EC_SIZE_OVERFLOW)
                if opt & ST_KEEP:
                    return rt.exception
            if has_pad:
                b2[48 - ds] &= 0x0F
    if not fdst.a.signed:
        b2[47] |= 0x0F
    elif final_positive:
        b2[47] |= 0x0C
    else:
        b2[47] |= 0x0D
    fdst.b[fdst.o: fdst.o + ds] = b2[48 - ds:]
    return 0


# =============================================================================================
# entry points
# =============================================================================================
def run_program(ir: I.IrProgram, stdin: bytes = b"", files: dict[str, bytes] | None = None,
                args: list[str] | None = None, env: dict[str, str] | None = None,
                statement_limit: int = STATEMENT_LIMIT) -> ProgramResult:
    """Run a whole program like the GnuCOBOL binary (cwd holds `files`; result has every file)."""
    if args:
        raise InterpUnsupported("command-line arguments are not modelled")
    m = Machine(ir, stdin, files, env, statement_limit)
    error: str | None = None
    try:
        if m.paras:
            m.run_from(0, None)
    except _StopRun:
        pass
    except CobolRuntimeError as exc:
        error = str(exc)
    except (_GoTo, _ExitPerform, _ExitParagraph) as exc:
        raise InterpUnsupported(f"control transfer {type(exc).__name__} outside its context") from exc
    rc = m.return_code() if error is None else 1
    return ProgramResult(bytes(m.out), bytes(m.err), rc & 0xFF, {k: bytes(v) for k, v in m.fs.items()},
                         error, m.count)


def run_paragraph(ir: I.IrProgram, name: str, values: dict[str, str] | None = None,
                  state: dict[str, bytes] | None = None,
                  statement_limit: int = STATEMENT_LIMIT) -> ParagraphResult:
    """Run one paragraph (and everything it PERFORMs) on a given state.

    The initial state is the program's initial WORKING-STORAGE, overridden by `state` (record
    name -> bytes, as returned in `ParagraphResult.state`) and then by `values` (data name ->
    value text, stored with the exact encoding of that item's PICTURE/USAGE)."""
    from verifier.inputs.encode import decode_elementary, encode_elementary

    m = Machine(ir, b"", {}, {}, statement_limit)
    p = ir.paragraph(name)
    if p is None or _implicit(p):
        raise InterpUnsupported(f"no paragraph {name}")
    if state:
        for r in m.prog.records():
            key = _record_key(r)
            if key in state and id(r) in m.buffers:
                data = state[key]
                m.buffers[id(r)][: len(data)] = data
        if "RETURN-CODE" in state:
            m.return_code_field.b[:] = state["RETURN-CODE"]
    for nm, text in (values or {}).items():
        item = ir.return_code if nm.upper() == I.RETURN_CODE_NAME else m.prog.resolve(nm)
        if item is None or item.children or item.occurs_dims():
            raise InterpUnsupported(f"cannot set {nm} by name")
        f = m.field(I.Ref(item))
        f.b[f.o: f.o + f.size] = encode_elementary(item, text) if item is not ir.return_code \
            else int(text).to_bytes(4, "big", signed=True)
    flow = "return"
    m.frames.append(("para", p.name))
    try:
        m.run_from(m.index[p.name], ("para", p.name))
    except _StopRun:
        flow = "stop"
    fields: dict[str, str] = {}
    for item in m.prog.all_items():
        if item.children or item.level in (66, 88) or item.is_filler or item.occurs_dims():
            continue
        if id(m.root_of(item)) not in m.buffers:
            continue
        fields[".".join(reversed(item.path()))] = decode_elementary(item, m.field(I.Ref(item)).data())
    fields["RETURN-CODE"] = str(m.return_code())
    return ParagraphResult(m.snapshot(), fields, list(m.size_error_lines), flow, m.return_code(),
                           bytes(m.out), m.count)
