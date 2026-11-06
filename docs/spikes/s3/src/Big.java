import java.math.BigDecimal;
import java.math.RoundingMode;

// Toy 6: does OpenJML ESC reason about java.math.BigDecimal at all?
public class Big {

    // trivially true: returns what the spec says
    //@ requires a != null && b != null;
    //@ ensures \result != null;
    public static BigDecimal add(BigDecimal a, BigDecimal b) {
        return a.add(b);
    }

    // value-level property: a + 0 == a (compareTo-based)
    //@ requires a != null;
    //@ ensures \result.compareTo(a) == 0;
    public static BigDecimal addZero(BigDecimal a) {
        return a.add(BigDecimal.ZERO);
    }

    // commutativity of add
    //@ requires a != null && b != null;
    //@ ensures \result.equals(b.add(a));
    public static BigDecimal addComm(BigDecimal a, BigDecimal b) {
        return a.add(b);
    }

    // COBOL-ish: ADD with scale 2, ROUNDED. Spec relates to long cents.
    //@ requires a != null;
    //@ ensures \result != null && \result.scale() == 2;
    public static BigDecimal round2(BigDecimal a) {
        return a.setScale(2, RoundingMode.HALF_UP);
    }

    // BUGGY: wrong value; ESC should complain (if it understands BigDecimal values).
    //@ requires a != null && b != null;
    //@ ensures \result.equals(a.add(b));
    public static BigDecimal addBuggy(BigDecimal a, BigDecimal b) {
        return a.subtract(b);
    }
}
