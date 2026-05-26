# Audit Logging and Control Evidence

This document defines the audit log model implemented in `ai_control_plane`, explains how audit evidence supports governance review and control validation, identifies which fields are implemented versus designed, and references the AUDIT.md control review.

---

## 1. Purpose

To establish a complete and accurate record of every request processed by the service, including the policy decision made, which agents were invoked, whether PII was detected and redacted, and the outcome of the workflow. This record supports troubleshooting, governance review, approval tracking, and replay of prior workflows from the stored sanitized payload.

---

## 2. Business Use Case

Regulated and risk-sensitive data operations require that every AI-assisted decision be traceable. Without an audit log, it is impossible to:
- Reconstruct what happened to a request that resulted in an unexpected outcome
- Verify that PII-containing requests were held for approval rather than processed directly
- Demonstrate that blocked requests were recorded and not silently dropped
- Replay a workflow after human approval using the exact sanitized payload that was evaluated at intake

The audit log serves as the primary evidence artifact for all of these requirements.

---

## 3. Operating Model

Every request that reaches `POST /run` results in exactly one audit record, regardless of outcome. The record is written:
- Before returning a `blocked` response
- Before returning a `needs_approval` response
- After the agent pipeline completes for `succeeded` outcomes
- After the agent pipeline completes for `replayed` outcomes

The audit record is written to a PostgreSQL table (`ai_control_plane_audit`) via SQLAlchemy. The requester email is hashed before any storage operation. The raw email is never written to the database.

Approval records (from `POST /approve/{audit_id}`) are written separately to `logs/approvals.jsonl`.

---

## 4. Architecture

```
build_audit_record()                    — app/governance/audit.py
    ├─ audit_id: uuid4
    ├─ timestamp_utc: datetime.now(timezone.utc).isoformat()
    ├─ input_hash: sha256(json.dumps(payload, sort_keys=True))
    ├─ agents_invoked: list of agent names
    ├─ policy: full policy evaluation dict
    ├─ latency_ms: elapsed time since Timer() start
    ├─ status: "succeeded" | "blocked" | "needs_approval" | "replayed"
    └─ summary: LLM-generated summary or "unavailable" or None

write_audit_record(audit, intake)       — app/governance/audit.py
    ├─ hash_email(intake["requester_email"]) → requester_email_hash
    ├─ Exclude requester_email from intake_text
    └─ SQLAlchemy insert into ai_control_plane_audit
```

Approval record (separate):
```
record_approval()                       — app/governance/approvals.py
    ├─ approval_id: uuid4()             (collision-resistant UUID)
    ├─ timestamp_utc
    ├─ audit_id (reference to original audit record)
    ├─ decision: "approved" | "rejected"
    ├─ approved_by: human identifier from request body
    └─ reason: text from request body
→ Appended to logs/approvals.jsonl     (supplemental ledger)
→ _update_postgres_approval()          (sets approved column in ai_control_plane_audit)
```

Audit lookup:
```
find_audit_record()                     — app/governance/approvals.py
    ├─ Primary: SessionLocal() → query AuditRecord by request_id (PostgreSQL)
    │       Returns structured dict if row found
    └─ Fallback: JSONL scan (only when DB is unavailable or row absent)
               Documented in code as non-authoritative fallback path
```

---

## 5. Control Design

### Audit record fields — Implemented

| Field | Type | Source | Notes |
|---|---|---|---|
| `id` | UUID | `uuid.uuid4()` | PostgreSQL primary key |
| `request_id` | String | same UUID as `id` | Index for lookup |
| `requester_email_hash` | String (64 hex chars) | `hashlib.sha256(email.encode()).hexdigest()` | SHA-256 of raw email; raw email never stored |
| `intake_text` | Text (JSON) | intake payload minus `requester_email` | Stored as JSON string |
| `policy_decision` | String | `policy.get("action")` | One of: allow, allow_with_redaction, require_approval, block |
| `assigned_agent` | String | `", ".join(agents_invoked)` | Comma-separated agent names |
| `resolution` | String | `audit["status"]` | Outcome: succeeded, blocked, needs_approval, replayed |
| `confidence` | Float | `policy.get("confidence_score")` | 0.85 in current config |
| `redacted` | Boolean | `policy.get("pii_detected")` | True if PII was detected and redacted |
| `approved` | Boolean | Default `False`; updated to True/False by `_update_postgres_approval()` when `/approve/{audit_id}` is called | Updated by approval flow |
| `summary` | Text | LLM summary or "unavailable" or None | Written after SummaryAgent runs |
| `created_at` | DateTime(timezone=True) | `datetime.now(timezone.utc)` at insert | PostgreSQL-side timestamp |

### Audit record fields — In build_audit_record() but not in DB columns (Designed)

These fields exist in the dict returned by `build_audit_record()` but are not stored as dedicated columns in the current PostgreSQL schema:

