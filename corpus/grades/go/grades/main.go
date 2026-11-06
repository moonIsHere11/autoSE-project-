// Hand translation of GRADES. Numeric WORKING-STORAGE items are int64 scaled by 10^scale; OCCURS
// tables are arrays (index 0 = COBOL subscript 1). Input record fields are kept as raw text
// because they may hold non-numeric data (IS NUMERIC).
package main

import (
	"bufio"
	"os"
	"strconv"
	"strings"
)

const inRecLen = 26

// Grades holds the FILE SECTION and WORKING-STORAGE of GRADES.
type Grades struct {
	InId     string // X(4)
	InName   string // X(10)
	InScore1 string // 9(3), raw text
	InScore2 string
	InScore3 string
	InScore4 string

	WsEof          string   // X VALUE "N"
	WsWeight       [4]int64 // 9(2) OCCURS 4 (REDEFINES of FILLER values)
	WsScore        [4]int64 // 9(3) OCCURS 4
	WsId           string   // X(4)
	WsI            int64    // 9
	WsBadCount     int64    // 9
	WsTotal        int64    // 9(3)
	WsWeightedSum  int64    // 9(5)
	WsWeighted     int64    // 9(3)V9, scale 1
	WsAverage      int64    // 9(3)V99, scale 2
	WsAverageR     int64    // 9(3)V9, scale 1
	WsBest         int64    // 9(3)
	WsWorst        int64    // 9(3)
	WsGradeIdx     int64    // 9
	WsLetters      string   // X(5)
	WsLetter       string   // X
	WsGradeCount   [5]int64 // 9(3) OCCURS 5
	WsStudents     int64    // 9(3)
	WsRejects      int64    // 9(3)
	WsClassSum     int64    // 9(6)V9, scale 1
	WsClassAvg     int64    // 9(3)V99, scale 2
	WsClassFlag    string   // X(3)
	WsTopScore     int64    // 9(3)V9, scale 1
	WsTopId        string   // X(4)
	WsStars        string   // X(20) VALUE ALL "*"
	WsBarLen       int64    // 9(2)
	ReturnCode     int
	records        []string
	pos            int
	outFile        strings.Builder
	out            strings.Builder
}

func newGrades() *Grades {
	return &Grades{InId: "    ", InName: strings.Repeat(" ", 10), InScore1: "   ", InScore2: "   ", InScore3: "   ",
		InScore4: "   ", WsEof: "N", WsWeight: [4]int64{20, 20, 25, 35}, WsId: "    ", WsLetters: "ABCDF",
		WsLetter: " ", WsClassFlag: "   ", WsTopId: "    ", WsStars: strings.Repeat("*", 20)}
}

// MainPara is MAIN-PARA.
func (p *Grades) MainPara() {
	data, err := os.ReadFile("GRADES.IN")
	if err != nil {
		os.Stderr.WriteString("cannot open GRADES.IN: " + err.Error() + "\n")
		os.Exit(35)
	}
	p.records = lineSeqRecords(data, inRecLen)
	for k := range p.WsGradeCount {
		p.WsGradeCount[k] = 0 // INITIALIZE
	}
	p.ReadNext()
	for p.WsEof != "Y" {
		p.ProcessRecord()
	}
	p.ClassSummary()
	p.WriteSummary()
	if err := os.WriteFile("GRADES.OUT", []byte(p.outFile.String()), 0o644); err != nil {
		os.Stderr.WriteString("cannot write GRADES.OUT: " + err.Error() + "\n")
		os.Exit(30)
	}
	p.out.WriteString("STUDENTS " + digits(p.WsStudents, 3) + " REJECTED " + digits(p.WsRejects, 3) + "\n")
	p.out.WriteString("CLASS AVERAGE " + point(digits(p.WsClassAvg, 5), 2) + " " + p.WsClassFlag + "\n")
	if p.WsRejects > 0 {
		p.ReturnCode = 4
	}
}

// ReadNext is READ-NEXT.
func (p *Grades) ReadNext() {
	if p.pos >= len(p.records) {
		p.WsEof = "Y"
		return
	}
	rec := p.records[p.pos]
	p.pos++
	p.InId = rec[0:4]
	p.InName = rec[4:14]
	p.InScore1 = rec[14:17]
	p.InScore2 = rec[17:20]
	p.InScore3 = rec[20:23]
	p.InScore4 = rec[23:26]
}

