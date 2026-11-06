// Difftest driver: interprets each batch's script.txt with the Go cobolrt and writes go.out /
// go.enc next to it (same interpreter as tests/runtimes/pydriver.py and the Java Driver).
package main

import (
	"bytes"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"cobolrt"
)

type item struct {
	n *cobolrt.CobolDecimal
	x *cobolrt.PicX
}

func parseField(spec string) item {
	p := strings.Split(spec, ",")
	if p[0] == "N" {
		a := func(i int) int { v, _ := strconv.Atoi(p[i]); return v }
		pic := cobolrt.NewPic(a(1), a(2), p[3] == "1", a(4), p[5] == "1", p[6] == "1")
		d := cobolrt.NewDecimal(pic)
		d.MoveLiteral(p[7])
		return item{n: d}
	}
	ln, _ := strconv.Atoi(p[1])
	x := cobolrt.NewPicX(ln, p[2] == "1")
	if p[3] == "-" {
		x.MoveBytes(nil)
	} else {
		b, _ := hex.DecodeString(p[3])
		x.MoveBytes(b)
	}
	return item{x: x}
}

func show(out *bytes.Buffer, cid, tag string, it item) {
	var disp, raw []byte
	if it.n != nil {
		disp, raw = it.n.Display(), it.n.Encode()
	} else {
		disp, raw = it.x.Display(), it.x.Data
	}
	out.WriteString("#" + cid + " " + tag + " ")
	out.Write(disp)
	out.WriteString("|" + strings.ToUpper(hex.EncodeToString(raw)) + "\n")
}

func status(out *bytes.Buffer, cid string, err bool, sc int) {
	if err && (sc == 1 || sc == 3) {
		out.WriteString("#" + cid + " SE\n")
	}
	if !err && (sc == 1 || sc == 2) {
		out.WriteString("#" + cid + " NSE\n")
	}
}

func rpn(toks []string, items []item) cobolrt.Dec {
	var st []cobolrt.Dec
	pop := func() cobolrt.Dec { v := st[len(st)-1]; st = st[:len(st)-1]; return v }
	for _, t := range toks {
		switch {
		case strings.HasPrefix(t, "$"):
			i, _ := strconv.Atoi(t[1:])
			st = append(st, items[i].n.Dec())
		case strings.HasPrefix(t, "#"):
			st = append(st, cobolrt.Literal(t[1:]))
		case t == "~":
			st = append(st, pop().Neg())
		default:
			b := pop()
			a := pop()
			switch t {
			case "+":
				st = append(st, a.Add(b))
			case "-":
				st = append(st, a.Sub(b))
			case "*":
				st = append(st, a.Mul(b))
			default:
				st = append(st, a.Div(b))
			}
		}
	}
	return st[0]
}

func runCase(line string, acc *cobolrt.Accept, out, enc *bytes.Buffer) {
	head, extraS, _ := strings.Cut(line, " -- ")
	var extra []string
	if extraS != "" {
		extra = strings.Fields(extraS)
	}
	t := strings.Fields(head)
	cid, op := t[0], t[1]
	rnd, _ := strconv.Atoi(t[2])
	sc, _ := strconv.Atoi(t[3])
	size := map[int]int{0: cobolrt.SizeNone, 1: cobolrt.SizeOn, 2: cobolrt.SizeNotOnly, 3: cobolrt.SizeOn}[sc]
	var items []item
	for _, s := range t[4:] {
		items = append(items, parseField(s))
	}
	switch op {
	case "MOVE":
		items[1].n.Move(items[0].n)
		show(out, cid, "R1", items[1])
	case "MOVEL":
		items[0].n.MoveLiteral(extra[0])
		show(out, cid, "R1", items[0])
	case "DISP":
		show(out, cid, "R1", items[0])
	case "ENC":
		e := items[0].n.Encode()
		enc.Write(e)
		enc.WriteString(strings.Repeat("*", 40-len(e)))
		show(out, cid, "R1", items[0])
	case "ADD", "SUB", "MUL", "DIVI":
		a, b := cobolrt.Item(items[0].n), items[1].n
		var err bool
		switch op {
		case "ADD":
			err = b.Add(a, rnd, size)
		case "SUB":
			err = b.Subtract(a, rnd, size)
		case "MUL":
			err = b.Multiply(a, rnd, size)
		default:
			err = b.Divide(a, rnd, size)
		}
		status(out, cid, err, sc)
		show(out, cid, "R1", items[1])
	case "ADDG", "SUBG", "MULG", "DIVIG", "DIVBG":
		a, b := items[0].n.Dec(), items[1].n.Dec()
		var v cobolrt.Dec
		switch op {
		case "ADDG":
			v = a.Add(b)
		case "SUBG":
			v = b.Sub(a)
		case "MULG":
			v = a.Mul(b)
		case "DIVIG":
			v = b.Div(a)
		default:
			v = a.Div(b)
		}
		status(out, cid, items[2].n.Compute(v, rnd, size), sc)
		show(out, cid, "R1", items[2])
	case "DIVBR", "DIVIR":
		dd, dv := items[0].n.Dec(), items[1].n.Dec()
		if op == "DIVIR" {
			dd, dv = dv, dd
		}
		status(out, cid, cobolrt.DivideRemainder(dd, dv, items[2].n, items[3].n, rnd, size), sc)
		show(out, cid, "R1", items[2])
		show(out, cid, "R2", items[3])
	case "COMP":
		status(out, cid, items[0].n.Compute(rpn(extra, items), rnd, size), sc)
		show(out, cid, "R1", items[0])
	case "NX":
		items[1].x.MoveNum(items[0].n)
		show(out, cid, "R1", items[1])
	case "XN":
		items[1].n.MoveX(items[0].x)
		show(out, cid, "R1", items[1])
	case "XX":
		items[1].x.Move(items[0].x)
		show(out, cid, "R1", items[1])
	case "XL":
		b, _ := hex.DecodeString(extra[0])
		items[0].x.MoveBytes(b)
		show(out, cid, "R1", items[0])
	case "CMP", "XCMP":
		var c int
		if op == "CMP" {
			c = items[0].n.Compare(cobolrt.Item(items[1].n))
		} else {
			c = items[0].x.Compare(items[1].x)
		}
		r := map[int]string{-1: "LT", 0: "EQ", 1: "GT"}[c]
		out.WriteString("#" + cid + " " + r + "\n")
	case "ACC":
		acc.Num(items[0].n)
		show(out, cid, "R1", items[0])
	case "ACCX":
		acc.X(items[0].x)
		show(out, cid, "R1", items[0])
	default:
		panic(op)
	}
}

func main() {
	for _, dir := range os.Args[1:] {
		script, err := os.ReadFile(filepath.Join(dir, "script.txt"))
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(2)
		}
		stdin, _ := os.ReadFile(filepath.Join(dir, "stdin.txt"))
		acc := cobolrt.NewAccept(bytes.NewReader(stdin))
		var out, enc bytes.Buffer
		for _, line := range strings.Split(string(script), "\n") {
			if strings.TrimSpace(line) != "" {
				runCase(line, acc, &out, &enc)
			}
		}
		_ = os.WriteFile(filepath.Join(dir, "go.out"), out.Bytes(), 0o644)
		_ = os.WriteFile(filepath.Join(dir, "go.enc"), enc.Bytes(), 0o644)
	}
}
