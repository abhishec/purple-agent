"""
fsm_runner.py
Lightweight FSM for structured business process execution.
Inspired by BrainOS process-intelligence/fsm-runner.ts + process-registry.ts.

States: DECOMPOSE → ASSESS → POLICY_CHECK → EXECUTE → COMPLETE
Error paths: ESCALATE, FAILED

16 process types detected from task text keywords (same as BrainOS registry).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FSMState(str, Enum):
    DECOMPOSE     = "DECOMPOSE"
    ASSESS        = "ASSESS"
    POLICY_CHECK  = "POLICY_CHECK"
    APPROVAL_GATE = "APPROVAL_GATE"
    EXECUTE       = "EXECUTE"
    COMPLETE      = "COMPLETE"
    ESCALATE      = "ESCALATE"
    FAILED        = "FAILED"


# Process type → ordered FSM states
# Mirrors BrainOS process-registry.ts 16 built-in types
PROCESS_TEMPLATES: dict[str, list[FSMState]] = {
    "expense_approval": [
        FSMState.DECOMPOSE, FSMState.ASSESS, FSMState.POLICY_CHECK,
        FSMState.APPROVAL_GATE, FSMState.EXECUTE, FSMState.COMPLETE,
    ],
    "procurement": [
        FSMState.DECOMPOSE, FSMState.ASSESS, FSMState.POLICY_CHECK,
        FSMState.APPROVAL_GATE, FSMState.EXECUTE, FSMState.COMPLETE,
    ],
    "hr_offboarding": [
        FSMState.DECOMPOSE, FSMState.ASSESS, FSMState.POLICY_CHECK,
        FSMState.EXECUTE, FSMState.COMPLETE,
    ],
    "incident_response": [
        FSMState.DECOMPOSE, FSMState.ASSESS,
        FSMState.EXECUTE, FSMState.COMPLETE,
    ],
    "invoice_reconciliation": [
        FSMState.DECOMPOSE, FSMState.ASSESS, FSMState.POLICY_CHECK,
        FSMState.EXECUTE, FSMState.COMPLETE,
    ],
    "customer_onboarding": [
        FSMState.DECOMPOSE, FSMState.ASSESS,
        FSMState.EXECUTE, FSMState.COMPLETE,
    ],
    "compliance_audit": [
        FSMState.DECOMPOSE, FSMState.ASSESS, FSMState.POLICY_CHECK,
        FSMState.APPROVAL_GATE, FSMState.EXECUTE, FSMState.COMPLETE,
    ],
    "dispute_resolution": [
        FSMState.DECOMPOSE, FSMState.ASSESS, FSMState.POLICY_CHECK,
        FSMState.EXECUTE, FSMState.COMPLETE,
    ],
    "order_management": [
        FSMState.DECOMPOSE, FSMState.ASSESS,
        FSMState.EXECUTE, FSMState.COMPLETE,
    ],
    "sla_breach": [
        FSMState.DECOMPOSE, FSMState.ASSESS, FSMState.POLICY_CHECK,
        FSMState.ESCALATE,
    ],
    "general": [
        FSMState.DECOMPOSE, FSMState.ASSESS,
        FSMState.EXECUTE, FSMState.COMPLETE,
    ],
}

# Keywords → process type
PROCESS_KEYWORDS: dict[str, list[str]] = {
    "expense_approval":       ["expense", "reimbursement", "approval", "spend", "budget", "receipt", "claim"],
    "procurement":            ["vendor", "purchase", "order", "contract", "supplier", "rfp", "quote", "procurement"],
    "hr_offboarding":         ["offboard", "terminate", "resignation", "exit", "departing", "leaving", "offboarding"],
    "incident_response":      ["incident", "outage", "breach", "alert", "critical", "down", "failure", "p0", "p1"],
    "invoice_reconciliation": ["invoice", "reconcil", "payment", "billing", "overdue", "accounts payable"],
    "customer_onboarding":    ["onboard", "new customer", "setup", "provision", "activate", "signup"],
    "compliance_audit":       ["audit", "compliance", "regulation", "gdpr", "sox", "policy violation", "violation"],
    "dispute_resolution":     ["dispute", "chargeback", "refund", "complaint", "escalat", "resolution"],
    "order_management":       ["order", "fulfillment", "shipment", "delivery", "tracking", "return"],
    "sla_breach":             ["sla", "breach", "missed deadline", "overdue ticket", "past due"],
}


def detect_process_type(task_text: str) -> str:
    """Detect process type from task text. Returns 'general' if no match."""
    text = task_text.lower()
    best, best_count = "general", 0
    for ptype, keywords in PROCESS_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in text)
        if count > best_count:
            best_count, best = count, ptype
    return best


@dataclass
class FSMContext:
    task_text: str
    session_id: str
    process_type: str
    current_state: FSMState = FSMState.DECOMPOSE
    state_history: list[str] = field(default_factory=list)
    policy_result: dict | None = None
    requires_hitl: bool = False
    escalation_reason: str = ""
    data: dict[str, Any] = field(default_factory=dict)


class FSMRunner:
    """
    Lightweight FSM runner for business process tasks.
    Mirrors BrainOS BPaaSFSMRunner core logic.

    Provides:
    - Process type detection from task text
    - State-gated execution with policy checks
    - HITL detection at APPROVAL_GATE
    - Per-phase prompt injection
    """

    def __init__(self, task_text: str, session_id: str, process_type: str | None = None):
        ptype = process_type or detect_process_type(task_text)
        self.ctx = FSMContext(task_text=task_text, session_id=session_id, process_type=ptype)
        self.states = PROCESS_TEMPLATES.get(ptype, PROCESS_TEMPLATES["general"])
        self._idx = 0

    @property
    def current_state(self) -> FSMState:
        return self.ctx.current_state

    @property
    def process_type(self) -> str:
        return self.ctx.process_type

    @property
    def is_terminal(self) -> bool:
        return self.ctx.current_state in (FSMState.COMPLETE, FSMState.FAILED, FSMState.ESCALATE)

    def advance(self, data: dict | None = None) -> FSMState:
        """Advance to next state in the process template."""
        if data:
            self.ctx.data.update(data)
        self.ctx.state_history.append(self.ctx.current_state.value)
        self._idx += 1
        self.ctx.current_state = (
            self.states[self._idx] if self._idx < len(self.states) else FSMState.COMPLETE
        )
        return self.ctx.current_state

    def fail(self, reason: str) -> FSMState:
        self.ctx.state_history.append(self.ctx.current_state.value)
        self.ctx.current_state = FSMState.FAILED
        self.ctx.data["failure_reason"] = reason
        return FSMState.FAILED

    def escalate(self, reason: str) -> FSMState:
        self.ctx.state_history.append(self.ctx.current_state.value)
        self.ctx.current_state = FSMState.ESCALATE
        self.ctx.escalation_reason = reason
        self.ctx.requires_hitl = True
        return FSMState.ESCALATE

    def apply_policy(self, policy_result: dict) -> FSMState:
        """Apply deterministic policy result at POLICY_CHECK state."""
        self.ctx.policy_result = policy_result
        if not policy_result.get("passed"):
            if policy_result.get("escalationRequired"):
                return self.escalate(policy_result.get("summary", "Policy escalation required"))
            if policy_result.get("requiresApproval"):
                self.ctx.requires_hitl = True
        return self.advance()

    def build_phase_prompt(self) -> str:
        """
        Build a phase-aware prompt block to inject into the system prompt.
        Tells Claude exactly what phase it's in and what's expected.
        """
        state = self.ctx.current_state
        process = self.ctx.process_type.replace("_", " ").title()
        history_str = " → ".join(self.ctx.state_history + [state.value])

        lines = [
            f"## Business Process: {process}",
            f"## Execution Phase: {state.value}",
            f"## Phase History: {history_str}",
            "",
        ]

        instructions = {
            FSMState.DECOMPOSE:     "Break this task into sub-tasks and identify all data you need before acting.",
            FSMState.ASSESS:        "Gather all required data via tools. Do NOT take any actions yet — only collect.",
            FSMState.POLICY_CHECK:  "Verify all policy rules are satisfied before proceeding. Do not skip this.",
            FSMState.APPROVAL_GATE: "Human approval is required. Summarize what needs approval and why.",
            FSMState.EXECUTE:       "Execute all required actions end-to-end using tools. Be complete.",
            FSMState.COMPLETE:      "Summarize all completed actions and their outcomes concisely.",
            FSMState.ESCALATE:      f"ESCALATION: {self.ctx.escalation_reason}. Summarize why escalation is needed.",
            FSMState.FAILED:        f"FAILED: {self.ctx.data.get('failure_reason', 'Unknown')}. Explain what went wrong.",
        }
        lines.append(instructions.get(state, "Execute the current phase."))
        return "\n".join(lines)

    def get_summary(self) -> dict:
        return {
            "process_type": self.ctx.process_type,
            "final_state": self.ctx.current_state.value,
            "state_history": self.ctx.state_history,
            "requires_hitl": self.ctx.requires_hitl,
            "escalation_reason": self.ctx.escalation_reason,
        }
