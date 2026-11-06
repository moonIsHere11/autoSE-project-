"""cobolrt — COBOL runtime semantics for Python translations (GnuCOBOL 3.2, `-std=default`).

Layers (see docs/RUNTIME_API.md):

* `cobolrt.num`    pure functions on scaled ints: store/round/truncate, MOVE, exact intermediates
* `cobolrt.codec`  record encodings and DISPLAY formatting
* `cobolrt.alnum`  PIC X moves/compare/reference modification, numeric<->alphanumeric, ACCEPT
* `cobolrt.fields` object API: `CobolDecimal`, `PicX`, `divide_remainder`, `display_line`
"""

from cobolrt.fields import CobolDecimal, Operand, PicX, display_line, divide_remainder, operand
from cobolrt.num import Dec, Stored
from cobolrt.pic import ROUNDED, AlnumPic, NumPic, Round, SizeError, Usage, parse_pic

__version__ = "1.0.0"

__all__ = [
    "ROUNDED", "AlnumPic", "CobolDecimal", "Dec", "NumPic", "Operand", "PicX", "Round", "SizeError", "Stored",
    "Usage", "display_line", "divide_remainder", "operand", "parse_pic",
]
