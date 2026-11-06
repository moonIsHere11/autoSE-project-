package main

import "strings"

// splitLines splits stdin on '\n' only; a last line without '\n' still counts.
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

// deedit reproduces GnuCOBOL's de-editing of ACCEPTed text into a numeric DISPLAY field;
// the result is the value scaled by 10^scale.
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

// unsignedStr is the DISPLAY of an unsigned numeric DISPLAY field (decimal point inserted).
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

// signedStr is the DISPLAY of a signed numeric DISPLAY field: the sign is always shown first.
func signedStr(v int64, intDigits, scale int) string {
	if v < 0 {
		return "-" + unsignedStr(v, intDigits, scale)
	}
	return "+" + unsignedStr(v, intDigits, scale)
}

func abs64(v int64) int64 {
	if v < 0 {
		return -v
	}
	return v
}
