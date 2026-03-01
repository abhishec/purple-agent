"""
process_definitions.py
Per-process, per-state instructions — the DATA layer for the generic FSM executor.

Inspired by BrainOS bpaas_process_definitions.state_instructions column.
The executor is dumb; the definitions are smart.

Instead of hardcoding "what to do at DECOMPOSE" in the executor, each process
definition tells the executor what to do at each state. The FSM runner reads
this and builds the prompt. No hardcoding in the execution path.

Adding a new process type = add an entry here. Never touch fsm_runner.py.

Structure per process:
  state_instructions  — what Claude should do at each FSM state (process-specific)
  connector_hints     — which tool NAME PREFIXES are relevant (helps Claude prioritize)
  hitl_required       — whether this process always needs human approval
  risk_level          — "low" | "medium" | "high" — affects approval brief detail

IMPORTANT: state_instructions MUST NOT reference specific tool names.
They describe WHAT data to gather / WHAT action to take. Use phrases like
"use available read-only tools", "use the tools available for this workspace",
"look up", "retrieve", "fetch using whichever tools are available".
"""
from __future__ import annotations

PROCESS_DEFINITIONS: dict[str, dict] = {

    # ── FINANCIAL PROCESSES ────────────────────────────────────────────────

    "expense_approval": {
        "hitl_required": True,
        "risk_level": "medium",
        "connector_hints": ["expense", "finance", "slack", "email", "hr"],
        "state_instructions": {
            "DECOMPOSE": (
                "Identify: requester name, expense amount, category, date, "
                "receipt status, department, cost center, and business justification. "
                "Flag if any information is missing — clarify before proceeding."
            ),
            "ASSESS": (
                "Using the read-only tools available for this workspace, gather: "
                "the requester's remaining expense budget, their approval limit, "
                "the department policy document, and any prior reimbursements this period. "
                "Look up the requester's profile, their budget balance, and their expense history."
            ),
            "COMPUTE": (
                "Calculate: total claim amount (itemized), tax-deductible portion, "
                "policy threshold comparison (is amount within limit?), "
                "and year-to-date spend for this requester."
            ),
            "POLICY_CHECK": (
                "Verify: amount is within the requester's single-transaction limit, "
                "category is in the approved list, receipt is attached if required, "
                "and submission is within the 30-day window. Flag any violation."
            ),
            "APPROVAL_GATE": (
                "Approval required. Present: requester, amount, category, "
                "policy compliance status, computed totals. "
                "If amount exceeds $500: manager approval required. "
                "If amount exceeds $5,000: VP approval required. "
                "Do NOT call any create or update tools — wait for approval."
            ),
            "MUTATE": (
                "Approval received. Using the write tools available for this workspace, execute: "
                "record the approved expense, mark it as approved, "
                "update the budget allocation, and initiate reimbursement. "
                "Log each action taken."
            ),
            "COMPLETE": (
                "Summarize: total approved, reimbursement timeline, "
                "updated budget balance."
            ),
        },
    },

    "invoice_reconciliation": {
        "hitl_required": False,
        "risk_level": "medium",
        "connector_hints": ["invoice", "vendor", "finance", "erp", "accounting"],
        "state_instructions": {
            "DECOMPOSE": (
                "Identify: invoice number, vendor, amount, PO number, "
                "due date, line items. Extract all fields before proceeding."
            ),
            "ASSESS": (
                "Using the read-only tools available for this workspace, retrieve: "
                "the matching purchase order, the goods receipt record, "
                "vendor payment terms, and any prior invoices from this vendor. "
                "Look up the PO by number, the receipt by PO or delivery reference, "
                "and vendor terms from the vendor or contract record."
            ),
            "COMPUTE": (
                "Calculate: invoice-to-PO variance (must be less than 2% or less than $500 per policy), "
                "early payment discount if applicable, "
                "and late payment penalty if the invoice is past due. "
                "Use 6-decimal precision for boundary variance cases."
            ),
            "POLICY_CHECK": (
                "Verify: 3-way match passes (invoice matches PO matches goods receipt), "
                "amount variance is within tolerance, "
                "vendor is on the approved list, and payment terms match the contract."
            ),
            "MUTATE": (
                "3-way match passed. Using the write tools available for this workspace, execute: "
                "approve the invoice, schedule payment per vendor terms, "
                "and update the accounts payable ledger."
            ),
            "COMPLETE": (
                "Summarize: invoice approved or rejected, payment date, "
                "variance amount if any, and AP balance impact."
            ),
        },
    },

    "month_end_close": {
        "hitl_required": True,
        "risk_level": "high",
        "connector_hints": ["accounting", "erp", "finance", "ledger"],
        "state_instructions": {
            "DECOMPOSE": (
                "Identify: close period (month and year), entities in scope, "
                "checklist items including: accruals, reconciliations, journal entries, "
                "and intercompany eliminations."
            ),
            "ASSESS": (
                "Using the read-only tools available for this workspace, retrieve all open items "
                "per the close checklist: unapproved journal entries, unreconciled accounts, "
                "pending accruals, and intercompany imbalances. "
                "Look up each category of open item separately."
            ),
            "COMPUTE": (
                "Calculate: P&L by department, balance sheet movements, "
                "tax provision estimates, and revenue recognition adjustments. "
                "Apply straight-line depreciation for any new assets added this period."
            ),
            "POLICY_CHECK": (
                "Verify: all reconciliations are signed off, no unexplained variances exceed $1,000, "
                "management review is complete, and an audit trail exists for all adjustments."
            ),
            "APPROVAL_GATE": (
                "CFO sign-off required before period lock. "
                "Present: P&L summary, balance sheet, open items count, "
                "and material variances requiring explanation."
            ),
            "MUTATE": (
                "CFO approved. Using the write tools available for this workspace, execute: "
                "lock the accounting period, post final journal entries, "
                "and generate the trial balance."
            ),
            "COMPLETE": (
                "Period closed. Output: final trial balance hash, "
                "close timestamp, approver name, and open items deferred to next period."
            ),
        },
    },

    "ar_collections": {
        "hitl_required": False,
        "risk_level": "medium",
        "connector_hints": ["crm", "email", "finance", "billing"],
        "state_instructions": {
            "DECOMPOSE": (
                "Identify: customer, overdue amount, aging bucket (30/60/90+ days), "
                "invoice numbers, last payment date, and the assigned collector."
            ),
            "ASSESS": (
                "Using the read-only tools available for this workspace, retrieve: "
                "the customer's full payment history, credit limit, current outstanding balance, "
                "any open disputes, and the billing contact information. "
                "Look up the customer account record, payment records, and any open invoices."
            ),
            "COMPUTE": (
                "Calculate: total overdue amount broken down by aging bucket, "
                "applicable interest or late fees per contract terms, "
                "and a collectability score based on days overdue and invoice count."
            ),
            "POLICY_CHECK": (
                "Determine the appropriate collection action by aging tier: "
                "30-day bucket: send a courtesy reminder, "
                "60-day bucket: send a formal notice, "
                "90-day and beyond: escalate to a collections agency or legal team."
            ),
            "MUTATE": (
                "Using the write tools available for this workspace, send the appropriate "
                "communication per the policy tier. "
                "If a payment plan is agreed upon: create an installment schedule. "
                "If writing off the debt: create a bad debt record."
            ),
            "SCHEDULE_NOTIFY": (
                "Schedule: next follow-up reminder, "
                "payment plan due date alerts, "
                "and an escalation trigger if no response is received within 5 days."
            ),
            "COMPLETE": (
                "Summarize: action taken, amounts outstanding, "
                "next follow-up date, and predicted resolution."
            ),
        },
    },

    "payroll": {
        "hitl_required": True,
        "risk_level": "high",
        "connector_hints": ["hr", "payroll", "finance", "bank"],
        "state_instructions": {
            "DECOMPOSE": (
                "Identify: pay period, full employee list, pay types "
                "(regular hours, overtime, commission, bonus), "
                "and any off-cycle adjustments for this period."
            ),
            "ASSESS": (
                "Using the read-only tools available for this workspace, retrieve for each employee: "
                "hours worked, approved overtime, tax withholding settings, "
                "benefit deductions, garnishments, and year-to-date figures. "
                "Look up timesheets, HR records, and payroll configuration."
            ),
            "COMPUTE": (
                "Calculate for each employee: gross pay (regular hours times rate, plus overtime at 1.5x), "
                "all statutory deductions (federal and state tax, FICA), "
                "voluntary deductions (401k, health insurance), and net pay. "
                "Apply loan amortization for any pay advances on record."
            ),
            "POLICY_CHECK": (
                "Verify: total payroll is within the approved budget, "
                "no duplicate entries exist, all garnishments are applied, "
                "and overtime is manager-approved for each employee."
            ),
            "APPROVAL_GATE": (
                "Payroll director approval required before disbursement. "
                "Present: total gross pay, total deductions, total net pay, "
                "headcount, and any anomalies compared to the prior period."
            ),
            "MUTATE": (
                "Approved. Using the write tools available for this workspace, execute: "
                "submit the payroll file to the bank (ACH or BACS), "
                "update year-to-date accumulators for each employee, "
                "and record the payroll journal entry in accounting."
            ),
            "SCHEDULE_NOTIFY": (
                "Notify employees that pay stubs are available. "
                "Send the payroll summary to the finance team. "
                "Schedule the next pay run."
            ),
            "COMPLETE": (
                "Payroll run complete. Output: total amount disbursed, "
                "headcount paid, and next scheduled run date."
            ),
        },
    },

    # ── PROCUREMENT / VENDOR ────────────────────────────────────────────────

    "procurement": {
        "hitl_required": True,
        "risk_level": "medium",
        "connector_hints": ["vendor", "finance", "jira", "slack", "erp"],
        "state_instructions": {
            "DECOMPOSE": (
                "Identify: item or service requested, quantity, estimated cost, "
                "department, requester name, budget code, and business justification. "
                "Ask if any field is missing before proceeding."
            ),
            "ASSESS": (
                "Using the read-only tools available for this workspace, retrieve: "
                "the vendor's profile (are they approved?), the department's remaining budget, "
                "any existing contracts with this vendor, and prior purchases this quarter. "
                "Look up the vendor record, the budget balance, and any active contracts."
            ),
            "COMPUTE": (
                "Calculate: total purchase order value (unit price times quantity, plus tax and shipping), "
                "budget impact (percentage of budget remaining after this purchase), "
                "and 3-year total cost of ownership if this is a multi-year commitment."
            ),
            "POLICY_CHECK": (
                "Verify: the vendor is on the approved list, the amount is within the requester's "
                "purchase authority, the budget is available, and there are no conflict-of-interest flags."
            ),
            "APPROVAL_GATE": (
                "Purchase authority thresholds: under $5,000 requires manager approval; "
                "$5,000 to $50,000 requires VP approval; above $50,000 requires CFO approval. "
                "Present: vendor name, line items, computed total, budget impact, and policy status."
            ),
            "MUTATE": (
                "Approved. Using the write tools available for this workspace, execute: "
                "create the purchase order in the system, commit the budget, "
                "send the PO to the vendor, and create a tracking ticket."
            ),
            "SCHEDULE_NOTIFY": (
                "Notify the requester of the PO number. "
                "Set a delivery reminder. "
                "Alert the finance team of the budget commitment."
            ),
            "COMPLETE": (
                "Purchase order created. Output: PO number, vendor name, amount, "
                "expected delivery date, and remaining budget."
            ),
        },
    },

    # ── HR PROCESSES ───────────────────────────────────────────────────────

    "hr_offboarding": {
        "hitl_required": False,
        "risk_level": "high",
        "connector_hints": ["hr", "okta", "jira", "slack", "github", "email"],
        "state_instructions": {
            "DECOMPOSE": (
                "Identify: employee name, employee ID, last day of work, "
                "department, manager, equipment assigned, "
                "systems with active access, and any ongoing projects."
            ),
            "ASSESS": (
                "Using the read-only tools available for this workspace, retrieve: "
                "the full list of system access (SSO, code repositories, project management, "
                "messaging platforms, cloud infrastructure), equipment checklist, "
                "pending paid time off balance, and open tasks or projects assigned to this employee. "
                "Look up the employee's access records and asset inventory."
            ),
            "POLICY_CHECK": (
                "Verify access revocation timing policy: "
                "for terminations access must be revoked immediately; "
                "for voluntary resignations access expires on the last working day. "
                "Confirm the equipment return policy and that an IP and NDA acknowledgment is on file."
            ),
            "MUTATE": (
                "Using the write tools available for this workspace, execute in order: "
                "1. Suspend the primary SSO account, "
                "2. Revoke all individual system access (code repositories, cloud, project tools, messaging), "
                "3. Transfer owned resources to the employee's manager, "
                "4. Process the final PTO payout. "
                "Log each revocation action with a timestamp."
            ),
            "SCHEDULE_NOTIFY": (
                "Send: equipment return instructions to the departing employee, "
                "a handover summary to the manager, "
                "an IT ticket for laptop and hardware retrieval, "
                "and a notification that the HR closure checklist is complete."
            ),
            "COMPLETE": (
                "Offboarding complete. Output: list of access revoked, "
                "equipment return status, final pay details, and handover status."
            ),
        },
    },

    # ── CUSTOMER / SLA PROCESSES ───────────────────────────────────────────

    "sla_breach": {
        "hitl_required": False,
        "risk_level": "high",
        "connector_hints": ["monitoring", "crm", "email", "jira", "pagerduty"],
        "state_instructions": {
            "DECOMPOSE": (
                "Identify: affected service, customer name, breach type "
                "(uptime, response time, or resolution time), "
                "breach start time, and current status."
            ),
            "ASSESS": (
                "Using the read-only tools available for this workspace, retrieve: "
                "the SLA contract terms for this customer, actual uptime and response metrics, "
                "the customer's tier, the credit calculation formula, "
                "and any breach history for this customer this quarter. "
                "Look up the customer account and their SLA agreement."
            ),
            "COMPUTE": (
                "Calculate: total breach duration, credit amount per the SLA contract formula, "
                "and cumulative breach penalties issued this quarter. "
                "Apply the credit formula precisely using the breach duration."
            ),
            "POLICY_CHECK": (
                "Verify: the credit amount is within the auto-approve limit, "
                "there is no active dispute from this customer, "
                "and the customer's account is current on payments."
            ),
            "SCHEDULE_NOTIFY": (
                "Send: a breach acknowledgment to the customer including the credit amount, "
                "an incident report to the account manager, "
                "and an internal alert to the engineering team for root cause analysis."
            ),
            "ESCALATE": (
                "Escalate to the account manager if: "
                "the credit amount exceeds $10,000, the customer is classified as strategic, "
                "or this is the third or more breach this quarter."
            ),
        },
    },

    "customer_onboarding": {
        "hitl_required": False,
        "risk_level": "low",
        "connector_hints": ["crm", "email", "billing", "provisioning"],
        "state_instructions": {
            "DECOMPOSE": (
                "Identify: customer name, plan selected, billing contact, "
                "technical contact, required integrations, and target go-live date."
            ),
            "ASSESS": (
                "Using the read-only tools available for this workspace, retrieve: "
                "the customer's account record, the signed contract, the payment method on file, "
                "and the onboarding checklist template for this plan tier. "
                "Look up the account and contract details."
            ),
            "MUTATE": (
                "Using the write tools available for this workspace, execute: "
                "provision the customer account, set the billing plan, "
                "create the welcome email sequence, assign a customer success manager, "
                "and create the onboarding project epic."
            ),
            "SCHEDULE_NOTIFY": (
                "Send: a welcome email with login credentials, "
                "a kickoff meeting invitation, "
                "and schedule 30-day, 60-day, and 90-day check-in reminders."
            ),
            "COMPLETE": (
                "Onboarding initiated. Output: account ID, "
                "customer success manager assigned, kickoff date, and next milestone."
            ),
        },
    },

    "dispute_resolution": {
        "hitl_required": True,
        "risk_level": "medium",
        "connector_hints": ["crm", "billing", "email", "finance"],
        "state_instructions": {
            "DECOMPOSE": (
                "Identify: customer name, disputed amount, affected invoice numbers, "
                "dispute reason, date filed, and any supporting evidence provided."
            ),
            "ASSESS": (
                "Using the read-only tools available for this workspace, retrieve: "
                "the original invoice, the customer's payment history, "
                "service delivery records for the disputed period, contract terms, "
                "and any prior disputes from this customer. "
                "Look up the invoice and customer account records."
            ),
            "POLICY_CHECK": (
                "Assess the claim's validity: is it substantiated by evidence? "
                "Was it filed within the dispute window (typically 60 days)? "
                "What resolution options are permitted under the contract terms?"
            ),
            "APPROVAL_GATE": (
                "Resolution requires approval if the credit amount exceeds $1,000. "
                "Present: claim summary, evidence assessment, "
                "proposed resolution, and financial impact."
            ),
            "MUTATE": (
                "Using the write tools available for this workspace, execute the resolution: "
                "issue a credit memo, adjust the invoice, or decline with a written explanation. "
                "Document the decision with references to supporting evidence."
            ),
            "COMPLETE": (
                "Dispute resolved. Output: outcome (approved, partial, or declined), "
                "credit amount if any, and confirmation that customer notification was sent."
            ),
        },
    },

    "order_management": {
        "hitl_required": False,
        "risk_level": "low",
        "connector_hints": ["erp", "inventory", "shipping", "crm"],
        "state_instructions": {
            "DECOMPOSE": (
                "Identify: order number, customer name, line items, "
                "quantities, pricing, shipping address, "
                "and requested delivery date."
            ),
            "ASSESS": (
                "Using the read-only tools available for this workspace, retrieve: "
                "inventory levels for each line item, current pricing from the price book, "
                "the customer's credit status, and any backorder alerts. "
                "Look up inventory records and the customer account."
            ),
            "COMPUTE": (
                "Calculate: order total (unit price times quantity for each line), "
                "shipping cost based on weight and destination zone, "
                "tax by jurisdiction, and any applicable discount "
                "(volume discount or contract pricing)."
            ),
            "APPROVAL_GATE": (
                "Approval required if: order total exceeds $10,000, "
                "the customer is on a credit hold, or any items are on allocation. "
                "Present the full order summary with computed totals."
            ),
            "MUTATE": (
                "Order confirmed. Using the write tools available for this workspace, execute: "
                "reserve the inventory, create the fulfillment request, "
                "charge the payment method, and generate the order confirmation."
            ),
            "COMPLETE": (
                "Order placed. Output: order number, "
                "items reserved, estimated ship date, and total amount charged."
            ),
        },
    },

    "compliance_audit": {
        "hitl_required": True,
        "risk_level": "high",
        "connector_hints": ["grc", "audit", "finance", "hr", "security"],
        "state_instructions": {
            "DECOMPOSE": (
                "Identify: audit scope (SOX, GDPR, PCI, ISO, or other), "
                "audit period, entities in scope, "
                "auditor type (internal or external), and key controls to test."
            ),
            "ASSESS": (
                "Using the read-only tools available for this workspace, retrieve: "
                "control documentation, prior audit findings, "
                "evidence samples for each control under review, "
                "and open remediation items from the last audit. "
                "Look up each control and its associated evidence records."
            ),
            "COMPUTE": (
                "Score: control effectiveness based on evidence quality, "
                "risk rating for each finding (critical, high, medium, or low), "
                "and calculate the overall compliance score."
            ),
            "POLICY_CHECK": (
                "Flag: any critical or high severity findings, "
                "repeat findings from the prior audit (indicates a systemic issue), "
                "and any controls with no evidence present (automatic fail)."
            ),
            "APPROVAL_GATE": (
                "Audit report requires sign-off before distribution. "
                "Present: findings count by severity, overall compliance score, "
                "and critical items requiring immediate action."
            ),
            "MUTATE": (
                "Using the write tools available for this workspace, finalize: "
                "publish the audit report, create remediation tasks for each finding, "
                "and set remediation deadlines based on severity level."
            ),
            "SCHEDULE_NOTIFY": (
                "Notify: control owners of their specific findings, "
                "management of all critical items, "
                "and schedule a 30-day remediation check-in."
            ),
            "COMPLETE": (
                "Audit complete. Output: findings summary by severity, "
                "compliance score, critical action items, and report location."
            ),
        },
    },

    "incident_response": {
        "hitl_required": True,
        "risk_level": "high",
        "connector_hints": ["pagerduty", "jira", "slack", "monitoring", "aws"],
        "state_instructions": {
            "DECOMPOSE": (
                "Identify: severity level (P1, P2, or P3), affected systems and services, "
                "impacted customers, symptom description, "
                "first reported time, and current status."
            ),
            "ASSESS": (
                "Using the read-only tools available for this workspace, retrieve: "
                "system health metrics, recent deployments in the affected area, "
                "similar past incidents, the on-call engineer contact, "
                "and the count of affected customers. "
                "Look up monitoring dashboards and the incident history."
            ),
            "COMPUTE": (
                "Calculate: total customer impact (number affected multiplied by SLA tier weight), "
                "estimated revenue at risk per hour of downtime, "
                "and SLA credit exposure if a breach occurs."
            ),
            "APPROVAL_GATE": (
                "P1 incidents require VP of Engineering approval of the communications plan. "
                "Present: impact scope, available mitigation options, "
                "and a draft customer communication."
            ),
            "MUTATE": (
                "Using the write tools available for this workspace, execute mitigation: "
                "initiate rollback or hotfix procedures, scale affected resources, "
                "enable circuit breakers as needed. "
                "Update the incident ticket with each action taken and its outcome."
            ),
            "SCHEDULE_NOTIFY": (
                "Send: status page update for affected customers, "
                "direct customer notifications per SLA requirements, "
                "and an internal incident bridge message. "
                "Schedule the post-mortem for the next business day."
            ),
            "COMPLETE": (
                "Incident resolved. Output: root cause, resolution steps taken, "
                "total duration, customer impact summary, "
                "and scheduled post-mortem date."
            ),
        },
    },

    "subscription_migration": {
        "hitl_required": True,
        "risk_level": "high",
        "connector_hints": ["billing", "crm", "email", "provisioning"],
        "state_instructions": {
            "DECOMPOSE": (
                "Identify: customer name, current plan, target plan, "
                "migration date, reason for change (upgrade, downgrade, or cancellation), "
                "and whether billing cycle alignment is needed."
            ),
            "ASSESS": (
                "Using the read-only tools available for this workspace, retrieve: "
                "current subscription details, usage metrics for the current plan, "
                "full billing history, contract terms (including early termination fees), "
                "and the feature differences between current and target plans. "
                "Look up the subscription record and contract."
            ),
            "COMPUTE": (
                "Calculate: prorated credit for remaining days on the current plan, "
                "new plan cost going forward, early termination fee if applicable, "
                "and the net charge or refund at time of migration."
            ),
            "POLICY_CHECK": (
                "Verify: the customer is eligible for the target plan, "
                "there is no outstanding balance on the account, "
                "and whether the downgrade requires data deletion or data migration."
            ),
            "APPROVAL_GATE": (
                "For data-destructive downgrades, a 5-step explicit confirmation is required: "
                "1. Customer confirms the plan change, "
                "2. Customer confirms awareness of feature loss, "
                "3. Customer confirms the scope of data deletion, "
                "4. Customer confirms the billing change amount, "
                "5. Customer gives final irreversible execution confirmation."
            ),
            "MUTATE": (
                "All confirmations received. Using the write tools available for this workspace, execute: "
                "update the subscription record, apply the proration credit, "
                "process the charge or refund for the delta, "
                "and provision or deprovision features as required."
            ),
            "COMPLETE": (
                "Migration complete. Output: new plan name, "
                "billing change amount, effective date, and list of features changed."
            ),
        },
    },

    # ── FALLBACK ───────────────────────────────────────────────────────────

    "general": {
        "hitl_required": False,
        "risk_level": "low",
        "connector_hints": [],
        "state_instructions": {
            "DECOMPOSE": (
                "Break the task into sub-tasks. Identify all entities, "
                "IDs, amounts, and parties involved. "
                "List what data you need to collect before taking any action."
            ),
            "ASSESS": (
                "Using the read-only tools available for this workspace, collect all required data. "
                "Do NOT take any write actions yet. "
                "Retrieve records, check statuses, and look up documents."
            ),
            "COMPUTE": (
                "Run any required calculations using the data already collected. "
                "Do not call additional tools at this stage — work with data already fetched."
            ),
            "POLICY_CHECK": (
                "Verify all rules, thresholds, and constraints "
                "before executing any changes."
            ),
            "APPROVAL_GATE": (
                "Present the proposed actions for approval. "
                "List exactly what will change and the business justification for each change."
            ),
            "MUTATE": (
                "Using the write tools available for this workspace, execute all required changes. "
                "Log each action with its outcome."
            ),
            "SCHEDULE_NOTIFY": (
                "Send all relevant notifications and schedule follow-up actions."
            ),
            "COMPLETE": (
                "Summarize all completed actions and their outcomes."
            ),
        },
    },
}


def get_definition(process_type: str) -> dict:
    """Return the process definition. Falls back to 'general' if not found."""
    return PROCESS_DEFINITIONS.get(process_type, PROCESS_DEFINITIONS["general"])


def get_state_instruction(process_type: str, state: str) -> str:
    """Return the per-state instruction string for a given process."""
    defn = get_definition(process_type)
    return defn.get("state_instructions", {}).get(state, "")


def get_connector_hints(process_type: str) -> list[str]:
    """Tool name prefixes relevant to this process type."""
    return get_definition(process_type).get("connector_hints", [])


def is_hitl_required(process_type: str) -> bool:
    return get_definition(process_type).get("hitl_required", False)


def get_risk_level(process_type: str) -> str:
    return get_definition(process_type).get("risk_level", "low")
