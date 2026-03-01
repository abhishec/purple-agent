# Purple Agent — Mini AI Worker for AgentX

**Live endpoint:** `https://purple.agentbench.usebrainos.com`

> **Purple Agent is a competition-focused distillation of the [BrainOS](https://usebrainos.com) AI Worker.**
>
> BrainOS runs AI Workers at enterprise scale. This is the same cognitive architecture —
> FSM process engine, Mixture-of-Agents synthesis, deterministic policy enforcement,
> HITL safety gate, cross-task memory, self-reflection, RL quality loop —
> extracted into a standalone Python service with zero external infrastructure.

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
       │     ├─ Smart process classifier (Haiku semantic routing, no whitelist)
       │     ├─ RL primer (case log patterns + benchmark intelligence, PRIMED)
       │     ├─ Knowledge base (facts extracted from past tasks)
       │     ├─ Entity memory (vendors/people/amounts seen before)
       │     ├─ Session context (Haiku-compressed history)
       │     ├─ FSM restore (resume state from prior turn)
       │     ├─ Policy parse (deterministic JSON rules)
       │     └─ HITL gate check (mutation block at APPROVAL_GATE)
       │
       ├── PHASE 2: EXECUTE
       │     ├─ BrainOS SSE → Claude SDK fallback
       │     │     ├─ Complex tasks → Five-Phase Executor (PLAN→GATHER→SYNTHESIZE→ARTIFACT)
       │     │     └─ Simple tasks → 20-iter agentic loop (MAX_TOOL_CALLS=18 guard)
       │     ├─ Pre-flight tool validation (rejects non-existent tools before HTTP)
       │     ├─ Schema-resilient tool calls (5-tier fuzzy column matching + empty-result trigger)
       │     ├─ Recovery agent (dynamic difflib synonyms → decompose → Haiku → degrade)
       │     ├─ Paginated bulk fetch (cursor loop for large datasets)
       │     ├─ Output validation (required fields check per process type)
       │     ├─ Self-reflection (Haiku scores answer → improve if < 0.65)
       │     └─ MoA synthesis (dual top_p Haiku consensus on pure-reasoning tasks)
       │
       └── PHASE 3: REFLECT
             ├─ FSM checkpoint save (next turn resumes here)
             ├─ Async Haiku compression (session > 20 turns)
             ├─ RL outcome recording (BrainOS quality formula + domain tag)
             ├─ Knowledge extraction (Haiku + fast-path regex → knowledge_base.json)
             └─ Entity persistence (entity_memory.json)
```

---

## What Makes It Different

| Capability | Most agents | This agent |
|---|---|---|
| **Process routing** | Keywords | Haiku semantic classifier (no hardcoded whitelist) |
| **Complex tasks** | Single Claude call | Five-Phase Executor (PLAN→GATHER→SYNTHESIZE→ARTIFACT→INSIGHT) |
| **Answer synthesis** | Single top_p | MoA: dual top_p (0.85/0.99) Haiku consensus, +6% quality |
| **Cross-task memory** | None | Knowledge base + entity memory compound across all tasks |
| **Tool failures** | Error out | 4-strategy auto-recovery (dynamic difflib synonyms → decompose → Haiku → degrade) |
| **Schema drift** | Error on wrong column | 5-tier fuzzy matching + empty-result trigger + expanded alias table |
| **Hallucination** | Return bad tool call | Pre-flight validation rejects non-existent tools before network |
| **Answer quality** | Return as-is | Self-reflection: scores own answer, auto-improves if < 0.65 |
| **Output completeness** | No check | Per-process required field validation (14 process types) |
| **Token budget** | Uncontrolled | 10K cap, Haiku routing for simple tasks, 18-tool hard guard |
| **Financial math** | Floats | Integer cents, 6-decimal variance precision |
| **Large datasets** | First page | Cursor-loop pagination (handles 287+ record tasks) |
| **Policy gates** | None | Deterministic policy checker |
| **Human approval** | None | HITL gate blocks mutation tools at APPROVAL_GATE state |
| **Training** | Cold start | S3 benchmark JSONL seeds RL on startup, benchmark primer in PRIME |
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

**Short-circuit paths for efficiency** (Wave 10):
- Read-only queries: `DECOMPOSE → ASSESS → COMPLETE` (3 states, ~40% of tasks)
- General tasks: `DECOMPOSE → ASSESS → POLICY_CHECK → MUTATE → COMPLETE`
- Full process: all 8 states for complex approvals

**14 built-in process types** — each with per-state instructions (data layer, zero hardcoded tool names):

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

## Five-Phase Executor (Wave 10)

For complex multi-step tasks, replaces a single Claude call with a structured pipeline:

```
PLAN (Haiku, 200 tok)
  └─ Decompose task into 2-4 JSON subtasks with tool_needed flags

GATHER (tool calls, max 8)
  └─ Async tool calls for subtasks marked tool_needed=true

SYNTHESIZE (Sonnet, 1500 tok)
  └─ Comprehensive analysis from plan + gathered data

ARTIFACT (Haiku, 800 tok)
  └─ Format into clean structured deliverable (headers, tables, bullets)

INSIGHT (fire-and-forget)
  └─ extract_and_store → knowledge_base.json
```

Trigger heuristic: multi-step keywords, 3+ entities, analysis verbs, >80 chars.

---

## Mixture-of-Agents (MoA) Synthesis (Wave 10)

For pure-reasoning tasks (no tool calls needed), a dual top_p consensus pass
improves answer quality at near-zero cost:

```
Query ──┬── Haiku (top_p=0.85) ──┐
        └── Haiku (top_p=0.99) ──┴── Jaccard overlap check
                                         │
                                 overlap ≥ 0.70 → take longer answer
                                 overlap < 0.70 → Haiku synthesis call
```

3-lens mode (optional, for highly complex analytical tasks):
- Risk lens + Execution lens + Data-quality lens → pairwise consensus → Sonnet synthesis

---

## Source Layout

```
src/
  worker_brain.py          ← MiniAIWorker: 3-phase cognitive loop (PRIME/EXECUTE/REFLECT)
  server.py                ← FastAPI A2A server + /health /rl/status /training/*
  config.py                ← Env vars

  # FSM Engine
  fsm_runner.py            ← 8-state FSM (short-circuit paths for read-only/general tasks)
  process_definitions.py   ← Per-process per-state instructions (DATA layer, zero hardcoded tool names)

  # Advanced Execution (Wave 10)
  five_phase_executor.py   ← PLAN→GATHER→SYNTHESIZE→ARTIFACT→INSIGHT pipeline
  self_moa.py              ← Mixture-of-Agents: dual top_p consensus + 3-lens synthesis

  # Intelligence
  smart_classifier.py      ← Haiku semantic process type detection (no whitelist)
  knowledge_extractor.py   ← Post-task insight extraction → knowledge_base.json
  entity_extractor.py      ← Regex entity persistence → entity_memory.json
  rl_loop.py               ← Quality scoring + case log primer + structured memory
  memory_compressor.py     ← Haiku session compression (> 20 turns)
  session_context.py       ← Multi-turn FSM + conversation state

  # Safety & Policy
  hitl_guard.py            ← Mutation tool blocking at APPROVAL_GATE
  policy_checker.py        ← Deterministic policy rule evaluation
  privacy_guard.py         ← PII/sensitive data early refuse

  # Execution Quality
  self_reflection.py       ← Pre-return answer scoring + auto-improve
  output_validator.py      ← Per-process required field check
  recovery_agent.py        ← 4-strategy failure recovery (dynamic difflib synonyms)
  schema_adapter.py        ← 5-tier fuzzy column matching + empty-result trigger
  mcp_bridge.py            ← MCP tool discovery + pre-flight validation + call

  # Precision
  financial_calculator.py  ← Integer-cents arithmetic (12 functions)
  paginated_tools.py       ← Cursor-loop bulk data fetch
  document_generator.py    ← Structured doc generation (9 types)
  token_budget.py          ← 10K token budget, Haiku routing, 18-tool hard guard
  structured_output.py     ← Competition answer format

  # Training (Wave 6)
  training_loader.py       ← S3 JSONL download → RL seed
  report_analyzer.py       ← S3 benchmark reports → benchmark_intelligence.json

  # Primary Execution
  brainos_client.py        ← BrainOS SSE (primary executor)
  fallback_solver.py       ← Claude SDK fallback (20-iter loop, sentinel replaced with _synthesize_from_history)
```

---

## Competition Scoring Targets

| Dimension | Weight | Key mechanism |
|---|---|---|
| Functional Correctness | 30% | FSM state machine + output validator + five-phase structured execution |
| Drift Adaptation | 20% | 5-tier schema adapter (empty-result trigger + prefix match + alias table) |
| Token Efficiency | 12% | 10K budget + Haiku routing (fixed dead code) + 18-tool guard + short-circuit FSM |
| Query Efficiency | 12% | Pre-flight tool validation + read-only short-circuit (3 states vs 8) |
| Error Recovery | 8% | Dynamic difflib synonyms (unbounded vs 13 hardcoded) + 4-strategy recovery |
| Trajectory Efficiency | 10% | Five-phase PLAN phase decomposes upfront → fewer wasted tool calls |
| Hallucination Rate | 8% | Pre-flight validation rejects non-existent tools before any HTTP round-trip |

---

## Quick Start

```bash
# 1. Set env vars
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
GET /rl/status            # case log stats, quality distribution, knowledge base growth,
                          # entity memory stats, recent outcomes
GET /training/status      # seeded vs live cases, benchmark intelligence
POST /training/sync       # force refresh from S3
```

## Knowledge Growth Monitoring

```bash
# Watch knowledge base grow in real time
tail -f /data/knowledge_growth.log

# Check stats
curl http://localhost:9010/rl/status | jq .knowledge_base
# → { "total_entries": 47, "domains_covered": 8, "growth_rate": "3.2/hr", "last_extraction": "..." }
```
