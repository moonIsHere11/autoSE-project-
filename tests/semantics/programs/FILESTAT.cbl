       IDENTIFICATION DIVISION.
       PROGRAM-ID. FILESTAT.
      * File status codes for LINE SEQUENTIAL and fixed SEQUENTIAL
      * files: 00, 06 (long line split), 10, 35, 41, 42, 46, 47, 48, 71;
      * READ INTO, WRITE FROM, OPEN EXTEND, record area contents.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-F ASSIGN TO "IN.DAT"
               ORGANIZATION IS LINE SEQUENTIAL FILE STATUS IS FS1.
           SELECT OUT-F ASSIGN TO "OUT.DAT"
               ORGANIZATION IS LINE SEQUENTIAL FILE STATUS IS FS2.
           SELECT SQ-F ASSIGN TO "SQ.DAT"
               ORGANIZATION IS SEQUENTIAL FILE STATUS IS FS3.
           SELECT MISS-F ASSIGN TO "MISSING.DAT"
               ORGANIZATION IS LINE SEQUENTIAL FILE STATUS IS FS4.
       DATA DIVISION.
       FILE SECTION.
       FD IN-F.
       01 IN-REC.
          05 IN-A      PIC X(3).
          05 IN-N      PIC 9(3).
          05 IN-T      PIC X(2).
       FD OUT-F.
       01 OUT-REC      PIC X(6).
       01 OUT-REC2     PIC X(3).
       FD SQ-F.
       01 SQ-REC.
          05 SQ-N      PIC S9(3).
          05 SQ-B      PIC S9(4) COMP.
          05 SQ-P      PIC S9(3) COMP-3.
       FD MISS-F.
       01 MISS-REC     PIC X(4).
       WORKING-STORAGE SECTION.
       01 FS1          PIC XX.
       01 FS2          PIC XX.
       01 FS3          PIC XX.
       01 FS4          PIC XX.
       01 W8           PIC X(8).
       01 EOF-FLAG     PIC X VALUE "N".
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "REC0 [" IN-REC "]"
           OPEN INPUT MISS-F
           DISPLAY "MISS " FS4
           OPEN INPUT IN-F
           DISPLAY "OPEN " FS1
           OPEN INPUT IN-F
           DISPLAY "OPEN AGAIN " FS1
           READ IN-F INTO W8
           DISPLAY "R1 " FS1 " [" IN-REC "] [" W8 "] " IN-N
           PERFORM UNTIL EOF-FLAG = "Y"
               READ IN-F
                   AT END MOVE "Y" TO EOF-FLAG
                   NOT AT END DISPLAY "R " FS1 " [" IN-REC "]"
               END-READ
           END-PERFORM
           DISPLAY "EOF " FS1 " [" IN-REC "]"
           READ IN-F
           DISPLAY "AFTER EOF " FS1
           CLOSE IN-F
           DISPLAY "CLOSE " FS1
           CLOSE IN-F
           DISPLAY "CLOSE AGAIN " FS1
           OPEN OUTPUT OUT-F
           MOVE "AB" TO OUT-REC
           WRITE OUT-REC
           DISPLAY "W1 " FS2
           MOVE LOW-VALUES TO OUT-REC
           WRITE OUT-REC
           DISPLAY "W2 " FS2
           MOVE "XYZ" TO OUT-REC2
           WRITE OUT-REC2
           DISPLAY "W3 " FS2
           READ OUT-F
           DISPLAY "READ OUTPUT " FS2
           CLOSE OUT-F
           OPEN EXTEND OUT-F
           DISPLAY "EXTEND " FS2
           WRITE OUT-REC FROM W8
           CLOSE OUT-F
           OPEN INPUT SQ-F
           DISPLAY "SQ OPEN " FS3
           OPEN OUTPUT SQ-F
           MOVE -12 TO SQ-N
           MOVE -3 TO SQ-B
           MOVE 45 TO SQ-P
           WRITE SQ-REC
           MOVE 9 TO SQ-N
           WRITE SQ-REC
           DISPLAY "SQ WRITE " FS3
           CLOSE SQ-F
           OPEN INPUT SQ-F
           READ SQ-F
           DISPLAY "SQ R " FS3 " " SQ-N " " SQ-B " " SQ-P
           WRITE SQ-REC
           DISPLAY "SQ WRITE INPUT " FS3
           READ SQ-F
           READ SQ-F
           DISPLAY "SQ EOF " FS3
           CLOSE SQ-F
           STOP RUN.
