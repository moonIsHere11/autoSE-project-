package corpus;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.charset.StandardCharsets;

/**
 * Hand translation of LOANCALC using {@link BigDecimal} for every numeric field. Stores into a
 * PIC either truncate or round half away from zero, then drop high-order digits (no ON SIZE
 * ERROR) and, for unsigned fields, the sign. Divisions keep GnuCOBOL's 38 extra digits.
 */
public class Loancalc {
    private static final BigDecimal B1200 = BigDecimal.valueOf(1200);

    BigDecimal wsPrincipal = BigDecimal.ZERO.setScale(2);   // 9(6)V99
    BigDecimal wsRate = BigDecimal.ZERO.setScale(2);        // 9(2)V99
    BigDecimal wsTerm = BigDecimal.ZERO;                    // 9(3)
    BigDecimal wsLoanNo = BigDecimal.ZERO;                  // 9(2) VALUE 0
    String wsDone = "N";                                    // X VALUE "N"
    BigDecimal wsBalance = BigDecimal.ZERO.setScale(2);     // S9(6)V99
    BigDecimal wsMonthlyRate = BigDecimal.ZERO.setScale(6); // V9(6)
    BigDecimal wsInterest = BigDecimal.ZERO.setScale(2);    // 9(5)V99
    BigDecimal wsPrinPart = BigDecimal.ZERO.setScale(2);    // 9(6)V99
    BigDecimal wsPayment = BigDecimal.ZERO.setScale(2);     // 9(6)V99
    BigDecimal wsTotalInt = BigDecimal.ZERO.setScale(2);    // 9(7)V99
    BigDecimal wsEstimate = BigDecimal.ZERO.setScale(2);    // 9(7)V99
    String wsEstFlag = "    ";                              // X(4)
    BigDecimal wsMonth = BigDecimal.ZERO;                   // 9(3)
    BigDecimal wsMaxPay = BigDecimal.ZERO.setScale(2);      // 9(4)V99
    String wsPayFlag = "    ";                              // X(4)
    BigDecimal wsGrandPrin = BigDecimal.ZERO.setScale(2);   // 9(8)V99 VALUE 0
    BigDecimal wsGrandInt = BigDecimal.ZERO.setScale(2);    // 9(8)V99 VALUE 0
    BigDecimal wsSkipped = BigDecimal.ZERO;                 // 9(2) VALUE 0
    int returnCode;

    private final BufferedReader in =
            new BufferedReader(new InputStreamReader(System.in, StandardCharsets.ISO_8859_1));
    private final StringBuilder out = new StringBuilder();

    public static void main(String[] args) throws IOException {
        Loancalc p = new Loancalc();
        p.mainPara();
        System.out.write(p.out.toString().getBytes(StandardCharsets.ISO_8859_1));
        System.out.flush();
        System.exit(p.returnCode);
    }

    void mainPara() throws IOException {
        readRequest();
        while (!wsDone.equals("Y")) {
            if (wsTerm.compareTo(BigDecimal.ONE) >= 0 && wsTerm.compareTo(BigDecimal.valueOf(360)) <= 0) {
                amortize();
                showLoan();
            } else {
                line("LOAN " + display(wsLoanNo, 2, 0, false) + " REJECTED: TERM " + display(wsTerm, 3, 0, false));
                wsSkipped = store(wsSkipped.add(BigDecimal.ONE), 2, 0, false, false);
            }
            readRequest();
        }
        line("LOANS " + display(wsLoanNo, 2, 0, false) + " SKIPPED " + display(wsSkipped, 2, 0, false));
        line("TOTAL PRINCIPAL " + display(wsGrandPrin, 8, 2, false) + " TOTAL INTEREST "
                + display(wsGrandInt, 8, 2, false));
        if (wsSkipped.signum() > 0) {
            returnCode = 4;
        }
    }

    void readRequest() throws IOException {
        wsPrincipal = acceptNumeric(8, 6, 2);
        if (wsPrincipal.signum() == 0 || wsLoanNo.compareTo(BigDecimal.valueOf(20)) >= 0) {
            wsDone = "Y";
        } else {
            wsRate = acceptNumeric(4, 2, 2);
            wsTerm = acceptNumeric(3, 3, 0);
            wsLoanNo = store(wsLoanNo.add(BigDecimal.ONE), 2, 0, false, false);
        }
    }

