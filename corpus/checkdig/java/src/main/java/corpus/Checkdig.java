package corpus;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;

/** Hand translation of CHECKDIG: mod-11 check digits for up to three account numbers. */
public class Checkdig {
    String wsAccount = spaces(10); // X(10)
    int wsAcctNo = 0;              // 9(1) VALUE 0
    int wsValidCount = 0;          // 9(1) VALUE 0
    int wsI;                       // 9(2)
    int wsWeight;                  // 9(2)
    int wsDigit;                   // 9(1)
    int wsGiven;                   // 9(1)
    int wsSum;                     // 9(3)
    int wsQuot;                    // 9(3)
    int wsRem;                     // 9(2)
    int wsCheck;                   // 9(2)
    int wsCheckD;                  // 9(1)
    String wsCheckX = spaces(1);   // X(1)
    int wsBad;                     // 9(2)
    String wsResult = spaces(7);   // X(7)
    int returnCode;

    private final BufferedReader in =
            new BufferedReader(new InputStreamReader(System.in, StandardCharsets.ISO_8859_1));
    private final StringBuilder out = new StringBuilder();

    public static void main(String[] args) throws IOException {
        Checkdig p = new Checkdig();
        p.mainPara();
        System.out.write(p.out.toString().getBytes(StandardCharsets.ISO_8859_1));
        System.out.flush();
        System.exit(p.returnCode);
    }

    void mainPara() throws IOException {
        for (int k = 0; k < 3; k++) {
            checkOne();
        }
        out.append("VALID ACCOUNTS: ").append(num(wsValidCount, 1)).append('\n');
    }

    void checkOne() throws IOException {
        wsAcctNo = (wsAcctNo + 1) % 10;
        wsAccount = acceptAlnum(10);
        scanChars();
        if (wsBad > 0) {
            out.append(num(wsAcctNo, 1)).append(" [").append(wsAccount).append("] REJECTED: ")
                    .append(num(wsBad, 2)).append(" NON-DIGIT(S)").append('\n');
        } else {
            weighDigits();
            deriveCheck();
            reportResult();
        }
    }

    void scanChars() {
        wsBad = 0;
        for (wsI = 1; wsI <= 10; wsI++) {
            char c = wsAccount.charAt(wsI - 1);
            if (c < '0' || c > '9') {
                wsBad = (wsBad + 1) % 100;
            }
        }
    }

    void weighDigits() {
        wsSum = 0;
        for (wsWeight = 10; !(wsWeight < 2); wsWeight--) {
            wsI = 11 - wsWeight;
            wsDigit = wsAccount.charAt(wsI - 1) - '0';
            wsSum = (wsSum + wsDigit * wsWeight) % 1000;
        }
    }

    void deriveCheck() {
        wsQuot = (wsSum / 11) % 1000;
        wsRem = (wsSum % 11) % 100;
        if (wsRem == 0) {
            wsCheck = 0;
        } else if (wsRem == 1) {
            wsCheck = 10;
        } else {
            wsCheck = (11 - wsRem) % 100;
        }
    }

    void reportResult() {
        wsGiven = wsAccount.charAt(9) - '0';
        if (wsCheck == 10) {
            wsCheckX = "X";
            wsResult = "NOCHECK";
        } else {
            wsCheckD = wsCheck % 10;
            wsCheckX = num(wsCheckD, 1);
            if (wsCheckD == wsGiven) {
                wsResult = pad("VALID", 7);
                wsValidCount = (wsValidCount + 1) % 10;
            } else {
                wsResult = pad("INVALID", 7);
            }
        }
        out.append(num(wsAcctNo, 1)).append(' ').append(wsAccount).append(' ').append(wsResult)
                .append(" CHECK=").append(wsCheckX).append(" SUM=").append(num(wsSum, 3))
                .append(" Q=").append(num(wsQuot, 3)).append(" R=").append(num(wsRem, 2)).append('\n');
    }

    // ---------------------------------------------------------------- runtime helpers

    /** One stdin line terminated by '\n' only; null at end of input. */
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

    /** ACCEPT into X(n): first n characters, space padded; at end of input the field becomes spaces. */
    private String acceptAlnum(int n) throws IOException {
        String line = readLine();
        if (line == null) {
            return spaces(n);
        }
        return pad(line.length() > n ? line.substring(0, n) : line, n);
    }

    private static String spaces(int n) {
        return " ".repeat(n);
    }

    private static String pad(String s, int n) {
        return s.length() >= n ? s.substring(0, n) : s + spaces(n - s.length());
    }

    /** DISPLAY of an unsigned integer DISPLAY field with `digits` digits. */
    private static String num(long v, int digits) {
        StringBuilder s = new StringBuilder(Long.toString(Math.abs(v)));
        while (s.length() < digits) {
            s.insert(0, '0');
        }
        return s.toString();
    }
}
