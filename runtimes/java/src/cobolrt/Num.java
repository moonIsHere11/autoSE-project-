package cobolrt;

/**
 * Static numeric core on {@code long} unscaled values (value = v * 10^-scale), for the verifier's
 * reference emitter (JBMC, OpenJML) and for hand-written code that wants plain longs.
 *
 * <p>JBMC/OpenJML rules followed here: no JDK calls (no Math, no System.arraycopy, no BigInteger,
 * no String), no exceptions, no collections, powers of ten from a switch. Every method states its
 * 63-bit preconditions; the emitter must only call a method when it has shown they hold (the
 * {@code fitsShiftUp}/{@code fitsMul} predicates help). Semantics are those of GnuCOBOL 3.2's
 * decimal path (cob_decimal_get_field): see docs/RUNTIME_API.md. The object API
 * ({@link CobolDecimal}) is the reference for the rarer cases this core does not model (record
 * byte details such as COMP-3 sign/pad nibbles, the COMP-3 ADD/SUBTRACT fast paths, COMPUTE with
 * divisions inside an expression).
 */
public final class Num {
    private Num() {}

    public static final long MAX18 = 999999999999999999L;

    /*@ public normal_behavior
      @   requires 0 <= n && n <= 18;
      @   ensures \result >= 1 && \result <= 1000000000000000000L;
      @   ensures n == 0 ==> \result == 1;
      @   ensures n == 1 ==> \result == 10;
      @   ensures n == 2 ==> \result == 100;
      @   ensures n >= 1 ==> \result % 10 == 0;
      @ pure
      @*/
    public static long pow10(int n) {
        switch (n) {
            case 0: return 1L;
            case 1: return 10L;
            case 2: return 100L;
            case 3: return 1000L;
            case 4: return 10000L;
            case 5: return 100000L;
            case 6: return 1000000L;
            case 7: return 10000000L;
            case 8: return 100000000L;
            case 9: return 1000000000L;
            case 10: return 10000000000L;
            case 11: return 100000000000L;
            case 12: return 1000000000000L;
            case 13: return 10000000000000L;
            case 14: return 100000000000000L;
            case 15: return 1000000000000000L;
            case 16: return 10000000000000000L;
            case 17: return 100000000000000000L;
            default: return 1000000000000000000L;
        }
    }

    /*@ public normal_behavior
      @   requires v != Long.MIN_VALUE;
      @   ensures \result >= 0;
      @   ensures \result == v || \result == -v;
      @ pure
      @*/
    public static long abs(long v) {
        return v < 0 ? -v : v;
    }

    /*@ public normal_behavior
      @   ensures \result == (v > 0 ? 1 : (v < 0 ? -1 : 0));
      @ pure
      @*/
    public static int sign(long v) {
        return v > 0 ? 1 : (v < 0 ? -1 : 0);
    }

    /** Does |v| fit in {@code digits} decimal digits? */
    /*@ public normal_behavior
      @   requires 1 <= digits && digits <= 18 && v != Long.MIN_VALUE;
      @   ensures \result <==> (-pow10(digits) < v && v < pow10(digits));
      @ pure
      @*/
    public static boolean fits(long v, int digits) {
        long p = pow10(digits);
        return v > -p && v < p;
    }

    /** High-order truncation keeping the sign: v % 10^digits. */
    /*@ public normal_behavior
      @   requires 1 <= digits && digits <= 18;
      @   ensures \result == v % pow10(digits);
      @   ensures -pow10(digits) < \result && \result < pow10(digits);
      @ pure
      @*/
    public static long truncDigits(long v, int digits) {
        return v % pow10(digits);
    }

    /** Can v be multiplied by 10^n without overflow? */
    /*@ public normal_behavior
      @   requires 0 <= n && n <= 18;
      @   ensures \result <==> (v <= Long.MAX_VALUE / pow10(n) && v >= -(Long.MAX_VALUE / pow10(n)));
      @ pure
      @*/
    public static boolean fitsShiftUp(long v, int n) {
        long lim = Long.MAX_VALUE / pow10(n);
        return v <= lim && v >= -lim;
    }

