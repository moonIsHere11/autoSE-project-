package corpus;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;

/**
 * Hand translation of DIVREM. Numerics are {@code long}s scaled by 10^scale. Java's integer
 * division and {@code %} truncate toward zero, which is exactly COBOL's truncation and its
 * remainder sign rule (the remainder takes the sign of the dividend).
 */
public class Divrem {
    long wsDividend;            // S9(2)
    long wsDivisor;             // 9
    long wsQuot;                // S9(2)
    long wsRem;                 // S9
    long wsQuotR;               // S9(2)V9, scale 1
    long wsRemR;                // S9V99, scale 2
    long wsRatio = 0;           // S9V9 VALUE 0, scale 1
    String wsRatioFlag = " ";   // X VALUE SPACE
    long wsUquot = 77;          // 9(2) VALUE 77
    long wsAcc = 120;           // S9(3) VALUE 120
    long wsCheck;               // S9(3)
    String wsStatus = "    ";   // X(4)
    String wsKind = "         "; // X(9)
    String wsDivClass = "        "; // X(8)
    long wsGcdA;                // 9(2)
    long wsGcdB;                // 9(2)
    long wsGcdQ;                // 9(2)
    long wsGcdT;                // 9(2)
    long wsSteps = 0;           // 9(2) VALUE 0
    int returnCode;

    private final BufferedReader in =
            new BufferedReader(new InputStreamReader(System.in, StandardCharsets.ISO_8859_1));
    private final StringBuilder out = new StringBuilder();

    public static void main(String[] args) throws IOException {
        Divrem p = new Divrem();
        p.mainPara();
        System.out.write(p.out.toString().getBytes(StandardCharsets.ISO_8859_1));
        System.out.flush();
        System.exit(p.returnCode);
    }

    void mainPara() throws IOException {
        getOperands();
        doDivide();
        classifyResult();
        findGcd();
        showResult();
        setReturn();
    }

    void getOperands() throws IOException {
        wsDividend = acceptNumeric(2, 2, 0, true);
        wsDivisor = acceptNumeric(1, 1, 0, false);
    }

    void doDivide() {
        if (wsDivisor == 0) {
            wsStatus = "ZDIV";                       // ON SIZE ERROR: targets unchanged
        } else {
            long q = wsDividend / wsDivisor;
            wsQuot = q % 100;
            wsRem = (wsDividend - q * wsDivisor) % 10;
            wsStatus = "OK  ";
        }
        if (wsDivisor != 0) {
            long n = wsDividend * 10;                // quotient at scale 1
            long qt = n / wsDivisor;                 // truncated quotient
            long r = n % wsDivisor;
            long qr = qt;
            if (2 * (r < 0 ? -r : r) >= wsDivisor) {
                qr = qt + (n < 0 ? -1 : 1);          // ROUNDED: half away from zero
            }
            wsQuotR = qr % 1000;
            wsRemR = ((n - qt * wsDivisor) * 10) % 1000; // remainder uses the truncated quotient
        }
        if (wsDivisor == 0) {
            wsRatioFlag = "Y";
        } else {
            long n = wsDividend * 10;
            long q = n / wsDivisor;
            long r = n % wsDivisor;
            if (2 * (r < 0 ? -r : r) >= wsDivisor) {
                q = q + (n < 0 ? -1 : 1);
            }
            if (q >= 100 || q <= -100) {
                wsRatioFlag = "Y";
            } else {
                wsRatio = q;
                wsRatioFlag = "N";
            }
        }
        if (wsDivisor != 0) {
            wsAcc = (wsAcc / wsDivisor) % 1000;
        }
        if (wsDivisor != 0) {
            long q = wsDividend / wsDivisor;
            wsUquot = (q < 0 ? -q : q) % 100;        // unsigned target drops the sign
        }
        wsCheck = (wsQuot * wsDivisor + wsRem) % 1000;
    }

    void classifyResult() {
        if (wsDivisor == 0) {
            wsKind = "UNDEFINED";
        } else if (wsRem == 0 && wsDividend < 0) {
            wsKind = "NEG-EXACT";
        } else if (wsRem == 0) {
            wsKind = "EXACT    ";
        } else if (wsRem < 0 && wsDivisor >= 1 && wsDivisor <= 3) {
            wsKind = "NEG-SMALL";
        } else {
            wsKind = "INEXACT  ";
        }
        if (wsDivisor == 0) {
            wsDivClass = "NONE    ";
        } else if (wsDivisor >= 1 && wsDivisor <= 3) {
            wsDivClass = "LOW-DIV ";
        } else if (wsQuot == 0) {
            wsDivClass = "ZERO-Q  ";
        } else if (wsQuot >= -9 && wsQuot <= -1) {
            wsDivClass = "NEG-Q   ";
        } else {
            wsDivClass = "HIGH-DIV";
        }
    }

