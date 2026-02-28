from __future__ import annotations
import json
from typing import Callable, Awaitable

from src.brainos_client import run_task, BrainOSUnavailableError
from src.fallback_solver import solve_with_claude
from src.mcp_bridge import discover_tools, call_tool
from src.policy_checker import evaluate_policy_rules
from src.structured_output import build_policy_section
from src.rl_loop import build_rl_primer, record_outcome
from src.session_context import (
    get_or_create, add_turn, get_context_prompt,
    set_process_type, is_multi_turn,
)
from src.fsm_runner import FSMRunner
from src.config import GREEN_AGENT_MCP_URL


def _parse_policy(policy_doc: str) -> tuple[dict | None, str]:
    """
    Parse policy_doc:
    - JSON with 'rules' array → evaluate deterministically (zero LLM)
    - Plain text → inject as-is
    """
    if not policy_doc:
        return None, ""
    try:
        parsed = json.loads(policy_doc)
        if isinstance(parsed, dict) and "rules" in parsed:
            result = evaluate_policy_rules(parsed["rules"], parsed.get("context", {}))
            return result, build_policy_section(result)
    except (json.JSONDecodeError, TypeError):
        pass
    return None, f"\nPOLICY:\n{policy_doc}\n"


async def handle_task(
    task_text: str,
    policy_doc: str,
    tools_endpoint: str,
    task_id: str,
    session_id: str,
) -> str:
    """
    Main task handler — wires RL + multi-turn context + FSM + policy + BrainOS/Claude.

    Execution order:
    1. RL primer — inject learned patterns from past similar tasks
    2. Multi-turn context — inject compressed session history
    3. FSM — detect process type, build phase-aware prompt
    4. Policy — deterministic rule evaluation (if structured JSON)
    5. BrainOS first, Claude fallback
    6. Record outcome → RL case log
    """
    ep = tools_endpoint or GREEN_AGENT_MCP_URL

    # ── 1. RL primer ─────────────────────────────────────────────────────────
    rl_primer = build_rl_primer(task_text)

    # ── 2. Multi-turn session context ────────────────────────────────────────
    multi_turn_ctx = ""
    if is_multi_turn(session_id):
        multi_turn_ctx = get_context_prompt(session_id)

    # ── 3. FSM — process type detection + phase prompt ───────────────────────
    fsm = FSMRunner(task_text=task_text, session_id=session_id)
    set_process_type(session_id, fsm.process_type)
    phase_prompt = fsm.build_phase_prompt()

    # ── 4. Policy enforcement ─────────────────────────────────────────────────
    policy_result, policy_section = _parse_policy(policy_doc)

    # Apply policy to FSM if we're at POLICY_CHECK state
    if policy_result and fsm.current_state.value == "POLICY_CHECK":
        fsm.apply_policy(policy_result)
        phase_prompt = fsm.build_phase_prompt()

    # ── 5. Tool discovery ─────────────────────────────────────────────────────
    try:
        tools = await discover_tools(ep, session_id=session_id)
    except Exception:
        tools = []

    async def on_tool_call(tool_name: str, params: dict) -> dict:
        try:
            return await call_tool(ep, tool_name, params, session_id)
        except Exception as e:
            return {"error": str(e)}

    # Build full system context
    system_context_parts = [
        f"Task ID: {task_id}",
        f"Session ID: {session_id}",
        f"Tools endpoint: {ep}",
    ]
    if rl_primer:
        system_context_parts.append(rl_primer)
    if multi_turn_ctx:
        system_context_parts.append(multi_turn_ctx)
    system_context_parts.append(phase_prompt)
    if policy_section:
        system_context_parts.append(policy_section)

    system_context = "\n\n".join(system_context_parts)

    # ── 5. Execute — BrainOS first, Claude fallback ───────────────────────────
    answer = ""
    tool_count = 0
    error = None

    # Record user turn in session
    add_turn(session_id, "user", task_text)

    try:
        answer = await run_task(
            message=task_text,
            system_context=system_context,
            on_tool_call=on_tool_call,
            session_id=session_id,
        )
    except BrainOSUnavailableError:
        try:
            answer, tool_count = await solve_with_claude(
                task_text=task_text,
                policy_section=policy_section,
                policy_result=policy_result,
                tools=tools,
                on_tool_call=on_tool_call,
                session_id=session_id,
            )
        except Exception as e:
            error = str(e)
            answer = f"Task failed: {error}"

    # Record agent response in session (multi-turn)
    if answer:
        add_turn(session_id, "assistant", answer)

    # ── 6. RL outcome recording ───────────────────────────────────────────────
    policy_passed = policy_result.get("passed") if policy_result else None
    quality = record_outcome(
        task_text=task_text,
        answer=answer,
        tool_count=tool_count,
        policy_passed=policy_passed,
        error=error,
    )

    # Append FSM summary to answer if process was complex
    if fsm.process_type != "general":
        summary = fsm.get_summary()
        if summary.get("requires_hitl"):
            answer += f"\n\n[Process: {summary['process_type']} | Requires human approval]"

    return answer
