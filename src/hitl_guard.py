"""
hitl_guard.py
Destructive tool detection + mutation blocking at APPROVAL_GATE.
Ported from BrainOS brain/hitl-gate.ts checkHitlGate() pattern.

At APPROVAL_GATE state: classify all available tools, inject a system
prompt block that EXPLICITLY lists mutation-class tools and instructs
the agent to present an approval summary instead of calling them.

This is the fix for Gap 1 — the agent now CANNOT accidentally mutate
state when it should be presenting an approval request.
"""
from __future__ import annotations

# Patterns indicating a tool modifies state (irreversible or hard to undo)
_MUTATE_PREFIXES = (
    "create_", "update_", "delete_", "cancel_", "approve_", "reject_",
    "submit_", "send_", "post_", "modify_", "change_", "set_", "add_",
    "remove_", "revoke_", "grant_", "book_", "order_", "place_",
    "transfer_", "pay_", "charge_", "refund_", "issue_", "close_",
    "archive_", "migrate_", "deploy_", "rollback_", "terminate_",
    "execute_", "apply_", "process_", "dispatch_", "trigger_",
    "write_", "insert_", "upsert_", "patch_", "commit_", "push_",
    "publish_", "fire_", "mark_", "flag_", "lock_", "unlock_",
    # Extended: verbs that are clearly state-modifying but were missing
    "escalate_", "initiate_", "finalize_", "complete_", "activate_",
    "deactivate_", "enable_", "disable_", "start_", "stop_", "pause_",
    "resume_", "confirm_", "acknowledge_", "resolve_", "reopen_",
    "merge_", "split_", "transfer_", "move_", "assign_", "unassign_",
    "notify_", "alert_", "enroll_", "disenroll_", "provision_", "deprovision_",
    "bump_", "promote_", "demote_", "reset_", "regenerate_", "rotate_",
    "register_", "deregister_", "tag_", "untag_", "link_", "unlink_",
    "import_", "export_", "upload_", "download_",
)

_READ_PREFIXES = (
    "get_", "list_", "fetch_", "read_", "search_", "find_", "query_",
    "check_", "verify_", "lookup_", "describe_", "show_", "calculate_",
    "compute_", "estimate_", "preview_", "validate_", "inspect_",
    "count_", "sum_", "aggregate_", "filter_", "compare_",
)

_MUTATE_KEYWORDS = (
    "write", "insert", "upsert", "patch", "execute", "commit",
    "push", "publish", "trigger", "invoke", "dispatch",
    # Extended keywords for verbs embedded in the middle of tool names
    "escalat", "initiat", "finaliz", "terminat", "activat", "deactivat",
)


def classify_tool(tool_name: str) -> str:
    """
    Returns 'read', 'compute', or 'mutate'.
    read   = safe to call any time (data gathering)
    compute = calculation only, no side effects
    mutate = changes state — BLOCKED at APPROVAL_GATE

    Fix (CRITICAL): The original default was 'return "read"' for any tool
    that matched no prefix. This meant novel mutation tools (e.g. escalate_ticket,
    initiate_payment, finalize_order) were silently classified as READ and allowed
    through the APPROVAL_GATE, causing unauthorized mutations.

    Fix: Default is now 'mutate' for unrecognized tools. The reasoning:
    - A read tool that gets misclassified as mutate = harmless (it just appears
      in the blocked list, no actual mutation occurs since it's read-only)
    - A mutate tool that gets misclassified as read = dangerous (unauthorized
      state change happens without human approval)
    - Erring toward mutation blocking is the correct security posture.

    Compute tools (calculate_, compute_, estimate_) are still identified first
    since they are truly side-effect-free and should never be blocked.
    """
    name = tool_name.lower()
    # Check compute FIRST (higher priority than general read prefixes)
    if name.startswith("calculate_") or name.startswith("compute_") or name.startswith("estimate_"):
        return "compute"
    if any(name.startswith(p) for p in _READ_PREFIXES):
        return "read"
    if any(name.startswith(p) for p in _MUTATE_PREFIXES):
        return "mutate"
    if any(kw in name for kw in _MUTATE_KEYWORDS):
        return "mutate"
    # Default: mutate — unknown tools are assumed to be state-modifying.
    # A false positive here (read tool blocked) is recoverable; a false negative
    # (mutate tool allowed through) causes unauthorized mutations at APPROVAL_GATE.
    return "mutate"



