"""
Core A2A agent implementation for the Purple Business Process Agent.
Wraps Claude 3.5 Sonnet with business process capabilities.
"""
import asyncio
import logging
import os
from typing import Any

import anthropic
from a2a.server.tasks import TaskUpdater
from a2a.types import Message, Part, TaskState, TextPart
from a2a.utils import get_message_text, new_agent_text_message

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a highly capable business process automation agent. You excel at:
- Airline reservation management (bookings, cancellations, changes, refunds)
- Retail order processing (orders, returns, refunds, tracking)
- Customer relationship management (customer data, complaints, requests)
- Employee management (HR processes, scheduling, payroll)
- Financial workflows (payments, approvals, reconciliations)
- General business process automation

When given a task:
1. Understand the request clearly
2. Use the available tools/context to complete it
3. Provide a clear, concise response with the outcome
4. If you need to perform multiple steps, do them systematically

Always be direct and action-oriented. Complete tasks efficiently."""

MAX_TOKENS = 4096
MAX_TURNS = 20


class A2AAgent:
    """Business process agent using Claude 3.5 Sonnet."""

    def __init__(self):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.history: list[dict] = []
        logger.info("A2AAgent initialized with Claude 3.5 Sonnet")

    async def run(self, message: Message, updater: TaskUpdater) -> None:
        """Process an A2A message and return a response."""
        input_text = get_message_text(message)
        if not input_text:
            await updater.complete(
                new_agent_text_message("No task text provided.", 
                                       context_id=message.context_id or "")
            )
            return

        logger.info(f"Processing task: {input_text[:200]}...")
        await updater.update_status(
            TaskState.working,
            new_agent_text_message("Processing your request...", 
                                   context_id=message.context_id or "")
        )

        # Add user message to history
        self.history.append({"role": "user", "content": input_text})

        try:
            # Use asyncio to run sync Claude call in thread pool
            response_text = await asyncio.get_event_loop().run_in_executor(
                None, self._call_claude
            )
            
            # Add assistant response to history
            self.history.append({"role": "assistant", "content": response_text})

            logger.info(f"Task completed. Response length: {len(response_text)}")

            # Return result as artifact
            await updater.add_artifact(
                parts=[Part(root=TextPart(text=response_text))],
                name="result",
                artifact_id="result-001",
            )
            await updater.complete()

        except Exception as e:
            logger.error(f"Claude call failed: {e}", exc_info=True)
            raise

    def _call_claude(self) -> str:
        """Synchronous Claude API call."""
        response = self.client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=self.history,
        )
        return response.content[0].text
