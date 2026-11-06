// Toy 4b: invariant that is false on loop entry; and a loop-free postcondition next to an
// un-annotated loop.
public class LoopEntry {
    //@ requires 0 <= n && n <= 10_000;
    //@ ensures \result == 5L * n;
    public static long fiveTimesBadEntry(int n) {
        long s = 0;
        //@ loop_invariant 0 <= i && i <= n && s == 5L * i + 1;
        //@ decreases n - i;
        for (int i = 0; i < n; i++) {
            s += 5;
        }
        return s;
    }

    // Postcondition does not depend on the loop; loop has no invariant.
    //@ requires 0 <= n && n <= 10_000;
    //@ ensures \result == n;
    public static int countNoInv(int n) {
        int k = 0;
        for (int i = 0; i < n; i++) {
            k++;
        }
        return n;
    }
}
