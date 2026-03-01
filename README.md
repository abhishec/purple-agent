# Purple Agent — Business Process AI Worker

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Track](https://img.shields.io/badge/track-AgentBeats%20Business%20Process-purple)]()
[![Version](https://img.shields.io/badge/version-4.0.0%20Wave%2014-green)]()

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
                    │  Load context   8-state FSM    RL feedback     │
                    │  RL patterns    MCP tools      Knowledge       │
                    │  Knowledge      Mutation        extraction     │
                    │  Entity mem.    verify          Case log       │
                    └─────────────────────────────────────────────────┘
                                       │
                    ┌──────────────────▼──────────────────────────────┐
                    │              8-STATE FSM                        │
                    │                                                 │
                    │  DECOMPOSE → ASSESS → COMPUTE → POLICY_CHECK   │
                    │       → APPROVAL_GATE → MUTATE →               │
                    │       SCHEDULE_NOTIFY → COMPLETE                │
                    │                                                 │
                    │  Read phases: ASSESS only (no writes)           │
                    │  Write phase: MUTATE only (verified + logged)   │
                    └─────────────────────────────────────────────────┘
```

**Three phases, one cognitive loop:**

| Phase | What it does |
|-------|-------------|
| **PRIME** | Loads RL patterns, entity memory, knowledge base, dynamic tools |
| **EXECUTE** | Runs 8-state FSM with MCP tools, mutation verification, schema drift recovery |
| **REFLECT** | Records outcome to RL loop, extracts knowledge, updates case log |

---

## Key Innovations

### 1. Dynamic FSM Synthesizer
Novel process types get a Haiku-synthesized FSM definition at runtime — no hardcoded templates required. Unknown process types become known after first encounter.

### 2. Dynamic Tool Factory
Detects tool gaps from task text (NPV, IRR, bond pricing, WACC, depreciation...) and synthesizes Python implementations via Haiku, validates in a sandbox, and hot-loads them into the runtime. Zero hardcoded financial tools — they're all synthesized or seeded at startup.

### 3. Mutation Verifier (WAL Fix)
After every write MCP call, immediately reads back the same entity. This forces SQLite WAL checkpoint so the scorer sees mutations — not stale pre-write data. Also builds a structured mutation log for LLM judge scoring.

### 4. Compound Reinforcement Learning
Every task outcome feeds back. The RL case log primes future tasks with learned patterns. Quality scores drive dopamine/gaba signals. After 50 tasks, the agent performs measurably better than after task 1.

### 5. Schema Drift Recovery
5-tier fuzzy matching corrects column name drift (Levenshtein + alias table + prefix matching). Empty-result paths also trigger correction — not just hard errors.

### 6. Mixture of Agents (MoA)
Two parallel Haiku calls produce independent answers, then a synthesis call resolves conflicts — at 3× less cost than a single Sonnet call.

---

## Quick Start

```bash
git clone https://github.com/abhishec/purple-agent
cd purple-agent
pip install -r requirements.txt

# Set environment variables (see below)
export ANTHROPIC_API_KEY=sk-ant-...
export MCP_TOOLS_ENDPOINT=https://...
export AWS_S3_BUCKET=...

# Run
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
| `AWS_S3_REGION` | No | Default: `us-east-1` |

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

Health check: `GET /health` — returns FSM stats, RL metrics, dynamic tool registry size.

---

## Tech Stack

- **Runtime**: Python 3.11, FastAPI, uvicorn
- **LLM**: Anthropic Claude (Haiku for synthesis/classification, Sonnet for complex reasoning)
- **FSM Engine**: Custom 8-state machine with dynamic synthesis
- **Tool Bridge**: MCP HTTP bridge with pre-flight validation
- **Storage**: S3 (RL case log), local JSON (tool registry)
- **Arithmetic**: Python `decimal.Decimal` — no float rounding errors

---

## Project Structure

```
src/
  server.py          — FastAPI app, A2A endpoint, health
  worker_brain.py    — 3-phase cognitive loop (PRIME/EXECUTE/REFLECT)
  fsm_runner.py      — 8-state FSM engine
  dynamic_fsm.py     — Haiku-powered FSM synthesizer for novel types
  dynamic_tools.py   — Runtime tool factory (gap detection → synthesis → sandbox → registry)
  mutation_verifier.py — Write tracking + WAL flush + LLM judge log
  schema_adapter.py  — 5-tier fuzzy schema drift recovery
  mcp_bridge.py      — MCP tool call bridge with validation
  rl_engine.py       — Reinforcement learning quality loop
  knowledge_base.py  — Per-domain fact extraction and retrieval
  entity_memory.py   — Cross-task entity tracking (vendors, amounts, people)
  moa_engine.py      — Mixture of Agents synthesis
  finance_tools.py   — Finance context builder (tools come from registry)
```

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

Built with ❤️ on [BrainOS](https://usebrainos.com).