| Field | Location | Notes |
|---|---|---|
| `audit_id` | Dict key | Used as `request_id` in DB; also the `id` UUID |
| `timestamp_utc` | Dict key | The `created_at` column serves this purpose |
| `input_hash` | Dict key | SHA-256 of the full payload; not a DB column in current schema |
| `agents_invoked` | Dict key | Stored as comma-separated string in `assigned_agent`; list structure lost |
| `policy` | Dict key | Full policy dict stored in memory for replay; not persisted as structured column |
| `latency_ms` | Dict key | Not stored as a DB column; not in application logs as structured field |

### Approval record fields — Implemented

| Field | Source | Storage |
|---|---|---|
| `approval_id` | `str(uuid.uuid4())` — collision-resistant UUID4 | JSONL ledger |
| `timestamp_utc` | `datetime.now(timezone.utc).isoformat()` | JSONL ledger |
| `audit_id` | From path parameter | JSONL ledger |
| `decision` | "approved" or "rejected" | JSONL ledger |
| `approved_by` | From request body | JSONL ledger |
| `reason` | From request body | JSONL ledger |
| `approved` column update | `_update_postgres_approval(audit_id, decision)` | PostgreSQL `ai_control_plane_audit` row |

The `approved` column in `ai_control_plane_audit` is now updated by `record_approval()` through `_update_postgres_approval()`. The JSONL ledger remains the append-only supplemental record; PostgreSQL is the primary queryable store for approval state.

### Audit lookup — Implemented

`find_audit_record()` in `app/governance/approvals.py` queries PostgreSQL first (by `request_id`) and falls back to JSONL scan only when the database is unavailable. The fallback path is documented in code as non-authoritative.

### Privacy control — Implemented

`hash_email()` in `app/governance/audit.py`:

```python
def hash_email(email: str) -> str:
    return hashlib.sha256(email.encode()).hexdigest()
```

This is called before `write_audit_record()` writes to the database. The `intake_text` JSON explicitly excludes the `requester_email` key:

```python
intake_text=json.dumps(
    {k: v for k, v in intake.items() if k != "requester_email"}
)
```

The result is that the `requester_email` field from `IntakeRequest` is never stored in recoverable form anywhere in the audit trail.

---

## 6. Governance Workflow

### Evidence collection per request

1. Request arrives at `POST /run`.
2. `Timer()` starts at the beginning of `/run`.
3. `evaluate_policy()` runs. If blocked or needs_approval:
   - `build_audit_record()` called with `agents=["policy_approval_required"]` or `["policy_block"]`
   - `write_audit_record()` writes to PostgreSQL
   - Response returned immediately
4. If allowed, `WorkflowEngine` runs. After completion:
   - `build_audit_record()` called with agent list and LLM summary
   - `write_audit_record()` writes to PostgreSQL

### Evidence collection for approvals

1. Human calls `POST /approve/{audit_id}` with decision, approver identity, and reason.
2. `find_audit_record()` queries PostgreSQL by `request_id`. Falls back to JSONL only if DB is unavailable.
3. `record_approval()` appends to `logs/approvals.jsonl` (supplemental ledger).
4. `_update_postgres_approval()` sets `approved = True/False` on the matching `ai_control_plane_audit` row.
5. Approval record returned in response body.

### Evidence collection for replay

1. Human calls `POST /replay/{audit_id}`.
2. `find_audit_record()` retrieves the original audit record.
3. `sanitized_payload` is extracted from the stored policy dict.
4. `WorkflowEngine` re-runs with the sanitized payload.
5. A new audit record is written with `status: "replayed"` and `policy["replayed_from_audit_id"]` set to the original `audit_id`.

This creates a traceable chain from original intake → approval → replay.

### Support for troubleshooting

Each audit record contains:
- The full policy evaluation result, including what PII was detected, what risk score was assigned, and what action was taken
- The list of agents that ran (or the policy-only path if blocked)
- The latency of the full request (in the in-memory dict; not persisted as a column)
- The LLM-generated summary of the intake, or "unavailable" if the LLM was unreachable

This allows reconstruction of what the system did and why for any recorded request.

---

## 7. Implementation Workflow

```bash
# Apply database migrations (creates ai_control_plane_audit and ai_control_plane_runs tables)
make migrate

# Verify the audit table exists (requires psql access)
psql analytics_demo -c "\d ai_control_plane_audit"

# Submit a request and observe the audit record
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{"title":"Test","description":"desc","requester_email":"user@example.com","department":"eng","system":"test","urgency":"low"}'

# The audit_id in the response can be used to retrieve or approve
```

---

## 8. Operational Metrics

| Metric | Column | Query pattern |
|---|---|---|
| Request volume by day | `created_at` | `GROUP BY DATE(created_at)` |
| Policy decision distribution | `policy_decision` | `GROUP BY policy_decision` |
| PII detection rate | `redacted` | `COUNT(*) WHERE redacted = true` |
| Approval rate | `approved` | `COUNT(*) WHERE approved = true` |
| Agent routing distribution | `assigned_agent` | `GROUP BY assigned_agent` |
| Confidence score distribution | `confidence` | `AVG(confidence)`, `MIN`, `MAX` |

