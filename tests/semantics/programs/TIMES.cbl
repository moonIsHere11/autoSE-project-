       IDENTIFICATION DIVISION.
       PROGRAM-ID. TIMES.
      * PERFORM n TIMES (count read once), PERFORM UNTIL with TEST
      * BEFORE / AFTER, inline PERFORM, EXIT PERFORM [CYCLE].
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 N            PIC 9(2) VALUE 3.
       01 K            PIC 9(2) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM SHOW-K N TIMES
           PERFORM N TIMES
               ADD 1 TO N
               DISPLAY "N " N
           END-PERFORM
           PERFORM 0 TIMES
               DISPLAY "NEVER"
           END-PERFORM
           MOVE 0 TO K
           PERFORM UNTIL K >= 3
               ADD 1 TO K
               DISPLAY "UNTIL " K
           END-PERFORM
           PERFORM WITH TEST AFTER UNTIL K >= 3
               ADD 1 TO K
               DISPLAY "AFTER " K
           END-PERFORM
           MOVE 0 TO K
           PERFORM UNTIL K > 9
               ADD 1 TO K
               IF K = 2
                   EXIT PERFORM CYCLE
               END-IF
               IF K = 5
                   EXIT PERFORM
               END-IF
               DISPLAY "LOOP " K
           END-PERFORM
           DISPLAY "K " K
           STOP RUN.
       SHOW-K.
           ADD 1 TO K
           DISPLAY "K " K.
