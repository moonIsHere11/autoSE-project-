// Hand translation of T2APROG with package-level state (int64 scaled by 10^scale).
// Single-program repository: the main package is the repository root and there is no go.mod
// (the verifier creates one in its workspace copy).
package main

import (
	"bufio"
	"io"
	"os"
	"strings"
)

var (
	WsQty   int64 // 9(2)
	WsCode  int64 // 9
	WsPrice int64 // 9(3)V99, scale 2
	WsTotal int64 // 9(4)V99, scale 2
	WsDisc  int64 // 9(3)V99, scale 2
	WsNet   int64 // S9(4)V99, scale 2
)

var (
	lines []string
	out   strings.Builder
)

// MainPara is MAIN-PARA.
func MainPara() {
	WsQty = accept(WsQty, 2)
	WsCode = accept(WsCode, 1)
	CalcPara()
	sign := "+"
	if WsNet < 0 {
		sign = "-"
	}
	out.WriteString("TOTAL=" + fmtNum(WsTotal, 4, 2) + " NET=" + sign + fmtNum(WsNet, 4, 2) + "\n")
}

// CalcPara is CALC-PARA.
func CalcPara() {
	switch {
	case WsCode == 0:
		WsPrice = 125
	case WsCode >= 1 && WsCode <= 4:
		WsPrice = 1999
	default:
		WsPrice = 750
	}
	// qty * price (scale 2) * 1.075 (scale 3) exact at scale 5; ROUNDED to scale 2 (never negative)
	exact := WsQty * WsPrice * 1075
	WsTotal = ((exact + 500) / 1000) % 1000000
	if WsQty > 50 {
		WsDisc = ((WsTotal*125 + 500) / 1000) % 100000
	} else {
		WsDisc = 0
	}
	WsNet = (WsTotal - WsDisc) % 1000000
}

// accept reads one line into an unsigned integer DISPLAY field of `width` digits.
func accept(current int64, width int) int64 {
	if len(lines) == 0 {
		return current
	}
	w := lines[0]
	lines = lines[1:]
	if len(w) > width {
		w = w[:width]
	}
	return deedit(w, width, 0, false)
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

func fmtNum(v int64, intDigits, scale int) string {
	if v < 0 {
		v = -v
	}
	s := []byte(strings.Repeat("0", intDigits+scale))
	for k := len(s) - 1; k >= 0 && v > 0; k-- {
		s[k] = byte('0' + v%10)
		v /= 10
	}
	return string(s[:intDigits]) + "." + string(s[intDigits:])
}

func main() {
	data, err := io.ReadAll(os.Stdin)
	if err != nil {
		os.Exit(2)
	}
	if len(data) > 0 {
		lines = strings.Split(string(data), "\n")
		if data[len(data)-1] == '\n' {
			lines = lines[:len(lines)-1]
		}
	}
	MainPara()
	w := bufio.NewWriter(os.Stdout)
	w.WriteString(out.String())
	w.Flush()
	os.Exit(0)
}
