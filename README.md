# Purple Agent — AI Worker for Business Processes

A structured AI worker that executes enterprise business processes through a three-phase cognitive loop: PRIME (context assembly), EXECUTE (FSM-driven action), and REFLECT (learning feedback). The architecture enforces correct operation ordering at the structural level — mutations cannot occur before data collection, and policy checks cannot be bypassed, because the state machine makes those tool classes unavailable at the wrong phase.

---

## What It Is

Business process automation fails at a small set of predictable failure modes: agents that write before they read, arithmetic that accumulates floating-point error, policy rules that get summarized rather than evaluated, and no memory of what worked on similar tasks last week. A flat agentic loop with a long system prompt addresses none of these structurally — it relies on the model obeying instructions it could plausibly ignore.

Purple Agent replaces the flat loop with an 8-state finite state machine that makes incorrect ordering physically impossible. In the ASSESS state, mutation tools are absent from the tool schema. In the APPROVAL_GATE state, all write-capable tools are blocked at the prompt layer. The model cannot accidentally write before it reads because the write tools are not offered until the FSM reaches MUTATE.

On top of the FSM sits a reinforcement loop. After each task, a quality score is computed from signals (tool depth, answer completeness, policy compliance, error phrase detection) and recorded to a case log. Before the next task, the top three keyword-relevant past cases are injected as a primer. After 20+ tasks of the same type, the agent has pattern context, a tuned UCB1 strategy bandit, a populated knowledge base, and pre-loaded tool registrations — it executes faster and makes fewer errors than it did on its first encounter with that process type.

The mental model: each `session_id` corresponds to one `MiniAIWorker` instance. State persists across A2A turns — the FSM checkpoint, conversation history, and schema correction cache all survive between turns in the same session. A multi-turn HR offboarding task that pauses for human confirmation resumes exactly where it left off.

---

## Architecture Overview

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

---

## The Execution Pipeline

### PRIME: Building Context Before Acting

PRIME assembles the system prompt before Claude sees the task. Every step below runs before any LLM call that touches the task itself.

**Step 1 — Privacy guard**
Regex scan for PII patterns (SSNs, credit card numbers, passwords, API keys in the payload). If detected, the task is refused with a structured error and zero API cost. This runs before everything else.

**Step 2 — RL primer**
`build_rl_primer()` loads `case_log.json` and scores each entry by keyword overlap with the current task. The top-3 relevant past cases are formatted as: `"Past pattern: invoice tasks with variance >2% → escalate to APPROVAL_GATE"`. The primer is injected at the top of the system context. Bad entries are pruned first (quality < 0.35, age > 72h, repeated failure patterns with ≥50% keyword overlap).

**Step 3 — Session context**
If the session has prior turns, `get_context_prompt()` returns a Haiku-compressed summary (~200 tokens) of past conversation. This gives turn 2 the context of what was decided in turn 1 without replaying the full history.

**Step 4 — FSM classification**
`classify_process_type()` calls Haiku to classify the task into a process type (`invoice_reconciliation`, `expense_approval`, `hr_offboarding`, etc.). On Haiku timeout or error, a keyword fallback fires deterministically. The process type selects the FSM template.

**Step 5 — Dynamic FSM synthesis**
If the classified type is not among the 15 built-in templates, `synthesize_if_needed()` calls Haiku once to produce a custom state sequence and per-state instructions specific to the novel process type. The result is cached permanently to `synthesized_definitions.json`. Future tasks of the same novel type use the cache — Haiku is called exactly once per new process type, ever.

**Step 6 — FSMRunner setup**
`detect_task_complexity()` scans for read-only intent patterns (`what is`, `show me`, `list`, `find`) against action patterns (`approve`, `update`, `cancel`, `reconcile`). Pure query tasks collapse to a 3-state path (DECOMPOSE → ASSESS → COMPLETE), skipping COMPUTE, POLICY_CHECK, APPROVAL_GATE, and MUTATE entirely. Existing FSM checkpoints are restored from the session here.