// ProcessRecord is PROCESS-RECORD.
func (p *Grades) ProcessRecord() {
	p.LoadScores()
	p.ScoreStudent()
	if p.WsBadCount == 0 {
		p.WriteDetail()
	} else {
		p.WriteReject()
	}
	p.ReadNext()
}

// LoadScores is LOAD-SCORES.
func (p *Grades) LoadScores() {
	p.WsId = p.InId
	for k, raw := range [4]string{p.InScore1, p.InScore2, p.InScore3, p.InScore4} {
		p.WsScore[k] = 999
		if isNumeric(raw) {
			v, _ := strconv.ParseInt(raw, 10, 64)
			p.WsScore[k] = v
		}
	}
}

// ScoreStudent is SCORE-STUDENT.
func (p *Grades) ScoreStudent() {
	p.WsTotal = 0
	p.WsWeightedSum = 0
	p.WsBadCount = 0
	p.WsBest = 0
	p.WsWorst = 999
	for p.WsI = 1; p.WsI <= 4; p.WsI++ {
		s := p.WsScore[p.WsI-1]
		if s >= 0 && s <= 100 { // VALID-SCORE
			p.WsTotal = (p.WsTotal + s) % 1000
			p.WsWeightedSum = (p.WsWeightedSum + s*p.WsWeight[p.WsI-1]) % 100000
			if s > p.WsBest {
				p.WsBest = s
			}
			if s < p.WsWorst {
				p.WsWorst = s
			}
		} else {
			p.WsBadCount = (p.WsBadCount + 1) % 10
		}
	}
	if p.WsId == "    " {
		p.WsBadCount = 9
	}
	if p.WsBadCount == 0 {
		n := p.WsWeightedSum * 10 // WS-WEIGHTED-SUM / 100 at scale 1, ROUNDED
		q := n / 100
		if 2*(n%100) >= 100 {
			q++
		}
		p.WsWeighted = q % 10000
		p.WsAverage = (p.WsTotal * 100 / 4) % 100000 // truncated, scale 2
		a := p.WsTotal * 10
		qa := a / 4
		if 2*(a%4) >= 4 {
			qa++
		}
		p.WsAverageR = qa % 10000 // ROUNDED, scale 1
		switch {
		case p.WsWeighted >= 900 && p.WsWeighted <= 1000:
			p.WsGradeIdx = 1
		case p.WsWeighted >= 750 && p.WsWeighted <= 899:
			p.WsGradeIdx = 2
		case p.WsWeighted >= 600 && p.WsWeighted <= 749:
			p.WsGradeIdx = 3
		case p.WsWeighted >= 400 && p.WsWeighted <= 599:
			p.WsGradeIdx = 4
		default:
			p.WsGradeIdx = 5
		}
		p.WsLetter = p.WsLetters[p.WsGradeIdx-1 : p.WsGradeIdx]
		p.WsGradeCount[p.WsGradeIdx-1] = (p.WsGradeCount[p.WsGradeIdx-1] + 1) % 1000
		p.WsStudents = (p.WsStudents + 1) % 1000
		p.WsClassSum = (p.WsClassSum + p.WsWeighted) % 10000000
		if p.WsWeighted > p.WsTopScore {
			p.WsTopScore = p.WsWeighted
			p.WsTopId = p.WsId
		}
	} else {
		p.WsRejects = (p.WsRejects + 1) % 1000
	}
}

// WriteDetail is WRITE-DETAIL.
func (p *Grades) WriteDetail() {
	rec := p.WsId + " " + justifyRight(p.InName, 12) + " " + digits(p.WsTotal, 3) + " " + editZZ9V9(p.WsWeighted) +
		" " + digits(p.WsAverage, 5) + " " + digits(p.WsAverageR, 4) + " " + digits(p.WsBest, 3) + "-" +
		digits(p.WsWorst, 3) + " " + p.WsLetter
	p.writeLine(rec)
}