    void amortize() {
        wsBalance = store(wsPrincipal, 6, 2, true, false);
        wsMonthlyRate = store(div(wsRate, B1200), 0, 6, false, true);
        wsPrinPart = store(div(wsPrincipal, wsTerm), 6, 2, false, true);
        wsTotalInt = BigDecimal.ZERO.setScale(2);
        wsMaxPay = BigDecimal.ZERO.setScale(2);
        wsPayFlag = "OK  ";
        BigDecimal est = div(div(wsPrincipal.multiply(wsRate), B1200).multiply(wsTerm.add(BigDecimal.ONE)),
                BigDecimal.valueOf(2));
        if (sizeError(est, 7, 2, true)) {
            wsEstimate = BigDecimal.ZERO.setScale(2);
            wsEstFlag = "OVF ";
        } else {
            wsEstimate = store(est, 7, 2, false, true);
            wsEstFlag = "OK  ";
        }
        for (wsMonth = BigDecimal.ONE; wsMonth.compareTo(wsTerm) <= 0; wsMonth = wsMonth.add(BigDecimal.ONE)) {
            wsInterest = store(wsBalance.multiply(wsMonthlyRate), 5, 2, false, true);
            if (wsMonth.compareTo(wsTerm) == 0) {
                wsPrinPart = store(wsBalance, 6, 2, false, false);
            }
            wsPayment = store(wsPrinPart.add(wsInterest), 6, 2, false, false);
            wsBalance = store(wsBalance.subtract(wsPrinPart), 6, 2, true, false);
            wsTotalInt = store(wsTotalInt.add(wsInterest), 7, 2, false, false);
            if (wsPayment.compareTo(wsMaxPay) > 0) {
                if (sizeError(wsPayment, 4, 2, false)) {
                    wsPayFlag = "HIGH";
                } else {
                    wsMaxPay = store(wsPayment, 4, 2, false, false);
                }
            }
        }
        wsMonth = store(wsMonth, 3, 0, false, false);
        wsGrandPrin = store(wsGrandPrin.add(wsPrincipal), 8, 2, false, false);
        wsGrandInt = store(wsGrandInt.add(wsTotalInt), 8, 2, false, false);
    }

    void showLoan() {
        line("LOAN " + display(wsLoanNo, 2, 0, false) + " PRINCIPAL " + display(wsPrincipal, 6, 2, false)
                + " RATE " + display(wsRate, 2, 2, false) + " TERM " + display(wsTerm, 3, 0, false));
        line("  MONTHLY RATE " + display(wsMonthlyRate, 0, 6, false) + " PRINCIPAL PART "
                + display(wsPrinPart, 6, 2, false) + " FINAL BALANCE " + display(wsBalance, 6, 2, true));
        line("  INTEREST " + display(wsTotalInt, 7, 2, false) + " ESTIMATE " + display(wsEstimate, 7, 2, false)
                + " " + wsEstFlag + " MAX PAYMENT " + display(wsMaxPay, 4, 2, false) + " " + wsPayFlag);
    }

    // ---------------------------------------------------------------- COBOL arithmetic helpers

    static BigDecimal div(BigDecimal a, BigDecimal b) {
        return a.divide(b, 38 + Math.max(0, a.scale() - b.scale()), RoundingMode.DOWN);
    }

    static BigDecimal store(BigDecimal v, int intDigits, int scale, boolean isSigned, boolean rounded) {
        BigDecimal r = v.setScale(scale, rounded ? RoundingMode.HALF_UP : RoundingMode.DOWN);
        r = r.remainder(BigDecimal.TEN.pow(intDigits));
        if (!isSigned || r.signum() == 0) {
            r = r.abs();
        }
        return r.setScale(scale);
    }

    static boolean sizeError(BigDecimal v, int intDigits, int scale, boolean rounded) {
        BigDecimal r = v.setScale(scale, rounded ? RoundingMode.HALF_UP : RoundingMode.DOWN);
        return r.abs().compareTo(BigDecimal.TEN.pow(intDigits)) >= 0;
    }

    // ---------------------------------------------------------------- I/O helpers

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

    /** ACCEPT into an unsigned numeric DISPLAY field (first byte-length characters, de-edited). */
    private BigDecimal acceptNumeric(int window, int intDigits, int scale) throws IOException {
        String s = readLine();
        if (s == null) {
            return BigDecimal.ZERO.setScale(scale);
        }
        return BigDecimal.valueOf(deedit(s.length() > window ? s.substring(0, window) : s, intDigits, scale), scale);
    }

    static long deedit(String w, int intDigits, int scale) {
        int i = 0;
        int n = w.length();
        while (i < n && w.charAt(i) == ' ') {
            i++;
        }
        if (i < n && (w.charAt(i) == '+' || w.charAt(i) == '-')) {
            i++; // unsigned target: the sign is dropped
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
        return v;
    }

    static String display(BigDecimal v, int intDigits, int scale, boolean isSigned) {
        BigDecimal r = v.setScale(scale, RoundingMode.DOWN);
        String digits = r.unscaledValue().abs().toString();
        StringBuilder sb = new StringBuilder();
        for (int k = digits.length(); k < intDigits + scale; k++) {
            sb.append('0');
        }
        sb.append(digits);
        if (scale > 0) {
            sb.insert(sb.length() - scale, '.');
        }
        if (isSigned) {
            sb.insert(0, r.signum() < 0 ? '-' : '+');
        }
        return sb.toString();
    }
}
