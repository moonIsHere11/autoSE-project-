package corpus;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;

/**
 * Hand translation of PAYROLL. Every numeric WORKING-STORAGE item is a {@code long} scaled by
 * 10^scale; OCCURS tables are arrays (index 0 = subscript 1). The computational paragraphs
 * (CALC-GROSS ... ACCUMULATE) use only long arithmetic; record decoding/encoding and
 * numeric editing live in helper methods at the end.
 */
public class Payroll {
    private static final int EMP_LEN = 47;

    // FD EMP-FILE (raw text of the current record)
    String empId = spaces(5);
    String empName = spaces(15);
    String empDept = " ";
    String empType = " ";
    String empHours = spaces(4);     // 9(3)V9
    String empRate = spaces(6);      // 9(4)V99
    String empSales = spaces(8);     // 9(6)V99
    String empAllow = spaces(6);     // S9(3)V99 SIGN LEADING SEPARATE
    String empTaxcode = " ";

    // WORKING-STORAGE
    String wsEof = "N";
    long[] wsTaxExempt = {20000, 30000, 10000, 0};      // 9(4)V99, scale 2
    long[] wsTaxRate = {150, 200, 225, 300};             // V999, scale 3
    long[] wsTierLimit = {1000000, 5000000, 99999999};   // 9(6)V99, scale 2
    long[] wsTierRate = {20, 35, 50};                    // V999, scale 3
    long[] wsHealthRate = {2500, 3000, 3550, 4000, 0};   // 9(3)V99, scale 2
    long wsHours;          // 9(3)V9, scale 1
    long wsRate;           // 9(4)V99, scale 2
    long wsSales;          // 9(6)V99, scale 2
    long wsAllow;          // S9(3)V99, scale 2
    boolean wsAllowNegZero; // WS-ALLOW holds "-0" (MOVE keeps the sign of EMP-ALLOW)
    long wsRegHours;       // 9(3)V9
    long wsOtHours;        // 9(3)V9
    long wsDtHours;        // 9(3)V9
    long wsCommission;     // 9(6)V99
    long wsGross;          // S9(7)V99
    long wsTaxable;        // S9(7)V99
    long wsTax;            // S9(7)V99
    long wsSurtax;         // S9(5)V99
    long wsPension;        // S9(5)V99
    long wsHealth;         // 9(3)V99
    long wsNet;            // S9(6)V99
    long wsDept;           // 9
    long wsTaxIdx;         // 9
    long wsTier;           // 9
    String wsErrorMsg = spaces(16);
    long[] dtCount = new long[5];   // 9(3)
    long[] dtGross = new long[5];   // S9(9)V99
    long[] dtNet = new long[5];     // S9(9)V99
    long wsD;              // 9
    long wsAvgNet;         // S9(7)V99
    long wsReadCount = 0;  // 9(3)
    long wsPaidCount = 0;  // 9(4)
    long wsErrorCount = 0; // 9(3)
    long wsTotalGross = 0; // S9(9)V99
    long wsTotalNet = 0;   // S9(9)V99
    long wsTopNet = -99999999; // S9(6)V99 VALUE -999999.99
    String wsTopId = "NONE ";
    int returnCode;

    private List<String> empRecs;
    private int empPos;
    private final StringBuilder slipFile = new StringBuilder();
    private final ByteArrayOutputStream payFile = new ByteArrayOutputStream();
    private final StringBuilder out = new StringBuilder();

    public static void main(String[] args) throws IOException {
        Payroll p = new Payroll();
        p.mainPara();
        System.out.write(p.out.toString().getBytes(StandardCharsets.ISO_8859_1));
        System.out.flush();
        System.exit(p.returnCode);
    }

    void mainPara() throws IOException {
        empRecs = lineSeqRecords(Files.readAllBytes(Paths.get("EMPLOYEES.TXT")), EMP_LEN);
        for (int k = 0; k < 5; k++) { // INITIALIZE WS-DEPT-TOTALS
            dtCount[k] = 0;
            dtGross[k] = 0;
            dtNet[k] = 0;
        }
        readEmployee();
        while (!wsEof.equals("Y")) {
            processEmployee();
            readEmployee();
        }
        writeDeptSummary();
        Files.write(Paths.get("PAYSLIP.TXT"), slipFile.toString().getBytes(StandardCharsets.ISO_8859_1));
        Files.write(Paths.get("PAYROLL.DAT"), payFile.toByteArray());
        showTotals();
    }

