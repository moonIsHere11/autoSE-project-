package cobolrt;

import java.math.BigInteger;

/**
 * A numeric elementary item for generated code: a {@code long} unscaled value plus its
 * {@link Pic} (digits, scale, signed, usage). Statement methods implement GnuCOBOL 3.2 semantics
 * exactly (validated by differential testing, docs/RUNTIME_API.md) and return {@code true} when a
 * size error occurred:
 *
 * <pre>
 *   // ADD A TO B ROUNDED ON SIZE ERROR ... NOT ON SIZE ERROR ... END-ADD
 *   if (b.add(a, Round.ROUNDED, SizeError.ON)) { ... } else { ... }
 * </pre>
 *
 * <p>Besides the value, the item tracks storage details GnuCOBOL can leave behind that only show
 * in record bytes: a negative zero (DISPLAY/COMP-3), and for COMP-3 a sign nibble F in a signed
 * item and a garbage digit in the pad nibble of an even-digit item. For an unsigned 8-byte COMP-5
 * item {@link #unscaled()} is the unsigned 64-bit bit pattern.
 */
public final class CobolDecimal {
    public final Pic pic;
    private long u;
    private boolean negZero;
    private boolean fnib;
    private int pad;

    public CobolDecimal(Pic pic) {
        this.pic = pic;
    }

    /** e.g. {@code new CobolDecimal("S9(5)V99", "COMP-3")}. */
    public CobolDecimal(String picture, String usage) {
        this(Pic.parse(picture, usage, ""));
    }

    public CobolDecimal(String picture, String usage, String sign) {
        this(Pic.parse(picture, usage, sign));
    }

    public CobolDecimal(String picture) {
        this(Pic.parse(picture));
    }

    /** With an initial value given as a numeric literal (like a VALUE clause / MOVE literal). */
    public static CobolDecimal of(String picture, String usage, String literal) {
        CobolDecimal d = new CobolDecimal(picture, usage);
        d.move(literal);
        return d;
    }

    // ---- state ---------------------------------------------------------------------------------

    public long unscaled() {
        return u;
    }

    public int scale() {
        return pic.scale;
    }

    public boolean isNegativeZero() {
        return negZero;
    }

    /** Exact value as an intermediate for COMPUTE expressions. */
    public Dec dec() {
        return Dec.of(big(), pic.scale);
    }

    BigInteger big() {
        return pic.isU64() ? Big.unsigned(u) : BigInteger.valueOf(u);
    }

    /** Set the raw value (no truncation; the caller guarantees it fits the item). */
    public void setUnscaled(long v) {
        setState(v, false, false, 0);
    }

    void setState(long v, boolean nz, boolean f, int p) {
        u = v;
        negZero = nz && v == 0;
        fnib = f;
        pad = p;
    }

    private boolean dneg() {
        return pic.signed && (u < 0 || negZero) && !fnib;
    }

    /** Magnitude including a garbage pad digit (what the BCD routines see). */
    private BigInteger full() {
        BigInteger m = big().abs();
        if (pic.usage == Usage.COMP3 && pad != 0) {
            m = m.add(BigInteger.valueOf(pad).multiply(Big.pow10(pic.digits)));
        }
        return m;
    }

    // ---- MOVE ----------------------------------------------------------------------------------

    /** MOVE src TO this. */
    public void move(CobolDecimal src) {
        Pic d = pic;
        Pic s = src.pic;
        if (s.equals(d)) {
            setState(src.u, src.negZero, src.fnib, src.pad);
            return;
        }
        if (s.usage == Usage.COMP3 && d.usage == Usage.COMP3 && s.scale >= 0 && d.scale >= 0) {
            long mag = Big.shift(src.full(), d.scale - s.scale).mod(Big.pow10(d.digits)).longValue();
            if (!d.signed) {
                setState(mag, false, false, 0);
            } else if (src.dneg()) {
                setState(-mag, mag == 0, false, 0);
            } else {
                setState(mag, false, !s.signed || src.fnib, 0);
            }
            return;
        }
        if (s.isBinary() && d.usage == Usage.COMP3) {
            int diff = s.scale - d.scale;
            if (s.digits < 19 && s.digits - diff < 19) {
                BigInteger val = Big.shift(src.big(), -diff);
                if (val.bitLength() <= 31) {
                    setPackedInt(val.longValue());
                    return;
                }
            }
        }
        moveValue(src.big(), s.scale, src.u < 0 || src.negZero, s.isBinary());
    }

