       IDENTIFICATION DIVISION.
       PROGRAM-ID. VARYING.
      * PERFORM VARYING boundaries: final value of the control item,
      * negative BY, VARYING ... AFTER, TEST AFTER, zero iterations.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 I            PIC S9(3).
       01 J            PIC S9(3).
       01 N            PIC 9(3) VALUE 0.
       01 LIM          PIC 9(3) VALUE 3.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > LIM
               ADD 1 TO N
           END-PERFORM
           DISPLAY "I=" I " N=" N
           MOVE 0 TO N
           PERFORM VARYING I FROM 10 BY -3 UNTIL I < 0
               DISPLAY "DOWN " I
           END-PERFORM
           DISPLAY "I=" I
           PERFORM VARYING I FROM 5 BY 1 UNTIL I > 3
               DISPLAY "NEVER"
           END-PERFORM
           DISPLAY "I=" I
           PERFORM WITH TEST AFTER VARYING I FROM 5 BY 1 UNTIL I > 3
               DISPLAY "ONCE " I
           END-PERFORM
           PERFORM WITH TEST AFTER VARYING I FROM 1 BY 1 UNTIL I >= 3
               DISPLAY "TA " I
           END-PERFORM
           DISPLAY "I=" I
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 2
                   AFTER J FROM 1 BY 1 UNTIL J > 3
               DISPLAY I " " J
           END-PERFORM
           DISPLAY "I=" I " J=" J
           PERFORM BODY-PARA VARYING I FROM 1 BY 2 UNTIL I > 6
           DISPLAY "I=" I
           STOP RUN.
       BODY-PARA.
           DISPLAY "BODY " I.
