package s2;

import org.cprover.CProver;

/**
 * T2b equivalence harnesses for CALC-TOTAL. Each public static void method is one JBMC entry
 * point (selected with --function s2.Harness.<name>).
 *
 * Pattern: nondet inputs (one local per COBOL field, named in_<field>) -> assume PIC domain ->
 * identical state into reference and candidate -> run both -> assert every field equal.
 */
public final class Harness {

    /** Nondet unscaled value in the domain of a PIC with {@code digits} digits. */
    static long pic(int digits, boolean signed) {
        long v = CProver.nondetLong();
        long lim = Dec.pow10(digits);
        CProver.assume(v < lim);
        CProver.assume(signed ? v > -lim : v >= 0);
        return v;
    }

    static RefUnit ref(long a, long b, long c, long d) {
        RefUnit r = new RefUnit();
        r.wsA.unscaled = a;
        r.wsB.unscaled = b;
        r.wsC.unscaled = c;
        r.wsD.unscaled = d;
        return r;
    }

    // ---------------------------------------------------------------- equivalence checks

    public static void checkGood() {
        long in_wsA = pic(7, true);
        long in_wsB = pic(7, true);
        long in_wsC = pic(6, true);
        long in_wsD = pic(6, false);
        RefUnit r = ref(in_wsA, in_wsB, in_wsC, in_wsD);
        LlmGood l = new LlmGood();
        l.wsA = in_wsA; l.wsB = in_wsB; l.wsC = in_wsC; l.wsD = in_wsD;
        r.calcTotal();
        l.calcTotal();
        assert r.wsA.unscaled == l.wsA : "EQ WS-A";
        assert r.wsB.unscaled == l.wsB : "EQ WS-B";
        assert r.wsC.unscaled == l.wsC : "EQ WS-C";
        assert r.wsD.unscaled == l.wsD : "EQ WS-D";
    }

    public static void checkBug() {
        long in_wsA = pic(7, true);
        long in_wsB = pic(7, true);
        long in_wsC = pic(6, true);
        long in_wsD = pic(6, false);
        RefUnit r = ref(in_wsA, in_wsB, in_wsC, in_wsD);
        LlmBug l = new LlmBug();
        l.wsA = in_wsA; l.wsB = in_wsB; l.wsC = in_wsC; l.wsD = in_wsD;
        r.calcTotal();
        l.calcTotal();
        assert r.wsA.unscaled == l.wsA : "EQ WS-A";
        assert r.wsB.unscaled == l.wsB : "EQ WS-B";
        assert r.wsC.unscaled == l.wsC : "EQ WS-C";
        assert r.wsD.unscaled == l.wsD : "EQ WS-D";
    }

    public static void checkBugTrunc() {
        long in_wsA = pic(7, true);
        long in_wsB = pic(7, true);
        long in_wsC = pic(6, true);
        long in_wsD = pic(6, false);
        RefUnit r = ref(in_wsA, in_wsB, in_wsC, in_wsD);
        LlmBugTrunc l = new LlmBugTrunc();
        l.wsA = in_wsA; l.wsB = in_wsB; l.wsC = in_wsC; l.wsD = in_wsD;
        r.calcTotal();
        l.calcTotal();
        assert r.wsA.unscaled == l.wsA : "EQ WS-A";
        assert r.wsB.unscaled == l.wsB : "EQ WS-B";
        assert r.wsC.unscaled == l.wsC : "EQ WS-C";
        assert r.wsD.unscaled == l.wsD : "EQ WS-D";
    }

    // ---------------------------------------------------------------- vacuity

    /** Reachability probe: must be reported FAILURE (the end of the harness is reachable). */
    public static void reachGood() {
        long in_wsA = pic(7, true);
        long in_wsB = pic(7, true);
        long in_wsC = pic(6, true);
        long in_wsD = pic(6, false);
        RefUnit r = ref(in_wsA, in_wsB, in_wsC, in_wsD);
        LlmGood l = new LlmGood();
        l.wsA = in_wsA; l.wsB = in_wsB; l.wsC = in_wsC; l.wsD = in_wsD;
        r.calcTotal();
        l.calcTotal();
        assert false : "REACH";
    }

    /** Contradictory assumptions + BUGGY candidate: equivalence "passes" vacuously. */
    public static void contradictoryBug() {
        long in_wsA = pic(7, true);
        CProver.assume(in_wsA > 5);
        CProver.assume(in_wsA < 3);           // contradiction
        long in_wsB = pic(7, true);
        RefUnit r = ref(in_wsA, in_wsB, 0, 0);
        LlmBug l = new LlmBug();
        l.wsA = in_wsA; l.wsB = in_wsB;
        r.calcTotal();
        l.calcTotal();
        assert r.wsC.unscaled == l.wsC : "EQ WS-C";
        assert r.wsD.unscaled == l.wsD : "EQ WS-D";
    }

    /** Same contradictory harness, with the reachability probe: SUCCESS here means VACUOUS. */
    public static void contradictoryReach() {
        long in_wsA = pic(7, true);
        CProver.assume(in_wsA > 5);
        CProver.assume(in_wsA < 3);
        long in_wsB = pic(7, true);
        RefUnit r = ref(in_wsA, in_wsB, 0, 0);
        LlmBug l = new LlmBug();
        l.wsA = in_wsA; l.wsB = in_wsB;
        r.calcTotal();
        l.calcTotal();
        assert false : "REACH";
    }
}