    /** MOVE numeric-literal TO this, e.g. {@code move("-12.5")}. */
    public void move(String literal) {
        Lit l = Lit.parse(literal);
        Pic d = pic;
        if (d.usage == Usage.COMP3 && d.scale >= 0 && l.fitsInt() && l.ndigits + d.scale <= 9) {
            setPackedInt(l.value.longValue() * Num.pow10(d.scale));
            return;
        }
        moveValue(l.value, l.scale, l.minus, false);
    }

    /** MOVE integer-literal TO this. */
    public void move(long literal) {
        move(Long.toString(literal));
    }

    /** MOVE alphanumeric TO this (de-editing: sign, digits, one '.', ',' and spaces; else zero). */
    public void move(PicX src) {
        moveAlnum(src.bytes());
    }

    /** MOVE alphanumeric bytes TO this. */
    public void moveAlnum(byte[] src) {
        if (pic.usage == Usage.DISPLAY) {
            byte[] dd = Alnum.deedit(src, pic.digits, pic.scale);
            long mag = 0;
            for (int i = 0; i < pic.digits; i++) {
                mag = mag * 10 + (dd[i] - '0');
            }
            boolean neg = dd[pic.digits] < 0 && pic.signed;
            setState(neg ? -mag : mag, neg && mag == 0, false, 0);
            return;
        }
        byte[] dd = Alnum.deedit(src, 76, 38);
        BigInteger mag = new BigInteger(new String(dd, 0, 76, java.nio.charset.StandardCharsets.ISO_8859_1));
        boolean neg = dd[76] < 0;
        moveValue(neg ? mag.negate() : mag, 38, neg, false);
    }

    /** COMPUTE-style store of an intermediate (MOVE of an expression value). */
    public void move(Dec value) {
        store(value, Round.TRUNCATION, SizeError.NONE);
    }

    /** cob_set_packed_int: zero is +0; digits beyond the item spill into the pad nibble. */
    private void setPackedInt(long val) {
        if (val == 0) {
            setState(0, false, false, 0);
            return;
        }
        int nib = 2 * pic.byteLength() - 1;
        long full = nib > 18 ? Num.abs(val) : Num.abs(val) % Num.pow10(nib);
        long mag = full % Num.pow10(pic.digits);
        boolean neg = val < 0 && pic.signed;
        setState(neg ? -mag : mag, neg && mag == 0, false, (int) (full / Num.pow10(pic.digits)));
    }

    /** Generic numeric MOVE: align scale (truncating), high-order truncate / wrap, source sign. */
    private void moveValue(BigInteger v, int vscale, boolean neg, boolean fromBinary) {
        Pic d = pic;
        BigInteger w = Big.shift(v, d.scale - vscale);
        BigInteger mag = w.abs();
        if (d.usage == Usage.DISPLAY || d.usage == Usage.COMP3) {
            long m = mag.mod(Big.pow10(d.digits)).longValue();
            if (!d.signed) {
                setState(m, false, false, 0);
                return;
            }
            boolean n = (fromBinary && d.usage == Usage.COMP3) ? w.signum() < 0 : neg;
            setState(n ? -m : m, n && m == 0, false, 0);
            return;
        }
        if (d.usage == Usage.COMP) {
            long m = mag.mod(Big.pow10(d.digits)).longValue();
            setState(w.signum() < 0 && d.signed ? -m : m, false, false, 0);
            return;
        }
        setState(Big.wrap(d.signed ? w : mag, d.byteLength(), d.signed), false, false, 0);
    }

    // ---- store (cob_decimal_get_field) ---------------------------------------------------------

    private static boolean keeps(Pic p, int size) {
        if (p.usage == Usage.COMP5) {
            return size == SizeError.ON;
        }
        return size != SizeError.NONE;
    }

