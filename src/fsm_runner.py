"""
fsm_runner.py
8-state FSM for structured business process execution.

Wave 7: build_phase_prompt() now reads per-state instructions from
process_definitions.py (data layer) instead of hardcoded strings.
Also accepts available_tools list → injects tool-awareness at each state.

The executor is generic. The definitions are smart. Never hardcode
"what to do at DECOMPOSE" here — put it in process_definitions.py.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FSMState(str, Enum):
    DECOMPOSE       = "DECOMPOSE"
    ASSESS          = "ASSESS"
    COMPUTE         = "COMPUTE"
    POLICY_CHECK    = "POLICY_CHECK"
    APPROVAL_GATE   = "APPROVAL_GATE"
    MUTATE          = "MUTATE"
    SCHEDULE_NOTIFY = "SCHEDULE_NOTIFY"
    COMPLETE        = "COMPLETE"
    ESCALATE        = "ESCALATE"
    FAILED          = "FAILED"


# Process type → ordered FSM states
PROCESS_TEMPLATES: dict[str, list[FSMState]] = {
    "expense_approval":       [FSMState.DECOMPOSE, FSMState.ASSESS, FSMState.COMPUTE, FSMState.POLICY_CHECK, FSMState.APPROVAL_GATE, FSMState.MUTATE, FSMState.COMPLETE],
    "procurement":            [FSMState.DECOMPOSE, FSMState.ASSESS, FSMState.COMPUTE, FSMState.POLICY_CHECK, FSMState.APPROVAL_GATE, FSMState.MUTATE, FSMState.SCHEDULE_NOTIFY, FSMState.COMPLETE],
    "hr_offboarding":         [FSMState.DECOMPOSE, FSMState.ASSESS, FSMState.POLICY_CHECK, FSMState.MUTATE, FSMState.SCHEDULE_NOTIFY, FSMState.COMPLETE],
    "incident_response":      [FSMState.DECOMPOSE, FSMState.ASSESS, FSMState.COMPUTE, FSMState.APPROVAL_GATE, FSMState.MUTATE, FSMState.SCHEDULE_NOTIFY, FSMState.COMPLETE],
    "invoice_reconciliation": [FSMState.DECOMPOSE, FSMState.ASSESS, FSMState.COMPUTE, FSMState.POLICY_CHECK, FSMState.MUTATE, FSMState.COMPLETE],
    "customer_onboarding":    [FSMState.DECOMPOSE, FSMState.ASSESS, FSMState.MUTATE, FSMState.SCHEDULE_NOTIFY, FSMState.COMPLETE],
    "compliance_audit":       [FSMState.DECOMPOSE, FSMState.ASSESS, FSMState.COMPUTE, FSMState.POLICY_CHECK, FSMState.APPROVAL_GATE, FSMState.MUTATE, FSMState.SCHEDULE_NOTIFY, FSMState.COMPLETE],
    "dispute_resolution":     [FSMState.DECOMPOSE, FSMState.ASSESS, FSMState.POLICY_CHECK, FSMState.APPROVAL_GATE, FSMState.MUTATE, FSMState.COMPLETE],
    "order_management":       [FSMState.DECOMPOSE, FSMState.ASSESS, FSMState.COMPUTE, FSMState.APPROVAL_GATE, FSMState.MUTATE, FSMState.COMPLETE],
    "sla_breach":             [FSMState.DECOMPOSE, FSMState.ASSESS, FSMState.COMPUTE, FSMState.POLICY_CHECK, FSMState.SCHEDULE_NOTIFY, FSMState.ESCALATE],
    "month_end_close":        [FSMState.DECOMPOSE, FSMState.ASSESS, FSMState.COMPUTE, FSMState.POLICY_CHECK, FSMState.APPROVAL_GATE, FSMState.MUTATE, FSMState.COMPLETE],
    "ar_collections":         [FSMState.DECOMPOSE, FSMState.ASSESS, FSMState.COMPUTE, FSMState.POLICY_CHECK, FSMState.MUTATE, FSMState.SCHEDULE_NOTIFY, FSMState.COMPLETE],
    "subscription_migration": [FSMState.DECOMPOSE, FSMState.ASSESS, FSMState.COMPUTE, FSMState.POLICY_CHECK, FSMState.APPROVAL_GATE, FSMState.MUTATE, FSMState.COMPLETE],
    "payroll":                [FSMState.DECOMPOSE, FSMState.ASSESS, FSMState.COMPUTE, FSMState.POLICY_CHECK, FSMState.APPROVAL_GATE, FSMState.MUTATE, FSMState.SCHEDULE_NOTIFY, FSMState.COMPLETE],
    "general":                [FSMState.DECOMPOSE, FSMState.ASSESS, FSMState.MUTATE, FSMState.COMPLETE],
}

PROCESS_KEYWORDS: dict[str, list[str]] = {
    "expense_approval":       ["expense", "reimbursement", "approval", "spend", "budget", "receipt", "claim"],
    "procurement":            ["vendor", "purchase", "order", "contract", "supplier", "rfp", "quote", "procurement"],
    "hr_offboarding":         ["offboarding", "offboard", "termination", "access revocation", "exit", "last day"],
    "incident_response":      ["incident", "outage", "down", "breach", "alert", "p1", "p2", "emergency", "sev"],
    "invoice_reconciliation": ["invoice", "reconcile", "reconciliation", "statement", "bill", "ap ", "accounts payable"],
    "customer_onboarding":    ["onboarding", "onboard", "new customer", "new client", "setup", "provision"],
    "compliance_audit":       ["compliance", "audit", "kyc", "gdpr", "pci", "sox", "regulatory", "review"],
    "dispute_resolution":     ["dispute", "chargeback", "complaint", "resolution", "contested", "claim"],
    "order_management":       ["order", "shipment", "delivery", "fulfillment", "cart", "item", "product"],
    "sla_breach":             ["sla", "service level", "uptime", "downtime", "breach", "penalty", "credit"],
    "month_end_close":        ["month-end", "month end", "close", "p&l", "financial close", "accounting", "books"],
    "ar_collections":         ["accounts receivable", "ar ", "aging", "overdue", "collection", "payment plan", "bad debt"],
    "subscription_migration": ["migrate", "migration", "downgrade", "upgrade", "plan change", "subscription change"],
    "payroll":                ["payroll", "salary", "wages", "compensation", "pay run", "paye", "bacs"],
    "general":                [],
}


def detect_process_type(task_text: str) -> str:
    text = task_text.lower()
    best_type, best_score = "general", 0
    for ptype, keywords in PROCESS_KEYWORDS.items():
        if ptype == "general":
            continue
        score = sum(1 for kw in keywords if kw in text)
        if score > best_score:
            best_score, best_type = score, ptype
    return best_type


@dataclass
class FSMContext:
    task_text: str
    session_id: str
    process_type: str
    current_state: FSMState = FSMState.DECOMPOSE
    state_history: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    policy_result: dict | None = None
    escalation_reason: str = ""
    requires_hitl: bool = False
    approval_count: int = 0


class FSMRunner:
    """
    8-state FSM. Generic executor — instructions come from process_definitions.py.
    Wave 7: build_phase_prompt() is connector-aware via available_tools param.
    """

    def __init__(self, task_text: str, session_id: str, process_type: str | None = None, checkpoint=None):
        ptype = process_type or detect_process_type(task_text)
        self.ctx = FSMContext(task_text=task_text, session_id=session_id, process_type=ptype)
        self.states = PROCESS_TEMPLATES.get(ptype, PROCESS_TEMPLATES["general"])
        self._idx = 0

        if checkpoint:
            self.ctx.process_type = checkpoint.process_type
            self.states = PROCESS_TEMPLATES.get(checkpoint.process_type, PROCESS_TEMPLATES["general"])
            self._idx = checkpoint.state_idx
            self.ctx.state_history = list(checkpoint.state_history)
            self.ctx.current_state = (
                self.states[self._idx] if self._idx < len(self.states) else FSMState.COMPLETE
            )

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
        self.ctx.policy_result = policy_result
        if not policy_result.get("passed"):
            if policy_result.get("escalationRequired"):
                return self.escalate(policy_result.get("summary", "Policy escalation required"))
            if policy_result.get("requiresApproval"):
                self.ctx.requires_hitl = True
        return self.advance()

    def reopen_approval_gate(self) -> None:
        if self.ctx.current_state == FSMState.MUTATE:
            self.ctx.state_history.append(FSMState.MUTATE.value)
            self.ctx.current_state = FSMState.APPROVAL_GATE
            self.ctx.approval_count += 1

    def build_phase_prompt(self, available_tools: list[dict] | None = None) -> str:
        """
        Wave 7: reads instruction from process_definitions.py (data layer).
        Falls back to generic instruction if process has no specific definition.
        Injects tool-awareness if available_tools provided.
        """
        from src.process_definitions import get_state_instruction, get_connector_hints

        state = self.ctx.current_state
        process = self.ctx.process_type.replace("_", " ").title()
        history_str = " → ".join(self.ctx.state_history + [state.value])

        lines = [
            f"## Business Process: {process}",
            f"## Execution Phase: {state.value}",
            f"## Phase History: {history_str}",
            "",
        ]

        # Read instruction from data layer (not hardcoded here)
        instruction = get_state_instruction(self.ctx.process_type, state.value)

        # Special overrides for terminal/error states (these don't live in definitions)
        if state == FSMState.ESCALATE:
            instruction = (
                f"ESCALATION REQUIRED: {self.ctx.escalation_reason}\n"
                "Do not attempt to resolve this yourself. "
                "Explain clearly why escalation is needed and who must act."
            )
        elif state == FSMState.FAILED:
            instruction = (
                f"FAILED: {self.ctx.data.get('failure_reason', 'Unknown error')}\n"
                "Explain what went wrong and what the next step should be."
            )
        elif not instruction:
            # Absolute fallback — should rarely fire since process_definitions covers all states
            instruction = f"Execute the {state.value} phase for this {process} process."

        lines.append(instruction)

        # Tool awareness injection (Wave 7)
        if available_tools:
            tool_names = [t.get("name", "") for t in available_tools if t.get("name")]
            hints = get_connector_hints(self.ctx.process_type)

            # At ASSESS: call out read tools by name
            if state == FSMState.ASSESS and tool_names:
                read_tools = [
                    n for n in tool_names
                    if any(n.startswith(p) for p in ("get_", "list_", "fetch_", "search_", "read_", "check_"))
                ]
                if read_tools:
                    lines.append(f"\nAvailable read tools: {', '.join(read_tools[:12])}")

            # At MUTATE: call out mutation tools by name
            elif state == FSMState.MUTATE and tool_names:
                mutate_tools = [
                    n for n in tool_names
                    if any(n.startswith(p) for p in ("create_", "update_", "delete_", "send_", "approve_", "submit_", "cancel_", "post_"))
                ]
                if mutate_tools:
                    lines.append(f"\nAvailable mutation tools: {', '.join(mutate_tools[:12])}")

            # At SCHEDULE_NOTIFY: call out notify/schedule tools
            elif state == FSMState.SCHEDULE_NOTIFY and tool_names:
                notify_tools = [
                    n for n in tool_names
                    if any(n.startswith(p) for p in ("send_", "notify_", "schedule_", "post_", "email_", "slack_"))
                ]
                if notify_tools:
                    lines.append(f"\nAvailable notify/schedule tools: {', '.join(notify_tools[:8])}")

            # At DECOMPOSE: show connector hint for awareness
            elif state == FSMState.DECOMPOSE and hints:
                relevant = [n for n in tool_names if any(h in n.lower() for h in hints)]
                if relevant:
                    lines.append(f"\nConnectors available for this process: {', '.join(relevant[:8])}")
                elif tool_names:
                    lines.append(f"\nAll available tools: {', '.join(tool_names[:10])}")

        if self.ctx.approval_count > 0:
            lines.append(f"\n[Multi-checkpoint: approval gate #{self.ctx.approval_count + 1}]")

        return "\n".join(lines)

    def get_summary(self) -> dict:
        return {
            "process_type": self.ctx.process_type,
            "final_state": self.ctx.current_state.value,
            "state_history": self.ctx.state_history,
            "requires_hitl": self.ctx.requires_hitl,
            "escalation_reason": self.ctx.escalation_reason,
            "approval_count": self.ctx.approval_count,
        }
