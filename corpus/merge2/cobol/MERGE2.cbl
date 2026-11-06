       IDENTIFICATION DIVISION.
       PROGRAM-ID. MERGE2.
      *----------------------------------------------------------------
      * Classic balanced-line master file update.  Reads MASTER.TXT
      * and TRANS.TXT (LINE SEQUENTIAL, expected in ascending key
      * order), writes the updated master to NEWMAST.TXT (LINE
      * SEQUENTIAL) and an error log plus totals on stdout.
      * Transaction codes: A add, U update (add amount), D delete.
      * Targets (deliberately outside the T2b IR subset): GO TO,
      * PERFORM ... THRU ... EXIT, fall-through from MAIN-PARA into
      * MERGE-LOOP and FINISH, HIGH-VALUES / LOW-VALUES key compares,
      * sequence checking, signed zoned (overpunch) amounts in text
      * records, negative zero carried through MOVEs, ON SIZE ERROR,
      * 88-levels, RETURN-CODE 4.
      *----------------------------------------------------------------
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT MASTER-FILE ASSIGN TO "MASTER.TXT"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT TRANS-FILE ASSIGN TO "TRANS.TXT"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT NEW-FILE ASSIGN TO "NEWMAST.TXT"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD MASTER-FILE.
       01 MST-REC.
          05 MST-KEY            PIC X(5).
          05 MST-NAME           PIC X(10).
          05 MST-BAL            PIC S9(5)V99.
       FD TRANS-FILE.
       01 TRN-REC.
          05 TRN-KEY            PIC X(5).
          05 TRN-CODE           PIC X.
             88 TRN-ADD         VALUE "A".
             88 TRN-UPDATE      VALUE "U".
             88 TRN-DELETE      VALUE "D".
          05 TRN-NAME           PIC X(10).
          05 TRN-AMT            PIC S9(5)V99.
       FD NEW-FILE.
       01 NEW-REC.
          05 NEW-KEY            PIC X(5).
          05 NEW-NAME           PIC X(10).
          05 NEW-BAL            PIC S9(5)V99.
       WORKING-STORAGE SECTION.
       01 WS-MKEY               PIC X(5).
       01 WS-TKEY               PIC X(5).
       01 WS-PREV-MKEY          PIC X(5) VALUE LOW-VALUES.
       01 WS-PREV-TKEY          PIC X(5) VALUE LOW-VALUES.
       01 WS-MNAME              PIC X(10).
       01 WS-BAL                PIC S9(5)V99.
       01 WS-DELETED            PIC X VALUE "N".
       01 WS-MSG                PIC X(20).
       01 WS-READ-M             PIC 9(3) VALUE 0.
       01 WS-READ-T             PIC 9(3) VALUE 0.
       01 WS-WRITTEN            PIC 9(3) VALUE 0.
       01 WS-ADDED              PIC 9(3) VALUE 0.
       01 WS-UPDATED            PIC 9(3) VALUE 0.
       01 WS-DEL-COUNT          PIC 9(3) VALUE 0.
       01 WS-ERRORS             PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT MASTER-FILE
           OPEN INPUT TRANS-FILE
           OPEN OUTPUT NEW-FILE
           PERFORM READ-MASTER THRU READ-MASTER-EXIT
           PERFORM READ-TRANS THRU READ-TRANS-EXIT.
       MERGE-LOOP.
           IF WS-MKEY = HIGH-VALUES AND WS-TKEY = HIGH-VALUES
               GO TO FINISH.
           IF WS-MKEY < WS-TKEY
               PERFORM COPY-MASTER
               PERFORM READ-MASTER THRU READ-MASTER-EXIT
               GO TO MERGE-LOOP.
           IF WS-MKEY = WS-TKEY
               PERFORM APPLY-TRANS THRU APPLY-TRANS-EXIT
               PERFORM READ-TRANS THRU READ-TRANS-EXIT
               GO TO MERGE-LOOP.
           PERFORM ADD-NEW THRU ADD-NEW-EXIT
           PERFORM READ-TRANS THRU READ-TRANS-EXIT
           GO TO MERGE-LOOP.
       FINISH.
           CLOSE MASTER-FILE
           CLOSE TRANS-FILE
           CLOSE NEW-FILE
           DISPLAY "MASTERS " WS-READ-M " TRANS " WS-READ-T
                   " WRITTEN " WS-WRITTEN " ADDED " WS-ADDED
           DISPLAY "UPDATED " WS-UPDATED " DELETED " WS-DEL-COUNT
                   " ERRORS " WS-ERRORS
           IF WS-ERRORS > 0
               MOVE 4 TO RETURN-CODE
           END-IF
           STOP RUN.
       READ-MASTER.
           READ MASTER-FILE
               AT END
                   MOVE HIGH-VALUES TO WS-MKEY
                   GO TO READ-MASTER-EXIT
           END-READ
           ADD 1 TO WS-READ-M
           IF MST-BAL IS NOT NUMERIC
               DISPLAY "BAD MASTER [" MST-KEY "]"
               ADD 1 TO WS-ERRORS
               GO TO READ-MASTER
           END-IF
           IF MST-KEY NOT > WS-PREV-MKEY
               DISPLAY "MASTER OUT OF SEQUENCE [" MST-KEY "]"
               ADD 1 TO WS-ERRORS
               GO TO READ-MASTER
           END-IF
           MOVE MST-KEY TO WS-MKEY WS-PREV-MKEY
           MOVE MST-NAME TO WS-MNAME
           MOVE MST-BAL TO WS-BAL
           MOVE "N" TO WS-DELETED.
       READ-MASTER-EXIT.
           EXIT.
       READ-TRANS.
           READ TRANS-FILE
               AT END
                   MOVE HIGH-VALUES TO WS-TKEY
                   GO TO READ-TRANS-EXIT
           END-READ
           ADD 1 TO WS-READ-T
           IF TRN-AMT IS NOT NUMERIC
               DISPLAY "BAD TRANS [" TRN-KEY "]"
               ADD 1 TO WS-ERRORS
               GO TO READ-TRANS
           END-IF
           IF TRN-KEY < WS-PREV-TKEY
               DISPLAY "TRANS OUT OF SEQUENCE [" TRN-KEY "]"
               ADD 1 TO WS-ERRORS
               GO TO READ-TRANS
           END-IF
           MOVE TRN-KEY TO WS-TKEY WS-PREV-TKEY.
       READ-TRANS-EXIT.
           EXIT.
       COPY-MASTER.
           IF WS-DELETED = "N"
               MOVE WS-MKEY TO NEW-KEY
               MOVE WS-MNAME TO NEW-NAME
               MOVE WS-BAL TO NEW-BAL
               WRITE NEW-REC
               ADD 1 TO WS-WRITTEN
           END-IF.
       APPLY-TRANS.
           IF WS-DELETED = "Y"
               MOVE "ALREADY DELETED" TO WS-MSG
               GO TO APPLY-ERROR.
           EVALUATE TRUE
               WHEN TRN-UPDATE
                   ADD TRN-AMT TO WS-BAL
                       ON SIZE ERROR
                           MOVE "BALANCE OVERFLOW" TO WS-MSG
                           GO TO APPLY-ERROR
                   END-ADD
                   ADD 1 TO WS-UPDATED
               WHEN TRN-DELETE
                   MOVE "Y" TO WS-DELETED
                   ADD 1 TO WS-DEL-COUNT
               WHEN TRN-ADD
                   MOVE "DUPLICATE KEY" TO WS-MSG
                   GO TO APPLY-ERROR
               WHEN OTHER
                   MOVE "BAD CODE" TO WS-MSG
                   GO TO APPLY-ERROR
           END-EVALUATE
           GO TO APPLY-TRANS-EXIT.
       APPLY-ERROR.
           ADD 1 TO WS-ERRORS
           DISPLAY "ERROR [" TRN-KEY "] " TRN-CODE " " WS-MSG.
       APPLY-TRANS-EXIT.
           EXIT.
       ADD-NEW.
           IF NOT TRN-ADD
               MOVE "NO MASTER" TO WS-MSG
               ADD 1 TO WS-ERRORS
               DISPLAY "ERROR [" TRN-KEY "] " TRN-CODE " " WS-MSG
               GO TO ADD-NEW-EXIT
           END-IF
           MOVE TRN-KEY TO NEW-KEY
           MOVE TRN-NAME TO NEW-NAME
           MOVE TRN-AMT TO NEW-BAL
           WRITE NEW-REC
           ADD 1 TO WS-ADDED
           ADD 1 TO WS-WRITTEN.
       ADD-NEW-EXIT.
           EXIT.
