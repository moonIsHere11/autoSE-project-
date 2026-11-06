"""Record encodings (bytes <-> field state) and DISPLAY formatting, byte-identical to GnuCOBOL 3.2.

* DISPLAY (zoned): one ASCII digit per byte; a negative embedded sign is an ASCII overpunch of the
  last (or, with SIGN LEADING, first) digit: 0x70 + d (`p`..`y`); SEPARATE puts `+`/`-` in its
  own byte. Unsigned items carry no sign.
* COMP-3: two digits per byte, last nibble is the sign (C positive, D negative, F unsigned).
* COMP / BINARY: big-endian two's complement (`binary-byteorder: big-endian`).
* COMP-5: native little-endian two's complement.
"""

from __future__ import annotations

from cobolrt.pic import COMP5_DISPLAY_DIGITS, NumPic, Usage


def encode(u: int, pic: NumPic, negzero: bool = False, fnib: bool = False, pad: int = 0) -> bytes:
    """Storage bytes of a numeric field holding unscaled value `u` (negzero: negative zero).

    COMP-3 only: `fnib` writes the sign nibble F although the item is signed (left by a MOVE
    from an unsigned COMP-3 item); `pad` is a garbage digit in the unused high nibble of an
    even-digit item (left by GnuCOBOL's in-place integer ADD on overflow). Neither affects the value.
    """
    neg = u < 0 or (negzero and u == 0)
    mag = abs(u)
    if pic.usage == Usage.DISPLAY:
        digits = bytearray(str(mag % 10**pic.digits).rjust(pic.digits, "0").encode("ascii"))
        if not pic.signed:
            return bytes(digits)
        if pic.sign_separate:
            ch = b"-" if neg else b"+"
            return ch + bytes(digits) if pic.sign_leading else bytes(digits) + ch
        if neg:
            i = 0 if pic.sign_leading else len(digits) - 1
            digits[i] += 0x40
        return bytes(digits)
    if pic.usage == Usage.COMP3:
        n = pic.byte_length
        s = str(mag % 10**pic.digits + (pad * 10**pic.digits if pic.digits % 2 == 0 else 0)).rjust(2 * n - 1, "0")
        nib = 0x0F if not pic.signed or fnib else (0x0D if neg else 0x0C)
        out = bytearray(n)
        for i in range(n):
            hi = int(s[2 * i])
            lo = int(s[2 * i + 1]) if i < n - 1 else nib
            out[i] = (hi << 4) | lo
        return bytes(out)
    n = pic.byte_length
    raw = (u % (1 << (8 * n))).to_bytes(n, "big")
    return raw if pic.usage == Usage.COMP else raw[::-1]


def decode(data: bytes, pic: NumPic) -> tuple[int, bool]:
    """Field state `(unscaled, negzero)` from storage bytes (inverse of `encode`)."""
    if len(data) != pic.byte_length:
        raise ValueError(f"expected {pic.byte_length} bytes for {pic.picture()}, got {len(data)}")
    if pic.usage == Usage.DISPLAY:
        b = bytearray(data)
        neg = False
        if pic.signed and pic.sign_separate:
            sb = b.pop(0) if pic.sign_leading else b.pop()
            neg = sb == ord("-")
        elif pic.signed:
            i = 0 if pic.sign_leading else len(b) - 1
            if 0x70 <= b[i] <= 0x79:
                neg = True
                b[i] -= 0x40
        mag = 0
        for c in b:
            mag = mag * 10 + (c & 0x0F if c != 0x20 else 0)
        return (-mag if neg else mag), neg and mag == 0
    u, negzero, _f, _p = decode_state(data, pic)
    return u, negzero


def decode_state(data: bytes, pic: NumPic) -> tuple[int, bool, bool, int]:
    """Like `decode`, also returning the COMP-3 byte details `(fnib, pad)` (see `encode`)."""
    if len(data) != pic.byte_length:
        raise ValueError(f"expected {pic.byte_length} bytes for {pic.picture()}, got {len(data)}")
    if pic.usage == Usage.COMP3:
        mag = 0
        nibbles: list[int] = []
        for c in data:
            nibbles += [c >> 4, c & 0x0F]
        sn = nibbles.pop()
        pad = nibbles.pop(0) if pic.digits % 2 == 0 else 0  # not part of the value
        for d in nibbles:
            mag = mag * 10 + d
        neg = pic.signed and sn == 0x0D
        return (-mag if neg else mag), neg and mag == 0, pic.signed and sn == 0x0F, pad
    if pic.usage == Usage.DISPLAY:
        u, nz = decode(data, pic)
        return u, nz, False, 0
    raw = data if pic.usage == Usage.COMP else data[::-1]
    return int.from_bytes(raw, "big", signed=pic.signed), False, False, 0


def display(u: int, pic: NumPic) -> bytes:
    """What `DISPLAY field` prints (GnuCOBOL `pretty-display: yes`).

    Signed items always show a sign (`+`/`-`, leading; trailing only for SIGN TRAILING SEPARATE);
    negative zero prints as `+`. A V inserts a decimal point; P positions print as zeros. COMP-5
    prints the raw binary integer (scale ignored) with 3/5/10/20 digits for 1/2/4/8 bytes.
    """
    mag = abs(u)
    if pic.usage == Usage.COMP5:
        width = COMP5_DISPLAY_DIGITS[pic.byte_length]
        body = str(mag).rjust(width, "0")
        return ((("-" if u < 0 else "+") if pic.signed else "") + body).encode("ascii")
    if pic.scale <= 0:
        body = str(mag * 10**-pic.scale).rjust(pic.digits - pic.scale, "0")
    else:
        width = max(pic.digits, pic.scale)
        s = str(mag).rjust(width, "0")
        body = s[: width - pic.scale] + "." + s[width - pic.scale:]
    if not pic.signed:
        return body.encode("ascii")
    sg = "-" if u < 0 else "+"
    if pic.sign_separate and not pic.sign_leading:
        return (body + sg).encode("ascii")
    return (sg + body).encode("ascii")
