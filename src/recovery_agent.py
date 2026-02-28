"""
recovery_agent.py
Tool failure recovery — ported from BrainOS brain/recovery-agent.ts.

When a tool call returns an error, empty result, or stale data, the recovery
agent tries up to 4 strategies before graceful degradation:

  Strategy 1: Retry with corrected params (schema adapter already does this)
  Strategy 2: Try a synonym/alternative tool name
  Strategy 3: Decompose — split into smaller sub-calls
  Strategy 4: Ask Haiku for an alternative approach
  Strategy 5: Partial answer with what we have (graceful degrade)

All recovery is non-blocking and fire-and-forget safe.
A failed recovery never crashes the task — it always returns something.
"""
from __future__ import annotations
import asyncio
import json
from dataclasses import dataclass
from typing import Callable, Awaitable, Any

from src.config import ANTHROPIC_API_KEY

RECOVERY_MODEL = "claude-haiku-4-5-20251001"
RECOVERY_TIMEOUT = 8.0    # seconds per recovery attempt


@dataclass
class RecoveryResult:
    recovered: bool
    strategy: str   # "retry" | "synonym" | "decompose" | "llm_advice" | "graceful_degrade"
    result: Any
    explanation: str
    attempts: int


# ── Tool synonym map (alternative names for common tools) ─────────────────────
# If tool_name fails, try these synonyms in order

_TOOL_SYNONYMS: dict[str, list[str]] = {
    "get_vendor":            ["fetch_vendor", "lookup_vendor", "search_vendor", "get_supplier"],
    "get_employee":          ["fetch_employee", "lookup_employee", "get_user", "get_staff"],
    "get_invoice":           ["fetch_invoice", "lookup_invoice", "get_bill"],
    "get_purchase_order":    ["fetch_po", "get_po", "lookup_po", "fetch_purchase_order"],
    "get_customer":          ["fetch_customer", "lookup_customer", "get_account"],
    "get_budget_balance":    ["fetch_budget", "get_budget", "check_budget", "get_funds"],
    "list_expenses":         ["get_expenses", "fetch_expenses", "search_expenses"],
    "list_contracts":        ["get_contracts", "fetch_contracts", "search_contracts"],
    "create_expense":        ["submit_expense", "log_expense", "record_expense"],
    "create_purchase_order": ["submit_po", "create_po", "place_order"],
    "send_notification":     ["send_email", "notify_user", "post_message", "send_alert"],
    "send_email":            ["send_notification", "notify_user", "post_message"],
    "post_message":          ["send_slack", "send_notification", "send_message"],
}


def _is_empty_result(result: Any) -> bool:
    """True if the tool result is effectively empty/failed."""
    if result is None:
        return True
    if isinstance(result, dict):
        if result.get("error"):
            return True
        if "data" in result and not result["data"]:
            return True
        if result == {} or result == {"status": "error"}:
            return True
    if isinstance(result, list) and len(result) == 0:
        return True
    return False


def _is_error_result(result: Any) -> bool:
    """True if result contains an explicit error."""
    if isinstance(result, dict) and result.get("error"):
        return True
    return False


# ── Recovery strategies ───────────────────────────────────────────────────────

async def _try_synonym(
    tool_name: str,
    params: dict,
    call_fn: Callable,
    available_tools: list[dict],
) -> Any | None:
    """Strategy 2: try alternative tool names."""
    synonyms = _TOOL_SYNONYMS.get(tool_name, [])
    available_names = {t.get("name") for t in available_tools if t.get("name")}

    for syn in synonyms:
        if syn in available_names:
            try:
                result = await asyncio.wait_for(call_fn(syn, params), timeout=RECOVERY_TIMEOUT)
                if not _is_empty_result(result):
                    return result
            except Exception:
                continue
    return None


async def _try_decompose(
    tool_name: str,
    params: dict,
    call_fn: Callable,
) -> Any | None:
    """Strategy 3: try a simpler version of the call (fewer params)."""
    if not params:
        return None

    # Try removing optional/complex params one by one
    essential_keys = {"id", "name", "email", "organization_id", "session_id"}
    simplified = {k: v for k, v in params.items() if k in essential_keys or not k.startswith("filter")}

    if simplified == params:
        return None  # Nothing to simplify

    try:
        result = await asyncio.wait_for(call_fn(tool_name, simplified), timeout=RECOVERY_TIMEOUT)
        if not _is_empty_result(result):
            return result
    except Exception:
        pass
    return None


