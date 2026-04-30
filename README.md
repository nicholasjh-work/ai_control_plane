<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/nh-logo-dark.svg" />
    <source media="(prefers-color-scheme: light)" srcset="assets/nh-logo-light.svg" />
    <img src="assets/nh-logo-dark.svg" width="80" alt="NH" />
  </picture>
</p>

<h1 align="center">ai_control_plane</h1>

<p align="center">
  <strong>Governance-first AI orchestration with policy enforcement,
  auditable decisions, and SQL safety for enterprise data platforms.</strong>
</p>

<p align="center">
  <a href="https://ai-control-plane.pages.dev">
    <img src="https://img.shields.io/badge/Live_Demo-Cloudflare_Pages-F38020?style=for-the-badge&logo=cloudflare&logoColor=white" alt="Live Demo" />
  </a>
  &nbsp;
  <a href="https://github.com/nicholasjh-work/ai_control_plane">
    <img src="https://img.shields.io/badge/GitHub-nicholasjh--work-181717?style=for-the-badge&logo=github&logoColor=white" alt="GitHub" />
  </a>
  &nbsp;
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/License-MIT-22c55e?style=for-the-badge" alt="MIT License" />
  </a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?style=flat&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?style=flat&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/PostgreSQL-analytics__demo-4169E1?style=flat&logo=postgresql&logoColor=white" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/SQLAlchemy-2.0-red?style=flat" alt="SQLAlchemy" />
  <img src="https://img.shields.io/badge/sqlglot-30.x-8B5CF6?style=flat" alt="sqlglot" />
  <img src="https://img.shields.io/badge/Pydantic-v2-E92063?style=flat&logo=pydantic&logoColor=white" alt="Pydantic" />
  <img src="https://img.shields.io/badge/LM_Studio-local-10B981?style=flat" alt="LM Studio" />
  <img src="https://img.shields.io/badge/GitHub_Actions-CI-2088FF?style=flat&logo=githubactions&logoColor=white" alt="GitHub Actions" />
</p>

---

<table><tr><td>

Most AI prototype repos are prompt playgrounds. This one is a control plane: a FastAPI service that sits in front of agent workflows and enforces what they are allowed to do before, during, and after execution. Every request passes through a policy engine that scans for PII, assigns a risk score, redacts sensitive fields, and routes the request to the appropriate team — all driven by JSON config files with no hardcoded business logic. Requests that clear policy are handed to a three-agent pipeline (classifier, resolver, summarizer) backed by a provider-agnostic LLM client that falls back gracefully when the model is unavailable. Every outcome — allowed, redacted, approval-gated, or blocked — writes a structured audit record to PostgreSQL with a SHA-256–hashed email, a UUID audit ID, and full policy metadata. A sqlglot-based SQL safety layer enforces SELECT-only queries against an allowlisted set of semantic views, rejecting mutations before they reach the database. A 30-prompt eval harness with pass/fail scoring and baseline regression tracking completes the production readiness story. The intended audience is data platform engineers and ML platform teams who need governance primitives that can be audited, replayed, and extended without touching application code.

</td></tr></table>

---

## Architecture

```mermaid
flowchart TD
    Client -->|POST /run| FastAPI
    Client -->|POST /v1/sql/validate| SQLSafety
    Client -->|GET /demo| HTMLDemo

    subgraph FastAPI["FastAPI — app/main.py"]
        R1["/run"] --> PolicyEngine
        R2["/approve/:id"] --> Approvals
        R3["/replay/:id"] --> Replay
        R4["/v1/sql/validate"] --> SQLSafety
    end

    subgraph PolicyEngine["evaluate_policy() — policy_rules.json"]
        PE1["PII scan\nemail · SSN regex"] --> PE2["Risk scorer\n0.25 clean · 0.70 PII"]
        PE2 --> PE3{action}
        PE3 -->|risk ≥ 0.90| Block
        PE3 -->|risk ≥ 0.70| ApprovalGate["requires_approval"]
        PE3 -->|pii| Redact["allow_with_redaction"]
        PE3 -->|clean| Allow
    end

    PolicyEngine -->|sanitized payload + routing_team| WorkflowEngine

    subgraph WorkflowEngine["WorkflowEngine — orchestration/engine.py"]
        LLM["LLMClient\nLM Studio · OpenAI\nenv-switched · 5s timeout"]
        WE1["ClassifierAgent\nLLM → category · priority · routing_team"] --> WE2["ResolverAgent\npriority → actions · draft response"]
        WE2 --> WE3["SummaryAgent\nLLM → one-sentence summary"]
        WE1 --- LLM
        WE3 --- LLM
    end

    subgraph SQLSafety["SQL Safety — app/sql/safety.py"]
        SQ1["sqlglot parse"] --> SQ2["SELECT-only check"]
        SQ2 --> SQ3["Allowlist: semantic_views.json"]
        SQ3 --> SQ4["Subquery + UNION recursion"]
    end

    WorkflowEngine --> DecisionOutput["DecisionOutput schema\nPydantic-validated response"]
    DecisionOutput --> Client

    WorkflowEngine --> PostgresAudit

    subgraph PostgresAudit["PostgreSQL — analytics_demo"]
        PG1["ai_control_plane_audit\naudit_id · email_hash · policy_decision · summary"]
        PG2["ai_control_plane_runs\nphase · status · notes"]
    end

    subgraph QualityHarness["Eval Harness — eval/"]
        QH1["30 prompts\nrouting · pii · sql · edge · fallback"]
        QH2["runner.py — pass/fail scorer"]
        QH3["baseline.json — regression guard"]
        QH1 --> QH2 --> QH3
    end

    subgraph CI["GitHub Actions"]
        CI1["ruff + black"] --> CI2["pytest — 21 tests"]
    end

    HTMLDemo["HTML Demo\n/demo · /static/index.html"]
```

