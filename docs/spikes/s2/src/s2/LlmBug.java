package s2;

/** "LLM" translation #2: buggy -- ROUNDED implemented as truncation. */
public final class LlmBug {
    public long wsA;
    public long wsB;
    public long wsC;
    public long wsD;

    public void calcTotal() {
        long sum = wsA + wsB;
        wsC = (sum / 10) % 1_000_000L;              // BUG: truncates instead of rounding
        long diff = wsA - wsB;
        if (diff < 0) {
            diff = -diff;
        }
        wsD = diff % 1_000_000L;
    }
}
