"""
schema_adapter.py
Schema drift resilience for ASSESS state.
Inspired by BrainOS brain/schema-drift-handler.ts.

When a tool call fails with "column not found":
1. Run schema introspection
2. Fuzzy-match closest column name (Levenshtein via difflib)
3. Retry with corrected name
4. Cache mapping for this session
"""
from __future__ import annotations
import re
from difflib import get_close_matches, SequenceMatcher
from typing import Callable, Awaitable

# Canonical → known aliases (mirrors BrainOS KNOWN_COLUMN_ALIASES)
KNOWN_COLUMN_ALIASES: dict[str, list[str]] = {
    "client_name":      ["customer_name", "account_name", "company_name", "org_name"],
    "created_at":       ["created_date", "creation_date", "date_created", "timestamp"],
    "updated_at":       ["updated_date", "modification_date", "last_modified", "modified_at"],
    "amount":           ["value", "total", "price", "cost", "sum", "total_amount"],
    "status":           ["state", "stage", "condition", "current_status"],
    "user_id":          ["owner_id", "creator_id", "assigned_to", "employee_id"],
    "description":      ["details", "notes", "comments", "body", "content"],
    "email":            ["email_address", "contact_email", "user_email"],
    "name":             ["title", "label", "display_name", "full_name"],
    "category":         ["type", "classification", "group", "kind"],
}

SCHEMA_ERROR_PATTERNS = [
    r"column[s]?\s+['\"]?(\w+)['\"]?\s+(?:not found|does not exist|unknown|not recognized)",
    r"no such column[s]?:?\s+['\"]?(\w+)['\"]?",
    r"invalid column name[s]?\s+['\"]?(\w+)['\"]?",
    r"unknown column[s]?[:\s]+['\"]?(\w+)['\"]?",
    r"field[s]?\s+['\"]?(\w+)['\"]?\s+(?:not found|does not exist)",
    r"KeyError:\s+['\"]?(\w+)['\"]?",
]


def detect_schema_error(error_text: str) -> str | None:
    """Extract the bad column name from an error message. None if not a schema error."""
    text = error_text.lower()
    for pattern in SCHEMA_ERROR_PATTERNS:
        m = re.search(pattern, text)
        if m and m.lastindex >= 1:
            return m.group(1)
    return None


def fuzzy_match_column(bad_col: str, candidates: list[str]) -> str | None:
    """
    Match bad_col to closest candidate.
    Order: exact → known alias → difflib close match → Levenshtein ratio.
    Mirrors BrainOS fuzzyMatchColumn().
    """
    # Exact
    if bad_col in candidates:
        return bad_col

    # Known alias lookup
    for canonical, aliases in KNOWN_COLUMN_ALIASES.items():
        if bad_col in aliases and canonical in candidates:
            return canonical
        if bad_col == canonical:
            match = next((a for a in aliases if a in candidates), None)
            if match:
                return match

    # difflib close match (cutoff 0.6)
    matches = get_close_matches(bad_col, candidates, n=1, cutoff=0.6)
    if matches:
        return matches[0]

    # Levenshtein ratio fallback (>0.7)
    best, best_ratio = None, 0.0
    for c in candidates:
        ratio = SequenceMatcher(None, bad_col, c).ratio()
        if ratio > best_ratio:
            best_ratio, best = ratio, c
    if best and best_ratio > 0.7:
        return best

    return None


def _replace_in_params(params: dict, bad: str, good: str) -> dict:
    result = {}
    for k, v in params.items():
        if isinstance(v, str):
            result[k] = v.replace(bad, good)
        elif isinstance(v, dict):
            result[k] = _replace_in_params(v, bad, good)
        elif isinstance(v, list):
            result[k] = [
                _replace_in_params(i, bad, good) if isinstance(i, dict)
                else i.replace(bad, good) if isinstance(i, str)
                else i
                for i in v
            ]
        else:
            result[k] = v
    return result


async def resilient_tool_call(
    tool_name: str,
    params: dict,
    on_tool_call: Callable[[str, dict], Awaitable[dict]],
    schema_cache: dict,
) -> dict:
    """
    Wrapper around on_tool_call with schema drift retry.
    If call fails with a column error:
    1. Introspect schema
    2. Fuzzy-match the bad column
    3. Retry once with corrected params
    """
    result = await on_tool_call(tool_name, params)
    error_text = str(result.get("error", "")) if isinstance(result, dict) else str(result)

    if not error_text or "error" not in error_text.lower():
        return result  # success

    bad_col = detect_schema_error(error_text)
    if not bad_col:
        return result  # not a schema error

    # Check cache
    cache_key = f"{tool_name}:{bad_col}"
    if cache_key in schema_cache:
        corrected = schema_cache[cache_key]
    else:
        # Introspect schema
        table = params.get("table") or params.get("table_name") or params.get("resource", "")
        schema_result = None
        for schema_tool in ["describe_table", "get_schema", "list_columns", "schema_introspect"]:
            try:
                r = await on_tool_call(schema_tool, {"table": table} if table else {})
                if not (isinstance(r, dict) and "error" in r):
                    schema_result = r
                    break
            except Exception:
                continue

        if not schema_result:
            return result

        # Extract columns from schema response
        schema_text = str(schema_result)
        columns = list(set(re.findall(r'\b([a-z_][a-z0-9_]{2,})\b', schema_text.lower())))
        corrected = fuzzy_match_column(bad_col, columns)
        if not corrected:
            return result

        schema_cache[cache_key] = corrected

    corrected_params = _replace_in_params(params, bad_col, corrected)
    return await on_tool_call(tool_name, corrected_params)
