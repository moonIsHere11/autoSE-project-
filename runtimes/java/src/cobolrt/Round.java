package cobolrt;

/**
 * The ROUNDED phrase of a statement (int codes shared with the Python and Go runtimes).
 *
 * <p>TRUNCATION means <em>no</em> ROUNDED phrase. ROUNDED is a plain {@code ROUNDED}: GnuCOBOL's
 * default mode is nearest-away-from-zero, except for ADD/SUBTRACT into a COMP-3 item, where
 * GnuCOBOL 3.2 truncates (measured). The others are {@code ROUNDED MODE IS <mode>}.
 */
public final class Round {
    private Round() {}

    public static final int TRUNCATION = 0;
    public static final int ROUNDED = 1;
    public static final int NEAREST_AWAY_FROM_ZERO = 2;
    public static final int AWAY_FROM_ZERO = 3;
    public static final int NEAREST_EVEN = 4;
    public static final int NEAREST_TOWARD_ZERO = 5;
    public static final int TOWARD_GREATER = 6;
    public static final int TOWARD_LESSER = 7;
    public static final int PROHIBITED = 8;
    /** {@code ROUNDED MODE IS TRUNCATION}. */
    public static final int MODE_TRUNCATION = 9;
}