The `approved` column defaults to `False` at insert. It is updated to `True` or `False` by `_update_postgres_approval()` when `POST /approve/{audit_id}` is called. The query `SELECT * FROM ai_control_plane_audit WHERE resolution = 'needs_approval' AND approved = false` returns requests that are pending approval.

---

## 9. Workplace Application

The audit log design reflects several principles applicable in production data governance contexts:

- **Write before returning.** Audit records for blocked and approval-gated requests are written before the response is returned. There is no window where a request is processed but not recorded.
- **Store the sanitized version, not the original.** The `sanitized_payload` stored in the policy dict (and retrievable for replay) is the PII-redacted version. The original PII-containing text is never persisted.
- **Hash PII-adjacent identifiers.** The requester email is hashed consistently, enabling cross-request correlation without storing a recoverable identifier.
- **Record what the policy decided and why.** The full policy evaluation output is included in the audit record, including which PII types were detected, what risk score was assigned, and what action was taken. This makes the audit record self-contained for review purposes.

---

## 10. Limitations

- `input_hash`, `latency_ms`, and `agents_invoked` as a structured list are not persisted as dedicated columns in the current PostgreSQL schema. They exist in the in-memory audit dict but are not queryable from the database.
- `input_hash`, `latency_ms`, and `agents_invoked` as a structured list are not persisted as dedicated columns in the current PostgreSQL schema. They exist in the in-memory audit dict but are not queryable from the database.
- The JSONL files (`approvals.jsonl`) are not suitable for high-volume concurrent writes. PostgreSQL is the primary queryable store; JSONL is a supplemental append-only ledger.
- If `_update_postgres_approval()` fails due to a DB error, the JSONL ledger records the approval but the PostgreSQL `approved` column is not updated. The failure is silently swallowed to preserve the JSONL write.
- There is no retention policy, rotation, or archival mechanism for either `audit.jsonl` or `approvals.jsonl`.
- Audit records do not include a `policy_version` field. If `policy_rules.json` changes, there is no way to determine which version of the rules was active when a historical record was written.

---

## 11. What This Does Not Claim

- The audit log is not certified for any regulatory compliance standard (SOC 2, HIPAA, GDPR). It demonstrates the logging pattern.
- The `approved` column does not reflect a complete approval workflow; it is a placeholder that defaults to False.
- The audit table does not include all fields needed for a full production audit trail (e.g., caller IP, session token, policy version, raw input before redaction). These are reference architecture extensions.
- No data retention or archival guarantee is made.
- The flat-file approval log (`approvals.jsonl`) is not suitable for production volume or concurrent access.

---

## 12. Extension Path

- **Move approvals to PostgreSQL:** Add an `approval_events` table (as described in `AUDIT.md` Phase 2 plan) and replace JSONL writes with SQLAlchemy inserts. The current JSONL ledger and PostgreSQL `approved` column update would both be replaced by a structured `approval_events` row.
- **Add `input_hash` and `latency_ms` as DB columns:** Extend the `AuditRecord` model with `input_hash: String` and `latency_ms: Integer` columns and populate them from the audit dict.
- **Add `policy_version` field:** Hash `policy_rules.json` at startup and store the hash as a `policy_version` column on every audit record.
- **Structured agent list:** Replace `assigned_agent` (comma-separated string) with a PostgreSQL ARRAY or a normalized `audit_agents` junction table.
- **Surface `_update_postgres_approval` failures:** Log a warning when the PostgreSQL approval update fails so the inconsistency between JSONL and DB state is observable.

---

## 13. Interview Talking Points

- **Why write the audit record before agents run for blocked and approval-gated requests?** If the record were written after the response, a crash or timeout between policy evaluation and the audit write could leave a request unrecorded. Writing first ensures every policy-gated outcome has evidence, regardless of what happens to the request after.
- **Why hash the email instead of simply omitting it?** Omitting it entirely loses the ability to correlate multiple requests from the same requester, which is useful for compliance review and anomaly detection. The hash preserves correlation while preventing reconstruction of the original email address.
- **What makes replay safe from a PII perspective?** The `sanitized_payload` stored in the policy dict at intake time is the redacted version. When `/replay/{audit_id}` runs, it extracts this sanitized payload, not the original intake. PII cannot enter the agent pipeline through replay because the original PII was never stored in the policy dict in recoverable form.
- **How is the approval flow persisted?** `record_approval()` writes to the JSONL supplemental ledger and calls `_update_postgres_approval()`, which issues a SQLAlchemy UPDATE setting `approved = True` or `False` on the `ai_control_plane_audit` row. `find_audit_record()` queries PostgreSQL by `request_id` as the primary lookup, with JSONL as the documented fallback. Both improvements were implemented in the hardening pass following the initial governance documentation.
- **What is missing from this audit record for a SOC 2 context?** Caller authentication (who made the API call), policy version at time of evaluation, retention period enforcement, and tamper-evidence (e.g., log signing). These are the next-tier additions after the current implementation.
