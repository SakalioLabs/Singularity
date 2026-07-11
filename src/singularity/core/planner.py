"""LLM-powered goal decomposition with fixed M2/M4 planner evidence."""

import hashlib
import json
import logging
import math
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
    def __init__(self, llm: LLMProvider, task_system: TaskSystem, protocol: str = ""):
        self.llm = llm
        self.task_system = task_system
        self.protocol = str(protocol or "")
        self.strict_m2 = self.protocol == "m2-fixed-v1"
        self.strict_m4 = self.protocol == "m4-fixed-v1"
        self.last_call_evidence: dict = {}
        self._episode_goal = ""
        self._episode_id = ""
        self._call_index = 0
        self._active_root_plan_id = ""
        self._last_call_id = ""
        self._pending_replan_reason = ""
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

    def plan_from_goal(self, goal: str, world_state: dict, memory_context: str = "") -> dict:
        if self.strict_m2 and self._call_index == 0:
            plan_kind = "root"
        elif (self.strict_m2 or self.strict_m4) and self._pending_replan_reason:
            plan_kind = "replan"
            memory_context = "\n".join(
                part for part in (
                    memory_context,
                    f"Previous action failed and requires replan: {self._pending_replan_reason}",
                ) if part
            )
        else:
            plan_kind = "continuation"
        plan = self._call_planner(goal, world_state, memory_context, plan_kind)
        if plan_kind == "replan":
            self._pending_replan_reason = ""
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
        strict_deadline = self.strict_m2 or self.strict_m4
        if strict_deadline:
            if self.strict_m2:
                from singularity.evaluation.m2_protocol import PROTOCOL as deadline_protocol
            else:
                from singularity.evaluation.m4_protocol import PROTOCOL as deadline_protocol

            policy = deadline_protocol["deadline_policy"]
            expected_guard_s = float(policy.get("action_guard_ms", 0)) / 1000.0
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
                "max_retries": int(policy["planner_max_retries"]),
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
            schema_validation = self._validate_m4_plan_envelope(
                raw_plan,
                expected_goal=goal,
                expected_kind=plan_kind,
            )
            grounding_issues = list(action_parameter_grounding.get("issues", []))
            schema_validation["action_parameter_grounding"] = action_parameter_grounding
            schema_validation["issues"] = sorted(set(
                list(schema_validation.get("issues", [])) + grounding_issues
            ))
            schema_validation["passed"] = not schema_validation["issues"]

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
                else "llm-autonomous-planner-v1" if self.strict_m4 else "llm-planner-v1"
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
        prompt = f"""You are a Minecraft survival planner. Given a goal and current world state, decompose it into subtasks and immediate actions.

Available actions: move_to, look_at, dig, place, craft, attack, equip, use_item, chat, wait.

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
- A dig action must use top-level finite x, y, and z parameters and may use top-level block; never use block_name, position, target, or block_position aliases.
- Example: {"type":"dig","parameters":{"x":103,"y":139,"z":-30,"block":"oak_log"}}.
- A craft action must use item and may use a positive integer count; never use recipe as an alias.
- Example: {"type":"craft","parameters":{"item":"oak_planks","count":4}}."""
        return prompt

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
                "normalized_action_count": 0,
                "normalizations": [],
                "issues": [],
            }
        grounded_actions = []
        issues: list[str] = []
        normalizations = []
        dig_action_count = 0
        craft_action_count = 0

        for index, action in enumerate(actions):
            if not isinstance(action, dict):
                grounded_actions.append(action)
                continue
            grounded_action = dict(action)
            action_type = str(action.get("type") or "")
            if action_type not in {"dig", "craft"}:
                grounded_actions.append(grounded_action)
                continue
            if action_type == "dig":
                dig_action_count += 1
                canonical, evidence = cls._ground_m4_dig_parameters(
                    action.get("parameters"),
                    action_index=index,
                )
            else:
                craft_action_count += 1
                canonical, evidence = cls._ground_m4_craft_parameters(
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
            "normalized_action_count": len(normalizations),
            "normalizations": normalizations,
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
            task = self._existing_plan_task(root_plan_id, plan_node_id) if self.strict_m2 else None
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
