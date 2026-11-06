package s2;

import org.cprover.CProver;

/** Probes for JBMC's default checks and for String / char[] (PIC X) support. */
public final class Gotchas {

    // ---------------------------------------------------------------- implicit exceptions
    /** Entry with primitive params: JBMC makes them nondet. Divisor may be 0. */
    public static long divZero(long x, long y) {
        return x / y;
    }

    /** Index may be out of bounds. */
    public static long arrIdx(int i) {
        long[] t = new long[5];
        return t[i];
    }

    /** Reference-typed entry parameter: may be null unless --java-assume-inputs-non-null. */
    public static long nullIn(Dec d) {
        return d.unscaled;
    }

    /** Explicit throw of a runtime exception, never caught. */
    public static void explicitThrow(int x) {
        if (x == 42) {
            throw new IllegalStateException("boom");
        }
    }

    /** A JDK library call (java.lang.Math) -- is it modelled or stubbed? */
    public static void mathAbs() {
        long v = CProver.nondetLong();
        CProver.assume(v > -1000 && v < 1000);
        long m = Math.abs(v);
        assert m >= 0 && m < 1000 : "abs in range";
    }

    // ---------------------------------------------------------------- PIC X
    //   01 WS-IN  PIC X(5).   01 WS-OUT PIC X(8).   MOVE WS-IN TO WS-OUT.  (left-justify, pad)
    static char[] nondetPicX(int len) {
        char[] c = new char[len];
        for (int k = 0; k < len; k++) {
            char ch = CProver.nondetChar();
            CProver.assume(ch >= ' ' && ch <= '~');
            c[k] = ch;
        }
        return c;
    }

    static char[] refMove(char[] in, int outLen) {
        char[] out = new char[outLen];
        for (int k = 0; k < outLen; k++) {
            out[k] = k < in.length ? in[k] : ' ';
        }
        return out;
    }

    /** Candidate uses only char[] (no String). */
    public static void picXCharArray() {
        char[] in = nondetPicX(5);
        char[] ref = refMove(in, 8);
        char[] llm = new char[8];
        for (int k = 0; k < 8; k++) {
            llm[k] = ' ';
        }
        System.arraycopy(in, 0, llm, 0, 5);
        for (int k = 0; k < 8; k++) {
            assert ref[k] == llm[k] : "EQ WS-OUT";
        }
    }

    /** Candidate uses only char[] with an explicit copy loop (no System.arraycopy). */
    public static void picXCharArrayLoop() {
        char[] in = nondetPicX(5);
        char[] ref = refMove(in, 8);
        char[] llm = new char[8];
        for (int k = 0; k < 8; k++) {
            llm[k] = k < 5 ? in[k] : ' ';
        }
        for (int k = 0; k < 8; k++) {
            assert ref[k] == llm[k] : "EQ WS-OUT";
        }
    }

    /** Same, but buggy (pads with '0' instead of space). */
    public static void picXCharArrayLoopBug() {
        char[] in = nondetPicX(5);
        char[] ref = refMove(in, 8);
        char[] llm = new char[8];
        for (int k = 0; k < 8; k++) {
            llm[k] = k < 5 ? in[k] : '0';
        }
        for (int k = 0; k < 8; k++) {
            assert ref[k] == llm[k] : "EQ WS-OUT";
        }
    }

    /** Candidate uses String + concatenation + substring (invokedynamic on --release >= 9). */
    public static void picXStringConcat() {
        char[] in = nondetPicX(5);
        char[] ref = refMove(in, 8);
        String s = new String(in);
        String llm = (s + "        ").substring(0, 8);
        assert llm.length() == 8 : "LEN WS-OUT";
        for (int k = 0; k < 8; k++) {
            assert ref[k] == llm.charAt(k) : "EQ WS-OUT";
        }
    }

    /** Candidate uses StringBuilder explicitly (no invokedynamic at any release). */
    public static void picXStringBuilder() {
        char[] in = nondetPicX(5);
        char[] ref = refMove(in, 8);
        StringBuilder sb = new StringBuilder(new String(in));
        while (sb.length() < 8) {
            sb.append(' ');
        }
        String llm = sb.toString();
        assert llm.length() == 8 : "LEN WS-OUT";
        for (int k = 0; k < 8; k++) {
            assert ref[k] == llm.charAt(k) : "EQ WS-OUT";
        }
    }

    /** Buggy String candidate: right-justifies instead of left-justifying. */
    public static void picXStringBug() {
        char[] in = nondetPicX(5);
        char[] ref = refMove(in, 8);
        StringBuilder sb = new StringBuilder();
        sb.append("   ");
        sb.append(in);
        String llm = sb.toString();
        for (int k = 0; k < 8; k++) {
            assert ref[k] == llm.charAt(k) : "EQ WS-OUT";
        }
    }

    // ---------------------------------------------------------------- BigDecimal candidate
    /** What happens if the LLM uses java.math.BigDecimal (no JBMC model)? */
    public static void bigDecimalCandidate() {
        long in_wsA = Harness.pic(7, true);
        long in_wsB = Harness.pic(7, true);
        RefUnit r = Harness.ref(in_wsA, in_wsB, 0, 0);
        r.calcTotal();
        java.math.BigDecimal s = java.math.BigDecimal.valueOf(in_wsA, 2)
            .add(java.math.BigDecimal.valueOf(in_wsB, 2))
            .setScale(1, java.math.RoundingMode.HALF_UP);
        long c = s.unscaledValue().longValue() % 1_000_000L;
        assert r.wsC.unscaled == c : "EQ WS-C";
    }
}
