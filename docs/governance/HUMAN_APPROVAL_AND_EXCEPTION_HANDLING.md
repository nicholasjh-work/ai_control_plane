# Human Approval and Exception Handling

This document defines which actions require human approval, how approval-gated outcomes work, how exceptions and denied requests are handled, and how the escalation path operates within `ai_control_plane`.

---

## 1. Purpose

To specify the human oversight layer of the `ai_control_plane` service. AI agents in this system are bounded: they do not run until a human has either implicitly cleared the request (by submitting a clean intake) or explicitly approved it (by calling the approval endpoint after a policy hold). This document describes the mechanism, the risk tiers that trigger it, and the handling of each outcome.

---

## 2. Business Use Case

In AI-assisted operational workflows, the most common source of governance failure is not malicious intent — it is a clean-looking request that happens to contain PII or a sensitive identifier that should not enter an AI's context without review. The approval gate addresses this by holding any request above a risk threshold and requiring a human decision before agents run.

This also creates an evidence trail: every approval decision has an approver identity, a reason, and a timestamp, making it possible to review who approved what and why.

---

## 3. Operating Model

The approval model operates in three tiers based on the risk score produced by `evaluate_policy()`:

| Risk Tier | Condition | Action | Agents run? |
|---|---|---|---|
| Tier 0 — Blocked | `blocked_keywords` match OR `risk_score >= risk_threshold_block` | `status: blocked` | No |
| Tier 1 — Approval Required | `risk_score >= risk_threshold_approval` (currently: PII detected) | `status: needs_approval` | No — held pending human decision |
| Tier 2 — Allowed | `risk_score < risk_threshold_approval`, no blocked keywords | `status: succeeded` | Yes |

Current configured thresholds (from `app/config/policy_rules.json`):
- `risk_score_clean: 0.25`
- `risk_score_pii: 0.70`
- `risk_threshold_approval: 0.70`
- `risk_threshold_block: 0.90`

The risk score for PII-detected requests (0.70) equals the approval threshold, so all PII-detected requests enter Tier 1. The block threshold (0.90) is not reachable with current scoring unless a `blocked_keywords` match is added to the `policy_rules.json` `blocked_keywords` list (currently empty).

---

## 4. Architecture

```
POST /run
    │
    ├─ evaluate_policy()
    │       ├─ blocked_keyword match
    │       │       └─ return {action: "block", allowed: False, requires_approval: False}
    │       ├─ risk_score >= risk_threshold_block
    │       │       └─ return {action: "block", allowed: False, requires_approval: False}
    │       ├─ risk_score >= risk_threshold_approval (PII detected)
    │       │       └─ return {action: "require_approval", requires_approval: True}
    │       └─ clean → {action: "allow" or "allow_with_redaction"}
    │
    ├─ if requires_approval:
    │       ├─ build_audit_record(status="needs_approval")
    │       ├─ write_audit_record() → PostgreSQL
    │       └─ return DecisionOutput(status="needs_approval", audit_id=...)
    │
    ├─ if not allowed:
    │       ├─ build_audit_record(status="blocked")
    │       ├─ write_audit_record() → PostgreSQL
    │       └─ return DecisionOutput(status="blocked", audit_id=...)
    │
    └─ agents run → audit written → DecisionOutput(status="succeeded")

Approval flow:
    POST /approve/{audit_id}
        ├─ Validate decision: "approved" | "rejected"
        ├─ find_audit_record() → look up original record
        ├─ record_approval() → append to approvals.jsonl
        └─ Return approval record

Replay flow (after approval):
    POST /replay/{audit_id}
        ├─ find_audit_record() → retrieve sanitized_payload
        ├─ WorkflowEngine.run(sanitized_payload)
        ├─ build_audit_record(status="replayed", policy includes replayed_from_audit_id)
        └─ write_audit_record() → PostgreSQL
```

---

## 5. Control Design

### Implemented controls

**Approval gate — trigger:**
`evaluate_policy()` returns `requires_approval: True` when `risk_score >= risk_threshold_approval`. This is currently triggered by any PII detection (email or SSN in title or description). The `/run` handler checks `policy.get("requires_approval")` and returns immediately without invoking agents.

**Approval gate — record:**
An audit record is written at the moment of hold, before the response is returned. The record contains the full policy evaluation including which PII types were detected, the risk score, and the sanitized (redacted) payload. Agents never run for held requests.

**Approval endpoint — validation:**
`POST /approve/{audit_id}` validates that `decision` is one of `"approved"` or `"rejected"`. Any other value returns `{"status": "error", "message": "decision must be 'approved' or 'rejected'"}`.

**Approval endpoint — audit_id lookup:**
`find_audit_record()` scans `logs/audit.jsonl` for the given `audit_id`. If not found, returns `{"status": "error", "message": "audit_id not found"}`.

**Approval record contents (Implemented):**
- `approval_id`: `str(uuid.uuid4())` — UUID4, collision-resistant
- `timestamp_utc`: UTC ISO timestamp of approval
- `audit_id`: reference to original audit record
- `decision`: "approved" or "rejected"
- `approved_by`: human identifier from request body
- `reason`: text from request body

