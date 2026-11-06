// Hand translation of DIVREM. Numerics are int64 scaled by 10^scale. Go's integer division and %
// truncate toward zero, which is COBOL's truncation and its remainder sign rule.
package main

import (
	"bufio"
	"io"
	"os"
	"strings"
)

// Divrem holds the WORKING-STORAGE of DIVREM.
type Divrem struct {
	WsDividend  int64  // S9(2)
	WsDivisor   int64  // 9
	WsQuot      int64  // S9(2)
	WsRem       int64  // S9
	WsQuotR     int64  // S9(2)V9, scale 1
	WsRemR      int64  // S9V99, scale 2
	WsRatio     int64  // S9V9 VALUE 0, scale 1
	WsRatioFlag string // X VALUE SPACE
	WsUquot     int64  // 9(2) VALUE 77
	WsAcc       int64  // S9(3) VALUE 120
	WsCheck     int64  // S9(3)
	WsStatus    string // X(4)
	WsKind      string // X(9)
	WsDivClass  string // X(8)
	WsGcdA      int64  // 9(2)
	WsGcdB      int64  // 9(2)
	WsGcdQ      int64  // 9(2)
	WsGcdT      int64  // 9(2)
	WsSteps     int64  // 9(2) VALUE 0
	ReturnCode  int

	lines []string
	out   strings.Builder
}

func newDivrem(stdin []byte) *Divrem {
	return &Divrem{WsRatioFlag: " ", WsUquot: 77, WsAcc: 120, WsStatus: "    ", WsKind: strings.Repeat(" ", 9),
		WsDivClass: strings.Repeat(" ", 8), lines: splitLines(stdin)}
}

// MainPara is MAIN-PARA.
func (p *Divrem) MainPara() {
	p.GetOperands()
	p.DoDivide()
	p.ClassifyResult()
	p.FindGcd()
	p.ShowResult()
	p.SetReturn()
}

// GetOperands is GET-OPERANDS.
func (p *Divrem) GetOperands() {
	p.WsDividend = p.acceptNumeric(2, 2, 0, true)
	p.WsDivisor = p.acceptNumeric(1, 1, 0, false)
}

// DoDivide is DO-DIVIDE.
func (p *Divrem) DoDivide() {
	if p.WsDivisor == 0 {
		p.WsStatus = "ZDIV" // ON SIZE ERROR: targets unchanged
	} else {
		q := p.WsDividend / p.WsDivisor
		p.WsQuot = q % 100
		p.WsRem = (p.WsDividend - q*p.WsDivisor) % 10
		p.WsStatus = "OK  "
	}
	if p.WsDivisor != 0 {
		n := p.WsDividend * 10 // quotient at scale 1
		qt := n / p.WsDivisor  // truncated quotient
		r := n % p.WsDivisor
		qr := qt
		if 2*abs64(r) >= p.WsDivisor {
			if n < 0 {
				qr = qt - 1
			} else {
				qr = qt + 1
			}
		}
		p.WsQuotR = qr % 1000
		p.WsRemR = ((n - qt*p.WsDivisor) * 10) % 1000 // the remainder uses the truncated quotient
	}
	if p.WsDivisor == 0 {
		p.WsRatioFlag = "Y"
	} else {
		n := p.WsDividend * 10
		q := n / p.WsDivisor
		r := n % p.WsDivisor
		if 2*abs64(r) >= p.WsDivisor {
			if n < 0 {
				q--
			} else {
				q++
			}
		}
		if q >= 100 || q <= -100 {
			p.WsRatioFlag = "Y"
		} else {
			p.WsRatio = q
			p.WsRatioFlag = "N"
		}
	}
	if p.WsDivisor != 0 { // no SIZE ERROR phrase: a zero divisor leaves the target as is
		p.WsAcc = (p.WsAcc / p.WsDivisor) % 1000
	}
	if p.WsDivisor != 0 {
		q := p.WsDividend / p.WsDivisor
		p.WsUquot = abs64(q) % 100 // unsigned target drops the sign
	}
	p.WsCheck = (p.WsQuot*p.WsDivisor + p.WsRem) % 1000
}

