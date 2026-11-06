package cobolrt;

/** USAGE of a numeric item (int codes shared with the Python and Go runtimes). */
public final class Usage {
    private Usage() {}

    /** Zoned decimal: one ASCII digit per byte, sign overpunched (or SEPARATE). */
    public static final int DISPLAY = 0;
    /** COMP / COMP-4 / BINARY: big-endian two's complement, truncated to the PIC digits. */
    public static final int COMP = 1;
    /** COMP-3 / PACKED-DECIMAL: BCD nibbles + sign nibble C/D/F. */
    public static final int COMP3 = 2;
    /** COMP-5: native little-endian binary, limited by the byte width, not by the PIC. */
    public static final int COMP5 = 3;
}
