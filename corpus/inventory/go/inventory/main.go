// Hand translation of INVENTORY. Numerics are int64 scaled by 10^scale. Record fields are decoded
// from / encoded to the exact GnuCOBOL byte layouts: COMP-3 (packed, sign nibble C/D/F), COMP
// (big-endian two's complement), zoned with ASCII overpunch (negative last digit = 0x70 + d) and
// SIGN LEADING / TRAILING SEPARATE.
package main

import (
	"bufio"
	"encoding/binary"
	"os"
	"strconv"
	"strings"
)

const (
	stkLen = 21
	valLen = 32
)

// Inventory holds the FILE SECTION and WORKING-STORAGE of INVENTORY.
type Inventory struct {
	// FD STOCK-FILE
	StkItem    string // X(6)
	StkQty     int64  // S9(5) COMP-3
	StkCost    int64  // 9(4)V99 COMP-3, scale 2
	StkReorder int64  // S9(4) COMP
	StkAdj     int64  // S9(3)
	StkDisc    int64  // SV99 SIGN LEADING SEPARATE, scale 2
	stkRec     []byte

	// FD VALUE-FILE
	ValItem      string // X(6)
	ValNewQty    int64  // S9(5) COMP-3
	ValUnit      int64  // S9(4)V99 COMP-3
	ValAmount    int64  // S9(8)V99 COMP-3
	ValCount     int64  // 9(4) COMP
	ValFlag      string // X
	ValNet       int64  // S9(7)V99 SIGN TRAILING SEPARATE (digits)
	valUnitSignF bool
	valNetNeg    bool

	// WORKING-STORAGE
	WsEof    string
	WsValid  string
	WsItem   string
	WsQty    int64 // S9(5) COMP-3
	WsCost   int64 // 9(4)V99 COMP-3
	WsReorder int64 // S9(4) COMP
	WsAdj    int64 // S9(3)
	WsDisc   int64 // SV99 SIGN LEADING SEPARATE
	WsUnit   int64 // S9(4)V99 COMP-3
	// a packed MOVE from the unsigned WS-COST keeps sign nibble F in the signed WS-UNIT;
	// arithmetic results always get C/D (visible in VALUE.DAT)
	wsUnitSignF    bool
	WsAmount       int64  // S9(8)V99 COMP-3
	WsStatus       string // X
	WsRecCount     int64  // 9(4) COMP VALUE 0
	WsRejectCount  int64
	WsNegCount     int64
	WsReorderCount int64
	WsTotalValue   int64 // S9(11)V99 COMP-3 VALUE 0
	ReturnCode     int

	stock    []byte
	stockPos int
	valFile  []byte
	out      strings.Builder
}

// MainPara is MAIN-PARA.
func (p *Inventory) MainPara() {
	data, err := os.ReadFile("STOCK.DAT")
	if err != nil {
		os.Stderr.WriteString("cannot open STOCK.DAT: " + err.Error() + "\n")
		os.Exit(35)
	}
	p.stock = data
	p.ReadStock()
	for p.WsEof != "Y" {
		p.ValidateRecord()
		if p.WsValid == "Y" {
			p.ValueItem()
		} else {
			p.RejectItem()
		}
		p.WriteValue()
		p.ReadStock()
	}
	if err := os.WriteFile("VALUE.DAT", p.valFile, 0o644); err != nil {
		os.Stderr.WriteString("cannot write VALUE.DAT: " + err.Error() + "\n")
		os.Exit(30)
	}
	p.SetReturn()
	p.ShowTotals()
}

// ReadStock is READ-STOCK.
func (p *Inventory) ReadStock() {
	if p.stockPos+stkLen > len(p.stock) {
		p.WsEof = "Y"
		return
	}
	p.stkRec = p.stock[p.stockPos : p.stockPos+stkLen]
	p.stockPos += stkLen
	p.StkItem = string(p.stkRec[0:6])
}

