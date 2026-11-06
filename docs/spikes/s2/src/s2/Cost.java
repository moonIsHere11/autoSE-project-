package s2;

import org.cprover.CProver;

/** Cost probes: reference (Dec) vs an "LLM-style" inline translation, asserted equal. */
public final class Cost {

    // ---------------------------------------------------------------- (b) multiply + rescale
    //   01 WS-A PIC S9(5)V99.   01 WS-R PIC 9V9(4).   01 WS-P PIC S9(5)V99.
    //   COMPUTE WS-P ROUNDED = WS-A * WS-R.
    public static void mulRescale() {
        long in_wsA = Harness.pic(7, true);
        long in_wsR = Harness.pic(5, false);
        Dec a = new Dec(7, 2, true);  a.unscaled = in_wsA;
        Dec r = new Dec(5, 4, false); r.unscaled = in_wsR;
        Dec p = new Dec(7, 2, true);
        Dec.multiply(a, r, p, true);

        long prod = in_wsA * in_wsR;                 // scale 6
        long mag = prod < 0 ? -prod : prod;
        long q = ((mag + 5_000) / 10_000) % 10_000_000L;
        long llm = prod < 0 ? -q : q;
        assert p.unscaled == llm : "EQ WS-P";
    }

    /** Same, candidate truncates instead of rounding (expect a counterexample). */
    public static void mulRescaleBug() {
        long in_wsA = Harness.pic(7, true);
        long in_wsR = Harness.pic(5, false);
        Dec a = new Dec(7, 2, true);  a.unscaled = in_wsA;
        Dec r = new Dec(5, 4, false); r.unscaled = in_wsR;
        Dec p = new Dec(7, 2, true);
        Dec.multiply(a, r, p, true);

        long llm = (in_wsA * in_wsR / 10_000) % 10_000_000L;   // BUG: no rounding
        assert p.unscaled == llm : "EQ WS-P";
    }

    // ---------------------------------------------------------------- (b') general division
    //   01 WS-A PIC S9(5)V99.  01 WS-B PIC S9(3)V99.  01 WS-Q PIC S9(5)V99.
    //   COMPUTE WS-Q ROUNDED = WS-A / WS-B.   (WS-B /= 0)
    public static void divRounded() {
        long in_wsA = Harness.pic(7, true);
        long in_wsB = Harness.pic(5, true);
        CProver.assume(in_wsB != 0);
        Dec a = new Dec(7, 2, true); a.unscaled = in_wsA;
        Dec b = new Dec(5, 2, true); b.unscaled = in_wsB;
        Dec q = new Dec(7, 2, true);
        Dec.divide(a, b, q, true);

        long num = in_wsA * 100;                     // a/b at scale 2 = a*100/b
        long t = num / in_wsB;
        long rem = num % in_wsB;
        long ar = rem < 0 ? -rem : rem;
        long ab = in_wsB < 0 ? -in_wsB : in_wsB;
        if (2 * ar >= ab) {
            t += ((num < 0) != (in_wsB < 0)) ? -1 : 1;
        }
        long llm = t % 10_000_000L;
        assert q.unscaled == llm : "EQ WS-Q";
    }

    // ---------------------------------------------------------------- (c) OCCURS loop
    //   01 WS-TAB.  05 WS-AMT PIC S9(5)V99 OCCURS N TIMES.
    //   01 WS-TOTAL PIC S9(7)V99.   01 WS-I PIC 9(2).
    //   SUM-AMTS.  MOVE 0 TO WS-TOTAL
    //              PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > N
    //                  ADD WS-AMT(WS-I) TO WS-TOTAL
    //              END-PERFORM.
    static void loopSum(int n) {
        long[] refAmt = new long[n];
        long[] llmAmt = new long[n];
        for (int k = 0; k < n; k++) {
            long v = Harness.pic(7, true);
            refAmt[k] = v;
            llmAmt[k] = v;
        }
        // reference: per-iteration COBOL store into WS-TOTAL (truncation each ADD)
        Dec total = new Dec(9, 2, true);
        Dec amt = new Dec(7, 2, true);
        total.unscaled = 0;
        int refI;
        for (refI = 1; refI <= n; refI++) {
            amt.unscaled = refAmt[refI - 1];
            Dec.add(amt, total, total, false);
        }
        // candidate: plain sum, truncation once at the end
        long sum = 0;
        int llmI;
        for (llmI = 1; llmI <= n; llmI++) {
            sum += llmAmt[llmI - 1];
        }
        long llmTotal = sum % 1_000_000_000L;
        assert total.unscaled == llmTotal : "EQ WS-TOTAL";
        assert refI == llmI : "EQ WS-I";
    }

    public static void loopSum5() { loopSum(5); }
    public static void loopSum10() { loopSum(10); }
}