    /** v * 10^n. */
    /*@ public normal_behavior
      @   requires 0 <= n && n <= 18;
      @   requires v <= Long.MAX_VALUE / pow10(n) && v >= -(Long.MAX_VALUE / pow10(n));
      @   ensures \result == v * pow10(n);
      @ pure
      @*/
    public static long shiftUp(long v, int n) {
        return v * pow10(n);
    }

    /** v / 10^n truncated toward zero; 0 when n > 18. */
    /*@ public normal_behavior
      @   requires n >= 0;
      @   ensures n <= 18 ==> \result == v / pow10(n);
      @   ensures n > 18 ==> \result == 0;
      @ pure
      @*/
    public static long shiftDown(long v, int n) {
        if (n > 18) {
            return 0;
        }
        return v / pow10(n);
    }

    /** Re-express v (at scale from) at scale to, truncating dropped digits toward zero. */
    /*@ public normal_behavior
      @   requires to - from <= 18 && from - to <= 1000;
      @   requires to > from ==> (v <= Long.MAX_VALUE / pow10(to - from) && v >= -(Long.MAX_VALUE / pow10(to - from)));
      @   ensures to >= from ==> \result == v * pow10(to - from);
      @ pure
      @*/
    public static long rescale(long v, int from, int to) {
        if (to >= from) {
            return shiftUp(v, to - from);
        }
        return shiftDown(v, from - to);
    }

    /** Can a * b be computed without overflow? */
    /*@ public normal_behavior
      @   requires a != Long.MIN_VALUE && b != Long.MIN_VALUE;
      @   ensures \result ==> (a == 0 || b == 0 || abs(b) <= Long.MAX_VALUE / abs(a));
      @ pure
      @*/
    public static boolean fitsMul(long a, long b) {
        if (a == 0 || b == 0) {
            return true;
        }
        return abs(b) <= Long.MAX_VALUE / abs(a);
    }

    /**
     * Final rounding step: {@code t} is the magnitude-truncated value with ONE extra digit,
     * {@code sticky} says whether any digit below that one was non-zero, {@code negative} is the
     * sign of the exact value. Returns the value at the target scale for the given Round mode
     * (decimal path: plain ROUNDED = NEAREST-AWAY-FROM-ZERO; TRUNCATION, MODE_TRUNCATION and
     * PROHIBITED truncate - PROHIBITED's size error is {@link #prohibitedError}).
     */
    /*@ public normal_behavior
      @   requires t != Long.MIN_VALUE;
      @   requires 0 <= mode && mode <= 9;
      @   ensures negative ==> \result <= 0;
      @   ensures !negative ==> \result >= 0;
      @   ensures (mode == Round.TRUNCATION || mode == Round.MODE_TRUNCATION || mode == Round.PROHIBITED)
      @           ==> \result == (negative ? -(abs(t) / 10) : abs(t) / 10);
      @   ensures abs(\result) - abs(t) / 10 == 0 || abs(\result) - abs(t) / 10 == 1;
      @ pure
      @*/
    public static long roundDigit(long t, boolean sticky, boolean negative, int mode) {
        long a = abs(t);
        long m = a / 10;
        long rd = a % 10;
        boolean inexact = rd != 0 || sticky;
        boolean up;
        switch (mode) {
            case Round.ROUNDED:
            case Round.NEAREST_AWAY_FROM_ZERO:
                up = rd >= 5;
                break;
            case Round.AWAY_FROM_ZERO:
                up = inexact;
                break;
            case Round.NEAREST_EVEN:
                up = rd > 5 || (rd == 5 && (sticky || m % 2 == 1));
                break;
            case Round.NEAREST_TOWARD_ZERO:
                up = rd > 5 || (rd == 5 && sticky);
                break;
            case Round.TOWARD_GREATER:
                up = !negative && inexact;
                break;
            case Round.TOWARD_LESSER:
                up = negative && inexact;
                break;
            default:
                up = false;
                break;
        }
        if (up) {
            m = m + 1;
        }
        return negative ? -m : m;
    }

