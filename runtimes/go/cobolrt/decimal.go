package cobolrt

import (
	"math/big"
	"strconv"
)

// CobolDecimal is a numeric item: an int64 unscaled value plus its Pic. Statement methods follow
// GnuCOBOL 3.2 exactly and return true on a size error:
//
//	// ADD A TO B ROUNDED ON SIZE ERROR ... END-ADD
//	if b.Add(a, cobolrt.Rounded, cobolrt.SizeOn) { ... }
//
// It also tracks storage details only visible in record bytes: a negative zero (DISPLAY/COMP-3),
// a COMP-3 sign nibble F in a signed item, and a garbage digit in a COMP-3 pad nibble. For an
// unsigned 8-byte COMP-5 item U holds the unsigned 64-bit bit pattern.
type CobolDecimal struct {
	Pic     Pic
	u       int64
	negZero bool
	fnib    bool
	pad     int
}

// NewDecimal creates an item with value zero.
func NewDecimal(p Pic) *CobolDecimal { return &CobolDecimal{Pic: p} }

// NewDecimalPic parses picture/usage, e.g. NewDecimalPic("S9(5)V99", "COMP-3").
func NewDecimalPic(picture, usage string) *CobolDecimal {
	return NewDecimal(MustPic(picture, usage, ""))
}

// Unscaled returns the stored integer (value = Unscaled * 10^-Scale).
func (d *CobolDecimal) Unscaled() int64 { return d.u }

// IsNegativeZero reports a DISPLAY/COMP-3 negative zero.
func (d *CobolDecimal) IsNegativeZero() bool { return d.negZero }

// SetUnscaled sets the raw value (caller guarantees it fits).
func (d *CobolDecimal) SetUnscaled(v int64) { d.setState(v, false, false, 0) }

func (d *CobolDecimal) setState(v int64, nz, f bool, p int) {
	d.u, d.negZero, d.fnib, d.pad = v, nz && v == 0, f, p
}

func (d *CobolDecimal) big() *big.Int {
	if d.Pic.IsU64() {
		return new(big.Int).SetUint64(uint64(d.u))
	}
	return big.NewInt(d.u)
}

// Dec returns the value as an exact intermediate.
func (d *CobolDecimal) Dec() Dec { return Dec{d.big(), d.Pic.Scale, false} }

func (d *CobolDecimal) dneg() bool { return d.Pic.Signed && (d.u < 0 || d.negZero) && !d.fnib }

func (d *CobolDecimal) full() *big.Int {
	m := new(big.Int).Abs(d.big())
	if d.Pic.Usage == Comp3 && d.pad != 0 {
		m.Add(m, new(big.Int).Mul(big.NewInt(int64(d.pad)), bpow10(d.Pic.Digits)))
	}
	return m
}

func wrapBig(v *big.Int, bytes int, signed bool) int64 {
	bits := uint(8 * bytes)
	mod := new(big.Int).Lsh(big.NewInt(1), bits)
	m := new(big.Int).Mod(v, mod)
	if signed && m.Bit(int(bits)-1) == 1 {
		m.Sub(m, mod)
	}
	if !m.IsInt64() {
		return int64(m.Uint64())
	}
	return m.Int64()
}

func remPow(v *big.Int, n int) int64 { return new(big.Int).Rem(v, bpow10(n)).Int64() }

// Move implements MOVE src TO d for a numeric source item.
func (d *CobolDecimal) Move(src *CobolDecimal) {
	p, s := d.Pic, src.Pic
	if s == p {
		d.setState(src.u, src.negZero, src.fnib, src.pad)
		return
	}
	if s.Usage == Comp3 && p.Usage == Comp3 && s.Scale >= 0 && p.Scale >= 0 {
		mag := remPow(bshift(src.full(), p.Scale-s.Scale), p.Digits)
		switch {
		case !p.Signed:
			d.setState(mag, false, false, 0)
		case src.dneg():
			d.setState(-mag, mag == 0, false, 0)
		default:
			d.setState(mag, false, !s.Signed || src.fnib, 0)
		}
		return
	}
	if s.IsBinary() && p.Usage == Comp3 {
		diff := s.Scale - p.Scale
		if s.Digits < 19 && s.Digits-diff < 19 {
			val := bshift(src.big(), -diff)
			if val.BitLen() <= 31 {
				d.setPackedInt(val.Int64())
				return
			}
		}
	}
	d.moveValue(src.big(), s.Scale, src.u < 0 || src.negZero, s.IsBinary())
}

