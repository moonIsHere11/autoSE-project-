package s2;

/** "LLM" translation #1: correct, but written differently (plain scaled longs, inline logic). */
public final class LlmGood {
    public long wsA;   // S9(5)V99, hundredths
    public long wsB;   // S9(5)V99, hundredths
    public long wsC;   // S9(5)V9,  tenths
    public long wsD;   // 9(4)V99,  hundredths, unsigned

    public void calcTotal() {
        long sum = wsA + wsB;                       // hundredths
        boolean neg = sum < 0;
        long mag = neg ? -sum : sum;
        long tenths = (mag + 5) / 10;               // half away from zero on the magnitude
        tenths = tenths % 1_000_000L;               // keep 6 digits
        wsC = neg ? -tenths : tenths;

        long diff = wsA - wsB;
        if (diff < 0) {
            diff = -diff;                           // unsigned receiver
        }
        wsD = diff % 1_000_000L;
    }
}
