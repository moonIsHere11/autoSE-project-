package cobolrt;

/**
 * DISPLAY output, byte-identical to GnuCOBOL 3.2 ({@code pretty-display: yes}).
 *
 * <p>Signed items always show a sign ('+'/'-' leading; trailing only for SIGN TRAILING SEPARATE),
 * negative zero prints '+'; a V inserts '.', P positions print as zeros; COMP-5 prints the raw
 * binary integer (scale ignored) with 3/5/10/20 digits for 1/2/4/8 bytes; PIC X prints its bytes.
 * {@link #line} builds one DISPLAY statement's output including the newline.
 */
public final class Display {
    private Display() {}

    private static final int[] COMP5_DIGITS = {0, 3, 5, 0, 10, 0, 0, 0, 20};

    /** What {@code DISPLAY item} prints for a numeric item holding {@code u}. */
    public static byte[] numeric(long u, Pic pic) {
        StringBuilder b = new StringBuilder();
        if (pic.usage == Usage.COMP5) {
            int width = COMP5_DIGITS[pic.byteLength()];
            String body = pic.isU64() ? Long.toUnsignedString(u) : Long.toString(Math.abs(u));
            if (u == Long.MIN_VALUE) {
                body = "9223372036854775808";
            }
            if (pic.signed) {
                b.append(u < 0 ? '-' : '+');
            }
            for (int i = body.length(); i < width; i++) {
                b.append('0');
            }
            return Alnum.bytes(b.append(body).toString());
        }
        String mag = Long.toString(Math.abs(u));
        String body;
        if (pic.scale <= 0) {
            StringBuilder s = new StringBuilder();
            int width = pic.digits - pic.scale;
            String v = Math.abs(u) == 0 ? "0" : mag + zeros(-pic.scale);
            for (int i = v.length(); i < width; i++) {
                s.append('0');
            }
            body = s.append(v).toString();
        } else {
            int width = Math.max(pic.digits, pic.scale);
            StringBuilder s = new StringBuilder();
            for (int i = mag.length(); i < width; i++) {
                s.append('0');
            }
            s.append(mag);
            body = s.substring(0, width - pic.scale) + "." + s.substring(width - pic.scale);
        }
        if (!pic.signed) {
            return Alnum.bytes(body);
        }
        char sg = u < 0 ? '-' : '+';
        if (pic.signSeparate && !pic.signLeading) {
            return Alnum.bytes(body + sg);
        }
        return Alnum.bytes(sg + body);
    }

    private static String zeros(int n) {
        StringBuilder s = new StringBuilder();
        for (int i = 0; i < n; i++) {
            s.append('0');
        }
        return s.toString();
    }

    public static byte[] of(CobolDecimal item) {
        return numeric(item.unscaled(), item.pic);
    }

    public static byte[] of(PicX item) {
        return item.bytes();
    }

    /**
     * The bytes of {@code DISPLAY a b c}: items (CobolDecimal, PicX), literals (String, ISO-8859-1)
     * or raw byte[]; ends with a newline.
     */
    public static byte[] line(Object... items) {
        java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
        for (Object o : items) {
            byte[] b;
            if (o instanceof CobolDecimal) {
                b = of((CobolDecimal) o);
            } else if (o instanceof PicX) {
                b = of((PicX) o);
            } else if (o instanceof byte[]) {
                b = (byte[]) o;
            } else {
                b = Alnum.bytes(String.valueOf(o));
            }
            out.write(b, 0, b.length);
        }
        out.write('\n');
        return out.toByteArray();
    }

    /** Write {@code DISPLAY ...} to a stream (e.g. System.out); flushes nothing. */
    public static void print(java.io.OutputStream os, Object... items) {
        byte[] b = line(items);
        try {
            os.write(b);
        } catch (java.io.IOException e) {
            throw new java.io.UncheckedIOException(e);
        }
    }
}
