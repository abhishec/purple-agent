# Purple Agent — AI Worker for Business Processes

A persistent AI worker that executes enterprise business processes end-to-end using an 8-state FSM cognitive backbone, UCB1 strategy learning, and a reinforcement loop that compounds across tasks.

Built for the AgentBeats Business Process Agent Track.

---

## Overview

Business process agents fail at the edges: wrong mutation order, arithmetic errors before writes, stale schema assumptions, and no memory of what worked last time. Purple Agent addresses these directly with a structured execution model rather than a single agentic loop.

The core design is an 8-state finite state machine (DECOMPOSE → ASSESS → COMPUTE → POLICY_CHECK → APPROVAL_GATE → MUTATE → SCHEDULE_NOTIFY → COMPLETE) that forces correct ordering — data collection before computation, computation before policy check, policy check before mutation. This eliminates an entire class of errors where agents write incorrect values because they acted before reading.

Each task runs through a three-phase cognitive loop (PRIME → EXECUTE → REFLECT). PRIME loads relevant past patterns from the RL case log and known entity context. EXECUTE runs the FSM-driven pipeline. REFLECT records outcome quality back to the case log, updating the UCB1 strategy bandit and extracting reusable knowledge for future tasks.

The agent speaks the A2A JSON-RPC 2.0 protocol and connects to an MCP tool server for all data operations. It serves requests via FastAPI.

---

## Architecture

### The AI Worker Mental Model

Each request creates or resumes a `MiniAIWorker` instance keyed to a `session_id`. State persists across A2A turns — the FSM checkpoint, conversation history, and schema correction cache all survive between turns in the same session.

The worker does not maintain a flat conversational loop. It knows what phase it is in, what phase comes next, what actions are permitted in the current phase, and what actions are blocked. This structural clarity produces more consistent behavior than telling a model "here are all 130 tools, be careful what you call."

### Execution Pipeline

```
Request
  │
  ▼
PRIME
  ├── Load RL primer (pruned case log, top-3 relevant past cases)
  ├── Load entity memory (cross-task vendor/person/amount context)
  ├── Load knowledge base (per-domain extracted facts)
  ├── Classify process type (Haiku semantic classifier → keyword fallback)
  ├── Detect FSM strategy via UCB1 bandit (fsm / five_phase / moa)
  ├── Restore FSM checkpoint (if multi-turn session)
  └── Evaluate structured policy rules (zero-LLM, deterministic)
        │
        ▼
EXECUTE
  ├── UCB1 selects: fsm | five_phase | moa
  ├── [FSM path] Advance through 8 states
  │     ├── DECOMPOSE: classify + enumerate data needs
  │     ├── ASSESS:    read-only tool calls only (mutations blocked)
  │     ├── COMPUTE:   math from collected data; no tools; Haiku audit after
  │     ├── POLICY_CHECK: deterministic rule evaluation
  │     ├── APPROVAL_GATE: mutation tools blocked; produces approval document
  │     ├── MUTATE:    write tools; each followed by read-back (WAL flush)
  │     ├── SCHEDULE_NOTIFY: notifications/scheduling after mutations
  │     └── COMPLETE:  summarize
  ├── Schema drift recovery on every tool error (fuzzy column matching)
  ├── Tool failure recovery (synonym → decompose → Haiku advice → degrade)
  ├── Self-reflection gate: score answer quality; improve if below 0.65
  └── Bracket-format detection: exact_match answers bypass all post-processing
        │
        ▼
REFLECT
  ├── Record outcome to RL case log (quality score 0–1)
  ├── Record strategy performance to UCB1 bandit
  ├── Extract reusable knowledge facts (Haiku, fire-and-forget)
  ├── Update entity memory (cross-task entity tracking)
  └── Update context accuracy (drift detection for computed thresholds)
```

### 8-State FSM

Each state maps to a default model tier and has specific rules about what actions are permitted.

