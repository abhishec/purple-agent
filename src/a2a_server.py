"""
A2A-compatible server wrapper for the Purple Business Process Agent.
Exposes the agent via the A2A (Agent-to-Agent) protocol for AgentBeats assessments.
"""
import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from a2a_executor import A2AExecutor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def build_agent_card(host: str, port: int, card_url: str | None) -> AgentCard:
    url = card_url or f"http://{host}:{port}/"
    skill = AgentSkill(
        id="business_process",
        name="Business Process Management",
        description=(
            "AI agent for automating business processes including employee management, "
            "payment processing, scheduling, customer service, and workflow automation. "
            "Handles airline reservations, retail orders, CRM tasks, and complex "
            "multi-step business workflows."
        ),
        tags=["business", "process", "automation", "workflow", "crm", "airline", "retail"],
        examples=[
            "Book a flight from NYC to LAX for tomorrow",
            "Process a refund for order #12345",
            "Schedule a meeting with the team next week",
            "Create a new employee record for John Smith",
        ],
    )
    return AgentCard(
        name="Purple Business Process Agent",
        description=(
            "A powerful business process automation agent built on Claude 3.5 Sonnet. "
            "Specializes in complex multi-step business workflows, tool use, and "
            "intelligent decision-making for enterprise processes."
        ),
        url=url,
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[skill],
    )


def main():
    parser = argparse.ArgumentParser(description="Purple Business Process Agent - A2A Server")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=9009, help="Port to bind to")
    parser.add_argument("--card-url", type=str, default=None, help="Public URL for agent card")
    args = parser.parse_args()

    logger.info(f"Starting A2A server on {args.host}:{args.port}")

    agent_card = build_agent_card(args.host, args.port, args.card_url)
    request_handler = DefaultRequestHandler(
        agent_executor=A2AExecutor(),
        task_store=InMemoryTaskStore(),
    )
    app = A2AStarletteApplication(agent_card=agent_card, http_handler=request_handler)
    uvicorn.run(app.build(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
