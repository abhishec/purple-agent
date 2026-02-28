"""
financial_calculator.py
Precise financial arithmetic in integer cents.
Ported from BrainOS platform/lib/process-intelligence/arithmetic.ts.

All values: pass as floats (dollars), internal ops use cents (int).
Returns floats (dollars). Never trust floating-point for money.

Covers Tasks 1, 4, 5, 6, 9, 11, 13 — prorations, sublimits, SLA credits,
loan amortization, depreciation, revenue recognition, price deltas.
"""
from __future__ import annotations
import math
from dataclasses import dataclass


def _c(dollars: float) -> int:
    return round(dollars * 100)

def _d(cents: int) -> float:
    return cents / 100


# ── Proration ─────────────────────────────────────────────────────────────────

def prorated_amount(total: float, days_used: int, total_days: int) -> float:
    """Remaining value after days_used. E.g. 7 months into 12-month contract."""
    if total_days <= 0:
        return 0.0
    remaining = max(0, total_days - days_used)
    return _d(round(_c(total) * remaining / total_days))


def prorated_for_period(total: float, period_num: int, total_periods: int) -> float:
    """Recognizable amount for a single period. E.g. 1 month of annual prepaid."""
    if total_periods <= 0:
        return 0.0
    return _d(round(_c(total) / total_periods))


# ── Early termination / fees ────────────────────────────────────────────────

def apply_early_termination_fee(remaining_value: float, fee_pct: float) -> float:
    """Net refund after deducting early termination fee. fee_pct=10 means 10%."""
    cents = _c(remaining_value)
    fee = round(cents * fee_pct / 100)
    return _d(cents - fee)


# ── Variance checking ──────────────────────────────────────────────────────

def apply_variance_check(invoiced: float, po_amount: float, threshold_pct: float) -> dict:
    """
    Returns variance details.
    exceeds=True means approval required.
    pct is the raw variance percentage (not rounded — boundary cases matter).
    """
    if po_amount == 0:
        return {"exceeds": False, "variance": 0.0, "pct": 0.0}
    variance = invoiced - po_amount
    pct = abs(variance / po_amount) * 100  # keep full precision — 2.04% vs 2.0% matters
    return {
        "exceeds": pct > threshold_pct,
        "variance": round(variance, 2),
        "pct": round(pct, 6),  # 6 decimal places — boundary case precision
    }


# ── SLA credits ────────────────────────────────────────────────────────────

def compute_sla_credit(
    downtime_mins: float,
    sla_max_mins: float,
    invoice_amount: float,
    credit_pct_per_breach: float,
    cap_pct: float,
) -> float:
    """SLA breach credit. Each sla_max_mins of excess = credit_pct_per_breach% of invoice."""
    if downtime_mins <= sla_max_mins:
        return 0.0
    excess = downtime_mins - sla_max_mins
    breach_count = math.ceil(excess / sla_max_mins)
    raw_pct = breach_count * credit_pct_per_breach
    applied_pct = min(raw_pct, cap_pct)
    return _d(round(_c(invoice_amount) * applied_pct / 100))


# ── Insurance sublimits ────────────────────────────────────────────────────

def apply_sub_limit(claimed: float, sub_limit: float, rider_limit: float | None = None) -> float:
    """Apply coverage sub-limit with optional rider override (rider takes precedence if higher)."""
    effective = rider_limit if (rider_limit and rider_limit > sub_limit) else sub_limit
    return _d(min(_c(claimed), _c(effective)))


# ── Gift card / balance capacity ───────────────────────────────────────────

def compute_gift_card_capacity(
    current_balance: float,
    incoming_amount: float,
    capacity_limit: float,
) -> dict:
    projected = current_balance + incoming_amount
    fits = projected <= capacity_limit
    return {
        "fits": fits,
        "overflow": round(max(0.0, projected - capacity_limit), 2),
        "projected_balance": round(projected, 2),
        "direction": "refund" if incoming_amount >= 0 else "charge",
    }


# ── Loan amortization ──────────────────────────────────────────────────────

@dataclass
class AmortizationPayment:
    month: int
    payment: float
    principal: float
    interest: float
    balance: float


