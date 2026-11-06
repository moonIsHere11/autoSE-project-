package cobolrt

import (
	"bufio"
	"io"
)

// MoveAlnum: MOVE src TO dst (PIC X(len(dst))): left-aligned, space padded, right-truncated;
// justified = JUSTIFIED RIGHT (right-aligned, left-truncated).
func MoveAlnum(src, dst []byte, justified bool) {
	s := append([]byte(nil), src...)
	if justified {
		if len(s) >= len(dst) {
			copy(dst, s[len(s)-len(dst):])
			return
		}
		pad := len(dst) - len(s)
		for i := 0; i < pad; i++ {
			dst[i] = ' '
		}
		copy(dst[pad:], s)
		return
	}
	n := copy(dst, s)
	for i := n; i < len(dst); i++ {
		dst[i] = ' '
	}
}

// CompareAlnum compares with space padding of the shorter operand: -1, 0, 1.
func CompareAlnum(a, b []byte) int {
	n := max(len(a), len(b))
	for i := 0; i < n; i++ {
		x, y := byte(' '), byte(' ')
		if i < len(a) {
			x = a[i]
		}
		if i < len(b) {
			y = b[i]
		}
		if x != y {
			if x < y {
				return -1
			}
			return 1
		}
	}
	return 0
}

// Refmod returns a copy of data(start:length), 1-based.
func Refmod(data []byte, start, length int) []byte {
	return append([]byte(nil), data[start-1:start-1+length]...)
}

// SetRefmod: MOVE value TO data(start:length).
func SetRefmod(data []byte, start, length int, value []byte) {
	MoveAlnum(value, data[start-1:start-1+length], false)
}

func isSpace(c byte) bool {
	return c == ' ' || c == '\t' || c == '\n' || c == 0x0B || c == '\f' || c == '\r'
}

// deedit implements cob_move_alphanum_to_display: returns `size` digit chars and the sign.
func deedit(src []byte, size, scale int) ([]byte, int) {
	data := make([]byte, size)
	for i := range data {
		data[i] = '0'
	}
	zero := func() ([]byte, int) {
		z := make([]byte, size)
		for i := range z {
			z[i] = '0'
		}
		return z, 0
	}
	e1 := len(src)
	s1 := 0
	for s1 < e1 && isSpace(src[s1]) {
		s1++
	}
	sg := 0
	if s1 != e1 && (src[s1] == '+' || src[s1] == '-') {
		if src[s1] == '+' {
			sg = 1
		} else {
			sg = -1
		}
		s1++
	}
	count := 0
	for p := s1; p < e1 && src[p] != '.'; p++ {
		if src[p] >= '0' && src[p] <= '9' {
			count++
		}
	}
	isize := size - scale
	s2 := 0
	if count < isize {
		s2 = isize - count
	} else {
		for count > isize {
			for s1 < e1 && !(src[s1] >= '0' && src[s1] <= '9') {
				s1++
			}
			s1++
			count--
		}
	}
	points := 0
	for s1 < e1 && s2 < size {
		c := src[s1]
		switch {
		case c >= '0' && c <= '9':
			data[s2] = c
			s2++
		case c == '.':
			points++
			if points > 1 {
				return zero()
			}
		case !(isSpace(c) || c == ','):
			return zero()
		}
		s1++
	}
	return data, sg
}

// Accept reads stdin lines as GnuCOBOL's ACCEPT does (one line per ACCEPT; nil at end of input).
type Accept struct{ r *bufio.Reader }

// NewAccept wraps a reader (normally os.Stdin).
func NewAccept(r io.Reader) *Accept { return &Accept{bufio.NewReader(r)} }

// ReadLine returns the next line without its newline, or nil at end of input.
func (a *Accept) ReadLine() []byte {
	line, err := a.r.ReadBytes('\n')
	if len(line) == 0 && err != nil {
		return nil
	}
	if line[len(line)-1] == '\n' {
		line = line[:len(line)-1]
	}
	return line
}

// Num reads the next line into a numeric item.
func (a *Accept) Num(d *CobolDecimal) { d.Accept(a.ReadLine()) }

// X reads the next line into a PIC X item.
func (a *Accept) X(x *PicX) { x.Accept(a.ReadLine()) }