    /**
     * Round/truncate v (at vscale) to tscale with a Round mode (decimal path).
     * Requires, when tscale > vscale, that v * 10^(tscale - vscale) fits.
     */
    /*@ public normal_behavior
      @   requires v != Long.MIN_VALUE && 0 <= mode && mode <= 9;
      @   requires tscale - vscale <= 18 && vscale - tscale <= 1000;
      @   requires tscale > vscale ==> (v <= Long.MAX_VALUE / pow10(tscale - vscale) && v >= -(Long.MAX_VALUE / pow10(tscale - vscale)));
      @   ensures tscale >= vscale ==> \result == v * pow10(tscale - vscale);
      @ pure
      @*/
    public static long round(long v, int vscale, int tscale, int mode) {
        if (tscale >= vscale) {
            return shiftUp(v, tscale - vscale);
        }
        int k = vscale - tscale;
        long t = shiftDown(v, k - 1);
        boolean sticky;
        if (k - 1 > 18) {
            sticky = v != 0;
        } else {
            sticky = v % pow10(k - 1) != 0;
        }
        return roundDigit(t, sticky, v < 0, mode);
    }

    /** ROUNDED MODE PROHIBITED fails (EC-SIZE-TRUNCATION, target never written) when digits would be dropped. */
    /*@ public normal_behavior
      @   ensures \result <==> (v != 0 && tscale < vscale);
      @ pure
      @*/
    public static boolean prohibitedError(long v, int vscale, int tscale) {
        return v != 0 && tscale < vscale;
    }

    /** Two's complement wrap of v to {@code bytes} bytes (COMP-5); 8 bytes: unchanged bit pattern. */
    /*@ public normal_behavior
      @   requires bytes == 1 || bytes == 2 || bytes == 4 || bytes == 8;
      @   ensures bytes == 8 ==> \result == v;
      @   ensures bytes < 8 && signed ==> -(1L << (8 * bytes - 1)) <= \result && \result < (1L << (8 * bytes - 1));
      @   ensures bytes < 8 && !signed ==> 0 <= \result && \result < (1L << (8 * bytes));
      @ pure
      @*/
    public static long wrap(long v, int bytes, boolean signed) {
        if (bytes >= 8) {
            return v;
        }
        int bits = 8 * bytes;
        long m = v & ((1L << bits) - 1);
        if (signed && m >= (1L << (bits - 1))) {
            m = m - (1L << bits);
        }
        return m;
    }

    /**
     * Would storing v (already at the target scale) overflow the item? DISPLAY/COMP-3/COMP:
     * |v| >= 10^digits; COMP-5: |v| needs more than 8*bytes (-1 if signed) bits.
     */
    /*@ public normal_behavior
      @   requires 1 <= digits && digits <= 18 && v != Long.MIN_VALUE;
      @   requires bytes == 1 || bytes == 2 || bytes == 4 || bytes == 8;
      @   requires 0 <= usage && usage <= 3;
      @   ensures usage != Usage.COMP5 ==> (\result <==> !fits(v, digits));
      @ pure
      @*/
    public static boolean overflows(long v, int digits, boolean signed, int usage, int bytes) {
        if (usage != Usage.COMP5) {
            return !fits(v, digits);
        }
        if (bytes == 8) {
            return false;
        }
        int bitnum = 8 * bytes - (signed ? 1 : 0);
        return abs(v) >= (1L << bitnum);
    }

