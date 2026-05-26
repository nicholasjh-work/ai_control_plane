# Governance Eval Harness

This document describes the evaluation harness implemented in `ai_control_plane` for testing agent behavior, policy enforcement, SQL safety, and routing accuracy. It documents what `prompts.json`, `baseline.json`, and `runner.py` actually do, and reports the actual coverage and results from the recorded baseline run.

---

## 1. Purpose

To provide a repeatable, automated test of system behavior across the full range of expected inputs, including clean requests, PII-containing requests, SQL safety cases, edge cases, and routing fallbacks. The harness is separate from unit tests: it validates end-to-end behavior of the running service, not isolated module behavior.

---

## 2. Business Use Case

Policy engines and classification systems can drift. A change to `policy_rules.json`, a change to `routing_rules.json`, or an update to the LLM model can alter behavior in ways that unit tests do not catch. The eval harness catches this by:
- Running a fixed set of labeled cases against the live service after every change
- Comparing the result to expected values for three measurable fields per intake case
- Producing a structured pass/fail report with per-tag breakdowns
- Comparing the current pass rate against a saved baseline

This makes behavioral regression observable in the same CI run that checks code style and unit tests.

---

## 3. Operating Model

The harness (`eval/runner.py`) is a command-line tool that:
1. Loads 30 test cases from `eval/prompts.json`
2. POSTs each case to the running service
3. Compares the response to expected values
4. Writes results to `eval/results/latest.json`
5. Prints a formatted pass/fail table to stdout
6. Exits with code 0 if pass rate >= 90%, code 1 otherwise

It supports an optional `--compare` flag that loads a baseline JSON file and fails if the current pass rate drops more than 5 percentage points below the baseline.

```bash
# Run against a live server on localhost:8000
make eval

# Run with regression comparison
make eval-regression
```

---

## 4. Architecture

```
eval/runner.py
    │
    ├─ PROMPTS_PATH = eval/prompts.json          (30 test cases)
    ├─ BASE_URL = os.getenv("EVAL_BASE_URL", "http://localhost:8000")
    ├─ PASS_THRESHOLD = 0.90
    │
    ├─ For each case:
    │       ├─ "sql" in tags → _run_sql(case, client)
    │       │       └─ POST /v1/sql/validate {"query": case["sql"]}
    │       │           compare actual["allowed"] == expected["expected_allowed"]
    │       │
    │       └─ otherwise → _run_intake(case, client)
    │               └─ POST /run case["intake"]
    │                   compare actual routing_team, policy_decision, redacted
    │                   against expected_routing_team, expected_policy_decision, expected_redacted
    │
    ├─ _derive_policy_decision(body):
    │       status=blocked → "block"
    │       status=needs_approval → "require_approval"
    │       status=succeeded and pii_detected=true → "allow_with_redaction"
    │       otherwise → "allow"
    │
    ├─ Results written to eval/results/latest.json
    │
    └─ Pass rate >= PASS_THRESHOLD? → exit 0 : exit 1

eval/baseline.json
    └─ Saved pass_rate from first clean run (1.0 / 100.0%)

eval/results/latest.json
    └─ Most recent run results (30/30 pass, 100.0% in recorded run)
```

---

## 5. Control Design

### What prompts.json contains

The 30 test cases in `eval/prompts.json` are organized into five tagged groups. All cases are synthetic and labeled as test data; no real personal information is used.

#### Tag: routing (10 cases — eval_001 through eval_010)

Tests that the policy engine routes requests to the correct team based on keyword matching in title and description.

| Cases | Expected team | Keywords present |
|---|---|---|
| eval_001, eval_002, eval_003 | billing | invoice, payment/charge, refund |
| eval_004, eval_005, eval_006 | technical | 502 error/outage, timeout/ETL, crash/Safari |
| eval_007, eval_008 | compliance | audit log, redaction/SSN policy |
| eval_009, eval_010 | general | directory name update, office supply order |

All routing cases expect `expected_policy_decision: "allow"` and `expected_redacted: false`.

#### Tag: pii (8 cases — eval_011 through eval_018)

Tests that requests containing email addresses or SSNs in title or description trigger the `require_approval` policy decision and set `redacted: true`.

| Cases | PII type | Expected team |
|---|---|---|
| eval_011 | Email address in description | billing |
| eval_012 | SSN in description | technical |
| eval_013 | Email address in description | billing |
| eval_014 | SSN in description | general |
| eval_015 | Two email addresses in description | general |
| eval_016 | SSN in description | general |
| eval_017 | Email address in description | compliance |
| eval_018 | SSN in description | general |

All PII cases expect `expected_policy_decision: "require_approval"` and `expected_redacted: true`.

#### Tag: sql (6 cases — eval_019 through eval_024)

Tests the SQL safety layer via `POST /v1/sql/validate`.

