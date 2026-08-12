#!/bin/sh
""":"
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}" \
    exec /home/alik/workspace/agent_template/env-python/bin/python -m codexteam_tools.v2.cli "$@"
":"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from codexteam_tools.v2.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
