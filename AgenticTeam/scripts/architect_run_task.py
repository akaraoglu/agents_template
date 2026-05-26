#!/usr/bin/env python3
"""Architect-specific entrypoint onto the generic worker runtime."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from worker_contracts import ARCHITECT_CONTRACT
from worker_runtime import main_for_contract


if __name__ == "__main__":
    raise SystemExit(main_for_contract(ARCHITECT_CONTRACT))
