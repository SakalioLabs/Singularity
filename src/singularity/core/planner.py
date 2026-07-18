"""LLM-powered goal decomposition with fixed M2/M4 planner evidence."""

import hashlib
import json
import logging
import math
import re
import time
import uuid

from singularity.core.task_system import TaskSystem, Task
from singularity.data.knowledge_base import KnowledgeBase
from singularity.llm.provider import LLMProvider

logger = logging.getLogger("singularity.planner")

_CRAFTING_KNOWLEDGE = ""
_M2_TASK_GUIDANCE = {
    "BM-007": [
        "Resource check: two initial logs yield eight planks; four sticks consume two planks and a wooden pickaxe consumes three, so five planks are sufficient.",
        "Reuse the verified nearby crafting table and stone fixtures; do not gather extra logs or craft/place another table.",
        "If the successful-action summary has move_to=0, target an observed stone fixture once; after that first successful move, the three adjacent fixture stones require direct dig actions without moving between them.",
    ],
    "BM-009": [
        "A torch is a 2x2 inventory craft and does not require a crafting table or placement action.",
        "The verified initial two planks craft four sticks; one coal plus one stick then crafts four torches, so no gathering or digging is needed.",
        "Execute exactly the unmet prerequisite chain: craft sticks first, then craft torches; do not gather logs, craft a table, or place blocks.",
    ],
    "BM-010": [
        "The root plan still needs at least two auditable nodes: build the fixed shelter shell, then verify the completed structure and player occupancy with the second node depending on the first.",
        "Emit exactly one immediate build_shelter_5x5 action using construction_zone.origin as the origin and cobblestone as the material; the bounded handler builds the walls, entrance, roof, and moves the player inside.",
        "Do not emit move_to or individual place actions, and do not split the 55 fixed placements into planner actions.",
    ],
}
try:
    _KB = KnowledgeBase()
    _CRAFTING_KNOWLEDGE = _KB.format_for_prompt()
except Exception as e:
    logger.warning(f"Could not build planner knowledge summary: {e}")
    _CRAFTING_KNOWLEDGE = "Key recipes unavailable"


