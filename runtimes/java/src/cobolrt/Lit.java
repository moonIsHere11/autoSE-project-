package cobolrt;

import java.math.BigInteger;

/** A parsed COBOL numeric literal {@code [+-]digits[.digits]}. */
final class Lit {
    final BigInteger value;
    final int scale;
    final boolean minus;
    final int ndigits;

    private Lit(BigInteger value, int scale, boolean minus, int ndigits) {
        this.value = value;
        this.scale = scale;
        this.minus = minus;
        this.ndigits = ndigits;
    }

    static Lit parse(String text) {
        String t = text.trim();
        boolean neg = t.startsWith("-");
        if (t.startsWith("+") || t.startsWith("-")) {
            t = t.substring(1);
        }
        int dot = t.indexOf('.');
        String ip = dot < 0 ? t : t.substring(0, dot);
        String fp = dot < 0 ? "" : t.substring(dot + 1);
        String all = ip + fp;
        if (all.isEmpty() || fp.indexOf('.') >= 0) {
            throw new NumberFormatException("not a numeric literal: " + text);
        }
        for (int i = 0; i < all.length(); i++) {
            if (all.charAt(i) < '0' || all.charAt(i) > '9') {
                throw new NumberFormatException("not a numeric literal: " + text);
            }
        }
        BigInteger u = new BigInteger(all);
        return new Lit(neg ? u.negate() : u, fp.length(), neg, t.length());
    }

    /** cb_fits_int: no decimals and within a C int. */
    boolean fitsInt() {
        return scale == 0 && value.bitLength() <= 31;
    }

    boolean fitsLongLong() {
        return scale == 0 && value.bitLength() <= 63;
    }
}