// ValidateRecord is VALIDATE-RECORD.
func (p *Inventory) ValidateRecord() {
	rec := p.stkRec
	p.WsValid = "N"
	p.WsItem = p.StkItem
	if packedIsNumeric(rec, 6, 3, true) && packedIsNumeric(rec, 9, 4, false) && zonedIsNumeric(rec, 15, 3) &&
		leadingSeparateIsNumeric(rec, 18, 3) {
		p.WsValid = "Y"
		p.StkQty = unpack(rec, 6, 3)
		p.StkCost = unpack(rec, 9, 4)
		p.StkReorder = int64(int16(binary.BigEndian.Uint16(rec[13:15])))
		p.StkAdj = unzone(rec, 15, 3)
		disc, _ := strconv.ParseInt(string(rec[19:21]), 10, 64)
		if rec[18] == '-' {
			disc = -disc
		}
		p.StkDisc = disc
		p.WsQty = p.StkQty
		p.WsCost = p.StkCost
		p.WsReorder = p.StkReorder
		p.WsAdj = p.StkAdj
		p.WsDisc = p.StkDisc
	}
}

// ValueItem is VALUE-ITEM.
func (p *Inventory) ValueItem() {
	p.WsStatus = " "
	q := p.WsQty + p.WsAdj
	if q > 99999 || q < -99999 {
		p.WsStatus = "O" // ON SIZE ERROR: WS-QTY unchanged
	} else {
		p.WsQty = q
	}
	product := p.WsCost * (100 + p.WsDisc) // scale 4, never negative
	unit := (product + 50) / 100           // ROUNDED to scale 2
	if unit > 999999 {
		p.WsUnit = p.WsCost
		p.wsUnitSignF = true
		p.WsStatus = "P"
	} else {
		p.WsUnit = unit
		p.wsUnitSignF = false
	}
	amount := p.WsQty * p.WsUnit // scale 2
	if amount > 9999999999 || amount < -9999999999 {
		p.WsAmount = 0
		p.WsStatus = "V"
	} else {
		p.WsAmount = amount
	}
	switch {
	case p.WsStatus != " ":
		// already flagged (WHEN NOT STATUS-OK: CONTINUE)
	case p.WsQty < 0:
		p.WsStatus = "N"
		p.WsNegCount = (p.WsNegCount + 1) % 10000
	case p.WsQty < p.WsReorder:
		p.WsStatus = "R"
		p.WsReorderCount = (p.WsReorderCount + 1) % 10000
	}
	p.WsTotalValue = p.WsTotalValue + p.WsAmount
}

// RejectItem is REJECT-ITEM.
func (p *Inventory) RejectItem() {
	p.WsStatus = "X"
	p.WsQty = 0
	p.WsUnit = 0
	p.wsUnitSignF = false
	p.WsAmount = 0
	p.WsRejectCount = (p.WsRejectCount + 1) % 10000
}

// WriteValue is WRITE-VALUE.
func (p *Inventory) WriteValue() {
	p.WsRecCount = (p.WsRecCount + 1) % 10000
	p.ValItem = p.WsItem
	p.ValNewQty = p.WsQty
	p.ValUnit = p.WsUnit
	p.valUnitSignF = p.wsUnitSignF
	p.ValAmount = p.WsAmount
	p.ValCount = p.WsRecCount
	p.ValFlag = p.WsStatus
	p.ValNet = abs64(p.WsAmount) % 1000000000 // MOVE: high-order truncation
	p.valNetNeg = p.WsAmount < 0             // MOVE keeps the source sign
	rec := make([]byte, 0, valLen)
	rec = append(rec, p.ValItem...)
	rec = append(rec, pack(p.ValNewQty, 3, true)...)
	rec = append(rec, pack(p.ValUnit, 4, !p.valUnitSignF)...)
	rec = append(rec, pack(p.ValAmount, 6, true)...)
	rec = binary.BigEndian.AppendUint16(rec, uint16(p.ValCount))
	rec = append(rec, p.ValFlag[0])
	sign := "+"
	if p.valNetNeg {
		sign = "-"
	}
	rec = append(rec, digits(p.ValNet, 9)+sign...)
	p.valFile = append(p.valFile, rec...)
	shown := "+"
	if p.valNetNeg && p.ValNet != 0 {
		shown = "-"
	}
	p.line(digits(p.WsRecCount, 4) + " " + p.WsItem + " QTY " + signedStr(p.WsQty, 5, 0) + " UNIT " +
		signedStr(p.WsUnit, 4, 2) + " AMOUNT " + signedStr(p.WsAmount, 8, 2) + " [" + p.WsStatus + "] NET " +
		withPoint(digits(p.ValNet, 9), 2) + shown)
}

