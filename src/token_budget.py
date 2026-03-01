"""
token_budget.py
10K token budget per benchmark task — 12% of score.
Inspired by BrainOS brain/token-budget.ts.

Key rules (from BrainOS):
- 80% used → switch to Haiku
- 100% → skip remaining LLM calls
- formatCompetitionAnswer() → AgentX judge format (built in BrainOS for this exact competition)
"""
from __future__ import annotations

TASK_BUDGET = 10_000
CHARS_PER_TOKEN = 4
HAIKU_THRESHOLD = 0.80   # >80% used → Haiku
HARD_LIMIT = 1.0         # 100% → skip LLM

MODELS = {
    "haiku":  "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
}

# FSM state → default model tier (mirrors BrainOS token-budget.ts)
STATE_MODEL = {
    "DECOMPOSE":     "haiku",   # classification phase — haiku is fast enough
    "ASSESS":        "haiku",   # data gathering — haiku + full tokens is sufficient
    "POLICY_CHECK":  "haiku",   # deterministic anyway
    "APPROVAL_GATE": "haiku",   # summarize for human
    "EXECUTE":       "sonnet",  # actual work
    "COMPLETE":      "haiku",   # final summary
    "ESCALATE":      "haiku",   # refusal message
    "FAILED":        "haiku",   # error message
}

# Complex keywords → force Sonnet even in EXECUTE
COMPLEX_KEYWORDS = [
    "reconcile", "root cause", "diagnose", "analyze", "forecast",
    "synthesize", "cross-reference", "correlate", "investigate",
]


class TokenBudget:
    """
    Tracks token usage per task phase.
    Mirrors BrainOS createTokenBudget() + recordTokenUsage().
    """

    def __init__(self, budget: int = TASK_BUDGET):
        self.budget = budget
        self.used = 0
        self._by_phase: dict[str, int] = {}

    def consume(self, text: str, phase: str = "unknown") -> int:
        tokens = max(1, len(text) // CHARS_PER_TOKEN)
        self.used += tokens
        self._by_phase[phase] = self._by_phase.get(phase, 0) + tokens
        return tokens

    @property
    def remaining(self) -> int:
        return max(0, self.budget - self.used)

    @property
    def pct(self) -> float:
        return self.used / self.budget

    @property
    def should_skip_llm(self) -> bool:
        """Hard limit reached — mirrors BrainOS shouldSkipLLMCall()."""
        return self.pct >= HARD_LIMIT

    def get_model(self, fsm_state: str = "EXECUTE", task_text: str = "") -> str:
        """
        Returns model ID. Mirrors BrainOS getRecommendedModel().
        >80% used → always Haiku regardless of state.
        """
        if self.pct >= HAIKU_THRESHOLD:
            return MODELS["haiku"]

        tier = STATE_MODEL.get(fsm_state, "haiku")
        if tier == "sonnet":
            # Downgrade to Haiku for simple tasks that don't need Sonnet reasoning
            if not any(kw in task_text.lower() for kw in COMPLEX_KEYWORDS):
                return MODELS["haiku"]
            return MODELS["sonnet"]
        return MODELS["haiku"]

    def get_max_tokens(self, fsm_state: str = "EXECUTE") -> int:
        """Cap API max_tokens based on remaining budget."""
        r = self.remaining
        if r < 500:   return 256
        if r < 2000:  return 512
        # All active execution states get full 4096 budget
        # COMPUTE added: mathematical reasoning needs the full token budget
        ACTIVE_STATES = {"EXECUTE", "DECOMPOSE", "ASSESS", "COMPUTE", "MUTATE", "SCHEDULE_NOTIFY"}
        if fsm_state in ACTIVE_STATES: return min(4096, r // 2)
        return min(1024, r // 3)

    def cap_prompt(self, text: str, phase: str = "context") -> str:
        """Truncate a prompt block to stay within remaining budget."""
        max_chars = self.remaining * CHARS_PER_TOKEN
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + f"\n[truncated: {self.remaining} tokens remaining]"

    def efficiency_hint(self) -> str:
        """System prompt suffix — gets stricter as budget runs low."""
        pct = self.pct
        if pct < 0.3:   return "\nBe concise."
        if pct < 0.6:   return "\nBe very concise. One tool call per data need."
        if pct < 0.80:  return "\nCRITICAL: Token budget low. Shortest complete answer only."
        return "\nEMERGENCY: Budget nearly exhausted. One sentence answer max."

    def report(self) -> dict:
        return {
            "budget": self.budget,
            "used": self.used,
            "remaining": self.remaining,
            "pct": round(self.pct, 3),
            "by_phase": self._by_phase,
        }


def format_competition_answer(
    answer: str,
    process_type: str,
    quality: float,
    duration_ms: int,
    policy_passed: bool | None,
) -> str:
    """
    Format final answer for AgentX competition judge.
    Mirrors BrainOS token-budget.ts formatCompetitionAnswer() — built for this exact competition.

    Returns clean answer with metadata block for judging rubric.
    """
    lines = [answer.strip(), ""]

    # Metadata block for judge
    status = "✅ PASSED" if policy_passed else ("❌ FAILED" if policy_passed is False else "—")
    lines += [
        "---",
        f"Process: {process_type.replace('_', ' ').title()}",
        f"Policy: {status}",
        f"Quality: {quality:.2f}",
        f"Duration: {duration_ms}ms",
    ]
    return "\n".join(lines)
