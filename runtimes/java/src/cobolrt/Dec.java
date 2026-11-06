package cobolrt;

import java.math.BigInteger;

/**
 * An exact intermediate result (GnuCOBOL's cob_decimal): value * 10^-scale, or NaN after a
 * division by zero. Addition, subtraction and multiplication are exact; division keeps 38 extra
 * fractional digits and truncates, exactly like GnuCOBOL, so {@code A / B * B} may differ from A.
 * Build COMPUTE expressions in the same order as the COBOL source. Immutable.
 *
 * <p>Uses BigInteger, so it is for the object API (T1 testing), not for JBMC; the static core
 * {@link Num} covers what fits in 63 bits.
 */
public final class Dec {
    public static final int MAX_DIGITS = 38;

    public final BigInteger value;
    public final int scale;
    public final boolean nan;

    public static final Dec ZERO = new Dec(BigInteger.ZERO, 0, false);
    public static final Dec NAN = new Dec(BigInteger.ZERO, 0, true);

    private Dec(BigInteger value, int scale, boolean nan) {
        this.value = value;
        this.scale = scale;
        this.nan = nan;
    }

    public static Dec of(BigInteger value, int scale) {
        return new Dec(value, scale, false);
    }

    public static Dec of(long unscaled, int scale) {
        return new Dec(BigInteger.valueOf(unscaled), scale, false);
    }

    /** An integer. */
    public static Dec of(long v) {
        return of(v, 0);
    }

    /** The current value of an item. */
    public static Dec of(CobolDecimal item) {
        return item.dec();
    }

    /** A numeric literal such as {@code "-12.50"} (its scale is its number of decimals). */
    public static Dec literal(String text) {
        Lit l = Lit.parse(text);
        return of(l.value, l.scale);
    }

    public boolean isZero() {
        return !nan && value.signum() == 0;
    }

    public Dec add(Dec o) {
        if (nan || o.nan) {
            return NAN;
        }
        if (scale != o.scale) {
            if (o.value.signum() == 0) {
                return this;
            }
            if (value.signum() == 0) {
                return o;
            }
            int s = Math.max(scale, o.scale);
            return of(Big.shift(value, s - scale).add(Big.shift(o.value, s - o.scale)), s);
        }
        return of(value.add(o.value), scale);
    }

    public Dec subtract(Dec o) {
        if (nan || o.nan) {
            return NAN;
        }
        if (scale != o.scale) {
            if (o.value.signum() == 0) {
                return this;
            }
            int s = Math.max(scale, o.scale);
            return of(Big.shift(value, s - scale).subtract(Big.shift(o.value, s - o.scale)), s);
        }
        return of(value.subtract(o.value), scale);
    }

    public Dec multiply(Dec o) {
        if (nan || o.nan) {
            return NAN;
        }
        return of(value.multiply(o.value), scale + o.scale);
    }

    public Dec divide(Dec o) {
        if (nan || o.nan || o.value.signum() == 0) {
            return NAN;
        }
        if (value.signum() == 0) {
            return ZERO;
        }
        int s = scale - o.scale;
        int sh = MAX_DIGITS + (s < 0 ? -s : 0);
        return of(value.multiply(Big.pow10(sh)).divide(o.value), s + sh);
    }

    /** Unary minus (cobc builds {@code 0 - x}). */
    public Dec negate() {
        return ZERO.subtract(this);
    }

    public Dec add(CobolDecimal o) {
        return add(o.dec());
    }

    public Dec subtract(CobolDecimal o) {
        return subtract(o.dec());
    }

    public Dec multiply(CobolDecimal o) {
        return multiply(o.dec());
    }

    public Dec divide(CobolDecimal o) {
        return divide(o.dec());
    }

    @Override
    public String toString() {
        if (nan) {
            return "NaN";
        }
        return value + "E-" + scale;
    }
}
