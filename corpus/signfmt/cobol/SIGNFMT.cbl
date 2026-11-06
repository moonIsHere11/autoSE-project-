       IDENTIFICATION DIVISION.
       PROGRAM-ID. SIGNFMT.
      *----------------------------------------------------------------
      * Sign representations.  stdin: groups of three lines
      *   tag X(4), amount S9(3)V99 SIGN LEADING SEPARATE,
      *   delta S9(2)V9 SIGN TRAILING SEPARATE
      * repeated until the tag "END", an empty tag (also end of input)
      * or 30 groups.  Each value is MOVEd / COMPUTEd into other sign
      * forms and shown both as DISPLAY and as raw bytes through
      * REDEFINES and a group item.
      * Targets: SIGN LEADING / TRAILING SEPARATE and embedded
      * (overpunch) signs, negative zero (ACCEPT "-0", kept by MOVE,
      * produced by high-order truncation of a negative result,
      * normalised by DISPLAY), MOVE truncation at both ends, unsigned
      * fields dropping the sign, ACCEPT loop until a sentinel, ON SIZE
      * ERROR whose END-ADD binds to a nested ADD, RETURN-CODE = number
      * of negative amounts.
      *----------------------------------------------------------------
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-TAG                PIC X(4).
          88 TAG-END            VALUE "END".
       01 WS-COUNT              PIC 9(2) VALUE 0.
       01 WS-LS                 PIC S9(3)V99 SIGN LEADING SEPARATE.
       01 WS-LS-RAW REDEFINES WS-LS PIC X(6).
       01 WS-TS                 PIC S9(2)V9 SIGN TRAILING SEPARATE.
       01 WS-TS-RAW REDEFINES WS-TS PIC X(4).
       01 WS-EMB                PIC S9(3)V99.
       01 WS-EMB-RAW REDEFINES WS-EMB PIC X(5).
       01 WS-LEMB               PIC S9(3)V99 SIGN LEADING.
       01 WS-LEMB-RAW REDEFINES WS-LEMB PIC X(5).
       01 WS-UNS                PIC 9(3)V99.
       01 WS-SMALL              PIC S9V9.
       01 WS-SMALL-RAW REDEFINES WS-SMALL PIC X(2).
       01 WS-SUM                PIC S9(3)V99 SIGN TRAILING SEPARATE.
       01 WS-SUM-RAW REDEFINES WS-SUM PIC X(6).
       01 WS-DIFF               PIC S9(2)V99.
       01 WS-DIFF-RAW REDEFINES WS-DIFF PIC X(4).
       01 WS-TOTAL              PIC S9(4)V99 SIGN LEADING SEPARATE
                                VALUE 0.
       01 WS-OVERFLOWS          PIC 9(2) VALUE 0.
       01 WS-LAST-OVF           PIC 9(2) VALUE 0.
       01 WS-NEG-COUNT          PIC 9(2) VALUE 0.
       01 WS-ZERO-COUNT         PIC 9(2) VALUE 0.
       01 WS-POS-COUNT          PIC 9(2) VALUE 0.
       01 WS-ECHO.
          05 WS-E-TAG           PIC X(4).
          05 WS-E-LS            PIC S9(3)V99 SIGN LEADING SEPARATE.
          05 WS-E-TS            PIC S9(2)V9 SIGN LEADING.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM READ-ENTRY
           PERFORM UNTIL TAG-END OR WS-TAG = SPACES
                   OR WS-COUNT NOT < 30
               PERFORM CONVERT-ENTRY
               PERFORM SHOW-ENTRY
               PERFORM READ-ENTRY
           END-PERFORM
           PERFORM SHOW-SUMMARY
           STOP RUN.
       READ-ENTRY.
           ACCEPT WS-TAG
           IF NOT TAG-END AND WS-TAG NOT = SPACES
               ACCEPT WS-LS
               ACCEPT WS-TS
               ADD 1 TO WS-COUNT
           END-IF.
       CONVERT-ENTRY.
           MOVE WS-LS TO WS-EMB WS-LEMB WS-UNS WS-SMALL
           COMPUTE WS-SUM = WS-LS + WS-TS
           COMPUTE WS-DIFF = WS-LS - WS-TS
           EVALUATE TRUE
               WHEN WS-LS < 0
                   ADD 1 TO WS-NEG-COUNT
               WHEN WS-LS = 0
                   ADD 1 TO WS-ZERO-COUNT
               WHEN OTHER
                   ADD 1 TO WS-POS-COUNT
           END-EVALUATE
           MOVE WS-TAG TO WS-E-TAG
           MOVE WS-LS TO WS-E-LS
           MOVE WS-TS TO WS-E-TS
      *    Deliberate trap: END-ADD closes the nearest ADD, i.e. the
      *    inner "ADD 1 TO WS-OVERFLOWS", so the MOVE below still
      *    belongs to the ON SIZE ERROR phrase and runs only on overflow.
           ADD WS-LS TO WS-TOTAL
               ON SIZE ERROR
                   ADD 1 TO WS-OVERFLOWS
           END-ADD
           MOVE WS-COUNT TO WS-LAST-OVF.
       SHOW-ENTRY.
           DISPLAY WS-COUNT " " WS-TAG " LS " WS-LS " [" WS-LS-RAW
                   "] TS " WS-TS " [" WS-TS-RAW "]"
           DISPLAY "   EMB " WS-EMB " [" WS-EMB-RAW "] LEMB ["
                   WS-LEMB-RAW "] UNS " WS-UNS " SMALL " WS-SMALL
                   " [" WS-SMALL-RAW "]"
           DISPLAY "   SUM " WS-SUM " [" WS-SUM-RAW "] DIFF " WS-DIFF
                   " [" WS-DIFF-RAW "] ECHO [" WS-ECHO "]".
       SHOW-SUMMARY.
           DISPLAY "ENTRIES " WS-COUNT " NEGATIVE " WS-NEG-COUNT
                   " ZERO " WS-ZERO-COUNT " POSITIVE " WS-POS-COUNT
           DISPLAY "TOTAL " WS-TOTAL " OVERFLOWS " WS-OVERFLOWS
                   " LAST " WS-LAST-OVF
           MOVE WS-NEG-COUNT TO RETURN-CODE.