**Approval persistence (Implemented):**
`record_approval()` writes the approval to `logs/approvals.jsonl` (supplemental append-only ledger) and then calls `_update_postgres_approval()`, which sets `approved = True` or `False` on the matching row in `ai_control_plane_audit`. The JSONL ledger is preserved; PostgreSQL is the primary queryable store.

**Audit lookup (Implemented):**
`find_audit_record()` queries PostgreSQL by `request_id` as the primary path. If the DB is unavailable, it falls back to JSONL scan. The fallback is documented in code as non-authoritative.

**Replay — sanitized payload only:**
`POST /replay/{audit_id}` extracts `sanitized_payload` from the stored policy dict and re-runs the workflow. If `sanitized_payload` is not present in the stored record, the endpoint returns an error. The original PII-containing payload is never used for replay.

**Block handling:**
Blocked requests write an audit record with `status: "blocked"` and `agents: ["policy_block"]`. The response returns `status: "blocked"` with the `audit_id`. No further processing occurs.

### Designed but not yet implemented

- **Auto-replay after approval:** Currently, approval and replay are two separate API calls. There is no mechanism to automatically trigger replay when an approval decision of "approved" is received.
- **Rejection notification:** When `decision: "rejected"`, an approval record is written but no notification is sent to the original requester.
- **Approval expiry:** There is no time limit on how long a request can remain in `needs_approval` state. An old approval record could replay a workflow from an outdated sanitized payload.
- **Replay enforcement gate:** `POST /replay/{audit_id}` does not verify that an approval record exists before re-running the workflow. Enforcing approved-before-replay is a designed extension.

---

## 6. Governance Workflow

### Tier 1 — Approval-required path

```
1. Caller submits POST /run with PII in title or description
2. evaluate_policy() detects PII, sets risk_score=0.70
3. Audit record written: status="needs_approval", agents=["policy_approval_required"]
4. Response returned: {status: "needs_approval", audit_id: "<uuid>", pii_detected: true, redacted: true}

5. Human reviewer receives the audit_id
6. Human calls POST /approve/{audit_id} with:
   {decision: "approved", approved_by: "reviewer_name", reason: "Validated vendor contact"}
7. Approval record written to approvals.jsonl (supplemental ledger); approved column updated in PostgreSQL
8. Response: {status: "ok", approval: {approval_id (UUID4), timestamp_utc, audit_id, decision, approved_by, reason}}

9. Human calls POST /replay/{audit_id}
10. sanitized_payload extracted from original audit record
11. WorkflowEngine runs with sanitized payload (PII already redacted)
12. New audit record written: status="replayed", policy.replayed_from_audit_id=original_audit_id
13. Response: {status: "replayed", original_audit_id: "...", audit: {...}, result: {...}}
```

### Tier 0 — Blocked path

```
1. Caller submits POST /run with a blocked keyword (if configured) or extreme risk score
2. evaluate_policy() returns action="block", allowed=False
3. Audit record written: status="blocked", agents=["policy_block"]
4. Response returned: {status: "blocked", audit_id: "<uuid>"}
5. No further action. Blocked requests cannot be replayed.
```

### Exception handling

If `approve/{audit_id}` is called with an `audit_id` that is not found in PostgreSQL or JSONL, the endpoint returns:
```json
{"status": "error", "message": "audit_id not found"}
```

If `/replay/{audit_id}` is called and the record has no `sanitized_payload` in its policy dict, the endpoint returns:
```json
{"status": "error", "message": "no sanitized_payload available for replay"}
```

---

## 7. Implementation Workflow

```bash
# Submit a PII-containing request
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Invoice confirmation",
    "description": "Please contact billing@vendor.com to confirm receipt.",
    "requester_email": "ap@company.com",
    "department": "finance",
    "system": "accounts_payable",
    "urgency": "medium"
  }'
# Response: {status: "needs_approval", audit_id: "<uuid>", pii_detected: true, ...}

# Record an approval decision
curl -X POST "http://localhost:8000/approve/<uuid>" \
  -H "Content-Type: application/json" \
  -d '{"decision": "approved", "approved_by": "jane.reviewer", "reason": "Verified vendor contact"}'

# Replay the approved request
curl -X POST "http://localhost:8000/replay/<uuid>"
```

---

## 8. Operational Metrics

| Metric | Source |
|---|---|
| Approval-required rate | Count of `needs_approval` in `ai_control_plane_audit.resolution` |
| Approval decision distribution | Parse `decision` field in `approvals.jsonl`: approved vs. rejected |
| Approver identity distribution | Parse `approved_by` in `approvals.jsonl` |
| Replay rate | Count of `replayed` in `ai_control_plane_audit.resolution` |
| Blocked request rate | Count of `blocked` in `ai_control_plane_audit.resolution` |
| Average time from hold to approval | Requires `approvals.jsonl` timestamp minus `ai_control_plane_audit.created_at`; not currently computed |