// MoveLiteral implements MOVE numeric-literal TO d, e.g. d.MoveLiteral("-12.5").
func (d *CobolDecimal) MoveLiteral(text string) {
	l := parseLit(text)
	p := d.Pic
	if p.Usage == Comp3 && p.Scale >= 0 && l.fitsInt() && l.ndigits+p.Scale <= 9 {
		d.setPackedInt(l.v.Int64() * Pow10(p.Scale))
		return
	}
	d.moveValue(l.v, l.scale, l.minus, false)
}

// MoveInt implements MOVE integer-literal TO d.
func (d *CobolDecimal) MoveInt(v int64) { d.MoveLiteral(strconv.FormatInt(v, 10)) }

// MoveX implements MOVE alphanumeric-item TO d.
func (d *CobolDecimal) MoveX(src *PicX) { d.MoveAlnum(src.Data) }

// MoveAlnum implements MOVE alphanumeric bytes TO d (de-editing).
func (d *CobolDecimal) MoveAlnum(src []byte) {
	p := d.Pic
	if p.Usage == Display {
		dd, sg := deedit(src, p.Digits, p.Scale)
		var mag int64
		for _, c := range dd {
			mag = mag*10 + int64(c-'0')
		}
		neg := sg < 0 && p.Signed
		if neg {
			d.setState(-mag, mag == 0, false, 0)
		} else {
			d.setState(mag, false, false, 0)
		}
		return
	}
	dd, sg := deedit(src, 76, 38)
	mag, _ := new(big.Int).SetString(string(dd), 10)
	if sg < 0 {
		mag.Neg(mag)
	}
	d.moveValue(mag, 38, sg < 0, false)
}

func (d *CobolDecimal) setPackedInt(val int64) {
	if val == 0 {
		d.setState(0, false, false, 0)
		return
	}
	p := d.Pic
	nib := 2*p.ByteLength() - 1
	full := Abs(val)
	if nib <= 18 {
		full %= Pow10(nib)
	}
	mag := full % Pow10(p.Digits)
	neg := val < 0 && p.Signed
	v := mag
	if neg {
		v = -mag
	}
	d.setState(v, neg && mag == 0, false, int(full/Pow10(p.Digits)))
}

func (d *CobolDecimal) moveValue(v *big.Int, vscale int, neg, fromBinary bool) {
	p := d.Pic
	w := bshift(v, p.Scale-vscale)
	mag := new(big.Int).Abs(w)
	switch p.Usage {
	case Display, Comp3:
		m := remPow(mag, p.Digits)
		if !p.Signed {
			d.setState(m, false, false, 0)
			return
		}
		n := neg
		if fromBinary && p.Usage == Comp3 {
			n = w.Sign() < 0
		}
		if n {
			d.setState(-m, m == 0, false, 0)
		} else {
			d.setState(m, false, false, 0)
		}
	case Comp:
		m := remPow(mag, p.Digits)
		if w.Sign() < 0 && p.Signed {
			m = -m
		}
		d.setState(m, false, false, 0)
	default:
		x := mag
		if p.Signed {
			x = w
		}
		d.setState(wrapBig(x, p.ByteLength(), p.Signed), false, false, 0)
	}
}

func keeps(p Pic, size int) bool {
	if p.Usage == Comp5 {
		return size == SizeOn
	}
	return size != SizeNone
}