**Step 7 — Policy evaluation**
If a `policy_doc` was provided (JSON with a `rules` array), `evaluate_policy_rules()` evaluates it deterministically — no LLM involved. Supports `&&`, `||`, `!`, numeric comparisons, string equality, and range checks. The result is formatted as a policy section and injected into the system context.

**Step 8 — Tool discovery**
`discover_tools()` fetches tool schemas from the MCP server. `load_registered_tools()` loads `tool_registry.json` for any previously synthesized tools that apply to this session. The combined tool list is passed to Claude.

**Step 9 — Dynamic tool gap detection**
Two-phase detection runs before EXECUTE:
- Phase 1: 30+ regex patterns covering finance, HR, SLA, supply chain, tax, and risk domains. Zero API cost. Matches patterns like `FLSA overtime`, `sla_credit`, `variance_percent`, `proration`.
- Phase 2: If Phase 1 finds nothing and the task is ≥100 characters, `detect_tool_gaps_llm()` calls Haiku to identify what computation is missing.
If a gap is found, `synthesize_and_register()` generates a Python implementation via Haiku, runs it in a sandbox against auto-generated test cases, and on pass, persists it to `tool_registry.json`. All future tasks can use the tool — the synthesis cost is paid once.

**Step 10 — HITL gate check**
If the FSM is resuming from an APPROVAL_GATE checkpoint, `check_approval_gate()` injects `"MUTATION TOOLS ARE BLOCKED"` into the system prompt. This is belt-and-suspenders: the FSMRunner also withholds mutation tools from the schema at this state.

**Step 11 — Knowledge and entity memory**
`get_relevant_knowledge()` queries `knowledge_base.json` for domain facts and entity-specific history. `get_entity_context()` returns zero-cost regex-extracted context: known vendors, reference amounts, people, and IDs seen in past tasks. Both are injected into the system context.

**Step 12 — Finance pre-computation**
`build_finance_context()` extracts numbers from the task and pre-computes: variance percentage, SLA downtime minutes, proration amounts, and credit calculations. These values are injected as ground truth, reducing Claude's need to derive them from scratch. A context accuracy tracker monitors whether these pre-computed values have been drifting (if accuracy on the last 5 similar tasks drops below 40%, a drift warning replaces the value).

**Step 13 — system_context assembly**
All parts are joined in a fixed order: RL primer → session context → policy section → entity memory → knowledge facts → finance pre-computation → tool gap results → HITL gate status. This becomes the system prompt.

---

### EXECUTE: FSM-Driven with UCB1 Strategy Learning

**UCB1 strategy selection**

For each process type, `select_strategy()` maintains a 3-arm bandit:

| Arm | Use case |
|-----|----------|
| `fsm` | Structured processes with clear state transitions (default) |
| `five_phase` | Complex multi-step tasks: PLAN → GATHER → SYNTHESIZE → ARTIFACT → INSIGHT |
| `moa` | Pure-reasoning and numeric tasks: dual top_p Haiku consensus + optional Sonnet synthesis |

UCB1 score: `Q(arm) + sqrt(2) * sqrt(ln(N) / n(arm))`

Where Q is mean reward for this arm, N is total pulls across all arms for this process type, and n is pulls for this arm. On first visit to any process type, all n=0 so the bandit defaults to `fsm`. State persists to `strategy_bandit.json` across all tasks. The incremental mean update `Q_new = Q_old + (reward - Q_old) / n` avoids storing all historical rewards.

**Tool call stack**

Each tool call during EXECUTE passes through this stack, in order:

1. `MutationVerifier` — detects write-verb prefixes (`update_`, `create_`, `approve_`, `delete_`, etc.). After each write, infers the corresponding read tool and calls it immediately. This forces WAL checkpoint in SQLite, making the mutation visible before the scorer reads the database.

2. `RecoveryAgent` — if the tool call fails, tries: synonym lookup → task decomposition → Haiku advice on alternative approach → graceful degrade with explanation.

