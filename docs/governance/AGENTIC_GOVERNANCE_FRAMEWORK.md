# Agentic Governance Framework

This document defines how AI agents and LLM-assisted workflows are governed within the `ai_control_plane` service. It distinguishes clearly between controls that are implemented in the current codebase and those that represent reference architecture or proposed extensions.

---

## 1. Purpose

This framework establishes the governance model for AI agent pipelines operating on structured intake data. The goal is to ensure that any AI-assisted action taken on a user-submitted request is traceable, policy-bounded, and subject to human oversight at defined risk thresholds. The framework applies to the full request lifecycle: intake, policy evaluation, agent execution, and audit recording.

---

## 2. Business Use Case

Enterprise data and operations teams increasingly use LLM-assisted pipelines to triage, classify, and route support tickets, data requests, and operational workflows. Without governance controls, these pipelines can silently expose PII, route sensitive requests without review, or take actions that cannot be reconstructed after the fact.

This framework addresses three concrete risks:
- Uncontrolled PII propagation into agent context
- Agent actions that exceed authorized scope
- Lack of audit evidence for compliance or incident review

The governance model targets environments where AI assists human decision-making but does not replace it for high-risk outcomes.

---

## 3. Operating Model

The service operates as a request-gated pipeline. Every intake request passes through policy evaluation before agents are invoked. The operating model has three tiers:

**Tier 1 — Allowed:** Request contains no PII or blocked content. Agents run, outputs are structured, audit record is written.

**Tier 2 — Requires Approval:** Request contains PII (email address or SSN detected by regex). Agents do not run. Request is held pending human approval. Audit record is written immediately with `status: needs_approval`.

**Tier 3 — Blocked:** Request contains content matching blocked keyword rules. Agents do not run. Audit record is written with `status: blocked`. No further processing.

After approval, a human operator calls `/approve/{audit_id}` and then `/replay/{audit_id}` to re-run the workflow using the stored sanitized payload.

---

## 4. Architecture

The implemented architecture consists of the following layers, all in `app/`:

```
IntakeRequest (Pydantic validated)
    ↓
evaluate_policy()           — app/governance/policy.py
    ↓ (if allowed)
WorkflowEngine              — app/orchestration/engine.py
    ├── ClassifierAgent     — app/agents/classifier_agent.py
    ├── ResolverAgent       — app/agents/resolver_agent.py
    └── SummaryAgent        — app/agents/summary_agent.py
    ↓
write_audit_record()        — app/governance/audit.py → PostgreSQL
    ↓
DecisionOutput (Pydantic validated response)
```

**SQL safety layer (separate surface):**
```
POST /v1/sql/validate
    ↓
validate_query()            — app/sql/safety.py (sqlglot parser)
    ↓
ValidationResult (allowed: bool, reason: str)
```

**Approval and replay:**
```
POST /approve/{audit_id}    — record_approval() → approvals.jsonl
POST /replay/{audit_id}     — re-runs WorkflowEngine from stored sanitized_payload
```

**Storage:** Audit records are written to a PostgreSQL table (`ai_control_plane_audit`) via SQLAlchemy. The `requester_email` field is never stored; it is replaced with a SHA-256 hash before the record is written. Approval records are written to a flat JSONL file (`approvals.jsonl`) and are not currently in PostgreSQL.

---

## 5. Control Design

### Implemented controls

