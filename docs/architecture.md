# Purple Agent — Architecture

## Overview

Purple Agent is an A2A-compatible benchmark endpoint built for AgentBeats / AgentX.  
It solves business tasks by running a 10-stage pipeline before making any LLM call.

---

## Request flow

```
AgentBeats benchmark
        │
        │  POST / (JSON-RPC 2.0, method=tasks/send)
        ▼
  FastAPI server  (src/server.py, port 9010)
        │
        ▼
  executor.handle_task()
        │
        ├─ 0. privacy_guard.check_privacy()
        │       keyword match on task_text → immediate refuse, zero cost
        │
        ├─ 1. TokenBudget()
        │       track chars consumed, cap at 10K
        │       get_model() → sonnet normally, haiku at >80% budget
        │
        ├─ 2. rl_loop.build_rl_primer()
        │       case_log.json → find similar past tasks → inject as system prefix
        │
        ├─ 3. session_context.get_context_prompt()
        │       Haiku-compressed history + recent 6 turns for this session_id
        │
        ├─ 4. FSMRunner(checkpoint=get_fsm_checkpoint())
        │       restore FSM state from previous turn (multi-turn continuity)
        │       10 process types: expense_approval, procurement, hr_offboarding,
        │       incident_response, invoice_reconciliation, customer_onboarding,
        │       compliance_audit, dispute_resolution, order_management, sla_breach
        │
        ├─ 5. policy_checker.evaluate_policy_rules()
        │       parse JSON rules → evaluate conditions deterministically
        │       zero LLM, zero DB — pure Python condition logic
        │       result: {passed, requiresApproval, escalationLevel, triggeredRules}
        │
        ├─ 6. mcp_bridge.discover_tools() + schema_adapter.resilient_tool_call()
        │       load tools for session
        │       on_tool_call wraps every call with fuzzy-column retry
        │
        ├─ 7. brainos_client.run_task()  [PRIMARY]
        │       POST BrainOS copilot SSE — streams tool_call events
        │       ──── on BrainOSUnavailableError ────────────────────────────────
        │       fallback_solver.solve_with_claude()  [FALLBACK]
        │           Anthropic SDK messages.create() loop, up to 20 iterations
        │           model + max_tokens from TokenBudget
        │
        ├─ 8. session_context.maybe_compress_async()
        │       if > 20 turns: build messages → claude-haiku → 200-word summary
        │       summary stored in ctx.compressed_summary for next turn
        │       graceful fallback to inline concat if Anthropic unavailable
        │
        ├─ 9. rl_loop.record_outcome()
        │       quality = answer_length(0.35) + tool_count(0.35) + policy(0.30)
        │       append to case_log.json (max 200 entries, FIFO eviction)
        │
        └─ 10. token_budget.format_competition_answer()
                append process type, policy status, quality score, duration
```

---

## Components

### `src/server.py`
FastAPI application:
- `GET /health` — liveness probe
- `GET /.well-known/agent-card.json` — agent metadata
- `POST /` — A2A handler, JSON-RPC 2.0

### `src/executor.py`
10-stage pipeline. All stages are wired sequentially for maximum context accumulation.

### `src/policy_checker.py`
**Differentiator #1 — deterministic policy enforcement.**  
Evaluates structured JSON rules without LLM or DB:
```json
{
  "rules": [{
    "id": "EXPENSE_LIMIT",
    "condition": "amount > 5000",
    "action": "require_approval",
    "level": "manager"
  }],
  "context": { "amount": 7200 }
}
```
Supports: `>`, `<`, `>=`, `<=`, `==`, `!=`, `===`, `!==`, `&&`, `||`, `!field`.

### `src/memory_compressor.py`
**Differentiator #2 — context gets smarter, not bigger.**  
When session history exceeds 8K tokens:
- Keeps system message + last 6 turns
- Summarizes middle turns with claude-haiku (max 200 words)
- Injects summary as `[Earlier conversation summary]` system message
- Graceful no-op if Anthropic unavailable

