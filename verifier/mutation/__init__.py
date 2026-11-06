"""COBOL-semantic mutation operators (spec section 9) applied to target-language translations.

Used by `make selftest` (planted-bug catch rate) and by T2b's mutation-sanity vacuity check.
"""

from verifier.mutation.engine import CATEGORIES, Mutant, apply_mutant, find_mutants, sample_mutants

__all__ = ["CATEGORIES", "Mutant", "apply_mutant", "find_mutants", "sample_mutants"]
