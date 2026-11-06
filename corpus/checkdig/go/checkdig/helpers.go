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

// num is the DISPLAY of an unsigned integer DISPLAY field with `digits` digits.
func num(v int64, digits int) string {
	if v < 0 {
		v = -v
	}
	s := []byte(strings.Repeat("0", digits))
	for k := len(s) - 1; k >= 0 && v > 0; k-- {
		s[k] = byte('0' + v%10)
		v /= 10
	}
	return string(s)
}

// pad keeps exactly n bytes, space padded on the right.
func pad(s string, n int) string {
	if len(s) >= n {
		return s[:n]
	}
	return s + strings.Repeat(" ", n-len(s))
}