    void readEmployee() {
        if (empPos >= empRecs.size()) {
            wsEof = "Y";
            return;
        }
        String r = empRecs.get(empPos++);
        empId = r.substring(0, 5);
        empName = r.substring(5, 20);
        empDept = r.substring(20, 21);
        empType = r.substring(21, 22);
        empHours = r.substring(22, 26);
        empRate = r.substring(26, 32);
        empSales = r.substring(32, 40);
        empAllow = r.substring(40, 46);
        empTaxcode = r.substring(46, 47);
        wsReadCount = (wsReadCount + 1) % 1000;
    }

    void processEmployee() {
        initializePayWork();
        validateEmployee();
        if (isBlank(wsErrorMsg)) {
            calcGross();
        }
        if (isBlank(wsErrorMsg)) {
            calcDeductions();
        }
        if (isBlank(wsErrorMsg)) {
            accumulate();
            writePayslip();
            writePayRecord();
        } else {
            wsErrorCount = (wsErrorCount + 1) % 1000;
            writeSlip("EMP " + empId + " ERROR: " + wsErrorMsg);
        }
    }

    void validateEmployee() {
        boolean typeValid = empType.equals("H") || empType.equals("S") || empType.equals("C");
        if (isBlank(empId)) {
            wsErrorMsg = pad("MISSING ID", 16);
        } else if (!allDigits(empDept)) {
            wsErrorMsg = pad("BAD DEPT", 16);
        } else if (empDept.charAt(0) < '1' || empDept.charAt(0) > '5') {
            wsErrorMsg = pad("BAD DEPT", 16);
        } else if (!typeValid) {
            wsErrorMsg = pad("BAD TYPE", 16);
        } else if (!allDigits(empHours)) {
            wsErrorMsg = pad("BAD HOURS", 16);
        } else if (!allDigits(empRate)) {
            wsErrorMsg = pad("BAD RATE", 16);
        } else if (!allDigits(empSales)) {
            wsErrorMsg = pad("BAD SALES", 16);
        } else if (!leadingSeparateNumeric(empAllow)) {
            wsErrorMsg = pad("BAD ALLOWANCE", 16);
        } else {
            wsDept = empDept.charAt(0) - '0';
            wsHours = Long.parseLong(empHours);
            wsRate = Long.parseLong(empRate);
            wsSales = Long.parseLong(empSales);
            long a = Long.parseLong(empAllow.substring(1));
            boolean neg = empAllow.charAt(0) == '-';
            wsAllow = neg ? -a : a;
            wsAllowNegZero = neg && a == 0;
            if (empTaxcode.equals("A")) {
                wsTaxIdx = 1;
            } else if (empTaxcode.equals("B")) {
                wsTaxIdx = 2;
            } else if (empTaxcode.equals("C")) {
                wsTaxIdx = 3;
            } else {
                wsTaxIdx = 4;
            }
        }
    }

    void calcGross() {
        boolean hourly = empType.equals("H");
        boolean salaried = empType.equals("S");
        if (hourly && wsHours > 400) {
            splitHours();
            calcHourly();
        } else if (hourly) {
            wsRegHours = wsHours;
            calcHourly();
        } else if (salaried) {
            wsGross = (wsRate + wsAllow) % 1000000000L;
        } else {
            calcCommission();
        }
    }

    void splitHours() {
        wsRegHours = 400;
        // WS-OT-HOURS / WS-DT-HOURS are unsigned 9(3)V9: storing drops the sign and the high-order digits
        long ot = (wsHours - 400) % 10000;
        wsOtHours = ot < 0 ? -ot : ot;
        if (wsOtHours > 200) {
            long dt = (wsOtHours - 200) % 10000;
            wsDtHours = dt < 0 ? -dt : dt;
            wsOtHours = 200;
        }
    }

