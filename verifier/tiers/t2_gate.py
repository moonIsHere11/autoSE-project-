"""T2b validation gate (spec section 6, T2b.4) — see check_gate()."""

from __future__ import annotations

from typing import TYPE_CHECKING

from verifier.report.schema import Status, TierResult

if TYPE_CHECKING:
    from verifier.cobol import ir
    from verifier.pipeline import Pipeline, ProgramCtx


def check_gate(pl: Pipeline, pc: ProgramCtx, irp: ir.IrProgram) -> TierResult | None:
    """None when the reference is trusted for this program; otherwise the result every unit gets."""
    del pl, pc, irp
    return TierResult(status=Status.NOT_APPLICABLE, stub=True,
                      reason="reference validation gate not wired yet (needs interpreter snapshots)")
