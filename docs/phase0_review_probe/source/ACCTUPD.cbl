       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCTUPD.
      * NIGHTLY ACCOUNT UPDATE. RULE BR-17: ACCOUNTS OVER 90 DAYS PAST DUE
      * ARE FROZEN PER REGULATION Q. RULE BR-22: WAIVE FEE FOR GOLD TIER.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TRANS-FILE ASSIGN TO TRANIN
               ORGANIZATION IS SEQUENTIAL.
           SELECT XREF-FILE ASSIGN TO XREFVSAM
               ORGANIZATION IS INDEXED ACCESS MODE IS RANDOM
               RECORD KEY IS XR-KEY FILE STATUS IS WS-XR-STAT.
       DATA DIVISION.
       FILE SECTION.
       FD  TRANS-FILE.
       01  TRANS-REC.
           05 TR-ACCT        PIC 9(10).
           05 TR-AMT         PIC S9(7)V99.
       FD  XREF-FILE.
       01  XREF-REC.
           05 XR-KEY         PIC 9(10).
           05 XR-CUST        PIC 9(8).
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
           EXEC SQL INCLUDE ACCTDCL END-EXEC.
       01  WS-XR-STAT        PIC XX.
       01  WS-EOF            PIC X VALUE 'N'.
           88 AT-END         VALUE 'Y'.
       01  WS-DAYS-PAST      PIC 9(4).
       01  WS-FEE            PIC S9(5)V99.
       01  WS-TIER           PIC X.
           88 GOLD           VALUE 'G'.
       01  WS-PARM-DATE      PIC 9(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT TRANS-FILE XREF-FILE
           PERFORM UNTIL AT-END
              READ TRANS-FILE AT END SET AT-END TO TRUE
              NOT AT END PERFORM APPLY-TRANS
              END-READ
           END-PERFORM
           CLOSE TRANS-FILE XREF-FILE
           CALL 'DATEUTIL' USING WS-PARM-DATE
           STOP RUN.
       APPLY-TRANS.
           EXEC SQL
              SELECT BALANCE, DAYS_PAST_DUE, TIER
                INTO :DCL-BAL, :WS-DAYS-PAST, :WS-TIER
                FROM ACCOUNT_MASTER
               WHERE ACCT_NO = :TR-ACCT
           END-EXEC
           IF SQLCODE = 100
              DISPLAY 'NO SUCH ACCOUNT'
           ELSE
              IF WS-DAYS-PAST > 90
                 EXEC SQL UPDATE ACCOUNT_MASTER SET STATUS = 'F'
                    WHERE ACCT_NO = :TR-ACCT END-EXEC
              ELSE
                 PERFORM CALC-FEE
                 EXEC SQL UPDATE ACCOUNT_MASTER
                    SET BALANCE = BALANCE + :TR-AMT - :WS-FEE
                    WHERE ACCT_NO = :TR-ACCT END-EXEC
              END-IF
           END-IF.
       CALC-FEE.
           IF GOLD
              MOVE 0 TO WS-FEE
           ELSE
              IF TR-AMT > 5000
                 COMPUTE WS-FEE = TR-AMT * 0.015
              ELSE
                 MOVE 2.50 TO WS-FEE
              END-IF
           END-IF.