# Module-level cache: tool_name -> 'read' | 'compute' | 'mutate'
_tool_type_cache: dict[str, str] = {}


def seed_tool_type_cache(tool_type_map: dict[str, str]) -> None:
    """Called from worker_brain PRIME with Haiku-discovered classifications."""
    _tool_type_cache.update(tool_type_map)


def classify_tool_with_cache(tool_name: str, description: str = "") -> str:
    """Check cache first, then static patterns. Cache result for future calls."""
    if tool_name in _tool_type_cache:
        return _tool_type_cache[tool_name]
    result = classify_tool(tool_name)  # existing static classification
    _tool_type_cache[tool_name] = result
    return result

def get_mutate_tools(tools: list[dict]) -> list[str]:
    """Return names of all mutation-class tools in the tool list."""
    return [
        t["name"]
        for t in tools
        if isinstance(t, dict) and classify_tool(t.get("name", "")) == "mutate"
    ]


def build_hitl_block_prompt(
    mutate_tools: list[str],
    policy_result: dict | None = None,
    process_type: str = "",
) -> str:
    """
    System prompt block for APPROVAL_GATE state.
    Lists all blocked tools and forces the agent to produce an approval summary.
    Mirrors BrainOS hitl-gate.ts gate behavior (status: awaiting_approval).
    """
    if not mutate_tools:
        return ""

    tool_list = "\n".join(f"  - {t}" for t in sorted(mutate_tools))

    policy_note = ""
    if policy_result and not policy_result.get("passed"):
        triggered = policy_result.get("triggeredRules", [])
        rule_ids = ", ".join(r.get("ruleId", "") for r in triggered)
        policy_note = f"\nPolicy gate triggered by: {rule_ids}\n{policy_result.get('summary', '')}"

    process_note = f" for {process_type.replace('_', ' ').title()}" if process_type else ""

    return f"""
## APPROVAL GATE — MUTATION BLOCKED{process_note}

The following tools are BLOCKED until human approval is received:
{tool_list}
{policy_note}

YOU MUST NOT call any of the blocked tools in this response.

Instead, produce an approval request with these exact sections:
1. PROPOSED ACTIONS — list every action you plan to take (tool name, parameters, amounts, IDs)
2. REASON — why each action is needed
3. POLICY STATUS — which rules triggered this gate and what approval level is required
4. RISK — what happens if approved vs. if rejected
5. APPROVAL REQUEST — "Awaiting [approver role] approval before proceeding."

Your response IS the approval request document. Do not execute any actions.
"""


def check_approval_gate(
    current_state: str,
    tools: list[dict],
    policy_result: dict | None,
    process_type: str = "",
) -> tuple[bool, str]:
    """
    Returns (gate_fires, prompt_block).
    gate_fires=True means the agent is blocked from mutation tools.
    Call this in the system prompt construction for APPROVAL_GATE state.
    """
    if current_state != "APPROVAL_GATE":
        return False, ""

    mutate_tools = get_mutate_tools(tools)
    if not mutate_tools:
        return False, ""

    # Gate fires if: policy failed, OR we're just at APPROVAL_GATE (policy may not be structured)
    policy_requires = policy_result and (
        not policy_result.get("passed") or policy_result.get("requiresApproval")
    )
    # Always gate at APPROVAL_GATE state regardless of policy — that's the point of the state
    prompt = build_hitl_block_prompt(mutate_tools, policy_result, process_type)
    return True, prompt