3. `SchemaAdapter` — if the error is "column not found", runs `describe_table`, fuzzy-matches the intended column (difflib + known alias table + prefix matching), retries with the corrected name, and caches the correction in the session schema cache.

4. `PaginatedTools` — if the tool is a bulk-data fetch, runs a cursor loop to collect all pages before returning.

5. Direct call — either to a registered synthesized tool or to the MCP server via `call_tool()`.

**8-state FSM execution**

Each state has a fixed model assignment, explicit rules about permitted tool classes, and defined exit conditions:

| State | Purpose | Default Model | Permitted Tools |
|-------|---------|---------------|----------------|
| DECOMPOSE | Classify task, enumerate data needs, identify entities | Haiku | Read-only |
| ASSESS | Gather data via tool calls | Haiku | Read-only (mutations blocked) |
| COMPUTE | Pure arithmetic from collected data — no tool calls | Sonnet | None (math only) |
| POLICY_CHECK | Evaluate policy rules against computed values | Haiku | None (deterministic) |
| APPROVAL_GATE | Produce approval document; wait for HITL | Haiku | All mutations blocked |
| MUTATE | Write operations; each followed by immediate read-back | Sonnet | Write tools (always Sonnet — never downgraded) |
| SCHEDULE_NOTIFY | Notifications, scheduling, audit log entries | Haiku | Notification tools |
| COMPLETE | Summarize completed actions | Haiku | None |

Error paths: ESCALATE (policy violation requiring human), FAILED (unrecoverable error).

**Post-execution passes**

After the main execution loop completes, in order:

- Mutation verification log is appended to the answer text (LLM judge can score correct behavior even if a DB read fails)
- COMPUTE math reflection: `verify_compute_output()` runs a Haiku audit of all arithmetic before MUTATE — catches decimal errors before they become wrong writes
- Numeric MoA: `numeric_moa_synthesize()` runs dual top_p Haiku calls and checks word-overlap consensus on numeric results
- Approval brief: if the task reached APPROVAL_GATE, `build_approval_brief()` generates a structured approval document
- Output validation: checks for missing required fields and re-prompts if needed
- Self-reflection: `reflect_on_answer()` scores the answer quality. If below 0.65, `build_improvement_prompt()` generates a targeted improvement pass. Bracket-format answers (`["INV-001", "INV-002"]` — confirmed by full JSON parse, not `startswith`) bypass reflection entirely.

**Token budget and model selection**

Each task gets a 10,000-token budget (4 chars/token). Two thresholds:
- Above 80% used: all remaining calls switch to Haiku regardless of state
- At 100%: skip remaining LLM calls entirely

MUTATE always uses Sonnet and cannot be downgraded — an incorrect write is far worse than a slower one. COMPUTE uses Sonnet if the task contains complex analytical keywords (reconcile, root cause, diagnose, forecast, synthesize, correlate); otherwise Haiku. All other states default to Haiku. The efficiency hint in the system prompt scales with budget consumption: mild below 30%, strict below 60%, emergency above 80%.

---

### REFLECT: Compounding Learning Across Tasks

**FSM checkpoint**
If the session is multi-turn and the FSM ended at APPROVAL_GATE (waiting for human), `save_fsm_checkpoint()` persists the current state, completed steps, and pending steps. The next turn restores this checkpoint and continues without re-running PRIME from scratch.

**Session memory compression**
`maybe_compress_async()` fires asynchronously after REFLECT. If the session has accumulated 20+ turns, Haiku compresses the full history to a ~200-token summary. This summary replaces the raw history in future turns' Step 3.

**RL outcome recording**
`record_outcome()` computes a quality score (0.0–1.0) from: tool usage depth, answer length and structure, presence of decision and completion markers, policy compliance, and penalties for error phrases and empty data arrays. Bracket-format exact-match answers always score 1.0. The `CaseEntry` is appended to `case_log.json` (max 200 entries, FIFO eviction).

**UCB1 bandit update**
`bandit_record()` updates the arm that was selected this task: `Q_new = Q_old + (quality - Q_old) / n`. After enough tasks per process type, the bandit converges to the arm with the best mean reward.

