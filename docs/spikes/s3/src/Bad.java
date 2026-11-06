// Toy 7: tool-error cases. JML syntax error in a contract.
public class Bad {
    //@ ensures \result == a +;
    public static long id(long a) { return a; }
}
