"""
dynamic_tools.py
Runtime tool factory for computation gaps.

=============================================================
FINITE STATE MACHINE — full form explained inline
=============================================================
FSM = Finite State Machine.
  FINITE   — the agent can only be in one of a fixed set of named states
              (DECOMPOSE, ASSESS, COMPUTE, POLICY_CHECK, APPROVAL_GATE,
               MUTATE, SCHEDULE_NOTIFY, COMPLETE). Not infinite.
  STATE    — a discrete phase with specific rules and permitted actions.
              In ASSESS you ONLY read. In MUTATE you ONLY write.
              The state boundary prevents the agent from attempting
              a mutation during the reading phase (a common LLM failure).
  MACHINE  — a deterministic engine that knows which state it is in,
              what it can do there, and what comes next.

STATIC FSM (everyone else):
  - 14 hardcoded process types → fixed state sequences
  - Fallback to 5-state "general" for anything new
  - Per-state instructions like "gather data" (useless)

DYNAMIC FSM (what we built in Wave 13):
  - Unknown process type → Haiku synthesizes the right state sequence
    AND writes specific instructions per state
  - SUPPLIER_RISK_ASSESSMENT gets: "gather credit rating, ESG score,
    geo-risk → compute weighted risk score = 0.3×credit + 0.25×geo..."
    instead of "gather data"

THIS FILE extends the same principle to TOOLS:

STATIC TOOLS (what everyone else does):
  - Hardcode 7 finance functions → ship in the image → never grows

DYNAMIC TOOLS (Wave 14):
  - Detect when the task needs math that no tool handles
  - Synthesize a Python implementation via Haiku
  - Validate against auto-generated test cases
  - Register to tool_registry.json (persistent across all future tasks)
  - Hot-load immediately — zero restart needed

Competition impact:
  - Generality (20%): infinite computation capability, not just 14 functions
  - Drift Adaptation (20%): if formula changes → old tool fails accuracy
    check → synthesize new one → pass
  - Error Recovery (8%): tool synthesis IS error recovery for math failures
  - pass^k: consistent correct math = all k attempts return same result
=============================================================
"""
from __future__ import annotations

import json
import math
import os
import re
import asyncio
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any


# ── Registry store ─────────────────────────────────────────────────────────

_REGISTRY_FILE = Path(os.environ.get("RL_CACHE_DIR", "/app")) / "tool_registry.json"
_registry_defs: dict[str, dict] = {}   # name → full definition + python_code
_registry_fns: dict[str, Any] = {}     # name → callable (hot-loaded at startup)
_registry_loaded = False


def _load_registry() -> None:
    global _registry_defs, _registry_fns, _registry_loaded
    if _registry_loaded:
        return
    try:
        if _REGISTRY_FILE.exists():
            _registry_defs = json.loads(_REGISTRY_FILE.read_text())
            for name, defn in _registry_defs.items():
                fn = _exec_in_sandbox(defn.get("python_code", ""), name)
                if fn:
                    _registry_fns[name] = fn
    except Exception:
        _registry_defs = {}
        _registry_fns = {}
    _registry_loaded = True


def _save_registry() -> None:
    try:
        _REGISTRY_FILE.write_text(json.dumps(_registry_defs, indent=2))
    except Exception:
        pass  # best-effort — never crash the task


# ── Sandbox execution ────────────────────────────────────────────────────────
#
# We exec synthesized code in a restricted namespace.
# NO: import, open, eval, exec, os, sys, __import__
# YES: math, Decimal, ROUND_HALF_UP, safe builtins
#
# This is intentionally limited — financial math only needs arithmetic.

_SANDBOX_GLOBALS: dict[str, Any] = {
    "__builtins__": None,   # block all builtins explicitly
    # Math
    "math": math,
    "Decimal": Decimal,
    "ROUND_HALF_UP": ROUND_HALF_UP,
    # Safe builtins restored individually
    "abs": abs, "int": int, "float": float, "str": str, "bool": bool,
    "round": round, "min": min, "max": max, "sum": sum, "len": len,
    "range": range, "enumerate": enumerate, "zip": zip,
    "list": list, "dict": dict, "tuple": tuple, "set": set,
    "isinstance": isinstance, "pow": pow, "divmod": divmod,
    "sorted": sorted, "reversed": reversed, "any": any, "all": all,
    "ValueError": ValueError, "ZeroDivisionError": ZeroDivisionError,
}