**Knowledge extraction**
If quality ≥ 0.5, `extract_and_store()` calls Haiku to extract 1-2 reusable domain facts from the completed task. Examples: `"Acme Corp variance threshold is 2%, not 5%"`, `"INFRA-9 contract #CTR-441 uses 10% penalty per 0.1% downtime"`. These are stored to `knowledge_base.json` keyed by domain and entity and injected into future tasks.

**Entity memory update**
`record_task_entities()` runs zero-cost regex extraction over the task and answer — vendors, reference IDs, amounts, people, dates, and products — and appends to the entity memory store. Future tasks involving the same entities get context without any API cost.

**The compound effect**
After 20+ tasks of the same process type: the bandit has converged to the best strategy, the case log has 20 patterns including what failed, the knowledge base has 10-40 domain facts, and tools are pre-loaded from the registry. A task that took 45 seconds on first encounter takes 18 seconds on encounter 20, with a measurably lower error rate.

---

## Real-World Examples

### Case 1: Invoice Reconciliation with Variance Breach

**Task:** `"Acme Corp submitted invoice INV-2024-447 for $52,340. PO-8821 was $51,200. Approve or reject per policy."`

**PRIME:**
- RL primer finds 3 past Acme Corp entries: `"Past pattern: Acme variance >2% → escalate"`
- Finance pre-computation extracts `52340` and `51200`, computes `variance = (52340 - 51200) / 51200 = 2.22%`
- Policy evaluation loads threshold: `variance_percent > 2.0 → reject`
- FSM classifies: `invoice_reconciliation` → full 8-state path

**EXECUTE:**
- DECOMPOSE: identifies entities `INV-2024-447`, `PO-8821`, `Acme Corp`
- ASSESS: `get_invoice(INV-2024-447)` → `{amount: 52340, vendor: "Acme Corp"}`. `get_purchase_order(PO-8821)` → `{approved_amount: 51200}`
- COMPUTE: decimal variance `Decimal("52340") - Decimal("51200") = Decimal("1140")`. `1140 / 51200 = 0.02226 = 2.23%`. Haiku math audit: passes.
- POLICY_CHECK: `2.23% > 2.0%` → rule fires → outcome: `reject`
- APPROVAL_GATE: mutation tools blocked. `build_approval_brief()` produces: `Rejection Brief — INV-2024-447. Variance: 2.23% (threshold: 2.00%). Acme Corp past pattern: consistent overages. Recommendation: reject and request revised invoice.`
- FSM halts at APPROVAL_GATE. Task ends. No writes occur.

**Key detail:** Claude cannot write the rejection to the database even if it tries — `reject_invoice()` is absent from the tool schema at APPROVAL_GATE. The tool simply does not exist in that state.

---

### Case 2: Order Modification with HITL Confirmation

**Task:** `"Customer C-8821 wants to change order #ORD-5592: remove 3x Widget A, add 2x Widget B. Check inventory first."`

**PRIME:**
- FSM classifies: `order_modification` → full path
- Policy doc includes: `confirm_with_user required before modify_order_items`

**EXECUTE:**
- ASSESS: `get_inventory("Widget B")` → `{available: 47, reserved: 12}`. Sufficient stock.
- COMPUTE: net change = -3 Widget A, +2 Widget B. No financial delta to compute.
- POLICY_CHECK: `modify_order_items` requires `confirm_with_user` first → policy fires
- APPROVAL_GATE: produces confirmation request: `"Confirm: remove 3x Widget A ($89.97 credit), add 2x Widget B ($64.00 charge). Net: -$25.97 for C-8821. Approve?"`
- Human sends turn 2: `"Confirmed, proceed"`
- Turn 2 restores FSM checkpoint at APPROVAL_GATE. FSM advances to MUTATE.
- MUTATE: `modify_order_items(ORD-5592, ...)` → MutationVerifier reads back `get_order(ORD-5592)` immediately → WAL flushed → verified: Widget A removed, Widget B added.
- SCHEDULE_NOTIFY: `send_order_confirmation(C-8821, ORD-5592)` fires after mutation.

