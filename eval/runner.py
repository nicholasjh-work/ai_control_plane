# Eval harness: runs 30 prompts against the live server and scores pass/fail — Nicholas Hidalgo
import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

BASE_URL = os.getenv("EVAL_BASE_URL", "http://localhost:8000")
PROMPTS_PATH = Path(__file__).parent / "prompts.json"
RESULTS_DIR = Path(__file__).parent / "results"
PASS_THRESHOLD = 0.90


def _derive_policy_decision(body: Dict[str, Any]) -> str:
    status = body.get("status", "")
    pii = body.get("pii_detected", False)
    if status == "blocked":
        return "block"
    if status == "needs_approval":
        return "require_approval"
    if status == "succeeded" and pii:
        return "allow_with_redaction"
    return "allow"


def _run_intake(case: Dict[str, Any], client: httpx.Client) -> Dict[str, Any]:
    t0 = time.time()
    try:
        resp = client.post(f"{BASE_URL}/run", json=case["intake"], timeout=10.0)
        latency_ms = int((time.time() - t0) * 1000)
        body = resp.json()
    except Exception as exc:
        return {"passed": False, "error": str(exc), "latency_ms": 0}

    actual_routing = body.get("routing_team", "")
    actual_decision = _derive_policy_decision(body)
    actual_redacted = body.get("pii_detected", False)

    expected_routing = case.get("expected_routing_team", "")
    expected_decision = case.get("expected_policy_decision", "")
    expected_redacted = case.get("expected_redacted", False)

    passed = (
        actual_routing == expected_routing
        and actual_decision == expected_decision
        and actual_redacted == expected_redacted
    )

    return {
        "passed": passed,
        "latency_ms": latency_ms,
        "actual": {
            "routing_team": actual_routing,
            "policy_decision": actual_decision,
            "redacted": actual_redacted,
        },
        "expected": {
            "routing_team": expected_routing,
            "policy_decision": expected_decision,
            "redacted": expected_redacted,
        },
    }


def _run_sql(case: Dict[str, Any], client: httpx.Client) -> Dict[str, Any]:
    t0 = time.time()
    try:
        resp = client.post(
            f"{BASE_URL}/v1/sql/validate",
            json={"query": case["sql"]},
            timeout=10.0,
        )
        latency_ms = int((time.time() - t0) * 1000)
        body = resp.json()
    except Exception as exc:
        return {"passed": False, "error": str(exc), "latency_ms": 0}

    actual_allowed = body.get("allowed", None)
    expected_allowed = case.get("expected_allowed")
    passed = actual_allowed == expected_allowed

    return {
        "passed": passed,
        "latency_ms": latency_ms,
        "actual": {"allowed": actual_allowed, "reason": body.get("reason", "")},
        "expected": {"allowed": expected_allowed},
    }


def run_eval(compare_path: Optional[Path] = None) -> int:
    prompts = json.loads(PROMPTS_PATH.read_text())
    RESULTS_DIR.mkdir(exist_ok=True)

    results = []
    tag_counts: Dict[str, Dict[str, int]] = {}

    with httpx.Client() as client:
        for case in prompts:
            cid = case["id"]
            tags = case.get("tags", [])

            if "sql" in tags:
                outcome = _run_sql(case, client)
            else:
                outcome = _run_intake(case, client)

            outcome["id"] = cid
            outcome["tags"] = tags
            results.append(outcome)

            for tag in tags:
                tag_counts.setdefault(tag, {"passed": 0, "total": 0})
                tag_counts[tag]["total"] += 1
                if outcome["passed"]:
                    tag_counts[tag]["passed"] += 1

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed
    pass_rate = passed / total

    summary = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": round(pass_rate, 4),
        "pass_rate_pct": f"{pass_rate * 100:.1f}%",
        "results_by_tag": {
            tag: f"{v['passed']}/{v['total']}" for tag, v in tag_counts.items()
        },
        "results": results,
    }

    out_path = RESULTS_DIR / "latest.json"
    out_path.write_text(json.dumps(summary, indent=2))

    _print_table(results, summary, tag_counts)

    if compare_path:
        baseline = json.loads(Path(compare_path).read_text())
        baseline_rate = baseline.get("pass_rate", 0)
        drop = baseline_rate - pass_rate
        print(f"\nBaseline pass_rate: {baseline_rate * 100:.1f}%")
        print(f"Current  pass_rate: {pass_rate * 100:.1f}%")
        if drop > 0.05:
            print(f"REGRESSION: pass_rate dropped {drop * 100:.1f} points (threshold: 5)")
            return 1
        print(f"Regression check passed (delta: {drop * 100:.1f} points)")

    return 0 if pass_rate >= PASS_THRESHOLD else 1


def _print_table(
    results: List[Dict], summary: Dict, tag_counts: Dict[str, Dict[str, int]]
) -> None:
    print(f"\n{'─' * 72}")
    print(f"  AI Control Plane — Eval Harness Results")
    print(f"{'─' * 72}")
    print(f"  {'ID':<12} {'TAGS':<20} {'PASS':<6} {'LATENCY':>8}  {'DETAIL'}")
    print(f"{'─' * 72}")
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        tags = ",".join(r.get("tags", []))
        latency = f"{r.get('latency_ms', 0)}ms"
        detail = ""
        if not r["passed"]:
            a = r.get("actual", {})
            e = r.get("expected", {})
            detail = f"got={a} want={e}"
        print(f"  {r['id']:<12} {tags:<20} {status:<6} {latency:>8}  {detail}")
    print(f"{'─' * 72}")
    print(f"  Total: {summary['total']}  Passed: {summary['passed']}  Failed: {summary['failed']}")
    print(f"  Pass rate: {summary['pass_rate_pct']}")
    print(f"  By tag: {summary['results_by_tag']}")
    print(f"{'─' * 72}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--compare", metavar="PATH", help="Baseline JSON to compare against")
    args = parser.parse_args()
    sys.exit(run_eval(compare_path=args.compare))