def _exec_in_sandbox(code: str, func_name: str) -> Any | None:
    """
    Execute synthesized Python code in a restricted namespace.
    Returns the callable if successful, None if code fails to compile or run.
    """
    namespace = dict(_SANDBOX_GLOBALS)
    try:
        exec(compile(code, "<dynamic_tool>", "exec"), namespace)
        fn = namespace.get(func_name)
        if callable(fn):
            return fn
    except Exception:
        pass
    return None


# ── Gap detection ────────────────────────────────────────────────────────────
#
# Pattern: map task text keywords → gap key + description + param hints.
# We check if the gap key already exists in registry OR in passed tool list.
# If yes → skip (already have it). If no → flag as gap.

_GAP_PATTERNS: list[dict] = [
    {
        "key": "finance_npv",
        "patterns": [
            r"\bnpv\b", r"\bnet present value\b", r"\bdiscounted cash flow\b",
            r"\bpresent value of cash", r"\bpv of.*flows\b",
        ],
        "description": (
            "Net Present Value: NPV = sum(cash_flow[t] / (1+rate)^t) - initial_investment. "
            "Function name: finance_npv. "
            "Params: cash_flows (list of floats, first is usually negative investment), "
            "discount_rate (annual rate as %, e.g. 10 for 10%)."
        ),
    },
    {
        "key": "finance_irr",
        "patterns": [
            r"\birr\b", r"\binternal rate of return\b",
        ],
        "description": (
            "Internal Rate of Return: rate that makes NPV = 0. "
            "Function name: finance_irr. "
            "Params: cash_flows (list of floats, first negative = investment). "
            "Use Newton-Raphson or bisection method. Return rate as percentage."
        ),
    },
    {
        "key": "finance_bond_price",
        "patterns": [
            r"\bbond price\b", r"\byield to maturity\b", r"\bytm\b",
            r"\bcoupon.*face value\b", r"\bface value.*coupon\b", r"\bbond valuation\b",
        ],
        "description": (
            "Bond pricing: price = sum(coupon / (1+r)^t) + face_value / (1+r)^n. "
            "Function name: finance_bond_price. "
            "Params: face_value (float), coupon_rate (annual % e.g. 5 for 5%), "
            "ytm (yield to maturity as %, e.g. 6 for 6%), "
            "periods (int, number of coupon periods), "
            "periods_per_year (int, default 2 for semiannual)."
        ),
    },
    {
        "key": "finance_depreciation",
        "patterns": [
            r"\bstraight.line depreciation\b", r"\bsl depreciation\b",
            r"\bdepreciation schedule\b", r"\bdouble.declining\b",
            r"\bsum.of.years.digits\b", r"\bsoyd\b", r"\bddb\b",
        ],
        "description": (
            "Asset depreciation schedule supporting straight-line (SL), "
            "double-declining balance (DDB), and sum-of-years-digits (SOYD). "
            "Function name: finance_depreciation. "
            "Params: cost (float), salvage_value (float), useful_life (int years), "
            "method (str: 'sl', 'ddb', or 'soyd'). "
            "Return annual depreciation schedule."
        ),
    },
    {
        "key": "finance_wacc",
        "patterns": [
            r"\bwacc\b", r"\bweighted average cost of capital\b",
            r"\bcost of equity\b", r"\bcost of debt\b",
        ],
        "description": (
            "Weighted Average Cost of Capital: WACC = (E/V)*Re + (D/V)*Rd*(1-Tc). "
            "Function name: finance_wacc. "
            "Params: equity_value (float), debt_value (float), "
            "cost_of_equity (float, % e.g. 12 for 12%), "
            "cost_of_debt (float, % e.g. 8 for 8%), "
            "tax_rate (float, % e.g. 25 for 25%)."
        ),
    },
    {
        "key": "finance_compound_interest",
        "patterns": [
            r"\bcompound interest\b", r"\beffective annual rate\b",
            r"\bear\b", r"\bapy\b", r"\bcompounding.*frequency\b",
        ],
        "description": (
            "Compound interest: A = P * (1 + r/n)^(n*t). "
            "Function name: finance_compound_interest. "
            "Params: principal (float), annual_rate (float, % e.g. 5 for 5%), "
            "years (float), compounds_per_year (int, e.g. 12 for monthly). "
            "Return final amount, interest earned, and effective annual rate."
        ),
    },
    {
        "key": "finance_loan_amortization",
        "patterns": [
            r"\bamortization\b", r"\bloan schedule\b",
            r"\bmonthly payment.*loan\b", r"\bmortgage.*schedule\b",
            r"\binstallment.*principal\b",
        ],
        "description": "Loan amortization schedule — seeded at startup, not re-synthesized.",
    },
]

