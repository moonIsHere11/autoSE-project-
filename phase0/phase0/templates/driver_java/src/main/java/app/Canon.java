package app;

import java.math.BigDecimal;
import java.math.BigInteger;

/**
 * Canonical value encoding of the execution interface (agreement 4.2). The cases are pinned by
 * kb/target/encoding_fixtures.json; Phase 2 reviews them.
 *
 * <ul>
 * <li>Numeric (any usage: DISPLAY, COMP, COMP-3, COMP-5): plain decimal text with exactly
 * max(scale, 0) decimals, a leading '-' only when negative, no '+', no leading zeros beyond one
 * before the point: -123.40, 0.25, 7, 12300 (PIC 9(3)PP).</li>
 * <li>Zero is "0" / "0.00". A stored negative zero (only reachable through ACCEPT "-0" into a signed
 * DISPLAY item) is "-0" / "-0.00".</li>
 * <li>Alphanumeric X(n): exactly n characters, space padded, bytes mapped ISO-8859-1 to chars.</li>
 * <li>OCCURS element: key field_id(i) or field_id(i,j), 1-based, outermost subscript first.</li>
 * <li>Group item (only when a unit's state names a group): its raw record bytes as ISO-8859-1
 * text of exactly the group length (zoned signs overpunched, COMP-3 packed).</li>
 * </ul>
 */
public final class Canon {
    private Canon() {}

    /** A COBOL runtime failure inside a unit; the driver reports status "error". */
    public static final class UnitError extends RuntimeException {
        private static final long serialVersionUID = 1L;

        public UnitError(String message) {
            super(message);
        }
    }

    public static String decimal(long unscaled, int scale) {
        return decimal(unscaled, scale, false);
    }

    public static String decimal(long unscaled, int scale, boolean negativeZero) {
        BigDecimal v = new BigDecimal(BigInteger.valueOf(unscaled), scale);
        int shown = Math.max(scale, 0);
        String text = v.setScale(shown).toPlainString();
        if (unscaled == 0 && negativeZero) {
            return "-" + text;
        }
        return text;
    }

    /** Unscaled value of canonical text for a PIC with {@code scale}; extra decimals are an error. */
    public static long unscaled(String canonical, int scale) {
        BigDecimal v = new BigDecimal(canonical.trim());
        return v.movePointRight(scale).setScale(0).longValueExact();
    }

    public static boolean isNegativeZero(String canonical) {
        String t = canonical.trim();
        return t.startsWith("-") && new BigDecimal(t).signum() == 0;
    }

    public static String alnum(String value, int length) {
        StringBuilder b = new StringBuilder(length);
        for (int i = 0; i < length; i++) {
            if (i < value.length()) {
                b.append(value.charAt(i));
            } else {
                b.append(' ');
            }
        }
        return b.toString();
    }

    public static String key(String fieldId, int... subscripts) {
        if (subscripts.length == 0) {
            return fieldId;
        }
        StringBuilder b = new StringBuilder(fieldId).append('(');
        for (int i = 0; i < subscripts.length; i++) {
            if (i > 0) {
                b.append(',');
            }
            b.append(subscripts[i]);
        }
        return b.append(')').toString();
    }

    public static String bytes(byte[] raw) {
        StringBuilder b = new StringBuilder(raw.length);
        for (byte x : raw) {
            b.append((char) (x & 0xFF));
        }
        return b.toString();
    }
}
