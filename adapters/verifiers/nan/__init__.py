"""Adapter for Nandini's formal verifier (top-level `verifier/` package: T0 build/static, T1 differential vs
GnuCOBOL, T2 proofs, T3 contracts). The package itself is untouched; `adapter.py` calls verifier.api.verify
(needs the cobol-verifier venv + Docker image) and `convert.py` translates its report into the agreement Report."""
from pathlib import Path

from ..contract import ContractVerifier


class NanVerifier(ContractVerifier):
    def __init__(self, cmd=None, **kw):
        super().__init__(cmd or [str(Path(__file__).parent / "bin" / "phase2")], **kw)
