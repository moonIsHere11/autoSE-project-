// Hand translation of S1PROG: decimals are int64 values scaled by 10^scale (never float).
package main

import (
	"bufio"
	"io"
	"os"
	"strings"
)

// S1prog holds the WORKING-STORAGE of S1PROG.
type S1prog struct {
	WsA        int64 // S9(5)V99 VALUE 0, scale 2
	WsB        int64 // 9(3) VALUE 0
	WsR        int64 // S9(5)V99 VALUE 0, scale 2
	WsI        int64 // 9(2)
	ReturnCode int

	lines []string
	pos   int
	out   strings.Builder
}

// MainPara is MAIN-PARA.
func (p *S1prog) MainPara() {
	p.WsA = p.accept(p.WsA, 7, 5, 2, true)
	p.WsB = p.accept(p.WsB, 3, 3, 0, false)
	p.CalcPara()
	for p.WsI = 1; p.WsI <= 2; p.WsI++ {
		p.display("I=" + unsignedStr(p.WsI, 2, 0))
	}
	if p.WsR > 100*100 {
		p.display("BIG")
	} else {
		p.display("SMALL")
	}
	p.display("R=" + signedStr(p.WsR, 5, 2))
	p.ReturnCode = 3
}

// CalcPara is CALC-PARA: WS-A * 1.5 + WS-B exact at scale 3, ROUNDED to scale 2.
func (p *S1prog) CalcPara() {
	exact := p.WsA*15 + p.WsB*1000
	q := exact / 10
	r := exact % 10
	if r >= 5 || r <= -5 {
		if exact < 0 {
			q--
		} else {
			q++
		}
	}
	p.WsR = q % 10000000
}

// NeverPara is NEVER-PARA.
func (p *S1prog) NeverPara() {
	p.display("NEVER")
}

func (p *S1prog) display(s string) {
	p.out.WriteString(s)
	p.out.WriteByte('\n')
}

func (p *S1prog) accept(current int64, window, intDigits, scale int, isSigned bool) int64 {
	if p.pos >= len(p.lines) {
		return current
	}
	line := p.lines[p.pos]
	p.pos++
	if len(line) > window {
		line = line[:window]
	}
	return deedit(line, intDigits, scale, isSigned)
}

func splitLines(data []byte) []string {
	if len(data) == 0 {
		return nil
	}
	parts := strings.Split(string(data), "\n")
	if data[len(data)-1] == '\n' {
		parts = parts[:len(parts)-1]
	}
	return parts
}

// deedit reproduces GnuCOBOL's de-editing of ACCEPTed text into a numeric DISPLAY field.
func deedit(w string, intDigits, scale int, isSigned bool) int64 {
	i, n := 0, len(w)
	for i < n && w[i] == ' ' {
		i++
	}
	neg := false
	if i < n && (w[i] == '+' || w[i] == '-') {
		neg = w[i] == '-'
		i++
		for i < n && w[i] == ' ' {
			i++
		}
	}
	var ip, fp []byte
	dot := false
	for ; i < n; i++ {
		c := w[i]
		if c >= '0' && c <= '9' {
			if dot {
				fp = append(fp, c)
			} else {
				ip = append(ip, c)
			}
		} else if c == '.' && !dot {
			dot = true
		} else if c != ',' {
			break
		}
	}
	for i < n && w[i] == ' ' {
		i++
	}
	if i < n {
		c := w[i]
		onlySign := (c == '+' || c == '-') && strings.TrimSpace(w[i+1:]) == ""
		if !onlySign || scale > 0 {
			return 0
		}
	}
	if len(ip)+len(fp) == 0 {
		return 0
	}
	if len(ip) > intDigits {
		ip = ip[len(ip)-intDigits:]
	}
	var v int64
	for _, c := range ip {
		v = v*10 + int64(c-'0')
	}
	for k := 0; k < scale; k++ {
		d := int64(0)
		if k < len(fp) {
			d = int64(fp[k] - '0')
		}
		v = v*10 + d
	}
	if neg && isSigned {
		return -v
	}
	return v
}

func unsignedStr(v int64, intDigits, scale int) string {
	if v < 0 {
		v = -v
	}
	s := []byte(strings.Repeat("0", intDigits+scale))
	for k := len(s) - 1; k >= 0 && v > 0; k-- {
		s[k] = byte('0' + v%10)
		v /= 10
	}
	if scale > 0 {
		return string(s[:intDigits]) + "." + string(s[intDigits:])
	}
	return string(s)
}

func signedStr(v int64, intDigits, scale int) string {
	if v < 0 {
		return "-" + unsignedStr(v, intDigits, scale)
	}
	return "+" + unsignedStr(v, intDigits, scale)
}

func main() {
	data, err := io.ReadAll(os.Stdin)
	if err != nil {
		os.Exit(2)
	}
	p := &S1prog{lines: splitLines(data)}
	p.MainPara()
	w := bufio.NewWriter(os.Stdout)
	w.WriteString(p.out.String())
	w.Flush()
	os.Exit(p.ReturnCode)
}
