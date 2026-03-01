"""
finance_tools.py
Financial computation support — two usage patterns:

Pattern A — Synthetic tool (amortization only):
  Loan amortization is the one calculation too complex for Claude to do natively
  (360-period compounding, per-period integer rounding, payment schedule).
  Exposed as finance_loan_amortization in FINANCE_TOOL_DEFINITIONS.
  Intercepted in worker_brain._direct_call before MCP network round-trip.

Pattern B — Context injection (all other financial calculations):
  Variance checks, proration, SLA credits, depreciation, revenue recognition.
  These are pre-computed in the PRIME phase using financial_calculator.py and
  injected as ground-truth facts into the COMPUTE state prompt.
  Zero query budget cost. ~30 tokens instead of 560.
  FSM COMPUTE state semantics preserved ("DO NOT call any tools").

Why this split:
  amortization = 360 iterations, per-step rounding accumulates cent drift.
  Claude cannot produce correct amortization tables natively.
  Everything else = single-formula calculations Claude handles precisely.
"""
from __future__ import annotations

from src.financial_calculator import (
    apply_variance_check,
    prorated_amount,
    prorated_for_period,
    apply_early_termination_fee,
    compute_sla_credit,
    amortize_loan,
    payment_plan_summary,
    straight_line_depreciation,
    recognize_revenue,
)

# ── Synthetic tool definition — amortization only ─────────────────────────────
# All other calculations are handled via build_finance_context() injection.

FINANCE_TOOL_DEFINITIONS = [
    {
        "name": "finance_loan_amortization",
        "description": (
            "Generate full loan amortization schedule with monthly payment breakdown. "
            "Returns summary (total interest, monthly payment) and first 3 payments. "
            "Use for payroll loans, vendor financing, equipment leases."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "principal": {"type": "number", "description": "Loan principal in dollars"},
                "annual_rate_pct": {"type": "number", "description": "Annual interest rate %, e.g. 6.5"},
                "months": {"type": "number", "description": "Loan term in months"},
            },
            "required": ["principal", "annual_rate_pct", "months"],
        },
    },
]


def call_finance_tool(tool_name: str, params: dict) -> dict:
    """Route finance_* synthetic tool calls to local Python calculation."""
    try:
        if tool_name == "finance_loan_amortization":
            schedule = amortize_loan(
                principal=float(params["principal"]),
                annual_rate_pct=float(params["annual_rate_pct"]),
                months=int(params["months"]),
            )
            summary = payment_plan_summary(schedule)
            return {
                "summary": summary,
                "first_3_payments": [
                    {"month": p.month, "payment": p.payment, "principal": p.principal,
                     "interest": p.interest, "balance": p.balance}
                    for p in schedule[:3]
                ],
                "precision": "integer_cents",
            }
        return {"error": f"Unknown finance tool: {tool_name}"}
    except (KeyError, ValueError, TypeError) as e:
        return {"error": f"finance_tool error: {e}", "tool": tool_name}


def is_finance_tool(tool_name: str) -> bool:
    return tool_name.startswith("finance_")


# ── Context injection — pre-compute financial facts for COMPUTE state ─────────

import re as _re

# Patterns that signal a financial computation task
_DOLLAR_PAT = _re.compile(r"\$\s?([\d,]+(?:\.\d{1,2})?)", _re.IGNORECASE)
_PCT_PAT = _re.compile(r"(\d+(?:\.\d+)?)\s*%")
_DAYS_PAT = _re.compile(r"(\d+)\s*days?", _re.IGNORECASE)
_MONTHS_PAT = _re.compile(r"(\d+)\s*months?", _re.IGNORECASE)