    /**
     * Store an intermediate result: ROUNDED mode, truncation to the item's scale, then high-order
     * truncation (DISPLAY/COMP-3/COMP, sign kept: may give a negative zero) or COMP-5 wrap; with a
     * SIZE ERROR phrase an overflowing item is left unchanged. Returns true on size error
     * (including division by zero and ROUNDED MODE PROHIBITED, which never write the item).
     */
    public boolean store(Dec value, int mode, int size) {
        if (value.nan) {
            return true;
        }
        BigInteger v = value.value;
        int vscale = value.scale;
        Pic p = pic;
        if (mode != Round.TRUNCATION && mode != Round.MODE_TRUNCATION && v.signum() != 0 && p.scale < vscale) {
            if (mode == Round.PROHIBITED) {
                return true;
            }
            int sg = v.signum();
            int adj = vscale - p.scale;
            switch (mode) {
                case Round.AWAY_FROM_ZERO:
                    if (Big.trem(v, Big.pow10(adj)).signum() != 0) {
                        v = v.add(BigInteger.valueOf(sg).multiply(Big.pow10(adj)));
                    }
                    break;
                case Round.TOWARD_GREATER:
                    if (Big.trem(v, Big.pow10(adj)).signum() != 0 && sg > 0) {
                        v = v.add(Big.pow10(adj));
                    }
                    break;
                case Round.TOWARD_LESSER:
                    if (Big.trem(v, Big.pow10(adj)).signum() != 0 && sg < 0) {
                        v = v.subtract(Big.pow10(adj));
                    }
                    break;
                case Round.NEAREST_TOWARD_ZERO: {
                    BigInteger r = Big.trem(v, Big.pow10(adj - 1).multiply(BigInteger.valueOf(5)));
                    v = Big.shift(v, p.scale - vscale + 1);
                    vscale = p.scale + 1;
                    if (r.signum() != 0) {
                        v = v.add(BigInteger.valueOf(5L * sg));
                    }
                    break;
                }
                case Round.NEAREST_EVEN: {
                    BigInteger r = Big.trem(v, Big.pow10(adj - 1).multiply(BigInteger.valueOf(5)));
                    v = Big.shift(v, p.scale - vscale + 1);
                    vscale = p.scale + 1;
                    int last = v.abs().mod(BigInteger.valueOf(100)).intValue();
                    boolean even = r.signum() == 0
                            && (last == 5 || last == 25 || last == 45 || last == 65 || last == 85);
                    if (!even) {
                        v = v.add(BigInteger.valueOf(5L * sg));
                    }
                    break;
                }
                default: // ROUNDED, NEAREST_AWAY_FROM_ZERO
                    v = Big.shift(v, p.scale - vscale + 1).add(BigInteger.valueOf(5L * sg));
                    vscale = p.scale + 1;
                    break;
            }
        }
        if (v.signum() != 0) {
            v = Big.shift(v, p.scale - vscale);
        }
        if (v.signum() == 0) {
            setState(0, false, false, 0);
            return false;
        }
        boolean keep = keeps(p, size);
        int sg = v.signum();
        BigInteger mag = v.abs();
        if (p.usage == Usage.DISPLAY || p.usage == Usage.COMP3) {
            BigInteger lim = Big.pow10(p.digits);
            boolean err = mag.compareTo(lim) >= 0;
            if (err) {
                if (keep) {
                    return true;
                }
                mag = mag.mod(lim);
            }
            long m = mag.longValue();
            if (!p.signed) {
                setState(m, false, false, 0);
            } else {
                setState(sg < 0 ? -m : m, sg < 0 && m == 0, false, 0);
            }
            return err;
        }
        int bits = 8 * p.byteLength();
        int bitnum = bits - (p.signed ? 1 : 0);
        if (!p.signed) {
            sg = 1;
        }
        if (mag.bitLength() > bitnum) {
            if (keep) {
                return true;
            }
            if (p.usage == Usage.COMP) {
                long m = mag.mod(Big.pow10(p.digits)).longValue();
                setState(sg < 0 ? -m : m, false, false, 0);
            } else {
                setState(Big.wrap(sg < 0 ? mag.negate() : mag, p.byteLength(), p.signed), false, false, 0);
            }
            return true;
        }
        if (p.usage == Usage.COMP && mag.compareTo(Big.pow10(p.digits)) >= 0) {
            if (keep) {
                return true;
            }
            long m = mag.mod(Big.pow10(p.digits)).longValue();
            setState(sg < 0 ? -m : m, false, false, 0);
            return true;
        }
        setState((sg < 0 ? mag.negate() : mag).longValue(), false, false, 0);
        return false;
    }

    public boolean store(Dec value) {
        return store(value, Round.TRUNCATION, SizeError.NONE);
    }

    // ---- arithmetic statements -----------------------------------------------------------------

