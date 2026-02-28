#!/usr/bin/env python3
"""
smoke_test.py
Quick sanity check for the purple-agent A2A server.

Usage:
  python scripts/smoke_test.py                        # test localhost:9010
  python scripts/smoke_test.py --url http://host:9010 # test remote server
  python scripts/smoke_test.py --url https://purple.agentbench.usebrainos.com

All tests are read-only (GET + safe POST) — won't corrupt any state.
"""
from __future__ import annotations
import argparse
import json
import sys
import time
import urllib.request
import urllib.error


def _get(url: str, timeout: int = 10) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}


def _post(url: str, body: dict, timeout: int = 30) -> tuple[int, dict]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}


def run_tests(base_url: str) -> bool:
    base = base_url.rstrip("/")
    results = []
    all_pass = True

    def check(name: str, passed: bool, detail: str = ""):
        nonlocal all_pass
        icon = "✅" if passed else "❌"
        print(f"  {icon}  {name}", end="")
        if detail:
            print(f"  →  {detail}", end="")
        print()
        results.append(passed)
        if not passed:
            all_pass = False

    print(f"\n🔍  Smoke testing: {base}\n")

    # 1. Health check
    status, body = _get(f"{base}/health")
    check("GET /health", status == 200, f"status={status} version={body.get('version', '?')}")

    # 2. Agent card
    status, body = _get(f"{base}/.well-known/agent-card.json")
    has_card = status == 200 and "name" in body
    check("GET /.well-known/agent-card.json", has_card, body.get("name", "missing"))

    # 3. RL status
    status, body = _get(f"{base}/rl/status")
    check("GET /rl/status", status == 200, f"cases={body.get('total_cases', '?')} status={body.get('status', '?')}")

    # 4. Training status
    status, body = _get(f"{base}/training/status")
    check(
        "GET /training/status",
        status == 200,
        f"seeded={body.get('seeded_entries', '?')} live={body.get('live_entries', '?')}",
    )

    # 5. Simple A2A task (no tools needed)
    t0 = time.time()
    status, body = _post(f"{base}/", {
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "params": {
            "id": "smoke-test-001",
            "message": {"parts": [{"text": "What is 15% of $2,400? Show your calculation."}]},
            "metadata": {"session_id": "smoke-test-session"},
        },
    })
    elapsed = round(time.time() - t0, 1)
    result = body.get("result", {})
    answer_text = ""
    try:
        answer_text = result["artifacts"][0]["parts"][0]["text"][:80]
    except Exception:
        pass
    check(
        "POST / (simple math task)",
        status == 200 and bool(answer_text),
        f"{elapsed}s  →  {answer_text!r:.60}",
    )

    # 6. A2A task: expense approval (FSM process type detection)
    status, body = _post(f"{base}/", {
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "params": {
            "id": "smoke-test-002",
            "message": {"parts": [{"text": "Process expense reimbursement of $350 for John Smith, category: travel, receipt attached."}]},
            "metadata": {"session_id": "smoke-test-session-2"},
        },
    })
    result = body.get("result", {})
    answer_text = ""
    try:
        answer_text = result["artifacts"][0]["parts"][0]["text"][:80]
    except Exception:
        pass
    check(
        "POST / (expense approval process)",
        status == 200 and bool(answer_text),
        f"  →  {answer_text!r:.60}",
    )

    # 7. Invalid method (should return 400)
    status, body = _post(f"{base}/", {"jsonrpc": "2.0", "method": "invalid/method", "params": {}})
    check("POST / invalid method → 400", status == 400)

    print(f"\n{'✅  All tests passed' if all_pass else '❌  Some tests failed'}  ({sum(results)}/{len(results)})\n")
    return all_pass


def main():
    parser = argparse.ArgumentParser(description="Purple Agent smoke test")
    parser.add_argument("--url", default="http://localhost:9010", help="Base URL of the agent server")
    args = parser.parse_args()
    success = run_tests(args.url)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
