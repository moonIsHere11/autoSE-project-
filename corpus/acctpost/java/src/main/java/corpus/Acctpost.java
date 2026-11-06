package corpus;

import java.io.IOException;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;

/**
 * Hand translation of ACCTPOST using {@link BigDecimal} for every numeric field. Input records
 * are decoded byte-exactly (COMP big-endian, COMP-3 packed, SIGN TRAILING SEPARATE, trailing
 * overpunch); the statement lines use numeric-edited (floating minus) and sign-separate fields.
 */
public class Acctpost {
    private static final int REC_LEN = 20;
    private static final BigDecimal LIMIT = BigDecimal.valueOf(-500);
    private static final BigDecimal FEE_CAP = BigDecimal.valueOf(25);

    // FD TRANS-FILE (decoded)
    BigDecimal trAcct = BigDecimal.ZERO;                    // 9(4) COMP
    String trType = " ";                                    // X
    BigDecimal trAmount = BigDecimal.ZERO.setScale(2);      // S9(7)V99 COMP-3
    BigDecimal trRate = BigDecimal.ZERO.setScale(4);        // SV9(4) SIGN TRAILING SEPARATE
    BigDecimal trSeq = BigDecimal.ZERO;                     // S9(5)
    BigDecimal trBranch = BigDecimal.ZERO;                  // S9(3) COMP

    // WORKING-STORAGE
    String wsEof = "N";
    BigDecimal[] acOpen = new BigDecimal[10];               // S9(7)V99 COMP-3
    BigDecimal[] acBalance = new BigDecimal[10];            // S9(7)V99 COMP-3
    BigDecimal[] acCount = new BigDecimal[10];              // 9(3) COMP
    BigDecimal wsSlot = BigDecimal.ZERO;                    // 9(2)
    BigDecimal wsQuot = BigDecimal.ZERO;                    // 9(4)
    BigDecimal wsRem = BigDecimal.ZERO;                     // 9
    BigDecimal wsAmount = BigDecimal.ZERO.setScale(2);      // S9(7)V99
    BigDecimal wsRate = BigDecimal.ZERO.setScale(4);        // SV9(4)
    BigDecimal wsInterest = BigDecimal.ZERO.setScale(2);    // S9(7)V99
    BigDecimal wsNewBal = BigDecimal.ZERO.setScale(2);      // S9(8)V99
    String wsStatus = "        ";                           // X(8)
    BigDecimal wsTxnCount = BigDecimal.ZERO;                // 9(4)
    BigDecimal wsRejects = BigDecimal.ZERO;
    BigDecimal wsOverflows = BigDecimal.ZERO;
    BigDecimal wsForeign = BigDecimal.ZERO;
    BigDecimal wsAmountSum = BigDecimal.ZERO.setScale(2);   // S9(9)V99
    int returnCode;

    private byte[] transData;
    private final byte[] recordArea = new byte[REC_LEN];
    private int transPos;
    private final StringBuilder stmtFile = new StringBuilder();
    private final StringBuilder out = new StringBuilder();

    public static void main(String[] args) throws IOException {
        Acctpost p = new Acctpost();
        p.mainPara();
        System.out.write(p.out.toString().getBytes(StandardCharsets.ISO_8859_1));
        System.out.flush();
        System.exit(p.returnCode);
    }

    void mainPara() throws IOException {
        transData = Files.readAllBytes(Paths.get("TRANS.DAT"));
        openAccounts();
        readTrans();
        while (!wsEof.equals("Y")) {
            postTrans();
            writeTxnLine();
            readTrans();
        }
        writeAccounts();
        Files.write(Paths.get("STATEMENT.TXT"), stmtFile.toString().getBytes(StandardCharsets.ISO_8859_1));
        line("TRANSACTIONS " + digits(wsTxnCount, 4) + " REJECTED " + digits(wsRejects, 4) + " OVERFLOWS "
                + digits(wsOverflows, 4) + " FOREIGN " + digits(wsForeign, 4));
        line("AMOUNT SUM " + signedDisplay(wsAmountSum, 9, 2));
        if (wsOverflows.signum() > 0) {
            returnCode = 8;
        } else if (wsRejects.signum() > 0) {
            returnCode = 4;
        } else {
            returnCode = 0;
        }
    }