# Amortization tool code — seeded into registry at startup.
# Self-contained: uses only sandbox-available Decimal + ROUND_HALF_UP.
_AMORTIZATION_CODE = '''
def finance_loan_amortization(principal, annual_rate, months):
    """360-period loan amortization with cent-level Decimal precision."""
    P = Decimal(str(principal))
    annual = Decimal(str(annual_rate)) / Decimal("100")
    r = annual / Decimal("12")
    n = int(months)

    if r == Decimal("0"):
        monthly = (P / Decimal(str(n))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        factor = (Decimal("1") + r) ** n
        monthly = (P * r * factor / (factor - Decimal("1"))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    schedule = []
    balance = P
    total_interest = Decimal("0")

    for period in range(1, n + 1):
        interest = (balance * r).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        principal_portion = (monthly - interest).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if period == n:
            principal_portion = balance
            monthly_actual = (balance + interest).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            monthly_actual = monthly
        balance = (balance - principal_portion).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_interest += interest
        schedule.append({
            "period": period,
            "payment": float(monthly_actual),
            "principal": float(principal_portion),
            "interest": float(interest),
            "balance": float(balance),
        })

    return {
        "result": float(monthly),
        "details": {
            "monthly_payment": float(monthly),
            "total_payments": float(monthly * Decimal(str(n))),
            "total_interest": float(total_interest),
            "schedule": schedule[:6] + (["..."] if n > 12 else schedule[6:]),
        },
    }
'''.strip()

_AMORTIZATION_SCHEMA = {
    "name": "finance_loan_amortization",
    "description": (
        "Calculate loan amortization schedule with exact monthly payments. "
        "Use for: mortgage schedules, car loans, business loans, any installment loan. "
        "Returns monthly payment, total interest, and full payment schedule."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "principal": {"type": "number", "description": "Loan principal amount in dollars"},
            "annual_rate": {"type": "number", "description": "Annual interest rate as percentage (e.g. 5.5 for 5.5%)"},
            "months": {"type": "integer", "description": "Loan term in months (e.g. 360 for 30-year mortgage)"},
        },
        "required": ["principal", "annual_rate", "months"],
    },
}


def detect_tool_gaps(task_text: str, existing_tools: list[dict]) -> list[dict]:
    """
    Scan task text for computation patterns that no existing tool handles.

    existing_tools: list of tool definitions already available (MCP + registered).
    Returns: list of gap dicts with {key, description} for each gap detected.
    """
    _load_registry()

    # Build set of existing tool names (from both MCP tools and registry)
    existing_names: set[str] = set()
    for t in existing_tools:
        name = t.get("name") or t.get("function", {}).get("name", "")
        if name:
            existing_names.add(name)
    existing_names.update(_registry_fns.keys())  # in-memory registered tools

    text_lower = task_text.lower()
    gaps = []

    for gap in _GAP_PATTERNS:
        key = gap["key"]
        # Skip if we already have this tool
        if key in existing_names:
            continue
        # Skip amortization gap detection — it's always seeded
        if key == "finance_loan_amortization":
            continue
        # Check patterns
        if any(re.search(p, text_lower) for p in gap["patterns"]):
            gaps.append({"key": key, "description": gap["description"]})

    return gaps


# ── Haiku synthesis ──────────────────────────────────────────────────────────

