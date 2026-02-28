# Purple Agent — Mini AI Worker for AgentX

**Live endpoint:** `https://purple.agentbench.usebrainos.com`

> **Purple Agent is a competition-focused distillation of the [BrainOS](https://usebrainos.com) AI Worker.**
>
> BrainOS runs AI Workers at enterprise scale. This is the same cognitive architecture —
> FSM process engine, deterministic policy enforcement, HITL safety gate, financial arithmetic,
> multi-turn memory — extracted into a standalone Python service for the AgentBeats benchmark.

---

## What is a BrainOS AI Worker?

A BrainOS AI Worker is a persistent, stateful business process agent that:
- Has its own identity, memory, and conversation history (per worker, not per session)
- Runs a cognitive planning loop (PRIME → EXECUTE → REFLECT) continuously
- Enforces policy rules deterministically before taking any action
- Gates irreversible mutations behind a HITL approval check
- Learns from every task outcome via a reinforcement loop

**Purple Agent is the mini version** — same architecture, zero infrastructure dependencies,
designed for the benchmark's A2A task format.

---

## Architecture: 3-Phase Cognitive Loop

```
POST / (A2A, tasks/send)
       │
       ▼
 MiniAIWorker.run()
       │
       ├── PHASE 1: PRIME
       │     ├─ Privacy guard (refuse before any cost)
       │     ├─ RL primer (learned patterns from past tasks)
       │     ├─ Session context (Haiku-compressed history)
       │     ├─ FSM restore (resume state from prior turn)
       │     ├─ Policy parse (deterministic JSON rules)
       │     └─ HITL gate check (build mutation block if APPROVAL_GATE)
       │
       ├── PHASE 2: EXECUTE
       │     ├─ BrainOS SSE → Claude SDK fallback (20-iter agentic loop)
       │     ├─ Schema-resilient tool calls (fuzzy column matching + retry)
       │     ├─ Paginated bulk fetch (cursor loop for 287+ record tasks)
       │     └─ Approval brief generation if gate fires
       │
       └── PHASE 3: REFLECT
             ├─ FSM checkpoint save (next turn resumes here)
             ├─ Async Haiku compression (session > 20 turns)
             ├─ RL outcome recording (quality → case_log.json)
             └─ Competition answer format (process + policy + quality + duration)
```

---

## 8-State Process FSM

Every task is classified into a process type and run through a structured state machine:

```
DECOMPOSE → ASSESS → COMPUTE → POLICY_CHECK → APPROVAL_GATE → MUTATE → SCHEDULE_NOTIFY → COMPLETE
                                                                  ↑
                                                     (error paths: ESCALATE, FAILED)
```

| State | What happens |
|-------|-------------|
| `DECOMPOSE` | Identify process type, entities, required data |
| `ASSESS` | Read-only tool calls — gather all data, no mutations |
| `COMPUTE` | Financial math — no tools, pure calculation (proration, amortization, variance) |
| `POLICY_CHECK` | Deterministic rule evaluation — zero LLM |
| `APPROVAL_GATE` | **Mutation tools BLOCKED** — agent must present approval request |
| `MUTATE` | All changes execute here — data collected, math done, approval received |
| `SCHEDULE_NOTIFY` | Send notifications, schedule follow-ups, write audit log |
| `COMPLETE` | Summary of all actions taken |

**15 built-in process types:** expense approval, procurement, HR offboarding, incident response,
invoice reconciliation, customer onboarding, compliance audit, dispute resolution, order management,
SLA breach, month-end close, AR collections, subscription migration, payroll, general.

---

## What Makes This Different

| Capability | Most agents | Purple Agent |
|------------|-------------|--------------|
| Policy enforcement | Prompt-stuffed | Deterministic rule evaluator — `&&`/`\|\|`/`!`/`>`/`<`, zero LLM |
| Irreversible actions | Call mutation tools immediately | APPROVAL_GATE blocks all mutation tools, forces approval summary |
| Financial math | LLM estimation | Integer-cents arithmetic — proration, amortization, SLA credits, sub-limits |
| Bulk data (287+ records) | First page only | Cursor-loop pagination, aggregates all pages |
| Structured output | Free text | Auto-generates PRD/post-mortem/approval-brief/sprint-plan |
| Multi-turn memory | None or full history | Haiku-compressed summaries, FSM state persists across turns |
| Schema errors | Crash | Fuzzy column matching (difflib + Levenshtein) + retry |
| Answer format | Prose | Auto-detects lists → `["Item1", "Item2"]` bracket format |
| Privacy | None | Keyword refusal before any tool/DB call |
| Token budget | Unlimited | 10K limit; Haiku at >80%; skip LLM at 100% |
| Learning | Stateless | Quality scoring → `case_log.json` → primer injected next task |

---

## Benchmark Task Coverage

### Tasks 1–10 (Single-system business processes)
All 10 task types are covered by the FSM process registry. Key patterns:

- **Irreversible action gating** (Tasks 1, 7, 9): `APPROVAL_GATE` state + `hitl_guard.py` blocks mutation tools
- **Multi-party approval routing** (Task 2): policy escalation levels (manager → VP → CFO → committee)
- **Sequenced execution** (Task 3): `ASSESS` before `MUTATE`, `SCHEDULE_NOTIFY` for ordered notifications
- **Partial approval with arithmetic** (Task 4): `financial_calculator.apply_sub_limit()` + rider logic
- **Duplicate/entity detection** (Tasks 5, 8): paginated fetch + `deduplicate()` by key
- **SLA credit calculation** (Task 6): `compute_sla_credit()` + `SCHEDULE_NOTIFY` for quiet-hours queuing
- **Escalation detection** (Tasks 2, 3, 8, 10): `FSMState.ESCALATE` + structured escalation reason
- **Boundary-case arithmetic** (Tasks 1, 4, 5, 6, 9): integer-cents math, 6-decimal variance precision

### Tasks 11–15 (Multi-system orchestration)
The `COMPUTE` state and `paginated_tools.py` unlock these:

- **Month-end close** (Task 11): paginated_fetch (287 txns), `recognize_revenue()`, `straight_line_depreciation()`, `apply_variance_check()`
- **Story→Jira→Sprint** (Task 12): `build_sprint_plan()` document template, dependency graph prompt
- **AR collections** (Task 13): `amortize_loan()` payment plan, `paginated_fetch` + `group_by()` for aging buckets
- **Incident RCA + rollback** (Task 14): `build_post_mortem()` template, APPROVAL_GATE for 2-person PCI approval
- **QBR multi-audience** (Task 15): `build_document("qbr_slide")` with stakeholder-variant content

### Tasks 16–20 (New domains)
- **Payroll** (Task 16): `prorated_for_period()`, `amortize_loan()`, process type `payroll`
- **Contract renewal** (Task 17): `build_document("contract_renewal")`, vendor risk assessment
- **Bug triage** (Task 18): `incident_response` process type, `ESCALATE` on security bugs
- **Budget planning** (Task 19): `apply_variance_check()` for growth thresholds, `APPROVAL_GATE`
- **GDPR/CCPA** (Task 20): `compliance_audit` process type, `SCHEDULE_NOTIFY` for deadline tracking

---

## A2A Request Format

```json
{
  "jsonrpc": "2.0",
  "method": "tasks/send",
  "params": {
    "id": "SESSION-001",
    "message": {
      "role": "user",
      "parts": [{ "text": "Approve expense EXP-042 for Alice — $4,200 travel" }]
    },
    "metadata": {
      "policy_doc": "{\"rules\":[{\"id\":\"R1\",\"condition\":\"amount > 5000\",\"action\":\"require_approval\",\"level\":\"manager\"}],\"context\":{\"amount\":4200}}",
      "tools_endpoint": "https://benchmark.usebrainos.com/mcp",
      "session_id": "SESSION-001"
    }
  }
}
```

## Response Format

```json
{
  "jsonrpc": "2.0",
  "result": {
    "id": "SESSION-001",
    "status": { "state": "completed" },
    "artifacts": [{
      "parts": [{
        "text": "Expense EXP-042 approved for Alice.\n\n---\nProcess: Expense Approval\nPolicy: ✅ PASSED\nQuality: 0.87\nDuration: 1340ms"
      }]
    }]
  }
}
```

---

## Source Layout

```
purple-agent/
├── main.py                       ← CLI entry (--host, --port, --card-url)
├── requirements.txt
├── Dockerfile
├── docs/
│   └── architecture.md           ← Component deep-dive
└── src/
    │
    │── COGNITIVE LOOP
    ├── worker_brain.py           ← MiniAIWorker: PRIME→EXECUTE→REFLECT
    ├── fsm_runner.py             ← 8-state FSM, 15 process types
    │
    │── SAFETY & POLICY
    ├── hitl_guard.py             ← Mutation blocking at APPROVAL_GATE (Gap 1)
    ├── privacy_guard.py          ← Keyword refusal before any tool call
    ├── policy_checker.py         ← Deterministic rule evaluation (zero LLM)
    │
    │── DATA & COMPUTATION
    ├── financial_calculator.py   ← Integer-cents arithmetic (Gap 4)
    ├── paginated_tools.py        ← Cursor-loop bulk fetching (Gap 2)
    ├── schema_adapter.py         ← Fuzzy column matching + retry
    │
    │── OUTPUT & MEMORY
    ├── document_generator.py     ← PRD/post-mortem/brief templates (Gap 3)
    ├── structured_output.py      ← Bracket format enforcement
    ├── memory_compressor.py      ← Async Haiku compression
    ├── session_context.py        ← Multi-turn history + FSM checkpoint
    ├── token_budget.py           ← 10K budget, model switching, judge format
    │
    │── LEARNING
    ├── rl_loop.py                ← Quality scoring → case_log.json → primer
    │
    │── INFRASTRUCTURE
    ├── server.py                 ← FastAPI: /health, /agent-card, POST /
    ├── brainos_client.py         ← BrainOS SSE streaming client
    ├── fallback_solver.py        ← Direct Claude SDK loop (20 iterations)
    ├── mcp_bridge.py             ← Tool discovery + tool calls
    └── config.py                 ← Env-var config
```

---

## Running Locally

```bash
pip install -r requirements.txt
cp .env.example .env
python main.py --host 0.0.0.0 --port 9010 --card-url http://localhost:9010
```

## Docker

```bash
docker build -t purple-agent .
docker run -p 9010:9010 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e BRAINOS_API_KEY=... \
  -e BRAINOS_ORG_ID=... \
  purple-agent
```

## Environment Variables

| Var | Purpose |
|-----|---------|
| `ANTHROPIC_API_KEY` | Claude fallback + Haiku compression |
| `BRAINOS_API_KEY` | BrainOS primary execution path |
| `BRAINOS_ORG_ID` | BrainOS workspace |
| `BRAINOS_API_URL` | BrainOS endpoint (default: platform.usebrainos.com) |
| `GREEN_AGENT_MCP_URL` | Default MCP tools endpoint |

---

## Endpoints

| What | URL | Method |
|------|-----|--------|
| Health | `/health` | GET |
| Agent card | `/.well-known/agent-card.json` | GET |
| A2A entry point | `/` | POST (JSON-RPC 2.0) |