    void calcHourly() {
        // all terms at scale 4: hours (1) * rate (2) * factor (1) ; allowance (2)
        long sum = wsRegHours * wsRate * 10 + wsOtHours * wsRate * 15 + wsDtHours * wsRate * 20 + wsAllow * 100;
        long q = sum / 100;
        long r = sum % 100;
        if (r < 0) {
            r = -r;
        }
        if (2 * r >= 100) {
            q = q + (sum < 0 ? -1 : 1);       // ROUNDED: half away from zero
        }
        if (q > 999999999L || q < -999999999L) {
            wsErrorMsg = pad("GROSS OVERFLOW", 16);
        } else {
            wsGross = q;
        }
    }

    void calcCommission() {
        for (wsTier = 1; !(wsTier > 3 || wsSales <= wsTierLimit[(int) wsTier - 1]); wsTier++) {
            // CONTINUE
        }
        long p = wsSales * wsTierRate[(int) wsTier - 1];     // scale 5
        wsCommission = ((p + 500) / 1000) % 100000000L;
        wsGross = (wsRate + wsCommission + wsAllow) % 1000000000L;
    }

    void calcDeductions() {
        wsHealth = wsHealthRate[(int) wsDept - 1];
        wsTaxable = (wsGross - wsTaxExempt[(int) wsTaxIdx - 1]) % 1000000000L;
        if (wsTaxable > 0) {
            long p = wsTaxable * wsTaxRate[(int) wsTaxIdx - 1]; // scale 5
            wsTax = ((p + 500) / 1000) % 1000000000L;
        } else {
            wsTax = 0;
        }
        if (wsGross > 500000) {
            wsSurtax = ((wsGross - 500000) / 100) % 10000000L; // * 0.01, truncated
            wsTax = (wsTax + wsSurtax) % 1000000000L;
        }
        if (wsGross > 0) {
            wsPension = (wsGross * 5 / 100) % 10000000L;       // * 0.05, truncated, high-order digits lost
        } else {
            wsPension = 0;
        }
        long net = wsGross - wsTax - wsPension - wsHealth;
        if (net > 99999999L || net < -99999999L) {
            wsErrorMsg = pad("NET OVERFLOW", 16);
        } else {
            wsNet = net;
        }
    }

    void accumulate() {
        int d = (int) wsDept - 1;
        wsPaidCount = (wsPaidCount + 1) % 10000;
        dtCount[d] = (dtCount[d] + 1) % 1000;
        dtGross[d] = dtGross[d] + wsGross;
        wsTotalGross = wsTotalGross + wsGross;
        dtNet[d] = dtNet[d] + wsNet;
        wsTotalNet = wsTotalNet + wsNet;
        if (wsNet > wsTopNet) {
            wsTopNet = wsNet;
            wsTopId = empId;
        }
    }

    void writePayslip() {
        writeSlip("EMP " + empId + " " + empName + " DEPT " + wsDept + " TYPE " + empType + " TAX " + empTaxcode);
        writeSlip("  HOURS " + edit("ZZ9.9", wsHours, 1) + " OT " + edit("ZZ9.9", wsOtHours, 1)
                + " DT " + edit("ZZ9.9", wsDtHours, 1) + " GROSS " + edit("Z,ZZZ,ZZ9.99-", wsGross, 2));
        writeSlip("  TAX " + edit("Z,ZZZ,ZZ9.99-", wsTax, 2) + " PENSION " + edit("ZZ,ZZ9.99-", wsPension, 2)
                + " HEALTH " + edit("ZZ9.99", wsHealth, 2) + " NET " + edit("ZZZ,ZZ9.99-", wsNet, 2));
    }

    void writePayRecord() {
        byte[] rec = new byte[36];
        put(rec, 0, empId);
        rec[5] = (byte) ('0' + wsDept);
        rec[6] = (byte) empType.charAt(0);
        rec[7] = (byte) (wsHours >> 8);                    // PR-HOURS 9(3)V9 COMP, big-endian
        rec[8] = (byte) wsHours;
        put(rec, 9, digits(wsOtHours + wsDtHours, 4));     // PR-OT-HOURS S9(3)V9, never negative
        pack(rec, 13, wsGross, 5);
        pack(rec, 18, wsTax, 5);
        pack(rec, 23, wsNet, 5);
        put(rec, 28, digits(wsAllow, 5) + (wsAllow < 0 || wsAllowNegZero ? "-" : "+"));
        rec[34] = (byte) (wsPaidCount >> 8);
        rec[35] = (byte) wsPaidCount;
        payFile.write(rec, 0, rec.length);
    }