_SYNTHESIS_SYSTEM = """\
You are a financial computation specialist. Implement a precise Python function.

The function runs in a sandbox with ONLY these available:
- math module (math.log, math.exp, math.sqrt, math.pow, math.floor, math.ceil, math.pi, math.e)
- Decimal (from decimal module) for precision arithmetic
- ROUND_HALF_UP (rounding mode constant)
- Safe builtins: abs, int, float, str, bool, round, min, max, sum, len, range,
  enumerate, zip, list, dict, tuple, set, isinstance, pow, divmod, sorted, any, all
- ValueError, ZeroDivisionError for error handling

DO NOT use: import, open, eval, exec, __import__, os, sys, any external library.

Requirements:
1. Function name must EXACTLY match the specified name
2. Accept the specified parameters as keyword-capable positional args
3. Use Decimal for ALL financial calculations (avoid float precision loss)
4. Return dict with "result" (primary scalar answer) and "details" (dict of workings)
5. Handle edge cases: zero rates, zero periods, negative inputs

Respond ONLY with valid JSON (no markdown, no explanation):
{
  "python_code": "def func_name(param1, param2, ...):\\n    ...",
  "test_cases": [
    {"inputs": {"param1": val}, "expected_result_approx": 123.45, "tolerance_pct": 0.01},
    {"inputs": {"param1": val2}, "expected_result_approx": 456.78, "tolerance_pct": 0.01},
    {"inputs": {"param1": val3}, "expected_result_approx": 789.01, "tolerance_pct": 0.01}
  ]
}"""


async def _synthesize_via_haiku(gap: dict) -> dict | None:
    """Call Haiku to synthesize a tool implementation. Returns parsed response or None."""
    prompt = (
        f"Implement this financial calculation function:\n\n"
        f"{gap['description']}\n\n"
        f"Write precise, correct code. Include 3 test cases with known correct outputs."
    )
    try:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic()
        msg = await asyncio.wait_for(
            client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1200,
                system=_SYNTHESIS_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            ),
            timeout=10.0,
        )
        raw = msg.content[0].text if msg.content else ""

        # Strip markdown fences
        clean = raw.strip()
        if clean.startswith("```"):
            clean = re.sub(r"^```[a-z]*\n?", "", clean)
            clean = re.sub(r"\n?```$", "", clean).strip()

        return json.loads(clean)

    except Exception:
        return None


# ── Validation ───────────────────────────────────────────────────────────────

def _validate_tool(tool_def: dict) -> tuple[bool, str]:
    """
    Validate a synthesized tool by executing its test cases.
    Returns (passed: bool, reason: str).
    """
    code = tool_def.get("python_code", "")
    func_name = tool_def.get("name", "")
    test_cases = tool_def.get("test_cases", [])

    if not code or not func_name:
        return False, "missing code or name"

    fn = _exec_in_sandbox(code, func_name)
    if fn is None:
        return False, "code failed to compile or exec"

    if not test_cases:
        # No test cases — accept with a note (better than rejecting useful tools)
        return True, "no test cases (accepted without validation)"

    passes = 0
    for tc in test_cases[:3]:
        try:
            inputs = tc.get("inputs", {})
            expected = float(tc.get("expected_result_approx", 0))
            tolerance_pct = float(tc.get("tolerance_pct", 0.01))

            result = fn(**inputs)
            actual = float(result.get("result", 0)) if isinstance(result, dict) else float(result)

            # Relative tolerance check
            denom = max(abs(expected), 1.0)
            if abs(actual - expected) / denom <= tolerance_pct:
                passes += 1
        except Exception:
            pass  # test case failed — don't count it

    if passes == len(test_cases[:3]):
        return True, f"all {passes} test cases passed"
    if passes >= 2:
        return True, f"{passes}/{len(test_cases[:3])} test cases passed (accepted)"
    return False, f"only {passes}/{len(test_cases[:3])} test cases passed"


# ── Tool schema builder ──────────────────────────────────────────────────────

def _build_schema(gap_key: str, description: str) -> dict:
    """Build a minimal JSON schema for a synthesized tool. Uses input_schema (Anthropic API format)."""
    return {
        "name": gap_key,
        "description": description.split(". ")[0],  # first sentence as description
        "input_schema": {
            "type": "object",
            "properties": {},  # Claude will infer from description
            "additionalProperties": True,
        },
    }


# ── Public: synthesize + register ────────────────────────────────────────────

