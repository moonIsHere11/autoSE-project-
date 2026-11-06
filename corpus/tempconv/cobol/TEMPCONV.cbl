       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEMPCONV.
      *----------------------------------------------------------------
      * Temperature conversion.  stdin line 1: temperature PIC S9(2)
      * (canonical texts -9 .. 99); line 2: mode PIC 9
      *   1 C->F, 2 F->C, 3 C->K, 4 F->K, 5 C->F->C round trip,
      *   0 and 6-9 unknown (RETURN-CODE 3).
      * T2a candidate: 109 x 10 = 1,090 canonical inputs.
      * Targets: negative values and negative zero, COMPUTE with
      * division (intermediate precision: T / 3 * 3), ROUNDED vs
      * truncation on negative results, MOVE to an unsigned field,
      * ON SIZE ERROR / NOT ON SIZE ERROR, EVALUATE TRUE on ranges.
      *----------------------------------------------------------------
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-TEMP            PIC S9(2).
       01 WS-MODE            PIC 9.
          88 MODE-C-TO-F     VALUE 1.
          88 MODE-F-TO-C     VALUE 2.
          88 MODE-C-TO-K     VALUE 3.
          88 MODE-F-TO-K     VALUE 4.
          88 MODE-VALID      VALUE 1 THRU 5.
       01 WS-CELSIUS         PIC S9(3)V99.
       01 WS-FAHR            PIC S9(3)V99.
       01 WS-KELVIN          PIC 9(3)V99.
       01 WS-RESULT          PIC S9(3)V9.
       01 WS-RESULT-T        PIC S9(3)V9.
       01 WS-MAGNITUDE       PIC 9(3)V9.
       01 WS-THIRDS          PIC S9(3)V9.
       01 WS-THIRDS-R        PIC S9(3)V9.
       01 WS-SPREAD          PIC S9(2)V9.
       01 WS-SPREAD-FLAG     PIC X(3).
       01 WS-FEEL            PIC X(8).
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM GET-INPUT
           IF MODE-VALID
               PERFORM CONVERT
               PERFORM CLASSIFY
               PERFORM REPORT-OUT
           ELSE
               DISPLAY "UNKNOWN MODE " WS-MODE " FOR " WS-TEMP
               MOVE 3 TO RETURN-CODE
           END-IF
           STOP RUN.
       GET-INPUT.
           ACCEPT WS-TEMP
           ACCEPT WS-MODE.
       CONVERT.
           EVALUATE TRUE
               WHEN MODE-C-TO-F
                   MOVE WS-TEMP TO WS-CELSIUS
                   COMPUTE WS-FAHR ROUNDED = WS-TEMP * 9 / 5 + 32
                   COMPUTE WS-RESULT ROUNDED = WS-TEMP * 9 / 5 + 32
                   COMPUTE WS-RESULT-T = WS-TEMP * 9 / 5 + 32
               WHEN MODE-F-TO-C
                   MOVE WS-TEMP TO WS-FAHR
                   COMPUTE WS-CELSIUS ROUNDED = (WS-TEMP - 32) * 5 / 9
                   COMPUTE WS-RESULT ROUNDED = (WS-TEMP - 32) * 5 / 9
                   COMPUTE WS-RESULT-T = (WS-TEMP - 32) / 9 * 5
               WHEN MODE-C-TO-K
                   MOVE WS-TEMP TO WS-CELSIUS
                   COMPUTE WS-FAHR ROUNDED = WS-TEMP * 1.8 + 32
                   COMPUTE WS-RESULT ROUNDED = WS-TEMP + 273.15
                   COMPUTE WS-RESULT-T = WS-TEMP + 273.15
               WHEN MODE-F-TO-K
                   MOVE WS-TEMP TO WS-FAHR
                   COMPUTE WS-CELSIUS ROUNDED = (WS-TEMP - 32) / 1.8
                   COMPUTE WS-RESULT ROUNDED =
                       (WS-TEMP - 32) / 1.8 + 273.15
                   COMPUTE WS-RESULT-T = (WS-TEMP - 32) / 1.8 + 273.15
               WHEN OTHER
                   MOVE WS-TEMP TO WS-CELSIUS
                   COMPUTE WS-FAHR ROUNDED = WS-TEMP * 9 / 5 + 32
                   COMPUTE WS-RESULT ROUNDED = (WS-FAHR - 32) * 5 / 9
                   COMPUTE WS-RESULT-T = (WS-FAHR - 32) / 9 * 5
           END-EVALUATE
           COMPUTE WS-KELVIN ROUNDED = WS-CELSIUS + 273.15
           MOVE WS-RESULT TO WS-MAGNITUDE
           COMPUTE WS-THIRDS = WS-TEMP / 3 * 3
           COMPUTE WS-THIRDS-R ROUNDED = WS-TEMP / 3 * 3
           COMPUTE WS-SPREAD = WS-FAHR - WS-CELSIUS
               ON SIZE ERROR
                   MOVE "OVF" TO WS-SPREAD-FLAG
               NOT ON SIZE ERROR
                   MOVE "OK" TO WS-SPREAD-FLAG
           END-COMPUTE.
       CLASSIFY.
           EVALUATE TRUE
               WHEN WS-CELSIUS < -10
                   MOVE "FREEZING" TO WS-FEEL
               WHEN WS-CELSIUS < 0
                   MOVE "COLD" TO WS-FEEL
               WHEN WS-CELSIUS = 0
                   MOVE "ZERO" TO WS-FEEL
               WHEN WS-CELSIUS < 20
                   MOVE "MILD" TO WS-FEEL
               WHEN WS-CELSIUS < 30
                   MOVE "WARM" TO WS-FEEL
               WHEN OTHER
                   MOVE "HOT" TO WS-FEEL
           END-EVALUATE.
       REPORT-OUT.
           DISPLAY "MODE " WS-MODE " INPUT " WS-TEMP
           DISPLAY "CELSIUS " WS-CELSIUS " FAHRENHEIT " WS-FAHR
                   " KELVIN " WS-KELVIN
           DISPLAY "RESULT " WS-RESULT " TRUNCATED " WS-RESULT-T
                   " MAGNITUDE " WS-MAGNITUDE
           DISPLAY "THIRDS " WS-THIRDS " ROUNDED " WS-THIRDS-R
           DISPLAY "SPREAD " WS-SPREAD " " WS-SPREAD-FLAG
                   " FEEL " WS-FEEL.
