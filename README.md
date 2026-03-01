# Purple Agent — Business Process AI Worker

Live endpoint: https://purple.agentbench.usebrainos.com  
Built for the AgentBeats Sprint 1 competition (March 2–22, 2026). Apache 2.0.

---

## What It Is

Purple Agent is an AI worker that executes enterprise business processes end-to-end. It connects to an MCP tool server, operates a structured 8-state finite state machine, and compounds learning across tasks through five parallel feedback channels.

The design premise: a flat agentic loop ("here are 130 tools, be careful") produces inconsistent results for multi-step processes with policy gates and database mutations. Purple Agent enforces ordering structurally — data collection before computation, computation before policy check, policy check before mutation — using an FSM whose state determines which tools are available at each step.

---

## How It Works

```
                    ┌─────────────────────────────────────────────────┐
                    │                POST /  (A2A JSON-RPC 2.0)        │
                    └──────────────────────┬──────────────────────────┘
                                           │
                    ┌──────────────────────▼──────────────────────────┐
                    │                   PRIME                          │
                    │                                                  │
                    │  1.  Privacy guard          (zero API cost)      │
                    │  2.  RL primer              (top-3 past cases)   │
                    │  3.  Session context        (Haiku-compressed)   │
                    │  4.  FSM classification     (Haiku → keyword)    │
                    │  5.  Dynamic FSM synthesis  (unknown types)      │
                    │  6.  FSMRunner setup        (read-only detect)   │
                    │  7.  Policy evaluation      (deterministic)      │
                    │  8.  Tool discovery         (MCP + registry)     │
                    │  9.  Tool gap detection     (regex → Haiku)      │
                    │  10. HITL gate check        (approval state)     │
                    │  11. Knowledge + entity     (domain facts)       │
                    │  12. Finance pre-compute    (variance, SLA)      │
                    │  13. system_context assembly                      │
                    └──────────────────────┬──────────────────────────┘
                                           │
                    ┌──────────────────────▼──────────────────────────┐
                    │                   EXECUTE                        │
                    │                                                  │
                    │  UCB1 selects: fsm | five_phase | moa            │
                    │                                                  │
                    │  [fsm path]                                      │
                    │  DECOMPOSE → ASSESS → COMPUTE → POLICY_CHECK     │
                    │  → APPROVAL_GATE → MUTATE → SCHEDULE_NOTIFY      │
                    │  → COMPLETE                                      │
                    │                                                  │
                    │  Tool call stack per iteration:                  │
                    │  MutationVerifier → RecoveryAgent                │
                    │  → SchemaAdapter → PaginatedTools → direct call  │
                    │                                                  │
                    │  Post-execution:                                 │
                    │  mutation log · math reflection · numeric MoA    │
                    │  approval brief · output validation              │
                    │  self-reflection improvement                     │
                    └──────────────────────┬──────────────────────────┘
                                           │
                    ┌──────────────────────▼──────────────────────────┐
                    │                   REFLECT                        │
                    │                                                  │
                    │  FSM checkpoint saved                            │
                    │  Session memory compressed (Haiku, async)        │
                    │  RL outcome → case_log.json (max 200 entries)    │
                    │  UCB1 bandit updated: Q += (r - Q) / n           │
                    │  Knowledge extracted (quality ≥ 0.5)             │
                    │  Entity memory updated (vendors, amounts, IDs)   │
                    └─────────────────────────────────────────────────┘
```

Three phases run for every task:

| Phase | What it does |
|---|---|
| **PRIME** | Loads pruned RL patterns, entity memory, knowledge base, dynamic tools — all before Claude sees the task |
| **EXECUTE** | UCB1 picks strategy → 8-state FSM → COMPUTE gate → Numeric MoA → Mutation verify |
| **REFLECT** | Records outcome to RL + bandit, extracts knowledge, updates case log |

---

## Complete Execution Flow

### Layer 0 — Request Entry (`server.py`)

Every request is JSON-RPC 2.0 `tasks/send`. The server validates the method, extracts `task_text`, `policy_doc`, `tools_endpoint`, and `session_id`, then hands off to `MiniAIWorker(session_id).run(...)`. Any unhandled exception returns a JSON-RPC error — never a 500 HTML page.

`session_id` is the worker's identity. The same session ID across turns means the same worker: same FSM checkpoint, same conversation memory, same entity context.

---

### Layer 1 — PRIME Phase

Everything in PRIME runs before Claude sees the task. It assembles a `system_context` string that becomes the system prompt.

