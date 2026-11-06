package cobolrt

// Static numeric core on int64 unscaled values (value = v * 10^-scale); same functions and
// preconditions as the Java cobolrt.Num (no overflow checks: callers guarantee the operands fit,
// see docs/RUNTIME_API.md). Semantics: GnuCOBOL 3.2's decimal path.

var pow10Table = [19]int64{1, 10, 100, 1000, 10000, 100000, 1000000, 10000000, 100000000,
	1000000000, 10000000000, 100000000000, 1000000000000, 10000000000000, 100000000000000,
	1000000000000000, 10000000000000000, 100000000000000000, 1000000000000000000}

// Pow10 returns 10^n for 0 <= n <= 18.
func Pow10(n int) int64 { return pow10Table[n] }

// Abs returns |v| (v != MinInt64).
func Abs(v int64) int64 {
	if v < 0 {
		return -v
	}
	return v
}

// Fits reports |v| < 10^digits.
func Fits(v int64, digits int) bool {
	p := Pow10(digits)
	return v > -p && v < p
}

// FitsShiftUp reports whether v*10^n does not overflow.
func FitsShiftUp(v int64, n int) bool {
	lim := int64(9223372036854775807) / Pow10(n)
	return v <= lim && v >= -lim
}

// FitsMul reports whether a*b does not overflow.
func FitsMul(a, b int64) bool {
	if a == 0 || b == 0 {
		return true
	}
	return Abs(b) <= int64(9223372036854775807)/Abs(a)
}

// ShiftUp returns v*10^n.
func ShiftUp(v int64, n int) int64 { return v * Pow10(n) }

// ShiftDown returns v/10^n truncated toward zero (0 when n > 18).
func ShiftDown(v int64, n int) int64 {
	if n > 18 {
		return 0
	}
	return v / Pow10(n)
}

// Rescale re-expresses v from scale `from` to scale `to`, truncating toward zero.
func Rescale(v int64, from, to int) int64 {
	if to >= from {
		return ShiftUp(v, to-from)
	}
	return ShiftDown(v, from-to)
}

// RoundDigit: t is the truncated value with ONE extra digit, sticky = lower digits non-zero.
func RoundDigit(t int64, sticky, negative bool, mode int) int64 {
	a := Abs(t)
	m := a / 10
	rd := a % 10
	inexact := rd != 0 || sticky
	up := false
	switch mode {
	case Rounded, RoundNearestAwayFromZero:
		up = rd >= 5
	case RoundAwayFromZero:
		up = inexact
	case RoundNearestEven:
		up = rd > 5 || (rd == 5 && (sticky || m%2 == 1))
	case RoundNearestTowardZero:
		up = rd > 5 || (rd == 5 && sticky)
	case RoundTowardGreater:
		up = !negative && inexact
	case RoundTowardLesser:
		up = negative && inexact
	}
	if up {
		m++
	}
	if negative {
		return -m
	}
	return m
}

// Round rounds/truncates v (at vscale) to tscale with a Round mode (decimal path).
func Round(v int64, vscale, tscale, mode int) int64 {
	if tscale >= vscale {
		return ShiftUp(v, tscale-vscale)
	}
	k := vscale - tscale
	t := ShiftDown(v, k-1)
	var sticky bool
	if k-1 > 18 {
		sticky = v != 0
	} else {
		sticky = v%Pow10(k-1) != 0
	}
	return RoundDigit(t, sticky, v < 0, mode)
}

// ProhibitedError: ROUNDED MODE PROHIBITED fails when digits would be dropped.
func ProhibitedError(v int64, vscale, tscale int) bool { return v != 0 && tscale < vscale }

// Wrap is the two's complement wrap of v to `bytes` bytes (8: unchanged bit pattern).
func Wrap(v int64, bytes int, signed bool) int64 {
	if bytes >= 8 {
		return v
	}
	bits := uint(8 * bytes)
	m := v & ((int64(1) << bits) - 1)
	if signed && m >= int64(1)<<(bits-1) {
		m -= int64(1) << bits
	}
	return m
}

// Overflows: would storing v (at the target scale) overflow the item?
func Overflows(v int64, digits int, signed bool, usage, bytes int) bool {
	if usage != Comp5 {
		return !Fits(v, digits)
	}
	if bytes == 8 {
		return false
	}
	bitnum := uint(8 * bytes)
	if signed {
		bitnum--
	}
	return Abs(v) >= int64(1)<<bitnum
}

