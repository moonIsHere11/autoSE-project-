package corpus;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;

/**
 * Hand translation of DIGITS. WS-DIGIT REDEFINES WS-NUM, so {@code wsDigit} is refreshed from
 * {@code wsNum} whenever WS-NUM changes (only by ACCEPT). PERFORM PROCESS-NUMBER THRU
 * PROCESS-EXIT runs the paragraphs of the range in order (they fall through into each other);
 * MAIN-PARA falls through into SUMMARY-PARA.
 */
public class Digits {
    long wsNum;                       // 9(6)
    long[] wsDigit = new long[6];     // 9 OCCURS 6 REDEFINES WS-NUM
    long wsCount = 0;                 // 9(2)
    long wsI;                         // 9
    long wsPos;                       // 9
    long wsQ;                         // 9(6)
    long wsRem;                       // 9
    long wsSum;                       // 9(2)
    long wsRoot;                      // 9(2)
    long wsEvenCount;                 // 9
    long wsMaxDigit;                  // 9
    long wsWork;                      // 9(6)
    long wsRev;                       // 9(6)
    String wsPalin = "   ";           // X(3)
    long wsLuhnSum;                   // 9(3)
    long wsDbl;                       // 9(2)
    String wsLuhnOk = " ";            // X
    String wsKind = "          ";     // X(10)
    long wsSeventh;                   // 9(5)V99, scale 2
    long wsSeventhT;                  // 9(5)V99, scale 2
    long wsGrand = 0;                 // 9(7)
    long wsLuhnCount = 0;             // 9(2)
    int returnCode;

    private final BufferedReader in =
            new BufferedReader(new InputStreamReader(System.in, StandardCharsets.ISO_8859_1));
    private final StringBuilder out = new StringBuilder();

    public static void main(String[] args) throws IOException {
        Digits p = new Digits();
        p.mainPara();
        System.out.write(p.out.toString().getBytes(StandardCharsets.ISO_8859_1));
        System.out.flush();
        System.exit(p.returnCode);
    }

    void mainPara() throws IOException {
        readNumber();
        while (!(wsNum == 0 || wsCount > 15)) {
            // PERFORM PROCESS-NUMBER THRU PROCESS-EXIT
            processNumber();
            digitalRoot();
            reverseNumber();
            luhnCheck();
            classify();
            processExit();
        }
        summaryPara(); // fall-through
    }

    void summaryPara() {
        line("NUMBERS " + num(wsCount, 2) + " GRAND " + num(wsGrand, 7) + " LUHN-VALID " + num(wsLuhnCount, 2));
        returnCode = (int) wsLuhnCount;
    }

    void processNumber() {
        wsSum = 0;
        wsEvenCount = 0;
        wsMaxDigit = 0;
        for (wsI = 1; wsI <= 6; wsI++) {
            long d = wsDigit[(int) wsI - 1];
            wsSum = (wsSum + d) % 100;
            wsQ = d / 2;
            wsRem = d % 2;
            if (wsRem == 0) {
                wsEvenCount = (wsEvenCount + 1) % 10;
            }
            if (d > wsMaxDigit) {
                wsMaxDigit = d;
            }
        }
    }

    void digitalRoot() {
        wsRoot = wsSum;
        while (!(wsRoot < 10)) {
            wsQ = wsRoot / 10;
            wsRem = wsRoot % 10;
            wsRoot = (wsQ + wsRem) % 100;
        }
    }

    void reverseNumber() {
        wsWork = wsNum;
        wsRev = 0;
        for (int k = 0; k < 6; k++) {
            wsQ = wsWork / 10;
            wsRem = wsWork % 10;
            wsWork = wsQ;
            wsRev = (wsRev * 10 + wsRem) % 1000000;
        }
        if (wsRev == wsNum) {
            wsPalin = "YES";
        } else {
            wsPalin = "NO ";
        }
    }

    void luhnCheck() {
        wsLuhnSum = 0;
        for (wsI = 6; !(wsI < 1); wsI--) {
            wsPos = 7 - wsI;
            wsQ = wsPos / 2;
            wsRem = wsPos % 2;
            long d = wsDigit[(int) wsI - 1];
            if (wsRem == 0) {
                wsDbl = (d * 2) % 100;
                if (wsDbl > 9) {
                    wsDbl = wsDbl - 9;
                }
                wsLuhnSum = (wsLuhnSum + wsDbl) % 1000;
            } else {
                wsLuhnSum = (wsLuhnSum + d) % 1000;
            }
        }
        wsQ = wsLuhnSum / 10;
        wsRem = wsLuhnSum % 10;
        if (wsRem == 0) {
            wsLuhnOk = "Y";
        } else {
            wsLuhnOk = "N";
        }
    }