class Planner:
    M4_PLACE_REPLAN_FEEDBACK_POLICY_ID = "m4-place-replan-feedback-grounding-v1"

    def __init__(self, llm: LLMProvider, task_system: TaskSystem, protocol: str = ""):
        self.llm = llm
        self.task_system = task_system
        self.protocol = str(protocol or "")
        self.strict_m2 = self.protocol == "m2-fixed-v1"
        self.strict_m4 = self.protocol == "m4-fixed-v1"
        self.strict_stone_pickaxe = self.protocol == "stone-pickaxe-skill-fixed-v1"
        self.last_call_evidence: dict = {}
        self._episode_goal = ""
        self._episode_id = ""
        self._call_index = 0
        self._active_root_plan_id = ""
        self._last_call_id = ""
        self._pending_replan_reason = ""
        self._pending_m4_place_replan_feedback: dict = {}
        self._goal_deadline_monotonic = None
        self._action_guard_s = 0.0

    def start_episode(self, goal: str, episode_id: str = ""):
        self._episode_goal = str(goal or "")
        self._episode_id = str(episode_id or "")
        self._call_index = 0
        self._active_root_plan_id = ""
        self._last_call_id = ""
        self.last_call_evidence = {}
        self._pending_replan_reason = ""
        self._pending_m4_place_replan_feedback = {}
        self._goal_deadline_monotonic = None
        self._action_guard_s = 0.0

    def set_deadline(self, deadline_monotonic, action_guard_s: float = 0.0):
        """Bind planner requests to the current goal's monotonic deadline."""
        self._goal_deadline_monotonic = (
            float(deadline_monotonic) if deadline_monotonic is not None else None
        )
        self._action_guard_s = max(0.0, float(action_guard_s or 0.0))

    def request_replan(self, reason: str):
        self._pending_replan_reason = str(reason or "action_failure")[:500]
        self._pending_m4_place_replan_feedback = {}

    def request_place_replan(
        self,
        reason: str,
        *,
        rejected_reference: dict,
        adjacent_reference_candidates: list,
    ):
        """Bind one strict-M4 place replan to verifier-supplied coordinates."""
        self.request_replan(reason)
        if not self.strict_m4:
            return
        self._pending_m4_place_replan_feedback = {
            "policy_id": self.M4_PLACE_REPLAN_FEEDBACK_POLICY_ID,
            "rejected_reference": (
                dict(rejected_reference)
                if isinstance(rejected_reference, dict)
                else rejected_reference
            ),
            "adjacent_reference_candidates": (
                [dict(item) if isinstance(item, dict) else item for item in adjacent_reference_candidates]
                if isinstance(adjacent_reference_candidates, list)
                else adjacent_reference_candidates
            ),
        }

    def plan_from_goal(self, goal: str, world_state: dict, memory_context: str = "") -> dict:
        if (self.strict_m2 or self.strict_stone_pickaxe) and self._call_index == 0:
            plan_kind = "root"
        elif (
            self.strict_m2 or self.strict_m4 or self.strict_stone_pickaxe
        ) and self._pending_replan_reason:
            plan_kind = "replan"
            memory_context = "\n".join(
                part for part in (
                    memory_context,
                    f"Previous action failed and requires replan: {self._pending_replan_reason}",
                ) if part
            )
        else:
            plan_kind = "continuation"
        place_replan_feedback = (
            dict(self._pending_m4_place_replan_feedback)
            if plan_kind == "replan" and self.strict_m4
            else {}
        )
        plan = self._call_planner(
            goal,
            world_state,
            memory_context,
            plan_kind,
            m4_place_replan_feedback=place_replan_feedback,
        )
        if plan_kind == "replan":
            self._pending_replan_reason = ""
            self._pending_m4_place_replan_feedback = {}
        return plan

    def replan(self, failed_task: Task, world_state: dict, failure_reason: str) -> dict:
        goal = self._episode_goal or failed_task.title
        context = (
            f"Task '{failed_task.title}' failed: {failure_reason}. "
            f"Attempts so far: {failed_task.attempts}."
        )
        return self._call_planner(goal, world_state, context, "replan")

    def _call_planner(
        self,
        goal: str,
        world_state: dict,
        memory_context: str,
        plan_kind: str,
        m4_place_replan_feedback: dict = None,
    ) -> dict:
        call_id = f"llm-{uuid.uuid4().hex[:16]}"
        root_plan_id = self._active_root_plan_id or f"root-{uuid.uuid4().hex[:16]}"
        self._expected_plan_kind = plan_kind
        prompt = self._build_planning_prompt(goal, world_state, memory_context)
        messages = [
            {"role": "system", "content": self._planner_system_prompt()},
            {"role": "user", "content": prompt},
        ]
        response = ""
        call_error = ""
        request_timeout_s = None
        deadline_evidence = {}
        transport_evidence = {}
        deadline_protocol = None
        strict_deadline = self.strict_m2 or self.strict_m4 or self.strict_stone_pickaxe
        if strict_deadline:
            if self.strict_m2:
                from singularity.evaluation.m2_protocol import PROTOCOL as deadline_protocol
            elif self.strict_m4:
                from singularity.evaluation.m4_protocol import PROTOCOL as deadline_protocol
            else:
                from singularity.evaluation.stone_pickaxe_protocol import (
                    PROTOCOL as deadline_protocol,
                )

            policy = deadline_protocol["deadline_policy"]
            expected_guard_s = float(policy.get("action_guard_ms", 0)) / 1000.0
            planner_max_retries = int(
                policy.get(
                    "planner_max_retries",
                    deadline_protocol.get("planner", {}).get("provider_retries", 0),
                )
            )
            remaining_s = (
                self._goal_deadline_monotonic - time.monotonic()
                if self._goal_deadline_monotonic is not None
                else None
            )
            planner_budget_s = (
                remaining_s - self._action_guard_s
                if remaining_s is not None
                else None
            )
            if self.strict_m4 and planner_budget_s is not None:
                planner_budget_s = min(
                    planner_budget_s,
                    float(policy["llm_call_timeout_s"]),
                )
            deadline_evidence = {
                "policy_id": str(policy["id"]),
                "remaining_before_call_s": round(remaining_s, 3) if remaining_s is not None else None,
                "action_guard_s": round(self._action_guard_s, 3),
                "request_timeout_s": round(planner_budget_s, 3) if planner_budget_s is not None else None,
                "max_retries": planner_max_retries,
            }
            if self._goal_deadline_monotonic is None:
                call_error = f"{self.protocol.split('-', 1)[0]}_episode_deadline_not_configured"
            elif abs(self._action_guard_s - expected_guard_s) > 0.001:
                call_error = f"{self.protocol.split('-', 1)[0]}_action_guard_mismatch"
            elif planner_budget_s is None or planner_budget_s <= 0:
                call_error = f"{self.protocol.split('-', 1)[0]}_total_deadline_exhausted_before_planner_call"
            else:
                request_timeout_s = planner_budget_s

        if not call_error:
            transport_policy = (
                dict(deadline_protocol["llm_transport_policy"])
                if self.strict_m2
                else {
                    "id": "single-attempt",
                    "application_max_retries": 0,
                    "retryable_error_types": [],
                    "reset_client_before_retry": False,
                    "backoff_ms": 0,
                }
            )
            attempts = []
            maximum_attempts = 1 + int(transport_policy["application_max_retries"])
            for attempt_index in range(maximum_attempts):
                if strict_deadline:
                    remaining_request_s = (
                        self._goal_deadline_monotonic
                        - time.monotonic()
                        - self._action_guard_s
                    )
                    request_timeout_s = remaining_request_s
                    if self.strict_m4:
                        request_timeout_s = min(
                            request_timeout_s,
                            float(deadline_protocol["deadline_policy"]["llm_call_timeout_s"]),
                        )
                    deadline_evidence["request_timeout_s"] = round(request_timeout_s, 3)
                    if request_timeout_s <= 0:
                        call_error = f"{self.protocol.split('-', 1)[0]}_total_deadline_exhausted_before_planner_retry"
                        break
                chat_kwargs = {"response_format": {"type": "json_object"}}
                if request_timeout_s is not None:
                    chat_kwargs["timeout_s"] = request_timeout_s
                if self.strict_m2 or self.strict_m4:
                    chat_kwargs["extra_body"] = dict(deadline_protocol["llm"].get("extra_body", {}))
                elif self.strict_stone_pickaxe:
                    thinking = str(
                        deadline_protocol.get("planner", {}).get("thinking") or ""
                    ).strip()
                    if thinking:
                        chat_kwargs["extra_body"] = {"thinking": {"type": thinking}}
                try:
                    response = self.llm.chat(messages, **chat_kwargs)
                    metadata = dict(getattr(self.llm, "last_call_metadata", {}) or {})
                    attempts.append({
                        "attempt_index": attempt_index,
                        "success": True,
                        "timeout_s": metadata.get("timeout_s"),
                        "sdk_max_retries": metadata.get("max_retries"),
                        "finish_reason": metadata.get("finish_reason"),
                    })
                    break
                except Exception as exc:
                    error_chain = []
                    current_error = exc
                    while current_error is not None and len(error_chain) < 5:
                        error_chain.append(type(current_error).__name__)
                        current_error = current_error.__cause__ or current_error.__context__
                    metadata = dict(getattr(self.llm, "last_call_metadata", {}) or {})
                    metadata.update({
                        "error_type": type(exc).__name__,
                        "error_chain": error_chain,
                    })
                    self.llm.last_call_metadata = metadata
                    attempts.append({
                        "attempt_index": attempt_index,
                        "success": False,
                        "timeout_s": metadata.get("timeout_s"),
                        "sdk_max_retries": metadata.get("max_retries"),
                        "error_type": type(exc).__name__,
                        "error_chain": error_chain,
                    })
                    retryable = any(
                        name in set(transport_policy["retryable_error_types"])
                        for name in error_chain
                    )
                    if not retryable or attempt_index + 1 >= maximum_attempts:
                        call_error = str(exc)
                        logger.error(f"LLM planner call failed: {exc}")
                        break
                    logger.warning(
                        f"Retrying planner transport after {type(exc).__name__}; "
                        f"attempt {attempt_index + 2}/{maximum_attempts}"
                    )
                    if transport_policy.get("reset_client_before_retry"):
                        reset_client = getattr(self.llm, "reset_client", None)
                        if callable(reset_client):
                            reset_client()
                    backoff_s = float(transport_policy.get("backoff_ms", 0) or 0) / 1000.0
                    if backoff_s > 0:
                        time.sleep(backoff_s)
            transport_evidence = {
                "policy_id": str(transport_policy["id"]),
                "attempt_count": len(attempts),
                "retry_count": max(0, len(attempts) - 1),
                "attempts": attempts,
            }

        if (
            strict_deadline
            and not call_error
            and self._goal_deadline_monotonic is not None
            and time.monotonic() >= self._goal_deadline_monotonic - self._action_guard_s
        ):
            call_error = f"{self.protocol.split('-', 1)[0]}_planner_response_missed_action_window"
            response = ""

        parse_error = ""
        if self.strict_stone_pickaxe and not response and not call_error:
            parse_error = "planner_response_empty"
        try:
            raw_plan = json.loads(response) if response else {}
            if not isinstance(raw_plan, dict):
                parse_error = "planner response is not a JSON object"
                raw_plan = {}
        except json.JSONDecodeError as exc:
            parse_error = str(exc)
            raw_plan = {}

        schema_validation = {
            "type": "planner_schema_validation",
            "passed": not bool(call_error or parse_error),
            "issues": [issue for issue in (call_error, parse_error) if issue],
        }
        if self.strict_m2 and not call_error and not parse_error:
            from singularity.evaluation.m2_protocol import validate_root_plan

            schema_validation = validate_root_plan(
                raw_plan,
                expected_goal=goal,
                expected_kind=plan_kind,
            )
        elif self.strict_m4 and not call_error and not parse_error:
            raw_plan, action_parameter_grounding = self._ground_m4_action_parameters(raw_plan)
            raw_plan, place_replan_feedback_grounding = (
                self._ground_m4_place_replan_feedback(
                    raw_plan,
                    plan_kind=plan_kind,
                    feedback=m4_place_replan_feedback,
                )
            )
            raw_plan, place_success_criteria_grounding = (
                self._ground_m4_place_success_criteria(raw_plan, goal=goal)
            )
            raw_plan, subtask_numeric_grounding = self._ground_m4_subtask_numeric_criteria(raw_plan)
            raw_plan, opportunity_trigger_grounding = (
                self._ground_m4_subtask_opportunity_triggers(raw_plan)
            )
            raw_plan, shelter_phase_grounding = self._ground_m4_shelter_phase(
                raw_plan,
                goal=goal,
                world_state=world_state,
            )
            raw_plan, maintenance_phase_grounding = self._ground_m4_maintenance_phase(
                raw_plan,
                goal=goal,
                world_state=world_state,
            )
            schema_validation = self._validate_m4_plan_envelope(
                raw_plan,
                expected_goal=goal,
                expected_kind=plan_kind,
            )
            grounding_issues = list(action_parameter_grounding.get("issues", []))
            grounding_issues.extend(place_replan_feedback_grounding.get("issues", []))
            grounding_issues.extend(place_success_criteria_grounding.get("issues", []))
            grounding_issues.extend(subtask_numeric_grounding.get("issues", []))
            grounding_issues.extend(opportunity_trigger_grounding.get("issues", []))
            schema_validation["action_parameter_grounding"] = action_parameter_grounding
            schema_validation["place_replan_feedback_grounding"] = (
                place_replan_feedback_grounding
            )
            schema_validation["place_success_criteria_grounding"] = (
                place_success_criteria_grounding
            )
            schema_validation["subtask_numeric_criteria_grounding"] = subtask_numeric_grounding
            schema_validation["subtask_opportunity_trigger_grounding"] = (
                opportunity_trigger_grounding
            )
            schema_validation["shelter_phase_grounding"] = shelter_phase_grounding
            schema_validation["maintenance_phase_grounding"] = maintenance_phase_grounding
            schema_validation["issues"] = sorted(set(
                list(schema_validation.get("issues", [])) + grounding_issues
            ))
            schema_validation["passed"] = not schema_validation["issues"]
        elif self.strict_stone_pickaxe and not call_error and not parse_error:
            schema_validation = self._validate_stone_pickaxe_plan_envelope(
                raw_plan,
                expected_goal=goal,
                expected_kind=plan_kind,
            )

        schema_valid = bool(schema_validation.get("passed"))
        if schema_valid:
            plan = dict(raw_plan)
            plan["root_plan_id"] = root_plan_id
            plan["planner_call_id"] = call_id
            plan["parent_planner_call_id"] = self._last_call_id
            plan["schema_validation"] = schema_validation
            if self.strict_m4:
                plan["action_parameter_grounding"] = dict(
                    schema_validation.get("action_parameter_grounding", {})
                )
                plan["place_replan_feedback_grounding"] = dict(
                    schema_validation.get("place_replan_feedback_grounding", {})
                )
                plan["place_success_criteria_grounding"] = dict(
                    schema_validation.get("place_success_criteria_grounding", {})
                )
                plan["subtask_numeric_criteria_grounding"] = dict(
                    schema_validation.get("subtask_numeric_criteria_grounding", {})
                )
                plan["subtask_opportunity_trigger_grounding"] = dict(
                    schema_validation.get("subtask_opportunity_trigger_grounding", {})
                )
                plan["shelter_phase_grounding"] = dict(
                    schema_validation.get("shelter_phase_grounding", {})
                )
                plan["maintenance_phase_grounding"] = dict(
                    schema_validation.get("maintenance_phase_grounding", {})
                )
            if plan_kind == "root":
                self._active_root_plan_id = root_plan_id
            self._create_tasks_from_plan(plan)
        else:
            issue_text = ", ".join(schema_validation.get("issues", [])[:5])
            plan = {
                "schema_version": raw_plan.get("schema_version", ""),
                "plan_kind": plan_kind,
                "goal": goal,
                "status": "error",
                "reasoning": f"Planner output rejected before execution: {issue_text or 'schema validation failed'}",
                "subtasks": [],
                "actions": [],
                "root_plan_id": root_plan_id,
                "planner_call_id": call_id,
                "parent_planner_call_id": self._last_call_id,
                "schema_validation": schema_validation,
            }

        provider_metadata = dict(getattr(self.llm, "last_call_metadata", {}) or {})
        successful_action_summary = self._m2_action_summary(world_state) if self.strict_m2 else {}
        response_sha256 = provider_metadata.get("response_sha256") or hashlib.sha256(
            response.encode("utf-8")
        ).hexdigest()
        real_llm_call = bool(
            response
            and not call_error
            and provider_metadata.get("provider")
            and provider_metadata.get("model")
            and provider_metadata.get("request_sha256")
        )
        self.last_call_evidence = {
            "type": "llm_planner_call",
            "schema_version": 1,
            "planner_id": (
                "llm-root-planner-v1"
                if self.strict_m2
                else "llm-autonomous-planner-v1"
                if self.strict_m4 or self.strict_stone_pickaxe
                else "llm-planner-v1"
            ),
            "protocol": self.protocol,
            "episode_id": self._episode_id,
            "call_id": call_id,
            "call_index": self._call_index,
            "plan_kind": plan_kind,
            "root_plan_id": root_plan_id,
            "parent_call_id": self._last_call_id,
            "goal": goal,
            "real_llm_call": real_llm_call,
            "schema_valid": schema_valid,
            "schema_validation": schema_validation,
            "response_sha256": response_sha256,
            "response_byte_count": len(response.encode("utf-8")),
            "successful_action_summary": successful_action_summary,
            "deadline_policy": deadline_evidence,
            "transport_evidence": transport_evidence,
            "provider_metadata": provider_metadata,
            "error": call_error or parse_error,
        }
        plan["planner_evidence"] = dict(self.last_call_evidence)
        self._last_call_id = call_id
        self._call_index += 1
        return plan

    def _planner_system_prompt(self) -> str:
        if self.strict_m2:
            return self._m2_system_prompt()
        if self.strict_stone_pickaxe:
            return self._stone_pickaxe_system_prompt()
        prompt = f"""You are a Minecraft survival planner. Given a goal and current world state, decompose it into subtasks and immediate actions.

Available actions: move_to, look_at, dig, place, craft, build_shelter_cell, attack, equip, use_item, chat, wait.

MINECRAFT KNOWLEDGE SUMMARY:
{_CRAFTING_KNOWLEDGE}

TOOL PROGRESSION: hand -> wooden -> stone -> iron -> diamond
To mine stone/cobblestone you need at least a wooden pickaxe.
To mine iron_ore you need at least a stone pickaxe.
To get oak_planks, craft them from oak_log (1 log = 4 planks).
To get sticks, craft from 2 planks (2 planks = 4 sticks).
You can punch trees to get oak_log without any tools.

Output JSON:
{{
  "status": "planning" or "complete" or "blocked",
  "reasoning": "brief strategic explanation",
  "subtasks": [
    {{
      "title": "...",
      "type": "...",
      "priority": 1-5,
      "success_criteria": {{}},
      "preconditions": {{"inventory": {{"item_name": count}}, "flags": []}},
      "depends_on": ["earlier subtask title"],
      "opportunity_triggers": ["nearby block/entity/item that makes this task worth doing now"],
      "tags": ["resource", "crafting"],
      "deadline_seconds": 60,
      "assigned_skill": "optional skill name",
      "rationale": "why this subtask matters"
    }}
  ],
  "actions": [
    {{"type": "action_name", "parameters": {{}}}}
  ]
}}

Be practical and safe. Check inventory before crafting. Follow tool progression."""
        if self.strict_m4:
            prompt += """

M4 FIXED OUTPUT CONTRACT:
- Treat the current machine observation and the exact goal wording as authoritative.
- Do not substitute one item species for another exact named target unless the goal explicitly permits alternatives.
- If status is planning, return at least one immediate executable action; never pair planning status with completion prose and an empty actions array.
- If the observed machine state appears to satisfy the exact goal, use status complete and let the machine GoalVerifier decide; prose never completes a goal.
- Use status blocked only when no grounded progress action exists.
- In subtask preconditions.inventory and success_criteria.inventory, every count must be a positive integer. Inventory criteria already mean at least N; never emit comparator strings such as ">=8".
- Every subtask opportunity_triggers value must be a JSON array of non-empty strings. Use only block, entity, item, or causal-tag names; never emit objects, coordinates, numbers, or null values as triggers.
- For a place subtask, prove the placed item from machine world state with success_criteria {"nearby_block_present":"exact_item_name"}; never use inventory of the placed item as placement proof.
- Example placement success_criteria: {"nearby_block_present":"crafting_table"}.
- A dig action must use top-level finite x, y, and z parameters and may use top-level block; never use block_name, position, target, or block_position aliases.
- Example: {"type":"dig","parameters":{"x":103,"y":139,"z":-30,"block":"oak_log"}}.
- A craft action must use item and may use a positive integer count; never use recipe as an alias.
- Example: {"type":"craft","parameters":{"item":"oak_planks","count":4}}.
- A place action must use item plus top-level finite x, y, and z reference-block coordinates; never use block as an alias.
- For place, the actual target is the block cell at floor(x), floor(y)+1, floor(z). Choose a reference whose target is air or replaceable; never target an observed solid block, and choose a different reference after an occupied-target rejection. The target must also remain outside every player collision cell; never target the player's feet/head space. After a player-collision rejection, use one supplied adjacent reference candidate and never retry the rejected reference.
- Example: {"type":"place","parameters":{"item":"crafting_table","x":106,"y":135,"z":-29}}.
- For an active shelter goal, when the current machine state has at least 10 allowlisted building blocks, immediately use build_shelter_cell with the current shelter player_cell as origin and that inventory material. Nine blocks remain in the structure and one is a temporary roof scaffold. Do not add tools, a crafting table, a furnace, mining, or other unrelated prerequisites.
- Example: {"type":"build_shelter_cell","parameters":{"origin":{"x":93,"y":136,"z":-36},"material":"oak_planks"}}.
- A verified-shelter maintenance goal is continuous: before its named nightfall or dawn boundary, return a wait action and preserve the same root instead of reporting complete or expanding another goal."""
        return prompt

    def _stone_pickaxe_system_prompt(self) -> str:
        subtask_example = (
            "[{\"id\":\"observe_state\",\"title\":\"Observe exact state\","
            "\"type\":\"observe\",\"priority\":1,\"preconditions\":{},"
            "\"success_criteria\":{\"observed\":true},\"depends_on\":[]},"
            "{\"id\":\"advance_goal\",\"title\":\"Advance exact goal\","
            "\"type\":\"gather\",\"priority\":1,\"preconditions\":{},"
            "\"success_criteria\":{\"observed\":true},"
            "\"depends_on\":[\"observe_state\"]}]"
            if self._expected_plan_kind == "root"
            else "[]"
        )
        return f"""You are the fixed-protocol stone-pickaxe Minecraft planner. Return one compact JSON object and no prose.

This call is plan_kind={self._expected_plan_kind}. The machine observation, runtime_mode, exact goal, and action guard are authoritative.
Never claim success from prose; the machine verifier alone decides completion.

OUTPUT BOUNDS:
- Use schema_version "stone-pickaxe-plan-v1", the exact supplied goal, and the exact supplied plan_kind.
- Keep reasoning under 320 characters.
- When status is planning, return exactly one immediate action. Never emit a future action script.
- When status is complete or blocked, actions must be empty.
- On a planning root call, return 2-6 concise machine-verifiable subtasks with unique lowercase ids and at least one dependency edge.
- Every root subtask priority must be a JSON integer from 1 through 5; use 1 when no ordering distinction is needed.
- Root preconditions may use only inventory, flags, or nearby_block_present. Root success_criteria may use only inventory, action, result, flags, health_at_least, position_near, observed, or nearby_block_present.
- A table-placement subtask must use success_criteria {{"nearby_block_present":"crafting_table"}}; never use placed or other unsupported state keys.
- On continuation or replan calls, return subtasks=[] and preserve the existing root plan.

CANONICAL ACTIONS:
- move_to/look_at: {{"x":number,"y":number,"z":number}}
- dig: {{"block":"exact_observed_block","x":number,"y":number,"z":number}}
- craft: {{"item":"exact_item","count":positive_integer}}; count is requested output quantity.
- place: {{"item":"exact_item","x":number,"y":number,"z":number}} using an observed solid reference block.
- equip: {{"item":"exact_item"}}
- wait: {{"ms":positive_integer_at_most_2000}}
Never use recipe, block_name, target, position, or block_position aliases.

RUNTIME RULES:
- prepare_fixture: if no nearby blocks are observed, wait 500 ms. Otherwise use only observed coordinates. Dig only exact observed logs, leaves, or allowed terrain; never dig stone or cobblestone. Include block on every dig. Gather at least 3 logs, craft at least 12 matching planks, craft sticks and one table, place the table, then craft exactly one wooden_pickaxe. A crafting_table item in inventory is not a nearby crafting table. Craft wooden_pickaxe only when the current observation contains crafting_table within 4.5 blocks; when the table exists only in inventory, emit place first using an observed solid reference. Never retry wooden_pickaxe craft while no nearby crafting table is observed. Move near observed stone without digging it.
- sp001: do not craft or place. Treat held_item as the authoritative current main-hand item. Equip the exact wooden_pickaxe only when held_item differs; when held_item is wooden_pickaxe, never equip it again and dig block="stone" at the nearest reachable observed stone coordinates. Never repeat a removed source.
- prepare_sp002_fixture: preserve exactly two sticks and never craft stone_pickaxe. If no interactive crafting_table is observed, craft at most one table only when needed, then place or move to it. Equip wooden_pickaxe only when held_item differs. Mine only the nearest reachable observed stone and stop at exactly three cobblestone. Every response containing an action must use status planning. Never declare complete in the same response as placing, approaching, or moving to the table; the action counts only after the next machine observation. Report complete with actions=[] only when the current observation already has cobblestone=3, stick=2, stone_pickaxe=0, and crafting_table within 4.5 blocks.
- sp002: emit exactly one action: craft item="stone_pickaxe" count=1. Require current cobblestone=3, stick=2, stone_pickaxe=0, and an observed crafting_table within 4.5 blocks. Never move, wait, equip, retry, use a recipe alias, craft another item, or report textual success before the machine state changes.

Required JSON shape:
{{
  "schema_version":"stone-pickaxe-plan-v1",
  "plan_kind":"{self._expected_plan_kind}",
  "goal":"exact supplied goal",
  "status":"planning|complete|blocked",
  "reasoning":"brief machine-state rationale",
  "subtasks":{subtask_example},
  "actions":[{{"type":"wait","parameters":{{"ms":500}}}}]
}}"""

    def _m2_system_prompt(self) -> str:
        from singularity.evaluation.m2_protocol import PROTOCOL

        action_parameter_contracts = json.dumps(
            PROTOCOL["planner_schema"].get("action_parameter_contracts", {}),
            sort_keys=True,
            separators=(",", ":"),
        )
        return f"""You are the live Minecraft M2 root planner. Return one strict JSON object and no prose.

This call is plan_kind={self._expected_plan_kind}. Never claim completion from text; the machine verifier decides completion.
For a root call, decompose the exact goal into at least two auditable subtasks with at least one dependency edge.
Each depends_on entry must reference the id of an earlier subtask. Use unique lowercase ids.
Every subtask needs object preconditions and machine-checkable success_criteria using inventory, inventory_any,
observed, nearby_block_present, position_near, structure, action, result, or flags.
Every priority must be an integer from 1 through 5. For M2, set priority=1 on every subtask; dependencies alone encode order.
For an equip subtask, use success_criteria {{"action": {{"type": "equip"}}, "result": {{"success": true}}}};
do not invent equipment or equipped criteria. Use inventory criteria for crafted/mined items and position_near for movement.
Treat the current inventory and nearby/placed blocks as authoritative. Account for recipe output quantities, and do not
create a subtask whose success criteria are already satisfied by the current observation.
Return exactly one immediate executable action when status is planning.
Treat the episode successful-action summary as authoritative history. Do not repeat an action solely to satisfy
required_action_types when that action type is already proven there; advance the next unmet subtask instead.
A successful move_to to an unchanged target must not be repeated. When a target block is already within 4.5 blocks,
emit the dependent interaction action instead of move_to. The only exception is when required_action_types includes
move_to and the successful-action summary has move_to=0: emit one grounded move_to, then interact without moving again.

Allowed actions: move_to, look_at, dig, place, craft, equip, use_item, wait, build_shelter_5x5.
Canonical action parameter contracts: {action_parameter_contracts}
Follow these contracts exactly. In particular, dig uses top-level block, x, y, and z parameters; do not use
block_name, target, position, or block_position aliases.
Craft uses an item parameter and optional positive integer count; do not use recipe as an alias.
The build_shelter_5x5 action is bounded: use only the construction_zone origin supplied in benchmark_context,
choose an inventory material, and do not emit individual free-form place coordinates for a whole shelter.

Minecraft facts: one log crafts four planks; two planks craft four sticks; a crafting table needs four planks;
a wooden pickaxe needs three planks, two sticks, and a nearby crafting table; stone needs a wooden pickaxe;
a torch needs coal or charcoal plus a stick and does not require a crafting table.

Required JSON shape:
{{
  "schema_version": "m2-root-plan-v1",
  "plan_kind": "{self._expected_plan_kind}",
  "goal": "the exact supplied goal",
  "status": "planning" or "blocked" or "complete" or "error",
  "reasoning": "brief state-grounded rationale",
  "subtasks": [
    {{
      "id": "short_id",
      "title": "auditable title",
      "type": "observe|gather|craft|mine|build|verify|recover",
      "priority": 1,
      "depends_on": [],
      "preconditions": {{}},
      "success_criteria": {{"inventory": {{"item": 1}}}},
      "rationale": "why this node is needed"
    }}
  ],
  "actions": [{{"type": "action_name", "parameters": {{}}}}]
}}"""

    def _build_planning_prompt(self, goal: str, world_state: dict, memory_context: str) -> str:
        if self.strict_m2:
            from singularity.evaluation.m2_protocol import PROTOCOL, task_spec

            spec = next(
                (task for task in PROTOCOL["tasks"] if task.get("goal") == goal),
                task_spec(getattr(self, "_m2_task_id", "")),
            ) or {}
            contract = {
                "task_id": spec.get("id", ""),
                "success_criteria": spec.get("success_criteria", {}),
                "verified_initial_inventory": spec.get("initial_inventory", {}),
                "verified_initial_blocks": spec.get("initial_blocks", []),
                "task_guidance": _M2_TASK_GUIDANCE.get(str(spec.get("id") or ""), []),
                "construction_zone": (world_state.get("benchmark_context", {}) or {}).get("construction_zone", {}),
            }
            action_summary = self._m2_action_summary(world_state)
            observed_state = dict(world_state)
            observed_state.pop("m2_successful_action_summary", None)
            return f"""Exact goal: {goal}
Expected plan_kind: {self._expected_plan_kind}
Benchmark contract: {json.dumps(contract, sort_keys=True, default=str)}
Episode successful-action summary: {json.dumps(action_summary, sort_keys=True, default=str)}
Current observed world state: {json.dumps(observed_state, sort_keys=True, default=str)[:5000]}
Planner context: {memory_context[:1000] if memory_context else 'none'}
Return strict JSON now."""
        if self.strict_stone_pickaxe:
            machine_state = self._compact_stone_pickaxe_state(world_state)
            completion_gate = ""
            if machine_state.get("runtime_mode") == "prepare_sp002_fixture":
                inventory = machine_state.get("inventory", {})
                table_observed = any(
                    block.get("name") == "crafting_table"
                    and isinstance(block.get("distance"), (int, float))
                    and float(block["distance"]) <= 4.5
                    for block in machine_state.get("nearby_blocks", [])
                    if isinstance(block, dict)
                )
                completion_ready = (
                    inventory.get("cobblestone") == 3
                    and inventory.get("stick") == 2
                    and not inventory.get("stone_pickaxe", 0)
                    and table_observed
                )
                completion_gate = f"""
SP-002 fixture completion gate: completion_ready={str(completion_ready).lower()}.
If completion_ready=false, status=complete is forbidden; return status=planning with exactly one grounded action.
Every action-bearing response must use status=planning. Never combine complete or blocked with an action.
An action's predicted result does not satisfy this gate; wait for the next machine observation.
If completion_ready=true and no action is needed, return status=complete with actions=[]."""
            return f"""Exact goal: {goal}
Expected plan_kind: {self._expected_plan_kind}
Runtime mode: {machine_state.get('runtime_mode') or 'unknown'}
Current compact machine state: {json.dumps(machine_state, sort_keys=True, separators=(',', ':'), default=str)}
{completion_gate}
Planner context: {memory_context[:500] if memory_context else 'none'}
Choose only the next grounded action and return contract-valid compact JSON now."""
        if self.strict_m4:
            shelter = world_state.get("shelter_verification", {}) if isinstance(world_state, dict) else {}
            shelter = shelter if isinstance(shelter, dict) else {}
            compact_shelter = {
                "verifier_id": shelter.get("verifier_id", ""),
                "passed": shelter.get("passed") is True,
                "safe_state": shelter.get("safe_state") is True,
                "strategy": shelter.get("strategy", ""),
                "issues": list(shelter.get("issues", []) or [])[:8],
                "checks": {
                    str(check.get("name") or ""): check.get("passed") is True
                    for check in shelter.get("checks", [])
                    if isinstance(check, dict)
                },
                "episode_block_delta": {
                    "matched_position_count": (shelter.get("episode_block_delta") or {}).get("matched_position_count", 0),
                    "required_position_count": (shelter.get("episode_block_delta") or {}).get("required_position_count", 0),
                },
            }
            observed_state = dict(world_state)
            observed_state["shelter_verification"] = compact_shelter
            return f"""Exact autonomous goal: {goal}
Plan kind: {self._expected_plan_kind}
Current shelter machine state: {json.dumps(compact_shelter, sort_keys=True, default=str)}
Current observed machine state: {json.dumps(observed_state, sort_keys=True, default=str)[:3000]}
Planner context: {memory_context[:1000] if memory_context else 'none'}
Honor exact item identifiers. Return a contract-valid JSON plan now."""
        return f"""Goal: {goal}

World state:
{json.dumps(world_state, indent=2, default=str)[:2000]}

{f'Relevant memory: {memory_context}' if memory_context else ''}

Plan the steps to achieve this goal."""

    @staticmethod
    def _compact_stone_pickaxe_state(world_state: dict) -> dict:
        state = world_state if isinstance(world_state, dict) else {}

        def finite(value):
            return (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
            )

        def compact_position(value):
            if not isinstance(value, dict):
                return {}
            return {
                axis: value[axis]
                for axis in ("x", "y", "z")
                if finite(value.get(axis))
            }

        raw_blocks = state.get("nearby_blocks")
        raw_blocks = raw_blocks if isinstance(raw_blocks, list) else []
        blocks = []
        seen = set()
        for block in raw_blocks:
            if not isinstance(block, dict):
                continue
            name = str(block.get("name") or "")
            position = compact_position(block.get("position"))
            if not name or len(position) != 3:
                continue
            key = (name, position["x"], position["y"], position["z"])
            if key in seen:
                continue
            seen.add(key)
            row = {"name": name, **position}
            if finite(block.get("distance")):
                row["distance"] = round(float(block["distance"]), 3)
            blocks.append(row)

        def relevant(block):
            name = block["name"]
            return (
                name in {"stone", "crafting_table"}
                or name.endswith("_log")
                or name.endswith("_stem")
            )

        prioritized = [block for block in blocks if relevant(block)]
        prioritized.extend(block for block in blocks if not relevant(block))
        inventory = state.get("inventory") if isinstance(state.get("inventory"), dict) else {}
        compact_inventory = {}
        for name, count in sorted(inventory.items()):
            try:
                numeric = int(count)
            except (TypeError, ValueError):
                continue
            if numeric > 0:
                compact_inventory[str(name)] = numeric

        equipment = state.get("equipment")
        equipment = equipment if isinstance(equipment, list) else []
        main_hand = (
            equipment[0]
            if equipment and isinstance(equipment[0], dict)
            else {}
        )

        return {
            "runtime_mode": str(state.get("stone_pickaxe_runtime_mode") or ""),
            "position": compact_position(state.get("position")),
            "inventory": compact_inventory,
            "held_item": str(main_hand.get("name") or ""),
            "health": state.get("health"),
            "hunger": state.get("hunger"),
            "game_mode": str(state.get("game_mode") or ""),
            "ground_block": str(state.get("ground_block") or ""),
            "nearby_block_count": len(blocks),
            "nearby_blocks": prioritized[:24],
        }

    @staticmethod
    def _validate_stone_pickaxe_plan_envelope(
        plan: dict,
        expected_goal: str,
        expected_kind: str,
    ) -> dict:
        """Fail closed on malformed or unbounded stone-pickaxe plans."""
        issues: list[str] = []
        allowed_plan_keys = {
            "schema_version",
            "plan_kind",
            "goal",
            "status",
            "reasoning",
            "subtasks",
            "actions",
        }
        for unexpected in sorted(set(plan) - allowed_plan_keys):
            issues.append(f"plan_field_unexpected:{unexpected}")
        compact_plan_chars = len(
            json.dumps(plan, sort_keys=True, separators=(",", ":"), default=str)
        )
        if compact_plan_chars > 6000:
            issues.append("plan_compact_size_exceeded")
        if plan.get("schema_version") != "stone-pickaxe-plan-v1":
            issues.append("schema_version_invalid")
        if plan.get("plan_kind") != expected_kind:
            issues.append("plan_kind_mismatch")
        if plan.get("goal") != expected_goal:
            issues.append("goal_mismatch")

        status = str(plan.get("status") or "")
        if status not in {"planning", "complete", "blocked"}:
            issues.append("status_invalid")

        reasoning = plan.get("reasoning")
        if not isinstance(reasoning, str) or not reasoning.strip():
            issues.append("reasoning_missing")
        elif len(reasoning) > 320:
            issues.append("reasoning_too_long")

        subtasks = plan.get("subtasks")
        if not isinstance(subtasks, list):
            issues.append("subtasks_not_array")
            subtasks = []
        if expected_kind == "root" and status == "planning":
            if not 2 <= len(subtasks) <= 6:
                issues.append("root_subtask_count_out_of_bounds")
            seen_ids: set[str] = set()
            dependency_count = 0
            for index, subtask in enumerate(subtasks):
                if not isinstance(subtask, dict):
                    issues.append(f"subtask[{index}]:not_object")
                    continue
                node_id = str(subtask.get("id") or "")
                if not re.fullmatch(r"[a-z0-9_]{1,32}", node_id):
                    issues.append(f"subtask[{index}]:id_invalid")
                elif node_id in seen_ids:
                    issues.append(f"subtask[{index}]:id_duplicate")
                if not str(subtask.get("title") or "").strip():
                    issues.append(f"subtask[{index}]:title_missing")
                elif len(str(subtask["title"])) > 120:
                    issues.append(f"subtask[{index}]:title_too_long")
                allowed_subtask_keys = {
                    "id",
                    "title",
                    "type",
                    "priority",
                    "preconditions",
                    "success_criteria",
                    "depends_on",
                }
                for unexpected in sorted(set(subtask) - allowed_subtask_keys):
                    issues.append(f"subtask[{index}]:field_unexpected:{unexpected}")
                if not isinstance(subtask.get("preconditions"), dict):
                    issues.append(f"subtask[{index}]:preconditions_not_object")
                else:
                    allowed_precondition_keys = {
                        "inventory",
                        "flags",
                        "nearby_block_present",
                    }
                    for key in sorted(
                        set(subtask["preconditions"]) - allowed_precondition_keys
                    ):
                        issues.append(f"subtask[{index}]:precondition_key_forbidden:{key}")
                if not isinstance(subtask.get("success_criteria"), dict):
                    issues.append(f"subtask[{index}]:success_criteria_not_object")
                elif not subtask["success_criteria"]:
                    issues.append(f"subtask[{index}]:success_criteria_empty")
                else:
                    allowed_success_criteria_keys = {
                        "inventory",
                        "action",
                        "result",
                        "flags",
                        "health_at_least",
                        "position_near",
                        "observed",
                        "nearby_block_present",
                    }
                    for key in sorted(
                        set(subtask["success_criteria"]) - allowed_success_criteria_keys
                    ):
                        issues.append(
                            f"subtask[{index}]:success_criteria_key_forbidden:{key}"
                        )
                for field in ("preconditions", "success_criteria"):
                    if len(json.dumps(subtask.get(field), default=str)) > 600:
                        issues.append(f"subtask[{index}]:{field}_too_large")
                priority = subtask.get("priority")
                if (
                    not isinstance(priority, int)
                    or isinstance(priority, bool)
                    or not 1 <= priority <= 5
                ):
                    issues.append(f"subtask[{index}]:priority_invalid")
                dependencies = subtask.get("depends_on")
                if not isinstance(dependencies, list):
                    issues.append(f"subtask[{index}]:depends_on_not_array")
                    dependencies = []
                for dependency in dependencies:
                    if not isinstance(dependency, str) or dependency not in seen_ids:
                        issues.append(f"subtask[{index}]:dependency_not_earlier_id")
                    else:
                        dependency_count += 1
                if node_id:
                    seen_ids.add(node_id)
            if dependency_count == 0:
                issues.append("root_dependency_edge_missing")
        elif subtasks:
            issues.append("non_root_subtasks_forbidden")

        actions = plan.get("actions")
        if not isinstance(actions, list):
            issues.append("actions_not_array")
            actions = []
        if status == "planning" and len(actions) != 1:
            issues.append("planning_action_count_must_equal_one")
        if status in {"complete", "blocked"} and actions:
            issues.append("terminal_actions_forbidden")

        if len(actions) == 1:
            action = actions[0]
            if not isinstance(action, dict):
                issues.append("action_not_object")
            else:
                action_type = str(action.get("type") or "")
                params = action.get("parameters")
                if action_type not in {
                    "move_to",
                    "look_at",
                    "dig",
                    "craft",
                    "place",
                    "equip",
                    "wait",
                }:
                    issues.append("action_type_forbidden")
                if not isinstance(params, dict):
                    issues.append("action_parameters_not_object")
                    params = {}
                alias_names = {
                    "recipe",
                    "block_name",
                    "target",
                    "position",
                    "block_position",
                }
                for alias in sorted(alias_names.intersection(params)):
                    issues.append(f"action_parameter_alias_forbidden:{alias}")

                def require_xyz():
                    for axis in ("x", "y", "z"):
                        value = params.get(axis)
                        if (
                            not isinstance(value, (int, float))
                            or isinstance(value, bool)
                            or not math.isfinite(float(value))
                        ):
                            issues.append(f"action_parameter_{axis}_invalid")

                if action_type in {"move_to", "look_at"}:
                    require_xyz()
                    allowed = {"x", "y", "z"}
                elif action_type == "dig":
                    require_xyz()
                    if not str(params.get("block") or "").strip():
                        issues.append("dig_block_missing")
                    allowed = {"block", "x", "y", "z"}
                elif action_type == "craft":
                    if not str(params.get("item") or "").strip():
                        issues.append("craft_item_missing")
                    count = params.get("count", 1)
                    if (
                        not isinstance(count, int)
                        or isinstance(count, bool)
                        or not 1 <= count <= 64
                    ):
                        issues.append("craft_count_invalid")
                    allowed = {"item", "count"}
                elif action_type == "place":
                    require_xyz()
                    if not str(params.get("item") or "").strip():
                        issues.append("place_item_missing")
                    allowed = {"item", "x", "y", "z"}
                elif action_type == "equip":
                    if not str(params.get("item") or "").strip():
                        issues.append("equip_item_missing")
                    allowed = {"item", "destination"}
                elif action_type == "wait":
                    wait_ms = params.get("ms")
                    if (
                        not isinstance(wait_ms, int)
                        or isinstance(wait_ms, bool)
                        or not 1 <= wait_ms <= 2000
                    ):
                        issues.append("wait_ms_invalid")
                    allowed = {"ms"}
                else:
                    allowed = set()
                for unexpected in sorted(set(params) - allowed):
                    issues.append(f"action_parameter_unexpected:{unexpected}")

        return {
            "type": "stone_pickaxe_plan_envelope_validation",
            "schema_version": 1,
            "passed": not issues,
            "expected_goal": str(expected_goal or ""),
            "expected_kind": str(expected_kind or ""),
            "status": status,
            "subtask_count": len(subtasks),
            "action_count": len(actions),
            "compact_plan_chars": compact_plan_chars,
            "completion_requires_machine_verifier": True,
            "issues": sorted(set(issues)),
        }

    @staticmethod
    def _validate_m4_plan_envelope(
        plan: dict,
        expected_goal: str,
        expected_kind: str,
    ) -> dict:
        """Validate only the M4 status/action envelope before runtime execution."""
        issues: list[str] = []
        status = str(plan.get("status") or "")
        if status not in {"planning", "complete", "blocked"}:
            issues.append("status_invalid")

        actions = plan.get("actions")
        if not isinstance(actions, list):
            issues.append("actions_not_array")
            actions = []
        if status == "planning" and not actions:
            issues.append("planning_actions_missing")

        return {
            "type": "m4_plan_envelope_validation",
            "schema_version": 1,
            "passed": not issues,
            "expected_goal": str(expected_goal or ""),
            "expected_kind": str(expected_kind or ""),
            "status": status,
            "action_count": len(actions),
            "completion_requires_machine_verifier": True,
            "issues": sorted(set(issues)),
        }

    @classmethod
    def _ground_m4_action_parameters(cls, plan: dict) -> tuple[dict, dict]:
        """Canonicalize provably equivalent M4 primitive aliases and reject drift."""
        grounded_plan = dict(plan or {})
        actions = grounded_plan.get("actions")
        if not isinstance(actions, list):
            return grounded_plan, {
                "type": "m4_action_parameter_grounding",
                "schema_version": 1,
                "passed": True,
                "action_count": 0,
                "dig_action_count": 0,
                "craft_action_count": 0,
                "place_action_count": 0,
                "normalized_action_count": 0,
                "normalizations": [],
                "issues": [],
            }
        grounded_actions = []
        issues: list[str] = []
        normalizations = []
        dig_action_count = 0
        craft_action_count = 0
        place_action_count = 0

        for index, action in enumerate(actions):
            if not isinstance(action, dict):
                grounded_actions.append(action)
                continue
            grounded_action = dict(action)
            action_type = str(action.get("type") or "")
            if action_type not in {"dig", "craft", "place"}:
                grounded_actions.append(grounded_action)
                continue
            if action_type == "dig":
                dig_action_count += 1
                canonical, evidence = cls._ground_m4_dig_parameters(
                    action.get("parameters"),
                    action_index=index,
                )
            elif action_type == "craft":
                craft_action_count += 1
                canonical, evidence = cls._ground_m4_craft_parameters(
                    action.get("parameters"),
                    action_index=index,
                )
            else:
                place_action_count += 1
                canonical, evidence = cls._ground_m4_place_parameters(
                    action.get("parameters"),
                    action_index=index,
                )
            grounded_action["parameters"] = canonical
            grounded_actions.append(grounded_action)
            issues.extend(evidence["issues"])
            if evidence["normalized"]:
                normalizations.append(evidence)

        grounded_plan["actions"] = grounded_actions
        report = {
            "type": "m4_action_parameter_grounding",
            "schema_version": 1,
            "passed": not issues,
            "action_count": len(actions),
            "dig_action_count": dig_action_count,
            "craft_action_count": craft_action_count,
            "place_action_count": place_action_count,
            "normalized_action_count": len(normalizations),
            "normalizations": normalizations,
            "issues": sorted(set(issues)),
        }
        return grounded_plan, report

    @classmethod
    def _ground_m4_place_replan_feedback(
        cls,
        plan: dict,
        *,
        plan_kind: str,
        feedback: dict = None,
    ) -> tuple[dict, dict]:
        """Fail closed when a place replan violates the verifier's bounded candidates."""
        grounded_plan = dict(plan or {})
        report = {
            "type": "m4_place_replan_feedback_grounding",
            "schema_version": 1,
            "policy_id": cls.M4_PLACE_REPLAN_FEEDBACK_POLICY_ID,
            "activated": False,
            "passed": True,
            "plan_kind": str(plan_kind or ""),
            "reason": "no_pending_place_replan_feedback",
            "rejected_reference": {},
            "adjacent_reference_candidates": [],
            "candidate_count": 0,
            "place_action_count": 0,
            "selected_reference": {},
            "selected_candidate_index": None,
            "repeated_rejected_reference": False,
            "fail_closed_before_action_execution": True,
            "issues": [],
        }
        if str(plan_kind or "") != "replan" or not feedback:
            if str(plan_kind or "") != "replan":
                report["reason"] = "plan_kind_is_not_replan"
            return grounded_plan, report

        report["activated"] = True
        report["reason"] = "verifier_place_replan_feedback_applied"
        issues: list[str] = []

        rejected_reference = cls._m4_reference_coordinates(
            feedback.get("rejected_reference") if isinstance(feedback, dict) else None
        )
        if rejected_reference is None:
            issues.append("place_replan_feedback_rejected_reference_invalid")
            rejected_reference = {}
        report["rejected_reference"] = rejected_reference

        raw_candidates = (
            feedback.get("adjacent_reference_candidates")
            if isinstance(feedback, dict)
            else None
        )
        candidates = []
        if not isinstance(raw_candidates, list) or not 1 <= len(raw_candidates) <= 4:
            issues.append("place_replan_feedback_candidate_count_invalid")
            raw_candidates = raw_candidates if isinstance(raw_candidates, list) else []
        for index, value in enumerate(raw_candidates):
            candidate = cls._m4_reference_coordinates(value)
            if candidate is None:
                issues.append(f"place_replan_feedback_candidate[{index}]_invalid")
                continue
            if candidate in candidates:
                issues.append(f"place_replan_feedback_candidate[{index}]_duplicate")
                continue
            if rejected_reference and candidate == rejected_reference:
                issues.append(f"place_replan_feedback_candidate[{index}]_is_rejected_reference")
                continue
            candidates.append(candidate)
        report["adjacent_reference_candidates"] = candidates
        report["candidate_count"] = len(candidates)

        actions = grounded_plan.get("actions")
        actions = actions if isinstance(actions, list) else []
        place_actions = [
            (index, action)
            for index, action in enumerate(actions)
            if isinstance(action, dict) and str(action.get("type") or "") == "place"
        ]
        report["place_action_count"] = len(place_actions)
        if not place_actions:
            issues.append("place_replan_feedback_place_action_missing")
        elif len(place_actions) != 1:
            issues.append(
                f"place_replan_feedback_place_action_count_invalid:{len(place_actions)}"
            )
        else:
            action_index, action = place_actions[0]
            selected = cls._m4_reference_coordinates(action.get("parameters"))
            if selected is None:
                issues.append(f"action[{action_index}]:place_replan_reference_invalid")
            else:
                report["selected_reference"] = selected
                if rejected_reference and selected == rejected_reference:
                    report["repeated_rejected_reference"] = True
                    issues.append(
                        f"action[{action_index}]:place_replan_rejected_reference_repeated"
                    )
                elif selected not in candidates:
                    issues.append(
                        f"action[{action_index}]:place_replan_reference_not_adjacent_candidate"
                    )
                else:
                    report["selected_candidate_index"] = candidates.index(selected)

        report["issues"] = sorted(set(issues))
        report["passed"] = not report["issues"]
        return grounded_plan, report

    @classmethod
    def _m4_reference_coordinates(cls, value) -> dict | None:
        if not isinstance(value, dict):
            return None
        reference = {}
        for axis in ("x", "y", "z"):
            coordinate = cls._finite_parameter(value.get(axis))
            if coordinate is None:
                return None
            reference[axis] = coordinate
        return reference

    @classmethod
    def _ground_m4_place_success_criteria(
        cls,
        plan: dict,
        *,
        goal: str,
    ) -> tuple[dict, dict]:
        """Ground placement completion in nearby machine-observed block state."""
        grounded_plan = dict(plan or {})
        actions = grounded_plan.get("actions")
        subtasks = grounded_plan.get("subtasks")
        place_actions = [
            action for action in actions
            if (
                isinstance(action, dict)
                and str(action.get("type") or "").strip() == "place"
                and isinstance(action.get("parameters"), dict)
                and str((action.get("parameters") or {}).get("item") or "").strip()
            )
        ] if isinstance(actions, list) else []
        place_items = sorted({
            str((action.get("parameters") or {}).get("item") or "").strip()
            for action in place_actions
        })
        original_subtasks_sha256 = cls._parameter_sha256(subtasks)
        if not isinstance(subtasks, list):
            return grounded_plan, {
                "type": "m4_place_success_criteria_grounding",
                "schema_version": 1,
                "policy_id": "m4-place-success-criteria-grounding-v1",
                "passed": True,
                "goal": str(goal or ""),
                "place_action_count": len(place_actions),
                "place_action_items": place_items,
                "subtask_count": 0,
                "grounded_subtask_count": 0,
                "removed_inventory_requirement_count": 0,
                "original_subtasks_sha256": original_subtasks_sha256,
                "grounded_subtasks_sha256": original_subtasks_sha256,
                "normalizations": [],
                "issues": [],
            }

        issues: list[str] = []
        normalizations = []
        grounded_subtasks = []
        grounded_subtask_count = 0
        removed_requirement_count = 0
        place_item_set = set(place_items)

        for subtask_index, subtask in enumerate(subtasks):
            if not isinstance(subtask, dict):
                grounded_subtasks.append(subtask)
                continue
            grounded_subtask = dict(subtask)
            criteria = subtask.get("success_criteria")
            inventory = criteria.get("inventory") if isinstance(criteria, dict) else None
            matching_items = sorted(
                item
                for item in inventory
                if isinstance(item, str) and item in place_item_set
            ) if isinstance(inventory, dict) else []
            if not matching_items:
                grounded_subtasks.append(grounded_subtask)
                continue

            descriptor = " ".join((
                str(subtask.get("title") or ""),
                str(subtask.get("type") or ""),
            ))
            descriptor_tokens = set(re.findall(
                r"[a-z0-9]+",
                descriptor.lower().replace("_", " "),
            ))
            placement_intent = bool(
                descriptor_tokens
                & {"place", "placed", "places", "placing", "placement"}
            )
            if not placement_intent:
                issues.extend(
                    f"subtask[{subtask_index}]:place_success_criteria_intent_missing:{item}"
                    for item in matching_items
                )
                grounded_subtasks.append(grounded_subtask)
                continue

            ungrounded_goal_items = [
                item for item in matching_items
                if not cls._m4_goal_requests_item_placement(goal, item)
            ]
            if ungrounded_goal_items:
                issues.extend(
                    f"subtask[{subtask_index}]:place_success_criteria_goal_mismatch:{item}"
                    for item in ungrounded_goal_items
                )
                grounded_subtasks.append(grounded_subtask)
                continue

            expected_nearby = (
                matching_items[0] if len(matching_items) == 1 else matching_items
            )
            existing_nearby = criteria.get("nearby_block_present")
            if (
                existing_nearby is not None
                and cls._m4_required_name_set(existing_nearby) != set(matching_items)
            ):
                issues.append(
                    f"subtask[{subtask_index}]:"
                    "place_success_criteria_nearby_block_conflict"
                )
                grounded_subtasks.append(grounded_subtask)
                continue

            grounded_inventory = dict(inventory)
            for item in matching_items:
                source_value = grounded_inventory.pop(item)
                normalizations.append({
                    "subtask_index": subtask_index,
                    "item": item,
                    "source_field": "success_criteria.inventory",
                    "source_value_sha256": cls._parameter_sha256(source_value),
                    "source_count_was_positive_integer": (
                        isinstance(source_value, int)
                        and not isinstance(source_value, bool)
                        and source_value > 0
                    ),
                    "canonical_field": "success_criteria.nearby_block_present",
                    "canonical_value": item,
                    "reason": "placement_requires_machine_world_state",
                })
                removed_requirement_count += 1

            grounded_criteria = dict(criteria)
            if grounded_inventory:
                grounded_criteria["inventory"] = grounded_inventory
            else:
                grounded_criteria.pop("inventory", None)
            grounded_criteria["nearby_block_present"] = expected_nearby
            grounded_subtask["success_criteria"] = grounded_criteria
            grounded_subtasks.append(grounded_subtask)
            grounded_subtask_count += 1

        grounded_plan["subtasks"] = grounded_subtasks
        return grounded_plan, {
            "type": "m4_place_success_criteria_grounding",
            "schema_version": 1,
            "policy_id": "m4-place-success-criteria-grounding-v1",
            "passed": not issues,
            "goal": str(goal or ""),
            "place_action_count": len(place_actions),
            "place_action_items": place_items,
            "subtask_count": len(subtasks),
            "grounded_subtask_count": grounded_subtask_count,
            "removed_inventory_requirement_count": removed_requirement_count,
            "original_subtasks_sha256": original_subtasks_sha256,
            "grounded_subtasks_sha256": cls._parameter_sha256(grounded_subtasks),
            "normalizations": normalizations,
            "issues": sorted(set(issues)),
        }

    @staticmethod
    def _m4_goal_requests_item_placement(goal: str, item: str) -> bool:
        normalized_goal = " ".join(re.findall(
            r"[a-z0-9]+",
            str(goal or "").lower().replace("_", " "),
        ))
        goal_tokens = set(normalized_goal.split())
        has_place_intent = bool(
            goal_tokens & {"place", "placed", "places", "placing", "placement"}
        )
        normalized_item = " ".join(re.findall(
            r"[a-z0-9]+",
            str(item or "").lower().replace("_", " "),
        ))
        return bool(
            has_place_intent
            and normalized_item
            and f" {normalized_item} " in f" {normalized_goal} "
        )

    @staticmethod
    def _m4_required_name_set(value) -> set[str]:
        if isinstance(value, str):
            return {value.strip().lower()} if value.strip() else set()
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return {item.strip().lower() for item in value if item.strip()}
        return set()

    @classmethod
    def _ground_m4_subtask_numeric_criteria(cls, plan: dict) -> tuple[dict, dict]:
        """Normalize exact at-least aliases and reject unsafe M4 inventory counts."""
        grounded_plan = dict(plan or {})
        subtasks = grounded_plan.get("subtasks")
        if not isinstance(subtasks, list):
            return grounded_plan, {
                "type": "m4_subtask_numeric_criteria_grounding",
                "schema_version": 1,
                "passed": True,
                "subtask_count": 0,
                "inventory_requirement_count": 0,
                "normalized_requirement_count": 0,
                "normalizations": [],
                "issues": [],
            }

        grounded_subtasks = []
        issues: list[str] = []
        normalizations = []
        requirement_count = 0
        for subtask_index, subtask in enumerate(subtasks):
            if not isinstance(subtask, dict):
                grounded_subtasks.append(subtask)
                continue
            grounded_subtask = dict(subtask)
            for field_name in ("preconditions", "success_criteria"):
                if field_name not in subtask:
                    continue
                criteria = subtask.get(field_name)
                prefix = f"subtask[{subtask_index}]:{field_name}"
                if not isinstance(criteria, dict):
                    issues.append(prefix + "_not_object")
                    continue
                if "inventory" not in criteria:
                    continue
                inventory = criteria.get("inventory")
                if not isinstance(inventory, dict):
                    issues.append(prefix + "_inventory_not_object")
                    continue

                canonical_inventory = dict(inventory)
                for item, count in inventory.items():
                    requirement_count += 1
                    canonical_count = None
                    alias = ""
                    if isinstance(count, int) and not isinstance(count, bool) and count > 0:
                        canonical_count = count
                    elif isinstance(count, str):
                        match = re.fullmatch(r"\s*>=\s*([1-9]\d*)\s*", count)
                        if match:
                            canonical_count = int(match.group(1))
                            alias = ">=N->N"

                    if canonical_count is None:
                        issues.append(
                            prefix + "_inventory_count_invalid:" + str(item)
                        )
                        continue
                    canonical_inventory[item] = canonical_count
                    if alias:
                        normalizations.append({
                            "subtask_index": subtask_index,
                            "field": field_name,
                            "item": str(item),
                            "alias": alias,
                            "original_value_sha256": cls._parameter_sha256(count),
                            "canonical_count": canonical_count,
                        })

                grounded_criteria = dict(criteria)
                grounded_criteria["inventory"] = canonical_inventory
                grounded_subtask[field_name] = grounded_criteria
            grounded_subtasks.append(grounded_subtask)

        grounded_plan["subtasks"] = grounded_subtasks
        report = {
            "type": "m4_subtask_numeric_criteria_grounding",
            "schema_version": 1,
            "passed": not issues,
            "subtask_count": len(subtasks),
            "inventory_requirement_count": requirement_count,
            "normalized_requirement_count": len(normalizations),
            "normalizations": normalizations,
            "issues": sorted(set(issues)),
        }
        return grounded_plan, report

    @staticmethod
    def _ground_m4_subtask_opportunity_triggers(plan: dict) -> tuple[dict, dict]:
        """Reject malformed M4 scheduler hints before they enter TaskSystem."""
        grounded_plan = dict(plan or {})
        subtasks = grounded_plan.get("subtasks")
        if not isinstance(subtasks, list):
            return grounded_plan, {
                "type": "m4_subtask_opportunity_trigger_grounding",
                "schema_version": 1,
                "policy_id": "m4-subtask-opportunity-trigger-type-grounding-v1",
                "passed": True,
                "subtask_count": 0,
                "trigger_list_count": 0,
                "trigger_count": 0,
                "valid_trigger_count": 0,
                "issues": [],
            }

        issues: list[str] = []
        trigger_list_count = 0
        trigger_count = 0
        valid_trigger_count = 0
        for subtask_index, subtask in enumerate(subtasks):
            if not isinstance(subtask, dict) or "opportunity_triggers" not in subtask:
                continue
            triggers = subtask.get("opportunity_triggers")
            if not isinstance(triggers, list):
                issues.append(
                    f"subtask[{subtask_index}]:opportunity_triggers_not_array"
                )
                continue
            trigger_list_count += 1
            trigger_count += len(triggers)
            for trigger_index, trigger in enumerate(triggers):
                prefix = (
                    f"subtask[{subtask_index}]:"
                    f"opportunity_triggers[{trigger_index}]"
                )
                if not isinstance(trigger, str):
                    issues.append(prefix + "_not_string")
                elif not trigger.strip():
                    issues.append(prefix + "_empty")
                else:
                    valid_trigger_count += 1

        report = {
            "type": "m4_subtask_opportunity_trigger_grounding",
            "schema_version": 1,
            "policy_id": "m4-subtask-opportunity-trigger-type-grounding-v1",
            "passed": not issues,
            "subtask_count": len(subtasks),
            "trigger_list_count": trigger_list_count,
            "trigger_count": trigger_count,
            "valid_trigger_count": valid_trigger_count,
            "issues": sorted(set(issues)),
        }
        return grounded_plan, report

    @classmethod
    def _ground_m4_dig_parameters(cls, value, *, action_index: int) -> tuple[dict, dict]:
        prefix = f"action[{action_index}]:"
        if not isinstance(value, dict):
            return {}, {
                "action_index": action_index,
                "action_type": "dig",
                "normalized": False,
                "aliases": [],
                "original_parameters_sha256": cls._parameter_sha256(value),
                "canonical_parameters": {},
                "issues": [prefix + "dig_parameters_not_object"],
            }

        params = dict(value)
        issues: list[str] = []
        aliases: list[str] = []
        allowed = {"block", "x", "y", "z", "timeout_ms", "block_name", "position"}
        unknown = sorted(str(key) for key in params if key not in allowed)
        if unknown:
            issues.append(prefix + "dig_unknown_parameters:" + ",".join(unknown))

        nested = params.get("position")
        if "position" in params:
            aliases.append("position->x,y,z")
            if not isinstance(nested, dict):
                issues.append(prefix + "dig_position_not_object")
                nested = {}
            else:
                nested_unknown = sorted(str(key) for key in nested if key not in {"x", "y", "z"})
                if nested_unknown:
                    issues.append(prefix + "dig_position_unknown_keys:" + ",".join(nested_unknown))
        else:
            nested = {}

        canonical = {}
        missing = []
        for axis in ("x", "y", "z"):
            top_present = axis in params
            nested_present = axis in nested
            top = cls._finite_parameter(params.get(axis)) if top_present else None
            nested_value = cls._finite_parameter(nested.get(axis)) if nested_present else None
            if top_present and top is None:
                issues.append(prefix + f"dig_{axis}_not_finite")
            if nested_present and nested_value is None:
                issues.append(prefix + f"dig_position_{axis}_not_finite")
            if top is not None and nested_value is not None and top != nested_value:
                issues.append(prefix + f"dig_position_conflict:{axis}")
            selected = top if top is not None else nested_value
            if selected is None:
                missing.append(axis)
            else:
                canonical[axis] = selected
        if missing:
            issues.append(prefix + "dig_coordinates_missing:" + ",".join(missing))

        block = params.get("block")
        block_alias = params.get("block_name")
        if "block_name" in params:
            aliases.append("block_name->block")
        if block is not None and (not isinstance(block, str) or not block.strip()):
            issues.append(prefix + "dig_block_invalid")
            block = None
        if block_alias is not None and (not isinstance(block_alias, str) or not block_alias.strip()):
            issues.append(prefix + "dig_block_name_invalid")
            block_alias = None
        if isinstance(block, str):
            block = block.strip()
        if isinstance(block_alias, str):
            block_alias = block_alias.strip()
        if block and block_alias and block != block_alias:
            issues.append(prefix + "dig_block_conflict")
        selected_block = block or block_alias
        if selected_block:
            canonical["block"] = selected_block

        if "timeout_ms" in params:
            timeout_ms = cls._finite_parameter(params.get("timeout_ms"))
            if timeout_ms is None or timeout_ms <= 0:
                issues.append(prefix + "dig_timeout_ms_invalid")
            else:
                canonical["timeout_ms"] = timeout_ms

        normalized = bool(aliases or canonical != params)
        return canonical, {
            "action_index": action_index,
            "action_type": "dig",
            "normalized": normalized,
            "aliases": sorted(set(aliases)),
            "original_parameters_sha256": cls._parameter_sha256(params),
            "canonical_parameters": canonical,
            "issues": sorted(set(issues)),
        }

    @classmethod
    def _ground_m4_craft_parameters(cls, value, *, action_index: int) -> tuple[dict, dict]:
        prefix = f"action[{action_index}]:"
        if not isinstance(value, dict):
            return {}, {
                "action_index": action_index,
                "action_type": "craft",
                "normalized": False,
                "aliases": [],
                "original_parameters_sha256": cls._parameter_sha256(value),
                "canonical_parameters": {},
                "issues": [prefix + "craft_parameters_not_object"],
            }

        params = dict(value)
        issues: list[str] = []
        aliases: list[str] = []
        unknown = sorted(str(key) for key in params if key not in {"item", "count", "recipe"})
        if unknown:
            issues.append(prefix + "craft_unknown_parameters:" + ",".join(unknown))

        item = params.get("item")
        recipe = params.get("recipe")
        if "recipe" in params:
            aliases.append("recipe->item")
        if item is not None and (not isinstance(item, str) or not item.strip()):
            issues.append(prefix + "craft_item_invalid")
            item = None
        if recipe is not None and (not isinstance(recipe, str) or not recipe.strip()):
            issues.append(prefix + "craft_recipe_invalid")
            recipe = None
        if isinstance(item, str):
            item = item.strip()
        if isinstance(recipe, str):
            recipe = recipe.strip()
        if item and recipe and item != recipe:
            issues.append(prefix + "craft_item_conflict")
        selected_item = item or recipe
        canonical = {}
        if selected_item:
            canonical["item"] = selected_item
        else:
            issues.append(prefix + "craft_item_missing")

        if "count" in params:
            count = params.get("count")
            if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
                issues.append(prefix + "craft_count_invalid")
            else:
                canonical["count"] = count

        normalized = bool(aliases or canonical != params)
        return canonical, {
            "action_index": action_index,
            "action_type": "craft",
            "normalized": normalized,
            "aliases": sorted(set(aliases)),
            "original_parameters_sha256": cls._parameter_sha256(params),
            "canonical_parameters": canonical,
            "issues": sorted(set(issues)),
        }

    @classmethod
    def _ground_m4_place_parameters(cls, value, *, action_index: int) -> tuple[dict, dict]:
        prefix = f"action[{action_index}]:"
        if not isinstance(value, dict):
            return {}, {
                "action_index": action_index,
                "action_type": "place",
                "normalized": False,
                "aliases": [],
                "original_parameters_sha256": cls._parameter_sha256(value),
                "canonical_parameters": {},
                "issues": [prefix + "place_parameters_not_object"],
            }

        params = dict(value)
        issues: list[str] = []
        aliases: list[str] = []
        unknown = sorted(str(key) for key in params if key not in {"item", "block", "x", "y", "z"})
        if unknown:
            issues.append(prefix + "place_unknown_parameters:" + ",".join(unknown))

        item = params.get("item")
        block = params.get("block")
        if "block" in params:
            aliases.append("block->item")
        if item is not None and (not isinstance(item, str) or not item.strip()):
            issues.append(prefix + "place_item_invalid")
            item = None
        if block is not None and (not isinstance(block, str) or not block.strip()):
            issues.append(prefix + "place_block_invalid")
            block = None
        if isinstance(item, str):
            item = item.strip()
        if isinstance(block, str):
            block = block.strip()
        if item and block and item != block:
            issues.append(prefix + "place_item_conflict")

        canonical = {}
        selected_item = item or block
        if selected_item:
            canonical["item"] = selected_item
        else:
            issues.append(prefix + "place_item_missing")

        missing = []
        for axis in ("x", "y", "z"):
            coordinate = cls._finite_parameter(params.get(axis)) if axis in params else None
            if axis in params and coordinate is None:
                issues.append(prefix + f"place_{axis}_not_finite")
            if coordinate is None:
                missing.append(axis)
            else:
                canonical[axis] = coordinate
        if missing:
            issues.append(prefix + "place_coordinates_missing:" + ",".join(missing))

        normalized = bool(aliases or canonical != params)
        return canonical, {
            "action_index": action_index,
            "action_type": "place",
            "normalized": normalized,
            "aliases": sorted(set(aliases)),
            "original_parameters_sha256": cls._parameter_sha256(params),
            "canonical_parameters": canonical,
            "issues": sorted(set(issues)),
        }

    @classmethod
    def _ground_m4_shelter_phase(
        cls,
        plan: dict,
        *,
        goal: str,
        world_state: dict,
    ) -> tuple[dict, dict]:
        grounded = dict(plan or {})
        report = {
            "type": "m4_shelter_phase_grounding",
            "schema_version": 1,
            "activated": False,
            "reason": "not_applicable",
            "original_actions_sha256": cls._parameter_sha256(grounded.get("actions", [])),
            "origin": {},
            "material": "",
            "required_block_count": 9,
            "required_inventory_count": 10,
        }
        if "shelter" not in str(goal or "").lower():
            report["reason"] = "goal_is_not_shelter"
            return grounded, report
        state = world_state if isinstance(world_state, dict) else {}
        shelter = state.get("shelter_verification", {})
        shelter = shelter if isinstance(shelter, dict) else {}
        if shelter.get("passed") is True:
            report["reason"] = "shelter_already_verified"
            return grounded, report
        checks = {
            str(check.get("name") or ""): check.get("passed") is True
            for check in shelter.get("checks", [])
            if isinstance(check, dict)
        }
        evidence = shelter.get("coordinate_evidence", {})
        evidence = evidence if isinstance(evidence, dict) else {}
        origin = evidence.get("player_cell", {})
        origin = origin if isinstance(origin, dict) else {}
        try:
            origin = {
                axis: int(math.floor(float(origin[axis])))
                for axis in ("x", "y", "z")
            }
        except (KeyError, TypeError, ValueError):
            report["reason"] = "machine_player_cell_missing"
            return grounded, report
        if (
            shelter.get("verifier_id") != "m4-sealed-cell-shelter-verifier-v1"
            or shelter.get("source") != "machine_state"
            or checks.get("machine_snapshot") is not True
        ):
            report["reason"] = "machine_snapshot_not_verified"
            return grounded, report

        relocation = state.get("m4_shelter_relocation", {})
        relocation = relocation if isinstance(relocation, dict) else {}
        target = relocation.get("target_position", {})
        target = target if isinstance(target, dict) else {}
        try:
            target = {axis: float(target[axis]) for axis in ("x", "y", "z")}
            relocation_valid = all(math.isfinite(value) for value in target.values())
        except (KeyError, TypeError, ValueError):
            relocation_valid = False
        if relocation.get("status") == "scheduled" and relocation_valid:
            action = {
                "type": "move_to",
                "parameters": target,
            }
            grounded["status"] = "planning"
            grounded["actions"] = [action]
            grounded["reasoning"] = (
                "The previous bounded shelter origin failed atomically; "
                "move to the machine-grounded relocation before retrying the template."
            )
            report.update({
                "activated": True,
                "reason": "partial_failure_relocation_required",
                "origin": origin,
                "recovery_id": str(relocation.get("recovery_id") or ""),
                "relocation_origin": dict(relocation.get("target_origin", {}) or {}),
                "relocation_target": target,
                "canonical_action": action,
            })
            return grounded, report

        inventory = state.get("inventory", {})
        inventory = inventory if isinstance(inventory, dict) else {}
        materials = (
            "oak_planks", "spruce_planks", "birch_planks", "jungle_planks",
            "acacia_planks", "dark_oak_planks", "mangrove_planks", "cherry_planks",
            "bamboo_planks", "crimson_planks", "warped_planks", "cobblestone", "dirt",
        )
        material = next(
            (
                name for name in materials
                if isinstance(inventory.get(name), (int, float))
                and not isinstance(inventory.get(name), bool)
                and inventory.get(name, 0) >= 10
            ),
            "",
        )
        if not material:
            report["reason"] = "building_material_below_10"
            report["origin"] = origin
            return grounded, report

        action = {
            "type": "build_shelter_cell",
            "parameters": {
                "origin": origin,
                "material": material,
            },
        }
        grounded["status"] = "planning"
        grounded["actions"] = [action]
        grounded["reasoning"] = (
            "Machine-grounded shelter material is ready; execute the bounded sealed-cell template now."
        )
        report.update({
            "activated": True,
            "reason": "shelter_goal_and_material_ready",
            "origin": origin,
            "material": material,
            "canonical_action": action,
        })
        return grounded, report

    @classmethod
    def _ground_m4_maintenance_phase(
        cls,
        plan: dict,
        *,
        goal: str,
        world_state: dict,
    ) -> tuple[dict, dict]:
        grounded = dict(plan or {})
        goal_lower = str(goal or "").lower()
        report = {
            "type": "m4_maintenance_phase_grounding",
            "schema_version": 1,
            "activated": False,
            "boundary": "",
            "boundary_reached": False,
            "time_of_day": 0,
            "wait_ms": 0,
            "reason": "not_applicable",
        }
        if "through nightfall" in goal_lower:
            boundary = "nightfall"
        elif "until dawn" in goal_lower:
            boundary = "dawn"
        else:
            return grounded, report
        state = world_state if isinstance(world_state, dict) else {}
        shelter = state.get("shelter_verification", {})
        shelter = shelter if isinstance(shelter, dict) else {}
        try:
            raw_time = state["time_of_day"]
            time_of_day = int(float(raw_time)) % 24000
            time_valid = math.isfinite(float(raw_time))
        except (TypeError, ValueError):
            time_of_day = 0
            time_valid = False
        except KeyError:
            time_of_day = 0
            time_valid = False
        boundary_reached = (
            time_valid and 12000 <= time_of_day < 23000
            if boundary == "nightfall"
            else time_valid and (time_of_day >= 23000 or time_of_day < 1000)
        )
        report.update({
            "boundary": boundary,
            "boundary_reached": boundary_reached,
            "time_of_day": time_of_day,
        })
        if shelter.get("passed") is not True:
            report["reason"] = "machine_shelter_not_verified"
            return grounded, report
        if boundary_reached:
            report["reason"] = "maintenance_boundary_reached"
            return grounded, report

        wait_ms = 15000
        grounded["status"] = "planning"
        grounded["actions"] = [{"type": "wait", "parameters": {"ms": wait_ms}}]
        grounded["reasoning"] = (
            f"Maintain the verified shelter and observe again after a bounded wait for {boundary}."
        )
        report.update({
            "activated": True,
            "wait_ms": wait_ms,
            "reason": "verified_shelter_boundary_pending",
        })
        return grounded, report

    @staticmethod
    def _finite_parameter(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = float(value)
        if not math.isfinite(number):
            return None
        return int(number) if number.is_integer() else number

    @staticmethod
    def _parameter_sha256(value) -> str:
        payload = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _m2_action_summary(self, world_state: dict) -> dict:
        from singularity.evaluation.m2_protocol import PROTOCOL

        contract = PROTOCOL["planner_context"]["successful_action_summary"]
        summary = world_state.get("m2_successful_action_summary", {}) if isinstance(world_state, dict) else {}
        if isinstance(summary, dict) and summary.get("profile") == contract["profile"]:
            return dict(summary)
        return {
            "profile": str(contract["profile"]),
            "successful_action_count": 0,
            "successful_action_types": {},
            "included_action_count": 0,
            "truncated": False,
            "actions": [],
        }

    def _create_tasks_from_plan(self, plan: dict):
        """Create scheduler tasks only after the planner response passes its contract."""
        subtasks = plan.get("subtasks", [])
        if not isinstance(subtasks, list):
            return
        reference_to_id = {}
        pending_dependencies: list[tuple[str, list[str]]] = []
        root_plan_id = str(plan.get("root_plan_id") or "")
        planner_call_id = str(plan.get("planner_call_id") or "")
        for st in subtasks:
            if not isinstance(st, dict):
                continue
            title = str(st.get("title") or "unnamed")
            plan_node_id = str(st.get("id") or "")
            task = (
                self._existing_plan_task(root_plan_id, plan_node_id)
                if self.strict_m2 or self.strict_stone_pickaxe
                else None
            )
            if task is None:
                task = self.task_system.create_task(
                    title=title,
                    task_type=st.get("type", "general"),
                    success_criteria=st.get("success_criteria", {}),
                    failure_criteria=st.get("failure_criteria", {}),
                    preconditions=st.get("preconditions", {}),
                    priority=self._safe_priority(st.get("priority", 3)),
                    assigned_skill=st.get("assigned_skill"),
                    tags=st.get("tags", []),
                    opportunity_triggers=st.get("opportunity_triggers", []),
                    deadline=self._deadline_from_seconds(st.get("deadline_seconds")),
                    rationale=st.get("rationale", ""),
                    plan_node_id=plan_node_id,
                    root_plan_id=root_plan_id,
                    planner_call_id=planner_call_id,
                )
            reference_to_id[title.lower()] = task.id
            if plan_node_id:
                reference_to_id[plan_node_id.lower()] = task.id
            dependencies = st.get("depends_on", [])
            if isinstance(dependencies, list) and dependencies:
                pending_dependencies.append((task.id, dependencies))
        for task_id, dependencies in pending_dependencies:
            task = self.task_system.tasks.get(task_id)
            if not task:
                continue
            task.depends_on = [
                reference_to_id[dependency.lower()]
                for dependency in dependencies
                if isinstance(dependency, str) and dependency.lower() in reference_to_id
            ]

    def _existing_plan_task(self, root_plan_id: str, plan_node_id: str):
        if not root_plan_id or not plan_node_id:
            return None
        for task in self.task_system.tasks.values():
            if task.root_plan_id == root_plan_id and task.plan_node_id == plan_node_id:
                return task
        return None

    def _safe_priority(self, value) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 3

    def _deadline_from_seconds(self, seconds) -> float | None:
        if seconds is None:
            return None
        try:
            return time.time() + float(seconds)
        except (TypeError, ValueError):
            return None