// Store stores an intermediate result (COMPUTE / GIVING): ROUNDED mode, scale truncation, then
// high-order truncation or COMP-5 wrap; with a SIZE ERROR phrase an overflowing item is unchanged.
// Returns true on size error (also division by zero and PROHIBITED, which never write).
func (d *CobolDecimal) Store(val Dec, mode, size int) bool {
	if val.NaN {
		return true
	}
	p := d.Pic
	v := new(big.Int).Set(val.V)
	vscale := val.Scale
	if mode != RoundTruncation && mode != RoundModeTruncation && v.Sign() != 0 && p.Scale < vscale {
		if mode == RoundProhibited {
			return true
		}
		sg := int64(v.Sign())
		adj := vscale - p.Scale
		inexact := func() bool { return new(big.Int).Rem(v, bpow10(adj)).Sign() != 0 }
		switch mode {
		case RoundAwayFromZero:
			if inexact() {
				v.Add(v, new(big.Int).Mul(big.NewInt(sg), bpow10(adj)))
			}
		case RoundTowardGreater:
			if inexact() && sg > 0 {
				v.Add(v, bpow10(adj))
			}
		case RoundTowardLesser:
			if inexact() && sg < 0 {
				v.Sub(v, bpow10(adj))
			}
		case RoundNearestTowardZero, RoundNearestEven:
			r := new(big.Int).Rem(v, new(big.Int).Mul(bpow10(adj-1), big.NewInt(5)))
			v = bshift(v, p.Scale-vscale+1)
			vscale = p.Scale + 1
			add := r.Sign() != 0
			if mode == RoundNearestEven {
				last := new(big.Int).Rem(new(big.Int).Abs(v), big.NewInt(100)).Int64()
				add = !(r.Sign() == 0 && (last == 5 || last == 25 || last == 45 || last == 65 || last == 85))
			}
			if add {
				v.Add(v, big.NewInt(5*sg))
			}
		default:
			v = bshift(v, p.Scale-vscale+1)
			vscale = p.Scale + 1
			v.Add(v, big.NewInt(5*sg))
		}
	}
	if v.Sign() != 0 {
		v = bshift(v, p.Scale-vscale)
	}
	if v.Sign() == 0 {
		d.setState(0, false, false, 0)
		return false
	}
	keep := keeps(p, size)
	sg := v.Sign()
	mag := new(big.Int).Abs(v)
	if p.Usage == Display || p.Usage == Comp3 {
		err := mag.Cmp(bpow10(p.Digits)) >= 0
		if err {
			if keep {
				return true
			}
			mag.Rem(mag, bpow10(p.Digits))
		}
		m := mag.Int64()
		if !p.Signed {
			d.setState(m, false, false, 0)
		} else if sg < 0 {
			d.setState(-m, m == 0, false, 0)
		} else {
			d.setState(m, false, false, 0)
		}
		return err
	}
	bits := 8 * p.ByteLength()
	bitnum := bits
	if p.Signed {
		bitnum--
	} else {
		sg = 1
	}
	signedMag := func(m int64) int64 {
		if sg < 0 {
			return -m
		}
		return m
	}
	if mag.BitLen() > bitnum {
		if keep {
			return true
		}
		if p.Usage == Comp {
			d.setState(signedMag(remPow(mag, p.Digits)), false, false, 0)
		} else {
			x := mag
			if sg < 0 {
				x = new(big.Int).Neg(mag)
			}
			d.setState(wrapBig(x, p.ByteLength(), p.Signed), false, false, 0)
		}
		return true
	}
	if p.Usage == Comp && mag.Cmp(bpow10(p.Digits)) >= 0 {
		if keep {
			return true
		}
		d.setState(signedMag(remPow(mag, p.Digits)), false, false, 0)
		return true
	}
	if sg < 0 {
		mag.Neg(mag)
	}
	if mag.IsInt64() {
		d.setState(mag.Int64(), false, false, 0)
	} else {
		d.setState(int64(mag.Uint64()), false, false, 0)
	}
	return false
}

// Compute is COMPUTE d [ROUNDED] = val (also the GIVING forms).
func (d *CobolDecimal) Compute(val Dec, mode, size int) bool { return d.Store(val, mode, size) }

// Operand is a statement operand: an item or a numeric literal.
type Operand struct {
	item *CobolDecimal
	lit  string
}

// Item wraps an item as an operand.
func Item(d *CobolDecimal) Operand { return Operand{item: d} }

// Lit wraps a numeric literal (e.g. "1.5") as an operand.
func Lit(text string) Operand { return Operand{lit: text} }

func (o Operand) dec() Dec {
	if o.item != nil {
		return o.item.Dec()
	}
	return Literal(o.lit)
}

// Add is ADD x TO d.
func (d *CobolDecimal) Add(x Operand, mode, size int) bool { return d.addsub(x, mode, size, false) }

// Subtract is SUBTRACT x FROM d.
func (d *CobolDecimal) Subtract(x Operand, mode, size int) bool { return d.addsub(x, mode, size, true) }