| State | Purpose | Default Model | Notes |
|-------|---------|---------------|-------|
| DECOMPOSE | Classify task, enumerate data needs, identify entities | Haiku | Entry point for all tasks |
| ASSESS | Read-only data gathering via tools | Haiku | Mutation tools explicitly blocked |
| COMPUTE | Pure arithmetic from collected data — no tool calls | Sonnet | Haiku audit runs after; MUTATE blocked until clean |
| POLICY_CHECK | Evaluate policy rules against computed values | Haiku | Deterministic; no LLM for structured rules |
| APPROVAL_GATE | Present approval document; wait for HITL | Haiku | All mutation tools blocked here |
| MUTATE | Write operations; each write followed by read-back | Sonnet | Never downgraded to Haiku — wrong writes are worse than slow ones |
| SCHEDULE_NOTIFY | Notifications, scheduling, audit log entries | Haiku | Runs after all mutations are verified |
| COMPLETE | Summarize completed actions | Haiku | |

Error paths: ESCALATE (policy violation requiring human), FAILED (unrecoverable error).

Read-only shortcircuit: tasks that contain no action verbs collapse to a 3-state path (DECOMPOSE → ASSESS → COMPLETE), skipping COMPUTE, POLICY_CHECK, APPROVAL_GATE, and MUTATE entirely.

Process type determines the state sequence. Fifteen built-in templates cover common types (expense_approval, procurement, hr_offboarding, invoice_reconciliation, sla_breach, payroll, etc.). Unknown process types trigger the dynamic FSM synthesizer, which calls Haiku once to produce a custom state sequence and per-state instructions, then caches the result permanently.

### Strategy Bandit (UCB1)

For each process type, the agent maintains a 3-arm bandit:

- `fsm` — 8-state FSM (default, reliable for structured processes)
- `five_phase` — 5-phase executor for complex multi-step tasks: PLAN (Haiku) → GATHER (async tool calls) → SYNTHESIZE (Sonnet) → ARTIFACT (Haiku) → INSIGHT (fire-and-forget)
- `moa` — Mixture of Agents: dual Haiku calls at different sampling temperatures, word-overlap consensus check, Sonnet synthesis if divergent

UCB1 score: `Q(arm) + sqrt(2) * sqrt(ln(N) / n(arm))`

Where Q is the mean reward (quality 0–1) for this arm, N is total pulls across all arms for this process type, and n is pulls for this arm. This balances exploitation (pick what has worked) with exploration (try undertested strategies).

On the first visit to any process type, all n=0, so the bandit defaults to `fsm`. After enough data, it converges to the best arm per process type. State persists to `strategy_bandit.json` across all tasks.

Incremental mean update: `Q_new = Q_old + (reward - Q_old) / n` — no need to store all rewards.

### Token Budget and Model Selection

Each task gets a 10,000-token budget (4 chars/token). Two thresholds govern model selection:

- **Above 80% used**: all remaining calls switch to Haiku regardless of state
- **At 100%**: skip remaining LLM calls entirely

Within budget, model selection is state-aware:

- MUTATE always gets Sonnet — irreversible writes should not be downgraded
- COMPUTE gets Sonnet only if the task contains complex analytical keywords (reconcile, root cause, diagnose, forecast, synthesize, cross-reference, correlate, investigate); otherwise Haiku
- All other states default to Haiku

The efficiency hint appended to system prompts scales with budget usage: mild at <30%, strict at <60%, emergency at >80%. The autonomy directive ("never ask clarifying questions") is always present.

Token budget also caps `max_tokens` per API call based on remaining budget — tight budgets get 256-token caps; full budgets get 4096.

### RL Feedback Loop

**Case log**: After each task, a `CaseEntry` records the task summary, keywords, outcome (success/partial/failure), quality score, what worked, what failed, tool count, and domain. Up to 200 entries stored in `case_log.json`.

**Quality scoring**: Conservative baseline of 0.5, then adjusted by signals:
- Tool usage depth (more calls = more complete)
- Answer length and structure
- Presence of decision/completion markers
- Policy compliance
- Penalty for error phrases, empty data arrays, and very short answers
- Bracket-format answers (exact_match targets) always score 1.0

**PRIME injection**: Before each task, the top-3 most keyword-relevant past cases are injected as a primer. Relevance is scored by keyword overlap between the new task and past case keywords.

**Context rot pruning**: Before injection, the case log is filtered. Dropped entries:
- Quality < 0.35 and outcome = failure
- Age > 72 hours
- Repeated failure patterns (3+ failures with >= 50% keyword overlap)

If pruning would remove more than 70% of entries, the pruner falls back to keeping the higher-quality half — conservative by design.

**Knowledge extraction**: After tasks with quality >= 0.50, Haiku extracts up to 4 reusable facts and stores them in `knowledge_base.json`. Future tasks get relevant facts injected by domain and entity keyword match. Extraction is fire-and-forget and never blocks task completion.

