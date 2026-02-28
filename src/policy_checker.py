"""
policy_checker.py
Deterministic policy rule evaluator — zero LLM, zero DB.
Ported from BrainOS process-intelligence layer.

Differentiator #1: When the benchmark sends a policy_doc with structured rules,
we evaluate them deterministically instead of prompt-stuffing.
"""
from __future__ import annotations
import re
from typing import Any

PolicyContext = dict[str, Any]


def evaluate_policy_rules(rules: list[dict], context: PolicyContext) -> dict:
    """
    Evaluate policy rules against a context object.
    Fully deterministic — no LLM, no DB.
    """
    triggered = []

    for rule in rules:
        if _evaluate_condition(rule.get("condition", ""), context):
            triggered.append({
                "ruleId": rule.get("id", ""),
                "action": rule.get("action", ""),
                "level": rule.get("level", ""),
                "description": rule.get("description", ""),
            })

    requires_approval = any(r["action"] == "require_approval" for r in triggered)
    escalation_required = any(r["action"] == "escalate" for r in triggered)
    blocked = any(r["action"] == "block" for r in triggered)

    level_priority = ["manager", "hr", "finance", "committee", "legal", "cfo", "ciso"]
    triggered_levels = [r["level"] for r in triggered]
    escalation_level = next(
        (l for l in reversed(level_priority) if l in triggered_levels), None
    )

    passed = not blocked and not escalation_required and not requires_approval

    return {
        "passed": passed,
        "requiresApproval": requires_approval,
        "escalationRequired": escalation_required,
        "triggeredRules": triggered,
        "escalationLevel": escalation_level if triggered else None,
        "summary": (
            "All policy rules passed"
            if passed
            else f"{len(triggered)} rule(s) triggered: {', '.join(r['ruleId'] for r in triggered)}"
        ),
    }


def _evaluate_atom(atom: str, context: PolicyContext) -> bool:
    trimmed = atom.strip()

    # Negation: "!field"
    if trimmed.startswith("!"):
        return not bool(context.get(trimmed[1:].strip()))

    # Comparison: "field op value"
    m = re.match(r'^(\w+)\s*(>=|<=|===|!==|==|!=|>|<)\s*(.+)$', trimmed)
    if m:
        field, op, raw = m.group(1), m.group(2), m.group(3).strip()
        ctx_val = context.get(field)
        if ctx_val is None:
            return False
        str_val = raw.strip("'\"")
        try:
            num_val = float(raw)
            ctx_num = float(ctx_val)
            if op == ">":  return ctx_num > num_val
            if op == "<":  return ctx_num < num_val
            if op == ">=": return ctx_num >= num_val
            if op == "<=": return ctx_num <= num_val
        except (TypeError, ValueError):
            pass
        if op in ("===", "=="): return str(ctx_val) == str_val
        if op in ("!==", "!="): return str(ctx_val) != str_val

    # Boolean field: "has_unvested_equity"
    if re.match(r'^\w+$', trimmed):
        return bool(context.get(trimmed))

    return False


def _evaluate_condition(condition: str, context: PolicyContext) -> bool:
    """
    Supports &&, ||, !, comparisons, boolean fields.
    Precedence: NOT > AND > OR.
    """
    try:
        trimmed = condition.strip()
        if " || " in trimmed:
            return any(_evaluate_condition(p.strip(), context) for p in trimmed.split(" || "))
        if " && " in trimmed:
            return all(_evaluate_condition(p.strip(), context) for p in trimmed.split(" && "))
        return _evaluate_atom(trimmed, context)
    except Exception:
        return False
