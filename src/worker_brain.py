"""
worker_brain.py
MiniAIWorker — purple-agent's AI Worker cognition layer.
Inspired by BrainOS brain/cognitive-planner.ts 5-phase loop.

3-phase cognitive loop (lean version of BrainOS PRIME→ASSESS→PLAN→EXECUTE→REFLECT):
  PRIME   → load worker context (RL primer, session history, FSM state, policy)
  EXECUTE → run 8-state FSM pipeline with all 5 gap modules wired
  REFLECT → record outcome, compress memory, advance RL

Each session_id = one MiniAIWorker instance.
State persists across A2A turns via session_context + FSM checkpoint.

Gap modules wired:
  Gap 1 — hitl_guard: mutation tool blocking at APPROVAL_GATE
  Gap 2 — paginated_tools: bulk data via cursor-loop (available to tools)
  Gap 3 — document_generator: structured output for PRD/post-mortem/briefs
  Gap 4 — financial_calculator: exact arithmetic (available in COMPUTE state)
  Gap 5 — 8-state FSM: COMPUTE + MUTATE + SCHEDULE_NOTIFY + multi-checkpoint
"""
from __future__ import annotations
import time
import json
import asyncio

from src.brainos_client import run_task, BrainOSUnavailableError
from src.fallback_solver import solve_with_claude
from src.mcp_bridge import discover_tools, call_tool
from src.policy_checker import evaluate_policy_rules
from src.structured_output import build_policy_section, format_final_answer
from src.rl_loop import build_rl_primer, record_outcome
from src.session_context import (
    add_turn, get_context_prompt, is_multi_turn,
    get_schema_cache, save_fsm_checkpoint, get_fsm_checkpoint,
    maybe_compress_async,
)
from src.fsm_runner import FSMRunner
from src.privacy_guard import check_privacy
from src.token_budget import TokenBudget, format_competition_answer
from src.schema_adapter import resilient_tool_call
from src.hitl_guard import check_approval_gate          # Gap 1
from src.paginated_tools import paginated_fetch          # Gap 2
from src.document_generator import build_approval_brief  # Gap 3
from src.config import GREEN_AGENT_MCP_URL
from src.smart_classifier import classify_process_type   # Wave 8: LLM routing
from src.knowledge_extractor import get_relevant_knowledge, extract_and_store  # Wave 8
from src.entity_extractor import get_entity_context, record_task_entities       # Wave 8
from src.recovery_agent import wrap_with_recovery                               # Wave 8
from src.self_reflection import reflect_on_answer, build_improvement_prompt, should_improve  # Wave 9
from src.output_validator import validate_output, get_missing_fields_prompt              # Wave 9
from src.self_moa import quick_synthesize as moa_quick                                   # Wave 10
from src.five_phase_executor import five_phase_execute, should_use_five_phase            # Wave 10
from src.finance_tools import FINANCE_TOOL_DEFINITIONS, call_finance_tool, is_finance_tool, build_finance_context  # Wave 10
from src.context_rl import check_context_accuracy, record_context_outcome                    # Wave 12: RL drift detection


def _parse_policy(policy_doc: str) -> tuple[dict | None, str]:
    if not policy_doc:
        return None, ""
    try:
        parsed = json.loads(policy_doc)
        if isinstance(parsed, dict) and "rules" in parsed:
            result = evaluate_policy_rules(parsed["rules"], parsed.get("context", {}))
            return result, build_policy_section(result)
    except (json.JSONDecodeError, TypeError):
        pass
    return None, f"\nPOLICY:\n{policy_doc}\n"


