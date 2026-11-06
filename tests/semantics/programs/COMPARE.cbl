       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMPARE.
      * Comparisons: alphanumeric with space padding, numeric across
      * usages and scales, numeric item vs alphanumeric literal,
      * figurative constants, spaces in a numeric DISPLAY item.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 X3           PIC X(3) VALUE "AB".
       01 X5           PIC X(5) VALUE "AB".
       01 N3           PIC 9(3) VALUE 7.
       01 M3           PIC 9(3) VALUE 7.
       01 P            PIC S9(3)V9 COMP-3 VALUE 7.
       01 B            PIC S9(4) COMP VALUE 7.
       01 D            PIC S99V99 VALUE 7.00.
       01 GRP.
          05 SP3       PIC 9(3).
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF X3 = X5 DISPLAY "PAD EQ" END-IF
           IF X3 < "ABC" DISPLAY "LT" END-IF
           IF X5 = SPACES DISPLAY "SP" ELSE DISPLAY "NOT SP" END-IF
           IF N3 = P AND P = B AND B = D DISPLAY "NUM EQ" END-IF
           IF N3 = "007" DISPLAY "N3 = '007'" END-IF
           IF N3 > "7" DISPLAY "N3 > '7'"
               ELSE DISPLAY "N3 NOT > '7'" END-IF
           IF N3 = ZERO DISPLAY "Z" ELSE DISPLAY "NZ" END-IF
           IF X3 > LOW-VALUES DISPLAY "GT LOW" END-IF
           IF X3 < HIGH-VALUES DISPLAY "LT HIGH" END-IF
           MOVE SPACES TO GRP
           IF SP3 = 0 DISPLAY "SPACES = 0"
               ELSE DISPLAY "SPACES <> 0" END-IF
           IF SP3 = M3 DISPLAY "SP3 = M3"
               ELSE DISPLAY "SP3 <> M3" END-IF
           MOVE "  7" TO GRP
           IF SP3 = M3 DISPLAY "' 7' = M3"
               ELSE DISPLAY "' 7' <> M3" END-IF
           IF SP3 = 7 DISPLAY "' 7' = 7" ELSE DISPLAY "' 7' <> 7" END-IF
           ADD 1 TO SP3
           DISPLAY SP3
           STOP RUN.
