# Purple Agent — Business Process AI Worker

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Track](https://img.shields.io/badge/track-AgentBeats%20Business%20Process-purple)]()
[![Version](https://img.shields.io/badge/version-5.0.0%20Wave%2016-green)]()

**Live endpoint:** `https://purple.agentbench.usebrainos.com`

A production-grade AI worker for business process automation — distilled from the [BrainOS](https://usebrainos.com) platform. Built for the AgentBeats Sprint 1 competition (March 2–22, 2026).

---

## How It Works — The Mini AI Worker

```
                    ┌─────────────────────────────────────────────────┐
                    │              MINI AI WORKER                     │
                    │                                                 │
  A2A Request  ───► │  ┌──────────┐  ┌──────────┐  ┌─────────────┐  │
  (JSON-RPC 2.0)    │  │  PRIME   │─►│ EXECUTE  │─►│   REFLECT   │  │
                    │  └──────────┘  └──────────┘  └─────────────┘  │
                    │       │              │               │          │
                    │  Context rot    UCB1 bandit    RL feedback      │
                    │  pruning        selects          Bandit         │
                    │  RL patterns    strategy         learns         │
                    │  Dynamic tools  8-state FSM    Knowledge        │
                    │  MC sandbox     COMPUTE gate   extraction       │
                    └─────────────────────────────────────────────────┘
                                       │
                    ┌──────────────────▼──────────────────────────────┐
                    │              8-STATE FSM                        │
                    │                                                 │
                    │  DECOMPOSE → ASSESS → COMPUTE ─────────────►   │
                    │                         │ ▲                     │
                    │                   Math reflection               │
                    │                   gate (Haiku)                  │
                    │                         │                       │
                    │  POLICY_CHECK → APPROVAL_GATE → MUTATE →        │
                    │       SCHEDULE_NOTIFY → COMPLETE                │
                    │                                                 │
                    │  After COMPUTE: numeric MoA verification        │
                    │  After MUTATE:  WAL flush + mutation log        │
                    └─────────────────────────────────────────────────┘
```

**Three phases, one cognitive loop:**

| Phase | What it does |
|-------|-------------|
| **PRIME** | Loads pruned RL patterns, entity memory, knowledge base, dynamic tools |
| **EXECUTE** | UCB1 picks strategy → 8-state FSM → COMPUTE gate → Numeric MoA → Mutation verify |
| **REFLECT** | Records outcome to RL + bandit, extracts knowledge, updates case log |

---

## Key Innovations (Waves 1–15)

### 1. Dynamic FSM Synthesizer (Wave 13)
Unknown process types get a Haiku-synthesized FSM definition at runtime — states + per-state instructions customized to the specific process.

### 2. Dynamic Tool Factory (Wave 14 + Wave 16)
Two-phase universal gap detection covers any business computation a task might require:

**Phase 1 (regex, zero API cost):** 30+ static patterns across all business domains:
- Finance: NPV, IRR, bond pricing, WACC, compound interest, depreciation
- Monte Carlo simulation, Black-Scholes, VaR, Newton-Raphson
- HR/Payroll: overtime (FLSA), proration, benefits cost, FTE/attrition
- SLA/Operations: uptime %, SLA credits, penalty/liquidated damages
- Supply Chain: EOQ, safety stock, FIFO/LIFO/weighted-avg inventory
- Date/Time: business days, pro-rata periods, AR aging buckets
- Statistics: z-score, weighted average, linear regression
- Tax: VAT/GST (add/extract/reverse), withholding, gross-up, capital allowances
- Risk/Compliance: weighted risk score, AHP, Herfindahl concentration index
- AR/Collections: bad debt provision (ECL), DSO, collection efficiency
- Contract Math: escalation clauses, early termination fees

**Phase 2 (LLM-based, Haiku):** When Phase 1 finds nothing and the task is >= 100 chars, asks Haiku to identify what custom calculations the task requires. Max 2 LLM-detected gaps, 8s timeout — never blocks execution.

Synthesizes Python implementations via Haiku, validates in a restricted sandbox, and hot-loads them at runtime. Zero hardcoded tools — registry grows with every new computation type.

### 3. Monte Carlo + Numerical Methods (Wave 15)
Sandbox expanded with `random` + `statistics` modules, enabling synthesized tools for:
- Monte Carlo simulation (GBM paths, VaR estimation)
- Black-Scholes option pricing with Greeks
- Value at Risk / CVaR
- Newton-Raphson root finding (IRR, yield solving)

### 4. UCB1 Strategy Bandit (Wave 15)
Multi-armed bandit learns which execution strategy (FSM / Five-Phase / MoA) wins per process type. After the sprint, the bandit converges to the best strategy per problem class.

### 5. COMPUTE Math Reflection Gate (Wave 15)
After every COMPUTE state, a fast Haiku audit verifies the numeric answer before it gets written to the DB. Catches arithmetic errors before they become wrong mutations.

### 6. Numeric MoA — Dual top_p (Wave 15)
For tool-result tasks, runs two parallel Haiku interpretations (verify + challenge) then synthesizes the best. Different from Wave 10 MoA which only ran on reasoning-only tasks.

### 7. Context Rot Pruning (Wave 15)
Before PRIME injection, filters the RL case log for stale, low-quality, and repeated-failure entries. Keeps the prompt clean and focused.

### 8. Mutation Verifier (Wave 14)
After every write MCP call, immediately reads back the same entity. Forces SQLite WAL checkpoint so the scorer sees mutations. Also builds a structured mutation log for LLM judge scoring.

### 9. Compound Reinforcement Learning (Waves 8–15)
Every task outcome feeds back into 3 loops: RL case log, UCB1 bandit, and knowledge extraction. After 50 tasks, the agent performs measurably better than after task 1.

### 10. Schema Drift Recovery (Wave 6)
5-tier fuzzy matching corrects column name drift (Levenshtein + alias table + prefix matching). Empty-result paths also trigger correction.

---

## Competition Benchmark Alignment

Based on SOP-Bench, AgentArch, and MCPToolBench++ research:

| Benchmark Dimension | Our Coverage |
|--------------------|-------------|
| Tool selection accuracy | Pre-flight validation in mcp_bridge.py |
| Argument correctness | Decimal arithmetic, schema validation |
| SOP / policy adherence | 8-state FSM enforces READ-before-MUTATE |
| Branching logic | FSM state transitions + HITL gate |
| DB mutation persistence | WAL flush via mutation verifier read-backs |
| Novel process types | Dynamic FSM synthesizer |
| Novel computation | Dynamic tool factory: 30+ patterns + LLM phase-2 (Wave 16) |
| Self-correction | COMPUTE reflection gate + numeric MoA |
| Compound learning | UCB1 bandit + RL case log + knowledge base |

---

## Quick Start

```bash
git clone https://github.com/abhishec/purple-agent
cd purple-agent
pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...
export MCP_TOOLS_ENDPOINT=https://...

uvicorn src.server:app --host 0.0.0.0 --port 8000
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key |
| `MCP_TOOLS_ENDPOINT` | Yes | Competition MCP server URL |
| `AWS_ACCESS_KEY_ID` | No | S3 benchmark intelligence |
| `AWS_SECRET_ACCESS_KEY` | No | S3 benchmark intelligence |
| `AWS_S3_BUCKET` | No | S3 bucket for RL case log |

---

## A2A Protocol

Standard JSON-RPC 2.0 `tasks/send`:

```json
POST /
{
  "jsonrpc": "2.0",
  "method": "tasks/send",
  "id": "task-123",
  "params": {
    "id": "task-123",
    "message": {
      "role": "user",
      "parts": [{ "text": "Process the vendor invoice for Acme Corp..." }]
    }
  }
}
```

Health: `GET /health` | RL stats: `GET /rl/status` (case log, bandit, tool registry, FSM cache)

---

## Tech Stack

- **Runtime**: Python 3.11, FastAPI, uvicorn
- **LLM**: Anthropic Claude (Haiku for synthesis/classification, Sonnet for complex reasoning)
- **FSM Engine**: Custom 8-state machine with dynamic synthesis
- **Tool Bridge**: MCP HTTP bridge with pre-flight validation
- **Numerics**: Python `decimal.Decimal` + `random` + `statistics` in sandboxed tool execution
- **RL**: UCB1 bandit + case log + quality scoring + knowledge extraction
- **Storage**: S3 (RL case log), local JSON (tool registry, bandit state, entity memory)

---

## Project Structure

```
src/
  server.py            — FastAPI app, A2A endpoint, health + RL status
  worker_brain.py      — 3-phase cognitive loop (PRIME / EXECUTE / REFLECT)
  fsm_runner.py        — 8-state FSM engine
  dynamic_fsm.py       — Haiku-powered FSM synthesizer for novel types
  dynamic_tools.py     — Runtime tool factory (gap detection → synthesis → sandbox → registry)
  strategy_bandit.py   — UCB1 multi-armed bandit for strategy selection  [Wave 15]
  compute_verifier.py  — COMPUTE math reflection gate (Haiku audit)       [Wave 15]
  context_pruner.py    — Context rot pruning for RL case log              [Wave 15]
  mutation_verifier.py — Write tracking + WAL flush + LLM judge log
  schema_adapter.py    — 5-tier fuzzy schema drift recovery
  mcp_bridge.py        — MCP tool call bridge with validation
  claude_executor.py   — Primary Claude execution engine (agentic loop)
  self_moa.py          — Dual top_p MoA + numeric verification MoA        [Wave 15]
  rl_loop.py           — Reinforcement learning quality loop
  knowledge_extractor.py — Per-domain fact extraction and retrieval
  entity_extractor.py  — Cross-task entity tracking (vendors, amounts, people)
  self_reflection.py   — Answer quality scoring + improvement pass
```

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

Built with ❤️ on [BrainOS](https://usebrainos.com).
