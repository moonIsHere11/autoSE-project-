package cobolrt

import (
	"strconv"
	"strings"
)

// Encode returns the storage bytes of an item holding u (DISPLAY zoned with ASCII overpunch or
// SEPARATE sign, COMP-3 with C/D/F nibble, COMP big-endian, COMP-5 little-endian). negZero,
// fnib (COMP-3 sign nibble F in a signed item) and pad (garbage pad digit) are byte details
// GnuCOBOL can leave behind; pass false/false/0 for canonical bytes.
func Encode(u int64, p Pic, negZero, fnib bool, pad int) []byte {
	n := p.ByteLength()
	out := make([]byte, n)
	if p.IsBinary() {
		for i := 0; i < n; i++ {
			b := byte(uint64(u) >> (8 * uint(i)))
			if p.Usage == Comp {
				out[n-1-i] = b
			} else {
				out[i] = b
			}
		}
		return out
	}
	neg := u < 0 || (negZero && u == 0)
	mag := Abs(u) % Pow10(p.Digits)
	if p.Usage == Display {
		off := 0
		if p.SignSeparate && p.SignLeading {
			off = 1
		}
		for i := p.Digits - 1; i >= 0; i-- {
			out[off+i] = byte('0' + mag%10)
			mag /= 10
		}
		if p.Signed {
			if p.SignSeparate {
				c := byte('+')
				if neg {
					c = '-'
				}
				if p.SignLeading {
					out[0] = c
				} else {
					out[n-1] = c
				}
			} else if neg {
				i := n - 1
				if p.SignLeading {
					i = 0
				}
				out[i] += 0x40
			}
		}
		return out
	}
	nib := 2*n - 1
	digits := make([]int64, nib)
	for i, k := nib-1, 0; i >= 0; i, k = i-1, k+1 {
		if k < p.Digits {
			digits[i] = mag % 10
			mag /= 10
		} else if k == p.Digits && p.Digits%2 == 0 {
			digits[i] = int64(pad)
		}
	}
	sn := byte(0x0C)
	if !p.Signed || fnib {
		sn = 0x0F
	} else if neg {
		sn = 0x0D
	}
	for i := 0; i < n; i++ {
		lo := sn
		if i < n-1 {
			lo = byte(digits[2*i+1])
		}
		out[i] = byte(digits[2*i])<<4 | lo
	}
	return out
}

// Decode loads storage bytes into an item's state.
func Decode(data []byte, d *CobolDecimal) {
	p := d.Pic
	if len(data) != p.ByteLength() {
		panic("cobolrt: wrong record length for item")
	}
	if p.IsBinary() {
		n := len(data)
		var v uint64
		for i := 0; i < n; i++ {
			b := data[i]
			if p.Usage == Comp5 {
				b = data[n-1-i]
			}
			v = v<<8 | uint64(b)
		}
		x := int64(v)
		if p.Signed && n < 8 && x&(int64(1)<<(8*uint(n)-1)) != 0 {
			x -= int64(1) << (8 * uint(n))
		}
		d.setState(x, false, false, 0)
		return
	}
	if p.Usage == Display {
		b := append([]byte(nil), data...)
		neg := false
		from, to := 0, len(b)
		if p.Signed && p.SignSeparate {
			if p.SignLeading {
				neg = b[0] == '-'
				from = 1
			} else {
				neg = b[to-1] == '-'
				to--
			}
		} else if p.Signed {
			i := len(b) - 1
			if p.SignLeading {
				i = 0
			}
			if b[i] >= 0x70 && b[i] <= 0x79 {
				neg = true
				b[i] -= 0x40
			}
		}
		var mag int64
		for i := from; i < to; i++ {
			c := b[i]
			dg := int64(c & 0x0F)
			if c == ' ' {
				dg = 0
			}
			mag = mag*10 + dg
		}
		if neg {
			d.setState(-mag, mag == 0, false, 0)
		} else {
			d.setState(mag, false, false, 0)
		}
		return
	}
	n := len(data)
	var mag int64
	pad := 0
	for i := 0; i < 2*n-1; i++ {
		b := data[i/2]
		dg := int(b & 0x0F)
		if i%2 == 0 {
			dg = int(b >> 4)
		}
		if i == 0 && p.Digits%2 == 0 {
			pad = dg
		} else {
			mag = mag*10 + int64(dg)
		}
	}
	sn := data[n-1] & 0x0F
	neg := p.Signed && sn == 0x0D
	if neg {
		mag = -mag
	}
	d.setState(mag, neg && mag == 0, p.Signed && sn == 0x0F, pad)
}

var comp5Digits = map[int]int{1: 3, 2: 5, 4: 10, 8: 20}

// DisplayNumeric is what DISPLAY prints for a numeric item holding u (pretty-display).
func DisplayNumeric(u int64, p Pic) []byte {
	if p.Usage == Comp5 {
		var body string
		if p.IsU64() {
			body = strconv.FormatUint(uint64(u), 10)
		} else if u == -9223372036854775808 {
			body = "9223372036854775808"
		} else {
			body = strconv.FormatInt(Abs(u), 10)
		}
		w := comp5Digits[p.ByteLength()]
		s := ""
		if p.Signed {
			if u < 0 {
				s = "-"
			} else {
				s = "+"
			}
		}
		return []byte(s + strings.Repeat("0", max(0, w-len(body))) + body)
	}
	mag := strconv.FormatInt(Abs(u), 10)
	var body string
	if p.Scale <= 0 {
		v := "0"
		if u != 0 {
			v = mag + strings.Repeat("0", -p.Scale)
		}
		body = strings.Repeat("0", max(0, p.Digits-p.Scale-len(v))) + v
	} else {
		w := max(p.Digits, p.Scale)
		s := strings.Repeat("0", max(0, w-len(mag))) + mag
		body = s[:w-p.Scale] + "." + s[w-p.Scale:]
	}
	if !p.Signed {
		return []byte(body)
	}
	sg := "+"
	if u < 0 {
		sg = "-"
	}
	if p.SignSeparate && !p.SignLeading {
		return []byte(body + sg)
	}
	return []byte(sg + body)
}

// DisplayLine returns the bytes of `DISPLAY a b ...` (items *CobolDecimal / *PicX, string
// literals, []byte), including the newline.
func DisplayLine(items ...any) []byte {
	var out []byte
	for _, it := range items {
		switch v := it.(type) {
		case *CobolDecimal:
			out = append(out, v.Display()...)
		case *PicX:
			out = append(out, v.Data...)
		case []byte:
			out = append(out, v...)
		case string:
			for i := 0; i < len(v); i++ {
				out = append(out, v[i])
			}
		}
	}
	return append(out, '\n')
}
