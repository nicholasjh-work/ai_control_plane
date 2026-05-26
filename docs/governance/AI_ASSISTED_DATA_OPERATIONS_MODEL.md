# AI-Assisted Data Operations Model

This document defines how AI assistance is applied to data operations tasks within `ai_control_plane`, what boundaries govern AI involvement, and how the system behaves when AI components fail or are unavailable.

---

## 1. Purpose

To specify the scope of AI assistance in operational workflows, define what tasks AI is permitted to perform autonomously versus what must remain human-owned, and establish safe operating boundaries including fallback behavior when LLM providers are unavailable.

---

## 2. Business Use Case

Data operations teams handle a continuous stream of structured requests: ticket routing, issue classification, response drafting, compliance review flagging, and operational reporting. AI assistance can accelerate triage and reduce manual routing overhead, but only if the assistance is bounded, auditable, and safe to fail.

This model applies when an AI-assisted pipeline receives structured intake (a support ticket, a data access request, an incident report) and must produce a classified, routed, and potentially summarized output without accessing or mutating underlying data systems directly.

---

## 3. Operating Model

AI assistance in this service is scoped to three functions:

### What AI is permitted to do (Implemented)

| Task | Agent | Method |
|---|---|---|
| Routing team classification | `ClassifierAgent` | LLM call with constrained output (team name only, from a fixed list); falls back to keyword match if LLM unavailable |
| Ticket summarization | `SummaryAgent` | LLM call requesting one-sentence summary, 20 words or fewer; falls back to "unavailable" if LLM unavailable |
| Priority assignment | `ClassifierAgent` | Rule-based mapping from `urgency` field: `critical` → P0, `high` → P1, else P2 (no LLM) |
| Suggested actions | `ResolverAgent` | Deterministic mapping from priority code to a fixed action list (no LLM) |
| Draft response generation | `ResolverAgent` | Returns a fixed acknowledgment string; not LLM-generated in the current implementation |

### What must remain human-owned (Implemented controls)

| Task | Enforcement |
|---|---|
| Approving PII-containing requests | `POST /approve/{audit_id}` requires a human caller with `approved_by` identity and reason; system does not auto-approve |
| Replay of approved requests | `POST /replay/{audit_id}` is a separate human-initiated step; the system does not auto-replay after approval |
| Database writes | No agent writes to a database directly; agents only produce structured output returned to the caller |
| SQL execution | The SQL safety layer validates queries but does not execute them; execution is not part of this service |

### What is human-owned by design (not yet enforced in code)

- Escalation resolution: `ResolverAgent` sets an `escalation.required` flag but takes no escalation action
- Ticket closure: the service produces suggested actions but does not close, update, or acknowledge tickets in external systems
- Policy rule changes: `policy_rules.json` changes require human authorship and a service restart

---

## 4. Architecture

```
POST /run
    │
    ├─ IntakeRequest validation (Pydantic)
    │
    ├─ evaluate_policy()                      — deterministic, no LLM
    │       ├─ PII scan (regex)
    │       ├─ Risk scoring
    │       └─ Routing team assignment (keyword match)
    │
    ├─ [if allowed] WorkflowEngine.run()
    │       ├─ ClassifierAgent.run()
    │       │       ├─ Rule-based category and priority
    │       │       └─ LLM call for routing refinement (with fallback)
    │       ├─ ResolverAgent.run()
    │       │       └─ Deterministic action list and draft response
    │       └─ SummaryAgent.run()
    │               └─ LLM call for one-sentence summary (with fallback)
    │
    ├─ write_audit_record()                   — PostgreSQL
    │
    └─ DecisionOutput (validated Pydantic response)
```

The policy layer runs entirely without LLM involvement. Only `ClassifierAgent` and `SummaryAgent` make LLM calls, and both have fallback behavior. `ResolverAgent` is deterministic.

---

## 5. Control Design

### Safe operating boundaries