| Control | Location | How it works |
|---|---|---|
| PII detection | `app/governance/policy.py` | Regex scan for email addresses and SSNs against `title` and `description` fields |
| PII redaction | `app/governance/policy.py` | Matched PII replaced with `[REDACTED_EMAIL]` or `[REDACTED_SSN]` in `sanitized_payload` |
| Blocked keyword enforcement | `app/governance/policy.py` | Configurable list in `app/config/policy_rules.json`; blocked requests never reach agents |
| Risk scoring | `app/governance/policy.py` | Two configured scores: `risk_score_clean: 0.25`, `risk_score_pii: 0.70`; block threshold: `0.90`, approval threshold: `0.70` |
| Approval gate | `app/main.py`, `app/governance/approvals.py` | PII-flagged requests return `status: needs_approval` before agents run |
| Audit logging | `app/governance/audit.py` | Every request outcome writes a record with UUID, UTC timestamp, SHA-256 input hash, agent list, policy snapshot, latency, status |
| Email hash | `app/governance/audit.py` | `requester_email` is SHA-256 hashed before storage; raw value excluded from `intake_text` |
| Agent allowlist | `app/config/policy_rules.json` | `allowed_agents` field lists authorized agents; not currently enforced at dispatch — design-level control |
| SQL SELECT-only enforcement | `app/sql/safety.py` | sqlglot parser rejects INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE, and multi-statement queries |
| Semantic view allowlist | `app/config/semantic_views.json` | Only four named views permitted in SQL queries; any other table reference is blocked |
| Schema enforcement on response | `app/schemas/decision.py`, `app/main.py` | `/run` returns a validated `DecisionOutput` Pydantic model |
| Data-driven policy rules | `app/config/policy_rules.json` | PII patterns, risk scores, thresholds, and agent allowlist are JSON-configurable without code changes |
| LLM fallback | `app/agents/classifier_agent.py`, `app/agents/summary_agent.py` | Both agents catch `LLMUnavailableError` and fall back to deterministic output; service remains available when LLM provider is unreachable |

### Designed but not yet implemented

- Agent allowlist enforcement at dispatch (currently list is validated in tests but not enforced at runtime dispatch)
- Automatic replay after approval (currently requires two separate API calls)
- Approval record persistence in PostgreSQL (currently JSONL flat file)
- Retention policy and JSONL rotation for `approvals.jsonl`

---

## 6. Governance Workflow

```
Request received at POST /run
    │
    ├─ Policy evaluation
    │       ├─ Blocked keyword? → Audit record (blocked) → Return blocked response
    │       ├─ PII detected, risk >= threshold? → Audit record (needs_approval) → Return
    │       └─ Allowed → Sanitized payload forwarded to WorkflowEngine
    │
    ├─ Agent pipeline (ClassifierAgent → ResolverAgent → SummaryAgent)
    │       └─ LLM calls with fallback on provider failure
    │
    ├─ Audit record written (PostgreSQL)
    │
    └─ DecisionOutput returned

Approval path:
    POST /approve/{audit_id} → approval recorded in approvals.jsonl
    POST /replay/{audit_id}  → re-runs pipeline with stored sanitized_payload
```

Human review is required before any PII-containing request proceeds through the agent pipeline. The sanitized (redacted) payload is stored in the audit record at intake, so replay always uses the PII-scrubbed version regardless of the original content.

---

## 7. Implementation Workflow

Development and operations follow these steps:

1. Install dependencies: `make install`
2. Run the service locally: `make run` (starts uvicorn on port 8000)
3. Run unit tests: `make test`
4. Run lint checks: `make lint`
5. Run the eval harness against a live server: `make eval`
6. Run regression comparison: `make eval-regression`
7. Apply database migrations: `make migrate`

CI pipeline (`.github/workflows/ci.yml`) runs `make lint` then `make test` on every push.

---

## 8. Operational Metrics

The following metrics are derivable from the audit log (`ai_control_plane_audit` table):

| Metric | Source |
|---|---|
| Request volume by status (allowed, blocked, needs_approval) | `policy_decision` column |
| PII detection rate | `redacted` column |
| Approval rate | `approved` column |
| Latency distribution | Captured in audit record `latency_ms`; not yet stored as a structured column |
| Agent routing distribution | `assigned_agent` column |
| Confidence score distribution | `confidence` column |

The eval harness (`eval/runner.py`) produces a per-run pass rate and per-tag breakdown written to `eval/results/latest.json`.