    /** COMPUTE this [ROUNDED] = value (also the GIVING forms of ADD/SUBTRACT/MULTIPLY/DIVIDE). */
    public boolean compute(Dec value, int mode, int size) {
        return store(value, mode, size);
    }

    public boolean compute(Dec value) {
        return store(value, Round.TRUNCATION, SizeError.NONE);
    }

    /** ADD x TO this. */
    public boolean add(CobolDecimal x, int mode, int size) {
        return addsub(x, null, x.dec(), mode, size, false);
    }

    /** ADD literal TO this, e.g. {@code add("1.5", ...)}. */
    public boolean add(String literal, int mode, int size) {
        return addsub(null, literal, Dec.literal(literal), mode, size, false);
    }

    public boolean add(long literal, int mode, int size) {
        return add(Long.toString(literal), mode, size);
    }

    public boolean add(CobolDecimal x) {
        return add(x, Round.TRUNCATION, SizeError.NONE);
    }

    /** SUBTRACT x FROM this. */
    public boolean subtract(CobolDecimal x, int mode, int size) {
        return addsub(x, null, x.dec(), mode, size, true);
    }

    public boolean subtract(String literal, int mode, int size) {
        return addsub(null, literal, Dec.literal(literal), mode, size, true);
    }

    public boolean subtract(long literal, int mode, int size) {
        return subtract(Long.toString(literal), mode, size);
    }

    public boolean subtract(CobolDecimal x) {
        return subtract(x, Round.TRUNCATION, SizeError.NONE);
    }

    /** MULTIPLY x BY this. */
    public boolean multiply(CobolDecimal x, int mode, int size) {
        return store(dec().multiply(x.dec()), mode, size);
    }

    public boolean multiply(String literal, int mode, int size) {
        return store(dec().multiply(Dec.literal(literal)), mode, size);
    }

    /** DIVIDE x INTO this. */
    public boolean divide(CobolDecimal x, int mode, int size) {
        return store(dec().divide(x.dec()), mode, size);
    }

    public boolean divide(String literal, int mode, int size) {
        return store(dec().divide(Dec.literal(literal)), mode, size);
    }

    /**
     * DIVIDE dividend BY divisor GIVING quotient [ROUNDED] REMAINDER remainder (for
     * {@code DIVIDE a INTO b ...} pass (b, a)). The remainder is dividend - q' * divisor where q' is
     * the quotient truncated to the quotient's scale (not rounded, not high-order truncated); it is
     * stored even when the quotient had a size error. Division by zero leaves both unchanged.
     */
    public static boolean divideRemainder(Dec dividend, Dec divisor, CobolDecimal quotient,
                                          CobolDecimal remainder, int mode, int size) {
        Dec q = dividend.divide(divisor);
        if (q.nan) {
            return true;
        }
        boolean e1 = quotient.store(q, mode, size);
        Dec qt = q.value.signum() == 0 ? Dec.ZERO
                : Dec.of(Big.shift(q.value, quotient.pic.scale - q.scale), quotient.pic.scale);
        Dec rem = dividend.subtract(qt.multiply(divisor));
        boolean e2 = remainder.store(rem, Round.TRUNCATION, size);
        return e1 || e2;
    }

    public static boolean divideRemainder(CobolDecimal dividend, CobolDecimal divisor, CobolDecimal quotient,
                                          CobolDecimal remainder, int mode, int size) {
        return divideRemainder(dividend.dec(), divisor.dec(), quotient, remainder, mode, size);
    }

    /** cb_fits_int for an item. */
    private static boolean fitsInt(Pic p) {
        if (p.scale > 0) {
            return false;
        }
        if (p.usage == Usage.DISPLAY) {
            return p.byteLength() < 10;
        }
        if (p.usage == Usage.COMP3) {
            return p.gcDigits() < 10;
        }
        return p.byteLength() <= 4;
    }