    void openAccounts() {
        for (int k = 0; k < 10; k++) { // INITIALIZE WS-ACCOUNTS
            acOpen[k] = BigDecimal.ZERO.setScale(2);
            acBalance[k] = BigDecimal.ZERO.setScale(2);
            acCount[k] = BigDecimal.ZERO;
        }
        for (wsSlot = BigDecimal.ONE; wsSlot.compareTo(BigDecimal.TEN) <= 0; wsSlot = wsSlot.add(BigDecimal.ONE)) {
            int k = wsSlot.intValue() - 1;
            acOpen[k] = store(wsSlot.multiply(BigDecimal.valueOf(100)).subtract(BigDecimal.valueOf(300)), 7, 2, true, false);
            acBalance[k] = acOpen[k];
        }
    }

    void readTrans() {
        if (transPos >= transData.length) {
            wsEof = "Y";
            return;
        }
        // a short last record only overwrites the start of the record area (GnuCOBOL status 04)
        int n = Math.min(REC_LEN, transData.length - transPos);
        System.arraycopy(transData, transPos, recordArea, 0, n);
        transPos += n;
        decode(recordArea);
        wsTxnCount = store(wsTxnCount.add(BigDecimal.ONE), 4, 0, false, false);
        wsQuot = store(trAcct.divideToIntegralValue(BigDecimal.TEN), 4, 0, false, false);
        wsRem = store(trAcct.remainder(BigDecimal.TEN), 1, 0, false, false);
        wsSlot = store(wsRem.add(BigDecimal.ONE), 2, 0, false, false);
        wsAmount = store(trAmount, 7, 2, true, false);
        wsRate = store(trRate, 0, 4, true, false);
        if (trSeq.signum() < 0) {
            wsAmount = store(BigDecimal.ZERO.subtract(wsAmount), 7, 2, true, false);
        }
        if (trBranch.signum() < 0) {
            wsForeign = store(wsForeign.add(BigDecimal.ONE), 4, 0, false, false);
        }
    }

    void postTrans() {
        int k = wsSlot.intValue() - 1;
        wsStatus = "POSTED  ";
        if (trType.equals("D")) {
            wsNewBal = store(acBalance[k].add(wsAmount), 8, 2, true, false);
        } else if (trType.equals("W")) {
            wsNewBal = store(acBalance[k].subtract(wsAmount), 8, 2, true, false);
            if (wsNewBal.compareTo(LIMIT) < 0) {
                wsStatus = "NSF     ";
            }
        } else if (trType.equals("I")) {
            wsInterest = store(acBalance[k].multiply(wsRate), 7, 2, true, true);
            wsAmount = wsInterest;
            wsNewBal = store(acBalance[k].add(wsAmount), 8, 2, true, false);
        } else if (trType.equals("F")) {
            if (wsAmount.compareTo(FEE_CAP) > 0) {
                wsAmount = FEE_CAP.setScale(2);
            }
            wsNewBal = store(acBalance[k].subtract(wsAmount), 8, 2, true, false);
        } else {
            wsStatus = "BAD TYPE";
        }
        if (wsStatus.equals("POSTED  ")) {
            if (sizeError(wsNewBal, 7, 2)) {
                wsStatus = "OVERFLOW";
                wsOverflows = store(wsOverflows.add(BigDecimal.ONE), 4, 0, false, false);
            } else {
                acBalance[k] = store(wsNewBal, 7, 2, true, false);
                acCount[k] = store(acCount[k].add(BigDecimal.ONE), 3, 0, false, false);
                wsAmountSum = store(wsAmountSum.add(wsAmount), 9, 2, true, false);
            }
        } else {
            wsRejects = store(wsRejects.add(BigDecimal.ONE), 4, 0, false, false);
        }
    }

    void writeTxnLine() {
        int k = wsSlot.intValue() - 1;
        String rec = floatingMinus(trSeq, trSeq.signum() < 0, 5, 0) + " " + digits(trAcct, 4) + " " + trType + " "
                + (wsAmount.signum() < 0 ? "-" : "+") + digits(wsAmount.movePointRight(2), 9) + " "
                + digits(acBalance[k].movePointRight(2), 9) + (acBalance[k].signum() < 0 ? "-" : "+") + " " + wsStatus;
        writeStmt(rec);
    }