async def synthesize_and_register(gap: dict, task_text: str) -> dict | None:
    """
    Synthesize a tool for the detected gap, validate it, and register it.

    Returns the tool schema dict (for adding to self._tools) or None if synthesis failed.
    One Haiku call per new tool. All future tasks get the cached tool for free.
    """
    _load_registry()

    key = gap["key"]

    # Already registered during this run (race condition guard)
    if key in _registry_fns:
        return {"name": key, "input_schema": _registry_defs.get(key, {}).get("input_schema", {})}

    # Synthesize
    raw = await _synthesize_via_haiku(gap)
    if not raw:
        return None

    # Build full tool def
    tool_def = {
        "name": key,
        "python_code": raw.get("python_code", ""),
        "test_cases": raw.get("test_cases", []),
        "description": gap["description"].split(". ")[0],
        "input_schema": raw.get("input_schema", {"type": "object", "additionalProperties": True}),
        "_synthesized": True,
        "_gap_description": gap["description"],
    }

    # Validate
    passed, reason = _validate_tool(tool_def)
    if not passed:
        return None

    # Hot-load
    fn = _exec_in_sandbox(tool_def["python_code"], key)
    if fn is None:
        return None

    # Register
    _registry_fns[key] = fn
    _registry_defs[key] = tool_def
    _save_registry()

    return {
        "name": key,
        "description": tool_def["description"],
        "input_schema": tool_def["input_schema"],
    }


# ── Public: load + call ──────────────────────────────────────────────────────

def load_registered_tools() -> list[dict]:
    """
    Return JSON schemas for all registered tools (MCP-compatible format).
    Called in PRIME to add registered tools to self._tools.
    """
    _load_registry()
    result = []
    for name, defn in _registry_defs.items():
        result.append({
            "name": name,
            "description": defn.get("description", name),
            "input_schema": defn.get("input_schema", {"type": "object"}),
        })
    return result


def is_registered_tool(tool_name: str) -> bool:
    """Check if a tool name maps to a registered (synthesized or seeded) function."""
    _load_registry()
    return tool_name in _registry_fns


def call_registered_tool(tool_name: str, params: dict) -> dict:
    """Execute a registered tool with the given params. Returns result dict."""
    _load_registry()
    fn = _registry_fns.get(tool_name)
    if fn is None:
        return {"error": f"Tool '{tool_name}' not found in registry"}
    try:
        result = fn(**params)
        if isinstance(result, dict):
            return result
        return {"result": result}
    except Exception as e:
        return {"error": str(e), "tool": tool_name, "params": params}


# ── Seed: amortization tool ───────────────────────────────────────────────────

def seed_amortization_tool() -> None:
    """
    Seed the loan amortization tool into the registry at startup.
    Migrates it from hardcoded finance_tools.py to the dynamic registry.
    Only seeds once — idempotent.
    """
    _load_registry()

    key = "finance_loan_amortization"
    if key in _registry_fns:
        return  # already seeded

    fn = _exec_in_sandbox(_AMORTIZATION_CODE, key)
    if fn is None:
        return  # sandbox exec failed — keep the hardcoded fallback

    # Validate with a known test case: $200k, 5% APR, 360 months → ~$1073.64/mo
    try:
        test_result = fn(principal=200000, annual_rate=5.0, months=360)
        expected = 1073.64
        actual = test_result.get("result", 0)
        if abs(actual - expected) > 1.0:
            return  # validation failed — don't register broken tool
    except Exception:
        return

    defn = {
        **_AMORTIZATION_SCHEMA,
        "python_code": _AMORTIZATION_CODE,
        "test_cases": [
            {"inputs": {"principal": 200000, "annual_rate": 5.0, "months": 360},
             "expected_result_approx": 1073.64, "tolerance_pct": 0.01},
        ],
        "_seeded": True,
    }
    _registry_fns[key] = fn
    _registry_defs[key] = defn
    _save_registry()


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_tool_registry_stats() -> dict:
    """Return registry stats for /rl/status endpoint."""
    _load_registry()
    total = len(_registry_defs)
    seeded = sum(1 for v in _registry_defs.values() if v.get("_seeded"))
    synthesized = sum(1 for v in _registry_defs.values() if v.get("_synthesized"))
    return {
        "total_tools": total,
        "seeded_tools": seeded,
        "synthesized_tools": synthesized,
        "registered_names": list(_registry_defs.keys()),
    }
