"""
rl_loop.py
Lightweight RL feedback loop — learns from outcomes, injects case log primer.
Inspired by BrainOS agent-rl.ts + rl-agent-loop.ts.

Two-layer learning (same as BrainOS):
1. Case log: task patterns + outcomes → injected as primer before each task
2. Quality scoring: measures answer quality (tool usage, completeness, policy adherence)
"""
from __future__ import annotations
import json
import os
import time
import hashlib
from dataclasses import dataclass, field, asdict

CASE_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "case_log.json")
MAX_CASES = 200
RELEVANT_CASES = 3


@dataclass
class CaseEntry:
    case_id: str
    task_summary: str
    keywords: list[str]
    outcome: str          # "success" | "failure" | "partial"
    quality: float        # 0.0–1.0
    what_worked: str
    what_failed: str
    tool_count: int
    timestamp: float = field(default_factory=time.time)


def _load_cases() -> list[dict]:
    try:
        if os.path.exists(CASE_LOG_PATH):
            with open(CASE_LOG_PATH, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return []


def _save_cases(cases: list[dict]) -> None:
    try:
        with open(CASE_LOG_PATH, "w") as f:
            json.dump(cases[-MAX_CASES:], f, indent=2)
    except Exception:
        pass


def _extract_keywords(text: str) -> list[str]:
    stop = {
        "the","a","an","is","are","was","were","be","been","have","has","had",
        "do","does","did","will","would","could","should","can","for","in","on",
        "at","to","of","and","or","but","with","from","this","that","it","i",
        "you","please","need","want","help","task","make","get","use"
    }
    words = text.lower().split()
    seen, unique = set(), []
    for w in words:
        w = w.strip(".,!?;:\"'()[]")
        if len(w) > 3 and w not in stop and w not in seen:
            seen.add(w)
            unique.append(w)
    return unique[:15]


def score_quality(answer: str, tool_count: int, policy_passed: bool | None) -> float:
    """
    Quality score 0–1. Ported from BrainOS computeAgentQuality() Wave 9.
    Conservative baseline 0.5 (matches BrainOS), then adjust by signals.

    Penalizes:
      - Empty data arrays: -0.25 (BrainOS rule)
      - No tool calls: -0.10
      - Short answers: -0.20 if < 50 chars
      - Error phrases: -0.25
      - Policy violation: -0.15

    Rewards:
      - Answer length and structure
      - Tool usage depth
      - Policy compliance
      - Structured output markers
    """
    import re as _re
    score = 0.50   # BrainOS conservative baseline

    length = len(answer.strip())
    if length > 800:    score += 0.20
    elif length > 400:  score += 0.15
    elif length > 150:  score += 0.08
    elif length < 50:   score -= 0.20

    if tool_count >= 5:   score += 0.15
    elif tool_count >= 3: score += 0.10
    elif tool_count >= 1: score += 0.05
    elif tool_count == 0: score -= 0.10

    if policy_passed is True:    score += 0.15
    elif policy_passed is False: score -= 0.15
    # None = unknown, no adjustment

    # BrainOS: empty data array penalty
    if _re.search(r'"data"\s*:\s*\[\s*\]', answer): score -= 0.25
    if _re.search(r'"results"\s*:\s*\[\s*\]', answer): score -= 0.15

    # Structure reward
    if any(m in answer.lower() for m in ["approved", "rejected", "completed", "decision:", "total:"]):
        score += 0.08
    if "{" in answer and "}" in answer:
        score += 0.05

    # Error phrase penalty
    error_phrases = ["task failed", "unable to", "cannot access", "no data found",
                     "token budget exhausted", "tool unavailable"]
    if any(p in answer.lower() for p in error_phrases):
        score -= 0.25

    return round(max(0.0, min(1.0, score)), 3)


def record_outcome(
    task_text: str,
    answer: str,
    tool_count: int,
    policy_passed: bool | None = None,
    error: str | None = None,
) -> float:
    """Record task outcome. Returns quality score (dopamine if ≥0.6, gaba if <0.6)."""
    cases = _load_cases()
    quality = score_quality(answer, tool_count, policy_passed)
    outcome = "success" if quality >= 0.6 else ("failure" if error else "partial")
    case_id = hashlib.md5(f"{task_text[:50]}{time.time()}".encode()).hexdigest()[:8]

    what_worked = ""
    what_failed = ""
    if outcome == "success":
        if tool_count > 0:
            what_worked = f"Used {tool_count} tool calls"
        if policy_passed:
            what_worked += (". Policy enforced correctly" if what_worked else "Policy enforced correctly")
    else:
        what_failed = error or "Partial/incomplete answer"

    entry = CaseEntry(
        case_id=case_id,
        task_summary=task_text[:120],
        keywords=_extract_keywords(task_text),
        outcome=outcome,
        quality=round(quality, 3),
        what_worked=what_worked,
        what_failed=what_failed,
        tool_count=tool_count,
    )
    cases.append(asdict(entry))
    _save_cases(cases)
    return quality


def build_rl_primer(task_text: str) -> str:
    """
    Build a case-log primer — injected before task execution.
    Inspired by BrainOS rl-agent-loop.ts injectCaseLogContext().
    """
    cases = _load_cases()
    if not cases:
        return ""

    task_kw = set(_extract_keywords(task_text))
    scored = []
    for c in cases:
        overlap = len(task_kw & set(c.get("keywords", [])))
        if overlap > 0:
            scored.append((overlap, c))
    scored.sort(key=lambda x: (-x[0], -x[1].get("quality", 0)))
    relevant = [c for _, c in scored[:RELEVANT_CASES]]

    if not relevant:
        return ""

    lines = ["## LEARNED PATTERNS (from similar past tasks — apply these)"]
    for c in relevant:
        icon = "✅" if c["outcome"] == "success" else ("❌" if c["outcome"] == "failure" else "⚠️")
        lines.append(f'\n{icon} Past: "{c["task_summary"][:80]}" — quality {c["quality"]:.2f}')
        if c.get("what_worked"):
            lines.append(f'   ✓ Worked: {c["what_worked"]}')
        if c.get("what_failed"):
            lines.append(f'   ✗ Avoid: {c["what_failed"]}')
    lines.append("")
    return "\n".join(lines)