---

## 9. Workplace Application

This governance pattern applies to operational contexts where AI assists on structured intake workflows: support queue routing, compliance document classification, data access request review, and operational incident triage. The control pattern — evaluate policy before agents run, hold PII-containing requests for human review, record everything — is applicable wherever AI operates adjacent to personal data or sensitive operational decisions.

The SQL safety layer addresses a distinct but related concern: preventing AI-generated or user-supplied SQL from reaching a database without structural validation.

---

## 10. Limitations

- PII detection covers email addresses and SSNs only. Phone numbers, credit card numbers, passport numbers, and other PII types are not detected in the current implementation.
- The `blocked_keywords` list in `policy_rules.json` is empty by default. The block path requires configuration to be reachable.
- Risk scoring has two discrete values (0.25 and 0.70). There is no graduated scoring based on PII quantity, field sensitivity, or request context.
- The approval record (`approvals.jsonl`) uses a string-concatenated `approval_id` that can produce duplicates if two approvals are recorded within the same millisecond.
- The `agent allowlist` field in `policy_rules.json` is validated in tests but not enforced at runtime; an agent not on the list could be dispatched without a policy error.
- Audit persistence depends on PostgreSQL availability. No fallback write path exists if the database is unavailable.
- LLM calls are made synchronously within the request path. High LLM latency directly increases `/run` response time.

---

## 11. What This Does Not Claim

- This service is not deployed to a production environment. All functionality is local or containerized.
- The LLM client connects to LM Studio (local) or OpenAI by configuration. No model is embedded in this codebase.
- The policy engine does not learn or adapt. Rules are static JSON configuration.
- The agent pipeline does not take autonomous actions on external systems. Outputs are structured data returned to the caller.
- No SLA, availability guarantee, or production throughput claim is made.
- The audit table is not certified for regulatory compliance purposes; it is a demonstration of the audit logging pattern.

---

## 12. Extension Path

- **Additional PII patterns:** Add regex entries to `app/config/policy_rules.json` under `pii_patterns` and `pii_labels`.
- **Graduated risk scoring:** Replace the binary score with a weighted sum based on PII type, field location, and request context.
- **Auto-replay after approval:** `POST /approve/{audit_id}` could trigger automatic replay instead of requiring a separate `/replay` call.
- **Approval record persistence:** Move `approvals.jsonl` writes to a PostgreSQL `approval_events` table using the existing SQLAlchemy session.
- **Agent allowlist enforcement:** Add a runtime check in `WorkflowEngine` that validates each agent's name against `ALLOWED_AGENTS` before dispatch.
- **Streaming audit writes:** Replace synchronous SQLAlchemy writes with an async session or message queue to decouple audit latency from request latency.
- **Policy rule versioning:** Add a `policy_version` field to audit records so historical records can be associated with the rule configuration active at the time of evaluation.

---

## 13. Interview Talking Points

- **Why does policy run before agents?** If agents run first, PII may be included in LLM context before any redaction occurs. Running policy first ensures agents only ever see the sanitized payload.
- **What happens if the LLM provider goes down?** Both `ClassifierAgent` and `SummaryAgent` catch `LLMUnavailableError` and return deterministic fallback output. The service continues to function; routing falls back to the keyword-matched team from the policy layer.
- **How does the replay endpoint support governance?** The sanitized payload stored in the audit record at intake time is used for replay, not the original. This means a human approving and replaying a request never causes PII to enter the agent context.
- **Why SHA-256 the email instead of encrypting it?** The hash is one-way and consistent. It allows correlation of requests from the same requester across audit records without storing recoverable PII. It also satisfies the property that the audit log cannot be used to reconstruct original email addresses.
- **How are policy rules updated without a deployment?** `policy_rules.json` and `routing_rules.json` are loaded at startup from `app/config/`. Changing these files and restarting the service changes behavior without modifying Python code.
