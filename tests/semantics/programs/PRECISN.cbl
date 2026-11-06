       IDENTIFICATION DIVISION.
       PROGRAM-ID. PRECISN.
      * Intermediate precision in COMPUTE: division intermediates are
      * truncated after 38+ decimal digits, exponentiation, large
      * intermediates, literal folding, operator precedence.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 R            PIC S9(9)V9(6).
       01 RR           PIC S9(9)V9(6).
       01 A            PIC S9(5)V99 VALUE 10.
       01 B            PIC S9(5)V99 VALUE 3.
       01 C            PIC S9(5)V99 VALUE 7.
       01 BIG1         PIC S9(18) VALUE 999999999999999999.
       01 BIG2         PIC S9(18) VALUE 999999999999999998.
       01 Q            PIC S9(18).
       01 W            PIC S9V9(17).
       PROCEDURE DIVISION.
       MAIN-PARA.
           COMPUTE R = A / B * B
           COMPUTE RR ROUNDED = A / B * B
           DISPLAY R " " RR
           COMPUTE R = 1 / 3 + 1 / 3 + 1 / 3
           DISPLAY R
           COMPUTE R = (A / B) * (B / A) * 1000
           DISPLAY R
           COMPUTE R ROUNDED = A / C
           DISPLAY R
           COMPUTE R = 2 ** 10 / 3
           DISPLAY R
           COMPUTE R = 2 ** -2
           DISPLAY R
           COMPUTE R = B ** 3 - C ** 2
           DISPLAY R
           COMPUTE R = 2 ** 3 ** 2
           DISPLAY R
           COMPUTE R = - A ** 2
           DISPLAY R
           COMPUTE R = A - B - C
           DISPLAY R
           COMPUTE R = A / B / C
           DISPLAY R
           COMPUTE Q = BIG1 * BIG2 / BIG1
           DISPLAY Q
           COMPUTE Q = BIG1 * BIG2 / BIG2 - BIG1 + 1
           DISPLAY Q
           COMPUTE W = 1 / 7
           DISPLAY W
           COMPUTE W ROUNDED = 2 / 3
           DISPLAY W
           COMPUTE R = 1.50 * 1.5 / 0.3
           DISPLAY R
           COMPUTE R = (A + B) / (C - 7)
           DISPLAY R
           STOP RUN.
