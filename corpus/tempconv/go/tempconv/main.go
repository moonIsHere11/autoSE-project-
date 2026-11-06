// Hand translation of TEMPCONV. Numerics are int64 scaled by 10^scale; every COMPUTE is evaluated
// as an exact fraction num/den and stored with ROUNDED (half away from zero) or truncation, then
// high-order truncation.
//
// GnuCOBOL truncates an intermediate quotient 38 digits beyond the operands' scale. That is only
// observable when an inexact quotient is multiplied back onto an exact storage boundary: in
// `WS-TEMP / 3 * 3` the value 1/3*3 is 0.999…9 (38 nines), which truncates to 0.9. Every other
// expression here either divides last or yields a non-terminating value that is never within
// 1e-38 of a boundary, so exact fractions give identical results there. storeBelow models the
// "just below the exact value" case.
package main

import (
	"bufio"
	"io"
	"os"
	"strconv"
	"strings"
)

// Tempconv holds the WORKING-STORAGE of TEMPCONV.
type Tempconv struct {
	WsTemp       int64  // S9(2)
	WsMode       int64  // 9
	WsCelsius    int64  // S9(3)V99, scale 2
	WsFahr       int64  // S9(3)V99, scale 2
	WsKelvin     int64  // 9(3)V99, scale 2
	WsResult     int64  // S9(3)V9, scale 1
	WsResultT    int64  // S9(3)V9, scale 1
	WsMagnitude  int64  // 9(3)V9, scale 1
	WsThirds     int64  // S9(3)V9, scale 1
	WsThirdsR    int64  // S9(3)V9, scale 1
	WsSpread     int64  // S9(2)V9, scale 1
	WsSpreadFlag string // X(3)
	WsFeel       string // X(8)
	ReturnCode   int

	lines []string
	out   strings.Builder
}

func pow10(n int) int64 {
	p := int64(1)
	for i := 0; i < n; i++ {
		p *= 10
	}
	return p
}

// store keeps num/den (den > 0) at `scale` decimals: ROUNDED or truncated, then high-order truncation.
func store(num, den int64, intDigits, scale int, isSigned, rounded bool) int64 {
	return storeBelow(num, den, intDigits, scale, isSigned, rounded, false)
}

// storeBelow is store for a value that lies an infinitesimal amount closer to zero than num/den.
func storeBelow(num, den int64, intDigits, scale int, isSigned, rounded, below bool) int64 {
	n := num * pow10(scale)
	q := n / den
	r := n % den
	sign := int64(1)
	if n < 0 {
		sign = -1
	}
	if rounded {
		if 2*abs64(r) > den || (2*abs64(r) == den && !below) {
			q += sign
		}
	} else if below && r == 0 && n != 0 {
		q -= sign
	}
	q %= pow10(intDigits + scale)
	if !isSigned {
		q = abs64(q)
	}
	return q
}

// MainPara is MAIN-PARA.
func (p *Tempconv) MainPara() {
	p.GetInput()
	if p.WsMode >= 1 && p.WsMode <= 5 {
		p.Convert()
		p.Classify()
		p.ReportOut()
	} else {
		p.line("UNKNOWN MODE " + strconv.FormatInt(p.WsMode, 10) + " FOR " + signedStr(p.WsTemp, 2, 0))
		p.ReturnCode = 3
	}
}

// GetInput is GET-INPUT.
func (p *Tempconv) GetInput() {
	p.WsTemp = p.acceptNumeric(2, 2, 0, true)
	p.WsMode = p.acceptNumeric(1, 1, 0, false)
}

