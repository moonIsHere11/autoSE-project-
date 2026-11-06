// Toy 4: PERFORM VARYING I FROM 1 BY 1 UNTIL I > N  ADD I TO TOTAL.
public class Loops {

    // With invariant + variant: should verify.
    //@ requires 0 <= n && n <= 10_000;
    //@ ensures \result == (long) n * (n + 1) / 2;
    public static long sumTo(int n) {
        long s = 0;
        //@ maintaining 1 <= i && i <= n + 1;
        //@ maintaining s == (long)(i - 1) * i / 2;
        //@ decreases n - i + 1;
        for (int i = 1; i <= n; i++) {
            s += i;
        }
        return s;
    }

    // Same code, NO invariant: OpenJML cannot prove the postcondition.
    //@ requires 0 <= n && n <= 10_000;
    //@ ensures \result == (long) n * (n + 1) / 2;
    public static long sumToNoInv(int n) {
        long s = 0;
        for (int i = 1; i <= n; i++) {
            s += i;
        }
        return s;
    }

    // Wrong (non-inductive) invariant.
    //@ requires 0 <= n && n <= 10_000;
    //@ ensures \result == (long) n * (n + 1) / 2;
    public static long sumToBadInv(int n) {
        long s = 0;
        //@ maintaining 1 <= i && i <= n + 1;
        //@ maintaining s == (long) i * i / 2;
        //@ decreases n - i + 1;
        for (int i = 1; i <= n; i++) {
            s += i;
        }
        return s;
    }

    // Wrong variant (does not decrease).
    //@ requires 0 <= n && n <= 10_000;
    //@ ensures \result == (long) n * (n + 1) / 2;
    public static long sumToBadVariant(int n) {
        long s = 0;
        //@ maintaining 1 <= i && i <= n + 1;
        //@ maintaining s == (long)(i - 1) * i / 2;
        //@ decreases i;
        for (int i = 1; i <= n; i++) {
            s += i;
        }
        return s;
    }

    // Linear loop (constant step), no invariant -> also fails; with invariant -> verifies.
    //@ requires 0 <= n && n <= 10_000;
    //@ ensures \result == 5L * n;
    public static long fiveTimes(int n) {
        long s = 0;
        //@ loop_invariant 0 <= i && i <= n && s == 5L * i;
        //@ decreases n - i;
        for (int i = 0; i < n; i++) {
            s += 5;
        }
        return s;
    }
}