| Case | SQL | Expected |
|---|---|---|
| eval_019 | `SELECT audit_id, created_at FROM v_audit_summary WHERE resolution = 'succeeded'` | allowed |
| eval_020 | `SELECT routing_team, COUNT(*) FROM v_routing_decisions GROUP BY routing_team` | allowed |
| eval_021 | `SELECT agent_name, avg_latency_ms FROM v_agent_performance ORDER BY avg_latency_ms DESC LIMIT 10` | allowed |
| eval_022 | `INSERT INTO v_ticket_summary (id, title) VALUES ('abc', 'test')` | blocked |
| eval_023 | `DROP TABLE v_audit_summary` | blocked |
| eval_024 | `SELECT * FROM raw_user_pii WHERE ssn IS NOT NULL` | blocked (table not in allowlist) |

#### Tag: edge (4 cases — eval_025 through eval_028)

Tests boundary conditions and atypical inputs.

| Case | Condition | Expected decision |
|---|---|---|
| eval_025 | Empty description field | allow, general |
| eval_026 | Very long description (~400 words, no PII) | allow, billing |
| eval_027 | Clean routine request with no routing keywords | allow, general |
| eval_028 | Unicode characters + email address in description | require_approval, general |

#### Tag: fallback (2 cases — eval_029 through eval_030)

Tests that requests with no routing keywords default to the "general" team.

| Case | Expected decision |
|---|---|
| eval_029 | allow, general (no keyword match, explicit test) |
| eval_030 | allow, general (no keyword match, onboarding content) |

---

## 6. Governance Workflow

### Running the harness

1. Start the service: `make run` (uvicorn on port 8000)
2. In a separate terminal: `make eval`
3. Review output table and `eval/results/latest.json`
4. If pass rate drops, investigate failing cases before merging

### Baseline comparison

```bash
make eval-regression
```

This loads `eval/baseline.json` and compares the current `pass_rate` against `baseline.pass_rate`. If the drop exceeds 5 percentage points, the command exits with code 1 and prints:
```
REGRESSION: pass_rate dropped X.X points (threshold: 5)
```

### Updating the baseline

After an intentional improvement that changes expected behavior:
```bash
cp eval/results/latest.json eval/baseline.json
```

### CI integration

The `.github/workflows/ci.yml` pipeline runs `make lint` and `make test`. The eval harness (`make eval`) is defined in the Makefile but requires a running server, which is not currently started in CI. Adding `eval` to CI would require starting the server as a background process before running the harness.

### Running the eval harness locally (full sequence)

The eval harness requires a live server with PostgreSQL tables created:

```bash
# 1. Apply database migrations
make migrate

# 2. Start the server in one terminal
make run
# → uvicorn starts on http://localhost:8000

# 3. In a second terminal, run the harness
make eval

# 4. For regression comparison against baseline
make eval-regression
```

Verified result on local environment with PostgreSQL:
- 30/30 passed (100.0%)
- By tag: routing 10/10, pii 8/8, sql 6/6, edge 4/4, fallback 2/2
- Eval harness exit code: 0

---

## 7. Implementation Workflow

### Adding a new test case

1. Open `eval/prompts.json`
2. Append a new object following the schema:

For intake cases:
```json
{
  "id": "eval_031",
  "intake": {
    "title": "...",
    "description": "...",
    "requester_email": "...",
    "department": "...",
    "system": "...",
    "urgency": "..."
  },
  "expected_routing_team": "general",
  "expected_policy_decision": "allow",
  "expected_redacted": false,
  "tags": ["routing"]
}
```

For SQL cases:
```json
{
  "id": "eval_031",
  "sql": "SELECT * FROM v_ticket_summary",
  "expected_allowed": true,
  "tags": ["sql"]
}
```

3. Run `make eval` to verify the new case passes before committing.

---

## 8. Operational Metrics

### Recorded baseline results (from eval/results/latest.json and eval/baseline.json)

Both files record the same result: the first clean run after the full harness was implemented.

| Metric | Value |
|---|---|
| Total cases | 30 |
| Passed | 30 |
| Failed | 0 |
| Pass rate | 100.0% |
| Routing tag (10 cases) | 10/10 |
| PII tag (8 cases) | 8/8 |
| SQL tag (6 cases) | 6/6 |
| Edge tag (4 cases) | 4/4 |
| Fallback tag (2 cases) | 2/2 |

### Latency observations (from latest.json)

- Intake cases (routing, pii, edge, fallback): 40–150ms (includes full pipeline with LLM fallback path)
- PII cases (needs_approval, no agents run): 1–2ms (policy-only, no agent pipeline)
- SQL validation cases: 0–2ms (pure parsing, no network)

PII cases are fastest because agents do not run. SQL cases are near-zero because they use sqlglot's in-process parser with no database or LLM call.

### Pass threshold

`PASS_THRESHOLD = 0.90` in `runner.py`. The harness requires at least 27/30 cases to pass. Current baseline is 30/30.

### Regression threshold

5 percentage points. A drop from 100% to below 95% would trigger a regression failure when running `make eval-regression`.

---

## 9. Workplace Application

Evaluation harnesses of this type are applicable in AI-assisted operations wherever behavior must remain stable across code changes, configuration changes, and model updates. Key design aspects relevant to real operational use:

- **Three measurable fields per case.** Each intake case asserts `routing_team`, `policy_decision`, and `redacted`. These cover the three decision points that matter for operations: where does this go, what policy action was taken, and was PII handled. A single composite pass/fail is simpler to reason about than separate assertions.
- **Policy decision derivation from response fields.** The `_derive_policy_decision()` function maps `status` and `pii_detected` to a decision label. This means the harness tests observable behavior, not internal state.
- **Tag-based reporting.** The per-tag pass rates in the output make it immediately clear whether a regression is in routing, PII detection, SQL validation, or edge case handling. This narrows the investigation scope.
- **Baseline comparison as a regression gate.** Storing the baseline in version control and comparing against it in CI makes behavioral regression observable without requiring a human to manually compare runs.

---

## 10. Limitations

- The eval harness requires a running server. It cannot be run as part of a pure unit test suite. CI integration requires background server startup.
- Harness cases test observable API behavior, not internal state. If the policy engine makes an incorrect decision for the wrong reason, the harness may still pass.
- The 30 cases do not cover all possible input combinations. Coverage gaps include: requests with both email and SSN, requests where the routing team and PII detection interact unexpectedly, and requests at the max_intake_length boundary.
- The harness does not test the approval or replay endpoints. eval_011 through eval_018 confirm the `needs_approval` decision but do not call `/approve` or `/replay`.
- SQL cases do not test CTE (WITH clause) behavior or queries with multiple subquery levels.
- The harness does not test LLM fallback behavior directly. All eval cases run with whatever LLM configuration is active; if the LLM is available during eval, LLM routing is used. If unavailable, the keyword fallback is used. Both paths should produce the same expected `routing_team` values, but this is not explicitly verified.
- eval_026 expects `routing_team: "billing"`. This works because the long description contains the word "transaction" which matches a billing keyword. This is correct but non-obvious and could be a maintenance point if routing keywords change.

---

## 11. What This Does Not Claim

- The 30/30 pass rate recorded in `eval/results/latest.json` and `eval/baseline.json` was achieved on the local development environment with a specific configuration. It is not a production validation result.
- The harness does not validate LLM output quality, factual accuracy, or summary coherence. It tests policy behavior and routing decisions, which are deterministic or fallback-deterministic.
- eval_012 includes a synthetic SSN pattern (`123-45-6789`) formatted in the standard XXX-XX-XXXX pattern. This is test data labeled as sample data in this document; no real individual's SSN is used anywhere in the codebase.
- The eval harness does not constitute a security test. It tests functional behavior, not adversarial robustness.
- No production model validation, A/B testing, or online evaluation is claimed.

---

## 12. Extension Path

- **Add approval/replay cases:** Extend the harness to call `/approve/{audit_id}` and `/replay/{audit_id}` for the PII cases that produce `needs_approval`, and verify that replay produces `status: succeeded`.
- **LLM fallback cases:** Add a test mode where LLM is explicitly disabled (e.g., by pointing `LLM_BASE_URL` at a non-existent endpoint) and verify that all routing cases still pass with deterministic fallback.
- **CI server startup:** Add a step in `.github/workflows/ci.yml` that starts the server (`uvicorn app.main:app &`), waits for `/health` to return 200, runs `make eval`, then shuts down the server.
- **Additional SQL cases:** Add cases for CTE queries, multi-level subqueries, UNION queries, and queries that combine allowed and disallowed tables.
- **Max-length edge case:** Add a case with `title + description` exactly at `max_intake_length` (2000 chars) and one case at 2001 chars.
- **Coverage reporting:** Add a `--coverage-report` flag to `runner.py` that outputs which policy paths were exercised (allow, allow_with_redaction, require_approval, block) and which were not.

---

## 13. Interview Talking Points

- **Why 30 cases rather than hundreds?** 30 cases is enough to cover all five meaningful tag categories with meaningful distribution while keeping the harness fast enough to run in a CI pipeline. More cases without more coverage of distinct paths add noise without adding signal.
- **What is the difference between the eval harness and the unit tests?** Unit tests (`tests/`) test individual functions in isolation: `validate_query()`, `evaluate_policy()`, `hash_email()`. The eval harness tests end-to-end API behavior of the running service. Both are needed: unit tests catch regressions in isolated logic; the harness catches regressions in the assembled system.
- **How does the `_derive_policy_decision()` function work?** It maps the `status` and `pii_detected` fields from the `/run` response to one of four decision labels: block, require_approval, allow_with_redaction, allow. This mapping is explicit and testable, and avoids coupling the harness to internal field names that might change.
- **What would a failing case look like?** A case fails if any of its three assertion fields (routing_team, policy_decision, redacted) do not match the expected values. The table printed to stdout shows `FAIL` for that case and prints the actual vs. expected values. The most common failure mode would be a routing keyword change in `routing_rules.json` that shifts a case from one team to another.
- **How would you extend this to test the approval flow?** Add a new `_run_approval` function in `runner.py` that (1) calls `/run` to get an `audit_id` and `needs_approval` status, (2) calls `/approve/{audit_id}` with a test approver, (3) calls `/replay/{audit_id}`, and (4) verifies the replayed response has `status: succeeded`. Add these as a new `"approval"` tag group in `prompts.json`.