**Entity memory**: Zero-cost regex extraction tracks vendors, people, amounts, reference IDs, dates, and products across all tasks. Entity context is injected during PRIME.

**Context accuracy feedback**: After tasks involving computed financial thresholds (variance bounds, SLA credits, policy limits), the accuracy of the pre-computed values is tracked. If accuracy on the last 5 similar tasks drops below 40%, the injected context switches from a value to a drift warning telling Claude not to trust the threshold and to compute fresh from tool data.

---

## Key Design Decisions

**1. FSM enforces READ-before-MUTATE, not Claude**

Telling an LLM "gather data first, then act" in a system prompt is unreliable. The FSM makes mutation tools structurally unavailable during ASSESS and APPROVAL_GATE states. The agent cannot accidentally write before it reads because the tool classification layer (hitl_guard.py) blocks those calls at the prompt level, not the application level.

**2. MUTATE uses Sonnet always, never Haiku**

A wrong database write is far worse than a slow one. Haiku's token cost savings at the MUTATE state are not worth the risk of an incorrect tool call. The `get_model()` function has an explicit guard that prevents MUTATE from being downgraded even when the token budget threshold is close.

**3. WAL flush via read-back, not sleep**

SQLite WAL mode means mutations written through the MCP tool are in the WAL file, not the main database file. If the scorer reads the main file before WAL checkpoint, it sees stale data. The mutation verifier solves this by immediately reading back the same entity after every write — a SQLite read forces WAL merge, making the mutation visible without any delay or sleep.

**4. Bracket-format detection uses full JSON parse, not `startswith`**

The competition uses exact_match scoring for some tasks where the expected answer is a JSON array like `["INV-001", "INV-002"]`. Adding metadata or putting the answer through the reflection improvement loop would corrupt these answers. A pure `startswith('[')` check misclassifies prose like "Rejected. [Reason: policy violation]" as bracket format. The detection function requires: starts with `[`, ends with `]`, AND `json.loads()` returns a list. Prose with embedded brackets fails the JSON parse.

**5. Schema drift recovery before giving up on a tool**

Competition databases can have column names that differ from what the task description implies. Rather than propagating a tool error, the schema adapter intercepts "column not found" errors, runs `describe_table`, fuzzy-matches the intended column using difflib (Levenshtein-similar + known alias table + prefix matching), and retries with the corrected name. The correction is cached in the session schema cache so subsequent calls in the same session use the fixed name without another round-trip.

---

## Component Map