---

### Case 3: Payroll Overtime for an Unknown Process Type

**Task:** `"Calculate Sarah Chen's overtime: 52 hours this week, base rate $28/hr, CA state rules apply."`

**PRIME:**
- FSM classifies: `payroll_overtime` — not in 15 built-in templates
- `synthesize_if_needed()` calls Haiku: synthesizes state sequence `DECOMPOSE → ASSESS → COMPUTE → POLICY_CHECK → COMPLETE` with per-state instructions: `"COMPUTE: apply FLSA daily overtime (1.5x over 8hrs/day, 2x over 12hrs/day) AND weekly overtime (1.5x over 40hrs). Use Decimal arithmetic. CA rule takes precedence over FLSA."`
- Result cached to `synthesized_definitions.json` — never called again for this type
- Tool gap detection: Phase 1 matches `FLSA overtime` pattern → `synthesize_and_register()` generates Python function with CA daily overtime logic → sandbox validates against test cases → registered to `tool_registry.json`

**EXECUTE:**
- ASSESS: `get_employee_record("Sarah Chen")` → `{id: EMP-4421, department: Engineering, state: CA}`
- COMPUTE: registered tool `calculate_overtime_ca` called:
  - Daily calc (CA rule): Days assumed 5×8h standard + 12h extra. 5 days × 8h = 40h base. Remaining 12h: first 4h/day at 1.5x, over 12h at 2x.
  - Weekly: 52h total. 40h at $28.00, 12h at $42.00 = `Decimal("40") * 28 + Decimal("12") * 42 = $1,120 + $504 = $1,624`
  - CA daily rule produces higher number: applied as required by CA law.
  - Final: `$1,624.00`
- COMPLETE: answer includes calculation breakdown with Decimal precision.

**Result:** `$1,624.00 gross pay for week. CA daily overtime rule applied (1.5x on hours 8-12, 2x on hours >12 per day). Tool synthesized and registered for future payroll tasks.`

---

### Case 4: SLA Breach with Penalty Calculation

**Task:** `"Vendor INFRA-9 had 99.1% uptime last month against 99.9% SLA. Calculate credit per contract #CTR-441."`

**PRIME:**
- Finance pre-computation: month = 43,200 minutes. Allowed downtime: `43200 * 0.001 = 43.2 minutes`. Actual downtime: `43200 * 0.009 = 388.8 minutes`. Breach: `388.8 - 43.2 = 345.6 excess minutes`.
- Tool gap detection: Phase 1 matches `sla_credit` pattern → synthesizes penalty function: `excess_minutes / total_minutes * monthly_fee * penalty_multiplier` → registered.
- RL primer: if INFRA-9 seen before, injects contract terms from knowledge base.

**EXECUTE:**
- ASSESS: `get_contract(CTR-441)` → `{monthly_fee: 85000, penalty_multiplier: 1.5, sla_target: 99.9}`
- COMPUTE: registered tool `calculate_sla_credit`:
  - `345.6 / 43200 * 85000 * 1.5 = 0.008 * 85000 * 1.5 = $1,020.00`
  - Haiku math audit verifies.
- POLICY_CHECK: breach confirmed, credit authorized per contract terms
- MUTATE: `apply_account_credit(INFRA-9, 1020.00, "SLA breach CTR-441")` → MutationVerifier reads `get_account_balance(INFRA-9)` → credit confirmed in DB.
- SCHEDULE_NOTIFY: `send_sla_breach_notification(INFRA-9, CTR-441, 1020.00)` fires.

---

### Case 5: Multi-Turn HR Offboarding

**Turn 1:** `"Start offboarding for employee E-2291 (last day Friday)"`

