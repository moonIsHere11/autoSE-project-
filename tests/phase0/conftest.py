from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# the Phase 0 package lives in phase0/phase0; put it ahead of the repo root (where phase0/ is a plain dir)
sys.path.insert(0, str(REPO / "phase0"))