    /**
     * The value an item holds after storing v (already at the target scale) WITHOUT a size
     * error phrase: high-order truncation (DISPLAY/COMP-3/COMP, sign kept) or wrap (COMP-5);
     * an unsigned item receives the magnitude.
     */
    /*@ public normal_behavior
      @   requires 1 <= digits && digits <= 18 && v != Long.MIN_VALUE;
      @   requires bytes == 1 || bytes == 2 || bytes == 4 || bytes == 8;
      @   requires 0 <= usage && usage <= 3;
      @   ensures usage != Usage.COMP5 ==> fits(\result, digits);
      @   ensures !signed && usage != Usage.COMP5 ==> \result >= 0;
      @   ensures usage != Usage.COMP5 && fits(v, digits) ==> \result == (signed ? v : abs(v));
      @ pure
      @*/
    public static long storeValue(long v, int digits, boolean signed, int usage, int bytes) {
        if (usage == Usage.COMP5) {
            return wrap(signed ? v : abs(v), bytes, signed);
        }
        long m = abs(v) % pow10(digits);
        if (!signed) {
            return m;
        }
        return v < 0 ? -m : m;
    }

    /** Does storing v leave a DISPLAY/COMP-3 item holding a negative zero (record bytes only)? */
    /*@ public normal_behavior
      @   requires 1 <= digits && digits <= 18 && v != Long.MIN_VALUE;
      @   ensures \result <==> (signed && (usage == Usage.DISPLAY || usage == Usage.COMP3) && v < 0
      @                         && abs(v) % pow10(digits) == 0);
      @ pure
      @*/
    public static boolean storesNegativeZero(long v, int digits, boolean signed, int usage) {
        return signed && (usage == Usage.DISPLAY || usage == Usage.COMP3) && v < 0 && abs(v) % pow10(digits) == 0;
    }

    /**
     * Store v (at vscale) into an item WITHOUT size error phrase: rounding mode, truncation to
     * the item's scale, high-order truncation / wrap. (With ON SIZE ERROR: if
     * {@link #sizeError} the item is unchanged, else store.)
     */
    /*@ public normal_behavior
      @   requires 1 <= digits && digits <= 18 && v != Long.MIN_VALUE && 0 <= mode && mode <= 9;
      @   requires 0 <= usage && usage <= 3;
      @   requires scale - vscale <= 18 && vscale - scale <= 1000;
      @   requires scale > vscale ==> (v <= Long.MAX_VALUE / pow10(scale - vscale) && v >= -(Long.MAX_VALUE / pow10(scale - vscale)));
      @   ensures usage != Usage.COMP5 ==> fits(\result, digits);
      @ pure
      @*/
    public static long store(long v, int vscale, int digits, int scale, boolean signed, int usage, int mode) {
        long r = round(v, vscale, scale, mode);
        return storeValue(r, digits, signed, usage, Pic.binaryBytes(digits));
    }

    /** Would the store raise a size error (incl. PROHIBITED)? */
    /*@ public normal_behavior
      @   requires 1 <= digits && digits <= 18 && v != Long.MIN_VALUE && 0 <= mode && mode <= 9;
      @   requires 0 <= usage && usage <= 3;
      @   requires scale - vscale <= 18 && vscale - scale <= 1000;
      @   requires scale > vscale ==> (v <= Long.MAX_VALUE / pow10(scale - vscale) && v >= -(Long.MAX_VALUE / pow10(scale - vscale)));
      @ pure
      @*/
    public static boolean sizeError(long v, int vscale, int digits, int scale, boolean signed, int usage, int mode) {
        if (mode == Round.PROHIBITED && prohibitedError(v, vscale, scale)) {
            return true;
        }
        long r = round(v, vscale, scale, mode);
        return overflows(signed ? r : abs(r), digits, signed, usage, Pic.binaryBytes(digits));
    }