The eval harness covers 8 PII cases (eval_011 through eval_018) that validate the `require_approval` policy decision and the `redacted: true` flag. All 8 passed in the recorded baseline run.

---

## 9. Workplace Application

The approval gate pattern is applicable in any context where AI assistance operates on data that may include personal identifiers, financial data, or other sensitive content that should not be processed without human review. Key aspects of this implementation that apply in a real environment:

- **The hold is immediate and recorded.** A request does not sit in a queue; it returns immediately to the caller with a `needs_approval` status and an audit_id. The caller can surface this to a reviewer UI or notification system.
- **Agents never see unredacted PII.** The hold is triggered before agents run, and replay uses only the redacted payload. This is the correct order of operations.
- **The approver identity and reason are part of the record.** An approval without attribution is not audit-quality evidence. The `approved_by` and `reason` fields are required in the approval request body.
- **Replay is a separate step.** Separating approval from replay gives the reviewer an opportunity to review the outcome after replaying before acting on it.

---

## 10. Limitations

- There is no notification mechanism. A request in `needs_approval` state does not notify anyone. The caller must surface the `audit_id` to a reviewer through an external channel.
- Approval and replay are two separate API calls. A reviewer must call both to complete the approval-to-processing flow.
- `_update_postgres_approval()` silently swallows DB exceptions. If the update fails, the JSONL ledger has the approval record but PostgreSQL `approved` remains `False`. This inconsistency is not surfaced to the caller.
- The `approvals.jsonl` flat file is not suitable for high-volume concurrent writes. PostgreSQL is the primary store; JSONL is supplemental.
- There is no approval expiry. A `needs_approval` request from weeks ago can be replayed at any time.
- Rejected requests have no downstream effect beyond the approval record. There is no mechanism to notify the requester of rejection or to mark the original request as definitively closed.
- The block path has no override mechanism. A blocked request cannot be approved and replayed.

---

## 11. What This Does Not Claim

- The approval flow does not constitute a complete governance workflow. Notification, escalation routing, SLA tracking, and requester communication are not implemented.
- Approval by a named `approved_by` identity is not authenticated. The service accepts any string as the approver name; there is no integration with an identity provider or SSO system.
- The `needs_approval` state does not time out. Requests can remain indefinitely unapproved.
- The service does not enforce that a request was approved before replay. `POST /replay/{audit_id}` does not verify that an approval record exists for the given `audit_id`.
- No workflow automation (e.g., JIRA tickets, email notifications, Slack alerts) is implemented or implied.

---

## 12. Extension Path

- **Enforce approval before replay:** In `/replay/{audit_id}`, check `approvals.jsonl` (or a PostgreSQL `approval_events` table) for a record with `audit_id` and `decision: "approved"` before proceeding. Return an error if no approved record exists.
- **Auto-replay after approval:** Modify `/approve/{audit_id}` to trigger the replay pipeline automatically when `decision == "approved"`, combining the two steps.
- **Surface `_update_postgres_approval` failures:** Log a structured warning when the PostgreSQL update fails so the inconsistency between JSONL and DB state is observable.
- **Approval expiry:** Add an `expires_at` timestamp to the audit record at hold time. The replay endpoint checks this timestamp and rejects stale approvals.
- **Block override path:** For requests that are blocked by keyword but not by PII risk, add an optional override that allows a senior approver to move the request to the approval queue.
- **Approver authentication:** Integrate with an identity provider to validate the `approved_by` field against an authenticated session token.
- **Move approvals to PostgreSQL:** Add an `approval_events` table and replace `approvals.jsonl` with SQLAlchemy inserts.

---

## 13. Interview Talking Points

- **Why does the approval gate hold the request before agents run, rather than letting agents run and then asking for approval?** If agents run first, PII enters LLM context. The goal of the approval gate is to ensure human review happens before any AI processing of sensitive content. Holding before dispatch is the only design that achieves this.
- **What prevents an unauthenticated caller from approving a request?** Currently, nothing. The `approved_by` field is a free-text string from the request body. Authentication integration is a designed extension. In a real deployment, the approval endpoint would be protected by an identity provider and the `approved_by` value would be derived from the authenticated session.
- **Can a blocked request be replayed?** No. The block path writes an audit record with `status: "blocked"` and does not store a `sanitized_payload` in the policy dict in the same way as the approval path. The replay endpoint would return `"no sanitized_payload available for replay"` if called on a blocked audit_id.
- **How do you know which requests are awaiting approval?** Query `ai_control_plane_audit` for rows where `resolution = 'needs_approval'` and `approved = false`. The `approved` column is now updated by `_update_postgres_approval()` when `/approve/{audit_id}` is called, making this query reliable for filtering pending vs. resolved holds.
- **What is the risk tier model here?** Three tiers: blocked (no processing, no override), approval-required (hold pending human decision, then replay), and allowed (direct processing). The thresholds are configurable in `policy_rules.json` without code changes.