| File | Role |
|------|------|
| `main.py` | CLI entry point; FastAPI server startup with `--host`, `--port`, `--card-url` args |
| `src/server.py` | FastAPI app; A2A JSON-RPC handler; `/health` and `/rl/status` endpoints; startup training seed |
| `src/worker_brain.py` | MiniAIWorker: 3-phase cognitive loop (PRIME, EXECUTE, REFLECT) |
| `src/fsm_runner.py` | 8-state FSM engine; process templates; read-only shortcircuit; multi-checkpoint support |
| `src/dynamic_fsm.py` | Haiku-powered FSM synthesizer for unknown process types; caches to `synthesized_definitions.json` |
| `src/claude_executor.py` | Primary Claude execution engine; agentic tool-call loop (up to 20 iterations, 18 tool calls) |
| `src/five_phase_executor.py` | 5-phase executor: PLAN/GATHER/SYNTHESIZE/ARTIFACT/INSIGHT for complex tasks |
| `src/self_moa.py` | Mixture-of-Agents: dual top_p Haiku calls + word-overlap consensus + optional Sonnet synthesis |
| `src/strategy_bandit.py` | UCB1 multi-armed bandit; learns FSM/five_phase/MoA win rates per process type |
| `src/token_budget.py` | 10K token budget; model tier selection; bracket-format detection; `format_competition_answer()` |
| `src/self_reflection.py` | Post-execution answer quality scoring; improvement pass if score < 0.65 |
| `src/compute_verifier.py` | COMPUTE state math audit via Haiku; catches arithmetic errors before MUTATE |
| `src/mutation_verifier.py` | Write-tool tracking + immediate read-back for WAL flush; builds mutation log |
| `src/hitl_guard.py` | Tool classification (read/compute/mutate); mutation tool blocking at APPROVAL_GATE |
| `src/policy_checker.py` | Deterministic policy rule evaluation (zero LLM); supports `&&`, `\|\|`, `!`, comparisons |
| `src/schema_adapter.py` | Schema drift resilience; fuzzy column matching; 5-tier correction strategy |
| `src/smart_classifier.py` | Haiku semantic process type classification; keyword fallback on timeout/error |
| `src/rl_loop.py` | Case log persistence; quality scoring; RL primer construction |
| `src/context_pruner.py` | Case log quality filtering; repeated-failure detection; conservative prune guard |
| `src/context_rl.py` | Context injection accuracy tracking; drift detection for pre-computed thresholds |
| `src/knowledge_extractor.py` | Post-task Haiku fact extraction; domain-keyed knowledge base |
| `src/entity_extractor.py` | Zero-cost regex entity tracking (vendors, IDs, amounts, people) across tasks |
| `src/dynamic_tools.py` | Runtime tool factory: 30+ gap detection patterns + LLM phase-2 detection; sandboxed synthesis |
| `src/mcp_bridge.py` | MCP tool call bridge; pre-flight parameter validation; empty result detection |
| `src/session_context.py` | Multi-turn session state; FSM checkpoints; Haiku memory compression at 20 turns |
| `src/recovery_agent.py` | Tool failure recovery: synonym → decompose → Haiku advice → graceful degrade |
| `src/paginated_tools.py` | Cursor-loop pagination for bulk data tools |
| `src/document_generator.py` | Structured document generation (approval briefs, post-mortems) |
| `src/financial_calculator.py` | Exact decimal arithmetic for financial calculations |
| `src/finance_tools.py` | Financial analysis tools (NPV, amortization, depreciation) |
| `src/brainos_client.py` | BrainOS platform API client (fallback orchestration) |
| `src/structured_output.py` | Final answer formatting; policy section builder |
| `src/output_validator.py` | Output format validation; bracket preservation checks |
| `src/privacy_guard.py` | PII detection before external calls |
| `src/process_definitions.py` | Built-in process definitions used by smart classifier and dynamic FSM |
| `src/training_loader.py` | Background S3 seed for RL case log on startup |
| `src/report_analyzer.py` | Benchmark intelligence analysis; training data processing |
| `src/memory_compressor.py` | Haiku-based conversation memory compression |
| `src/config.py` | Environment variable loading |

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

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key (used for Haiku and Sonnet calls) |
| `GREEN_AGENT_MCP_URL` | Yes | MCP tool server base URL |
| `FALLBACK_MODEL` | No | Default: `claude-sonnet-4-6` |
| `TOOL_TIMEOUT` | No | Seconds per tool call, default 10 |
| `TASK_TIMEOUT` | No | Seconds per task, default 120 |
| `BRAINOS_API_URL` | No | BrainOS platform URL (fallback orchestration) |
| `BRAINOS_API_KEY` | No | BrainOS API key |
| `S3_TRAINING_BUCKET` | No | S3 bucket for RL training seed |
| `AWS_ACCESS_KEY_ID` | No | AWS credentials for S3 access |
| `AWS_SECRET_ACCESS_KEY` | No | AWS credentials for S3 access |
| `RL_CACHE_DIR` | No | Directory for bandit/registry JSON files (default: `/app`) |
| `PURPLE_AGENT_CARD_URL` | No | Public URL advertised in AgentCard |

### Start

```bash
pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...
export GREEN_AGENT_MCP_URL=http://localhost:9009

python main.py --host 0.0.0.0 --port 9010
```

Or with Docker:

```dockerfile
docker build -t purple-agent .
docker run -p 9010:9010 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e GREEN_AGENT_MCP_URL=http://mcp-server:9009 \
  purple-agent
```

### A2A Protocol

The agent implements the A2A JSON-RPC 2.0 `tasks/send` method:

```json
POST /
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "method": "tasks/send",
  "id": "task-123",
  "params": {
    "id": "task-123",
    "message": {
      "role": "user",
      "parts": [{ "text": "Process the expense claim for EMP-447, $2,340 for team offsite..." }]
    }
  }
}
```

AgentCard: `GET /.well-known/agent-card.json`

Health: `GET /health`

RL and bandit stats: `GET /rl/status` (returns case log counts, bandit arm values, tool registry size, FSM synthesis cache)

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

Copyright 2026 BrainOS / Abhishek.
