from __future__ import annotations
import os
import uuid
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

from src.worker_brain import run_worker   # MiniAIWorker replaces executor directly

app = FastAPI(title="BrainOS Purple Agent", version="2.1.0")

AGENT_CARD = {
    "name": "BrainOS Purple Agent",
    "description": (
        "Mini AI Worker — a competition-focused distillation of the BrainOS AI Worker. "
        "8-state FSM, deterministic policy enforcement, Haiku memory compression, "
        "financial arithmetic, schema drift resilience, RL quality loop, "
        "and S3-seeded benchmark training (Wave 6)."
    ),
    "version": "2.1.0",
    "url": os.getenv("PURPLE_AGENT_CARD_URL", "https://purple.agentbench.usebrainos.com"),
    "capabilities": {"streaming": False, "tools": True},
    "skills": [{
        "id": "business-process",
        "name": "Business Process AI Worker",
        "description": (
            "End-to-end business process execution: expense approval, procurement, "
            "offboarding, invoice reconciliation, SLA breach, order management, "
            "compliance audit, dispute resolution, AR collections, month-end close."
        ),
    }],
}


@app.get("/.well-known/agent-card.json")
async def agent_card():
    return JSONResponse(AGENT_CARD)


@app.get("/health")
async def health():
    from src.training_loader import is_stale as training_stale
    import os as _os
    intel_path = _os.path.join(_os.path.dirname(__file__), "..", "benchmark_intelligence.json")
    return {
        "status": "ok",
        "agent": "brainos-mini-ai-worker",
        "version": "2.1.0",
        "training_stale": training_stale(),
        "has_benchmark_intelligence": _os.path.exists(intel_path),
    }


@app.post("/")
async def a2a_handler(request: Request):
    body = await request.json()

    if body.get("method") != "tasks/send":
        raise HTTPException(400, "Only tasks/send method supported")

    params = body.get("params", {})
    task_id = params.get("id", str(uuid.uuid4()))
    message = params.get("message", {})
    metadata = params.get("metadata", {})

    task_text = "".join(p.get("text", "") for p in message.get("parts", []))
    policy_doc = metadata.get("policy_doc", "")
    tools_endpoint = metadata.get("tools_endpoint", "")
    session_id = metadata.get("session_id", task_id)

    answer = await run_worker(
        task_text=task_text,
        policy_doc=policy_doc,
        tools_endpoint=tools_endpoint,
        task_id=task_id,
        session_id=session_id,
    )

    return {
        "jsonrpc": "2.0",
        "result": {
            "id": task_id,
            "status": {"state": "completed"},
            "artifacts": [{"parts": [{"text": answer}]}],
        },
    }


# ── Wave 6: Training management endpoints ─────────────────────────────────────

@app.post("/training/sync")
async def training_sync(request: Request):
    """
    Force-refresh training data from S3 + benchmark reports.
    POST /training/sync?force=true to bypass staleness check.
    """
    import asyncio
    params = dict(request.query_params)
    force = params.get("force", "false").lower() == "true"

    results = {}

    def _sync():
        from src.training_loader import seed_from_training_data
        from src.report_analyzer import analyze_and_save
        results["training"] = seed_from_training_data(force=force)
        results["reports"] = analyze_and_save(force=force)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _sync)

    return {
        "status": "synced",
        "training": results.get("training", {}),
        "reports": results.get("reports", {}),
    }


@app.get("/training/status")
async def training_status():
    """Show current training data + benchmark intelligence status."""
    import json as _json
    import os as _os
    import time as _time

    from src.training_loader import SEED_MARKER_PATH, STALE_HOURS, is_stale
    from src.report_analyzer import INTELLIGENCE_PATH, load_intelligence
    from src.rl_loop import _load_cases

    cases = _load_cases()
    seeded = [c for c in cases if c.get("quality", 0) == 1.0]
    intel = load_intelligence()

    seed_age_h = None
    if _os.path.exists(SEED_MARKER_PATH):
        seed_age_h = round((_time.time() - _os.path.getmtime(SEED_MARKER_PATH)) / 3600, 1)

    return {
        "training_stale": is_stale(),
        "seed_age_hours": seed_age_h,
        "case_log_total": len(cases),
        "seeded_entries": len(seeded),
        "live_entries": len(cases) - len(seeded),
        "benchmark_intelligence": {
            "available": bool(intel),
            "overall_score": intel.get("overall_score"),
            "weak_dimensions": [d["dimension"] for d in intel.get("weak_dimensions", [])],
            "failure_patterns": len(intel.get("failure_patterns", [])),
        },
    }
