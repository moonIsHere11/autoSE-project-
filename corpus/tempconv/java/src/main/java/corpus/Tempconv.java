package corpus;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.charset.StandardCharsets;

/**
 * Hand translation of TEMPCONV using {@link BigDecimal} for every numeric field.
 * COBOL arithmetic is reproduced exactly: intermediate quotients are truncated at a large
 * scale (GnuCOBOL keeps 38 extra decimal digits), the final store either truncates or
 * rounds half away from zero, and high-order digits are dropped without ON SIZE ERROR.
 */
public class Tempconv {
    private static final BigDecimal K_OFFSET = new BigDecimal("273.15");
    private static final BigDecimal NINE_FIFTHS = new BigDecimal("1.8");
    private static final BigDecimal THIRTY_TWO = BigDecimal.valueOf(32);

    BigDecimal wsTemp = BigDecimal.ZERO;                 // S9(2)
    int wsMode;                                          // 9
    BigDecimal wsCelsius = BigDecimal.ZERO.setScale(2);  // S9(3)V99
    BigDecimal wsFahr = BigDecimal.ZERO.setScale(2);     // S9(3)V99
    BigDecimal wsKelvin = BigDecimal.ZERO.setScale(2);   // 9(3)V99
    BigDecimal wsResult = BigDecimal.ZERO.setScale(1);   // S9(3)V9
    BigDecimal wsResultT = BigDecimal.ZERO.setScale(1);  // S9(3)V9
    BigDecimal wsMagnitude = BigDecimal.ZERO.setScale(1); // 9(3)V9
    BigDecimal wsThirds = BigDecimal.ZERO.setScale(1);   // S9(3)V9
    BigDecimal wsThirdsR = BigDecimal.ZERO.setScale(1);  // S9(3)V9
    BigDecimal wsSpread = BigDecimal.ZERO.setScale(1);   // S9(2)V9
    String wsSpreadFlag = "   ";                         // X(3)
    String wsFeel = "        ";                          // X(8)
    int returnCode;

    private final BufferedReader in =
            new BufferedReader(new InputStreamReader(System.in, StandardCharsets.ISO_8859_1));
    private final StringBuilder out = new StringBuilder();

    public static void main(String[] args) throws IOException {
        Tempconv p = new Tempconv();
        p.mainPara();
        System.out.write(p.out.toString().getBytes(StandardCharsets.ISO_8859_1));
        System.out.flush();
        System.exit(p.returnCode);
    }

    void mainPara() throws IOException {
        getInput();
        if (wsMode >= 1 && wsMode <= 5) {
            convert();
            classify();
            reportOut();
        } else {
            line("UNKNOWN MODE " + wsMode + " FOR " + display(wsTemp, 2, 0, true));
            returnCode = 3;
        }
    }

    void getInput() throws IOException {
        wsTemp = BigDecimal.valueOf(acceptNumeric(2, 2, 0, true), 0);
        wsMode = (int) acceptNumeric(1, 1, 0, false);
    }