// WriteReject is WRITE-REJECT.
func (p *Grades) WriteReject() {
	p.writeLine("REJECT " + p.WsId + " BAD=" + digits(p.WsBadCount, 1))
}

// ClassSummary is CLASS-SUMMARY.
func (p *Grades) ClassSummary() {
	if p.WsStudents == 0 {
		p.WsClassFlag = "N/A" // divide by zero: size error
		return
	}
	n := p.WsClassSum * 10 // scale 1 -> 2, ROUNDED
	q := n / p.WsStudents
	if 2*(n%p.WsStudents) >= p.WsStudents {
		q++
	}
	if q > 99999 {
		p.WsClassFlag = "N/A"
	} else {
		p.WsClassAvg = q
		p.WsClassFlag = "OK "
	}
}

// WriteSummary is WRITE-SUMMARY.
func (p *Grades) WriteSummary() {
	for p.WsGradeIdx = 1; p.WsGradeIdx <= 5; p.WsGradeIdx++ {
		k := p.WsGradeIdx - 1
		letter := p.WsLetters[k : k+1]
		p.WsBarLen = p.WsGradeCount[k] % 100
		if p.WsGradeCount[k] > 20 {
			p.WsBarLen = 20
		}
		bar := strings.Repeat(" ", 20)
		if p.WsBarLen > 0 {
			bar = p.WsStars[:p.WsBarLen] + strings.Repeat(" ", int(20-p.WsBarLen))
		}
		p.writeLine(letter + " " + digits(p.WsGradeCount[k], 3) + " " + bar)
	}
	p.writeLine("STUDENTS " + digits(p.WsStudents, 3) + " REJECTS " + digits(p.WsRejects, 3) + " AVG " +
		digits(p.WsClassAvg, 5) + " " + p.WsClassFlag + " TOP " + p.WsTopId + " " + editZZ9V9(p.WsTopScore))
}

// writeLine is a LINE SEQUENTIAL WRITE: trailing spaces removed, newline appended.
func (p *Grades) writeLine(rec string) {
	p.outFile.WriteString(strings.TrimRight(rec, " "))
	p.outFile.WriteByte('\n')
}

// lineSeqRecords reproduces GnuCOBOL 3.2 LINE SEQUENTIAL READ: bytes up to '\n' fill the record
// (short lines are space padded); when the record is full one more byte is read: '\n' is
// consumed, anything else (including end of file) makes the reader step back one byte.
func lineSeqRecords(data []byte, recLen int) []string {
	var recs []string
	n := len(data)
	pos := 0
	for pos < n {
		start := pos
		for pos < n && data[pos] != '\n' && pos-start < recLen {
			pos++
		}
		rec := string(data[start:pos])
		if len(rec) < recLen {
			if pos < n {
				pos++
			}
		} else if pos < n && data[pos] == '\n' {
			pos++
		} else if pos >= n {
			pos = n - 1
		}
		recs = append(recs, rec+strings.Repeat(" ", recLen-len(rec)))
	}
	return recs
}

func isNumeric(s string) bool {
	if s == "" {
		return false
	}
	for i := 0; i < len(s); i++ {
		if s[i] < '0' || s[i] > '9' {
			return false
		}
	}
	return true
}

func digits(v int64, n int) string {
	s := strconv.FormatInt(v, 10)
	if len(s) < n {
		s = strings.Repeat("0", n-len(s)) + s
	}
	return s
}

func point(ds string, scale int) string {
	return ds[:len(ds)-scale] + "." + ds[len(ds)-scale:]
}

func justifyRight(s string, n int) string {
	if len(s) >= n {
		return s[len(s)-n:]
	}
	return strings.Repeat(" ", n-len(s)) + s
}

// editZZ9V9 is the numeric-edited PIC ZZ9.9 of a value held at scale 1.
func editZZ9V9(v int64) string {
	whole := strconv.FormatInt(v/10, 10)
	return strings.Repeat(" ", 3-len(whole)) + whole + "." + strconv.FormatInt(v%10, 10)
}

func main() {
	p := newGrades()
	p.MainPara()
	w := bufio.NewWriter(os.Stdout)
	w.WriteString(p.out.String())
	w.Flush()
	os.Exit(p.ReturnCode)
}
