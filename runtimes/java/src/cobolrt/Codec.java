package cobolrt;

/**
 * Record encodings of numeric items, byte-identical to GnuCOBOL 3.2:
 * <ul>
 * <li>DISPLAY (zoned): one ASCII digit per byte; a negative embedded sign is an ASCII overpunch of
 * the last (SIGN LEADING: first) digit, 0x70+d ('p'..'y'); SEPARATE puts '+'/'-' in its own byte;
 * unsigned items carry no sign.</li>
 * <li>COMP-3: two digits per byte, last nibble = sign (C positive, D negative, F unsigned).</li>
 * <li>COMP / BINARY: big-endian two's complement; COMP-5: little-endian.</li>
 * </ul>
 */
public final class Codec {
    private Codec() {}

    /** Bytes of an item holding unscaled {@code u} (for an unsigned 8-byte COMP-5: the bit pattern). */
    public static byte[] encode(long u, Pic pic) {
        return encode(u, pic, false, false, 0);
    }

    /**
     * Full form: {@code negZero} (DISPLAY/COMP-3 negative zero), and COMP-3 only {@code fnib} (sign
     * nibble F in a signed item) and {@code pad} (garbage digit in the unused high nibble of an
     * even-digit item). See {@link CobolDecimal}.
     */
    public static byte[] encode(long u, Pic pic, boolean negZero, boolean fnib, int pad) {
        int n = pic.byteLength();
        byte[] out = new byte[n];
        if (pic.usage == Usage.COMP || pic.usage == Usage.COMP5) {
            for (int i = 0; i < n; i++) {
                byte b = (byte) (u >>> (8 * i));
                if (pic.usage == Usage.COMP) {
                    out[n - 1 - i] = b;
                } else {
                    out[i] = b;
                }
            }
            return out;
        }
        boolean neg = u < 0 || (negZero && u == 0);
        long mag = Num.abs(u) % Num.pow10(pic.digits);
        if (pic.usage == Usage.DISPLAY) {
            int off = pic.signSeparate && pic.signLeading ? 1 : 0;
            for (int i = pic.digits - 1; i >= 0; i--) {
                out[off + i] = (byte) ('0' + (mag % 10));
                mag /= 10;
            }
            if (pic.signed) {
                if (pic.signSeparate) {
                    out[pic.signLeading ? 0 : n - 1] = (byte) (neg ? '-' : '+');
                } else if (neg) {
                    int i = pic.signLeading ? 0 : n - 1;
                    out[i] = (byte) (out[i] + 0x40);
                }
            }
            return out;
        }
        // COMP-3
        int nib = 2 * n - 1;
        long[] digits = new long[nib];
        for (int i = nib - 1, k = 0; i >= 0; i--, k++) {
            if (k < pic.digits) {
                digits[i] = mag % 10;
                mag /= 10;
            } else if (k == pic.digits && pic.digits % 2 == 0) {
                digits[i] = pad;
            }
        }
        int sn = !pic.signed || fnib ? 0x0F : (neg ? 0x0D : 0x0C);
        for (int i = 0; i < n; i++) {
            int hi = (int) digits[2 * i];
            int lo = i < n - 1 ? (int) digits[2 * i + 1] : sn;
            out[i] = (byte) ((hi << 4) | lo);
        }
        return out;
    }

    /** Decode bytes into an item's state (value, negative zero, COMP-3 F nibble / pad digit). */
    public static void decode(byte[] data, CobolDecimal item) {
        Pic pic = item.pic;
        if (data.length != pic.byteLength()) {
            throw new IllegalArgumentException("expected " + pic.byteLength() + " bytes for " + pic);
        }
        if (pic.usage == Usage.COMP || pic.usage == Usage.COMP5) {
            int n = data.length;
            long v = 0;
            for (int i = 0; i < n; i++) {
                int b = (pic.usage == Usage.COMP ? data[i] : data[n - 1 - i]) & 0xFF;
                v = (v << 8) | b;
            }
            if (pic.signed && n < 8 && (v & (1L << (8 * n - 1))) != 0) {
                v -= 1L << (8 * n);
            }
            item.setState(v, false, false, 0);
            return;
        }
        if (pic.usage == Usage.DISPLAY) {
            byte[] b = data.clone();
            boolean neg = false;
            int from = 0;
            int to = b.length;
            if (pic.signed && pic.signSeparate) {
                if (pic.signLeading) {
                    neg = b[0] == '-';
                    from = 1;
                } else {
                    neg = b[to - 1] == '-';
                    to--;
                }
            } else if (pic.signed) {
                int i = pic.signLeading ? 0 : b.length - 1;
                if (b[i] >= 0x70 && b[i] <= 0x79) {
                    neg = true;
                    b[i] -= 0x40;
                }
            }
            long mag = 0;
            for (int i = from; i < to; i++) {
                int c = b[i] & 0xFF;
                mag = mag * 10 + (c == 0x20 ? 0 : (c & 0x0F));
            }
            item.setState(neg ? -mag : mag, neg && mag == 0, false, 0);
            return;
        }
        int n = data.length;
        long mag = 0;
        int pad = 0;
        for (int i = 0; i < 2 * n - 1; i++) {
            int b = data[i / 2] & 0xFF;
            int d = i % 2 == 0 ? b >> 4 : b & 0x0F;
            if (i == 0 && pic.digits % 2 == 0) {
                pad = d;
            } else {
                mag = mag * 10 + d;
            }
        }
        int sn = data[n - 1] & 0x0F;
        boolean neg = pic.signed && sn == 0x0D;
        item.setState(neg ? -mag : mag, neg && mag == 0, pic.signed && sn == 0x0F, pad);
    }
}
