// Toy 3: COBOL 88-level conditions as named predicates.
//   05 WS-STATUS PIC X.
//      88 STATUS-OK  VALUE 'A' 'B'.
//      88 STATUS-END VALUE 'Z'.
//   IF IN-CODE = 'A' OR 'B' MOVE IN-CODE TO WS-STATUS ELSE SET STATUS-END TO TRUE.
// Several ways of naming the 88-level predicate are tried, one per method.
public class Status {
    public char status; //@ in isOk;

    // (a) spec-only model method WITH BODY ONLY (no ensures): body is NOT unfolded by ESC.
    /*@ public static model pure boolean okBodyOnly(char s) { return s == 'A' || s == 'B'; } @*/

    // (b) spec-only model method with an explicit postcondition: usable by ESC.
    /*@ public normal_behavior
      @   ensures \result == (s == 'A' || s == 'B');
      @ public static model pure boolean statusOk88(char s);
      @*/
    /*@ public normal_behavior
      @   ensures \result == (s == 'Z');
      @ public static model pure boolean statusEnd88(char s);
      @*/

    // (c) model field with represents clause (needs "//@ in isOk;" on the field).
    //@ public model boolean isOk;
    //@ public represents isOk = (status == 'A' || status == 'B');

    // (d) a pure Java helper (e.g. if the generated Java already has one).
    //@ ensures \result == (c == 'A' || c == 'B');
    public static /*@ pure @*/ boolean isOkCode(char c) { return c == 'A' || c == 'B'; }

    // uses (a) -- expected: cannot be proved although the code is right
    //@ assignable status;
    //@ ensures okBodyOnly(in) ==> status == in;
    public void setStatusA(char in) {
        if (in == 'A' || in == 'B') status = in; else status = 'Z';
    }

    // uses (b)
    //@ assignable status;
    //@ ensures statusOk88(in) ==> status == in;
    //@ ensures !statusOk88(in) ==> statusEnd88(status);
    public void setStatusB(char in) {
        if (in == 'A' || in == 'B') status = in; else status = 'Z';
    }

    // uses (c)
    //@ assignable status;
    //@ ensures isOk <==> (in == 'A' || in == 'B');
    public void setStatusC(char in) {
        if (in == 'A' || in == 'B') status = in; else status = 'Z';
    }

    // uses (d) in both code and spec
    //@ assignable status;
    //@ ensures isOkCode(in) ==> status == in;
    //@ ensures !isOkCode(in) ==> status == 'Z';
    public void setStatusD(char in) {
        if (isOkCode(in)) status = in; else status = 'Z';
    }

    // BUGGY: forgets the second VALUE of the 88 level ('B').
    //@ assignable status;
    //@ ensures statusOk88(in) ==> status == in;
    //@ ensures !statusOk88(in) ==> statusEnd88(status);
    public void setStatusBuggy(char in) {
        if (in == 'A') status = in; else status = 'Z';
    }
}