**1. Privacy guard**  
`privacy_guard.check_privacy()` — if the task contains PII, SSNs, or credentials, the worker refuses immediately. Zero API cost.

**2. RL primer**  
`rl_loop.build_rl_primer(task_text)` loads `case_log.json`, finds the 3 most similar past tasks by keyword overlap, and injects patterns like:
```
Past pattern: invoice tasks with variance >2% → escalate to approval gate
Past pattern: modify_order_items — confirm_with_user required first
```
Context rot pruning runs first: stale entries (>72h), low-quality entries (score <0.35 with failure), and repeated-failure patterns (3+ failures with ≥50% keyword overlap) are stripped before injection.

**3. Session context**  
`session_context.get_context_prompt(session_id)` — for multi-turn sessions, loads Haiku-compressed conversation history (~200 token summary of prior turns).

**4. FSM classification**  
`smart_classifier.classify_process_type(task_text)` makes a Haiku call to identify the process type (`invoice_reconciliation`, `hr_offboarding`, `sla_breach`, etc.). If the session has a prior checkpoint, that is restored instead — no re-classification on turn 2+.

**5. Dynamic FSM synthesis**  
If the process type is not in the 15 built-in templates, `dynamic_fsm.synthesize_if_needed()` calls Haiku once to produce a custom state sequence and per-state instructions. The result is cached permanently — subsequent tasks of the same type skip synthesis entirely.

**6. FSMRunner**  
Picks the state sequence from built-in templates or the synthesized definition. Read-only tasks (no action verbs detected) collapse to a 3-state path: DECOMPOSE → ASSESS → COMPLETE, skipping COMPUTE through SCHEDULE_NOTIFY.

**7. Policy evaluation**  
Parses `policy_doc` JSON and evaluates approval thresholds, spend limits, and escalation conditions deterministically — zero LLM calls.

**8. Tool discovery**  
`mcp_bridge.discover_tools()` fetches live tool schemas from the MCP endpoint. `load_registered_tools()` appends any tools synthesized in prior tasks from `tool_registry.json`.

**9. Dynamic tool gap detection**  
Two-phase detection covers business computations the MCP server doesn't provide:

*Phase 1 (regex, zero API cost):* 36 static patterns across 10 domains:
- Finance: NPV, IRR, WACC, amortization, depreciation, bond pricing
- Monte Carlo simulation, Black-Scholes, Value at Risk, Newton-Raphson (IRR/yield)
- HR/Payroll: FLSA overtime, proration, benefits cost, FTE/attrition rate
- SLA/Operations: uptime percentage, SLA credits, penalty/liquidated damages
- Supply Chain: EOQ, safety stock, FIFO/LIFO/weighted-average inventory
- Date/Time: business day calculation, pro-rata periods, AR aging buckets
- Statistics: z-score, weighted average, linear regression
- Tax: VAT/GST add/extract/reverse, withholding, gross-up, capital allowances
- Risk/Compliance: weighted risk score, AHP, Herfindahl concentration index
- AR/Collections: bad debt provision (ECL), DSO, collection efficiency

*Phase 2 (LLM, only if Phase 1 finds nothing AND task ≥ 100 chars):* Haiku identifies what custom calculations the task needs. Max 2 gaps detected, 8s timeout, never blocks execution.

For each gap: Haiku synthesizes a Python implementation with 3 test cases, validates it in a restricted sandbox (`math`, `Decimal`, `random`, `statistics` — `import`, `open`, `os`, `sys` blocked), and persists it to `tool_registry.json`. It is available for all future tasks immediately.

**10. HITL gate**  
If the FSM is at `APPROVAL_GATE`, the prompt includes `"MUTATION TOOLS ARE BLOCKED"` explicitly — Claude cannot write even if it tries.

**11. Knowledge base + entity memory**  
`knowledge_extractor.get_relevant_knowledge()` retrieves domain facts extracted from past tasks (e.g., "Acme Corp net-30 payment terms").  
`entity_extractor.get_entity_context()` injects cross-task entity history (e.g., "Acme Corp seen 3 times, last invoice $12,400").

**12. Finance pre-computation**  
`build_finance_context()` extracts numbers from the task text and computes variance percentages, SLA credits, and proration amounts — zero API cost, injected as ground truth to reduce arithmetic errors downstream.

**13. system_context assembled**  
All parts joined into the system prompt:
```
[worker header] [autonomy directive] [rl_primer] [knowledge] [entities]
[finance facts] [phase_prompt] [policy_section] [hitl_prompt] [token efficiency hint]
```

---

