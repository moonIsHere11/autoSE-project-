// Toy 9: generated Java usually calls helpers (or the cobolrt runtime). ESC is modular:
// it uses the CALLEE'S CONTRACT, not its body.
public class Calls {

    // helper with no JML spec
    static long trunc5NoSpec(long x) { return x % 100_000; }

    // same helper with a spec
    //@ requires -1_000_000_000L <= x && x <= 1_000_000_000L;
    //@ ensures \result == x % 100_000;
    static /*@ pure @*/ long trunc5Spec(long x) { return x % 100_000; }

    // helper marked 'inline' (OpenJML extension) -- body substituted at call site?
    /*@ inline @*/ static long trunc5Inline(long x) { return x % 100_000; }

    //@ requires 0 <= a && a < 100_000 && 0 <= b && b < 100_000;
    //@ ensures \result == (a + b) % 100_000;
    public static long addViaNoSpec(long a, long b) { return trunc5NoSpec(a + b); }

    //@ requires 0 <= a && a < 100_000 && 0 <= b && b < 100_000;
    //@ ensures \result == (a + b) % 100_000;
    public static long addViaSpec(long a, long b) { return trunc5Spec(a + b); }

    //@ requires 0 <= a && a < 100_000 && 0 <= b && b < 100_000;
    //@ ensures \result == (a + b) % 100_000;
    public static long addViaInline(long a, long b) { return trunc5Inline(a + b); }
}