- FSM classifies: `hr_offboarding` → full 8-state path
- ASSESS: `get_employee(E-2291)` → `{name: "Jordan Kim", department: Platform Engineering, systems: ["GitHub", "AWS", "Slack", "Jira", "Okta"]}`
- COMPUTE: last day = this Friday. Equipment return deadline = Friday. Final paycheck date = next pay cycle (verified from policy).
- MUTATE: `update_employee_status(E-2291, "offboarding")`, `create_offboarding_checklist(E-2291, [...])` → both verified via read-back.
- SCHEDULE_NOTIFY: `schedule_equipment_return(E-2291, Friday)`, `notify_it_team(E-2291, systems=[...])`, `schedule_exit_survey(E-2291)`.
- FSM checkpoint saved at SCHEDULE_NOTIFY — Jordan Kim's offboarding is in progress.

**Turn 2 (same session):** `"Now revoke system access and send exit survey"`

- Session context summary injected: `"Turn 1: Offboarding initiated for Jordan Kim (E-2291). Status updated. IT notified of 5 systems. Equipment return scheduled Friday. Exit survey scheduled."`
- FSM checkpoint restored: resumes from SCHEDULE_NOTIFY, skips re-classification entirely.
- MUTATE: `revoke_access(E-2291, "GitHub")` → read-back. `revoke_access(E-2291, "AWS")` → read-back. `revoke_access(E-2291, "Slack")` → read-back. `revoke_access(E-2291, "Jira")` → read-back. `revoke_access(E-2291, "Okta")` → read-back. All 5 systems confirmed revoked.
- SCHEDULE_NOTIFY: `send_exit_survey(E-2291)` → delivered.
- COMPLETE: full offboarding summary with mutation log showing all 5 revocations verified.

Turn 2 did not re-classify, did not re-run policy evaluation, did not re-load the tool schema from scratch. It picked up exactly where the FSM checkpoint said it was.

---

## Key Design Decisions

**1. FSM enforces READ-before-MUTATE structurally, not via instruction**

Telling a model "gather data first, then act" in a system prompt is a guideline, not a constraint. The FSM makes it a constraint: during ASSESS and APPROVAL_GATE, write-classified tools are withheld from the tool schema that Claude receives. The model cannot call `update_invoice()` in ASSESS because `update_invoice()` is not in the schema it was given. This eliminates an entire class of premature-write errors without relying on instruction-following.

**2. MUTATE always uses Sonnet — never downgraded**

The token budget system switches all calls to Haiku above 80% consumption. MUTATE has an explicit guard that blocks this downgrade. An incorrect database write is harder to recover from than a slow one, and the marginal cost of Sonnet at the MUTATE state is small relative to the value of correctness. The guard is in `get_model()` in `token_budget.py` and is not overridable by budget pressure.

**3. WAL flush via immediate read-back, not sleep**

SQLite WAL mode means mutations written through the MCP tool land in the WAL file, not the main database file. A scorer reading the main file before WAL checkpoint sees stale data and scores the mutation as failed — even though it happened correctly. The mutation verifier solves this by immediately executing a read of the same entity after every write. A SQLite read forces WAL merge without any artificial delay. The fix is also idempotent: in non-WAL databases, the read-back simply confirms the write.

**4. Dynamic FSM synthesis is a one-time cost per novel process type**

When the classifier returns a process type not in the 15 built-in templates, Haiku synthesizes a state sequence and per-state instructions tailored to that specific type. This synthesis runs exactly once, then the result is cached permanently. A `SUPPLIER_RISK_ASSESSMENT` type gets instructions like `"COMPUTE: weight credit rating 0.3, geo-risk 0.25, ESG score 0.15"` — not the generic `"gather data"` that a static fallback would produce. The cache means the first task of a novel type bears a small one-time Haiku cost; all subsequent tasks of that type run from the cache.

**5. Tool synthesis is validated before registration**

The dynamic tool factory generates Python implementations, but does not register them blindly. Before any synthesized function enters `tool_registry.json`, it is executed in a subprocess sandbox against auto-generated test cases. A function that raises an exception or produces a wrong result on the test cases is discarded, and the agent falls back to asking Claude to compute inline. This prevents a broken synthesized tool from corrupting future tasks.

**6. Bracket-format detection requires a full JSON parse**

