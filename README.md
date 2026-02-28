# Purple Agent — AgentX Competition Entry

**Live endpoint:** `https://purple.agentbench.usebrainos.com`

> An A2A-compatible agent for the AgentBeats benchmark — built on top of BrainOS with a direct Claude fallback.

---

## Endpoints

| What | URL | Method |
|------|-----|--------|
| Health check | `https://purple.agentbench.usebrainos.com/health` | GET |
| Agent card | `https://purple.agentbench.usebrainos.com/.well-known/agent-card.json` | GET |
| A2A entry point | `https://purple.agentbench.usebrainos.com/` | POST |

---

## How it works

### Request format (from benchmark)

```json
{
  "jsonrpc": "2.0",
  "method": "tasks/send",
  "params": {
    "id": "SESSION-ID",
    "message": {
      "role": "user",
      "parts": [{ "text": "TASK DESCRIPTION" }]
    },
    "metadata": {
      "policy_doc": "BUSINESS RULES",
      "tools_endpoint": "https://benchmark.usebrainos.com/mcp",
      "session_id": "SESSION-ID"
    }
  }
}
```

### Response format

```json
{
  "jsonrpc": "2.0",
  "result": {
    "id": "SESSION-ID",
    "status": { "state": "completed" },
    "artifacts": [{ "parts": [{ "text": "FINAL ANSWER" }] }]
  }
}
```

---

## Architecture

```
POST /
  └── executor.handle_task()
        ├── mcp_bridge.discover_tools()     ← GET tools for this session
        ├── brainos_client.run_task()        ← try BrainOS SSE stream
        │     └── on_tool_call()             ← forward tool calls to MCP endpoint
        └── fallback_solver.solve_with_claude()  ← direct Claude SDK if BrainOS down
              └── agentic tool-use loop (up to 20 iterations)
```

### Key design decisions

- **BrainOS-first**: tasks route through the BrainOS copilot API (SSE stream). If unavailable, falls back automatically.
- **Policy via system prompt**: `policy_doc` is injected into every Claude call as hard constraints.
- **Tool discovery per session**: only tools registered for the current `session_id` are loaded — avoids overloading the context with 130+ tools.
- **Agentic loop**: up to 20 tool-call iterations per task, covering multi-step business workflows.

---

## Running locally

```bash
pip install -r requirements.txt
cp .env.example .env
python main.py --host 0.0.0.0 --port 9010 --card-url http://localhost:9010
```

---

## Docker

```bash
docker build -t purple-agent .
docker run -p 9010:9010 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e BRAINOS_API_KEY=... \
  -e BRAINOS_ORG_ID=... \
  purple-agent
```

---

## Source layout

```
purple-agent/
├── main.py                 ← CLI entrypoint (--host, --port, --card-url)
├── requirements.txt
├── Dockerfile
└── src/
    ├── server.py           ← FastAPI app, all three endpoints
    ├── executor.py         ← task orchestration (BrainOS → Claude fallback)
    ├── brainos_client.py   ← BrainOS SSE streaming client
    ├── fallback_solver.py  ← direct Claude SDK agentic loop
    ├── mcp_bridge.py       ← tool discovery + tool calls
    └── config.py           ← env-var config
```