def build_finance_context(task_text: str, process_type: str) -> str:
    """
    Pre-compute financial facts and return a concise context block for injection
    into the COMPUTE state system prompt.

    Called during PRIME phase. Returns empty string if no financial signals found.
    Zero API cost. ~20-50 tokens when it fires.
    """
    lines: list[str] = []
    text = task_text.lower()

    # ── Variance check (invoice_reconciliation, procurement) ──────────────────
    if process_type in ("invoice_reconciliation", "procurement", "expense_approval"):
        amounts = _extract_dollars(task_text)
        pcts = _extract_pcts(task_text)
        if len(amounts) >= 2 and pcts:
            # Assume first two amounts are invoiced vs. PO (order in text)
            invoiced, po = amounts[0], amounts[1]
            threshold = pcts[0]
            try:
                result = apply_variance_check(invoiced, po, threshold)
                sign = "EXCEEDS" if result["exceeds"] else "does NOT exceed"
                lines.append(
                    f"Pre-computed variance: ${invoiced:,.2f} vs ${po:,.2f} = "
                    f"{result['pct']:.4f}% variance — {sign} {threshold}% threshold. "
                    f"Requires escalation: {result['exceeds']}."
                )
            except Exception:
                pass

    # ── SLA credit (sla_breach) ───────────────────────────────────────────────
    # compute_sla_credit(downtime_mins, sla_max_mins, invoice_amount, credit_pct_per_breach, cap_pct)
    if process_type == "sla_breach":
        amounts = _extract_dollars(task_text)
        pcts = _extract_pcts(task_text)
        downtime_m = _re.search(r"(\d+)\s*(?:minute|min)", task_text, _re.IGNORECASE)
        downtime_h = _re.search(r"(\d+(?:\.\d+)?)\s*(?:hour|hr)", task_text, _re.IGNORECASE)
        if amounts and (downtime_m or downtime_h):
            downtime_min = (
                float(downtime_m.group(1)) if downtime_m
                else float(downtime_h.group(1)) * 60
            )
            contract_val = amounts[0]
            sla_tgt = next((p for p in pcts if p > 90), 99.9)
            credit_pct = next((p for p in pcts if p < 50), 10.0)
            cap = next((p for p in pcts if 20 <= p <= 50), 30.0)
            # sla_max_mins = allowed downtime for 30-day month at target SLA
            sla_max_mins = 30 * 24 * 60 * (1.0 - sla_tgt / 100.0)
            try:
                credit = compute_sla_credit(downtime_min, sla_max_mins, contract_val, credit_pct, cap)
                lines.append(
                    f"Pre-computed SLA credit: ${credit:,.2f} for {downtime_min:.0f} min downtime "
                    f"vs {sla_max_mins:.1f} min allowed (SLA {sla_tgt}% on ${contract_val:,.2f} contract)."
                )
            except Exception:
                pass

    # ── Proration (subscription_migration, month_end_close) ──────────────────
    if process_type in ("subscription_migration", "month_end_close", "ar_collections"):
        amounts = _extract_dollars(task_text)
        days = _re.findall(r"(\d+)\s*(?:day|days)", task_text, _re.IGNORECASE)
        months = _re.findall(r"(\d+)\s*(?:month|months)", task_text, _re.IGNORECASE)
        if amounts and days and len(days) >= 2:
            try:
                total_days = int(days[1])
                used_days = int(days[0])
                remaining = prorated_amount(amounts[0], used_days, total_days)
                lines.append(
                    f"Pre-computed proration: ${amounts[0]:,.2f} for {used_days}/{total_days} days "
                    f"= ${remaining:,.2f} remaining value."
                )
            except Exception:
                pass
        elif amounts and months and len(months) >= 2:
            try:
                total_mo = int(months[1]) * 30
                used_mo = int(months[0]) * 30
                remaining = prorated_amount(amounts[0], used_mo, total_mo)
                lines.append(
                    f"Pre-computed proration: ${amounts[0]:,.2f} for {months[0]}/{months[1]} months "
                    f"= ${remaining:,.2f} remaining value."
                )
            except Exception:
                pass

    if not lines:
        return ""
    return (
        "## Pre-Computed Financial Facts\n"
        "The following values were computed with integer-cent precision. "
        "Use them as ground truth in your COMPUTE reasoning — do not recalculate.\n"
        + "\n".join(f"- {ln}" for ln in lines)
    )


def _extract_dollars(text: str) -> list[float]:
    """Extract dollar amounts from text, return as floats sorted largest-first."""
    matches = _DOLLAR_PAT.findall(text)
    return sorted([float(m.replace(",", "")) for m in matches], reverse=True)


def _extract_pcts(text: str) -> list[float]:
    """Extract percentage values from text."""
    return [float(m) for m in _PCT_PAT.findall(text)]
