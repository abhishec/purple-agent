from __future__ import annotations
import asyncio
import json
from typing import Callable, Awaitable

from src.brainos_client import run_task, BrainOSUnavailableError
from src.fallback_solver import solve_with_claude
from src.mcp_bridge import discover_tools, call_tool
from src.policy_checker import evaluate_policy_rules
from src.structured_output import build_policy_section
from src.config import GREEN_AGENT_MCP_URL


def _parse_policy(policy_doc: str) -> tuple[dict | None, str]:
    """
    Parse policy_doc string.
    - If JSON with a 'rules' array → evaluate deterministically (zero LLM)
    - Otherwise → inject as plain text into system prompt
    Returns (policy_result | None, policy_section_string).
    """
    if not policy_doc:
        return None, ""

    # Try structured JSON policy
    try:
        parsed = json.loads(policy_doc)
        if isinstance(parsed, dict) and "rules" in parsed:
            rules = parsed["rules"]
            context = parsed.get("context", {})
            result = evaluate_policy_rules(rules, context)
            section = build_policy_section(result)
            return result, section
    except (json.JSONDecodeError, TypeError):
        pass

    # Plain text policy — inject as-is
    return None, f"\nPOLICY:\n{policy_doc}\n"


async def handle_task(
    task_text: str,
    policy_doc: str,
    tools_endpoint: str,
    task_id: str,
    session_id: str,
) -> str:
    """
    Main task handler:
    1. Parse policy_doc — deterministic evaluation if structured JSON
    2. Discover tools from MCP endpoint
    3. Try BrainOS first
    4. Fall back to direct Claude SDK loop if BrainOS unavailable
    """
    ep = tools_endpoint or GREEN_AGENT_MCP_URL

    # Policy enforcement — deterministic if structured, string if prose
    policy_result, policy_section = _parse_policy(policy_doc)

    try:
        tools = await discover_tools(ep, session_id=session_id)
    except Exception:
        tools = []

    async def on_tool_call(tool_name: str, params: dict) -> dict:
        try:
            return await call_tool(ep, tool_name, params, session_id)
        except Exception as e:
            return {"error": str(e)}

    system_context = f"""Task ID: {task_id}
Session ID: {session_id}
Tools endpoint: {ep}
{policy_section}"""

    # Try BrainOS first
    try:
        answer = await run_task(
            message=task_text,
            system_context=system_context,
            on_tool_call=on_tool_call,
            session_id=session_id,
        )
        return answer
    except BrainOSUnavailableError:
        pass

    # Fallback to direct Claude
    return await solve_with_claude(
        task_text=task_text,
        policy_section=policy_section,
        policy_result=policy_result,
        tools=tools,
        on_tool_call=on_tool_call,
        session_id=session_id,
    )