    void findGcd() {
        wsGcdA = (wsDividend < 0 ? -wsDividend : wsDividend) % 100;
        wsGcdB = wsDivisor;
        while (wsGcdB != 0) {
            wsGcdQ = (wsGcdA / wsGcdB) % 100;
            wsGcdT = (wsGcdA % wsGcdB) % 100;
            wsGcdA = wsGcdB;
            wsGcdB = wsGcdT;
            wsSteps = (wsSteps + 1) % 100;
        }
    }

    void showResult() {
        line("DIVIDEND " + signed(wsDividend, 2, 0) + " DIVISOR " + unsigned(wsDivisor, 1, 0)
                + " STATUS " + wsStatus);
        line("QUOT " + signed(wsQuot, 2, 0) + " REM " + signed(wsRem, 1, 0) + " CHECK " + signed(wsCheck, 3, 0));
        line("QUOT-R " + signed(wsQuotR, 2, 1) + " REM-R " + signed(wsRemR, 1, 2));
        line("RATIO " + signed(wsRatio, 1, 1) + " SIZE " + wsRatioFlag + " UQUOT " + unsigned(wsUquot, 2, 0)
                + " ACC " + signed(wsAcc, 3, 0));
        line("KIND " + wsKind + " CLASS " + wsDivClass + " GCD " + unsigned(wsGcdA, 2, 0)
                + " STEPS " + unsigned(wsSteps, 2, 0));
    }

    void setReturn() {
        if (wsDivisor == 0) {
            returnCode = 8;
        } else if (wsRem != 0) {
            returnCode = 1;
        } else {
            returnCode = 0;
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

    /** ACCEPT into a numeric DISPLAY field (first byte-length characters, de-edited); EOF gives 0. */
    private long acceptNumeric(int window, int intDigits, int scale, boolean isSigned) throws IOException {
        String s = readLine();
        if (s == null) {
            return 0;
        }
        return deedit(s.length() > window ? s.substring(0, window) : s, intDigits, scale, isSigned);
    }

    static long deedit(String w, int intDigits, int scale, boolean isSigned) {
        int i = 0;
        int n = w.length();
        while (i < n && w.charAt(i) == ' ') {
            i++;
        }
        boolean neg = false;
        if (i < n && (w.charAt(i) == '+' || w.charAt(i) == '-')) {
            neg = w.charAt(i) == '-';
            i++;
            while (i < n && w.charAt(i) == ' ') {
                i++;
            }
        }
        StringBuilder ip = new StringBuilder();
        StringBuilder fp = new StringBuilder();
        boolean dot = false;
        for (; i < n; i++) {
            char c = w.charAt(i);
            if (c >= '0' && c <= '9') {
                (dot ? fp : ip).append(c);
            } else if (c == '.' && !dot) {
                dot = true;
            } else if (c != ',') {
                break;
            }
        }
        while (i < n && w.charAt(i) == ' ') {
            i++;
        }
        if (i < n) {
            char c = w.charAt(i);
            boolean onlySign = (c == '+' || c == '-') && w.substring(i + 1).trim().isEmpty();
            if (!onlySign || scale > 0) {
                return 0;
            }
        }
        if (ip.length() + fp.length() == 0) {
            return 0;
        }
        long v = 0;
        String ints = ip.length() > intDigits ? ip.substring(ip.length() - intDigits) : ip.toString();
        for (int k = 0; k < ints.length(); k++) {
            v = v * 10 + (ints.charAt(k) - '0');
        }
        for (int k = 0; k < scale; k++) {
            v = v * 10 + (k < fp.length() ? fp.charAt(k) - '0' : 0);
        }
        return (neg && isSigned) ? -v : v;
    }

    static String unsigned(long v, int intDigits, int scale) {
        String digits = Long.toString(v < 0 ? -v : v);
        StringBuilder sb = new StringBuilder();
        for (int k = digits.length(); k < intDigits + scale; k++) {
            sb.append('0');
        }
        sb.append(digits);
        if (scale > 0) {
            sb.insert(sb.length() - scale, '.');
        }
        return sb.toString();
    }

    static String signed(long v, int intDigits, int scale) {
        return (v < 0 ? "-" : "+") + unsigned(v, intDigits, scale);
    }
}