// Convert is CONVERT.
func (p *Tempconv) Convert() {
	t := p.WsTemp
	switch p.WsMode {
	case 1: // C -> F: T * 9 / 5 + 32 = (9T + 160) / 5
		p.WsCelsius = store(t, 1, 3, 2, true, false)
		p.WsFahr = store(9*t+160, 5, 3, 2, true, true)
		p.WsResult = store(9*t+160, 5, 3, 1, true, true)
		p.WsResultT = store(9*t+160, 5, 3, 1, true, false)
	case 2: // F -> C: (T - 32) * 5 / 9
		p.WsFahr = store(t, 1, 3, 2, true, false)
		p.WsCelsius = store(5*(t-32), 9, 3, 2, true, true)
		p.WsResult = store(5*(t-32), 9, 3, 1, true, true)
		p.WsResultT = store(5*(t-32), 9, 3, 1, true, false)
	case 3: // C -> K: T * 1.8 + 32 and T + 273.15
		p.WsCelsius = store(t, 1, 3, 2, true, false)
		p.WsFahr = store(18*t+320, 10, 3, 2, true, true)
		p.WsResult = store(100*t+27315, 100, 3, 1, true, true)
		p.WsResultT = store(100*t+27315, 100, 3, 1, true, false)
	case 4: // F -> K: (T - 32) / 1.8 = 5(T - 32) / 9, plus 273.15
		p.WsFahr = store(t, 1, 3, 2, true, false)
		p.WsCelsius = store(5*(t-32), 9, 3, 2, true, true)
		p.WsResult = store(500*(t-32)+9*27315, 900, 3, 1, true, true)
		p.WsResultT = store(500*(t-32)+9*27315, 900, 3, 1, true, false)
	default: // C -> F -> C round trip
		p.WsCelsius = store(t, 1, 3, 2, true, false)
		p.WsFahr = store(9*t+160, 5, 3, 2, true, true)
		f := p.WsFahr // scale 2: (F/100 - 32) * 5 / 9 = 5(F - 3200) / 900
		p.WsResult = store(5*(f-3200), 900, 3, 1, true, true)
		p.WsResultT = store(5*(f-3200), 900, 3, 1, true, false)
	}
	p.WsKelvin = store(p.WsCelsius+27315, 100, 3, 2, false, true)
	p.WsMagnitude = store(p.WsResult, 10, 3, 1, false, false)
	inexact := t%3 != 0 // T / 3 does not terminate: T / 3 * 3 lies just below T
	p.WsThirds = storeBelow(t, 1, 3, 1, true, false, inexact)
	p.WsThirdsR = storeBelow(t, 1, 3, 1, true, true, inexact)
	spread := p.WsFahr - p.WsCelsius // scale 2
	if abs64(spread/10) >= 1000 {    // S9(2)V9: ON SIZE ERROR
		p.WsSpreadFlag = "OVF"
	} else {
		p.WsSpread = store(spread, 100, 2, 1, true, false)
		p.WsSpreadFlag = "OK "
	}
}

// Classify is CLASSIFY.
func (p *Tempconv) Classify() {
	c := p.WsCelsius
	switch {
	case c < -1000:
		p.WsFeel = "FREEZING"
	case c < 0:
		p.WsFeel = "COLD    "
	case c == 0:
		p.WsFeel = "ZERO    "
	case c < 2000:
		p.WsFeel = "MILD    "
	case c < 3000:
		p.WsFeel = "WARM    "
	default:
		p.WsFeel = "HOT     "
	}
}

// ReportOut is REPORT-OUT.
func (p *Tempconv) ReportOut() {
	p.line("MODE " + strconv.FormatInt(p.WsMode, 10) + " INPUT " + signedStr(p.WsTemp, 2, 0))
	p.line("CELSIUS " + signedStr(p.WsCelsius, 3, 2) + " FAHRENHEIT " + signedStr(p.WsFahr, 3, 2) +
		" KELVIN " + unsignedStr(p.WsKelvin, 3, 2))
	p.line("RESULT " + signedStr(p.WsResult, 3, 1) + " TRUNCATED " + signedStr(p.WsResultT, 3, 1) +
		" MAGNITUDE " + unsignedStr(p.WsMagnitude, 3, 1))
	p.line("THIRDS " + signedStr(p.WsThirds, 3, 1) + " ROUNDED " + signedStr(p.WsThirdsR, 3, 1))
	p.line("SPREAD " + signedStr(p.WsSpread, 2, 1) + " " + p.WsSpreadFlag + " FEEL " + p.WsFeel)
}

func (p *Tempconv) line(s string) {
	p.out.WriteString(s)
	p.out.WriteByte('\n')
}

func (p *Tempconv) acceptNumeric(window, intDigits, scale int, isSigned bool) int64 {
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
	p := &Tempconv{WsSpreadFlag: "   ", WsFeel: strings.Repeat(" ", 8), lines: splitLines(data)}
	p.MainPara()
	w := bufio.NewWriter(os.Stdout)
	w.WriteString(p.out.String())
	w.Flush()
	os.Exit(p.ReturnCode)
}