    void writeDeptSummary() {
        for (wsD = 1; wsD <= 5; wsD++) {
            int d = (int) wsD - 1;
            String flag;
            if (dtCount[d] == 0) {
                wsAvgNet = 0;                                 // ON SIZE ERROR (divide by zero)
                flag = "N/A";
            } else {
                long q = dtNet[d] / dtCount[d];
                long r = dtNet[d] % dtCount[d];
                if (2 * (r < 0 ? -r : r) >= dtCount[d]) {
                    q = q + (dtNet[d] < 0 ? -1 : 1);
                }
                wsAvgNet = q;
                flag = "OK ";
            }
            writeSlip("DEPT " + wsD + " COUNT " + edit("ZZ9", dtCount[d], 0) + " GROSS "
                    + edit("$$,$$$,$$9.99", dtGross[d], 2) + " NET " + edit("$$,$$$,$$9.99", dtNet[d], 2)
                    + " AVG " + edit("Z,ZZZ,ZZ9.99-", wsAvgNet, 2) + " " + flag);
        }
    }

    void showTotals() {
        line("EMPLOYEES " + digits(wsReadCount, 3) + " PAID " + digits(wsPaidCount, 4) + " ERRORS "
                + digits(wsErrorCount, 3));
        line("GROSS " + signed(wsTotalGross, 9, 2) + " NET " + signed(wsTotalNet, 9, 2));
        line("TOP EARNER " + wsTopId + " NET " + signed(wsTopNet, 6, 2));
        if (wsErrorCount > 0) {
            returnCode = 4;
        }
    }

    private void initializePayWork() {
        wsHours = 0;
        wsRate = 0;
        wsSales = 0;
        wsAllow = 0;
        wsAllowNegZero = false;
        wsRegHours = 0;
        wsOtHours = 0;
        wsDtHours = 0;
        wsCommission = 0;
        wsGross = 0;
        wsTaxable = 0;
        wsTax = 0;
        wsSurtax = 0;
        wsPension = 0;
        wsHealth = 0;
        wsNet = 0;
        wsDept = 0;
        wsTaxIdx = 0;
        wsTier = 0;
        wsErrorMsg = spaces(16);
    }

    // ---------------------------------------------------------------- runtime helpers

    /**
     * Numeric editing for the pictures used here: Z (zero suppression), 9, comma, period,
     * floating $ (first $ is the symbol position) and a trailing '-' (sign). The value is held at
     * {@code scale}; excess integer digits are truncated like a MOVE and an unsigned picture
     * drops the sign.
     */
    static String edit(String pic, long v, int scale) {
        boolean neg = v < 0;
        long a = neg ? -v : v;
        int dot = pic.indexOf('.');
        String intPic = dot < 0 ? pic : pic.substring(0, dot);
        String fracPic = dot < 0 ? "" : pic.substring(dot + 1);
        int dollars = 0;
        int intSlots = 0;
        for (int i = 0; i < intPic.length(); i++) {
            char c = intPic.charAt(i);
            if (c == '$') {
                dollars++;
            }
            if (c == 'Z' || c == '9' || c == '$') {
                intSlots++;
            }
        }
        boolean floating = dollars > 1;
        if (floating) {
            intSlots--; // the leftmost $ only holds the symbol
        }
        long pow = 1;
        for (int i = 0; i < scale; i++) {
            pow *= 10;
        }
        long intPart = a / pow;
        long mod = 1;
        for (int i = 0; i < intSlots; i++) {
            mod *= 10;
        }
        String ds = digits(intPart % mod, intSlots);
        StringBuilder sb = new StringBuilder();
        int k = 0;
        boolean started = false;
        boolean firstDollar = true;
        for (int i = 0; i < intPic.length(); i++) {
            char c = intPic.charAt(i);
            if (c == '$' && floating && firstDollar) {
                firstDollar = false;
                sb.append(' ');
            } else if (c == 'Z' || c == '$') {
                char d = ds.charAt(k++);
                if (!started && d == '0') {
                    sb.append(' ');
                } else {
                    started = true;
                    sb.append(d);
                }
            } else if (c == '9') {
                started = true;
                sb.append(ds.charAt(k++));
            } else if (c == ',') {
                sb.append(started ? ',' : ' ');
            } else {
                sb.append(c);
            }
        }
        if (floating) {
            int first = 0;
            while (first < sb.length() && sb.charAt(first) == ' ') {
                first++;
            }
            sb.setCharAt(first - 1, '$');
        }
        String frac = digits(a % pow, scale);
        int f = 0;
        if (dot >= 0) {
            sb.append('.');
        }
        for (int i = 0; i < fracPic.length(); i++) {
            char c = fracPic.charAt(i);
            if (c == '9') {
                sb.append(frac.charAt(f++));
            } else if (c == '-') {
                sb.append(neg ? '-' : ' ');
            } else {
                sb.append(c);
            }
        }
        if (dot < 0 && pic.endsWith("-")) {
            sb.append(neg ? '-' : ' ');
        }
        return sb.toString();
    }