// Multiply is MULTIPLY x BY d.
func (d *CobolDecimal) Multiply(x Operand, mode, size int) bool {
	return d.Store(d.Dec().Mul(x.dec()), mode, size)
}

// Divide is DIVIDE x INTO d.
func (d *CobolDecimal) Divide(x Operand, mode, size int) bool {
	return d.Store(d.Dec().Div(x.dec()), mode, size)
}

// DivideRemainder is DIVIDE dividend BY divisor GIVING q [ROUNDED] REMAINDER r. The remainder is
// dividend - q'*divisor (q' = quotient truncated to q's scale); it is stored even when q had a
// size error. Division by zero leaves both unchanged.
func DivideRemainder(dividend, divisor Dec, q, r *CobolDecimal, mode, size int) bool {
	qq := dividend.Div(divisor)
	if qq.NaN {
		return true
	}
	e1 := q.Store(qq, mode, size)
	qt := zeroDec
	if qq.V.Sign() != 0 {
		qt = Dec{bshift(qq.V, q.Pic.Scale-qq.Scale), q.Pic.Scale, false}
	}
	rem := dividend.Sub(qt.Mul(divisor))
	e2 := r.Store(rem, RoundTruncation, size)
	return e1 || e2
}

func fitsIntPic(p Pic) bool {
	if p.Scale > 0 {
		return false
	}
	switch p.Usage {
	case Display:
		return p.ByteLength() < 10
	case Comp3:
		return p.GcDigits() < 10
	}
	return p.ByteLength() <= 4
}

func (d *CobolDecimal) addsub(x Operand, mode, size int, sub bool) bool {
	p := d.Pic
	opt0 := mode == RoundTruncation && p.Usage != Comp &&
		(size == SizeNone || (p.Usage == Comp5 && size == SizeNotOnly))
	var n int64
	haveN := false
	if x.item != nil && fitsIntPic(x.item.Pic) {
		n = new(big.Int).Mul(x.item.big(), bpow10(-x.item.Pic.Scale)).Int64()
		haveN = true
	} else if x.item == nil {
		if l := parseLit(x.lit); l.fitsInt() {
			n, haveN = l.v.Int64(), true
		}
	}
	if opt0 && haveN {
		nv := n
		if sub && p.Usage == Comp3 && p.Scale == 0 && p.GcDigits() >= 10 && p.GcDigits() <= 18 &&
			x.item != nil && x.item.Pic.IsBinary() && !x.item.Pic.Signed && x.item.Pic.ByteLength() == 4 && nv != 0 {
			nv = (int64(1) << 32) - nv // negated as a C unsigned int, then widened (measured)
		} else if sub {
			nv = -nv
		}
		if nv == 0 {
			return false
		}
		if p.Scale < 0 {
			if -p.Scale > 18 {
				return false
			}
			val := nv / Pow10(-p.Scale)
			if val == 0 {
				return false
			}
			return d.Store(Dec{new(big.Int).Add(d.big(), big.NewInt(val)), p.Scale, false}, RoundTruncation, SizeNone)
		}
		if p.Scale == 0 && p.Usage == Comp5 {
			d.setState(wrapBig(new(big.Int).Add(d.big(), big.NewInt(nv)), p.ByteLength(), p.Signed), false, false, 0)
			return false
		}
		if p.Scale == 0 && p.Usage == Comp3 {
			neg := d.dneg()
			if !((nv > 0 && neg) || (nv < 0 && !neg)) {
				nib := 2*p.ByteLength() - 1
				total := new(big.Int).Add(d.full(), big.NewInt(Abs(nv)))
				total.Rem(total, bpow10(nib))
				mag := remPow(total, p.Digits)
				pd := int(new(big.Int).Quo(total, bpow10(p.Digits)).Int64())
				if neg {
					d.setState(-mag, mag == 0, false, pd)
				} else {
					d.setState(mag, false, d.fnib, pd)
				}
				return false
			}
		}
		return d.Store(d.Dec().Add(DecInt(nv)), RoundTruncation, SizeNone)
	}
	if p.Usage == Comp3 {
		return d.bcdAdd(x, mode, size, sub)
	}
	if sub {
		return d.Store(d.Dec().Sub(x.dec()), mode, size)
	}
	return d.Store(d.Dec().Add(x.dec()), mode, size)
}

