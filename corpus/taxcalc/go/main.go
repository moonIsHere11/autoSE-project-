// Hand translation of TAXCALC with package-level state. Numerics are int64 scaled by 10^scale
// (WS-INCOME PIC 9(6)V99 holds cents). The main package is the repository root.
package main

import (
	"bufio"
	"io"
	"os"
	"strings"
)

var (
	WsCategory  int64            // 9
	WsIncomeK   int64            // 9(2)
	WsIncome    int64            // 9(6)V99, scale 2
	WsDeduction int64            // 9(5)V99, scale 2
	WsTaxable   int64            // S9(6)V99, scale 2
	WsGap       int64            // 9(6)V99, scale 2
	WsRate      int64            // V999, scale 3
	WsBracket   = "      "       // X(6)
	WsTax       int64            // 9(5)V99
	WsTaxTrunc  int64            // 9(5)V99
	WsSurcharge int64            // 9(3)V99 VALUE 0
	WsTotalTax  int64            // 9(5)V99
	WsEffRate   int64            // 9(2)V99 VALUE 0
	WsSizeFlag  = "N"            // X VALUE "N"
	WsRateFlag  = "N"            // X VALUE "N"
	ReturnCode  int
	lines       []string
	out         strings.Builder
)

// MainPara is MAIN-PARA.
func MainPara() {
	ReadInput()
	if WsCategory <= 3 { // CAT-VALID: 0 THRU 3
		ComputeTax()
		ShowResult()
	} else {
		line("INVALID CATEGORY " + unsignedStr(WsCategory, 1, 0))
		ReturnCode = 4
	}
}

// ReadInput is READ-INPUT.
func ReadInput() {
	WsCategory = acceptNumeric(1, 1, 0, false)
	WsIncomeK = acceptNumeric(2, 2, 0, false)
}

// ComputeTax is COMPUTE-TAX.
func ComputeTax() {
	WsIncome = (WsIncomeK * 1000 * 100) % 100000000
	switch WsCategory {
	case 0:
		WsDeduction = 9999999
	case 1:
		WsDeduction = 1255000
	case 2:
		WsDeduction = 2510000
	default:
		WsDeduction = 1880050
	}
	WsTaxable = (WsIncome - WsDeduction) % 100000000
	WsGap = abs64(WsIncome-WsDeduction) % 100000000 // unsigned target: the sign is dropped
	if WsTaxable < 0 {
		WsTaxable = 0
	}
	switch {
	case WsIncomeK <= 9:
		WsRate = 0
		WsBracket = "NIL   "
	case WsIncomeK <= 39:
		WsRate = 100
		WsBracket = "LOW   "
	case WsIncomeK <= 84:
		WsRate = 225
		WsBracket = "MIDDLE"
	default:
		WsRate = 333
		WsBracket = "HIGH  "
	}
	product := WsTaxable * WsRate               // scale 5, never negative
	WsTax = ((product + 500) / 1000) % 10000000 // ROUNDED to scale 2
	WsTaxTrunc = (product / 1000) % 10000000    // truncated
	surcharge := (WsTax*75 + 500) / 1000        // WS-TAX * 0.075, ROUNDED
	overflow := surcharge > 99999               // 9(3)V99: ON SIZE ERROR
	if overflow {
		WsSizeFlag = "Y" // target left unchanged
	} else {
		WsSurcharge = surcharge
		WsSizeFlag = "N"
	}
	WsTotalTax = (WsTax + WsSurcharge) % 10000000
	if WsIncome == 0 {
		WsRateFlag = "Z" // divide by zero: size error
	} else {
		n := WsTotalTax * 10000 // (total * 100 / income) at scale 2
		q := n / WsIncome
		r := n % WsIncome
		if 2*r >= WsIncome {
			q++
		}
		if q > 9999 {
			WsRateFlag = "Z"
		} else {
			WsEffRate = q
		}
	}
	if overflow {
		ReturnCode = 2
	}
}

// ShowResult is SHOW-RESULT.
func ShowResult() {
	line("CATEGORY " + unsignedStr(WsCategory, 1, 0) + " INCOME " + unsignedStr(WsIncome, 6, 2) + " BRACKET " + WsBracket)
	line("DEDUCTION " + unsignedStr(WsDeduction, 5, 2) + " TAXABLE " + signedStr(WsTaxable, 6, 2) +
		" GAP " + unsignedStr(WsGap, 6, 2))
	line("TAX " + unsignedStr(WsTax, 5, 2) + " TRUNC " + unsignedStr(WsTaxTrunc, 5, 2) +
		" SURCHARGE " + unsignedStr(WsSurcharge, 3, 2) + " OVERFLOW " + WsSizeFlag)
	line("TOTAL " + unsignedStr(WsTotalTax, 5, 2) + " EFFECTIVE " + unsignedStr(WsEffRate, 2, 2) + "% FLAG " + WsRateFlag)
}

func line(s string) {
	out.WriteString(s)
	out.WriteByte('\n')
}

func acceptNumeric(window, intDigits, scale int, isSigned bool) int64 {
	if len(lines) == 0 {
		return 0
	}
	w := lines[0]
	lines = lines[1:]
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
	lines = splitLines(data)
	MainPara()
	w := bufio.NewWriter(os.Stdout)
	w.WriteString(out.String())
	w.Flush()
	os.Exit(ReturnCode)
}
