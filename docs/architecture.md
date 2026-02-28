# Purple Agent — Architecture

## Overview

Purple Agent is a competition-ready A2A (Agent-to-Agent) endpoint built for structured benchmark tasks. It solves three problems that most LLM wrappers ignore:

---

## 1. Policy Enforcement (Deterministic)

Most agents stuff a `policy_doc` into the system prompt and hope the LLM obeys.  
Purple Agent runs a **deterministic rule evaluator** before any LLM call:

```
PolicyDoc → PolicyEvaluator.evaluate(task, policy)
           → { compliant, violations, applied_rules }
```

- Rules are matched by **keyword lists** or **regex patterns**
- `deny` rules produce violations before the LLM sees the task
- Violations are injected as hard constraints in the system prompt
- The `policy_compliant` flag in every response is **ground truth**, not a hallucination

**Result:** Zero hallucination on compliance. Policy is enforced before generation, not hoped for after.

---

## 2. Multi-Turn Memory with Compression

Most agents start fresh every task or blindly grow the context window.  
Purple Agent uses a **MemoryCompressor** that:

1. Keeps the last N turns verbatim (recency wins)
2. Summarizes older turns into a single `[Prior context summary: ...]` turn
3. Injects the compressed history into every call

```
history[0..n] → compress → [summary_turn, ...recent_turns]
```

**Result:** Context gets smarter, not just bigger. Long tasks stay coherent.

---

## 3. Structured Output Discipline

Benchmarks reward precision. Prose answers score poorly.  
Purple Agent enforces structure at two levels:

**System prompt instruction:**
> "Return answers as a JSON array of strings: ["Answer1", "Answer2"]. Sort alphabetically. No prose."

**Output parser fallback chain:**
1. JSON array extraction (primary)
2. Numbered/bulleted list parsing
3. Comma/semicolon split
4. Single-string fallback

**Result:** `["Answer1", "Answer2"]` — sorted, parseable, exact.

---

## Request / Response Schema

### POST `/api/a2a/purple-agent`

**Request:**
```json
{
  "task_id": "task-001",
  "task": "List the capitals of France and Germany.",
  "policy_doc": {
    "rules": [
      { "id": "r1", "type": "deny", "description": "No profanity", "keywords": ["..."] }
    ],
    "default_action": "allow"
  },
  "history": [
    { "role": "user", "content": "Previous question..." },
    { "role": "assistant", "content": "Previous answer..." }
  ],
  "expected_format": "list",
  "context": "Optional additional context"
}
```

**Response:**
```json
{
  "task_id": "task-001",
  "answers": ["Berlin", "Paris"],
  "metadata": {
    "policy_compliant": true,
    "policy_violations": [],
    "applied_rules": [],
    "memory_compressed": false,
    "memory_summary": null
  }
}
```

---

## Component Map

```
platform/
├── app/api/a2a/purple-agent/route.ts   ← HTTP handler (Next.js App Router)
└── lib/a2a/benchmark-solver.ts
    ├── PolicyEvaluator                  ← deterministic rule engine
    ├── MemoryCompressor                 ← history summarisation
    ├── OutputFormatter                  ← structured output parser
    └── BenchmarkSolver                  ← orchestrator
```
