"""Stage G entity check (ETF-style): only names from the unit's own facts may appear."""

from __future__ import annotations

import pytest
from phase0.schema import FileCrud, SourceSpan, Unit
from phase0.stages.summaries import (
    Client,
    SummaryConfig,
    allowed_names,
    clean,
    summarise,
    unsupported_entities,
)
from phase0.workspace import ContractError

UNIT = Unit(unit_id="CALC-FEE", kind="paragraph", span=SourceSpan(file="P.cbl", start_line=1, end_line=2),
            reads=["WS-ORDER.WS-AMOUNT"], writes=["WS-FEE"], performs=["ROUND-FEE"], calls=[],
            falls_through_to=None, summary=None)
FILES = [FileCrud(program="P", file="FEE-FILE", organization="LINE SEQUENTIAL", assign="FEE.DAT",
                  units={"CALC-FEE": ["C"]})]


def test_allowed_names_cover_the_units_facts() -> None:
    names = allowed_names(UNIT, {}, FILES)
    assert {"CALC-FEE", "WS-AMOUNT", "WS-ORDER", "WS-FEE", "ROUND-FEE", "FEE-FILE"} <= names


def test_entities_outside_the_facts_are_flagged() -> None:
    allowed = allowed_names(UNIT, {}, FILES)
    universe = {"WS-TOTAL", "CUSTOMER"}
    ok = "CALC-FEE multiplies WS-AMOUNT by a rate, stores WS-FEE and performs ROUND-FEE before writing FEE-FILE."
    assert unsupported_entities(ok, allowed, universe) == []
    bad = "CALC-FEE adds WS-FEE to WS-TOTAL for the CUSTOMER and checks WS-LIMIT."
    assert unsupported_entities(bad, allowed, universe) == ["CUSTOMER", "WS-LIMIT", "WS-TOTAL"]
    assert unsupported_entities("The paragraph uses COBOL ROUNDED.", allowed, universe) == []


def test_disabled_stage_never_calls_out() -> None:
    report = summarise([UNIT], [], FILES, __import__("pathlib").Path("/nonexistent"), __import__("pathlib").Path("/x"),
                       SummaryConfig())
    assert report.generated == 0 and UNIT.summary is None
    assert clean("<think>long</think>  A   b ") == "A b"


def test_misspelled_case_of_a_fact_is_flagged() -> None:
    allowed = allowed_names(UNIT, {}, FILES)
    assert unsupported_entities("It updates WS-Fee and runs ROUND-FEE.", allowed, set()) == ["WS-Fee"]
    assert unsupported_entities("A well-known follow-up step.", allowed, set()) == []


def test_ollama_options_override_memory_but_not_sampling() -> None:
    cfg = SummaryConfig.from_config({"summaries": {"enabled": True, "options": {"num_gpu": -1, "num_ctx": 8192}}})
    opts = Client(cfg).body("x")["options"]
    assert opts["num_gpu"] == -1 and opts["num_ctx"] == 8192 and opts["temperature"] == 0 and opts["seed"] == 7
    with pytest.raises(ContractError):
        SummaryConfig.from_config({"summaries": {"options": {"temperature": 1}}})
