from __future__ import annotations
import os

BRAINOS_API_URL = os.getenv("BRAINOS_API_URL", "https://platform.usebrainos.com")
BRAINOS_API_KEY = os.getenv("BRAINOS_API_KEY", "")
BRAINOS_ORG_ID = os.getenv("BRAINOS_ORG_ID", "")
GREEN_AGENT_MCP_URL = os.getenv("GREEN_AGENT_MCP_URL", "http://localhost:9009")
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL", "claude-sonnet-4-6")
TOOL_TIMEOUT = int(os.getenv("TOOL_TIMEOUT", "10"))
TASK_TIMEOUT = int(os.getenv("TASK_TIMEOUT", "120"))
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
