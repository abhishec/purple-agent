"""
knowledge_extractor.py
Post-task knowledge extraction — ported from BrainOS knowledge-extractor.ts.

After every task with quality >= 0.65, Haiku extracts 1-2 reusable facts
and stores them in knowledge_base.json. Future tasks get these facts injected
in the PRIME phase — the agent compounds knowledge across all tasks.

Example: Task 3 handles Acme Corp invoice with net-60 terms.
Task 7 asks about an Acme Corp PO → agent already knows their payment terms.
"""
from __future__ import annotations
import json
import os
import time
import hashlib
from dataclasses import dataclass, field, asdict

from src.config import ANTHROPIC_API_KEY

KNOWLEDGE_PATH = os.path.join(os.path.dirname(__file__), "..", "knowledge_base.json")
MAX_KNOWLEDGE_ENTRIES = 500
EXTRACTION_THRESHOLD = 0.65   # only extract from quality >= this
EXTRACT_MODEL = "claude-haiku-4-5-20251001"
RELEVANCE_OVERLAP = 2         # min keyword overlap to surface knowledge


@dataclass
class KnowledgeEntry:
    entry_id: str
    domain: str           # process_type (expense_approval, procurement, ...)
    content: str          # the extracted insight (max 100 words)
    entities: list[str]   # entity names/ids mentioned (for lookup)
    keywords: list[str]   # for keyword-match retrieval
    confidence: float     # 0-1 from LLM extraction
    quality_score: float  # task quality that generated this
    source_task: str      # first 80 chars of task that produced this
    created_at: float = field(default_factory=time.time)


# ── Storage ───────────────────────────────────────────────────────────────────

def _load() -> list[dict]:
    try:
        if os.path.exists(KNOWLEDGE_PATH):
            with open(KNOWLEDGE_PATH) as f:
                return json.load(f)
    except Exception:
        pass
    return []


def _save(entries: list[dict]) -> None:
    try:
        with open(KNOWLEDGE_PATH, "w") as f:
            json.dump(entries[-MAX_KNOWLEDGE_ENTRIES:], f, indent=2)
    except Exception:
        pass


# ── Extraction ────────────────────────────────────────────────────────────────

def _extract_keywords(text: str) -> list[str]:
    stop = {"the","a","an","is","are","was","were","be","been","have","has","had",
            "do","does","did","will","would","could","should","can","for","in","on",
            "at","to","of","and","or","but","with","from","this","that","it","i",
            "you","please","need","want","help","task","make","get","use","all","any"}
    words = text.lower().split()
    seen, unique = set(), []
    for w in words:
        w = w.strip(".,!?;:\"'()[]{}$%")
        if len(w) > 2 and w not in stop and w not in seen:
            seen.add(w)
            unique.append(w)
    return unique[:20]


