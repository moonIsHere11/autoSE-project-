       IDENTIFICATION DIVISION.
       PROGRAM-ID. S6DISP.
      * DISPLAY formats and byte lengths per usage / sign form.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 D-U3      PIC 9(3)            VALUE 7.
       01 D-S3      PIC S9(3)           VALUE -7.
       01 D-S3P     PIC S9(3)           VALUE 7.
       01 D-SV      PIC S9(3)V99        VALUE -1.5.
       01 D-UV      PIC 9(3)V99         VALUE 1.5.
       01 D-V99     PIC V99             VALUE .25.
       01 D-SVONLY  PIC SV99            VALUE -.25.
       01 D-LS      PIC S9(3) SIGN LEADING SEPARATE  VALUE -7.
       01 D-TS      PIC S9(3) SIGN TRAILING SEPARATE VALUE -7.
       01 D-LE      PIC S9(3) SIGN LEADING           VALUE -7.
       01 D-TE      PIC S9(3) SIGN TRAILING          VALUE -7.
       01 D-C3      PIC S9(5)V99 COMP-3 VALUE -123.45.
       01 D-C3U     PIC 9(4) COMP-3     VALUE 1234.
       01 D-CB      PIC S9(4) COMP      VALUE -123.
       01 D-CB9     PIC 9(9) COMP       VALUE 123456789.
       01 D-B18     PIC S9(18) BINARY   VALUE -1.
       01 D-C5      PIC S9(4) COMP-5    VALUE -123.
       01 D-C5U     PIC 9(2) COMP-5     VALUE 7.
       01 D-P       PIC 9(3)PP          VALUE 12300.
       01 D-PL      PIC PP9(2)          VALUE .0012.
       01 D-X       PIC X(5)            VALUE "AB".
       01 D-A       PIC A(3)            VALUE "XY".
       01 D-J       PIC X(5) JUSTIFIED RIGHT VALUE "AB".
       01 D-GRP.
          05 G-A    PIC X(2)  VALUE "GG".
          05 G-N    PIC S9(3) VALUE -12.
          05 G-C    PIC S9(3) COMP-3 VALUE 12.
       01 D-TAB.
          05 T-E    PIC 9(2) OCCURS 3 TIMES.
       01 D-NZ      PIC S9(3)           VALUE 0.
       01 D-NEG     PIC S9(3)           VALUE -5.
       01 D-TMP     PIC S9(3)V9         VALUE 0.
       PROCEDURE DIVISION.
           DISPLAY "U3   [" D-U3 "] len " FUNCTION BYTE-LENGTH(D-U3)
           DISPLAY "S3   [" D-S3 "] len " FUNCTION BYTE-LENGTH(D-S3)
           DISPLAY "S3P  [" D-S3P "]"
           DISPLAY "SV   [" D-SV "] len " FUNCTION BYTE-LENGTH(D-SV)
           DISPLAY "UV   [" D-UV "]"
           DISPLAY "V99  [" D-V99 "]"
           DISPLAY "SV99 [" D-SVONLY "]"
           DISPLAY "LS   [" D-LS "] len " FUNCTION BYTE-LENGTH(D-LS)
           DISPLAY "TS   [" D-TS "] len " FUNCTION BYTE-LENGTH(D-TS)
           DISPLAY "LE   [" D-LE "] len " FUNCTION BYTE-LENGTH(D-LE)
           DISPLAY "TE   [" D-TE "] len " FUNCTION BYTE-LENGTH(D-TE)
           DISPLAY "C3   [" D-C3 "] len " FUNCTION BYTE-LENGTH(D-C3)
           DISPLAY "C3U  [" D-C3U "] len " FUNCTION BYTE-LENGTH(D-C3U)
           DISPLAY "CB   [" D-CB "] len " FUNCTION BYTE-LENGTH(D-CB)
           DISPLAY "CB9  [" D-CB9 "] len " FUNCTION BYTE-LENGTH(D-CB9)
           DISPLAY "B18  [" D-B18 "] len " FUNCTION BYTE-LENGTH(D-B18)
           DISPLAY "C5   [" D-C5 "] len " FUNCTION BYTE-LENGTH(D-C5)
           DISPLAY "C5U  [" D-C5U "] len " FUNCTION BYTE-LENGTH(D-C5U)
           DISPLAY "P    [" D-P "] len " FUNCTION BYTE-LENGTH(D-P)
           DISPLAY "PL   [" D-PL "] len " FUNCTION BYTE-LENGTH(D-PL)
           DISPLAY "X    [" D-X "] len " FUNCTION BYTE-LENGTH(D-X)
           DISPLAY "A    [" D-A "]"
           DISPLAY "J    [" D-J "]"
           DISPLAY "GRP  [" D-GRP "] len " FUNCTION BYTE-LENGTH(D-GRP)
           DISPLAY "TAB  len " FUNCTION BYTE-LENGTH(D-TAB)
               " elem " FUNCTION BYTE-LENGTH(T-E(1))
               " LENGTH-fn " FUNCTION LENGTH(D-C3)
               " LENGTH-OF " LENGTH OF D-C3
           DISPLAY "NZ   [" D-NZ "]"
           COMPUTE D-TMP = D-NEG * 0
           DISPLAY "NEG*0 [" D-TMP "]"
           MOVE -0 TO D-NZ
           DISPLAY "MOVE -0 [" D-NZ "]"
           COMPUTE D-TMP = -0.04
           DISPLAY "C -0.04 to V9 [" D-TMP "]"
           COMPUTE D-TMP ROUNDED = -0.04
           DISPLAY "C ROUNDED -0.04 [" D-TMP "]"
           COMPUTE D-TMP ROUNDED = 2.45
           DISPLAY "C ROUNDED 2.45 [" D-TMP "]"
           COMPUTE D-TMP ROUNDED = -2.45
           DISPLAY "C ROUNDED -2.45 [" D-TMP "]"
           COMPUTE D-TMP ROUNDED = 2.55
           DISPLAY "C ROUNDED 2.55 [" D-TMP "]"
           COMPUTE D-TMP = 12345.6
           DISPLAY "C 12345.6 into S9(3)V9 [" D-TMP "]"
           MOVE 12345.6 TO D-TMP
           DISPLAY "M 12345.6 into S9(3)V9 [" D-TMP "]"
           MOVE -5 TO D-U3
           DISPLAY "M -5 into 9(3) [" D-U3 "]"
           STOP RUN.