- **LLM output is constrained at the prompt level.** `ClassifierAgent` requests a team name from a fixed list. Outputs not in the list are rejected and replaced with the fallback team.
- **LLM output is not executed.** LLM-produced text is returned as structured output fields (`routing_team`, `summary`) in the response. No LLM output is parsed as code or used as a database query.
- **Policy runs before agents.** Agents never see unredacted PII; the sanitized payload (with PII replaced by redaction tokens) is what enters the agent pipeline.
- **Agent list is configured.** `app/config/policy_rules.json` defines `allowed_agents`; the current authorized set is `["ClassifierAgent", "ResolverAgent", "SummaryAgent"]`.

### Failure behavior

| Failure mode | System behavior |
|---|---|
| LLM provider timeout | `LLMUnavailableError` raised; agent returns deterministic fallback; request completes normally |
| LLM provider returns unexpected output | Output validation rejects non-list routing teams; fallback applied |
| LLM provider HTTP error | Caught as `LLMUnavailableError`; fallback applied; no exception propagates to caller |
| PostgreSQL unavailable | `write_audit_record()` will raise at the SQLAlchemy layer; no fallback write path exists in the current implementation |
| Pydantic validation failure on intake | FastAPI returns HTTP 422 before any processing begins |
| Pydantic validation failure on response | Would raise a `ValidationError`; current implementation enforces `DecisionOutput` on the `/run` return |

### Fallback behavior when LLM is unavailable

`ClassifierAgent` uses `LLMUnavailableError` to fall back to the `routing_team` value already assigned by the keyword-matching policy layer. This means routing degrades gracefully to deterministic keyword matching when LLM routing is unavailable.

`SummaryAgent` returns `{"summary": "unavailable"}` on any `LLMUnavailableError`. The `summary` field in `DecisionOutput` will contain the string `"unavailable"`, which callers can detect and handle.

The LLM client configuration:

```python
# app/llm/client.py
self.provider = os.getenv("LLM_PROVIDER", "lmstudio")
self.base_url = os.getenv("LLM_BASE_URL", "http://localhost:1234/v1")
```

Provider is selected by environment variable. The default is `lmstudio` (local LM Studio instance). OpenAI is supported by setting `LLM_PROVIDER=openai`.

---

## 6. Governance Workflow

1. Request arrives at `POST /run`.
2. `evaluate_policy()` scans for PII, assigns risk score, and determines action.
3. If `action == "require_approval"` or `"block"`: audit record written, response returned immediately; agents do not run.
4. If `action == "allow"` or `"allow_with_redaction"`: sanitized payload passed to `WorkflowEngine`.
5. Each agent runs in sequence; LLM calls are made with fallback.
6. Audit record written to PostgreSQL with full policy snapshot, agent list, latency, and status.
7. `DecisionOutput` returned to caller.

For PII-gated requests:
1. Human reviews the `needs_approval` response, including the `audit_id`.
2. Human calls `POST /approve/{audit_id}` with `decision`, `approved_by`, and `reason`.
3. Human calls `POST /replay/{audit_id}` to re-run the workflow.
4. Replay uses the stored sanitized payload; a new audit record is written with `status: replayed`.

---

## 7. Implementation Workflow

```bash
# Install dependencies
make install

# Start the service
make run

# Verify health
curl http://localhost:8000/health

# Submit a clean intake request
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{"title":"Invoice not received","description":"March invoice missing","requester_email":"user@example.com","department":"finance","system":"billing","urgency":"high"}'

# Run all unit tests
make test

# Run the eval harness (server must be running)
make eval
```

---

## 8. Operational Metrics

| Metric | How to derive |
|---|---|
| LLM availability rate | Compare audit records where `summary != "unavailable"` vs total |
| Policy decision distribution | Count `policy_decision` values in `ai_control_plane_audit` |
| Routing accuracy | Compare `routing_team` in audit records against eval harness expected values |
| Fallback rate by agent | Not currently a structured field; derivable from summary field content |
| Request latency | Not yet stored as a structured column; available in application logs at the point of `write_audit_record` |

The eval harness provides the most complete operational view: 30 cases across routing, PII, SQL, edge, and fallback categories with per-tag pass rates written to `eval/results/latest.json`.

---

## 9. Workplace Application