def _extract_entities_regex(text: str) -> list[str]:
    """Fast regex entity extraction — zero API cost."""
    import re
    entities = []

    # Dollar amounts
    for m in re.finditer(r'\$[\d,]+(?:\.\d{2})?(?:K|M|B)?', text):
        entities.append(m.group())

    # Percentages
    for m in re.finditer(r'\d+(?:\.\d+)?%', text):
        entities.append(m.group())

    # Named things: Title Case words (likely vendor/person names)
    for m in re.finditer(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b', text):
        val = m.group()
        if val not in ("The", "This", "That", "In", "At", "On", "For"):
            entities.append(val)

    # IDs: JIRA-123, INV-456, EMP-789
    for m in re.finditer(r'\b[A-Z]{2,8}-\d+\b', text):
        entities.append(m.group())

    # Emails
    for m in re.finditer(r'\b[\w.+-]+@[\w.-]+\.\w{2,}\b', text):
        entities.append(m.group())

    # Deduplicate preserving order
    seen, result = set(), []
    for e in entities:
        if e not in seen:
            seen.add(e)
            result.append(e)
    return result[:15]


async def _call_haiku_extract(task_text: str, answer: str, domain: str) -> list[dict]:
    """
    Call Haiku to extract 1-2 reusable factual insights.
    Returns list of {content, confidence} dicts.
    Graceful no-op if API unavailable.
    """
    if not ANTHROPIC_API_KEY:
        return []
    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
        task_snippet = task_text[:300]
        answer_snippet = answer[:400]

        resp = await client.messages.create(
            model=EXTRACT_MODEL,
            max_tokens=256,
            messages=[{
                "role": "user",
                "content": (
                    f"Domain: {domain}\n"
                    f"Task: {task_snippet}\n"
                    f"Result: {answer_snippet}\n\n"
                    "Extract 1-2 SHORT, reusable factual insights from this completed task. "
                    "Focus on: vendor terms, entity-specific rules, policy thresholds, "
                    "process patterns, or constraints that would help future similar tasks.\n\n"
                    "Return JSON array: [{\"content\": \"...\", \"confidence\": 0.0-1.0}]\n"
                    "Each insight max 50 words. Only facts, no instructions."
                ),
            }],
        )
        text = resp.content[0].text if resp.content else ""
        # Parse JSON from response
        import re
        m = re.search(r'\[.*?\]', text, re.DOTALL)
        if m:
            insights = json.loads(m.group())
            if isinstance(insights, list):
                return [i for i in insights if isinstance(i, dict) and "content" in i]
    except Exception:
        pass
    return []


# ── Public API ────────────────────────────────────────────────────────────────

async def extract_and_store(
    task_text: str,
    answer: str,
    domain: str,
    quality: float,
) -> int:
    """
    Extract knowledge from a completed task and store it.
    Called in REFLECT phase by worker_brain.py after RL recording.
    Returns number of new insights stored (0 if quality too low or extraction failed).
    Fire-and-forget safe — never raises.
    """
    if quality < EXTRACTION_THRESHOLD:
        return 0
    if not task_text or not answer:
        return 0

    try:
        insights = await _call_haiku_extract(task_text, answer, domain)

        # Fallback: if Haiku unavailable, store a minimal fact from answer
        if not insights and len(answer) > 100:
            insights = [{"content": answer[:120].replace("\n", " "), "confidence": 0.7}]

        if not insights:
            return 0

        entries = _load()
        existing_ids = {e.get("entry_id") for e in entries}
        entities = _extract_entities_regex(task_text + " " + answer)
        keywords = _extract_keywords(task_text)
        new_count = 0

        for insight in insights[:2]:   # max 2 per task
            content = insight.get("content", "").strip()
            if not content or len(content) < 10:
                continue
            conf = float(insight.get("confidence", 0.75))
            entry_id = hashlib.md5(f"{domain}:{content[:40]}".encode()).hexdigest()[:8]
            if entry_id in existing_ids:
                continue

            entry = KnowledgeEntry(
                entry_id=entry_id,
                domain=domain,
                content=content,
                entities=entities,
                keywords=keywords,
                confidence=conf,
                quality_score=round(quality, 3),
                source_task=task_text[:80],
            )
            entries.append(asdict(entry))
            new_count += 1

        if new_count:
            _save(entries)
        return new_count
    except Exception:
        return 0


def get_relevant_knowledge(task_text: str, domain: str, top_k: int = 4) -> str:
    """
    Retrieve relevant past knowledge for injection into PRIME phase.
    Uses keyword overlap + entity matching + domain affinity.
    Returns a formatted string for the system prompt, or "" if nothing relevant.
    """
    entries = _load()
    if not entries:
        return ""

    task_kw = set(_extract_keywords(task_text))
    task_entities = set(e.lower() for e in _extract_entities_regex(task_text))

    scored = []
    for e in entries:
        score = 0.0
        # Keyword overlap
        kw_overlap = len(task_kw & set(e.get("keywords", [])))
        score += kw_overlap * 0.4
        # Entity overlap (highest weight — same vendor/customer = very relevant)
        ent_overlap = sum(
            1 for ent in e.get("entities", [])
            if ent.lower() in task_entities or any(ent.lower() in te for te in task_entities)
        )
        score += ent_overlap * 0.8
        # Domain affinity
        if e.get("domain") == domain:
            score += 0.3
        # Quality weight
        score += e.get("quality_score", 0) * 0.2
        if score >= 0.4:
            scored.append((score, e))

    if not scored:
        return ""

    scored.sort(key=lambda x: -x[0])
    top = [e for _, e in scored[:top_k]]

    lines = ["## KNOWLEDGE BASE (facts from past tasks — apply where relevant)"]
    for e in top:
        conf_str = f" (confidence: {e['confidence']:.0%})" if e.get("confidence") else ""
        lines.append(f"  • [{e.get('domain', 'general')}]{conf_str} {e['content']}")
    lines.append("")
    return "\n".join(lines)
