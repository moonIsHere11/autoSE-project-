"""Hand translation of GRADES. Numeric WORKING-STORAGE items are ints scaled by 10**scale; OCCURS
tables are lists (index 0 = COBOL subscript 1). Input record fields are kept as raw text because
they may hold non-numeric data (IS NUMERIC)."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

IN_REC_LEN = 26


def line_seq_records(data: bytes, rec_len: int) -> list[str]:
    """GnuCOBOL 3.2 LINE SEQUENTIAL READ: bytes up to '\\n' fill the record (short lines are space
    padded). When the record is full one more byte is read: '\\n' is consumed, anything else
    (including end of file) makes the reader step back one byte, so an overlong line is split into
    several records and a full-length last line without '\\n' yields one extra record holding its
    last byte."""
    recs: list[str] = []
    text = data.decode("latin-1")
    n = len(text)
    pos = 0
    while pos < n:
        start = pos
        while pos < n and text[pos] != "\n" and pos - start < rec_len:
            pos += 1
        rec = text[start:pos]
        if len(rec) < rec_len:
            if pos < n:
                pos += 1  # the newline
        elif pos < n and text[pos] == "\n":
            pos += 1
        elif pos >= n:
            pos = n - 1  # step back over the last byte at end of file
        recs.append(rec.ljust(rec_len))
    return recs


def is_numeric(s: str) -> bool:
    return bool(s) and all("0" <= c <= "9" for c in s)


def unsigned(v: int, int_digits: int, scale: int) -> str:
    s = str(v).rjust(int_digits + scale, "0")
    return s[: len(s) - scale] + "." + s[len(s) - scale:] if scale > 0 else s


def edit_zz9_9(v: int) -> str:
    """Numeric-edited PIC ZZ9.9 for a value held at scale 1."""
    return str(v // 10).rjust(3) + "." + str(v % 10)


@dataclass
class Grades:
    # FD GRADE-IN (raw text)
    in_id: str = " " * 4
    in_name: str = " " * 10
    in_score_1: str = " " * 3
    in_score_2: str = " " * 3
    in_score_3: str = " " * 3
    in_score_4: str = " " * 3
    # WORKING-STORAGE
    ws_eof: str = "N"  # X VALUE "N"
    ws_weight: list[int] = field(default_factory=lambda: [20, 20, 25, 35])  # 9(2) OCCURS 4 (REDEFINES)
    ws_score: list[int] = field(default_factory=lambda: [0, 0, 0, 0])  # 9(3) OCCURS 4
    ws_id: str = " " * 4  # X(4)
    ws_i: int = 0  # 9
    ws_bad_count: int = 0  # 9
    ws_total: int = 0  # 9(3)
    ws_weighted_sum: int = 0  # 9(5)
    ws_weighted: int = 0  # 9(3)V9, scale 1
    ws_average: int = 0  # 9(3)V99, scale 2
    ws_average_r: int = 0  # 9(3)V9, scale 1
    ws_best: int = 0  # 9(3)
    ws_worst: int = 0  # 9(3)
    ws_grade_idx: int = 0  # 9
    ws_letters: str = "ABCDF"  # X(5)
    ws_letter: str = " "  # X
    ws_grade_count: list[int] = field(default_factory=lambda: [0] * 5)  # 9(3) OCCURS 5
    ws_students: int = 0  # 9(3)
    ws_rejects: int = 0  # 9(3)
    ws_class_sum: int = 0  # 9(6)V9, scale 1
    ws_class_avg: int = 0  # 9(3)V99, scale 2
    ws_class_flag: str = "   "  # X(3)
    ws_top_score: int = 0  # 9(3)V9, scale 1
    ws_top_id: str = "    "  # X(4)
    ws_stars: str = "*" * 20  # X(20) VALUE ALL "*"
    ws_bar_len: int = 0  # 9(2)
    return_code: int = 0
    _records: list[str] = field(default_factory=list)
    _pos: int = 0
    _out_file: list[str] = field(default_factory=list)
    _out: list[str] = field(default_factory=list)

    def main_para(self) -> None:
        with open("GRADES.IN", "rb") as f:
            self._records = line_seq_records(f.read(), IN_REC_LEN)
        self._pos = 0
        for k in range(5):
            self.ws_grade_count[k] = 0  # INITIALIZE
        self.read_next()
        while self.ws_eof != "Y":
            self.process_record()
        self.class_summary()
        self.write_summary()
        with open("GRADES.OUT", "wb") as f:
            f.write("".join(self._out_file).encode("latin-1"))
        self._out.append("STUDENTS " + unsigned(self.ws_students, 3, 0) + " REJECTED "
                         + unsigned(self.ws_rejects, 3, 0) + "\n")
        self._out.append("CLASS AVERAGE " + unsigned(self.ws_class_avg, 3, 2) + " " + self.ws_class_flag + "\n")
        if self.ws_rejects > 0:
            self.return_code = 4

    def read_next(self) -> None:
        if self._pos >= len(self._records):
            self.ws_eof = "Y"
            return
        rec = self._records[self._pos]
        self._pos += 1
        self.in_id = rec[0:4]
        self.in_name = rec[4:14]
        self.in_score_1 = rec[14:17]
        self.in_score_2 = rec[17:20]
        self.in_score_3 = rec[20:23]
        self.in_score_4 = rec[23:26]

    def process_record(self) -> None:
        self.load_scores()
        self.score_student()
        if self.ws_bad_count == 0:
            self.write_detail()
        else:
            self.write_reject()
        self.read_next()

    def load_scores(self) -> None:
        self.ws_id = self.in_id
        self.ws_score = [999, 999, 999, 999]
        for k, raw in enumerate((self.in_score_1, self.in_score_2, self.in_score_3, self.in_score_4)):
            if is_numeric(raw):
                self.ws_score[k] = int(raw)

    def score_student(self) -> None:
        self.ws_total = 0
        self.ws_weighted_sum = 0
        self.ws_bad_count = 0
        self.ws_best = 0
        self.ws_worst = 999
        self.ws_i = 1
        while self.ws_i <= 4:
            s = self.ws_score[self.ws_i - 1]
            if 0 <= s <= 100:  # VALID-SCORE
                self.ws_total = (self.ws_total + s) % 1000
                self.ws_weighted_sum = (self.ws_weighted_sum + s * self.ws_weight[self.ws_i - 1]) % 100000
                if s > self.ws_best:
                    self.ws_best = s
                if s < self.ws_worst:
                    self.ws_worst = s
            else:
                self.ws_bad_count = (self.ws_bad_count + 1) % 10
            self.ws_i += 1
        if self.ws_id == "    ":
            self.ws_bad_count = 9
        if self.ws_bad_count == 0:
            n = self.ws_weighted_sum * 10  # WS-WEIGHTED-SUM / 100 at scale 1, ROUNDED
            q, r = divmod(n, 100)
            if 2 * r >= 100:
                q += 1
            self.ws_weighted = q % 10000
            self.ws_average = (self.ws_total * 100 // 4) % 100000  # truncated, scale 2
            qa, ra = divmod(self.ws_total * 10, 4)
            if 2 * ra >= 4:
                qa += 1
            self.ws_average_r = qa % 10000  # ROUNDED, scale 1
            if 900 <= self.ws_weighted <= 1000:
                self.ws_grade_idx = 1
            elif 750 <= self.ws_weighted <= 899:
                self.ws_grade_idx = 2
            elif 600 <= self.ws_weighted <= 749:
                self.ws_grade_idx = 3
            elif 400 <= self.ws_weighted <= 599:
                self.ws_grade_idx = 4
            else:
                self.ws_grade_idx = 5
            self.ws_letter = self.ws_letters[self.ws_grade_idx - 1]
            self.ws_grade_count[self.ws_grade_idx - 1] = (self.ws_grade_count[self.ws_grade_idx - 1] + 1) % 1000
            self.ws_students = (self.ws_students + 1) % 1000
            self.ws_class_sum = (self.ws_class_sum + self.ws_weighted) % 10000000
            if self.ws_weighted > self.ws_top_score:
                self.ws_top_score = self.ws_weighted
                self.ws_top_id = self.ws_id
        else:
            self.ws_rejects = (self.ws_rejects + 1) % 1000

    def write_detail(self) -> None:
        name = self.in_name.rjust(12)[-12:]  # MOVE to X(12) JUSTIFIED RIGHT
        rec = (self.ws_id + " " + name + " " + unsigned(self.ws_total, 3, 0) + " " + edit_zz9_9(self.ws_weighted)
               + " " + str(self.ws_average).rjust(5, "0") + " " + str(self.ws_average_r).rjust(4, "0") + " "
               + unsigned(self.ws_best, 3, 0) + "-" + unsigned(self.ws_worst, 3, 0) + " " + self.ws_letter)
        self.write_line(rec)

    def write_reject(self) -> None:
        self.write_line("REJECT " + self.ws_id + " BAD=" + unsigned(self.ws_bad_count, 1, 0))

    def class_summary(self) -> None:
        if self.ws_students == 0:
            self.ws_class_flag = "N/A"  # divide by zero: size error
        else:
            q, r = divmod(self.ws_class_sum * 10, self.ws_students)  # scale 1 -> 2, ROUNDED
            if 2 * r >= self.ws_students:
                q += 1
            if q > 99999:
                self.ws_class_flag = "N/A"
            else:
                self.ws_class_avg = q
                self.ws_class_flag = "OK "

    def write_summary(self) -> None:
        self.ws_grade_idx = 1
        while self.ws_grade_idx <= 5:
            k = self.ws_grade_idx - 1
            letter = self.ws_letters[k]
            self.ws_bar_len = self.ws_grade_count[k] % 100
            if self.ws_grade_count[k] > 20:
                self.ws_bar_len = 20
            bar = " " * 20
            if self.ws_bar_len > 0:
                bar = self.ws_stars[: self.ws_bar_len].ljust(20)
            self.write_line(letter + " " + unsigned(self.ws_grade_count[k], 3, 0) + " " + bar)
            self.ws_grade_idx += 1
        self.write_line("STUDENTS " + unsigned(self.ws_students, 3, 0) + " REJECTS " + unsigned(self.ws_rejects, 3, 0)
                        + " AVG " + str(self.ws_class_avg).rjust(5, "0") + " " + self.ws_class_flag
                        + " TOP " + self.ws_top_id + " " + edit_zz9_9(self.ws_top_score))

    def write_line(self, rec: str) -> None:
        """LINE SEQUENTIAL WRITE: trailing spaces removed, newline appended."""
        self._out_file.append(rec.rstrip(" ") + "\n")


def main() -> None:
    prog = Grades()
    prog.main_para()
    sys.stdout.buffer.write("".join(prog._out).encode("latin-1"))
    sys.stdout.buffer.flush()
    sys.exit(prog.return_code)


if __name__ == "__main__":
    main()
