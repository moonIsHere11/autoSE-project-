package s2;

/** "LLM" translation #3: buggy -- forgets COBOL high-order truncation of WS-D (9(4)V99). */
public final class LlmBugTrunc {
    public long wsA;
    public long wsB;
    public long wsC;
    public long wsD;

    public void calcTotal() {
        long sum = wsA + wsB;
        boolean neg = sum < 0;
        long mag = neg ? -sum : sum;
        long tenths = ((mag + 5) / 10) % 1_000_000L;
        wsC = neg ? -tenths : tenths;
        long diff = wsA - wsB;
        wsD = diff < 0 ? -diff : diff;              // BUG: no "% 10^6" -> overflows PIC 9(4)V99
    }
}
