from __future__ import annotations
from typing import Callable, Awaitable

import anthropic

from src.config import FALLBACK_MODEL, ANTHROPIC_API_KEY
from src.structured_output import format_final_answer

MAX_ITERATIONS = 20


async def solve_with_claude(
    task_text: str,
    policy_section: str,
    policy_result: dict | None,
    tools: list[dict],
    on_tool_call: Callable[[str, dict], Awaitable[dict]],
    session_id: str,
) -> str:
    """
    Direct Claude SDK fallback when BrainOS is unavailable.
    Runs an agentic tool-use loop up to MAX_ITERATIONS.
    Policy section is injected as hard constraints — not prompt-stuffed.
    """
    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    system_prompt = f"""You are an autonomous business operations agent running in a benchmark evaluation.

CRITICAL RULES — YOU MUST FOLLOW THESE:
1. NEVER ask the user for more information. All data you need is accessible via the provided tools.
2. Start calling tools IMMEDIATELY. Do not ask clarifying questions.
3. If a task mentions specific IDs (e.g. BK-001, ORD-001, EMP-MR), call the relevant tool with those IDs directly.
4. If you need to find records, call the appropriate lookup tool — don't ask the human.
5. Complete ALL required actions end-to-end before writing your final summary.
{policy_section}
Execute the task fully using the available tools. After completing all actions, provide a concise summary of what was done."""

    messages: list[dict] = [{"role": "user", "content": task_text}]

    for _ in range(MAX_ITERATIONS):
        response = await client.messages.create(
            model=FALLBACK_MODEL,
            max_tokens=4096,
            system=system_prompt,
            tools=tools,
            messages=messages,
        )

        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        if response.stop_reason == "end_turn":
            for block in assistant_content:
                if hasattr(block, "text"):
                    return format_final_answer(block.text, policy_result)
            return ""

        if response.stop_reason != "tool_use":
            break

        tool_results = []
        for block in assistant_content:
            if block.type != "tool_use":
                continue
            result = await on_tool_call(
                block.name,
                block.input if isinstance(block.input, dict) else {}
            )
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": str(result),
            })

        if tool_results:
            messages.append({"role": "user", "content": tool_results})

    return "Task completed. See tool call results for details."
