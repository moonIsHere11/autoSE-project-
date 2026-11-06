       IDENTIFICATION DIVISION.
       PROGRAM-ID. S6FILE.
      * Byte-exact record encodings (fixed SEQUENTIAL) and LINE
      * SEQUENTIAL padding / trimming rules.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT FIX-OUT ASSIGN TO "FIXOUT.DAT"
               ORGANIZATION IS SEQUENTIAL.
           SELECT LS-OUT ASSIGN TO "LSOUT.TXT"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT LS-IN ASSIGN TO "LSIN.TXT"
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-FS.
           SELECT PLAIN ASSIGN TO PLAINNAME
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD FIX-OUT.
       01 FIX-REC.
          05 F-ZS    PIC S9(3).
          05 F-ZU    PIC 9(3).
          05 F-ZSP   PIC S9(3).
          05 F-C3    PIC S9(3) COMP-3.
          05 F-CB    PIC S9(4) COMP.
          05 F-C5    PIC S9(4) COMP-5.
          05 F-LS    PIC S9(3) SIGN LEADING SEPARATE.
          05 F-X     PIC X(3).
       FD LS-OUT.
       01 LS-REC     PIC X(8).
       FD LS-IN.
       01 LSI-REC.
          05 LSI-A   PIC X(4).
          05 LSI-N   PIC 9(4).
       FD PLAIN.
       01 PLAIN-REC  PIC X(4).
       WORKING-STORAGE SECTION.
       01 WS-FS     PIC XX.
       01 WS-EOF    PIC X VALUE "N".
       PROCEDURE DIVISION.
           OPEN OUTPUT FIX-OUT
           MOVE -123 TO F-ZS
           MOVE 123 TO F-ZU
           MOVE 123 TO F-ZSP
           MOVE -123 TO F-C3
           MOVE -123 TO F-CB
           MOVE -123 TO F-C5
           MOVE -123 TO F-LS
           MOVE "AB" TO F-X
           WRITE FIX-REC
           MOVE -100 TO F-ZS
           MOVE 1 TO F-ZU
           WRITE FIX-REC
           CLOSE FIX-OUT
           OPEN OUTPUT LS-OUT
           MOVE "AB      " TO LS-REC
           WRITE LS-REC
           MOVE SPACES TO LS-REC
           WRITE LS-REC
           MOVE "ABCDEFGH" TO LS-REC
           WRITE LS-REC
           CLOSE LS-OUT
           OPEN OUTPUT PLAIN
           MOVE "PLN" TO PLAIN-REC
           WRITE PLAIN-REC
           CLOSE PLAIN
           OPEN INPUT LS-IN
           DISPLAY "open LS-IN status " WS-FS
           PERFORM UNTIL WS-EOF = "Y"
               READ LS-IN
                   AT END MOVE "Y" TO WS-EOF
                   NOT AT END
                     DISPLAY "rec [" LSI-REC "] A [" LSI-A "] N [" LSI-N
                        "] st " WS-FS
               END-READ
           END-PERFORM
           DISPLAY "final status " WS-FS
           CLOSE LS-IN
           STOP RUN.
