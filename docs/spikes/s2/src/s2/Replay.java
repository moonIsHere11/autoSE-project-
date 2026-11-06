package s2;

/**
 * Concrete replay of a JBMC counterexample with plain `java` (no CProver on the path).
 * Usage: java -cp build s2.Replay <Good|Bug|BugTrunc> <wsA> <wsB> <wsC> <wsD>   (unscaled longs)
 * Exit code 0 = all fields equal, 1 = mismatch reproduced.
 */
public final class Replay {
    public static void main(String[] args) {
        String which = args[0];
        long a = Long.parseLong(args[1]), b = Long.parseLong(args[2]);
        long c = Long.parseLong(args[3]), d = Long.parseLong(args[4]);

        RefUnit r = new RefUnit();
        r.wsA.unscaled = a; r.wsB.unscaled = b; r.wsC.unscaled = c; r.wsD.unscaled = d;
        r.calcTotal();

        long[] got;
        if (which.equals("Good")) {
            LlmGood l = new LlmGood(); l.wsA = a; l.wsB = b; l.wsC = c; l.wsD = d; l.calcTotal();
            got = new long[] {l.wsA, l.wsB, l.wsC, l.wsD};
        } else if (which.equals("Bug")) {
            LlmBug l = new LlmBug(); l.wsA = a; l.wsB = b; l.wsC = c; l.wsD = d; l.calcTotal();
            got = new long[] {l.wsA, l.wsB, l.wsC, l.wsD};
        } else {
            LlmBugTrunc l = new LlmBugTrunc(); l.wsA = a; l.wsB = b; l.wsC = c; l.wsD = d; l.calcTotal();
            got = new long[] {l.wsA, l.wsB, l.wsC, l.wsD};
        }
        long[] want = {r.wsA.unscaled, r.wsB.unscaled, r.wsC.unscaled, r.wsD.unscaled};
        String[] names = {"WS-A", "WS-B", "WS-C", "WS-D"};
        boolean same = true;
        for (int k = 0; k < 4; k++) {
            String flag = want[k] == got[k] ? "ok" : "MISMATCH";
            if (want[k] != got[k]) same = false;
            System.out.println(names[k] + ": reference=" + want[k] + " candidate=" + got[k] + "  " + flag);
        }
        System.exit(same ? 0 : 1);
    }
}