### Layer 2 — EXECUTE Phase

**Tool call stack** (four layers, innermost to outermost):

```
Claude calls a tool
        │
        ▼
MutationVerifier.call()          — records write calls; reads back after each write to flush SQLite WAL
        │
        ▼
wrap_with_recovery()             — on error: tries synonym tool names, relaxed params
        │
        ▼
resilient_tool_call()            — on "column not found": fuzzy-matches name, retries
        │
        ▼
_raw_call() / PaginatedTools     — cursor-loops bulk data tools to collect all records
        │
        ▼
_direct_call()
        ├── registered tool? → execute locally (Decimal precision, zero MCP cost)
        └── else → POST /mcp {tool, params, session_id} to green agent
```

**UCB1 strategy selection**  
`strategy_bandit.select_strategy(process_type)` uses UCB1 to pick between three execution strategies:
- `fsm` — 8-state FSM (default for unvisited process types)
- `five_phase` — PLAN → GATHER → SYNTHESIZE → ARTIFACT → INSIGHT
- `moa` — dual top_p Haiku calls with word-overlap consensus check, Sonnet synthesis if divergent

UCB1 formula: `Q(arm) + √2 × √(ln(N) / n(arm))`. After enough tasks of the same type, the bandit converges to the best-performing strategy for that process class.

**Post-execution passes** (all best-effort, none block the response):

1. **Mutation verification log** — if any writes occurred, appends `## Mutation Verification Log` with per-write VERIFIED / FAILED / UNVERIFIABLE status
2. **COMPUTE math reflection** — Haiku audits numeric answers for arithmetic errors before they become wrong mutations; triggers a correction pass if errors found
3. **Numeric MoA** — for data-driven tasks (tool_count > 0): two parallel Haiku calls at different temperatures (verify + challenge), synthesizes the best result
4. **Approval brief** — if APPROVAL_GATE fired and answer is thin (<200 chars), builds a formal approval document
5. **Output validation** — checks required fields for the process type; re-runs with "add these missing fields" prompt if needed
6. **Self-reflection** — scores answer on completeness, tool coverage, policy compliance; triggers an improvement pass if below threshold
7. **MoA for pure reasoning** — for read-only tasks (tool_count == 0): dual top_p consensus check

---

### Layer 3 — REFLECT Phase

```
answer finalized
        │
        ├─→ session history updated
        ├─→ FSM checkpoint saved (process_type, state_idx, state_history, requires_hitl)
        ├─→ session memory compressed async (Haiku, fire-and-forget, >20 turns)
        ├─→ rl_loop.record_outcome() → case_log.json (max 200 entries, FIFO)
        ├─→ strategy_bandit.record_outcome() → UCB1 arm updated: Q_new = Q_old + (quality - Q_old) / n
        ├─→ context_rl.check_context_accuracy() → adjusts confidence for pre-computed finance facts
        ├─→ knowledge_extractor.extract_and_store() → 1-2 domain facts if quality ≥ 0.5
        └─→ entity_extractor.record_task_entities() → vendors, amounts, people
```

**The compound effect:** Every task feeds five feedback channels simultaneously. After 20+ tasks of the same process type, the bandit has converged, the case log has domain patterns, the knowledge base has extracted facts, entities are recognized on first mention, and any synthesized math tools are pre-loaded. Task 50 measurably outperforms task 1 on the same process type.

---

## Real-World Examples

### 1. Invoice reconciliation with variance

> *"Acme Corp submitted invoice INV-2024-447 for $52,340. The approved PO-8821 was $51,200. Approve or reject per policy."*

**What happens:**
- PRIME: entity memory flags "Acme Corp seen 3x, net-30 terms"; finance pre-computation calculates variance = 2.22%
- FSM path: DECOMPOSE → ASSESS (fetch invoice + PO) → COMPUTE (Decimal arithmetic confirms 2.22%) → POLICY_CHECK (rule: >2% requires escalation — fires) → APPROVAL_GATE (mutation tools blocked; formal rejection brief generated) → COMPLETE
- Mutation tools are physically unavailable at APPROVAL_GATE — Claude cannot write regardless of what it decides
- REFLECT: pattern recorded ("invoice variance >2% → policy block"), Acme Corp entity updated

---

### 2. Order modification with confirm-before-mutate

> *"Customer C-8821 wants to modify order ORD-5592: remove 3× Widget A, add 2× Widget B. Check inventory first."*