func (d *CobolDecimal) bcdAdd(x Operand, mode, size int, sub bool) bool {
	p := d.Pic
	var xm *big.Int
	var xneg bool
	var xs int
	if x.item != nil {
		q := x.item.Pic
		switch {
		case q.Usage == Comp3:
			xm, xneg = x.item.full(), x.item.dneg()
		case q.IsBinary():
			sz := q.Digits/2 + 1
			xm = new(big.Int).Rem(new(big.Int).Abs(x.item.big()), bpow10(2*sz-1))
			xneg = x.item.big().Sign() < 0
		default:
			xm = new(big.Int).Abs(x.item.big())
			if q.Scale < 0 {
				sz := q.GcDigits()/2 + 1
				i0 := 1 - q.Digits%2
				xm.Mul(xm, bpow10((2*sz-1)-(i0+q.Digits)))
			}
			xneg = x.item.u < 0 || x.item.negZero
		}
		xs = q.Scale
	} else {
		l := parseLit(x.lit)
		xm, xneg, xs = new(big.Int).Abs(l.v), l.minus, l.scale
	}
	s := max(xs, p.Scale)
	xa := new(big.Int).Mul(xm, bpow10(s-xs))
	ya := new(big.Int).Mul(d.full(), bpow10(s-p.Scale))
	yneg := d.dneg()
	xn := xneg != sub
	var m *big.Int
	var positive bool
	if xn == yneg {
		m, positive = new(big.Int).Add(xa, ya), !xn
	} else {
		switch c := xa.Cmp(ya); {
		case c < 0:
			m, positive = new(big.Int).Sub(ya, xa), !yneg
		case c > 0:
			m, positive = new(big.Int).Sub(xa, ya), !xn
		default:
			d.setState(0, false, false, 0)
			return false
		}
	}
	if k := s - p.Scale; k > 0 {
		if mode != RoundTruncation && mode != Rounded && mode != RoundModeTruncation {
			rd := new(big.Int).Rem(new(big.Int).Quo(m, bpow10(k-1)), bigTen).Int64()
			restNz := new(big.Int).Rem(m, bpow10(k-1)).Sign() != 0
			inexact := rd != 0 || restNz
			switch {
			case mode == RoundProhibited:
				if inexact {
					return true
				}
				if k%2 == 0 {
					return false // target untouched, no exception (measured)
				}
			case mode == RoundNearestAwayFromZero || mode == RoundNearestEven:
				m.Add(m, new(big.Int).Mul(big.NewInt(5), bpow10(k-1)))
			case mode == RoundNearestTowardZero:
				if rd > 5 || (rd == 5 && restNz) {
					m.Add(m, bpow10(k))
				}
			case mode == RoundAwayFromZero || (mode == RoundTowardGreater && positive) ||
				(mode == RoundTowardLesser && !positive):
				if inexact {
					m.Add(m, bpow10(k))
				}
			}
		}
		m.Quo(m, bpow10(k))
	}
	nib := 2*p.ByteLength() - 1
	if p.GcDigits()%2 == 0 {
		nib--
	}
	err := m.Cmp(bpow10(nib)) >= 0
	if err {
		if size != SizeNone {
			return true
		}
		m.Rem(m, bpow10(nib))
	}
	mag := remPow(m, p.Digits)
	pd := int(new(big.Int).Quo(m, bpow10(p.Digits)).Int64())
	switch {
	case !p.Signed:
		d.setState(mag, false, false, pd)
	case positive:
		d.setState(mag, false, false, pd)
	default:
		d.setState(-mag, mag == 0, false, pd)
	}
	return err
}

func fitsLongLongPic(p Pic) bool {
	if p.Scale > 0 {
		return false
	}
	switch p.Usage {
	case Display:
		return p.ByteLength() < 19
	case Comp3:
		return p.GcDigits() < 19
	}
	return true
}

// Compare compares d with an operand as `IF d < x` does: -1, 0, 1.
func (d *CobolDecimal) Compare(x Operand) int {
	p := d.Pic
	if p.IsBinary() && !p.Signed && p.Scale == 0 && p.ByteLength() == 8 {
		neg, fits := false, false
		if x.item != nil {
			neg, fits = x.item.big().Sign() < 0, fitsLongLongPic(x.item.Pic)
		} else {
			l := parseLit(x.lit)
			neg, fits = l.v.Sign() < 0, l.fitsLongLong()
		}
		if neg && fits {
			return -1 // compared as C unsigned long long (measured)
		}
	}
	return d.Dec().Sub(x.dec()).V.Sign()
}

