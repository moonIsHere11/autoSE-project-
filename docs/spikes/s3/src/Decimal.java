// Toy 1: long-backed COBOL decimal helpers.
// COBOL: 01 X PIC S9(5).  ADD A TO B GIVING X  -> high-order digits are truncated,
// sign is kept. For |a|,|b| < 10^5 that is exactly Java's remainder (truncates toward 0).
public class Decimal {

    // Generic version: modulus is a parameter (10^digits). Non-linear for the solver.
    //@ requires 1 <= mod && mod <= 1_000_000_000_000_000_000L;
    //@ requires -mod < a && a < mod && -mod < b && b < mod;
    //@ ensures \result == (a + b) % mod;
    //@ ensures -mod < \result && \result < mod;
    public static long addTrunc(long a, long b, long mod) {
        return (a + b) % mod;
    }

    // Fixed-width version, as T3 would emit it for a PIC S9(5) target:
    // the postcondition states the COBOL semantics independently of '%':
    // result has the sign of the sum and |result| = |sum| mod 10^5.
    //@ requires -100_000 < a && a < 100_000 && -100_000 < b && b < 100_000;
    //@ ensures -100_000 < \result && \result < 100_000;
    //@ ensures (a + b >= 0) ==> (\result >= 0 && (\result == a + b || \result == a + b - 100_000));
    //@ ensures (a + b <  0) ==> (\result <= 0 && (\result == a + b || \result == a + b + 100_000));
    public static long addTrunc5(long a, long b) {
        long s = a + b;
        if (s >= 100_000) s -= 100_000;
        else if (s <= -100_000) s += 100_000;
        return s;
    }

    // BUGGY: LLM "forgot" negative overflow (S9(5) treated like 9(5)).
    //@ requires -100_000 < a && a < 100_000 && -100_000 < b && b < 100_000;
    //@ ensures -100_000 < \result && \result < 100_000;
    //@ ensures (a + b >= 0) ==> (\result >= 0 && (\result == a + b || \result == a + b - 100_000));
    //@ ensures (a + b <  0) ==> (\result <= 0 && (\result == a + b || \result == a + b + 100_000));
    public static long addTrunc5Buggy(long a, long b) {
        long s = a + b;
        if (s >= 100_000) s -= 100_000;
        return s;
    }

    // BUGGY generic: unsigned-style truncation (Math.floorMod) instead of COBOL's sign-keeping one.
    //@ requires 1 <= mod && mod <= 1_000_000_000_000_000_000L;
    //@ requires -mod < a && a < mod && -mod < b && b < mod;
    //@ ensures \result == (a + b) % mod;
    public static long addTruncBuggy(long a, long b, long mod) {
        long r = (a + b) % mod;
        if (r < 0) r += mod;
        return r;
    }
}