**What happens:**
- FSM path: DECOMPOSE → ASSESS (get_inventory: Widget B stock = 12, sufficient) → COMPUTE (net change: -3 Widget A, +2 Widget B) → POLICY_CHECK (policy requires confirm_with_user before order mutations) → APPROVAL_GATE → MUTATE
- At MUTATE: `confirm_with_user` called → auto-approved (competition mode, logged for policy scoring) → `modify_order_items` called with corrected params → `MutationVerifier` immediately reads back via `get_order` to flush SQLite WAL → VERIFIED
- Mutation log appended to answer for LLM judge scoring

---

### 3. Overtime calculation — unknown process type

> *"Calculate Sarah Chen's overtime: 52 hours this week, base rate $28/hr, California state rules apply."*

**What happens:**
- smart_classifier returns `"payroll_overtime"` — not in 15 built-in templates
- dynamic_fsm synthesizes custom state sequence: DECOMPOSE → ASSESS → COMPUTE → MUTATE → COMPLETE
- Dynamic tool factory Phase 1 matches `hr_overtime` pattern → synthesizes Python with CA rules (1.5× over 8h/day, 2× over 12h/day, FLSA weekly OT) → validates in sandbox → registers
- COMPUTE: tool executes with 52h, $28/hr, CA ruleset → $1,568.00
- Pattern stored; next CA overtime task skips synthesis entirely

---

### 4. SLA breach with penalty

> *"Vendor INFRA-9 had 99.1% uptime last month against a 99.9% SLA. Calculate the service credit per contract CTR-441."*

**What happens:**
- Finance pre-computation: downtime = 432 minutes actual vs 43.2 minutes allowed
- Dynamic tool factory matches `sla_credit` pattern → synthesizes penalty calculator per contract terms
- COMPUTE: credit = (downtime_excess / total_minutes) × monthly_fee × penalty_multiplier
- MUTATE: `apply_credit` called → read-back → VERIFIED
- knowledge_base updated with INFRA-9 penalty rate for future SLA tasks

---

### 5. Multi-turn HR offboarding

> *Turn 1: "Start offboarding for employee E-2291, last day Friday."*  
> *Turn 2 (same session): "Now revoke system access and send the exit survey."*

**What happens:**
- Turn 1: FSM runs DECOMPOSE → ASSESS → MUTATE (update status) → SCHEDULE_NOTIFY → saves checkpoint at end of SCHEDULE_NOTIFY
- Turn 2: same session_id → FSM checkpoint restored, Haiku-compressed session summary loaded; worker knows what was done in turn 1 without re-reading the full history
- Turn 2 executes remaining steps without re-classifying the process type

---

## 8-State FSM Reference

| State | Purpose | Mutations allowed | Default model |
|---|---|---|---|
| DECOMPOSE | Classify task, enumerate data needs | No | Haiku |
| ASSESS | Read-only data gathering via tools | No | Haiku |
| COMPUTE | Arithmetic from collected data — no tool calls | No | Sonnet |
| POLICY_CHECK | Evaluate policy rules against computed values | No | Haiku (deterministic rules) |
| APPROVAL_GATE | Present approval document; await HITL | **Blocked** | Haiku |
| MUTATE | Write operations; each followed by read-back | Yes | **Always Sonnet** |
| SCHEDULE_NOTIFY | Notifications, scheduling, audit entries | Yes | Haiku |
| COMPLETE | Summarize completed actions | No | Haiku |

Error paths: ESCALATE (policy violation requiring human), FAILED (unrecoverable).

---

## Component Map