    /**
     * Quotient of a single division a/b (a at sa, b at sb) rounded to tscale: exactly GnuCOBOL's
     * result for DIVIDE and for a COMPUTE whose only division is the outermost operation (its
     * 38 extra digits never matter there). Requires b != 0 and k = tscale+1-sa+sb with
     * a*10^k (k >= 0) or b*10^-k (k < 0) fitting in 63 bits.
     */
    /*@ public normal_behavior
      @   requires b != 0 && a != Long.MIN_VALUE && b != Long.MIN_VALUE && 0 <= mode && mode <= 9;
      @   requires -18 <= tscale + 1 - sa + sb && tscale + 1 - sa + sb <= 18;
      @   requires tscale + 1 - sa + sb >= 0 ==> (a <= Long.MAX_VALUE / pow10(tscale + 1 - sa + sb) && a >= -(Long.MAX_VALUE / pow10(tscale + 1 - sa + sb)));
      @   requires tscale + 1 - sa + sb < 0 ==> (b <= Long.MAX_VALUE / pow10(sa - sb - tscale - 1) && b >= -(Long.MAX_VALUE / pow10(sa - sb - tscale - 1)));
      @ pure
      @*/
    public static long divide(long a, int sa, long b, int sb, int tscale, int mode) {
        int k = tscale + 1 - sa + sb;
        long t;
        boolean sticky;
        if (k >= 0) {
            long num = a * pow10(k);
            t = num / b;
            sticky = num % b != 0;
        } else {
            long den = b * pow10(-k);
            t = a / den;
            sticky = a % den != 0;
        }
        boolean negative = a != 0 && ((a < 0) != (b < 0));
        return roundDigit(t, sticky, negative, mode);
    }

    /** PROHIBITED on a division fails whenever the dividend is not zero. */
    /*@ public normal_behavior
      @   ensures \result <==> a != 0;
      @ pure
      @*/
    public static boolean divideProhibitedError(long a) {
        return a != 0;
    }

    /** Scale of DIVIDE ... REMAINDER's remainder intermediate: max(sa, qscale + sb). */
    /*@ public normal_behavior
      @   ensures \result == (sa > qscale + sb ? sa : qscale + sb);
      @ pure
      @*/
    public static int remainderScale(int sa, int sb, int qscale) {
        return sa > qscale + sb ? sa : qscale + sb;
    }

    /**
     * DIVIDE a BY b GIVING q REMAINDER r: the remainder intermediate (at remainderScale) =
     * a - q' * b, q' being the quotient truncated to the quotient's scale (never rounded, never
     * high-order truncated). Requires b != 0 and no overflow of the products.
     */
    /*@ public normal_behavior
      @   requires b != 0 && a != Long.MIN_VALUE && b != Long.MIN_VALUE;
      @   requires -18 <= qscale + 1 - sa + sb && qscale + 1 - sa + sb <= 18;
      @   requires qscale + 1 - sa + sb >= 0 ==> (a <= Long.MAX_VALUE / pow10(qscale + 1 - sa + sb) && a >= -(Long.MAX_VALUE / pow10(qscale + 1 - sa + sb)));
      @   requires qscale + 1 - sa + sb < 0 ==> (b <= Long.MAX_VALUE / pow10(sa - sb - qscale - 1) && b >= -(Long.MAX_VALUE / pow10(sa - sb - qscale - 1)));
      @   requires remainderScale(sa, sb, qscale) - sa <= 18;
      @   requires remainderScale(sa, sb, qscale) - qscale - sb <= 18;
      @   requires a <= Long.MAX_VALUE / pow10(remainderScale(sa, sb, qscale) - sa) && a >= -(Long.MAX_VALUE / pow10(remainderScale(sa, sb, qscale) - sa));
      @ pure
      @*/
    public static long remainder(long a, int sa, long b, int sb, int qscale) {
        long q = divide(a, sa, b, sb, qscale, Round.TRUNCATION);
        int rs = remainderScale(sa, sb, qscale);
        return shiftUp(a, rs - sa) - q * b * pow10(rs - qscale - sb);
    }