// SetReturn is SET-RETURN.
func (p *Inventory) SetReturn() {
	switch {
	case p.WsRejectCount > 0:
		p.ReturnCode = 12
	case p.WsNegCount > 0:
		p.ReturnCode = 8
	case p.WsReorderCount > 0:
		p.ReturnCode = 4
	default:
		p.ReturnCode = 0
	}
}

// ShowTotals is SHOW-TOTALS.
func (p *Inventory) ShowTotals() {
	p.line("RECORDS " + digits(p.WsRecCount, 4) + " REJECTED " + digits(p.WsRejectCount, 4) + " NEGATIVE " +
		digits(p.WsNegCount, 4) + " REORDER " + digits(p.WsReorderCount, 4))
	p.line("TOTAL VALUE " + signedStr(p.WsTotalValue, 11, 2))
}

func (p *Inventory) line(s string) {
	p.out.WriteString(s)
	p.out.WriteByte('\n')
}

// ------------------------------------------------------------------------------ record codecs

func packedIsNumeric(b []byte, off, n int, isSigned bool) bool {
	for i := 0; i < n; i++ {
		hi, lo := b[off+i]>>4, b[off+i]&0xF
		if hi > 9 || (i < n-1 && lo > 9) {
			return false
		}
	}
	sign := b[off+n-1] & 0xF
	if isSigned {
		return sign == 0xC || sign == 0xD
	}
	return sign == 0xF
}

func unpack(b []byte, off, n int) int64 {
	var v int64
	for i := 0; i < n; i++ {
		v = v*10 + int64(b[off+i]>>4)
		if i < n-1 {
			v = v*10 + int64(b[off+i]&0xF)
		}
	}
	if b[off+n-1]&0xF == 0xD {
		return -v
	}
	return v
}

func pack(v int64, n int, isSigned bool) []byte {
	a := abs64(v)
	nib := make([]byte, 2*n)
	switch {
	case !isSigned:
		nib[2*n-1] = 0xF
	case v < 0:
		nib[2*n-1] = 0xD
	default:
		nib[2*n-1] = 0xC
	}
	for i := 2*n - 2; i >= 0; i-- {
		nib[i] = byte(a % 10)
		a /= 10
	}
	r := make([]byte, n)
	for i := 0; i < n; i++ {
		r[i] = nib[2*i]<<4 | nib[2*i+1]
	}
	return r
}

func zonedIsNumeric(b []byte, off, n int) bool {
	for i := 0; i < n-1; i++ {
		if b[off+i] < '0' || b[off+i] > '9' {
			return false
		}
	}
	last := b[off+n-1]
	return (last >= '0' && last <= '9') || (last >= 0x70 && last <= 0x79)
}

func unzone(b []byte, off, n int) int64 {
	var v int64
	for i := 0; i < n-1; i++ {
		v = v*10 + int64(b[off+i]-'0')
	}
	last := b[off+n-1]
	if last >= 0x70 {
		return -(v*10 + int64(last-0x70))
	}
	return v*10 + int64(last-'0')
}

func leadingSeparateIsNumeric(b []byte, off, n int) bool {
	if b[off] != '+' && b[off] != '-' {
		return false
	}
	for i := 1; i < n; i++ {
		if b[off+i] < '0' || b[off+i] > '9' {
			return false
		}
	}
	return true
}

// ------------------------------------------------------------------------------ display helpers

func abs64(v int64) int64 {
	if v < 0 {
		return -v
	}
	return v
}

func digits(v int64, n int) string {
	s := strconv.FormatInt(abs64(v), 10)
	if len(s) < n {
		s = strings.Repeat("0", n-len(s)) + s
	}
	return s
}

func withPoint(ds string, scale int) string {
	if scale == 0 {
		return ds
	}
	return ds[:len(ds)-scale] + "." + ds[len(ds)-scale:]
}

func signedStr(v int64, intDigits, scale int) string {
	sign := "+"
	if v < 0 {
		sign = "-"
	}
	return sign + withPoint(digits(v, intDigits+scale), scale)
}

func main() {
	p := &Inventory{StkItem: "      ", ValItem: "      ", ValFlag: " ", WsEof: "N", WsValid: " ", WsItem: "      ",
		WsStatus: " "}
	p.MainPara()
	w := bufio.NewWriter(os.Stdout)
	w.WriteString(p.out.String())
	w.Flush()
	os.Exit(p.ReturnCode)
}