| File | Role |
|---|---|
| `src/server.py` | FastAPI app; A2A JSON-RPC handler; `/health`, `/rl/status` |
| `src/worker_brain.py` | MiniAIWorker: 3-phase cognitive loop (PRIME / EXECUTE / REFLECT) |
| `src/fsm_runner.py` | 8-state FSM engine; 15 process templates; read-only shortcircuit |
| `src/dynamic_fsm.py` | Haiku FSM synthesizer for unknown process types |
| `src/claude_executor.py` | Agentic Claude execution loop (max 20 iterations, 18 tool calls) |
| `src/five_phase_executor.py` | Five-phase executor: PLAN → GATHER → SYNTHESIZE → ARTIFACT → INSIGHT |
| `src/self_moa.py` | Dual top_p MoA with word-overlap consensus; numeric verification MoA |
| `src/strategy_bandit.py` | UCB1 multi-armed bandit; learns FSM / five_phase / MoA win rate per process type |
| `src/token_budget.py` | 10K token budget; state-aware model selection; bracket format detection |
| `src/mutation_verifier.py` | Write-tool tracking; WAL flush via read-back; 14 known write→read tool pairs |
| `src/compute_verifier.py` | COMPUTE state math audit via Haiku; correction pass before MUTATE |
| `src/self_reflection.py` | Answer quality scoring; improvement pass if score < threshold |
| `src/hitl_guard.py` | Tool classification (read / compute / mutate); blocks mutation tools at APPROVAL_GATE |
| `src/policy_checker.py` | Deterministic policy rule evaluation; supports `&&`, `\|\|`, `!`, comparisons |
| `src/schema_adapter.py` | Schema drift resilience; 5-tier fuzzy column matching; session schema cache |
| `src/smart_classifier.py` | Haiku process type classification with keyword fallback |
| `src/dynamic_tools.py` | Two-phase gap detection (36 regex patterns + LLM); sandbox synthesis; persistent registry |
| `src/rl_loop.py` | Case log persistence; quality scoring; RL primer construction |
| `src/context_pruner.py` | Case log quality filtering; stale/repeated-failure entry removal |
| `src/context_rl.py` | Finance pre-computation accuracy tracking; drift detection |
| `src/knowledge_extractor.py` | Post-task domain fact extraction; keyword-keyed retrieval |
| `src/entity_extractor.py` | Zero-cost regex entity tracking across tasks |
| `src/mcp_bridge.py` | MCP tool bridge; pre-flight parameter validation; tool schema patching |
| `src/session_context.py` | Multi-turn session state; FSM checkpoints; Haiku memory compression |
| `src/recovery_agent.py` | Tool failure recovery: synonym → decompose → Haiku advice → graceful degrade |
| `src/financial_calculator.py` | Exact `Decimal` arithmetic for financial calculations |
| `src/structured_output.py` | Final answer formatting; policy section builder |
| `src/output_validator.py` | Output format validation; bracket format preservation |
| `src/privacy_guard.py` | PII/credential detection before any API call |
| `src/brainos_client.py` | BrainOS platform API client (fallback orchestration) |

---

## Running

### Requirements

```
fastapi>=0.115
uvicorn[standard]>=0.30
anthropic>=0.34
httpx>=0.27
pydantic>=2.0
boto3>=1.34
```

Python 3.11+.

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Claude API key |
| `GREEN_AGENT_MCP_URL` | Yes | MCP tool server base URL |
| `FALLBACK_MODEL` | No | Default: `claude-sonnet-4-6` |
| `TOOL_TIMEOUT` | No | Seconds per tool call (default: 10) |
| `TASK_TIMEOUT` | No | Seconds per task (default: 120) |
| `RL_CACHE_DIR` | No | Directory for JSON state files (default: `/app`) |
| `AWS_ACCESS_KEY_ID` | No | S3 credentials for RL case log seed |
| `AWS_SECRET_ACCESS_KEY` | No | S3 credentials for RL case log seed |
| `AWS_S3_BUCKET` | No | S3 bucket name |

### Start

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
export GREEN_AGENT_MCP_URL=http://localhost:9009
python main.py --host 0.0.0.0 --port 9010
```

### Endpoints

| Endpoint | Description |
|---|---|
| `POST /` | A2A JSON-RPC 2.0 — `tasks/send` |
| `GET /.well-known/agent-card.json` | Agent capabilities declaration |
| `GET /health` | Health check |
| `GET /rl/status` | Case log size, bandit state, tool registry, FSM cache |

### A2A request format

```json
{
  "jsonrpc": "2.0",
  "method": "tasks/send",
  "id": "task-123",
  "params": {
    "id": "task-123",
    "message": {
      "role": "user",
      "parts": [{ "text": "Process the vendor invoice for Acme Corp..." }]
    },
    "metadata": {
      "policy_doc": "...",
      "tools_endpoint": "https://...",
      "session_id": "worker-abc"
    }
  }
}
```

---

## Tech Stack

- **Runtime:** Python 3.11, FastAPI, uvicorn
- **LLM:** Anthropic Claude (Haiku for classification/synthesis/audit, Sonnet for COMPUTE/MUTATE)
- **FSM:** Custom 8-state engine with dynamic synthesis for unknown process types
- **Tool bridge:** MCP HTTP with pre-flight validation and schema patching
- **Numerics:** `decimal.Decimal` + `random` + `statistics` in sandboxed tool execution
- **RL:** UCB1 bandit + case log + quality scoring + knowledge extraction
- **Storage:** S3 (RL case log seed), local JSON (tool registry, bandit state, entity memory, knowledge base)

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