// ClassifyResult is CLASSIFY-RESULT.
func (p *Divrem) ClassifyResult() {
	switch {
	case p.WsDivisor == 0:
		p.WsKind = "UNDEFINED"
	case p.WsRem == 0 && p.WsDividend < 0:
		p.WsKind = "NEG-EXACT"
	case p.WsRem == 0:
		p.WsKind = "EXACT    "
	case p.WsRem < 0 && p.WsDivisor >= 1 && p.WsDivisor <= 3:
		p.WsKind = "NEG-SMALL"
	default:
		p.WsKind = "INEXACT  "
	}
	switch {
	case p.WsDivisor == 0:
		p.WsDivClass = "NONE    "
	case p.WsDivisor >= 1 && p.WsDivisor <= 3:
		p.WsDivClass = "LOW-DIV "
	case p.WsQuot == 0:
		p.WsDivClass = "ZERO-Q  "
	case p.WsQuot >= -9 && p.WsQuot <= -1:
		p.WsDivClass = "NEG-Q   "
	default:
		p.WsDivClass = "HIGH-DIV"
	}
}

// FindGcd is FIND-GCD.
func (p *Divrem) FindGcd() {
	p.WsGcdA = abs64(p.WsDividend) % 100
	p.WsGcdB = p.WsDivisor
	for p.WsGcdB != 0 {
		p.WsGcdQ = (p.WsGcdA / p.WsGcdB) % 100
		p.WsGcdT = (p.WsGcdA % p.WsGcdB) % 100
		p.WsGcdA = p.WsGcdB
		p.WsGcdB = p.WsGcdT
		p.WsSteps = (p.WsSteps + 1) % 100
	}
}

// ShowResult is SHOW-RESULT.
func (p *Divrem) ShowResult() {
	p.line("DIVIDEND " + signedStr(p.WsDividend, 2, 0) + " DIVISOR " + unsignedStr(p.WsDivisor, 1, 0) +
		" STATUS " + p.WsStatus)
	p.line("QUOT " + signedStr(p.WsQuot, 2, 0) + " REM " + signedStr(p.WsRem, 1, 0) + " CHECK " + signedStr(p.WsCheck, 3, 0))
	p.line("QUOT-R " + signedStr(p.WsQuotR, 2, 1) + " REM-R " + signedStr(p.WsRemR, 1, 2))
	p.line("RATIO " + signedStr(p.WsRatio, 1, 1) + " SIZE " + p.WsRatioFlag + " UQUOT " + unsignedStr(p.WsUquot, 2, 0) +
		" ACC " + signedStr(p.WsAcc, 3, 0))
	p.line("KIND " + p.WsKind + " CLASS " + p.WsDivClass + " GCD " + unsignedStr(p.WsGcdA, 2, 0) +
		" STEPS " + unsignedStr(p.WsSteps, 2, 0))
}

// SetReturn is SET-RETURN.
func (p *Divrem) SetReturn() {
	switch {
	case p.WsDivisor == 0:
		p.ReturnCode = 8
	case p.WsRem != 0:
		p.ReturnCode = 1
	default:
		p.ReturnCode = 0
	}
}

func (p *Divrem) line(s string) {
	p.out.WriteString(s)
	p.out.WriteByte('\n')
}

// acceptNumeric is ACCEPT into a numeric DISPLAY field (first byte-length characters); EOF gives 0.
func (p *Divrem) acceptNumeric(window, intDigits, scale int, isSigned bool) int64 {
	if len(p.lines) == 0 {
		return 0
	}
	w := p.lines[0]
	p.lines = p.lines[1:]
	if len(w) > window {
		w = w[:window]
	}
	return deedit(w, intDigits, scale, isSigned)
}

func main() {
	data, err := io.ReadAll(os.Stdin)
	if err != nil {
		os.Exit(2)
	}
	p := newDivrem(data)
	p.MainPara()
	w := bufio.NewWriter(os.Stdout)
	w.WriteString(p.out.String())
	w.Flush()
	os.Exit(p.ReturnCode)
}
