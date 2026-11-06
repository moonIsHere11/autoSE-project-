package cobolrt;

/** Which SIZE ERROR phrases a statement has (int codes shared with Python and Go). */
public final class SizeError {
    private SizeError() {}

    /** Neither phrase: an overflow truncates high-order digits (COMP-5 wraps) silently. */
    public static final int NONE = 0;
    /** ON SIZE ERROR present (with or without NOT ON SIZE ERROR): target left unchanged. */
    public static final int ON = 1;
    /** Only NOT ON SIZE ERROR present (unchanged on overflow, except COMP-5 which wraps). */
    public static final int NOT_ONLY = 2;
}