async def _ask_haiku_alternative(
    tool_name: str,
    params: dict,
    error_msg: str,
    available_tools: list[dict],
) -> str:
    """Strategy 4: ask Haiku what to try instead."""
    if not ANTHROPIC_API_KEY or not available_tools:
        return ""
    try:
        import anthropic
        tool_list = [t.get("name") for t in available_tools[:15] if t.get("name")]
        client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
        resp = await asyncio.wait_for(
            client.messages.create(
                model=RECOVERY_MODEL,
                max_tokens=80,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Tool '{tool_name}' failed: {error_msg[:100]}\n"
                        f"Available tools: {', '.join(tool_list)}\n"
                        "Reply with just the best alternative tool name to try, or 'none'."
                    ),
                }],
            ),
            timeout=4.0,
        )
        suggestion = resp.content[0].text.strip().strip('"').strip("'") if resp.content else ""
        if suggestion and suggestion != "none" and any(t.get("name") == suggestion for t in available_tools):
            return suggestion
    except Exception:
        pass
    return ""


# ── Public API ────────────────────────────────────────────────────────────────

async def recover_tool_call(
    tool_name: str,
    params: dict,
    failed_result: Any,
    call_fn: Callable[[str, dict], Awaitable[Any]],
    available_tools: list[dict] | None = None,
) -> RecoveryResult:
    """
    Attempt to recover a failed/empty tool call.
    call_fn: async (tool_name, params) -> result
    Returns RecoveryResult — always returns something, never raises.
    """
    available_tools = available_tools or []
    error_msg = ""
    if isinstance(failed_result, dict):
        error_msg = str(failed_result.get("error", ""))

    attempts = 0

    # Strategy 2: synonym tools
    attempts += 1
    syn_result = await _try_synonym(tool_name, params, call_fn, available_tools)
    if syn_result is not None:
        return RecoveryResult(
            recovered=True,
            strategy="synonym",
            result=syn_result,
            explanation=f"Recovered '{tool_name}' using synonym tool",
            attempts=attempts,
        )

    # Strategy 3: decompose (simplify params)
    attempts += 1
    decomp_result = await _try_decompose(tool_name, params, call_fn)
    if decomp_result is not None:
        return RecoveryResult(
            recovered=True,
            strategy="decompose",
            result=decomp_result,
            explanation=f"Recovered '{tool_name}' with simplified parameters",
            attempts=attempts,
        )

    # Strategy 4: ask Haiku for alternative
    attempts += 1
    alt_tool = await _ask_haiku_alternative(tool_name, params, error_msg, available_tools)
    if alt_tool:
        try:
            alt_result = await asyncio.wait_for(call_fn(alt_tool, params), timeout=RECOVERY_TIMEOUT)
            if not _is_empty_result(alt_result):
                return RecoveryResult(
                    recovered=True,
                    strategy="llm_advice",
                    result=alt_result,
                    explanation=f"Recovered using Haiku-suggested alternative: '{alt_tool}'",
                    attempts=attempts,
                )
        except Exception:
            pass

    # Strategy 5: graceful degradation
    return RecoveryResult(
        recovered=False,
        strategy="graceful_degrade",
        result={"error": error_msg, "tool": tool_name, "recovered": False},
        explanation=(
            f"Tool '{tool_name}' unavailable after {attempts} recovery attempts. "
            "Proceeding with available data."
        ),
        attempts=attempts,
    )


def wrap_with_recovery(
    call_fn: Callable[[str, dict], Awaitable[Any]],
    available_tools: list[dict] | None = None,
) -> Callable[[str, dict], Awaitable[Any]]:
    """
    Wraps a tool call function with automatic recovery.
    Drop-in replacement for on_tool_call in worker_brain._execute().

    Usage:
        on_tool_call = wrap_with_recovery(raw_call_fn, available_tools=self._tools)
    """
    async def wrapped(tool_name: str, params: dict) -> Any:
        result = await call_fn(tool_name, params)
        if _is_empty_result(result) or _is_error_result(result):
            recovery = await recover_tool_call(
                tool_name=tool_name,
                params=params,
                failed_result=result,
                call_fn=call_fn,
                available_tools=available_tools,
            )
            return recovery.result
        return result

    return wrapped
