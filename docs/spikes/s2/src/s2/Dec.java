package s2;

/**
 * Toy "JBMC-friendly" COBOL decimal: long-backed, no BigDecimal, no loops, no arrays,
 * no JDK library calls (JBMC has no model for most of java.lang / java.math).
 *
 * value = unscaled / 10^scale ; PIC S9(5)V99 -> digits = 7, scale = 2, signed = true.
 */
public final class Dec {
    public long unscaled;
    public final int digits;
    public final int scale;
    public final boolean signed;

    public Dec(int digits, int scale, boolean signed) {
        this.digits = digits;
        this.scale = scale;
        this.signed = signed;
    }

    /** 10^n for 0 <= n <= 18, via switch (no static array, no loop -> nothing to unwind). */
    public static long pow10(int n) {
        switch (n) {
            case 0: return 1L;
            case 1: return 10L;
            case 2: return 100L;
            case 3: return 1_000L;
            case 4: return 10_000L;
            case 5: return 100_000L;
            case 6: return 1_000_000L;
            case 7: return 10_000_000L;
            case 8: return 100_000_000L;
            case 9: return 1_000_000_000L;
            case 10: return 10_000_000_000L;
            case 11: return 100_000_000_000L;
            case 12: return 1_000_000_000_000L;
            case 13: return 10_000_000_000_000L;
            case 14: return 100_000_000_000_000L;
            case 15: return 1_000_000_000_000_000L;
            case 16: return 10_000_000_000_000_000L;
            case 17: return 100_000_000_000_000_000L;
            case 18: return 1_000_000_000_000_000_000L;
            default: throw new IllegalArgumentException("pow10 out of range");
        }
    }

    /**
     * Align an unscaled value from scale {@code from} to scale {@code to}. Scaling down drops
     * low-order digits: truncation (COBOL default) or round-half-away-from-zero (ROUNDED).
     */
    public static long rescale(long v, int from, int to, boolean rounded) {
        if (to >= from) {
            return v * pow10(to - from);
        }
        long p = pow10(from - to);
        long q = v / p;          // Java division truncates toward zero
        if (rounded) {
            long rem = v % p;    // same sign as v
            long mag = rem < 0 ? -rem : rem;
            if (mag * 2 >= p) {
                q += (v < 0) ? -1 : 1;
            }
        }
        return q;
    }

    /**
     * COBOL store into this field: decimal-point alignment (truncate or ROUNDED), then
     * high-order truncation to {@code digits} digits (no ON SIZE ERROR), then the sign is
     * dropped if the receiving field is unsigned (absolute value is stored).
     */
    public void store(long v, int vScale, boolean rounded) {
        long r = rescale(v, vScale, scale, rounded);
        r = r % pow10(digits);   // keeps sign; drops high-order digits of the magnitude
        if (!signed && r < 0) {
            r = -r;
        }
        unscaled = r;
    }

    /** ADD a TO b GIVING target [ROUNDED]. */
    public static void add(Dec a, Dec b, Dec target, boolean rounded) {
        int s = a.scale > b.scale ? a.scale : b.scale;
        long x = rescale(a.unscaled, a.scale, s, false);
        long y = rescale(b.unscaled, b.scale, s, false);
        target.store(x + y, s, rounded);
    }

    /** SUBTRACT a FROM b GIVING target [ROUNDED]  (target = b - a). */
    public static void subtract(Dec a, Dec b, Dec target, boolean rounded) {
        int s = a.scale > b.scale ? a.scale : b.scale;
        long x = rescale(a.unscaled, a.scale, s, false);
        long y = rescale(b.unscaled, b.scale, s, false);
        target.store(y - x, s, rounded);
    }

    /** MULTIPLY a BY b GIVING target [ROUNDED] (exact product has scale a.scale + b.scale). */
    public static void multiply(Dec a, Dec b, Dec target, boolean rounded) {
        target.store(a.unscaled * b.unscaled, a.scale + b.scale, rounded);
    }

    /**
     * DIVIDE b INTO a GIVING target [ROUNDED] (target = a / b). Caller guarantees b != 0
     * (COBOL: ON SIZE ERROR). Quotient is computed with one digit beyond the target scale,
     * then stored (truncated or rounded on that extra digit).
     */
    public static void divide(Dec a, Dec b, Dec target, boolean rounded) {
        int extra = target.scale + 1 - (a.scale - b.scale);   // >= 0 for the spike's PICs
        long num = a.unscaled * pow10(extra);
        long q = num / b.unscaled;
        target.store(q, target.scale + 1, rounded);
    }
}