    private void writeSlip(String rec) {
        int end = rec.length();
        while (end > 0 && rec.charAt(end - 1) == ' ') {
            end--;
        }
        slipFile.append(rec, 0, end).append('\n');
    }

    private void line(String s) {
        out.append(s).append('\n');
    }

    /** GnuCOBOL LINE SEQUENTIAL READ (see corpus/grades for the rules). */
    static List<String> lineSeqRecords(byte[] data, int recLen) {
        List<String> recs = new ArrayList<>();
        String all = new String(data, StandardCharsets.ISO_8859_1);
        int n = all.length();
        int pos = 0;
        while (pos < n) {
            int start = pos;
            while (pos < n && all.charAt(pos) != '\n' && pos - start < recLen) {
                pos++;
            }
            String rec = all.substring(start, pos);
            if (rec.length() < recLen) {
                if (pos < n) {
                    pos++;
                }
            } else if (pos < n && all.charAt(pos) == '\n') {
                pos++;
            } else if (pos >= n) {
                pos = n - 1;
            }
            recs.add(pad(rec, recLen));
        }
        return recs;
    }

    private static void pack(byte[] rec, int off, long v, int len) {
        long a = v < 0 ? -v : v;
        int[] nib = new int[len * 2];
        nib[len * 2 - 1] = v < 0 ? 0xD : 0xC;
        for (int i = len * 2 - 2; i >= 0; i--) {
            nib[i] = (int) (a % 10);
            a /= 10;
        }
        for (int i = 0; i < len; i++) {
            rec[off + i] = (byte) ((nib[2 * i] << 4) | nib[2 * i + 1]);
        }
    }

    private static void put(byte[] rec, int off, String s) {
        byte[] b = s.getBytes(StandardCharsets.ISO_8859_1);
        System.arraycopy(b, 0, rec, off, b.length);
    }

    private static boolean allDigits(String s) {
        for (int i = 0; i < s.length(); i++) {
            if (s.charAt(i) < '0' || s.charAt(i) > '9') {
                return false;
            }
        }
        return !s.isEmpty();
    }

    private static boolean leadingSeparateNumeric(String s) {
        return (s.charAt(0) == '+' || s.charAt(0) == '-') && allDigits(s.substring(1));
    }

    private static boolean isBlank(String s) {
        for (int i = 0; i < s.length(); i++) {
            if (s.charAt(i) != ' ') {
                return false;
            }
        }
        return true;
    }

    private static String spaces(int n) {
        return " ".repeat(n);
    }

    private static String pad(String s, int n) {
        return s.length() >= n ? s.substring(0, n) : s + spaces(n - s.length());
    }

    private static String digits(long v, int n) {
        StringBuilder sb = new StringBuilder(Long.toString(v < 0 ? -v : v));
        while (sb.length() < n) {
            sb.insert(0, '0');
        }
        return sb.toString();
    }

    private static String signed(long v, int intDigits, int scale) {
        String ds = digits(v, intDigits + scale);
        String body = scale == 0 ? ds : ds.substring(0, intDigits) + "." + ds.substring(intDigits);
        return (v < 0 ? "-" : "+") + body;
    }
}