def amortize_loan(principal: float, annual_rate_pct: float, months: int) -> list[AmortizationPayment]:
    """Standard loan amortization. Returns per-month schedule."""
    if months <= 0:
        return []
    if annual_rate_pct == 0:
        pmt = _d(round(_c(principal) / months))
        balance = principal
        schedule = []
        for m in range(1, months + 1):
            p = min(pmt, balance)
            balance = _d(max(0, _c(balance) - _c(p)))
            schedule.append(AmortizationPayment(m, p, p, 0.0, balance))
        return schedule

    r = annual_rate_pct / 100 / 12
    factor = (1 + r) ** months
    pmt_cents = round(_c(principal) * r * factor / (factor - 1))
    balance_cents = _c(principal)
    schedule = []

    for m in range(1, months + 1):
        interest_cents = round(balance_cents * r)
        pay_cents = min(pmt_cents, balance_cents + interest_cents)
        prin_cents = pay_cents - interest_cents
        balance_cents -= prin_cents
        schedule.append(AmortizationPayment(
            month=m,
            payment=_d(pay_cents),
            principal=_d(prin_cents),
            interest=_d(interest_cents),
            balance=_d(max(0, balance_cents)),
        ))
    return schedule


def payment_plan_summary(schedule: list[AmortizationPayment]) -> dict:
    """Summary stats for a payment plan schedule."""
    if not schedule:
        return {}
    total_paid = sum(p.payment for p in schedule)
    total_interest = sum(p.interest for p in schedule)
    return {
        "monthly_payment": schedule[0].payment,
        "months": len(schedule),
        "total_paid": round(total_paid, 2),
        "total_interest": round(total_interest, 2),
    }


# ── Depreciation ───────────────────────────────────────────────────────────

def straight_line_depreciation(cost: float, salvage: float, useful_life_months: int) -> float:
    """Monthly straight-line depreciation amount."""
    if useful_life_months <= 0:
        return 0.0
    depreciable = _c(cost) - _c(salvage)
    return _d(round(depreciable / useful_life_months))


def depreciation_schedule(cost: float, salvage: float, useful_life_months: int) -> list[dict]:
    """Full depreciation schedule from month 1 to end of life."""
    monthly = straight_line_depreciation(cost, salvage, useful_life_months)
    book_value = cost
    schedule = []
    for m in range(1, useful_life_months + 1):
        dep = min(monthly, round(book_value - salvage, 2))
        book_value = _d(_c(book_value) - _c(dep))
        schedule.append({"month": m, "depreciation": dep, "book_value": book_value})
    return schedule


# ── Revenue recognition ────────────────────────────────────────────────────

def recognize_revenue(contract_value: float, contract_months: int, periods_elapsed: int) -> dict:
    """
    ASC 606 / IFRS 15 straight-line revenue recognition for prepaid contracts.
    Returns recognized (this period) and deferred (remaining).
    """
    if contract_months <= 0:
        return {"recognized_per_period": 0.0, "recognized_total": 0.0, "deferred": 0.0}
    per_period = _d(round(_c(contract_value) / contract_months))
    recognized = _d(min(_c(per_period) * periods_elapsed, _c(contract_value)))
    deferred = _d(_c(contract_value) - _c(recognized))
    return {
        "recognized_per_period": per_period,
        "recognized_total": recognized,
        "deferred": deferred,
    }


# ── Order price delta ──────────────────────────────────────────────────────

def net_price_delta(
    original_items: list[dict],
    modified_items: list[dict],
    cancelled_ids: list[str],
) -> dict:
    """
    Net price change for an order modification.
    Items: [{"id": "...", "price": 12.99}, ...].
    Negative delta = refund owed to customer.
    """
    orig_map = {i["id"]: _c(i["price"]) for i in original_items}
    mod_map = {i["id"]: _c(i["price"]) for i in modified_items}
    delta_cents = 0
    breakdown = []

    for item_id in set(orig_map) | set(mod_map):
        orig = orig_map.get(item_id, 0)
        if item_id in cancelled_ids:
            new = 0
            action = "cancelled"
        else:
            new = mod_map.get(item_id, orig)
            action = "modified" if new != orig else "unchanged"
        item_delta = new - orig
        delta_cents += item_delta
        breakdown.append({
            "id": item_id, "action": action,
            "original": _d(orig), "new": _d(new), "delta": _d(item_delta),
        })

    return {
        "net_delta": _d(delta_cents),
        "direction": "refund" if delta_cents < 0 else "charge" if delta_cents > 0 else "no_change",
        "breakdown": breakdown,
    }
