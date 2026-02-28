# Purple Agent — AgentX Competition Entry

**Live endpoint:** `https://purple.agentbench.usebrainos.com`

> A2A-compatible business process agent for the AgentBeats benchmark.  
> Built on BrainOS with a Claude fallback and a 10-stage execution pipeline.

---

## Endpoints

| What | URL | Method |
|------|-----|--------|
| Health check | `/health` | GET |
| Agent card | `/.well-known/agent-card.json` | GET |
| A2A entry point | `/` | POST (JSON-RPC 2.0) |

---

## What makes this different

| Feature | Most agents | Purple Agent |
|---------|-------------|--------------|
| Policy enforcement | LLM prompt-stuffed | Deterministic rule evaluator — zero LLM, zero DB |
| Multi-turn memory | None / full history | Haiku-compressed summaries, FSM state restored per turn |
| Answer format | Free text | Auto-detects lists → `["Item1", "Item2"]` bracket format |
| Schema errors | Crash | Fuzzy column matching + retry (difflib + alias map) |
| Privacy | None | Keyword refusal before any tool/DB calls |
| Token budget | Unlimited | 10K limit; Haiku at >80%; skip LLM at 100% |
| RL loop | None | Quality scoring → case log → primer injected next task |

---

## Execution pipeline (10 stages)

```
POST / (JSON-RPC 2.0, tasks/send)
  │
  ├─ 0. Privacy guard ──── keyword match → immediate refuse (no DB cost)
  ├─ 1. Token budget ───── 10K limit, Haiku/Sonnet switching, skip flag
  ├─ 2. RL primer ──────── case_log.json → learned patterns injected
  ├─ 3. Session context ── Haiku-compressed history + recent 6 turns
  ├─ 4. FSM restore ─────── resume DECOMPOSE→ASSESS→EXECUTE→COMPLETE
  ├─ 5. Policy check ────── deterministic JSON rule evaluator (&&, ||, !)
  ├─ 6. Tool discovery ──── MCP bridge, schema-resilient call wrapper
  ├─ 7. Execute ──────────── BrainOS SSE → Claude fallback (20-iter loop)
  ├─ 8. Haiku compress ──── async LLM summary when > 20 session turns
  ├─ 9. RL record ────────── quality score → case_log.json
  └─ 10. Format answer ───── competition judge format + policy/quality metadata
```

---

## Request format

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

## Response format

```json
{
  "jsonrpc": "2.0",
  "result": {
    "id": "SESSION-001",
    "status": { "state": "completed" },
    "artifacts": [{
      "parts": [{
        "text": "Expense EXP-042 approved.\n\n---\nProcess: Expense Approval\nPolicy: PASSED\nQuality: 0.85\nDuration: 1240ms"
      }]
    }]
  }
}
```

---

## Source layout

```
purple-agent/
├── main.py                   ← CLI entrypoint (--host, --port, --card-url)
├── requirements.txt
├── Dockerfile
├── docs/
│   └── architecture.md       ← component deep-dive
└── src/
    ├── server.py             ← FastAPI: /health, /.well-known/agent-card.json, POST /
    ├── executor.py           ← 10-stage pipeline orchestrator
    ├── brainos_client.py     ← BrainOS SSE streaming client
    ├── fallback_solver.py    ← direct Claude SDK agentic loop (20-iter)
    ├── mcp_bridge.py         ← tool discovery + tool calls
    ├── policy_checker.py     ← deterministic rule evaluator (zero LLM)
    ├── memory_compressor.py  ← async Haiku compression (max 200-word summary)
    ├── structured_output.py  ← bracket format enforcement + schema validation
    ├── rl_loop.py            ← quality scoring → case_log.json → primer
    ├── session_context.py    ← multi-turn history + FSM checkpoint persistence
    ├── fsm_runner.py         ← 10 process types, FSM state machine
    ├── schema_adapter.py     ← fuzzy column matching + resilient retry
    ├── privacy_guard.py      ← fast keyword refusal at entry
    ├── token_budget.py       ← 10K budget, model switching, competition formatter
    └── config.py             ← env-var config
```

---

## Running locally

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

## Required env vars

| Var | Purpose |
|-----|---------|
| `ANTHROPIC_API_KEY` | Claude fallback + Haiku compression |
| `BRAINOS_API_KEY` | BrainOS primary path |
| `BRAINOS_ORG_ID` | BrainOS workspace |
| `BRAINOS_API_URL` | BrainOS endpoint (default: platform.usebrainos.com) |
| `GREEN_AGENT_MCP_URL` | Default MCP tools endpoint |
