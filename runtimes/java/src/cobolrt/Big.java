package cobolrt;

import java.math.BigInteger;

/** BigInteger helpers with C semantics (truncating division). Package-private. */
final class Big {
    private Big() {}

    private static final BigInteger[] POW = new BigInteger[160];

    static {
        POW[0] = BigInteger.ONE;
        for (int i = 1; i < POW.length; i++) {
            POW[i] = POW[i - 1].multiply(BigInteger.TEN);
        }
    }

    static BigInteger pow10(int n) {
        return n < POW.length ? POW[n] : BigInteger.TEN.pow(n);
    }

    /** v * 10^n, truncating toward zero when n < 0 (BigInteger.divide truncates). */
    static BigInteger shift(BigInteger v, int n) {
        if (n >= 0) {
            return n == 0 ? v : v.multiply(pow10(n));
        }
        return v.divide(pow10(-n));
    }

    /** Remainder with the sign of the dividend. */
    static BigInteger trem(BigInteger a, BigInteger b) {
        return a.subtract(b.multiply(a.divide(b)));
    }

    static final BigInteger TWO64 = BigInteger.ONE.shiftLeft(64);

    /** The unsigned 64-bit value of a long bit pattern. */
    static BigInteger unsigned(long v) {
        BigInteger b = BigInteger.valueOf(v);
        return v < 0 ? b.add(TWO64) : b;
    }

    /** v mod 2^bits as a two's complement value (signed) or unsigned value, in a long bit pattern. */
    static long wrap(BigInteger v, int bytes, boolean signed) {
        int bits = 8 * bytes;
        BigInteger m = v.mod(BigInteger.ONE.shiftLeft(bits));
        if (signed && m.testBit(bits - 1)) {
            m = m.subtract(BigInteger.ONE.shiftLeft(bits));
        }
        return m.longValue();
    }
}