    void writeAccounts() {
        for (wsSlot = BigDecimal.ONE; wsSlot.compareTo(BigDecimal.TEN) <= 0; wsSlot = wsSlot.add(BigDecimal.ONE)) {
            int k = wsSlot.intValue() - 1;
            writeStmt("ACCOUNT " + digits(wsSlot, 2) + " OPEN " + floatingMinus(acOpen[k], acOpen[k].signum() < 0, 7, 2)
                    + " CLOSE " + floatingMinus(acBalance[k], acBalance[k].signum() < 0, 7, 2) + " TXNS "
                    + zeroSuppressed(acCount[k], 3));
        }
    }

    // ---------------------------------------------------------------- record decoding

    private void decode(byte[] r) {
        trAcct = BigDecimal.valueOf(((r[0] & 0xFF) << 8) | (r[1] & 0xFF));
        trType = new String(r, 2, 1, StandardCharsets.ISO_8859_1);
        long packed = 0;
        for (int i = 3; i < 8; i++) {
            packed = packed * 10 + ((r[i] >> 4) & 0xF);
            if (i < 7) {
                packed = packed * 10 + (r[i] & 0xF);
            }
        }
        trAmount = BigDecimal.valueOf((r[7] & 0xF) == 0xD ? -packed : packed, 2);
        long rate = Long.parseLong(new String(r, 8, 4, StandardCharsets.ISO_8859_1));
        trRate = BigDecimal.valueOf(r[12] == '-' ? -rate : rate, 4);
        long seq = 0;
        boolean neg = false;
        for (int i = 13; i < 18; i++) {
            int c = r[i] & 0xFF;
            if (c >= 0x70) {
                neg = true;
                c -= 0x40;
            }
            seq = seq * 10 + (c - '0');
        }
        trSeq = BigDecimal.valueOf(neg ? -seq : seq);
        trBranch = BigDecimal.valueOf((short) (((r[18] & 0xFF) << 8) | (r[19] & 0xFF)));
    }

    // ---------------------------------------------------------------- COBOL helpers

    static BigDecimal store(BigDecimal v, int intDigits, int scale, boolean isSigned, boolean rounded) {
        BigDecimal r = v.setScale(scale, rounded ? RoundingMode.HALF_UP : RoundingMode.DOWN);
        r = r.remainder(BigDecimal.TEN.pow(intDigits));
        if (!isSigned || r.signum() == 0) {
            r = r.abs();
        }
        return r.setScale(scale);
    }

    static boolean sizeError(BigDecimal v, int intDigits, int scale) {
        return v.setScale(scale, RoundingMode.DOWN).abs().compareTo(BigDecimal.TEN.pow(intDigits)) >= 0;
    }

    /** Numeric-edited -(n)9[.99]: floating minus, n-1 floating digit positions plus the 9. */
    static String floatingMinus(BigDecimal v, boolean negative, int intDigits, int scale) {
        String ds = digits(v.abs().movePointRight(scale), intDigits + scale);
        String ints = ds.substring(0, intDigits);
        int first = 0;
        while (first < intDigits - 1 && ints.charAt(first) == '0') {
            first++;
        }
        StringBuilder sb = new StringBuilder();
        sb.append(" ".repeat(first)).append(negative ? '-' : ' ').append(ints.substring(first));
        if (scale > 0) {
            sb.append('.').append(ds.substring(intDigits));
        }
        return sb.toString();
    }

    static String zeroSuppressed(BigDecimal v, int n) {
        String ds = digits(v, n);
        int first = 0;
        while (first < n - 1 && ds.charAt(first) == '0') {
            first++;
        }
        return " ".repeat(first) + ds.substring(first);
    }

    private static String digits(BigDecimal v, int n) {
        StringBuilder sb = new StringBuilder(v.abs().setScale(0, RoundingMode.DOWN).toPlainString());
        while (sb.length() < n) {
            sb.insert(0, '0');
        }
        return sb.toString();
    }

    private static String signedDisplay(BigDecimal v, int intDigits, int scale) {
        String ds = digits(v.movePointRight(scale), intDigits + scale);
        return (v.signum() < 0 ? "-" : "+") + ds.substring(0, intDigits) + "." + ds.substring(intDigits);
    }

    private void writeStmt(String rec) {
        int end = rec.length();
        while (end > 0 && rec.charAt(end - 1) == ' ') {
            end--;
        }
        stmtFile.append(rec, 0, end).append('\n');
    }

    private void line(String s) {
        out.append(s).append('\n');
    }
}