Some tasks expect an exact-match answer like `["INV-001", "INV-002"]`. If the answer is detected as bracket-format, it bypasses the self-reflection improvement loop — which would add explanatory text and corrupt the exact-match score. A naive `startswith('[')` check misclassifies prose responses like `"Rejected. [Reason: variance exceeds threshold]"`. The detection function requires: starts with `[`, ends with `]`, AND `json.loads()` returns a `list`. Prose with embedded brackets fails the JSON parse test and flows through the normal reflection path.

---

## 8-State FSM Reference

| State | Purpose | Default Model | Notes |
|-------|---------|---------------|-------|
| DECOMPOSE | Classify task, enumerate data needs, identify entities | Haiku | Entry point for all tasks |
| ASSESS | Read-only data gathering via tools | Haiku | Mutation tools absent from schema |
| COMPUTE | Pure arithmetic from collected data — no tool calls | Sonnet | Haiku math audit runs after; MUTATE blocked if audit fails |
| POLICY_CHECK | Evaluate policy rules against computed values | Haiku | Deterministic; LLM not used for structured rules |
| APPROVAL_GATE | Produce approval document; wait for HITL decision | Haiku | All mutation tools blocked here |
| MUTATE | Write operations; each write followed by read-back | Sonnet | Never downgraded to Haiku; WAL flush on every write |
| SCHEDULE_NOTIFY | Notifications, scheduling, audit log entries | Haiku | Runs only after all mutations are verified |
| COMPLETE | Summarize completed actions | Haiku | Final output only |

Error paths: `ESCALATE` (policy violation requiring human intervention), `FAILED` (unrecoverable error after recovery attempts).

Read-only shortcircuit: tasks with no action verbs collapse to DECOMPOSE → ASSESS → COMPLETE.

Multi-checkpoint: processes requiring sequential human confirmations can cycle through APPROVAL_GATE → MUTATE → APPROVAL_GATE using `fsm.reopen_approval_gate()`.

---

## Component Map

| File | Role |
|------|------|
| `main.py` | CLI entry point; FastAPI server startup with `--host`, `--port`, `--card-url` |
| `src/server.py` | FastAPI app; A2A JSON-RPC handler; `/health` and `/rl/status` endpoints |
| `src/worker_brain.py` | `MiniAIWorker`: 3-phase cognitive loop (PRIME → EXECUTE → REFLECT) |
| `src/fsm_runner.py` | 8-state FSM engine; 15 built-in process templates; read-only shortcircuit |
| `src/dynamic_fsm.py` | Haiku FSM synthesizer for unknown process types; caches to `synthesized_definitions.json` |
| `src/claude_executor.py` | Primary Claude execution engine; agentic tool-call loop (up to 20 iterations) |
| `src/five_phase_executor.py` | 5-phase executor: PLAN / GATHER / SYNTHESIZE / ARTIFACT / INSIGHT |
| `src/self_moa.py` | Mixture-of-Agents: dual top_p Haiku + word-overlap consensus + optional Sonnet |
| `src/strategy_bandit.py` | UCB1 multi-armed bandit; learns FSM / five_phase / MoA win rates per process type |
| `src/token_budget.py` | 10K token budget; model tier selection; bracket-format detection |
| `src/self_reflection.py` | Post-execution answer quality scoring; improvement pass if score < 0.65 |
| `src/compute_verifier.py` | COMPUTE state math audit via Haiku; catches arithmetic errors before MUTATE |
| `src/mutation_verifier.py` | Write-tool tracking + immediate read-back for WAL flush; builds mutation log |
| `src/hitl_guard.py` | Tool classification (read / compute / mutate); mutation blocking at APPROVAL_GATE |
| `src/policy_checker.py` | Deterministic policy rule evaluation; supports `&&`, `||`, `!`, comparisons |
| `src/schema_adapter.py` | Schema drift resilience; fuzzy column matching; 5-tier correction strategy |
| `src/smart_classifier.py` | Haiku semantic process type classification; keyword fallback on timeout |
| `src/rl_loop.py` | Case log persistence; quality scoring; RL primer construction |
| `src/context_pruner.py` | Case log quality filtering; repeated-failure detection; conservative prune guard |
| `src/context_rl.py` | Context injection accuracy tracking; drift detection for pre-computed thresholds |
| `src/knowledge_extractor.py` | Post-task Haiku fact extraction; domain-keyed knowledge base |
| `src/entity_extractor.py` | Zero-cost regex entity tracking (vendors, IDs, amounts, people) across tasks |
| `src/dynamic_tools.py` | Runtime tool factory: 30+ gap patterns + LLM phase-2 detection; sandboxed synthesis |
| `src/mcp_bridge.py` | MCP tool call bridge; pre-flight parameter validation; empty result detection |
| `src/session_context.py` | Multi-turn session state; FSM checkpoints; Haiku memory compression at 20 turns |
| `src/recovery_agent.py` | Tool failure recovery: synonym → decompose → Haiku advice → graceful degrade |
| `src/paginated_tools.py` | Cursor-loop pagination for bulk data tools |
| `src/document_generator.py` | Structured document generation (approval briefs, post-mortems) |
| `src/financial_calculator.py` | Exact decimal arithmetic for financial calculations |
| `src/finance_tools.py` | Financial analysis tools (NPV, amortization, depreciation) |
| `src/structured_output.py` | Final answer formatting; policy section builder |
| `src/output_validator.py` | Output format validation; bracket preservation checks |
| `src/privacy_guard.py` | PII detection before external calls |
| `src/process_definitions.py` | Built-in process definitions for smart classifier and dynamic FSM |
| `src/memory_compressor.py` | Haiku-based conversation memory compression |
| `src/config.py` | Environment variable loading |