// Accept is ACCEPT d from a line (nil = end of input: sets zero).
func (d *CobolDecimal) Accept(line []byte) {
	b := line
	if b == nil {
		b = []byte{' '}
	}
	if d.Pic.Usage == Display && len(b) > d.Pic.ByteLength() {
		b = b[:d.Pic.ByteLength()]
	}
	d.MoveAlnum(b)
}

// Display returns what DISPLAY prints.
func (d *CobolDecimal) Display() []byte { return DisplayNumeric(d.u, d.Pic) }

// Encode returns the storage bytes.
func (d *CobolDecimal) Encode() []byte { return Encode(d.u, d.Pic, d.negZero, d.fnib, d.pad) }

// Decode loads storage bytes.
func (d *CobolDecimal) Decode(data []byte) { Decode(data, d) }

func (d *CobolDecimal) String() string { return string(d.Display()) }

// PicX is PIC X(n) [JUSTIFIED RIGHT]: fixed-length bytes, initially spaces.
type PicX struct {
	Data      []byte
	Justified bool
}

// NewPicX creates a space-filled item.
func NewPicX(n int, justified bool) *PicX {
	b := make([]byte, n)
	for i := range b {
		b[i] = ' '
	}
	return &PicX{b, justified}
}

// Move is MOVE src TO x.
func (x *PicX) Move(src *PicX) { MoveAlnum(src.Data, x.Data, x.Justified) }

// MoveBytes is MOVE literal/bytes TO x.
func (x *PicX) MoveBytes(b []byte) { MoveAlnum(b, x.Data, x.Justified) }

// MoveString is MOVE "literal" TO x (ISO-8859-1 bytes of s).
func (x *PicX) MoveString(s string) { x.MoveBytes([]byte(s)) }

// MoveNum is MOVE integer-numeric-item TO x (digits without sign, P positions as zeros).
func (x *PicX) MoveNum(src *CobolDecimal) {
	p := src.Pic
	if p.Scale > 0 {
		panic("cobolrt: MOVE of a non-integer numeric item to alphanumeric")
	}
	mag := Abs(src.u)
	length := len(x.Data)
	digits := func(m int64, n int) []byte {
		d := make([]byte, n)
		for i := n - 1; i >= 0; i-- {
			d[i] = byte('0' + m%10)
			m /= 10
		}
		return d
	}
	if p.Usage == Display && !p.Signed && p.Digits >= length {
		copy(x.Data, digits(mag, p.Digits)[:length])
		return
	}
	n := p.Digits
	if p.Usage != Display {
		n = p.GcDigits()
	}
	d := digits(mag%Pow10(min(n, 18)), n)
	zeros := -p.Scale
	size1 := len(d)
	if x.Justified {
		for i := range x.Data {
			x.Data[i] = ' '
		}
		size2 := length
		if zeros > 0 {
			z := min(zeros, size2)
			size2 -= z
			for i := 0; i < z; i++ {
				x.Data[size2+i] = '0'
			}
		}
		if size2 > 0 {
			if diff := size2 - size1; diff > 0 {
				copy(x.Data[diff:], d)
			} else {
				copy(x.Data[:size2], d[size1-size2:])
			}
		}
		return
	}
	if length < size1 {
		copy(x.Data, d[:length])
		return
	}
	copy(x.Data, d)
	rest := length - size1
	z := max(0, min(zeros, rest))
	for i := 0; i < rest; i++ {
		if i < z {
			x.Data[size1+i] = '0'
		} else {
			x.Data[size1+i] = ' '
		}
	}
}

// Compare compares alphanumerically (space padding).
func (x *PicX) Compare(o *PicX) int { return CompareAlnum(x.Data, o.Data) }

// Accept is ACCEPT x from a line (nil = end of input: spaces).
func (x *PicX) Accept(line []byte) {
	if line == nil {
		line = []byte{' '}
	}
	x.MoveBytes(line)
}

// Display returns the bytes DISPLAY prints.
func (x *PicX) Display() []byte { return append([]byte(nil), x.Data...) }

func (x *PicX) String() string { return string(x.Data) }