    void classify() {
        if (wsNum < 10) {
            wsKind = "SINGLE    ";
        } else if (wsPalin.equals("YES")) {
            wsKind = "PALINDROME";
        } else if (wsEvenCount == 6) {
            wsKind = "ALL-EVEN  ";
        } else if (wsRoot == 9) {
            wsKind = "NINES     ";
        } else {
            wsKind = "PLAIN     ";
        }
        long n = wsNum * 100;                 // WS-NUM / 7 at scale 2
        long q = n / 7;
        wsSeventhT = q % 10000000;            // 9(5)V99: high-order digits are dropped
        if (2 * (n % 7) >= 7) {
            q++;
        }
        wsSeventh = q % 10000000;
    }

    void processExit() throws IOException {
        showNumber();
        wsGrand = (wsGrand + wsNum) % 10000000;
        if (wsLuhnOk.equals("Y")) {
            wsLuhnCount = (wsLuhnCount + 1) % 100;
        }
        readNumber();
    }

    void showNumber() {
        line(num(wsCount, 2) + " " + num(wsNum, 6) + " SUM " + num(wsSum, 2) + " ROOT " + num(wsRoot, 2)
                + " EVEN " + wsEvenCount + " MAX " + wsMaxDigit);
        line("   REV " + num(wsRev, 6) + " PALIN " + wsPalin + " LUHN " + num(wsLuhnSum, 3) + " " + wsLuhnOk + " "
                + wsKind + " /7 " + dec(wsSeventh) + " " + dec(wsSeventhT));
    }

    void readNumber() throws IOException {
        wsNum = acceptNumeric(6);
        long v = wsNum;
        for (int k = 5; k >= 0; k--) {
            wsDigit[k] = v % 10;
            v /= 10;
        }
        if (wsNum != 0) {
            wsCount = (wsCount + 1) % 100;
        }
    }

    // ---------------------------------------------------------------- runtime helpers

    private void line(String s) {
        out.append(s).append('\n');
    }

    private String readLine() throws IOException {
        int ch = in.read();
        if (ch < 0) {
            return null;
        }
        StringBuilder sb = new StringBuilder();
        while (ch >= 0 && ch != '\n') {
            sb.append((char) ch);
            ch = in.read();
        }
        return sb.toString();
    }

    /** ACCEPT into an unsigned integer DISPLAY field of {@code n} digits (window = n characters). */
    private long acceptNumeric(int n) throws IOException {
        String s = readLine();
        if (s == null) {
            return 0;
        }
        String w = s.length() > n ? s.substring(0, n) : s;
        int i = 0;
        int len = w.length();
        while (i < len && w.charAt(i) == ' ') {
            i++;
        }
        if (i < len && (w.charAt(i) == '+' || w.charAt(i) == '-')) {
            i++;
            while (i < len && w.charAt(i) == ' ') {
                i++;
            }
        }
        StringBuilder ip = new StringBuilder();
        boolean dot = false;
        boolean any = false;
        for (; i < len; i++) {
            char c = w.charAt(i);
            if (c >= '0' && c <= '9') {
                any = true;
                if (!dot) {
                    ip.append(c);
                }
            } else if (c == '.' && !dot) {
                dot = true;
            } else if (c != ',') {
                break;
            }
        }
        while (i < len && w.charAt(i) == ' ') {
            i++;
        }
        if (i < len) {
            char c = w.charAt(i);
            if (!((c == '+' || c == '-') && w.substring(i + 1).trim().isEmpty())) {
                return 0;
            }
        }
        if (!any) {
            return 0;
        }
        String ints = ip.length() > n ? ip.substring(ip.length() - n) : ip.toString();
        return ints.isEmpty() ? 0 : Long.parseLong(ints);
    }

    private static String num(long v, int digits) {
        StringBuilder s = new StringBuilder(Long.toString(v));
        while (s.length() < digits) {
            s.insert(0, '0');
        }
        return s.toString();
    }

    private static String dec(long v) {
        String s = num(v, 7);
        return s.substring(0, 5) + "." + s.substring(5);
    }
}
