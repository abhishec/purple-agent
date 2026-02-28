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
                "Flag if any info is missing — ask before proceeding."
            ),
            "ASSESS": (
                "Fetch: requester's remaining expense budget, their approval limit, "
                "department policy doc, and any prior reimbursements this period. "
                "Use read-only tools: get_employee_profile, get_budget_balance, list_expenses."
            ),
            "COMPUTE": (
                "Calculate: total claim amount (itemized), tax-deductible portion, "
                "policy threshold comparison (is amount within limit?), "
                "and year-to-date spend for this requester."
            ),
            "POLICY_CHECK": (
                "Verify: amount ≤ requester's single-transaction limit, "
                "category is in approved list, receipt attached if required, "
                "submission within 30-day window. Flag any violation."
            ),
            "APPROVAL_GATE": (
                "Approval required. Present: requester, amount, category, "
                "policy compliance status, computed totals. "
                "If >$500: manager approval. If >$5,000: VP approval. "
                "Do NOT call create/update tools — wait for approval."
            ),
            "MUTATE": (
                "Approval received. Execute: create expense record, mark as approved, "
                "update budget allocation, initiate reimbursement. "
                "Log each action."
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
                "Fetch: matching PO, goods receipt record, vendor payment terms, "
                "any prior invoices from this vendor. "
                "Use: get_purchase_order, get_goods_receipt, get_vendor_terms."
            ),
            "COMPUTE": (
                "Calculate: invoice-PO variance (must be <2% or <$500 per policy), "
                "early payment discount if applicable, "
                "late payment penalty if past due. "
                "Use apply_variance_check() — 6-decimal precision for boundary cases."
            ),
            "POLICY_CHECK": (
                "Verify: 3-way match (invoice ↔ PO ↔ receipt), "
                "amount variance within tolerance, "
                "vendor is approved, payment terms match contract."
            ),
            "MUTATE": (
                "3-way match passed. Execute: approve invoice, "
                "schedule payment per terms, update AP ledger."
            ),
            "COMPLETE": (
                "Summarize: invoice approved/rejected, payment date, "
                "variance amount if any, AP balance impact."
            ),
        },
    },

    "month_end_close": {
        "hitl_required": True,
        "risk_level": "high",
        "connector_hints": ["accounting", "erp", "finance", "ledger"],
        "state_instructions": {
            "DECOMPOSE": (
                "Identify: close period (month/year), entities in scope, "
                "checklist items: accruals, reconciliations, journal entries, "
                "intercompany eliminations."
            ),
            "ASSESS": (
                "Fetch: all open items per close checklist — "
                "unapproved journals, unreconciled accounts, "
                "pending accruals, intercompany imbalances."
            ),
            "COMPUTE": (
                "Calculate: P&L by department, balance sheet movements, "
                "tax provision estimates, revenue recognition adjustments. "
                "Straight-line depreciation for any new assets this period."
            ),
            "POLICY_CHECK": (
                "Verify: all reconciliations signed off, no unexplained variances >$1K, "
                "management review complete, audit trail present for all adjustments."
            ),
            "APPROVAL_GATE": (
                "CFO sign-off required before period lock. "
                "Present: P&L summary, balance sheet, open items count, "
                "material variances requiring explanation."
            ),
            "MUTATE": (
                "CFO approved. Execute: lock accounting period, "
                "post final journal entries, generate trial balance."
            ),
            "COMPLETE": (
                "Period closed. Output: final trial balance hash, "
                "close timestamp, approver, open items deferred to next period."
            ),
        },
    },

    "ar_collections": {
        "hitl_required": False,
        "risk_level": "medium",
        "connector_hints": ["crm", "email", "finance", "billing"],
        "state_instructions": {
            "DECOMPOSE": (
                "Identify: customer, overdue amount, aging bucket (30/60/90+), "
                "invoice numbers, last payment date, and assigned collector."
            ),
            "ASSESS": (
                "Fetch: full payment history, credit limit, current balance, "
                "open disputes, contact info for billing contact. "
                "Use: get_customer_account, get_payment_history, list_open_invoices."
            ),
            "COMPUTE": (
                "Calculate: total overdue by aging bucket, "
                "interest/late fees per contract terms, "
                "collectability score (days overdue × invoice count)."
            ),
            "POLICY_CHECK": (
                "Determine collection action by aging: "
                "30-day: courtesy reminder, 60-day: formal notice, "
                "90-day+: escalate to collections agency or legal."
            ),
            "MUTATE": (
                "Send appropriate communication per policy tier. "
                "If payment plan agreed: create installment schedule. "
                "If write-off: create bad debt record."
            ),
            "SCHEDULE_NOTIFY": (
                "Schedule: next follow-up reminder, "
                "payment plan due date alerts, "
                "escalation trigger if no response in 5 days."
            ),
            "COMPLETE": (
                "Summarize: action taken, amounts outstanding, "
                "next follow-up date, predicted resolution."
            ),
        },
    },

    "payroll": {
        "hitl_required": True,
        "risk_level": "high",
        "connector_hints": ["hr", "payroll", "finance", "bank"],
        "state_instructions": {
            "DECOMPOSE": (
                "Identify: pay period, employee list, pay types "
                "(regular, overtime, commission, bonus), "
                "any off-cycle adjustments this period."
            ),
            "ASSESS": (
                "Fetch: hours worked per employee, approved overtime, "
                "tax withholding settings, benefit deductions, "
                "garnishments, and YTD figures."
            ),
            "COMPUTE": (
                "Calculate gross pay (hours × rate + OT at 1.5x), "
                "all statutory deductions (federal/state tax, FICA), "
                "voluntary deductions (401k, health), net pay. "
                "Use amortize_loan() for any pay advances."
            ),
            "POLICY_CHECK": (
                "Verify: total payroll within approved budget, "
                "no duplicate entries, all garnishments applied, "
                "OT approved by manager for each employee."
            ),
            "APPROVAL_GATE": (
                "Payroll director approval required. "
                "Present: total gross, total deductions, total net, "
                "headcount, any anomalies vs prior period."
            ),
            "MUTATE": (
                "Approved. Execute: submit payroll file to bank (ACH/BACS), "
                "update YTD accumulators, record payroll journal entry."
            ),
            "SCHEDULE_NOTIFY": (
                "Notify employees of pay stubs available. "
                "Send payroll summary to finance. "
                "Schedule next pay run."
            ),
            "COMPLETE": (
                "Payroll run complete. Output: total disbursed, "
                "headcount paid, next run date."
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
                "Identify: item/service requested, quantity, estimated cost, "
                "department, requester, budget code, and business justification. "
                "Ask if any field is missing."
            ),
            "ASSESS": (
                "Fetch: vendor profile (approved?), budget remaining for department, "
                "existing contracts with this vendor, prior purchases this quarter. "
                "Use: get_vendor, get_budget_balance, list_contracts."
            ),
            "COMPUTE": (
                "Calculate: total PO value (unit × qty + tax + shipping), "
                "budget impact (% remaining after this PO), "
                "3-year TCO if it's a multi-year commitment."
            ),
            "POLICY_CHECK": (
                "Verify: vendor on approved list, amount within requester's PO authority, "
                "budget available, no conflict of interest flags."
            ),
            "APPROVAL_GATE": (
                "<$5K: manager. $5K-$50K: VP. >$50K: CFO. "
                "Present: vendor, line items, computed total, budget impact, policy status."
            ),
            "MUTATE": (
                "Approved. Create PO in system, commit budget, "
                "send PO to vendor, create Jira ticket for tracking."
            ),
            "SCHEDULE_NOTIFY": (
                "Notify requester of PO number. "
                "Set delivery reminder. "
                "Alert finance of budget commitment."
            ),
            "COMPLETE": (
                "PO created. Output: PO number, vendor, amount, "
                "expected delivery, budget remaining."
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
                "Identify: employee name, ID, last day, "
                "department, manager, equipment assigned, "
                "systems with access, and any ongoing projects."
            ),
            "ASSESS": (
                "Fetch: full access list (SSO, GitHub, Slack, Jira, AWS), "
                "equipment checklist, pending PTO balance, "
                "open projects/tasks assigned to this employee."
            ),
            "POLICY_CHECK": (
                "Verify: access revocation timing (immediate for termination, "
                "on last day for resignation), "
                "equipment return policy, "
                "IP/NDA acknowledgment on file."
            ),
            "MUTATE": (
                "Execute in order: "
                "1. Suspend SSO/Okta account, "
                "2. Revoke all system access (GitHub, AWS, Jira, Slack), "
                "3. Transfer owned resources to manager, "
                "4. Process final PTO payout. "
                "Log each revocation with timestamp."
            ),
            "SCHEDULE_NOTIFY": (
                "Send: equipment return instructions to employee, "
                "handover summary to manager, "
                "IT ticket for laptop retrieval, "
                "HR closure checklist completed notification."
            ),
            "COMPLETE": (
                "Offboarding complete. Output: access revoked (list), "
                "equipment status, final pay details, handover status."
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
                "Identify: affected service, customer, breach type "
                "(uptime/response time/resolution time), "
                "breach start time, current status."
            ),
            "ASSESS": (
                "Fetch: SLA contract terms, actual uptime/response metrics, "
                "customer tier, credit formula, "
                "breach history for this customer."
            ),
            "COMPUTE": (
                "Calculate: breach duration, credit amount per SLA formula, "
                "cumulative breach penalties this quarter. "
                "Use compute_sla_credit() for exact credit amount."
            ),
            "POLICY_CHECK": (
                "Verify: credit amount within auto-approve limit, "
                "no active dispute, customer is current on payments."
            ),
            "SCHEDULE_NOTIFY": (
                "Send: breach acknowledgment to customer with credit amount, "
                "incident report to account manager, "
                "internal alert to engineering for RCA."
            ),
            "ESCALATE": (
                "Escalate to account manager if: "
                "credit >$10K, customer is strategic, "
                "or this is the 3rd breach this quarter."
            ),
        },
    },

    "customer_onboarding": {
        "hitl_required": False,
        "risk_level": "low",
        "connector_hints": ["crm", "email", "billing", "provisioning"],
        "state_instructions": {
            "DECOMPOSE": (
                "Identify: customer name, plan, billing contact, "
                "technical contact, required integrations, go-live date."
            ),
            "ASSESS": (
                "Fetch: account record, signed contract, payment method, "
                "onboarding checklist template for this plan tier."
            ),
            "MUTATE": (
                "Execute: provision account, set billing plan, "
                "create welcome email sequence, assign CSM, "
                "create onboarding Jira epic."
            ),
            "SCHEDULE_NOTIFY": (
                "Send: welcome email with credentials, "
                "kickoff meeting invite, "
                "30/60/90 day check-in reminders."
            ),
            "COMPLETE": (
                "Onboarding initiated. Output: account ID, "
                "CSM assigned, kickoff date, next milestone."
            ),
        },
    },

    "dispute_resolution": {
        "hitl_required": True,
        "risk_level": "medium",
        "connector_hints": ["crm", "billing", "email", "finance"],
        "state_instructions": {
            "DECOMPOSE": (
                "Identify: customer, disputed amount, invoice(s), "
                "dispute reason, date filed, supporting evidence."
            ),
            "ASSESS": (
                "Fetch: original invoice, payment history, "
                "service delivery records, contract terms, "
                "prior disputes from this customer."
            ),
            "POLICY_CHECK": (
                "Assess validity: is the claim substantiated by evidence? "
                "Is it within the dispute window (typically 60 days)? "
                "What resolution options are allowed per contract?"
            ),
            "APPROVAL_GATE": (
                "Resolution requires approval if credit >$1K. "
                "Present: claim summary, evidence assessment, "
                "proposed resolution, financial impact."
            ),
            "MUTATE": (
                "Execute resolution: issue credit memo, "
                "adjust invoice, or decline with explanation. "
                "Document decision with evidence references."
            ),
            "COMPLETE": (
                "Dispute resolved. Output: outcome (approved/partial/declined), "
                "credit amount if any, customer notification sent."
            ),
        },
    },

    "order_management": {
        "hitl_required": False,
        "risk_level": "low",
        "connector_hints": ["erp", "inventory", "shipping", "crm"],
        "state_instructions": {
            "DECOMPOSE": (
                "Identify: order number, customer, line items, "
                "quantities, pricing, shipping address, "
                "requested delivery date."
            ),
            "ASSESS": (
                "Fetch: inventory levels for each item, "
                "pricing from current price book, "
                "customer credit status, any backorder alerts."
            ),
            "COMPUTE": (
                "Calculate: order total (unit price × qty), "
                "shipping cost (weight/zone), tax by jurisdiction, "
                "discount if applicable (volume or contract)."
            ),
            "APPROVAL_GATE": (
                "Approval required if: order >$10K, "
                "customer on credit hold, or items on allocation. "
                "Present order summary with totals."
            ),
            "MUTATE": (
                "Confirmed. Execute: reserve inventory, "
                "create fulfillment request, charge payment, "
                "generate order confirmation."
            ),
            "COMPLETE": (
                "Order placed. Output: order number, "
                "items reserved, estimated ship date, total charged."
            ),
        },
    },

    "compliance_audit": {
        "hitl_required": True,
        "risk_level": "high",
        "connector_hints": ["grc", "audit", "finance", "hr", "security"],
        "state_instructions": {
            "DECOMPOSE": (
                "Identify: audit scope (SOX/GDPR/PCI/ISO), "
                "audit period, entities in scope, "
                "auditor (internal/external), key controls to test."
            ),
            "ASSESS": (
                "Fetch: control documentation, prior audit findings, "
                "evidence samples for each control, "
                "open remediation items from last audit."
            ),
            "COMPUTE": (
                "Score: control effectiveness per evidence, "
                "risk rating for each finding (critical/high/medium/low), "
                "overall compliance score."
            ),
            "POLICY_CHECK": (
                "Flag: any critical or high findings, "
                "repeat findings from prior audit (indicates systemic issue), "
                "controls with no evidence (automatic fail)."
            ),
            "APPROVAL_GATE": (
                "Audit report requires sign-off before distribution. "
                "Present: findings count by severity, "
                "compliance score, critical items for immediate action."
            ),
            "MUTATE": (
                "Finalize: publish audit report, "
                "create remediation tasks for each finding, "
                "set remediation deadlines per severity."
            ),
            "SCHEDULE_NOTIFY": (
                "Notify: control owners of their findings, "
                "management of critical items, "
                "schedule 30-day remediation check-in."
            ),
            "COMPLETE": (
                "Audit complete. Output: findings summary, "
                "compliance score, critical actions, report location."
            ),
        },
    },

    "incident_response": {
        "hitl_required": True,
        "risk_level": "high",
        "connector_hints": ["pagerduty", "jira", "slack", "monitoring", "aws"],
        "state_instructions": {
            "DECOMPOSE": (
                "Identify: severity (P1/P2/P3), affected systems/services, "
                "impacted customers, symptom description, "
                "first reported time, current status."
            ),
            "ASSESS": (
                "Fetch: system health metrics, recent deployments, "
                "similar past incidents, on-call engineer, "
                "affected customer count."
            ),
            "COMPUTE": (
                "Calculate: customer impact (# affected × SLA tier), "
                "estimated revenue at risk per hour, "
                "SLA credit exposure if breach occurs."
            ),
            "APPROVAL_GATE": (
                "P1 incidents: VP Engineering must approve comms plan. "
                "Present: impact scope, mitigation options, "
                "customer communication draft."
            ),
            "MUTATE": (
                "Execute mitigation: run rollback/hotfix commands, "
                "scale resources, enable circuit breakers. "
                "Update incident ticket with each action."
            ),
            "SCHEDULE_NOTIFY": (
                "Send: status page update, customer notifications, "
                "internal Slack bridge message. "
                "Schedule post-mortem for next business day."
            ),
            "COMPLETE": (
                "Incident resolved. Output: root cause, "
                "resolution steps, duration, customer impact, "
                "post-mortem scheduled date."
            ),
        },
    },

    "subscription_migration": {
        "hitl_required": True,
        "risk_level": "high",
        "connector_hints": ["billing", "crm", "email", "provisioning"],
        "state_instructions": {
            "DECOMPOSE": (
                "Identify: customer, current plan, target plan, "
                "migration date, reason for change (upgrade/downgrade/cancel), "
                "billing cycle alignment needed."
            ),
            "ASSESS": (
                "Fetch: current subscription details, usage metrics, "
                "billing history, contract terms (early termination fees?), "
                "features that will be gained/lost."
            ),
            "COMPUTE": (
                "Calculate: prorated credit for remaining days on current plan, "
                "new plan cost, early termination fee if applicable, "
                "net charge or refund at migration."
            ),
            "POLICY_CHECK": (
                "Verify: customer is eligible for target plan, "
                "no outstanding balance, "
                "data migration required (downgrade may require data deletion)."
            ),
            "APPROVAL_GATE": (
                "5-step confirmation required for data-destructive downgrades: "
                "1. Customer confirms plan change, "
                "2. Customer confirms feature loss, "
                "3. Customer confirms data deletion scope, "
                "4. Customer confirms billing change, "
                "5. Final irreversible execution confirmation."
            ),
            "MUTATE": (
                "All confirmations received. Execute: update subscription, "
                "apply proration credit, charge/refund delta, "
                "provision/deprovision features."
            ),
            "COMPLETE": (
                "Migration complete. Output: new plan name, "
                "billing change, effective date, features changed."
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
                "List what data you need before acting."
            ),
            "ASSESS": (
                "Collect all required data using read-only tools. "
                "Do NOT take actions yet. "
                "Fetch records, check statuses, retrieve documents."
            ),
            "COMPUTE": (
                "Run any required calculations using collected data. "
                "Do not call tools — work with data already fetched."
            ),
            "POLICY_CHECK": (
                "Verify all rules, thresholds, and constraints "
                "before executing any changes."
            ),
            "APPROVAL_GATE": (
                "Present proposed actions for approval. "
                "List exactly what will change and the business justification."
            ),
            "MUTATE": (
                "Execute all required state changes. "
                "Log each action with its outcome."
            ),
            "SCHEDULE_NOTIFY": (
                "Send all relevant notifications and schedule follow-ups."
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
