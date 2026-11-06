"""JML frame (`assignable`) locations follow the candidate's Java type, not the COBOL PICTURE."""

from __future__ import annotations

from typing import Any

from verifier.langpacks.java.jml import FieldMap, _frame_locs


def _fm(jtype: str) -> FieldMap:
    rf: Any = object()  # _frame_locs only looks at the Java side
    return FieldMap("WS-X", rf, "wsX", jtype)


def test_string_field_is_a_single_location() -> None:
    # regression: PIC X mapped to String used to produce `this.wsX[*]` ("array required, but String found")
    assert _frame_locs(_fm("String")) == ["this.wsX"]


def test_scalar_numeric_is_a_single_location() -> None:
    assert _frame_locs(_fm("long")) == ["this.wsX"]


def test_array_fields_frame_reference_and_elements() -> None:
    for t in ("char[]", "long[]", "String[]", "byte[]"):
        assert _frame_locs(_fm(t)) == ["this.wsX", "this.wsX[*]"]
