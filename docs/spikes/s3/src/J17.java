// Toy 8: Java 17 language features an LLM is likely to emit (var, switch expressions,
// records, text blocks are not used in logic). Checks that ESC copes at -source 17.
public class J17 {

    public record Money(long cents) {}

    //@ requires 0 <= code && code <= 9;
    //@ ensures (code == 1 || code == 2) ==> \result == 100;
    //@ ensures code == 3 ==> \result == 200;
    //@ ensures !(code == 1 || code == 2 || code == 3) ==> \result == 0;
    public static int rate(int code) {
        var r = switch (code) {
            case 1, 2 -> 100;
            case 3 -> 200;
            default -> 0;
        };
        return r;
    }

    //@ requires m != null;
    //@ requires 0 <= m.cents() && m.cents() <= 1_000_000;
    //@ ensures \result == m.cents() * 2;
    public static long doubleIt(Money m) {
        return m.cents() * 2;
    }

    // Vacuity: contradictory precondition (would "verify" anything).
    //@ requires a > 0 && a < 0;
    //@ ensures \result == 42;
    public static long vacuous(long a) {
        return a;
    }
}