    void convert() {
        BigDecimal t = wsTemp;
        switch (wsMode) {
            case 1:
                wsCelsius = store(t, 3, 2, true, false);
                wsFahr = store(div(t.multiply(BigDecimal.valueOf(9)), BigDecimal.valueOf(5)).add(THIRTY_TWO), 3, 2, true, true);
                wsResult = store(div(t.multiply(BigDecimal.valueOf(9)), BigDecimal.valueOf(5)).add(THIRTY_TWO), 3, 1, true, true);
                wsResultT = store(div(t.multiply(BigDecimal.valueOf(9)), BigDecimal.valueOf(5)).add(THIRTY_TWO), 3, 1, true, false);
                break;
            case 2:
                wsFahr = store(t, 3, 2, true, false);
                wsCelsius = store(div(t.subtract(THIRTY_TWO).multiply(BigDecimal.valueOf(5)), BigDecimal.valueOf(9)), 3, 2, true, true);
                wsResult = store(div(t.subtract(THIRTY_TWO).multiply(BigDecimal.valueOf(5)), BigDecimal.valueOf(9)), 3, 1, true, true);
                wsResultT = store(div(t.subtract(THIRTY_TWO), BigDecimal.valueOf(9)).multiply(BigDecimal.valueOf(5)), 3, 1, true, false);
                break;
            case 3:
                wsCelsius = store(t, 3, 2, true, false);
                wsFahr = store(t.multiply(NINE_FIFTHS).add(THIRTY_TWO), 3, 2, true, true);
                wsResult = store(t.add(K_OFFSET), 3, 1, true, true);
                wsResultT = store(t.add(K_OFFSET), 3, 1, true, false);
                break;
            case 4:
                wsFahr = store(t, 3, 2, true, false);
                wsCelsius = store(div(t.subtract(THIRTY_TWO), NINE_FIFTHS), 3, 2, true, true);
                wsResult = store(div(t.subtract(THIRTY_TWO), NINE_FIFTHS).add(K_OFFSET), 3, 1, true, true);
                wsResultT = store(div(t.subtract(THIRTY_TWO), NINE_FIFTHS).add(K_OFFSET), 3, 1, true, false);
                break;
            default:
                wsCelsius = store(t, 3, 2, true, false);
                wsFahr = store(div(t.multiply(BigDecimal.valueOf(9)), BigDecimal.valueOf(5)).add(THIRTY_TWO), 3, 2, true, true);
                wsResult = store(div(wsFahr.subtract(THIRTY_TWO).multiply(BigDecimal.valueOf(5)), BigDecimal.valueOf(9)), 3, 1, true, true);
                wsResultT = store(div(wsFahr.subtract(THIRTY_TWO), BigDecimal.valueOf(9)).multiply(BigDecimal.valueOf(5)), 3, 1, true, false);
                break;
        }
        wsKelvin = store(wsCelsius.add(K_OFFSET), 3, 2, false, true);
        wsMagnitude = store(wsResult, 3, 1, false, false);
        wsThirds = store(div(t, BigDecimal.valueOf(3)).multiply(BigDecimal.valueOf(3)), 3, 1, true, false);
        wsThirdsR = store(div(t, BigDecimal.valueOf(3)).multiply(BigDecimal.valueOf(3)), 3, 1, true, true);
        BigDecimal spread = wsFahr.subtract(wsCelsius);
        if (sizeError(spread, 2, 1, false)) {
            wsSpreadFlag = "OVF";
        } else {
            wsSpread = store(spread, 2, 1, true, false);
            wsSpreadFlag = "OK ";
        }
    }

    void classify() {
        if (wsCelsius.compareTo(BigDecimal.valueOf(-10)) < 0) {
            wsFeel = "FREEZING";
        } else if (wsCelsius.signum() < 0) {
            wsFeel = "COLD    ";
        } else if (wsCelsius.signum() == 0) {
            wsFeel = "ZERO    ";
        } else if (wsCelsius.compareTo(BigDecimal.valueOf(20)) < 0) {
            wsFeel = "MILD    ";
        } else if (wsCelsius.compareTo(BigDecimal.valueOf(30)) < 0) {
            wsFeel = "WARM    ";
        } else {
            wsFeel = "HOT     ";
        }
    }

    void reportOut() {
        line("MODE " + wsMode + " INPUT " + display(wsTemp, 2, 0, true));
        line("CELSIUS " + display(wsCelsius, 3, 2, true) + " FAHRENHEIT " + display(wsFahr, 3, 2, true)
                + " KELVIN " + display(wsKelvin, 3, 2, false));
        line("RESULT " + display(wsResult, 3, 1, true) + " TRUNCATED " + display(wsResultT, 3, 1, true)
                + " MAGNITUDE " + display(wsMagnitude, 3, 1, false));
        line("THIRDS " + display(wsThirds, 3, 1, true) + " ROUNDED " + display(wsThirdsR, 3, 1, true));
        line("SPREAD " + display(wsSpread, 2, 1, true) + " " + wsSpreadFlag + " FEEL " + wsFeel);
    }

    // ---------------------------------------------------------------- COBOL arithmetic helpers

    /** COBOL division: quotient truncated toward zero, 38 digits beyond the operands' scale. */
    static BigDecimal div(BigDecimal a, BigDecimal b) {
        int scale = 38 + Math.max(0, a.scale() - b.scale());
        return a.divide(b, scale, RoundingMode.DOWN);
    }

    /** Store a result in a PIC: ROUNDED (half away from zero) or truncation, then high-order truncation. */
    static BigDecimal store(BigDecimal v, int intDigits, int scale, boolean isSigned, boolean rounded) {
        BigDecimal r = v.setScale(scale, rounded ? RoundingMode.HALF_UP : RoundingMode.DOWN);
        r = r.remainder(BigDecimal.TEN.pow(intDigits));
        if (!isSigned || r.signum() == 0) {
            r = r.abs();
        }
        return r.setScale(scale);
    }

    /** True when the (rounded or truncated) value does not fit the integer digits of the PIC. */
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

    /** DISPLAY of a numeric DISPLAY field (signed: leading sign always shown). */
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
