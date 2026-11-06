// Toy 5: a non-linear goal intended to make the solver time out / give up.
public class Hard {
    //@ requires 2 <= a && a <= 1_000_000 && 2 <= b && b <= 1_000_000 && 2 <= c && c <= 1_000_000;
    //@ ensures \result;
    public static boolean fermat3(long a, long b, long c) {
        return a * a * a + b * b * b != c * c * c;
    }
}