    /** Numeric comparison of a (at sa) and b (at sb): -1, 0, 1. Requires the aligned values to fit. */
    /*@ public normal_behavior
      @   requires sa - sb <= 18 && sb - sa <= 18;
      @   requires sb > sa ==> (a <= Long.MAX_VALUE / pow10(sb - sa) && a >= -(Long.MAX_VALUE / pow10(sb - sa)));
      @   requires sa > sb ==> (b <= Long.MAX_VALUE / pow10(sa - sb) && b >= -(Long.MAX_VALUE / pow10(sa - sb)));
      @   ensures \result == -1 || \result == 0 || \result == 1;
      @   ensures sa == sb ==> (\result == (a < b ? -1 : (a > b ? 1 : 0)));
      @ pure
      @*/
    public static int compare(long a, int sa, long b, int sb) {
        long x = a;
        long y = b;
        if (sb > sa) {
            x = shiftUp(a, sb - sa);
        } else if (sa > sb) {
            y = shiftUp(b, sa - sb);
        }
        return x < y ? -1 : (x > y ? 1 : 0);
    }

    /**
     * MOVE numeric to numeric (value part): align scales truncating, then high-order truncation
     * (DISPLAY/COMP-3/COMP) or wrap (COMP-5); unsigned targets get the magnitude. Negative zero
     * of DISPLAY/COMP-3 targets: {@link #moveNegativeZero}.
     */
    /*@ public normal_behavior
      @   requires u != Long.MIN_VALUE && 1 <= digits && digits <= 18 && 0 <= usage && usage <= 3;
      @   requires scale - sscale <= 18 && sscale - scale <= 1000;
      @   requires scale > sscale ==> (u <= Long.MAX_VALUE / pow10(scale - sscale) && u >= -(Long.MAX_VALUE / pow10(scale - sscale)));
      @   ensures usage != Usage.COMP5 ==> fits(\result, digits);
      @ pure
      @*/
    public static long move(long u, int sscale, int digits, int scale, boolean signed, int usage) {
        return storeValue(rescale(u, sscale, scale), digits, signed, usage, Pic.binaryBytes(digits));
    }

    /**
     * A DISPLAY/COMP-3 target takes the SOURCE sign, so a negative source whose digits are all
     * truncated away leaves a negative zero (binary sources into COMP-3: sign after scaling).
     */
    /*@ public normal_behavior
      @   requires u != Long.MIN_VALUE && 1 <= digits && digits <= 18;
      @   requires scale - sscale <= 18 && sscale - scale <= 1000;
      @   requires scale > sscale ==> (u <= Long.MAX_VALUE / pow10(scale - sscale) && u >= -(Long.MAX_VALUE / pow10(scale - sscale)));
      @ pure
      @*/
    public static boolean moveNegativeZero(long u, boolean srcNegZero, boolean srcBinary, int sscale,
                                           int digits, int scale, boolean signed, int usage) {
        if (!signed || (usage != Usage.DISPLAY && usage != Usage.COMP3)) {
            return false;
        }
        long w = rescale(u, sscale, scale);
        boolean neg = (srcBinary && usage == Usage.COMP3) ? w < 0 : (u < 0 || srcNegZero);
        return neg && abs(w) % pow10(digits) == 0;
    }

    /**
     * Effective Round mode of GnuCOBOL's packed-decimal ADD/SUBTRACT (target COMP-3, not GIVING,
     * with ROUNDED or a SIZE ERROR phrase): plain ROUNDED and MODE TRUNCATION truncate,
     * NEAREST-EVEN rounds half away from zero. (PROHIBITED differs too: see CobolDecimal.)
     */
    /*@ public normal_behavior
      @   ensures (mode == Round.ROUNDED || mode == Round.MODE_TRUNCATION) ==> \result == Round.TRUNCATION;
      @   ensures mode == Round.NEAREST_EVEN ==> \result == Round.NEAREST_AWAY_FROM_ZERO;
      @   ensures (mode != Round.ROUNDED && mode != Round.MODE_TRUNCATION && mode != Round.NEAREST_EVEN) ==> \result == mode;
      @ pure
      @*/
    public static int packedAddMode(int mode) {
        if (mode == Round.ROUNDED || mode == Round.MODE_TRUNCATION) {
            return Round.TRUNCATION;
        }
        if (mode == Round.NEAREST_EVEN) {
            return Round.NEAREST_AWAY_FROM_ZERO;
        }
        return mode;
    }
}