*Architecture as of Phase 6. LLM calls fall back gracefully when the model is unavailable.*

---

## Components

**Control Plane**

![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white)
![Pydantic Schemas](https://img.shields.io/badge/Pydantic_Schemas-E92063?style=flat)
![DecisionOutput](https://img.shields.io/badge/DecisionOutput-enforced-6366F1?style=flat)

**Governance**

![Policy Engine](https://img.shields.io/badge/Policy_Engine-policy__rules.json-F59E0B?style=flat)
![PII Redaction](https://img.shields.io/badge/PII_Redaction-email_·_SSN-EF4444?style=flat)
![Approval Gate](https://img.shields.io/badge/Approval_Gate-risk_≥_0.70-F97316?style=flat)

**SQL Safety**

![sqlglot](https://img.shields.io/badge/sqlglot-30.x-8B5CF6?style=flat)
![SELECT-only](https://img.shields.io/badge/SELECT--only-enforced-22C55E?style=flat)
![Semantic View Allowlist](https://img.shields.io/badge/Semantic_View_Allowlist-semantic__views.json-3B82F6?style=flat)

**Agents**

![ClassifierAgent](https://img.shields.io/badge/ClassifierAgent-LLM_routing-10B981?style=flat)
![ResolverAgent](https://img.shields.io/badge/ResolverAgent-actions_·_draft-10B981?style=flat)
![SummaryAgent](https://img.shields.io/badge/SummaryAgent-LLM_summary-10B981?style=flat)

**Persistence**

![PostgreSQL](https://img.shields.io/badge/PostgreSQL-analytics__demo-4169E1?style=flat&logo=postgresql&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-red?style=flat)
![Audit Log](https://img.shields.io/badge/Audit_Log-UUID_·_SHA--256-64748B?style=flat)
![Runs Table](https://img.shields.io/badge/Runs_Table-phase_·_status-64748B?style=flat)

**Eval**

![30-Prompt Harness](https://img.shields.io/badge/30--Prompt_Harness-routing_·_pii_·_sql_·_edge-6366F1?style=flat)
![Baseline Regression](https://img.shields.io/badge/Baseline_Regression-Δ_≤_5_points-6366F1?style=flat)
![Pass Rate](https://img.shields.io/badge/Pass_Rate-100%25-22C55E?style=flat)

---

## Quickstart

1. **Clone the repo**

   ```bash
   git clone https://github.com/nicholasjh-work/ai_control_plane.git
   cd ai_control_plane
   ```

2. **Install dependencies**

   ```bash
   make install
   ```

3. **Configure environment**

   ```bash
   cp .env.example .env
   # Edit .env — set DATABASE_URL, LLM_PROVIDER, LLM_BASE_URL, LLM_MODEL
   ```

4. **Create database tables**

   ```bash
   make migrate
   # Requires PostgreSQL running and DATABASE_URL set in .env
   # Tables created: ai_control_plane_audit, ai_control_plane_runs
   ```

5. **Start the server**

   ```bash
   make run
   # Starts uvicorn on http://localhost:8000
   # Open http://localhost:8000/demo for the interactive UI
   # Open http://localhost:8000/docs for the OpenAPI explorer
   ```

6. **Submit a ticket**

   ```bash
   curl -s -X POST http://localhost:8000/run \
     -H "Content-Type: application/json" \
     -d '{
       "title": "Invoice not received for March",
       "description": "I submitted my invoice on March 1st and have not received payment.",
       "requester_email": "contractor@company.com",
       "department": "finance",
       "system": "billing_portal",
       "urgency": "high"
     }' | python3 -m json.tool
   ```

7. **Validate a SQL query**

   ```bash
   curl -s -X POST http://localhost:8000/v1/sql/validate \
     -H "Content-Type: application/json" \
     -d '{"query": "SELECT * FROM v_ticket_summary"}' | python3 -m json.tool
   ```

8. **Run the eval harness** *(server must be running)*

   ```bash
   make eval
   # Runs 30 prompts, scores pass/fail, writes eval/results/latest.json
   # Exit 0 if pass_rate >= 90%

   make eval-regression
   # Fails if pass_rate drops more than 5 points from eval/baseline.json
   ```

9. **Run tests and lint**

   ```bash
   make test   # 21 unit tests, no live server or Postgres required
   make lint   # ruff + black --check
   ```

---

## LLM Configuration

Set `LLM_PROVIDER` in `.env` to switch models with no code changes:

| Provider | `.env` settings |
|---|---|
| LM Studio (local, default) | `LLM_PROVIDER=lmstudio`, `LLM_BASE_URL=http://localhost:1234/v1`, `LLM_MODEL=qwen2.5-coder-14b` |
| OpenAI | `LLM_PROVIDER=openai`, `OPENAI_API_KEY=sk-…`, `LLM_MODEL=gpt-4o-mini` |

All LLM calls have a 5-second timeout and fall back gracefully: routing defaults to the policy-level keyword result, summary returns `"unavailable"`. No request fails due to an unavailable model.

---

<p align="center">
  <img src="https://img.shields.io/badge/Built_by-Nicholas_Hidalgo-0f172a?style=for-the-badge" alt="Built by Nicholas Hidalgo" />
  &nbsp;
  <a href="https://github.com/nicholasjh-work/ai_control_plane">
    <img src="https://img.shields.io/badge/View_on-GitHub-181717?style=for-the-badge&logo=github&logoColor=white" alt="View on GitHub" />
  </a>
</p>