This model is applicable wherever AI is introduced into an existing operational workflow alongside humans. The key design decisions relevant to a real operational context:

- **LLM calls are isolated to classification and summarization.** Routing, priority assignment, and action lists are either deterministic or bounded. This limits blast radius if LLM behavior degrades.
- **The fallback chain is observable.** If a request arrives with `summary: "unavailable"`, the operator knows the LLM was unreachable during that request. If routing unexpectedly hits "general", the operator can check whether the LLM returned an out-of-list value.
- **Policy evaluation is independent of LLM availability.** PII detection, risk scoring, and approval gating are deterministic and do not require the LLM to be running. These controls remain active during LLM outages.

---

## 10. Limitations

- `ResolverAgent` returns a fixed action list and a fixed draft response string regardless of request content. LLM-generated resolution is a proposed extension, not a current implementation.
- The LLM client supports LM Studio and OpenAI. Anthropic is not wired in the current implementation despite being mentioned in `AUDIT.md` as a planned extension.
- LLM calls are synchronous within the request path. If the LLM provider is slow, it increases the response latency of `/run` directly. No async dispatch or timeout-before-fallback is implemented beyond the `httpx` 5-second timeout.
- There is no retry logic for LLM calls. A single timeout immediately triggers the fallback path.
- Draft response generation is a hardcoded string. It does not reflect the content of the intake request.

---

## 11. What This Does Not Claim

- AI agents do not take any action on external systems. All outputs are structured data returned to the API caller.
- The LLM does not have access to the audit database, the `policy_rules.json` file, or any internal system configuration.
- This service does not provide AI-assisted root cause analysis, anomaly detection, or predictive operations in the current implementation. These are reference architecture extensions.
- No LLM output is presented to end users without a structured intermediate layer (the `DecisionOutput` schema). Raw LLM text is not returned.
- The service is not deployed to a production environment.

---

## 12. Extension Path

- **LLM-generated draft responses:** `ResolverAgent` could call `LLMClient.complete()` with the ticket content to produce context-specific draft responses instead of the current fixed string.
- **Anthropic provider support:** Add an `elif self.provider == "anthropic"` branch in `app/llm/client.py` with the Anthropic SDK call pattern.
- **Async LLM dispatch:** Replace synchronous `httpx.post` in `LLMClient.complete()` with `httpx.AsyncClient` and run agents concurrently where ordering permits.
- **Retry with exponential backoff:** Add retry logic in `LLMClient.complete()` before triggering `LLMUnavailableError`.
- **Audit fallback write:** If PostgreSQL is unavailable, fall back to JSONL file write to preserve audit evidence.
- **Metadata drafting agent:** Add an agent that generates structured metadata for data catalog entries from intake descriptions.
- **Root cause support agent:** Add an agent that queries the semantic view allowlist for relevant historical patterns and returns suggested investigation paths.

---

## 13. Interview Talking Points

- **Why is `ResolverAgent` deterministic rather than LLM-driven?** Resolution action lists can be highly sensitive in an operational context. A deterministic mapping from priority to a vetted action set is safer than generating actions from an LLM that might suggest out-of-scope steps. LLM assistance is applied where it adds routing accuracy (ClassifierAgent) or human readability (SummaryAgent), not where it might propose actions.
- **How does the fallback chain preserve reliability?** Both LLM-calling agents (`ClassifierAgent`, `SummaryAgent`) are written to degrade gracefully. The policy layer is entirely deterministic. This means the service can be meaningfully operational even when the LLM provider is down, which matters in on-call scenarios.
- **What prevents LLM output from escaping the bounded output set?** `ClassifierAgent` validates the LLM-returned routing team against `_ROUTING_TEAMS` (loaded from `routing_rules.json`). Any value not in that list is discarded and replaced with the fallback team. This is a simple but effective guardrail against hallucinated routing targets.
- **How would you extend this to support Anthropic?** Add a provider branch in `LLMClient.__init__()` and `complete()` using the Anthropic Python SDK's `client.messages.create()` pattern. The `LLM_PROVIDER` environment variable already controls dispatch; adding `elif self.provider == "anthropic"` is the only code change required.
