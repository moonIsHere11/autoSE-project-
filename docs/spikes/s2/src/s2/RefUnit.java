package s2;

/**
 * Trusted reference translation of the toy COBOL paragraph
 *
 *   01 WS-A  PIC S9(5)V99.
 *   01 WS-B  PIC S9(5)V99.
 *   01 WS-C  PIC S9(5)V9.
 *   01 WS-D  PIC 9(4)V99.
 *   CALC-TOTAL.
 *       ADD WS-A TO WS-B GIVING WS-C ROUNDED.
 *       SUBTRACT WS-B FROM WS-A GIVING WS-D.
 */
public final class RefUnit {
    public final Dec wsA = new Dec(7, 2, true);
    public final Dec wsB = new Dec(7, 2, true);
    public final Dec wsC = new Dec(6, 1, true);
    public final Dec wsD = new Dec(6, 2, false);

    public void calcTotal() {
        Dec.add(wsA, wsB, wsC, true);
        Dec.subtract(wsB, wsA, wsD, false);
    }
}
