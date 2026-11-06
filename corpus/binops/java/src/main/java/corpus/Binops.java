package corpus;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;

/**
 * Hand translation of BINOPS. COMP / BINARY / COMP-3 fields are truncated to their PIC digits
 * (binary-truncate: yes); COMP-5 fields are native 16-bit integers that are not truncated to
 * the PIC and wrap at the binary width.
 */
public class Binops {
    long wsA;                 // S9(4) COMP
    long wsB;                 // S9(4) COMP-5 (16-bit)
    long wsC;                 // 9(3) COMP-3
    long wsSum;               // S9(4) COMP
    String wsSumFlag = "   "; // X(3)
    long wsProd;              // S9(6) BINARY
    long wsProd5;             // S9(4) COMP-5
    long wsWide5;             // S9(4) COMP-5
    String wsWide5Flag = "   ";
    long wsDiffU;             // 9(4) COMP
    long wsSmall;             // 99 COMP
    long wsQuot = 1111;       // S9(4) COMP VALUE 1111
    long wsRem = 111;         // S9(3) COMP-3 VALUE 111
    String wsDivFlag = "    ";
    long wsRawNum;            // S9(4) COMP (2 bytes, big-endian, seen through REDEFINES)
    long wsHi;                // 9(3)
    long wsLo;                // 9(3)
    long wsRc;                // 9(2) COMP
    int returnCode;

    private final BufferedReader in =
            new BufferedReader(new InputStreamReader(System.in, StandardCharsets.ISO_8859_1));
    private final StringBuilder out = new StringBuilder();

    public static void main(String[] args) throws IOException {
        Binops p = new Binops();
        p.mainPara();
        System.out.write(p.out.toString().getBytes(StandardCharsets.ISO_8859_1));
        System.out.flush();
        System.exit(p.returnCode);
    }

    void mainPara() throws IOException {
        getInput();
        calculate();
        showBytes();
        showResults();
        returnCode = (int) wsRc;
    }

    void getInput() throws IOException {
        BigInteger a = acceptInteger();
        wsA = truncDigits(a, 4, true);
        BigInteger b = acceptInteger();
        wsB = wrap16(b);
        BigInteger c = acceptInteger();
        wsC = truncDigits(c, 3, false);
    }

    void calculate() {
        long sum = wsA + wsB;
        if (sum > 9999 || sum < -9999) {
            wsSumFlag = "OVF";
        } else {
            wsSum = sum;
            wsSumFlag = "OK ";
        }
        long prod = wsA * wsB;
        wsProd = (prod < 0 ? -1 : 1) * ((prod < 0 ? -prod : prod) % 1000000); // binary-truncate to 6 digits
        wsProd5 = wrap16(BigInteger.valueOf(wsA * 3));                    // COMP-5: no PIC truncation
        long wide = wsB * 2;
        if (wide > 32767 || wide < -32768) {
            wsWide5Flag = "OVF";
        } else {
            wsWide5 = wide;
            wsWide5Flag = "OK ";
        }
        long diff = wsC - wsA;
        wsDiffU = (diff < 0 ? -diff : diff) % 10000;                    // unsigned: sign dropped
        wsSmall = (wsB < 0 ? -wsB : wsB) % 100;
        if (wsC == 0) {
            wsDivFlag = "ZERO";
        } else {
            long q = wsA / wsC;
            wsQuot = q;
            wsRem = wsA - q * wsC;
            wsDivFlag = "OK  ";
        }
        wsRawNum = wsA;
        if (wsA >= -9999 && wsA <= -1) {
            wsRc = 3;
        } else if (wsA >= 0 && wsA <= 99) {
            wsRc = 1;
        } else {
            wsRc = 2;
        }
    }

    void showBytes() {
        long u = wsRawNum & 0xFFFF;               // two's complement, big-endian
        wsHi = (u >> 8) & 0xFF;                   // FUNCTION ORD(byte) - 1
        wsLo = u & 0xFF;
    }

    void showResults() {
        line("A " + signed(wsA, 4) + " B " + signed(wsB, 5) + " C " + unsigned(wsC, 3));
        line("SUM " + signed(wsSum, 4) + " " + wsSumFlag + " PROD " + signed(wsProd, 6) + " PROD5 " + signed(wsProd5, 5));
        line("WIDE5 " + signed(wsWide5, 5) + " " + wsWide5Flag + " DIFF-U " + unsigned(wsDiffU, 4) + " SMALL "
                + unsigned(wsSmall, 2));
        line("QUOT " + signed(wsQuot, 4) + " REM " + signed(wsRem, 3) + " " + wsDivFlag);
        line("BYTES " + unsigned(wsHi, 3) + " " + unsigned(wsLo, 3) + " RC " + unsigned(wsRc, 2));
    }

    // ---------------------------------------------------------------- runtime helpers

    private static long truncDigits(BigInteger v, int digits, boolean isSigned) {
        BigInteger m = v.abs().mod(BigInteger.TEN.pow(digits));
        long r = m.longValue();
        return (isSigned && v.signum() < 0) ? -r : r;
    }

    private static long wrap16(BigInteger v) {
        return v.shortValue();
    }

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

    /** ACCEPT into a binary / packed field: the whole line is de-edited; decimals are dropped. */
    private BigInteger acceptInteger() throws IOException {
        String w = readLine();
        if (w == null) {
            return BigInteger.ZERO;
        }
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
        boolean dot = false;
        boolean any = false;
        for (; i < n; i++) {
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
        while (i < n && w.charAt(i) == ' ') {
            i++;
        }
        if (i < n) {
            char c = w.charAt(i);
            if (!((c == '+' || c == '-') && w.substring(i + 1).trim().isEmpty())) {
                return BigInteger.ZERO;
            }
        }
        if (!any || ip.length() == 0) {
            return BigInteger.ZERO;
        }
        BigInteger v = new BigInteger(ip.toString());
        return neg ? v.negate() : v;
    }

    private static String unsigned(long v, int digits) {
        StringBuilder s = new StringBuilder(Long.toString(v < 0 ? -v : v));
        while (s.length() < digits) {
            s.insert(0, '0');
        }
        return s.toString();
    }

    private static String signed(long v, int digits) {
        return (v < 0 ? "-" : "+") + unsigned(v, digits);
    }
}
