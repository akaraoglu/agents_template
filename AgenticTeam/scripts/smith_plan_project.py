#!/usr/bin/env python3
"""Smith-specific entrypoint for runtime-owned initial planning."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from worker_contracts import SMITH_PLANNING_CONTRACT
from worker_runtime import main_for_planning_contract


if __name__ == "__main__":
    raise SystemExit(main_for_planning_contract(SMITH_PLANNING_CONTRACT))
