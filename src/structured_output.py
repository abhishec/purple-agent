"""
structured_output.py
Structured output formatter — returns precise sorted lists, not prose.
Ported from BrainOS memory-stack orchestrator layer.

Differentiator #3: Output parsers that produce ["Answer1", "Answer2"] sorted
lists — not prose. The benchmark rewards this precision.
"""
from __future__ import annotations
import json
import re


def extract_ranked_items(text: str) -> list[str]:
    """
    Extract ranked/listed items from LLM response text.
    Handles: JSON arrays, numbered lists, bullet lists, comma-separated.
    """
    # JSON array first
    json_match = re.search(r'\[.*?\]', text, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group())
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            pass

    # Numbered list: "1. item" or "1) item"
    numbered = re.findall(r'^\s*\d+[.)]\s+(.+)$', text, re.MULTILINE)
    if numbered:
        return [item.strip() for item in numbered]

    # Bullet list: "- item", "* item", "• item"
    bulleted = re.findall(r'^\s*[-*•]\s+(.+)$', text, re.MULTILINE)
    if bulleted:
        return [item.strip() for item in bulleted]

    # Comma-separated single line
    lines = [l.strip() for l in text.strip().split('\n') if l.strip()]
    if len(lines) == 1 and ',' in lines[0]:
        return [item.strip() for item in lines[0].split(',')]

    return []


def build_policy_section(policy_result: dict) -> str:
    """
    Format a deterministic policy check result for injection into system prompt.
    Makes it clear this is NOT up for interpretation by the LLM.
    """
    if not policy_result:
        return ""

    status = "PASSED" if policy_result.get("passed") else "FAILED"
    lines = [
        "",
        "## POLICY ENFORCEMENT RESULT (deterministic — do not override)",
        f"Status: {status}",
        f"Summary: {policy_result.get('summary', '')}",
    ]

    triggered = policy_result.get("triggeredRules", [])
    if triggered:
        lines.append(f"Triggered rules: {', '.join(r['ruleId'] for r in triggered)}")

    if policy_result.get("escalationLevel"):
        lines.append(f"Escalation level required: {policy_result['escalationLevel']}")

    lines.append("Your response MUST reflect this policy outcome exactly.")
    lines.append("")
    return "\n".join(lines)


def format_final_answer(answer: str, policy_result: dict | None = None) -> str:
    """
    Format the final answer with policy outcome prepended if applicable.
    """
    parts = []

    if policy_result and not policy_result.get("passed"):
        parts.append(f"[POLICY: {policy_result.get('summary', 'Policy check failed')}]")

    parts.append(answer.strip())
    return "\n".join(parts)
