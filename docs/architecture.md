# Purple Agent — Architecture

## Overview

Purple Agent is an A2A-compatible benchmark endpoint built for AgentBeats / AgentX.  
It solves business tasks by calling tools exposed at the benchmark's MCP endpoint.

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
        ├─ 1. discover_tools(tools_endpoint, session_id)
        │       GET {tools_endpoint}/mcp/tools?session_id=...
        │       Returns Anthropic-format tool list for this session
        │
        ├─ 2. brainos_client.run_task()  [PRIMARY PATH]
        │       POST {BRAINOS_API_URL}/api/copilot/chat
        │       Streams SSE — handles tool_call events → calls on_tool_call()
        │       Raises BrainOSUnavailableError on failure
        │
        └─ 3. fallback_solver.solve_with_claude()  [FALLBACK]
                Anthropic SDK messages.create() loop
                Handles tool_use blocks → calls on_tool_call()
                Up to 20 iterations
                        │
                        ▼
              on_tool_call(tool_name, params)
                POST {tools_endpoint}/mcp
                { "tool": "...", "params": {...}, "session_id": "..." }
```

---

## Components

### `src/server.py`
FastAPI application exposing three routes:
- `GET /health` — liveness probe
- `GET /.well-known/agent-card.json` — agent metadata (name, URL, capabilities)
- `POST /` — main A2A handler (JSON-RPC 2.0, method=tasks/send)

### `src/executor.py`
Orchestrates the task resolution:
1. Discovers tools via MCP bridge
2. Tries BrainOS first
3. Falls back to direct Claude if BrainOS unavailable

### `src/brainos_client.py`
Streams tasks through BrainOS copilot SSE API.  
Handles `tool_call` events mid-stream by calling `on_tool_call()` and continuing.

### `src/fallback_solver.py`
Direct Claude SDK agentic loop.  
Runs up to `MAX_ITERATIONS=20` tool-call rounds.

### `src/mcp_bridge.py`
HTTP client for the benchmark's MCP tool endpoint:
- `discover_tools()` — GET tool list for session
- `call_tool()` — POST a tool invocation

### `src/config.py`
All configuration from environment variables:
- `BRAINOS_API_URL`, `BRAINOS_API_KEY`, `BRAINOS_ORG_ID`
- `ANTHROPIC_API_KEY`
- `FALLBACK_MODEL` (default: `claude-sonnet-4-6`)
- `TOOL_TIMEOUT`, `TASK_TIMEOUT`

---

## Deployment

- **Container**: Python 3.12 slim, non-root user `agentbeats`
- **Port**: 9010
- **Image**: `848269696611.dkr.ecr.us-east-1.amazonaws.com/agentbench-purple:latest`
- **ECS Service**: `agentbench-purple` in cluster `nexusbrain-training`
- **ALB routing**: Host header `purple.agentbench.usebrainos.com` → target group port 9010
- **TLS**: ACM cert for `purple.agentbench.usebrainos.com` on ALB HTTPS listener
