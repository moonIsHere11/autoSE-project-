// Package cobolrt implements GnuCOBOL 3.2 (-std=default) data semantics for Go translations of
// COBOL programs: numeric items on int64 scaled values (Num* core functions and the CobolDecimal
// type), PIC X items (PicX), DISPLAY formatting, record encodings and ACCEPT parsing.
// See docs/RUNTIME_API.md; the behaviour is validated against GnuCOBOL by tests/runtimes.
package cobolrt

import (
	"fmt"
	"strconv"
	"strings"
)

// USAGE codes (shared with the Java and Python runtimes).
const (
	Display = 0 // zoned decimal
	Comp    = 1 // COMP / COMP-4 / BINARY: big-endian, truncated to the PIC digits
	Comp3   = 2 // COMP-3 / PACKED-DECIMAL
	Comp5   = 3 // COMP-5: native little-endian, limited by the byte width
)

// ROUNDED phrase codes. RoundTruncation means no ROUNDED phrase; Rounded is a plain ROUNDED
// (nearest-away-from-zero, except ADD/SUBTRACT into COMP-3 where GnuCOBOL 3.2 truncates).
const (
	RoundTruncation           = 0
	Rounded                   = 1
	RoundNearestAwayFromZero  = 2
	RoundAwayFromZero         = 3
	RoundNearestEven          = 4
	RoundNearestTowardZero    = 5
	RoundTowardGreater        = 6
	RoundTowardLesser         = 7
	RoundProhibited           = 8
	RoundModeTruncation       = 9
)

// SIZE ERROR phrase codes.
const (
	SizeNone    = 0 // no phrase: truncate / wrap silently
	SizeOn      = 1 // ON SIZE ERROR present: target unchanged on overflow
	SizeNotOnly = 2 // only NOT ON SIZE ERROR (unchanged on overflow except COMP-5, which wraps)
)

// Pic describes a numeric item. Digits counts stored digit positions (P not stored); Scale is
// the power of ten the stored integer is divided by (9(3)V99 = 5,2; 9(3)PP = 3,-2; PP99 = 2,4).
type Pic struct {
	Digits       int
	Scale        int
	Signed       bool
	Usage        int
	SignLeading  bool
	SignSeparate bool
}

// NewPic builds a Pic, panicking on an invalid description.
func NewPic(digits, scale int, signed bool, usage int, lead, sep bool) Pic {
	if digits < 1 || digits > 18 {
		panic("cobolrt: digits must be 1..18")
	}
	if (lead || sep) && (!signed || usage != Display) {
		panic("cobolrt: SIGN LEADING/SEPARATE needs a signed DISPLAY item")
	}
	return Pic{digits, scale, signed, usage, lead, sep}
}

// BinaryBytes is binary-size 1-2-4-8.
func BinaryBytes(digits int) int {
	switch {
	case digits <= 2:
		return 1
	case digits <= 4:
		return 2
	case digits <= 9:
		return 4
	}
	return 8
}

// ByteLength is the storage size of the item.
func (p Pic) ByteLength() int {
	switch p.Usage {
	case Display:
		if p.SignSeparate {
			return p.Digits + 1
		}
		return p.Digits
	case Comp3:
		return p.Digits/2 + 1
	}
	return BinaryBytes(p.Digits)
}

// IsBinary reports COMP or COMP-5.
func (p Pic) IsBinary() bool { return p.Usage == Comp || p.Usage == Comp5 }

// GcDigits is GnuCOBOL's digit count (P positions after the 9s are counted).
func (p Pic) GcDigits() int {
	if p.Scale < 0 {
		return p.Digits - p.Scale
	}
	return p.Digits
}

// IsU64 reports an unsigned 8-byte COMP-5 item (its int64 holds the unsigned bit pattern).
func (p Pic) IsU64() bool { return p.Usage == Comp5 && !p.Signed && p.ByteLength() == 8 }

// ParsePic parses e.g. ParsePic("S9(5)V99", "COMP-3", "") or ParsePic("S9(3)", "", "LEADING SEPARATE").
func ParsePic(picture, usage, sign string) (Pic, error) {
	t := strings.ToUpper(strings.ReplaceAll(picture, " ", ""))
	var sg, seenV, seen9, leadingP bool
	d, s := 0, 0
	for i := 0; i < len(t); {
		c := t[i]
		i++
		n := 1
		if i < len(t) && t[i] == '(' {
			j := strings.IndexByte(t[i:], ')')
			if j < 0 {
				return Pic{}, fmt.Errorf("bad PICTURE %q", picture)
			}
			v, err := strconv.Atoi(t[i+1 : i+j])
			if err != nil {
				return Pic{}, err
			}
			n = v
			i += j + 1
		}
		switch c {
		case 'S':
			sg = true
		case 'V':
			seenV = true
		case '9':
			d += n
			if seenV || leadingP {
				s += n
			}
			seen9 = true
		case 'P':
			if seenV || !seen9 {
				s += n
				leadingP = true
			} else {
				s -= n
			}
		default:
			return Pic{}, fmt.Errorf("unsupported PICTURE %q", picture)
		}
	}
	u := strings.TrimSpace(strings.ReplaceAll(strings.ToUpper(usage), "COMPUTATIONAL", "COMP"))
	var us int
	switch u {
	case "", "DISPLAY":
		us = Display
	case "COMP", "COMP-4", "BINARY":
		us = Comp
	case "COMP-3", "PACKED-DECIMAL":
		us = Comp3
	case "COMP-5":
		us = Comp5
	default:
		return Pic{}, fmt.Errorf("unsupported USAGE %q", usage)
	}
	sc := strings.ToUpper(sign)
	if d < 1 || d > 18 {
		return Pic{}, fmt.Errorf("digits must be 1..18 in %q", picture)
	}
	return Pic{d, s, sg, us, strings.Contains(sc, "LEADING"), strings.Contains(sc, "SEPARATE")}, nil
}

// MustPic is ParsePic panicking on error.
func MustPic(picture, usage, sign string) Pic {
	p, err := ParsePic(picture, usage, sign)
	if err != nil {
		panic(err)
	}
	return p
}
