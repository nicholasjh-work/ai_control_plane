# Eval Harness

This document describes the evaluation harness for ai_control_plane. It is separate from the main README.

## What the harness does

`eval/runner.py` loads 30 structured test cases from `eval/prompts.json`, sends each one to the live server, compares the response to expected values, and reports a pass/fail score. It exits with code 0 if the pass rate is 90% or above, and code 1 if below.

Results are written to `eval/results/latest.json` after every run.

## How to run

Start the server in one terminal:

```
make run
```

Run the harness in another:

```
make eval
```

To compare against the saved baseline:

```
make eval-regression
```

This fails if the current pass rate drops more than 5 percentage points below the baseline.

## What the 30 cases cover

| Tag | Count | What is tested |
|---|---|---|
| `routing` | 10 | Intake tickets routed to billing (3), technical (3), compliance (2), general (2) |
| `pii` | 8 | Tickets containing email addresses or SSNs that trigger the `require_approval` policy decision |
| `sql` | 6 | SQL validation: 3 valid SELECTs against allowed views, 3 blocked statements (INSERT, DROP, unknown table) |
| `edge` | 4 | Empty description, long intake text, unicode characters, unexpected content |
| `fallback` | 2 | Content that does not match any routing keyword — expected to fall through to `general` |

Each intake case asserts three fields: `routing_team`, `policy_decision`, and `redacted`. SQL cases assert `allowed`.

The policy decision mapping from the `/run` response:

| `status` | `pii_detected` | Mapped decision |
|---|---|---|
| `succeeded` | false | `allow` |
| `succeeded` | true | `allow_with_redaction` |
| `needs_approval` | any | `require_approval` |
| `blocked` | any | `block` |

## How to add new cases

Open `eval/prompts.json` and append a new object following the schema of an existing case in the same tag group. Increment the `id` sequence (`eval_031`, etc.). Run `make eval` to verify the new case passes before committing.

For SQL cases, omit `intake`, `expected_routing_team`, `expected_policy_decision`, and `expected_redacted`. Include `sql` and `expected_allowed` instead.

## Pass threshold

The harness requires 90% pass rate (27/30 or better). This threshold is set in `eval/runner.py` as `PASS_THRESHOLD = 0.90`.

## Regression baseline

`eval/baseline.json` contains the result summary from the first clean run. The `make eval-regression` command compares the current pass rate against the baseline and fails if it drops more than 5 percentage points.

To update the baseline after an intentional improvement, copy `eval/results/latest.json` to `eval/baseline.json`.
