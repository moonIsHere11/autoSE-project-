package corpus;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;

/**
 * Hand translation of TAXCALC. Numerics are {@code long} values scaled by 10^scale
 * (e.g. WS-INCOME PIC 9(6)V99 holds cents). The computational paragraph uses only
 * long arithmetic so that it stays JBMC-friendly; formatting lives in helpers.
 */
public class Taxcalc {
    int wsCategory;                 // 9
    int wsIncomeK;                  // 9(2)
    long wsIncome;                  // 9(6)V99, scale 2
    long wsDeduction;               // 9(5)V99, scale 2
    long wsTaxable;                 // S9(6)V99, scale 2
    long wsGap;                     // 9(6)V99, scale 2
    long wsRate;                    // V999, scale 3
    String wsBracket = "      ";    // X(6)
    long wsTax;                     // 9(5)V99
    long wsTaxTrunc;                // 9(5)V99
    long wsSurcharge = 0;           // 9(3)V99 VALUE 0
    long wsTotalTax;                // 9(5)V99
    long wsEffRate = 0;             // 9(2)V99 VALUE 0
    String wsSizeFlag = "N";        // X VALUE "N"
    String wsRateFlag = "N";        // X VALUE "N"
    int returnCode;

    private final BufferedReader in =
            new BufferedReader(new InputStreamReader(System.in, StandardCharsets.ISO_8859_1));
    private final StringBuilder out = new StringBuilder();

    public static void main(String[] args) throws IOException {
        Taxcalc p = new Taxcalc();
        p.mainPara();
        System.out.write(p.out.toString().getBytes(StandardCharsets.ISO_8859_1));
        System.out.flush();
        System.exit(p.returnCode);
    }

    void mainPara() throws IOException {
        readInput();
        if (wsCategory <= 3) { // CAT-VALID: 0 THRU 3
            computeTax();
            showResult();
        } else {
            line("INVALID CATEGORY " + unsigned(wsCategory, 1, 0));
            returnCode = 4;
        }
    }

    void readInput() throws IOException {
        wsCategory = (int) acceptNumeric(1, 1, 0, false);
        wsIncomeK = (int) acceptNumeric(2, 2, 0, false);
    }

    void computeTax() {
        wsIncome = (wsIncomeK * 1000L * 100L) % 100000000L;
        if (wsCategory == 0) {
            wsDeduction = 9999999L;
        } else if (wsCategory == 1) {
            wsDeduction = 1255000L;
        } else if (wsCategory == 2) {
            wsDeduction = 2510000L;
        } else {
            wsDeduction = 1880050L;
        }
        wsTaxable = (wsIncome - wsDeduction) % 100000000L;
        long gap = wsIncome - wsDeduction;
        if (gap < 0) {
            gap = -gap; // unsigned target: sign dropped
        }
        wsGap = gap % 100000000L;
        if (wsTaxable < 0) {
            wsTaxable = 0;
        }
        if (wsIncomeK <= 9) {
            wsRate = 0;
            wsBracket = "NIL   ";
        } else if (wsIncomeK <= 39) {
            wsRate = 100;
            wsBracket = "LOW   ";
        } else if (wsIncomeK <= 84) {
            wsRate = 225;
            wsBracket = "MIDDLE";
        } else {
            wsRate = 333;
            wsBracket = "HIGH  ";
        }
        long product = wsTaxable * wsRate;                 // scale 5, never negative
        wsTax = ((product + 500) / 1000) % 10000000L;      // ROUNDED to scale 2
        wsTaxTrunc = (product / 1000) % 10000000L;         // truncated
        long surcharge = (wsTax * 75 + 500) / 1000;        // WS-TAX * 0.075, ROUNDED
        boolean overflow = surcharge > 99999L;             // 9(3)V99
        if (overflow) {
            wsSizeFlag = "Y";                              // target left unchanged
        } else {
            wsSurcharge = surcharge;
            wsSizeFlag = "N";
        }
        wsTotalTax = (wsTax + wsSurcharge) % 10000000L;
        if (wsIncome == 0) {
            wsRateFlag = "Z";                              // divide by zero: size error
        } else {
            long n = wsTotalTax * 10000L;                  // (total * 100 / income) at scale 2
            long q = n / wsIncome;
            long r = n % wsIncome;
            if (2 * r >= wsIncome) {
                q = q + 1;
            }
            if (q > 9999L) {
                wsRateFlag = "Z";
            } else {
                wsEffRate = q;
            }
        }
        if (overflow) {
            returnCode = 2;
        }
    }

    void showResult() {
        line("CATEGORY " + unsigned(wsCategory, 1, 0) + " INCOME " + unsigned(wsIncome, 6, 2)
                + " BRACKET " + wsBracket);
        line("DEDUCTION " + unsigned(wsDeduction, 5, 2) + " TAXABLE " + signed(wsTaxable, 6, 2)
                + " GAP " + unsigned(wsGap, 6, 2));
        line("TAX " + unsigned(wsTax, 5, 2) + " TRUNC " + unsigned(wsTaxTrunc, 5, 2)
                + " SURCHARGE " + unsigned(wsSurcharge, 3, 2) + " OVERFLOW " + wsSizeFlag);
        line("TOTAL " + unsigned(wsTotalTax, 5, 2) + " EFFECTIVE " + unsigned(wsEffRate, 2, 2)
                + "% FLAG " + wsRateFlag);
    }

    // ---------------------------------------------------------------- runtime helpers

    private void line(String s) {
        out.append(s).append('\n');
    }

    /** One stdin line terminated by '\n'; null at end of input. */
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

    /**
     * ACCEPT into a numeric DISPLAY field: GnuCOBOL takes the first {@code window} (byte length)
     * characters, de-edits them and MOVEs the value (decimal alignment, truncation). EOF gives 0.
     */
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

    /** DISPLAY of an unsigned numeric field with {@code intDigits} integer and {@code scale} decimal digits. */
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

    /** DISPLAY of a signed numeric field: the sign is always shown, leading. */
    static String signed(long v, int intDigits, int scale) {
        return (v < 0 ? "-" : "+") + unsigned(v, intDigits, scale);
    }
}
