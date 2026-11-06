package cobolrt

import (
	"fmt"
	"math/big"
	"strings"
)

// MaxDigits is COB_MAX_DIGITS: extra fractional digits kept by a COMPUTE division.
const MaxDigits = 38

// Dec is an exact intermediate (GnuCOBOL's cob_decimal): V * 10^-Scale, or NaN after a
// division by zero. Add/Sub/Mul are exact; Div keeps 38 extra digits and truncates. Immutable.
type Dec struct {
	V     *big.Int
	Scale int
	NaN   bool
}

var bigTen = big.NewInt(10)

func bpow10(n int) *big.Int { return new(big.Int).Exp(bigTen, big.NewInt(int64(n)), nil) }

// bshift returns v*10^n, truncating toward zero for n < 0.
func bshift(v *big.Int, n int) *big.Int {
	if n >= 0 {
		return new(big.Int).Mul(v, bpow10(n))
	}
	return new(big.Int).Quo(v, bpow10(-n))
}

// DecOf makes an intermediate from an unscaled int64.
func DecOf(u int64, scale int) Dec { return Dec{big.NewInt(u), scale, false} }

// DecInt is an integer intermediate.
func DecInt(v int64) Dec { return DecOf(v, 0) }

// NaNDec is the result of a division by zero.
var NaNDec = Dec{big.NewInt(0), 0, true}

var zeroDec = Dec{big.NewInt(0), 0, false}

type lit struct {
	v       *big.Int
	scale   int
	minus   bool
	ndigits int
}

func parseLit(text string) lit {
	t := strings.TrimSpace(text)
	neg := strings.HasPrefix(t, "-")
	if strings.HasPrefix(t, "-") || strings.HasPrefix(t, "+") {
		t = t[1:]
	}
	ip, fp, _ := strings.Cut(t, ".")
	all := ip + fp
	v, ok := new(big.Int).SetString(all, 10)
	if !ok || all == "" || strings.Contains(fp, ".") || strings.ContainsAny(all, "+-") {
		panic(fmt.Sprintf("cobolrt: not a numeric literal: %q", text))
	}
	if neg {
		v.Neg(v)
	}
	return lit{v, len(fp), neg, len(t)}
}

func (l lit) fitsInt() bool      { return l.scale == 0 && l.v.BitLen() <= 31 }
func (l lit) fitsLongLong() bool { return l.scale == 0 && l.v.BitLen() <= 63 }

// Literal parses a numeric literal such as "-12.50".
func Literal(text string) Dec {
	l := parseLit(text)
	return Dec{l.v, l.scale, false}
}

// Add returns d + o.
func (d Dec) Add(o Dec) Dec {
	if d.NaN || o.NaN {
		return NaNDec
	}
	if d.Scale != o.Scale {
		if o.V.Sign() == 0 {
			return d
		}
		if d.V.Sign() == 0 {
			return o
		}
		s := max(d.Scale, o.Scale)
		return Dec{new(big.Int).Add(bshift(d.V, s-d.Scale), bshift(o.V, s-o.Scale)), s, false}
	}
	return Dec{new(big.Int).Add(d.V, o.V), d.Scale, false}
}

// Sub returns d - o.
func (d Dec) Sub(o Dec) Dec {
	if d.NaN || o.NaN {
		return NaNDec
	}
	if d.Scale != o.Scale {
		if o.V.Sign() == 0 {
			return d
		}
		s := max(d.Scale, o.Scale)
		return Dec{new(big.Int).Sub(bshift(d.V, s-d.Scale), bshift(o.V, s-o.Scale)), s, false}
	}
	return Dec{new(big.Int).Sub(d.V, o.V), d.Scale, false}
}

// Mul returns d * o.
func (d Dec) Mul(o Dec) Dec {
	if d.NaN || o.NaN {
		return NaNDec
	}
	return Dec{new(big.Int).Mul(d.V, o.V), d.Scale + o.Scale, false}
}

// Div returns d / o with 38 extra fractional digits, truncated (NaN if o is zero).
func (d Dec) Div(o Dec) Dec {
	if d.NaN || o.NaN || o.V.Sign() == 0 {
		return NaNDec
	}
	if d.V.Sign() == 0 {
		return zeroDec
	}
	s := d.Scale - o.Scale
	sh := MaxDigits
	if s < 0 {
		sh -= s
	}
	return Dec{new(big.Int).Quo(bshift(d.V, sh), o.V), s + sh, false}
}

// Neg is unary minus (cobc builds 0 - x).
func (d Dec) Neg() Dec { return zeroDec.Sub(d) }

func (d Dec) String() string {
	if d.NaN {
		return "NaN"
	}
	return fmt.Sprintf("%sE-%d", d.V, d.Scale)
}