// StoreValue: value held after storing v (at the target scale) without a SIZE ERROR phrase.
func StoreValue(v int64, digits int, signed bool, usage, bytes int) int64 {
	if usage == Comp5 {
		if signed {
			return Wrap(v, bytes, true)
		}
		return Wrap(Abs(v), bytes, false)
	}
	m := Abs(v) % Pow10(digits)
	if !signed {
		return m
	}
	if v < 0 {
		return -m
	}
	return m
}

// StoresNegativeZero: does storing v leave a DISPLAY/COMP-3 item holding a negative zero?
func StoresNegativeZero(v int64, digits int, signed bool, usage int) bool {
	return signed && (usage == Display || usage == Comp3) && v < 0 && Abs(v)%Pow10(digits) == 0
}

// Store stores v (at vscale) without a SIZE ERROR phrase: rounding, scale truncation, high-order
// truncation / wrap.
func Store(v int64, vscale, digits, scale int, signed bool, usage, mode int) int64 {
	return StoreValue(Round(v, vscale, scale, mode), digits, signed, usage, BinaryBytes(digits))
}

// SizeErrorOf reports whether the store raises a size error (including PROHIBITED).
func SizeErrorOf(v int64, vscale, digits, scale int, signed bool, usage, mode int) bool {
	if mode == RoundProhibited && ProhibitedError(v, vscale, scale) {
		return true
	}
	r := Round(v, vscale, scale, mode)
	if !signed {
		r = Abs(r)
	}
	return Overflows(r, digits, signed, usage, BinaryBytes(digits))
}

// Divide returns the quotient a/b of a single division rounded to tscale (GnuCOBOL's DIVIDE).
func Divide(a int64, sa int, b int64, sb, tscale, mode int) int64 {
	k := tscale + 1 - sa + sb
	var t int64
	var sticky bool
	if k >= 0 {
		num := a * Pow10(k)
		t = num / b
		sticky = num%b != 0
	} else {
		den := b * Pow10(-k)
		t = a / den
		sticky = a%den != 0
	}
	return RoundDigit(t, sticky, a != 0 && ((a < 0) != (b < 0)), mode)
}

// RemainderScale is the scale of the DIVIDE ... REMAINDER intermediate.
func RemainderScale(sa, sb, qscale int) int {
	if sa > qscale+sb {
		return sa
	}
	return qscale + sb
}

// Remainder: a - q'*b at RemainderScale, q' = quotient truncated to qscale.
func Remainder(a int64, sa int, b int64, sb, qscale int) int64 {
	q := Divide(a, sa, b, sb, qscale, RoundTruncation)
	rs := RemainderScale(sa, sb, qscale)
	return ShiftUp(a, rs-sa) - q*b*Pow10(rs-qscale-sb)
}

// Compare compares a (at sa) with b (at sb): -1, 0, 1.
func Compare(a int64, sa int, b int64, sb int) int {
	x, y := a, b
	if sb > sa {
		x = ShiftUp(a, sb-sa)
	} else if sa > sb {
		y = ShiftUp(b, sa-sb)
	}
	switch {
	case x < y:
		return -1
	case x > y:
		return 1
	}
	return 0
}

// Move is the value part of MOVE numeric -> numeric.
func Move(u int64, sscale, digits, scale int, signed bool, usage int) int64 {
	return StoreValue(Rescale(u, sscale, scale), digits, signed, usage, BinaryBytes(digits))
}

// MoveNegativeZero: does the MOVE leave a negative zero in a DISPLAY/COMP-3 target?
func MoveNegativeZero(u int64, srcNegZero, srcBinary bool, sscale, digits, scale int, signed bool, usage int) bool {
	if !signed || (usage != Display && usage != Comp3) {
		return false
	}
	w := Rescale(u, sscale, scale)
	neg := u < 0 || srcNegZero
	if srcBinary && usage == Comp3 {
		neg = w < 0
	}
	return neg && Abs(w)%Pow10(digits) == 0
}

// PackedAddMode is the effective mode of GnuCOBOL's packed-decimal ADD/SUBTRACT.
func PackedAddMode(mode int) int {
	switch mode {
	case Rounded, RoundModeTruncation:
		return RoundTruncation
	case RoundNearestEven:
		return RoundNearestAwayFromZero
	}
	return mode
}
