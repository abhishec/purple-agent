"""
session_context.py
Multi-turn A2A conversation context — per session_id history with compression.
Inspired by BrainOS memory compression + brain context mesh.

Each A2A session_id gets its own context window.
Older turns are compressed into a summary; recent 6 turns stay raw.
Evicts sessions idle for > 1 hour.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field

MAX_SESSION_AGE = 3600   # 1 hour idle → evict
MAX_RAW_TURNS = 20       # compress when exceeded
KEEP_RECENT = 6

_sessions: dict[str, "SessionContext"] = {}


@dataclass
class Turn:
    role: str       # "user" | "assistant"
    content: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class SessionContext:
    session_id: str
    turns: list[Turn] = field(default_factory=list)
    compressed_summary: str = ""
    process_type: str = "general"
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)


def get_or_create(session_id: str) -> SessionContext:
    _evict_stale()
    if session_id not in _sessions:
        _sessions[session_id] = SessionContext(session_id=session_id)
    return _sessions[session_id]


def add_turn(session_id: str, role: str, content: str) -> None:
    ctx = get_or_create(session_id)
    ctx.turns.append(Turn(role=role, content=content))
    ctx.last_active = time.time()
    if len(ctx.turns) > MAX_RAW_TURNS:
        _compress_inline(ctx)


def get_context_prompt(session_id: str) -> str:
    """
    Returns compressed summary + recent turns formatted for system prompt injection.
    Empty string if this is the first turn in the session.
    """
    ctx = _sessions.get(session_id)
    if not ctx or (not ctx.compressed_summary and not ctx.turns):
        return ""

    parts = []
    if ctx.compressed_summary:
        parts.append(f"## Prior Conversation Summary\n{ctx.compressed_summary}")

    recent = ctx.turns[-KEEP_RECENT:]
    if recent:
        parts.append("## Recent Conversation")
        for t in recent:
            label = "User" if t.role == "user" else "Agent"
            parts.append(f"{label}: {t.content[:400]}")

    return "\n".join(parts)


def set_process_type(session_id: str, process_type: str) -> None:
    get_or_create(session_id).process_type = process_type


def get_process_type(session_id: str) -> str:
    ctx = _sessions.get(session_id)
    return ctx.process_type if ctx else "general"


def is_multi_turn(session_id: str) -> bool:
    ctx = _sessions.get(session_id)
    return bool(ctx and ctx.turns)


def _compress_inline(ctx: SessionContext) -> None:
    """Inline compression — truncates older turns into plain summary (no LLM call)."""
    older = ctx.turns[:-KEEP_RECENT]
    keep = ctx.turns[-KEEP_RECENT:]
    if not older:
        return
    lines = [f"{'User' if t.role == 'user' else 'Agent'}: {t.content[:200]}" for t in older]
    new_block = "\n".join(lines)
    ctx.compressed_summary = (
        ctx.compressed_summary + "\n\n" + new_block if ctx.compressed_summary else new_block
    )
    ctx.turns = keep


def _evict_stale() -> None:
    now = time.time()
    stale = [sid for sid, ctx in _sessions.items() if now - ctx.last_active > MAX_SESSION_AGE]
    for sid in stale:
        del _sessions[sid]
