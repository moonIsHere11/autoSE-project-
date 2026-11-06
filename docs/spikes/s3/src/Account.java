// Toy 2: instance method mutating fields, with a frame (assignable) clause.
// COBOL working-storage: WS-BALANCE, WS-COUNT, WS-AUDIT.
public class Account {
    public long balance;
    public long count;
    public long audit;

    //@ requires 0 <= amt && amt <= 1_000_000;
    //@ requires 0 <= balance && balance <= 1_000_000_000L;
    //@ requires 0 <= count && count < 1_000_000;
    //@ assignable balance, count;
    //@ ensures balance == \old(balance) + amt;
    //@ ensures count == \old(count) + 1;
    public void deposit(long amt) {
        balance += amt;
        count++;
    }

    // BUGGY: also writes 'audit', which is not in the frame.
    //@ requires 0 <= amt && amt <= 1_000_000;
    //@ requires 0 <= balance && balance <= 1_000_000_000L;
    //@ requires 0 <= count && count < 1_000_000;
    //@ assignable balance, count;
    //@ ensures balance == \old(balance) + amt;
    //@ ensures count == \old(count) + 1;
    public void depositBad(long amt) {
        balance += amt;
        count++;
        audit = amt;
    }
}
