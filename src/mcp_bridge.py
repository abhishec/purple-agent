from __future__ import annotations
import json
import httpx
from src.config import TOOL_TIMEOUT


def validate_tool_call(
    tool_name: str,
    params: dict,
    tools_list: list[dict],
) -> tuple[bool, str]:
    """Pre-flight: verify tool exists and required params are present.

    Returns (valid, error_msg). If tools_list is empty we cannot validate —
    allow through rather than blocking legitimate calls.
    """
    if not tools_list:
        return True, ""  # can't validate without schema — allow through

    tool_schema = next((t for t in tools_list if t.get("name") == tool_name), None)
    if tool_schema is None:
        # Tool not in discovered list — likely hallucinated
        available = [t.get("name") for t in tools_list[:10]]
        return False, f"Tool '{tool_name}' not in available tools. Available: {available}"

    # Check required params — handle both input_schema (Anthropic) and inputSchema (MCP spec)
    input_schema = tool_schema.get("input_schema") or tool_schema.get("inputSchema", {})
    required = input_schema.get("required", [])
    missing = [r for r in required if r not in params]
    if missing:
        return False, f"Tool '{tool_name}' missing required params: {missing}"

    return True, ""


def _is_empty_result(result: dict) -> bool:
    """Return True when the tool result carries no useful data."""
    if "error" in result:
        return False  # errors are meaningful — not "empty"
    for key in ("data", "result", "items", "records", "rows"):
        val = result.get(key)
        if val is not None:
            if isinstance(val, (list, dict)) and len(val) == 0:
                continue  # empty container — keep checking other keys
            return False  # non-empty value found
    # If none of the expected keys had content, consider it empty
    return all(
        (result.get(k) is None or result.get(k) == [] or result.get(k) == {})
        for k in ("data", "result", "items", "records", "rows")
    )


async def discover_tools(tools_endpoint: str, session_id: str = "") -> list[dict]:
    """POST {tools_endpoint}/mcp — discover tools via MCP JSON-RPC 2.0 (tools/list).

    Returns Anthropic-format tool list.
    Pass session_id to get only the tools registered for that specific task session.
    """
    url = f"{tools_endpoint}/mcp"
    if session_id:
        url = f"{url}?session_id={session_id}"

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {},
    }

    async with httpx.AsyncClient(timeout=TOOL_TIMEOUT) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

    # MCP response: {"result": {"tools": [{"name": ..., "description": ..., "inputSchema": {...}}]}}
    tools = data.get("result", {}).get("tools", [])
    return [
        {
            "name": t["name"],
            "description": t.get("description", ""),
            # MCP uses "inputSchema"; Anthropic uses "input_schema"
            "input_schema": t.get("inputSchema") or t.get("input_schema") or {
                "type": "object", "properties": {}
            },
        }
        for t in tools
    ]


async def call_tool(
    tools_endpoint: str,
    tool_name: str,
    params: dict,
    session_id: str,
    tools_list: list[dict] | None = None,
) -> dict:
    """POST {tools_endpoint}/mcp — call a tool via MCP JSON-RPC 2.0 (tools/call).

    Runs pre-flight validation via validate_tool_call() when tools_list is
    provided.  Invalid calls return immediately without a network round-trip.
    """
    # Pre-flight validation
    valid, error_msg = validate_tool_call(tool_name, params, tools_list or [])
    if not valid:
        return {"error": error_msg, "validation_failed": True}

    url = f"{tools_endpoint}/mcp"
    if session_id:
        url = f"{url}?session_id={session_id}"

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": params,
        },
    }

    async with httpx.AsyncClient(timeout=TOOL_TIMEOUT) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

    # JSON-RPC error
    if "error" in data:
        err = data["error"]
        return {"error": err.get("message", str(err)) if isinstance(err, dict) else str(err)}

    result = data.get("result", {})

    # MCP tool error response
    if result.get("isError"):
        content = result.get("content", [])
        error_text = " ".join(
            c.get("text", "") for c in content if c.get("type") == "text"
        )
        return {"error": error_text or "Tool returned an error"}

    # Parse MCP content array → dict
    content = result.get("content", [])
    if not content:
        return result  # return as-is if no content

    # Single text item: try JSON parse, otherwise wrap in result key
    if len(content) == 1 and content[0].get("type") == "text":
        text = content[0]["text"]
        try:
            return json.loads(text)
        except Exception:
            return {"result": text}

    # Multiple items or non-text: return content array
    return {"content": content}