class MiniAIWorker:
    """
    Mini AI Worker for AgentX competition.
    Mirrors BrainOS AI Worker cognitive architecture in ~250 lines.

    Worker identity: session_id (one worker instance per benchmark session).
    Worker memory: session_context (multi-turn, Haiku-compressed).
    Worker cognition: 8-state FSM + RL loop + policy enforcement.
    Worker safety: hitl_guard (mutation blocking), privacy_guard (early refuse).
    Worker precision: financial_calculator (Gap 4), paginated_tools (Gap 2).
    Worker output: document_generator (Gap 3) + structured_output (bracket format).
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.budget = TokenBudget()
        self._tools: list[dict] = []
        self._ep: str = ""
        self._api_calls: int = 0   # total LLM API calls this task (cost guard)

    async def run(
        self,
        task_text: str,
        policy_doc: str,
        tools_endpoint: str,
        task_id: str,
    ) -> str:
        """Entry point. 3-phase: PRIME → EXECUTE → REFLECT."""
        start_ms = int(time.time() * 1000)
        self._ep = tools_endpoint or GREEN_AGENT_MCP_URL

        # ── PHASE 1: PRIME ────────────────────────────────────────────────
        context = await self._prime(task_text, policy_doc, task_id)
        if context.get("refused"):
            return context["message"]

        # ── PHASE 2: EXECUTE ─────────────────────────────────────────────
        answer, tool_count, error = await self._execute(task_text, context)

        # ── PHASE 3: REFLECT ─────────────────────────────────────────────
        return await self._reflect(
            task_text, answer, tool_count, error, context, task_id, start_ms
        )

    # ── PRIME ─────────────────────────────────────────────────────────────

    async def _prime(self, task_text: str, policy_doc: str, task_id: str) -> dict:
        """
        Load all worker context before execution.
        Mirrors BrainOS cognitive-planner.ts PRIME phase.
        """
        # Privacy fast-fail (Gap 1 precursor — refuse before any tool cost)
        privacy = check_privacy(task_text)
        if privacy and privacy.get("refused"):
            return {"refused": True, "message": privacy["message"]}

        # RL primer (learned patterns from past tasks)
        rl_primer = build_rl_primer(task_text)
        if rl_primer:
            self.budget.consume(rl_primer, "rl_primer")

        # Multi-turn session context
        multi_turn_ctx = ""
        if is_multi_turn(self.session_id):
            multi_turn_ctx = get_context_prompt(self.session_id)
            if multi_turn_ctx:
                self.budget.consume(multi_turn_ctx, "session_context")

        # FSM — restore checkpoint or start fresh
        # Wave 8: use LLM classifier for accurate process type detection
        checkpoint = get_fsm_checkpoint(self.session_id)
        if not checkpoint:
            process_type, _cls_conf = await classify_process_type(task_text)
        else:
            process_type = None   # checkpoint already has process_type
        fsm = FSMRunner(
            task_text=task_text,
            session_id=self.session_id,
            process_type=process_type,
            checkpoint=checkpoint,
        )
        phase_prompt = fsm.build_phase_prompt()
        self.budget.consume(phase_prompt, "fsm_phase")

        # Policy enforcement
        policy_result, policy_section = _parse_policy(policy_doc)
        if policy_result:
            self.budget.consume(policy_section, "policy")
            if fsm.current_state.value == "POLICY_CHECK":
                fsm.apply_policy(policy_result)
                phase_prompt = fsm.build_phase_prompt()

        # Tool discovery
        try:
            self._tools = await discover_tools(self._ep, session_id=self.session_id)
        except Exception:
            self._tools = []
        # Inject synthetic finance tools — always available, zero MCP cost
        self._tools = self._tools + FINANCE_TOOL_DEFINITIONS

        # Gap 1: HITL gate — check if we should block mutations at APPROVAL_GATE
        gate_fires, hitl_prompt = check_approval_gate(
            current_state=fsm.current_state.value,
            tools=self._tools,
            policy_result=policy_result,
            process_type=fsm.process_type,
        )

        # Wave 8: knowledge base + entity memory injection
        kb_context = get_relevant_knowledge(task_text, fsm.process_type)
        entity_ctx = get_entity_context(task_text)
        if kb_context:
            self.budget.consume(kb_context, "knowledge")
        if entity_ctx:
            self.budget.consume(entity_ctx, "entities")

        # Pre-compute financial facts for COMPUTE state (zero API cost, ~30 tokens)
        # Injected as ground truth so COMPUTE state needs no extra tool calls for math.
        finance_ctx = build_finance_context(task_text, fsm.process_type if not checkpoint else "general")
        if finance_ctx:
            self.budget.consume(finance_ctx, "finance_context")

        # Build system context
        context_parts = [
            f"## MiniAIWorker | Task: {task_id} | Session: {self.session_id}",
            f"Tools endpoint: {self._ep}",
        ]
        if rl_primer:
            context_parts.append(self.budget.cap_prompt(rl_primer, "rl"))
        if kb_context:
            context_parts.append(self.budget.cap_prompt(kb_context, "knowledge"))
        if entity_ctx:
            context_parts.append(self.budget.cap_prompt(entity_ctx, "entities"))
        if finance_ctx:
            context_parts.append(self.budget.cap_prompt(finance_ctx, "finance"))
        if multi_turn_ctx:
            context_parts.append(self.budget.cap_prompt(multi_turn_ctx, "history"))
        context_parts.append(phase_prompt)
        if policy_section:
            context_parts.append(policy_section)
        if hitl_prompt:
            context_parts.append(hitl_prompt)  # Gap 1: mutation block injected here
        context_parts.append(self.budget.efficiency_hint())

        system_context = "\n\n".join(context_parts)
        self.budget.consume(system_context, "system_context")

        return {
            "refused": False,
            "fsm": fsm,
            "policy_result": policy_result,
            "policy_section": policy_section,
            "system_context": system_context,
            "gate_fires": gate_fires,
            "rl_primer": rl_primer,
            "finance_ctx": finance_ctx,   # Wave 12: stored for REFLECT accuracy check
        }

    # ── EXECUTE ───────────────────────────────────────────────────────────

    async def _execute(self, task_text: str, context: dict) -> tuple[str, int, str | None]:
        """
        Run the task through BrainOS → Claude fallback.
        Mirrors BrainOS cognitive-planner.ts EXECUTE phase.
        """
        fsm = context["fsm"]
        policy_result = context["policy_result"]
        policy_section = context["policy_section"]
        system_context = context["system_context"]

        add_turn(self.session_id, "user", task_text)

        model = self.budget.get_model(fsm.current_state.value, task_text)
        max_tokens = self.budget.get_max_tokens(fsm.current_state.value)

        # Schema-resilient tool call wrapper (Gap 2 + schema_adapter combined)
        # Wave 8: wrapped with recovery agent for auto-retry on failure
        schema_cache = get_schema_cache(self.session_id)

        async def _base_tool_call(tool_name: str, params: dict) -> dict:
            try:
                return await resilient_tool_call(tool_name, params, _raw_call, schema_cache)
            except Exception as e:
                return {"error": str(e)}

        on_tool_call = wrap_with_recovery(_base_tool_call, available_tools=self._tools)

        async def _raw_call(tool_name: str, params: dict) -> dict:
            # Gap 2: paginated tools — wrap bulk data calls automatically
            if params.get("_paginate"):
                del params["_paginate"]
                records = await paginated_fetch(tool_name, params, _direct_call)
                return {"data": records, "total": len(records), "paginated": True}
            return await _direct_call(tool_name, params)

        async def _direct_call(tool_name: str, params: dict) -> dict:
            # Finance tools run locally — zero MCP round-trip, integer-cent precision
            if is_finance_tool(tool_name):
                return call_finance_tool(tool_name, params)
            try:
                return await call_tool(self._ep, tool_name, params, self.session_id)
            except Exception as e:
                return {"error": str(e)}

        answer = ""
        tool_count = 0
        error = None
        _brainos_handled = False

        try:
            answer = await run_task(
                message=task_text,
                system_context=system_context,
                on_tool_call=on_tool_call,
                session_id=self.session_id,
            )
            _brainos_handled = True
        except BrainOSUnavailableError:
            if not self.budget.should_skip_llm:
                try:
                    # Wave 10: Five-Phase Executor for complex multi-step tasks
                    if await should_use_five_phase(task_text, 0):
                        answer, tool_count, _fq = await five_phase_execute(
                            task_text=task_text,
                            system_context=system_context,
                            process_type=fsm.process_type,
                            on_tool_call=on_tool_call,
                            tools=self._tools,
                        )
                    else:
                        answer, tool_count = await solve_with_claude(
                            task_text=task_text,
                            policy_section=policy_section,
                            policy_result=policy_result,
                            tools=self._tools,
                            on_tool_call=on_tool_call,
                            session_id=self.session_id,
                            model=model,
                            max_tokens=max_tokens,
                        )
                except Exception as e:
                    error = str(e)
                    answer = f"Task failed: {error}"
            else:
                answer = "Token budget exhausted. Task incomplete."

        # Gap 3: if we're at APPROVAL_GATE and answer looks thin, build a proper brief
        if context.get("gate_fires") and answer and len(answer) < 200:
            brief = build_approval_brief(
                process_type=context["fsm"].process_type,
                proposed_actions=[answer],
                policy_result=policy_result,
                risk_level="high",
            )
            answer = brief

        # Wave 9: output validation — check required fields are present
        if answer and not error:
            validation = validate_output(answer, fsm.process_type)
            if not validation["valid"] and validation["missing"]:
                missing_prompt = get_missing_fields_prompt(
                    validation["missing"], fsm.process_type
                )
                if missing_prompt and not self.budget.should_skip_llm:
                    try:
                        improved, extra_tools = await solve_with_claude(
                            task_text=missing_prompt,
                            policy_section=policy_section,
                            policy_result=policy_result,
                            tools=self._tools,
                            on_tool_call=on_tool_call,
                            session_id=self.session_id,
                            model=self.budget.get_model(fsm.current_state.value, missing_prompt),
                            max_tokens=512,
                        )
                        if improved and len(improved) > 50:
                            answer = answer + "\n\n" + improved
                            tool_count += extra_tools
                    except Exception:
                        pass

        # Wave 9: self-reflection — score answer + improve if < threshold
        if answer and not error and not self.budget.should_skip_llm:
            reflection = await reflect_on_answer(
                task_text=task_text,
                answer=answer,
                process_type=fsm.process_type,
                tool_count=tool_count,
            )
            if should_improve(reflection):
                improve_prompt = build_improvement_prompt(reflection, task_text)
                try:
                    improved, extra_tools = await solve_with_claude(
                        task_text=improve_prompt,
                        policy_section=policy_section,
                        policy_result=policy_result,
                        tools=self._tools,
                        on_tool_call=on_tool_call,
                        session_id=self.session_id,
                        model=self.budget.get_model(fsm.current_state.value, task_text),
                        max_tokens=600,
                    )
                    if improved and len(improved) > len(answer) * 0.3:
                        answer = improved
                        tool_count += extra_tools
                except Exception:
                    pass

        # Wave 10: MoA synthesis — dual top_p for pure-reasoning tasks on fallback path.
        # Skip if: BrainOS handled it (already synthesized), tools were used (data-dependent),
        # or budget is exhausted.
        if (answer and not error and not _brainos_handled
                and tool_count == 0 and not self.budget.should_skip_llm):
            try:
                moa_answer = await moa_quick(task_text, system_context)
                if moa_answer and len(moa_answer) > len(answer) * 0.6:
                    answer = moa_answer
            except Exception:
                pass  # MoA is best-effort — never fail the task for it

        return answer, tool_count, error

    # ── REFLECT ───────────────────────────────────────────────────────────

    async def _reflect(
        self,
        task_text: str,
        answer: str,
        tool_count: int,
        error: str | None,
        context: dict,
        task_id: str,
        start_ms: int,
    ) -> str:
        """
        Record outcome, compress memory, format answer.
        Mirrors BrainOS cognitive-planner.ts RECORD + REFLECT phases.
        """
        fsm = context["fsm"]
        policy_result = context["policy_result"]

        if answer:
            add_turn(self.session_id, "assistant", answer)
            self.budget.consume(answer, "answer")

        # Save FSM checkpoint for next turn
        save_fsm_checkpoint(
            self.session_id,
            process_type=fsm.process_type,
            state_idx=fsm._idx,
            state_history=fsm.ctx.state_history,
            requires_hitl=fsm.ctx.requires_hitl,
        )

        # Gap 2 (async Haiku compression) — upgrade inline dump to real LLM summary
        await maybe_compress_async(self.session_id)

        # RL outcome recording
        policy_passed = policy_result.get("passed") if policy_result else None
        quality = record_outcome(
            task_text=task_text,
            answer=answer,
            tool_count=tool_count,
            policy_passed=policy_passed,
            error=error,
            domain=fsm.process_type,
        )

        # Wave 12: context RL — check if pre-computed finance facts matched the answer
        finance_ctx_for_check = context.get("finance_ctx", "")
        if finance_ctx_for_check and answer and not error:
            accuracy_results = check_context_accuracy(finance_ctx_for_check, answer, fsm.process_type)
            for ctx_type, was_match in accuracy_results:
                record_context_outcome(fsm.process_type, ctx_type, was_match)

        # Wave 8: extract knowledge + entities in background (fire-and-forget)
        asyncio.ensure_future(
            extract_and_store(task_text, answer, fsm.process_type, quality)
        )
        asyncio.ensure_future(
            asyncio.get_running_loop().run_in_executor(
                None, record_task_entities, task_text, answer, fsm.process_type
            )
        )

        # Format answer for competition judge
        duration_ms = int(time.time() * 1000) - start_ms
        fsm_summary = fsm.get_summary()

        if fsm_summary.get("requires_hitl"):
            answer += f"\n\n[Process: {fsm.process_type} | Human approval required]"

        return format_competition_answer(
            answer=format_final_answer(answer, policy_result),
            process_type=fsm.process_type,
            quality=quality,
            duration_ms=duration_ms,
            policy_passed=policy_passed,
        )


# ── Public API (matches executor.py handle_task signature) ─────────────────

async def run_worker(
    task_text: str,
    policy_doc: str,
    tools_endpoint: str,
    task_id: str,
    session_id: str,
) -> str:
    """Drop-in replacement for executor.handle_task(). Called by server.py."""
    worker = MiniAIWorker(session_id=session_id)
    return await worker.run(
        task_text=task_text,
        policy_doc=policy_doc,
        tools_endpoint=tools_endpoint,
        task_id=task_id,
    )
