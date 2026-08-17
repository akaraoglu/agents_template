from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--behavior",
        choices=(
            "normal",
            "timeout",
            "crash",
            "malformed",
            "oversize",
            "notification",
            "wrong-identity",
            "boolean-id",
            "empty-tool-result",
        ),
        default="normal",
    )
    parser.add_argument("--catalog", default="echo")
    args = parser.parse_args()
    child: subprocess.Popen[bytes] | None = None

    def terminate(_signal: int, _frame: object) -> None:
        if child is not None:
            try:
                child.wait(timeout=1)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, terminate)
    for line in sys.stdin:
        request = json.loads(line)
        if "id" not in request:
            continue
        if args.behavior == "timeout":
            time.sleep(60)
        if args.behavior == "crash":
            os._exit(3)
        if args.behavior == "malformed":
            sys.stdout.write("not-json\n")
            sys.stdout.flush()
            continue
        if args.behavior == "oversize":
            sys.stdout.write("{" + "x" * 10_000 + "}\n")
            sys.stdout.flush()
            continue
        method = request["method"]
        if method == "initialize":
            result = {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "attacker-controlled"
                    if args.behavior == "wrong-identity"
                    else "fake-local",
                    "version": "9.9"
                    if args.behavior == "wrong-identity"
                    else "1.0",
                },
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": name,
                        "inputSchema": {"type": "object"},
                        "annotations": {
                            "readOnlyHint": True,
                            "destructiveHint": False,
                        },
                    }
                    for name in args.catalog.split(",")
                ]
            }
        elif method == "tools/call":
            name = request["params"]["name"]
            if name == "spawn_child":
                child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
                value = {"child_pid": child.pid}
            else:
                value = {
                    "value": request["params"]["arguments"].get("value"),
                    "credential_present": "TEST_API_KEY" in os.environ,
                    "proxy_present": "HTTPS_PROXY" in os.environ,
                    "other_secret_present": any(
                        name in os.environ
                        for name in ("DATABASE_URL", "GIT_ASKPASS")
                    ),
                    "case_folded_path_present": "Path" in os.environ,
                    "query_stats": {
                        "source_bytes": 12,
                        "cache_hit": False,
                    },
                }
            result = (
                {}
                if args.behavior == "empty-tool-result"
                else {"structuredContent": value, "isError": False}
            )
        else:
            continue
        response = {
            "jsonrpc": "2.0",
            "id": True if args.behavior == "boolean-id" else request["id"],
            "result": result,
        }
        if args.behavior == "notification":
            sys.stdout.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/progress",
                        "params": {},
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )
        sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
