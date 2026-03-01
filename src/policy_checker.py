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

# Actions that require approval from a human (gate the mutation path)
_APPROVAL_ACTIONS = frozenset({"require_approval", "approve", "approval_required"})

# Actions that immediately block the request (stronger than approval)
_BLOCK_ACTIONS = frozenset({"block", "deny", "reject", "forbidden", "prohibited"})

# Actions that require escalation to a higher authority
_ESCALATE_ACTIONS = frozenset({"escalate", "escalation_required", "raise"})

# Actions that flag/warn but do NOT block (informational — passed=True unless blocked/escalated)
_WARN_ACTIONS = frozenset({"warn", "flag", "notify", "alert", "log", "audit"})


def evaluate_policy_rules(rules: list[dict], context: PolicyContext) -> dict:
    """
    Evaluate policy rules against a context object.
    Fully deterministic — no LLM, no DB.

    Fix (CRITICAL): Previously only recognized 3 action literals:
    'require_approval', 'escalate', 'block'. Any other action (e.g. 'deny',
    'warn', 'flag', 'reject') was silently ignored — the rule fired but had
    no effect on the passed/requiresApproval flags, potentially letting
    policy violations through the gate.

    Fix: Use action category sets (_APPROVAL_ACTIONS, _BLOCK_ACTIONS,
    _ESCALATE_ACTIONS, _WARN_ACTIONS) so all semantically equivalent
    action names are correctly classified. Unknown actions are treated as
    requiring approval (safe default — never silently pass).
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

    requires_approval = any(r["action"] in _APPROVAL_ACTIONS for r in triggered)
    escalation_required = any(r["action"] in _ESCALATE_ACTIONS for r in triggered)
    blocked = any(r["action"] in _BLOCK_ACTIONS for r in triggered)

    # Safe default: unknown actions are treated as requiring approval.
    # This prevents a novel action keyword from silently passing a triggered rule.
    known_actions = _APPROVAL_ACTIONS | _BLOCK_ACTIONS | _ESCALATE_ACTIONS | _WARN_ACTIONS
    unknown_action_triggered = any(
        r["action"] not in known_actions and r["action"] != ""
        for r in triggered
    )
    if unknown_action_triggered:
        requires_approval = True

    # Escalation level: pick the highest-priority level from all triggered rules.
    # Extended to include common policy levels not in the original 7-item list.
    level_priority = [
        "manager", "supervisor", "hr", "finance", "committee",
        "legal", "vp", "director", "cfo", "ciso", "ceo", "board",
    ]
    triggered_levels = [r["level"].lower() for r in triggered if r.get("level")]
    escalation_level = next(
        (l for l in reversed(level_priority) if l in triggered_levels), None
    )
    # If a level was set but isn't in our priority list, still surface it
    if not escalation_level and triggered_levels:
        escalation_level = triggered_levels[-1]

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

    # "in" operator: "field in [val1, val2, val3]" or "field in val1,val2"
    # Handles: amount_type in [refund, credit]  /  status in ['pending','review']
    in_match = re.match(r'^(\w+)\s+in\s+(.+)$', trimmed, re.IGNORECASE)
    if in_match:
        field, raw_list = in_match.group(1), in_match.group(2).strip()
        ctx_val = context.get(field)
        if ctx_val is None:
            return False
        # Strip surrounding brackets if present
        inner = raw_list.strip("[]")
        # Split on comma, strip quotes and whitespace from each item
        candidates = [v.strip().strip("'\"") for v in inner.split(",") if v.strip()]
        return str(ctx_val).lower() in [c.lower() for c in candidates]

    # "contains" operator: "field contains value" (field is a string/list, value is substring/member)
    contains_match = re.match(r'^(\w+)\s+contains\s+(.+)$', trimmed, re.IGNORECASE)
    if contains_match:
        field, raw_val = contains_match.group(1), contains_match.group(2).strip().strip("'\"")
        ctx_val = context.get(field)
        if ctx_val is None:
            return False
        if isinstance(ctx_val, list):
            return raw_val.lower() in [str(v).lower() for v in ctx_val]
        return raw_val.lower() in str(ctx_val).lower()

    # "not in" operator: "field not in [val1, val2]"
    not_in_match = re.match(r'^(\w+)\s+not\s+in\s+(.+)$', trimmed, re.IGNORECASE)
    if not_in_match:
        field, raw_list = not_in_match.group(1), not_in_match.group(2).strip()
        ctx_val = context.get(field)
        if ctx_val is None:
            return True  # not in anything → True
        inner = raw_list.strip("[]")
        candidates = [v.strip().strip("'\"") for v in inner.split(",") if v.strip()]
        return str(ctx_val).lower() not in [c.lower() for c in candidates]

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
    Supports &&, ||, !, comparisons, boolean fields, 'in', 'contains', 'not in'.
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