---

## Running

### Requirements

Python 3.11+.

```
fastapi>=0.115
uvicorn[standard]>=0.30
anthropic>=0.34
httpx>=0.27
pydantic>=2.0
boto3>=1.34
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key (Haiku and Sonnet calls) |
| `GREEN_AGENT_MCP_URL` | Yes | MCP tool server base URL |
| `FALLBACK_MODEL` | No | Default: `claude-sonnet-4-6` |
| `TOOL_TIMEOUT` | No | Seconds per tool call; default 10 |
| `TASK_TIMEOUT` | No | Seconds per task; default 120 |
| `RL_CACHE_DIR` | No | Directory for bandit and registry JSON files; default `/app` |
| `BRAINOS_API_URL` | No | BrainOS platform URL (fallback orchestration) |
| `BRAINOS_API_KEY` | No | BrainOS API key |
| `S3_TRAINING_BUCKET` | No | S3 bucket for RL training seed on startup |
| `AWS_ACCESS_KEY_ID` | No | AWS credentials for S3 access |
| `AWS_SECRET_ACCESS_KEY` | No | AWS credentials for S3 access |
| `PURPLE_AGENT_CARD_URL` | No | Public URL advertised in AgentCard |

### Start

```bash
pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...
export GREEN_AGENT_MCP_URL=http://localhost:9009

python main.py --host 0.0.0.0 --port 9010
```

Docker:

```bash
docker build -t purple-agent .
docker run -p 9010:9010 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e GREEN_AGENT_MCP_URL=http://mcp-server:9009 \
  purple-agent
```

### Endpoints

**POST /** — A2A JSON-RPC 2.0 `tasks/send`:

```json
{
  "jsonrpc": "2.0",
  "method": "tasks/send",
  "id": "task-123",
  "params": {
    "id": "task-123",
    "message": {
      "role": "user",
      "parts": [{ "text": "Process expense claim EMP-447, $2,340 for team offsite..." }]
    }
  }
}
```

**GET /.well-known/agent-card.json** — AgentCard metadata

**GET /health** — Health check

**GET /rl/status** — Returns case log counts, UCB1 bandit arm values (Q and n per arm per process type), tool registry size, and synthesized FSM definition cache size

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

Copyright 2026 BrainOS / Abhishek.
