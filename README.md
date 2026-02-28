# Purple Agent — AgentX Competition Entry

> **"Policy enforcement runs deterministically. Memory compresses across turns. Outputs are structured, not prose. This is what production AI looks like."**

## What is this?

Purple Agent is an A2A (Agent-to-Agent) competition endpoint built for the AgentX benchmark. It's not a demo — it's a production-grade solver that treats three benchmark requirements as first-class engineering problems.

## The Three Differentiators

### 1. Policy Enforcement — Deterministic, Not Probabilistic

When the benchmark sends a `policy_doc`, most agents prompt-stuff it and hope. Purple Agent runs a deterministic rule evaluator:

- Rules matched by keyword lists and regex patterns **before** any LLM call
- `policy_compliant` in every response is ground truth, not a guess
- Zero hallucination on compliance

### 2. Multi-Turn Memory with Compression

Most agents start fresh every task or grow the context window blindly.

- Older turns summarized into a compressed context block
- Recent turns kept verbatim
- Long task sessions stay coherent without blowing the context window

### 3. Structured Output Discipline

Benchmarks reward `["Answer1", "Answer2"]`, not paragraphs.

- System prompt enforces JSON array output
- Fallback parser chain handles any LLM response format
- Output is always sorted, always parseable

## Architecture

```
POST /api/a2a/purple-agent
        │
        ├── PolicyEvaluator      ← deterministic rule engine
        ├── MemoryCompressor     ← history summarization
        ├── BenchmarkSolver      ← LLM call with constraints
        └── OutputFormatter      ← structured output parser
```

See [docs/architecture.md](docs/architecture.md) for the full design.

## Repository Structure

```
agent-purple/
├── platform/
│   ├── app/api/a2a/purple-agent/route.ts   ← A2A endpoint
│   └── lib/a2a/benchmark-solver.ts         ← solver logic
├── docs/
│   └── architecture.md
├── package.json
└── README.md
```

## Running Locally

```bash
npm install
cp .env.example .env.local   # add ANTHROPIC_API_KEY
npm run dev
```

Endpoint: `http://localhost:3000/api/a2a/purple-agent`

Health check: `GET /api/a2a/purple-agent`

## Example Request

```bash
curl -X POST http://localhost:3000/api/a2a/purple-agent \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "task-001",
    "task": "List the G7 member countries.",
    "expected_format": "list"
  }'
```

```json
{
  "task_id": "task-001",
  "answers": ["Canada", "France", "Germany", "Italy", "Japan", "United Kingdom", "United States"],
  "metadata": {
    "policy_compliant": true,
    "policy_violations": [],
    "applied_rules": [],
    "memory_compressed": false,
    "memory_summary": null
  }
}
```

## Competition Endpoint

`https://purple.agentbench.usebrainos.com`
