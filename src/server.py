from __future__ import annotations
import os
import uuid
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

from src.worker_brain import run_worker   # MiniAIWorker replaces executor directly

app = FastAPI(title="BrainOS Purple Agent", version="2.0.0")

AGENT_CARD = {
    "name": "BrainOS Purple Agent",
    "description": (
        "Mini AI Worker — a competition-focused distillation of the BrainOS AI Worker. "
        "8-state FSM, deterministic policy enforcement, Haiku memory compression, "
        "financial arithmetic, schema drift resilience, and RL quality loop."
    ),
    "version": "2.0.0",
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
    return {"status": "ok", "agent": "brainos-mini-ai-worker", "version": "2.0.0"}


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
