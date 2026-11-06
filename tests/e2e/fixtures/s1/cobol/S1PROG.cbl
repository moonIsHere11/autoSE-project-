       IDENTIFICATION DIVISION.
       PROGRAM-ID. S1PROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY S1COPY.
       01 WS-B        PIC 9(3) VALUE 0.
       01 WS-R        PIC S9(5)V99 VALUE 0.
       01 WS-I        PIC 9(2).
       PROCEDURE DIVISION.
       MAIN-PARA.
           ACCEPT WS-A
           ACCEPT WS-B
           PERFORM CALC-PARA
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 2
               DISPLAY "I=" WS-I
           END-PERFORM
           IF WS-R > 100
              DISPLAY "BIG"
           ELSE
              DISPLAY "SMALL"
           END-IF
           DISPLAY "R=" WS-R
           MOVE 3 TO RETURN-CODE
           STOP RUN.
       CALC-PARA.
           COMPUTE WS-R ROUNDED = WS-A * 1.5 + WS-B.
       NEVER-PARA.
           DISPLAY "NEVER".