    /**
     * ADD/SUBTRACT, following the code path cobc 3.2 selects (cb_build_add): an in-place integer
     * add when there is neither ROUNDED nor SIZE ERROR and the operand is a small integer, the
     * packed-decimal (BCD) routine for COMP-3 targets, otherwise exact decimal arithmetic.
     */
    private boolean addsub(CobolDecimal x, String lit, Dec xd, int mode, int size, boolean sub) {
        Pic p = pic;
        boolean opt0 = mode == Round.TRUNCATION && p.usage != Usage.COMP
                && (size == SizeError.NONE || (p.usage == Usage.COMP5 && size == SizeError.NOT_ONLY));
        Long n = null;
        if (x != null && fitsInt(x.pic)) {
            n = x.big().multiply(Big.pow10(-x.pic.scale)).longValue();
        } else if (lit != null) {
            Lit l = Lit.parse(lit);
            if (l.fitsInt()) {
                n = l.value.longValue();
            }
        }
        if (opt0 && n != null) {
            long nv = n;
            if (sub && p.usage == Usage.COMP3 && p.scale == 0 && p.gcDigits() >= 10 && p.gcDigits() <= 18
                    && x != null && x.pic.isBinary() && !x.pic.signed && x.pic.byteLength() == 4 && nv != 0) {
                nv = (1L << 32) - nv; // negated as a C unsigned int, then widened (measured)
            } else if (sub) {
                nv = -nv;
            }
            if (nv == 0) {
                return false;
            }
            if (p.scale < 0) {
                long val = nv / Num.pow10(Math.min(18, -p.scale));
                if (-p.scale > 18) {
                    val = 0;
                }
                if (val == 0) {
                    return false;
                }
                return store(Dec.of(big().add(BigInteger.valueOf(val)), p.scale), Round.TRUNCATION, SizeError.NONE);
            }
            if (p.scale == 0 && p.usage == Usage.COMP5) {
                setState(Big.wrap(big().add(BigInteger.valueOf(nv)), p.byteLength(), p.signed), false, false, 0);
                return false;
            }
            if (p.scale == 0 && p.usage == Usage.COMP3) {
                boolean neg = dneg();
                if (!((nv > 0 && neg) || (nv < 0 && !neg))) {
                    int nib = 2 * p.byteLength() - 1;
                    BigInteger total = full().add(BigInteger.valueOf(Math.abs(nv))).mod(Big.pow10(nib));
                    long mag = total.mod(Big.pow10(p.digits)).longValue();
                    int pd = total.divide(Big.pow10(p.digits)).intValue();
                    if (neg) {
                        setState(-mag, mag == 0, false, pd);
                    } else {
                        setState(mag, false, fnib, pd);
                    }
                    return false;
                }
            }
            return store(dec().add(Dec.of(nv)), Round.TRUNCATION, SizeError.NONE);
        }
        if (p.usage == Usage.COMP3) {
            return bcdAdd(x, lit, mode, size, sub);
        }
        return store(sub ? dec().subtract(xd) : dec().add(xd), mode, size);
    }

