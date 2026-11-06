       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCTPOST.
      *----------------------------------------------------------------
      * Account posting.  Reads TRANS.DAT (fixed-length SEQUENTIAL,
      * 20-byte records: COMP account, type, COMP-3 amount, SIGN
      * TRAILING SEPARATE rate, overpunched zoned sequence number and
      * a signed COMP branch), posts them to ten accounts (account
      * number mod 10) and writes STATEMENT.TXT (LINE SEQUENTIAL) with
      * one line per transaction plus one per account.
      * Types: D deposit, W withdrawal (overdraft limit 500.00),
      * I interest (balance x rate, may be negative), F fee (max 25.00).
      * A negative sequence number marks a reversal (amount negated).
      * Targets: binary / packed / zoned / sign-separate input
      * decoding, DIVIDE ... REMAINDER for the table slot, OCCURS with
      * INITIALIZE and PERFORM VARYING, 88-levels, EVALUATE TRUE,
      * ROUNDED, ON SIZE ERROR, floating-minus edited output,
      * RETURN-CODE 0 / 4 / 8.
      *----------------------------------------------------------------
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TRANS-FILE ASSIGN TO "TRANS.DAT"
               ORGANIZATION IS SEQUENTIAL.
           SELECT STMT-FILE ASSIGN TO "STATEMENT.TXT"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD TRANS-FILE.
       01 TR-REC.
          05 TR-ACCT            PIC 9(4) COMP.
          05 TR-TYPE            PIC X.
             88 TR-DEPOSIT      VALUE "D".
             88 TR-WITHDRAW     VALUE "W".
             88 TR-INTEREST     VALUE "I".
             88 TR-FEE          VALUE "F".
          05 TR-AMOUNT          PIC S9(7)V99 COMP-3.
          05 TR-RATE            PIC SV9(4) SIGN TRAILING SEPARATE.
          05 TR-SEQ             PIC S9(5).
          05 TR-BRANCH          PIC S9(3) COMP.
       FD STMT-FILE.
       01 STMT-REC              PIC X(60).
       WORKING-STORAGE SECTION.
       01 WS-EOF                PIC X VALUE "N".
       01 WS-ACCOUNTS.
          05 WS-ACCOUNT         OCCURS 10 TIMES.
             10 AC-OPEN         PIC S9(7)V99 COMP-3.
             10 AC-BALANCE      PIC S9(7)V99 COMP-3.
             10 AC-COUNT        PIC 9(3) COMP.
       01 WS-SLOT               PIC 9(2).
       01 WS-QUOT               PIC 9(4).
       01 WS-REM                PIC 9.
       01 WS-AMOUNT             PIC S9(7)V99.
       01 WS-RATE               PIC SV9(4).
       01 WS-INTEREST           PIC S9(7)V99.
       01 WS-NEW-BAL            PIC S9(8)V99.
       01 WS-STATUS             PIC X(8).
          88 STATUS-POSTED      VALUE "POSTED".
       01 WS-TXN-COUNT          PIC 9(4) VALUE 0.
       01 WS-REJECTS            PIC 9(4) VALUE 0.
       01 WS-OVERFLOWS          PIC 9(4) VALUE 0.
       01 WS-FOREIGN            PIC 9(4) VALUE 0.
       01 WS-AMOUNT-SUM         PIC S9(9)V99 VALUE 0.
       01 WS-TXN-LINE.
          05 TL-SEQ             PIC -(5)9.
          05 FILLER             PIC X VALUE SPACE.
          05 TL-ACCT            PIC 9(4).
          05 FILLER             PIC X VALUE SPACE.
          05 TL-TYPE            PIC X.
          05 FILLER             PIC X VALUE SPACE.
          05 TL-AMOUNT          PIC S9(7)V99 SIGN LEADING SEPARATE.
          05 FILLER             PIC X VALUE SPACE.
          05 TL-BALANCE         PIC S9(7)V99 SIGN TRAILING SEPARATE.
          05 FILLER             PIC X VALUE SPACE.
          05 TL-STATUS          PIC X(8).
       01 WS-ACCT-LINE.
          05 FILLER             PIC X(8) VALUE "ACCOUNT ".
          05 AL-SLOT            PIC 9(2).
          05 FILLER             PIC X(6) VALUE " OPEN ".
          05 AL-OPEN            PIC -(7)9.99.
          05 FILLER             PIC X(7) VALUE " CLOSE ".
          05 AL-CLOSE           PIC -(7)9.99.
          05 FILLER             PIC X(6) VALUE " TXNS ".
          05 AL-COUNT           PIC ZZ9.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT TRANS-FILE
           OPEN OUTPUT STMT-FILE
           PERFORM OPEN-ACCOUNTS
           PERFORM READ-TRANS
           PERFORM UNTIL WS-EOF = "Y"
               PERFORM POST-TRANS
               PERFORM WRITE-TXN-LINE
               PERFORM READ-TRANS
           END-PERFORM
           PERFORM WRITE-ACCOUNTS
           CLOSE TRANS-FILE
           CLOSE STMT-FILE
           DISPLAY "TRANSACTIONS " WS-TXN-COUNT " REJECTED " WS-REJECTS
                   " OVERFLOWS " WS-OVERFLOWS " FOREIGN " WS-FOREIGN
           DISPLAY "AMOUNT SUM " WS-AMOUNT-SUM
           EVALUATE TRUE
               WHEN WS-OVERFLOWS > 0
                   MOVE 8 TO RETURN-CODE
               WHEN WS-REJECTS > 0
                   MOVE 4 TO RETURN-CODE
               WHEN OTHER
                   MOVE 0 TO RETURN-CODE
           END-EVALUATE
           STOP RUN.
       OPEN-ACCOUNTS.
           INITIALIZE WS-ACCOUNTS
           PERFORM VARYING WS-SLOT FROM 1 BY 1 UNTIL WS-SLOT > 10
               COMPUTE AC-OPEN (WS-SLOT) = WS-SLOT * 100 - 300
               MOVE AC-OPEN (WS-SLOT) TO AC-BALANCE (WS-SLOT)
           END-PERFORM.
       READ-TRANS.
           READ TRANS-FILE
               AT END
                   MOVE "Y" TO WS-EOF
               NOT AT END
                   ADD 1 TO WS-TXN-COUNT
                   DIVIDE TR-ACCT BY 10 GIVING WS-QUOT REMAINDER WS-REM
                   COMPUTE WS-SLOT = WS-REM + 1
                   MOVE TR-AMOUNT TO WS-AMOUNT
                   MOVE TR-RATE TO WS-RATE
                   IF TR-SEQ < 0
                       COMPUTE WS-AMOUNT = 0 - WS-AMOUNT
                   END-IF
                   IF TR-BRANCH < 0
                       ADD 1 TO WS-FOREIGN
                   END-IF
           END-READ.
       POST-TRANS.
           MOVE "POSTED" TO WS-STATUS
           EVALUATE TRUE
               WHEN TR-DEPOSIT
                   COMPUTE WS-NEW-BAL = AC-BALANCE (WS-SLOT) + WS-AMOUNT
               WHEN TR-WITHDRAW
                   COMPUTE WS-NEW-BAL = AC-BALANCE (WS-SLOT) - WS-AMOUNT
                   IF WS-NEW-BAL < -500
                       MOVE "NSF" TO WS-STATUS
                   END-IF
               WHEN TR-INTEREST
                   COMPUTE WS-INTEREST ROUNDED =
                           AC-BALANCE (WS-SLOT) * WS-RATE
                   MOVE WS-INTEREST TO WS-AMOUNT
                   COMPUTE WS-NEW-BAL = AC-BALANCE (WS-SLOT) + WS-AMOUNT
               WHEN TR-FEE
                   IF WS-AMOUNT > 25
                       MOVE 25 TO WS-AMOUNT
                   END-IF
                   COMPUTE WS-NEW-BAL = AC-BALANCE (WS-SLOT) - WS-AMOUNT
               WHEN OTHER
                   MOVE "BAD TYPE" TO WS-STATUS
           END-EVALUATE
           IF STATUS-POSTED
               COMPUTE AC-BALANCE (WS-SLOT) = WS-NEW-BAL
                   ON SIZE ERROR
                       MOVE "OVERFLOW" TO WS-STATUS
      *                END-ADD is required: without it NOT ON SIZE ERROR
      *                would belong to this nested ADD
                       ADD 1 TO WS-OVERFLOWS
                       END-ADD
                   NOT ON SIZE ERROR
                       ADD 1 TO AC-COUNT (WS-SLOT)
                       ADD WS-AMOUNT TO WS-AMOUNT-SUM
               END-COMPUTE
           ELSE
               ADD 1 TO WS-REJECTS
           END-IF.
       WRITE-TXN-LINE.
           MOVE TR-SEQ TO TL-SEQ
           MOVE TR-ACCT TO TL-ACCT
           MOVE TR-TYPE TO TL-TYPE
           MOVE WS-AMOUNT TO TL-AMOUNT
           MOVE AC-BALANCE (WS-SLOT) TO TL-BALANCE
           MOVE WS-STATUS TO TL-STATUS
           WRITE STMT-REC FROM WS-TXN-LINE.
       WRITE-ACCOUNTS.
           PERFORM VARYING WS-SLOT FROM 1 BY 1 UNTIL WS-SLOT > 10
               MOVE WS-SLOT TO AL-SLOT
               MOVE AC-OPEN (WS-SLOT) TO AL-OPEN
               MOVE AC-BALANCE (WS-SLOT) TO AL-CLOSE
               MOVE AC-COUNT (WS-SLOT) TO AL-COUNT
               WRITE STMT-REC FROM WS-ACCT-LINE
           END-PERFORM.
