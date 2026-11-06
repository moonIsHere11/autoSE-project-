// Hand translation of CHECKDIG: mod-11 check digits for up to three account numbers.
package main

import (
	"bufio"
	"io"
	"os"
	"strings"
)

// Checkdig holds the WORKING-STORAGE of CHECKDIG.
type Checkdig struct {
	WsAccount    string // X(10)
	WsAcctNo     int64  // 9(1) VALUE 0
	WsValidCount int64  // 9(1) VALUE 0
	WsI          int64  // 9(2)
	WsWeight     int64  // 9(2)
	WsDigit      int64  // 9(1)
	WsGiven      int64  // 9(1)
	WsSum        int64  // 9(3)
	WsQuot       int64  // 9(3)
	WsRem        int64  // 9(2)
	WsCheck      int64  // 9(2)
	WsCheckD     int64  // 9(1)
	WsCheckX     string // X(1)
	WsBad        int64  // 9(2)
	WsResult     string // X(7)
	ReturnCode   int

	lines []string
	out   strings.Builder
}

// MainPara is MAIN-PARA.
func (p *Checkdig) MainPara() {
	for k := 0; k < 3; k++ {
		p.CheckOne()
	}
	p.out.WriteString("VALID ACCOUNTS: " + num(p.WsValidCount, 1) + "\n")
}

// CheckOne is CHECK-ONE.
func (p *Checkdig) CheckOne() {
	p.WsAcctNo = (p.WsAcctNo + 1) % 10
	p.WsAccount = p.acceptAlnum(10)
	p.ScanChars()
	if p.WsBad > 0 {
		p.out.WriteString(num(p.WsAcctNo, 1) + " [" + p.WsAccount + "] REJECTED: " + num(p.WsBad, 2) + " NON-DIGIT(S)\n")
	} else {
		p.WeighDigits()
		p.DeriveCheck()
		p.ReportResult()
	}
}

// ScanChars is SCAN-CHARS.
func (p *Checkdig) ScanChars() {
	p.WsBad = 0
	for p.WsI = 1; p.WsI <= 10; p.WsI++ {
		c := p.WsAccount[p.WsI-1]
		if c < '0' || c > '9' {
			p.WsBad = (p.WsBad + 1) % 100
		}
	}
}

// WeighDigits is WEIGH-DIGITS.
func (p *Checkdig) WeighDigits() {
	p.WsSum = 0
	for p.WsWeight = 10; !(p.WsWeight < 2); p.WsWeight-- {
		p.WsI = 11 - p.WsWeight
		p.WsDigit = int64(p.WsAccount[p.WsI-1] - '0')
		p.WsSum = (p.WsSum + p.WsDigit*p.WsWeight) % 1000
	}
}

// DeriveCheck is DERIVE-CHECK.
func (p *Checkdig) DeriveCheck() {
	p.WsQuot = (p.WsSum / 11) % 1000
	p.WsRem = (p.WsSum % 11) % 100
	switch p.WsRem {
	case 0:
		p.WsCheck = 0
	case 1:
		p.WsCheck = 10
	default:
		p.WsCheck = (11 - p.WsRem) % 100
	}
}

// ReportResult is REPORT-RESULT.
func (p *Checkdig) ReportResult() {
	p.WsGiven = int64(p.WsAccount[9] - '0')
	if p.WsCheck == 10 {
		p.WsCheckX = "X"
		p.WsResult = "NOCHECK"
	} else {
		p.WsCheckD = p.WsCheck % 10
		p.WsCheckX = num(p.WsCheckD, 1)
		if p.WsCheckD == p.WsGiven {
			p.WsResult = pad("VALID", 7)
			p.WsValidCount = (p.WsValidCount + 1) % 10
		} else {
			p.WsResult = pad("INVALID", 7)
		}
	}
	p.out.WriteString(num(p.WsAcctNo, 1) + " " + p.WsAccount + " " + p.WsResult + " CHECK=" + p.WsCheckX +
		" SUM=" + num(p.WsSum, 3) + " Q=" + num(p.WsQuot, 3) + " R=" + num(p.WsRem, 2) + "\n")
}

// acceptAlnum is ACCEPT into X(n): first n bytes, space padded; at end of input: spaces.
func (p *Checkdig) acceptAlnum(n int) string {
	if len(p.lines) == 0 {
		return strings.Repeat(" ", n)
	}
	line := p.lines[0]
	p.lines = p.lines[1:]
	return pad(line, n)
}

func main() {
	data, err := io.ReadAll(os.Stdin)
	if err != nil {
		os.Exit(2)
	}
	p := &Checkdig{WsAccount: strings.Repeat(" ", 10), WsCheckX: " ", WsResult: strings.Repeat(" ", 7),
		lines: splitLines(data)}
	p.MainPara()
	w := bufio.NewWriter(os.Stdout)
	w.WriteString(p.out.String())
	w.Flush()
	os.Exit(p.ReturnCode)
}
