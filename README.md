# Purple Agent — Mini AI Worker for AgentX

**Live endpoint:** `https://purple.agentbench.usebrainos.com`

> **Purple Agent is a competition-focused distillation of the [BrainOS](https://usebrainos.com) AI Worker.**
>
> BrainOS runs AI Workers at enterprise scale. This is the same cognitive architecture —
> FSM process engine, deterministic policy enforcement, HITL safety gate, cross-task memory,
> financial arithmetic, self-reflection — extracted into a standalone Python service.

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
       │     ├─ Training sync (S3 benchmark JSONL → RL seed, background)
       │     ├─ Smart process classifier (Haiku semantic routing)
       │     ├─ RL primer (case log patterns + benchmark intelligence)
       │     ├─ Knowledge base (facts extracted from past tasks)
       │     ├─ Entity memory (vendors/people/amounts seen before)
       │     ├─ Session context (Haiku-compressed history)
       │     ├─ FSM restore (resume state from prior turn)
       │     ├─ Policy parse (deterministic JSON rules)
       │     └─ HITL gate check (mutation block at APPROVAL_GATE)
       │
       ├── PHASE 2: EXECUTE
       │     ├─ BrainOS SSE → Claude SDK fallback (20-iter agentic loop)
       │     ├─ Schema-resilient tool calls (fuzzy column matching + retry)
       │     ├─ Recovery agent (synonym → decompose → Haiku → graceful degrade)
       │     ├─ Paginated bulk fetch (cursor loop for large datasets)
       │     ├─ Output validation (required fields check per process type)
       │     └─ Self-reflection (Haiku scores answer → improve if < 0.65)
       │
       └── PHASE 3: REFLECT
             ├─ FSM checkpoint save (next turn resumes here)
             ├─ Async Haiku compression (session > 20 turns)
             ├─ RL outcome recording (BrainOS quality formula)
             ├─ Knowledge extraction (Haiku → knowledge_base.json)
             └─ Entity persistence (entity_memory.json)
```

---

## What Makes It Different

| Capability | Most agents | This agent |
|---|---|---|
| **Process routing** | Keywords | Haiku semantic classifier |
| **Cross-task memory** | None | Knowledge base + entity memory compound across all tasks |
| **Tool failures** | Error out | 4-strategy auto-recovery (synonym → decompose → Haiku → degrade) |
| **Answer quality** | Return as-is | Self-reflection: scores own answer, auto-improves if < 0.65 |
| **Output completeness** | No check | Per-process required field validation (14 process types) |
| **Financial math** | Floats | Integer cents, 6-decimal variance precision |
| **Large datasets** | First page | Cursor-loop pagination (handles 287+ record tasks) |
| **Policy gates** | None | Deterministic policy checker |
| **Human approval** | None | HITL gate blocks mutation tools at APPROVAL_GATE state |
| **Training** | Cold start | S3 benchmark JSONL seeds RL on startup |
| **Learning** | None | RL quality loop + knowledge extraction after every task |

---

## 8-State Process FSM

Every task is classified and run through a structured state machine:

```
DECOMPOSE → ASSESS → COMPUTE → POLICY_CHECK → APPROVAL_GATE → MUTATE → SCHEDULE_NOTIFY → COMPLETE
                                                    │
                                              (policy escalation)
                                                    └─ ESCALATE
```

**14 built-in process types** — each with per-state instructions (data layer, not hardcoded):

| Process | Key states |
|---|---|
| `expense_approval` | COMPUTE amounts → POLICY_CHECK limits → APPROVAL_GATE → MUTATE |
| `invoice_reconciliation` | ASSESS 3-way match → COMPUTE variance → POLICY_CHECK → MUTATE |
| `procurement` | ASSESS vendor → COMPUTE TCO → APPROVAL_GATE (tiered) → MUTATE |
| `hr_offboarding` | ASSESS access → POLICY_CHECK → MUTATE (revoke all) → SCHEDULE_NOTIFY |
| `payroll` | COMPUTE gross/net/deductions → APPROVAL_GATE → MUTATE (ACH) |
| `compliance_audit` | COMPUTE control scores → APPROVAL_GATE → MUTATE (findings) |
| `subscription_migration` | 5-checkpoint APPROVAL_GATE for destructive downgrades |
| `ar_collections` | COMPUTE aging → POLICY_CHECK tier → MUTATE (notices/plans) |
| `month_end_close` | COMPUTE P&L → CFO APPROVAL_GATE → MUTATE (period lock) |
| `sla_breach` | COMPUTE credit → POLICY_CHECK → SCHEDULE_NOTIFY → ESCALATE |
| `incident_response` | COMPUTE impact → APPROVAL_GATE → MUTATE (mitigation) |
| `dispute_resolution` | ASSESS evidence → APPROVAL_GATE → MUTATE (credit/decline) |
| `order_management` | COMPUTE totals → MUTATE (reserve + charge) |
| `customer_onboarding` | MUTATE (provision) → SCHEDULE_NOTIFY (welcome) |

---

## Source Layout

```
src/
  worker_brain.py        ← MiniAIWorker: 3-phase cognitive loop (PRIME/EXECUTE/REFLECT)
  fsm_runner.py          ← 8-state FSM engine (generic — reads from process_definitions)
  process_definitions.py ← Per-process per-state instructions (DATA layer)

  # Intelligence
  smart_classifier.py    ← Haiku semantic process type detection
  knowledge_extractor.py ← Post-task insight extraction → knowledge_base.json
  entity_extractor.py    ← Regex entity persistence → entity_memory.json
  rl_loop.py             ← Quality scoring + case log primer
  memory_compressor.py   ← Haiku session compression (> 20 turns)
  session_context.py     ← Multi-turn FSM + conversation state

  # Safety & Policy
  hitl_guard.py          ← Mutation tool blocking at APPROVAL_GATE
  policy_checker.py      ← Deterministic policy rule evaluation
  privacy_guard.py       ← PII/sensitive data early refuse

  # Execution Quality
  self_reflection.py     ← Pre-return answer scoring + auto-improve
  output_validator.py    ← Per-process required field check
  recovery_agent.py      ← 4-strategy tool failure recovery
  schema_adapter.py      ← Fuzzy column name matching + retry

  # Precision
  financial_calculator.py← Integer-cents arithmetic (12 functions)
  paginated_tools.py     ← Cursor-loop bulk data fetch
  document_generator.py  ← Structured doc generation (9 types)
  token_budget.py        ← 10K token budget, Haiku at 80%, skip at 100%
  structured_output.py   ← Competition answer format

  # Training (Wave 6)
  training_loader.py     ← S3 JSONL download → RL seed
  report_analyzer.py     ← S3 benchmark reports → benchmark_intelligence.json

  # Infrastructure
  brainos_client.py      ← BrainOS SSE (primary executor)
  fallback_solver.py     ← Claude SDK (fallback, 20-iter agentic loop)
  mcp_bridge.py          ← MCP tool discovery + call
  config.py              ← Env vars
  server.py              ← FastAPI A2A server + /health /rl/status /training/*
```

---

## Quick Start

```bash
# 1. Set env vars (copy .env.example → .env)
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY at minimum

# 2. Run
docker build -t purple-agent .
docker run -p 9010:9010 --env-file .env purple-agent

# 3. Smoke test
python scripts/smoke_test.py

# 4. Test against live endpoint
python scripts/smoke_test.py --url https://purple.agentbench.usebrainos.com
```

---

## A2A Protocol

```bash
curl -X POST http://localhost:9010/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tasks/send",
    "params": {
      "id": "task-001",
      "message": {"parts": [{"text": "Process expense reimbursement of $350 for travel, John Smith, receipt attached."}]},
      "metadata": {
        "session_id": "session-abc",
        "policy_doc": "{\"rules\": [{\"field\": \"amount\", \"operator\": \"lte\", \"value\": 500}]}",
        "tools_endpoint": "http://benchmark-tools:9009"
      }
    }
  }'
```

---

## Monitoring

```bash
GET /health               # server status + training freshness
GET /rl/status            # case log stats, quality distribution, recent outcomes
GET /training/status      # seeded vs live cases, benchmark intelligence
POST /training/sync       # force refresh from S3
```