### `src/structured_output.py`
**Differentiator #3 — answer format discipline.**  
- `format_final_answer()` auto-detects ranked/list tasks → enforces `["Item1", "Item2"]`
- Strips markdown noise (bullets, numbering) → clean bracket format
- `build_policy_section()` formats policy result for system prompt injection

### `src/rl_loop.py`
Lightweight RL loop without a DB:
- Outcomes stored in `case_log.json` (max 200, FIFO)
- Quality formula: `0.35 * answer_score + 0.35 * tool_score + 0.30 * policy_score`
- `build_rl_primer(task)` — keyword-matches past cases, injects top-3 as examples

### `src/session_context.py`
Multi-turn conversation memory + FSM state persistence:
- `add_turn()` — append user/assistant turns
- `maybe_compress_async()` — Haiku summary when > 20 turns
- `save_fsm_checkpoint()` / `get_fsm_checkpoint()` — persist FSM state across A2A turns
- `get_schema_cache()` — column correction cache per session
- Sessions evicted after 1 hour idle

### `src/fsm_runner.py`
Process state machine for business workflows:
```
DECOMPOSE → ASSESS → POLICY_CHECK → APPROVAL_GATE → EXECUTE → COMPLETE
```
10 process types auto-detected from task keywords.  
FSM state persists across multi-turn A2A calls via `FSMCheckpoint`.

### `src/schema_adapter.py`
Schema drift resilience — handles column name mismatches in tool responses:
- `KNOWN_COLUMN_ALIASES` — 10 canonical columns → known variant names
- `fuzzy_match_column()` — exact → alias → difflib sequence matcher → Levenshtein
- `resilient_tool_call()` — retry with corrected params on schema error

### `src/privacy_guard.py`
Fast privacy refusal at DECOMPOSE state — fires before any tool or DB call:
- Keyword list: passwords, SSN, credit cards, medical records, etc.
- Returns `{"refused": True, "message": "..."}` to cut the pipeline immediately

### `src/token_budget.py`
10K token budget per task:
- Tracks chars consumed across all pipeline stages
- `get_model()` → haiku at >80%, sonnet otherwise; per-FSM-state overrides
- `should_skip_llm` → True at 100% (avoids burning tokens on hopeless tasks)
- `format_competition_answer()` — appends judge-readable metadata footer

### `src/brainos_client.py`
BrainOS SSE streaming client:
- Streams task through `/api/copilot/chat`
- Handles `tool_call` events mid-stream → calls `on_tool_call()` → continues
- Raises `BrainOSUnavailableError` on timeout or 5xx → triggers fallback

### `src/fallback_solver.py`
Direct Claude SDK agentic loop (fallback only):
- `anthropic.AsyncAnthropic().messages.create()` with full tool list
- Up to `MAX_ITERATIONS=20` tool-call rounds
- Returns `(answer, tool_count)` for RL quality scoring

### `src/mcp_bridge.py`
HTTP client for the benchmark MCP endpoint:
- `discover_tools(endpoint, session_id)` — GET Anthropic-format tool list
- `call_tool(endpoint, name, params, session_id)` — POST tool invocation

---

## Deployment

- **Container**: Python 3.12 slim, non-root user `agentbeats`
- **Port**: 9010
- **Image**: `848269696611.dkr.ecr.us-east-1.amazonaws.com/agentbench-purple:latest`
- **ECS Service**: `agentbench-purple` in cluster `nexusbrain-training`
- **ALB**: Host header `purple.agentbench.usebrainos.com` → TG port 9010
- **TLS**: ACM cert on ALB HTTPS listener

---

## Competition strategy

The benchmark scores agents on:
1. **Exact match** — bracket format `["A", "B"]` is required, free text fails
2. **Policy adherence** — tasks with `policy_doc` must respect the rules
3. **Tool efficiency** — fewer tool calls = higher quality score
4. **Multi-turn** — `session_id` reuse means history must be maintained correctly

Purple Agent addresses all four with its pipeline stages 5, 3/8, 9, and 4 respectively.