    /** GnuCOBOL's packed-decimal ADD/SUBTRACT (cob_add_bcd), value semantics. */
    private boolean bcdAdd(CobolDecimal x, String lit, int mode, int size, boolean sub) {
        Pic p = pic;
        BigInteger xm;
        boolean xneg;
        int xs;
        if (x != null) {
            Pic q = x.pic;
            if (q.usage == Usage.COMP3) {
                xm = x.full();
                xneg = x.dneg();
            } else if (q.isBinary()) {
                int sz = q.digits / 2 + 1;
                xm = x.big().abs().mod(Big.pow10(2 * sz - 1));
                xneg = x.big().signum() < 0;
            } else {
                xm = x.big().abs();
                if (q.scale < 0) {
                    int sz = q.gcDigits() / 2 + 1;
                    int i0 = 1 - q.digits % 2;
                    xm = xm.multiply(Big.pow10((2 * sz - 1) - (i0 + q.digits)));
                }
                xneg = x.u < 0 || x.negZero;
            }
            xs = q.scale;
        } else {
            Lit l = Lit.parse(lit);
            xm = l.value.abs();
            xneg = l.minus;
            xs = l.scale;
        }
        int s = Math.max(xs, p.scale);
        BigInteger xa = xm.multiply(Big.pow10(s - xs));
        BigInteger ya = full().multiply(Big.pow10(s - p.scale));
        boolean yneg = dneg();
        boolean xn = xneg != sub;
        BigInteger m;
        boolean positive;
        if (xn == yneg) {
            m = xa.add(ya);
            positive = !xn;
        } else {
            int c = xa.compareTo(ya);
            if (c < 0) {
                m = ya.subtract(xa);
                positive = !yneg;
            } else if (c > 0) {
                m = xa.subtract(ya);
                positive = !xn;
            } else {
                setState(0, false, false, 0);
                return false;
            }
        }
        int k = s - p.scale;
        if (k > 0) {
            boolean rounding = mode != Round.TRUNCATION && mode != Round.ROUNDED && mode != Round.MODE_TRUNCATION;
            if (rounding) {
                int rd = m.divide(Big.pow10(k - 1)).mod(BigInteger.TEN).intValue();
                boolean restNz = m.mod(Big.pow10(k - 1)).signum() != 0;
                boolean inexact = rd != 0 || restNz;
                if (mode == Round.PROHIBITED) {
                    if (inexact) {
                        return true;
                    }
                    if (k % 2 == 0) {
                        return false; // target untouched, no exception (measured)
                    }
                } else if (mode == Round.NEAREST_AWAY_FROM_ZERO || mode == Round.NEAREST_EVEN) {
                    m = m.add(BigInteger.valueOf(5).multiply(Big.pow10(k - 1)));
                } else if (mode == Round.NEAREST_TOWARD_ZERO) {
                    if (rd > 5 || (rd == 5 && restNz)) {
                        m = m.add(Big.pow10(k));
                    }
                } else if (mode == Round.AWAY_FROM_ZERO || (mode == Round.TOWARD_GREATER && positive)
                        || (mode == Round.TOWARD_LESSER && !positive)) {
                    if (inexact) {
                        m = m.add(Big.pow10(k));
                    }
                }
            }
            m = m.divide(Big.pow10(k));
        }
        int nib = 2 * p.byteLength() - (p.gcDigits() % 2 == 0 ? 2 : 1);
        boolean err = m.compareTo(Big.pow10(nib)) >= 0;
        if (err) {
            if (size != SizeError.NONE) {
                return true;
            }
            m = m.mod(Big.pow10(nib));
        }
        BigInteger[] qr = m.divideAndRemainder(Big.pow10(p.digits));
        long mag = qr[1].longValue();
        int pd = qr[0].intValue();
        if (!p.signed) {
            setState(mag, false, false, pd);
        } else {
            setState(positive ? mag : -mag, !positive && mag == 0, false, pd);
        }
        return err;
    }

    // ---- other ---------------------------------------------------------------------------------

    /** Numeric comparison this <=> other: -1, 0, 1 (as in {@code IF this < other}). */
    public int compareTo(CobolDecimal other) {
        Pic p = pic;
        if (p.isBinary() && !p.signed && p.scale == 0 && p.byteLength() == 8 && other.big().signum() < 0
                && fitsLongLong(other.pic)) {
            return -1; // compared as C unsigned long long (cob_cmp_u64), measured
        }
        return dec().subtract(other.dec()).value.signum();
    }

    /** Comparison with a numeric literal. */
    public int compareTo(String literal) {
        Lit l = Lit.parse(literal);
        Pic p = pic;
        if (p.isBinary() && !p.signed && p.scale == 0 && p.byteLength() == 8 && l.value.signum() < 0
                && l.fitsLongLong()) {
            return -1;
        }
        return dec().subtract(Dec.of(l.value, l.scale)).value.signum();
    }

    private static boolean fitsLongLong(Pic p) {
        if (p.scale > 0) {
            return false;
        }
        if (p.usage == Usage.DISPLAY) {
            return p.byteLength() < 19;
        }
        if (p.usage == Usage.COMP3) {
            return p.gcDigits() < 19;
        }
        return true;
    }

    /** ACCEPT this from a line (without its newline); {@code null} = end of input (sets zero). */
    public void accept(byte[] line) {
        byte[] b = line == null ? new byte[] {' '} : line;
        if (pic.usage == Usage.DISPLAY && b.length > pic.byteLength()) {
            byte[] w = new byte[pic.byteLength()];
            for (int i = 0; i < w.length; i++) {
                w[i] = b[i];
            }
            b = w;
        }
        moveAlnum(b);
    }

    public void accept(String line) {
        accept(line == null ? null : Alnum.bytes(line));
    }

    /** DISPLAY output bytes. */
    public byte[] display() {
        return Display.numeric(u, pic);
    }

    /** Storage bytes (record encoding). */
    public byte[] encode() {
        return Codec.encode(u, pic, negZero, fnib, pad);
    }

    /** Load storage bytes (record decoding). */
    public void decode(byte[] data) {
        Codec.decode(data, this);
    }

    @Override
    public String toString() {
        return Alnum.string(display());
    }
}
