"""Session logger — structured JSON logging for all agent sessions."""
import json
import os
import time
import uuid
import logging
from typing import Optional

logger = logging.getLogger("singularity.session")


class SessionLogger:
    """Records all observations, actions, plans, and reflections as structured JSON."""

    def __init__(self, log_dir: str = "logs", session_id: Optional[str] = None):
        self.log_dir = log_dir
        self.session_id = session_id or str(uuid.uuid4())[:12]
        self.start_time = time.time()
        self.events: list[dict] = []
        os.makedirs(log_dir, exist_ok=True)
        self._log_path = os.path.join(log_dir, f"session_{self.session_id}.jsonl")
        logger.info(f"Session {self.session_id} logging to {self._log_path}")

    def log(self, event_type: str, data: dict, level: str = "INFO"):
        """Append one structured event to the session log."""
        entry = {
            "ts": time.time(),
            "elapsed_s": round(time.time() - self.start_time, 2),
            "session": self.session_id,
            "type": event_type,
            "level": level,
            "data": data,
        }
        self.events.append(entry)
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.error(f"Failed to write session log: {e}")

    def log_observation(self, observation: dict):
        self.log("observation", observation)

    def log_plan(self, plan: dict):
        self.log("plan", plan)

    def log_action(
        self,
        action: dict,
        result: dict,
        pre_observation: dict = None,
        post_observation: dict = None,
        context: dict = None,
    ):
        payload = {"action": action, "result": result}
        if pre_observation:
            payload["pre_observation"] = pre_observation
        if post_observation:
            payload["post_observation"] = post_observation
        if context:
            payload["action_context"] = context
        self.log("action", payload)

    def log_reflection(self, reflection: dict):
        self.log("reflection", reflection)

    def log_error(self, error: str, context: dict = None):
        self.log("error", {"error": error, "context": context or {}}, level="ERROR")

    def log_goal_start(self, goal: str):
        self.log("goal_start", {"goal": goal})

    def log_goal_end(self, goal: str, result: dict):
        self.log("goal_end", {"goal": goal, "result": result})

    def log_connect(self, host: str, port: int, success: bool):
        self.log("connect", {"host": host, "port": port, "success": success})

    def get_summary(self) -> dict:
        """Return a summary of the session."""
        elapsed = time.time() - self.start_time
        action_count = sum(1 for e in self.events if e["type"] == "action")
        error_count = sum(1 for e in self.events if e["type"] == "error")
        intervention_metrics = self._intervention_metrics()
        visual_action_metrics = self._visual_action_metrics()
        intervention_metrics.update(visual_action_metrics)
        skill_memory_metrics = self._skill_memory_metrics()
        intervention_metrics.update(skill_memory_metrics)
        action_verification_metrics = self._action_verification_metrics()
        intervention_metrics.update(action_verification_metrics)
        action_candidate_metrics = self._action_candidate_selection_metrics()
        intervention_metrics.update(action_candidate_metrics)
        goal_verification_metrics = self._goal_verification_metrics()
        plan_cache_metrics = self._plan_cache_metrics()
        episode_abort_metrics = self._episode_abort_metrics()
        frontier_budget_metrics = self._frontier_budget_metrics()
        memory_policy_metrics = self._memory_policy_metrics()
        return {
            "session_id": self.session_id,
            "duration_s": round(elapsed, 2),
            "total_events": len(self.events),
            "action_count": action_count,
            "error_count": error_count,
            "intervention_metrics": intervention_metrics,
            "visual_action_metrics": visual_action_metrics,
            "skill_memory_metrics": skill_memory_metrics,
            "action_verification_metrics": action_verification_metrics,
            "action_candidate_selection_metrics": action_candidate_metrics,
            "goal_verification_metrics": goal_verification_metrics,
            "plan_cache_metrics": plan_cache_metrics,
            "episode_abort_metrics": episode_abort_metrics,
            "frontier_budget_metrics": frontier_budget_metrics,
            "memory_policy_metrics": memory_policy_metrics,
            "log_path": self._log_path,
        }

    def _plan_cache_metrics(self) -> dict:
        hits = [event for event in self.events if event.get("type") == "plan_cache_hit"]
        hybrid_hints = [event for event in self.events if event.get("type") == "plan_cache_hybrid_hint"]
        misses = [event for event in self.events if event.get("type") == "plan_cache_miss"]
        signatures = [event for event in self.events if event.get("type") == "plan_cache_signature"]
        hit_entries = {}
        hit_goals = set()
        stage_counts = {"hybrid": len(hybrid_hints), "deterministic": len(hits)}
        for event in hits + hybrid_hints:
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            entry_id = str(data.get("entry_id") or "unknown")
            hit_entries[entry_id] = hit_entries.get(entry_id, 0) + 1
            if data.get("goal"):
                hit_goals.add(str(data["goal"]))
        intervention_count = len(hits) + len(hybrid_hints)
        total = intervention_count + len(misses)
        return {
            "plan_cache_hit_count": len(hits),
            "plan_cache_hybrid_hint_count": len(hybrid_hints),
            "plan_cache_workflow_intervention_count": intervention_count,
            "plan_cache_miss_count": len(misses),
            "plan_cache_signature_count": len(signatures),
            "plan_cache_hit_rate": round(intervention_count / total, 3) if total else 0.0,
            "plan_cache_hit_entries": hit_entries,
            "plan_cache_hit_goals": sorted(hit_goals),
            "plan_cache_execution_stage_counts": stage_counts,
        }

    def _episode_abort_metrics(self) -> dict:
        gates = [event for event in self.events if event.get("type") == "episode_abort_runtime_gate"]
        probes = [event for event in self.events if event.get("type") == "episode_viability_probe"]
        triggers = [event for event in self.events if event.get("type") == "episode_early_abort"]
        active_count = 0
        shadow_count = 0
        round_counts = {}
        scores = []
        for event in probes:
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            try:
                scores.append(float(data.get("score") or 0.0))
            except (TypeError, ValueError):
                pass
            round_key = str(data.get("round") or "unknown")
            round_counts[round_key] = round_counts.get(round_key, 0) + 1
        for event in triggers:
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            if data.get("active_abort") is True:
                active_count += 1
            elif data.get("would_abort") is True:
                shadow_count += 1
        latest_gate = gates[-1].get("data", {}) if gates and isinstance(gates[-1].get("data", {}), dict) else {}
        return {
            "runtime_gate_event_count": len(gates),
            "requested_mode": str(latest_gate.get("requested_mode") or "off"),
            "effective_mode": str(latest_gate.get("effective_mode") or "off"),
            "gate_readiness": str(latest_gate.get("gate_readiness") or "not_configured"),
            "viability_probe_count": len(probes),
            "early_abort_trigger_count": len(triggers),
            "active_early_abort_count": active_count,
            "shadow_would_abort_count": shadow_count,
            "probe_round_counts": round_counts,
            "average_viability_risk_score": round(sum(scores) / len(scores), 6) if scores else 0.0,
        }

    def _frontier_budget_metrics(self) -> dict:
        gates = [event for event in self.events if event.get("type") == "frontier_budget_runtime_gate"]
        allocations = [event for event in self.events if event.get("type") == "frontier_budget_allocation"]
        contexts = [event for event in self.events if event.get("type") == "frontier_budget_planner_context"]
        outcomes = [event for event in self.events if event.get("type") == "frontier_budget_outcome"]
        credits = [event for event in self.events if event.get("type") == "frontier_budget_recovery_credit"]
        policy_counts = {}
        allocation_pool = 0
        allocated_rounds = 0
        conservation_failure_count = 0
        for event in allocations:
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            policy = str(data.get("policy") or "unknown")
            policy_counts[policy] = policy_counts.get(policy, 0) + 1
            ledger = data.get("ledger", {}) if isinstance(data.get("ledger", {}), dict) else {}
            allocation_pool += int(ledger.get("allocation_pool_rounds", 0) or 0)
            allocated_rounds += int(ledger.get("allocated_rounds", 0) or 0)
            if ledger.get("conservation_valid") is not True:
                conservation_failure_count += 1
        recovered_rounds = 0
        for event in credits:
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            recovered_rounds += int(data.get("saved_planner_rounds", 0) or 0)
        consumed_recovered = 0
        completed = 0
        for event in outcomes:
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            consumed_recovered += int(data.get("reallocated_rounds_consumed", 0) or 0)
            if data.get("goal_completed") is True:
                completed += 1
        latest_gate = gates[-1].get("data", {}) if gates and isinstance(gates[-1].get("data", {}), dict) else {}
        return {
            "runtime_gate_event_count": len(gates),
            "requested_mode": str(latest_gate.get("requested_mode") or "off"),
            "effective_mode": str(latest_gate.get("effective_mode") or "off"),
            "policy": str(latest_gate.get("policy") or "information"),
            "allocation_event_count": len(allocations),
            "planner_context_event_count": len(contexts),
            "outcome_event_count": len(outcomes),
            "completed_outcome_count": completed,
            "recovery_credit_event_count": len(credits),
            "recovered_rounds": recovered_rounds,
            "reallocated_rounds_consumed": consumed_recovered,
            "allocation_pool_rounds": allocation_pool,
            "allocated_rounds": allocated_rounds,
            "budget_conservation_failure_count": conservation_failure_count,
            "policy_counts": policy_counts,
        }

    def _memory_policy_metrics(self) -> dict:
        writes = [event for event in self.events if event.get("type") == "memory_write"]
        reads = [event for event in self.events if event.get("type") == "memory_read"]
        manages = [event for event in self.events if event.get("type") in {"memory_manage", "memory_consolidation"}]
        write_layers = {}
        write_types = {}
        read_types = {}
        manage_operations = {}
        policy_decisions = {}
        read_filter_event_count = 0
        read_filtered_entries = 0
        read_filter_reasons = {}
        memory_trace_event_count = 0
        weighted_memory_read_count = 0
        weighted_memory_match_count = 0
        weighted_transfer_match_count = 0
        memory_attribution_policy_counts = {}

        for event in writes + reads + manages:
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            decision = data.get("policy_decision", {}) if isinstance(data.get("policy_decision", {}), dict) else {}
            decision_name = str(decision.get("decision") or "")
            if decision_name:
                policy_decisions[decision_name] = policy_decisions.get(decision_name, 0) + 1

        for event in writes:
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            layer = str(data.get("layer") or "unknown")
            memory_type = str(data.get("memory_type") or "unknown")
            write_layers[layer] = write_layers.get(layer, 0) + 1
            write_types[memory_type] = write_types.get(memory_type, 0) + 1

        for event in reads:
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            memory_type = str(data.get("memory_type") or "unknown")
            read_types[memory_type] = read_types.get(memory_type, 0) + 1
            retrieval_trace = data.get("retrieval_trace", {}) if isinstance(data.get("retrieval_trace", {}), dict) else {}
            if retrieval_trace:
                memory_trace_event_count += 1
                if retrieval_trace.get("weighted_retrieval_enabled"):
                    weighted_memory_read_count += 1
                try:
                    weighted_memory_match_count += int(retrieval_trace.get("weighted_memory_match_count") or 0)
                except (TypeError, ValueError):
                    pass
                try:
                    weighted_transfer_match_count += int(retrieval_trace.get("weighted_transfer_match_count") or 0)
                except (TypeError, ValueError):
                    pass
                policies = retrieval_trace.get("attribution_policy_counts", {})
                if isinstance(policies, dict):
                    for policy, count in policies.items():
                        policy = str(policy or "unknown")
                        try:
                            amount = int(count)
                        except (TypeError, ValueError):
                            amount = 1
                        memory_attribution_policy_counts[policy] = memory_attribution_policy_counts.get(policy, 0) + amount
            filter_report = data.get("read_filter_report", {}) if isinstance(data.get("read_filter_report", {}), dict) else {}
            if filter_report:
                read_filter_event_count += 1
                read_filtered_entries += int(filter_report.get("filtered_entries") or 0)
                reasons = filter_report.get("filter_reasons", {})
                if isinstance(reasons, dict):
                    for reason, count in reasons.items():
                        reason = str(reason or "unknown")
                        try:
                            amount = int(count)
                        except (TypeError, ValueError):
                            amount = 1
                        read_filter_reasons[reason] = read_filter_reasons.get(reason, 0) + amount

        for event in manages:
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            operation = str(data.get("operation") or event.get("type") or "unknown")
            manage_operations[operation] = manage_operations.get(operation, 0) + 1

        return {
            "memory_write_count": len(writes),
            "memory_read_count": len(reads),
            "memory_manage_count": len(manages),
            "memory_write_layers": write_layers,
            "memory_write_types": write_types,
            "memory_read_types": read_types,
            "memory_manage_operations": manage_operations,
            "memory_policy_decisions": policy_decisions,
            "memory_read_filter_event_count": read_filter_event_count,
            "memory_read_filtered_entries": read_filtered_entries,
            "memory_read_filter_reasons": read_filter_reasons,
            "memory_retrieval_trace_event_count": memory_trace_event_count,
            "weighted_memory_read_count": weighted_memory_read_count,
            "weighted_memory_match_count": weighted_memory_match_count,
            "weighted_transfer_match_count": weighted_transfer_match_count,
            "memory_attribution_policy_counts": memory_attribution_policy_counts,
        }

    def _intervention_metrics(self) -> dict:
        hints = [event for event in self.events if event.get("type") == "policy_hint"]
        interventions = [
            event for event in self.events
            if event.get("type") in {"policy_intervention", "failure_correction_selected", "failure_correction_action", "failure_correction_completed", "failure_correction_failed"}
        ]
        phases = []
        skills = set()
        for event in interventions:
            event_type = event.get("type")
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            phase = data.get("phase")
            if not phase:
                phase = {
                    "failure_correction_selected": "selected",
                    "failure_correction_action": "action",
                    "failure_correction_completed": "completed",
                    "failure_correction_failed": "failed",
                }.get(event_type, "")
            if phase:
                phases.append(phase)
            if data.get("skill"):
                skills.add(str(data["skill"]))
            for hint in data.get("hints", []):
                if isinstance(hint, str) and ":" in hint:
                    skills.add(hint.split(":", 1)[0])

        completed = phases.count("completed")
        failed = phases.count("failed")
        attempts = phases.count("selected")
        action_steps = phases.count("action")
        denominator = completed + failed
        return {
            "policy_hint_count": len(hints),
            "policy_intervention_count": attempts,
            "policy_intervention_actions": action_steps,
            "policy_intervention_successes": completed,
            "policy_intervention_failures": failed,
            "policy_intervention_success_rate": round(completed / denominator, 3) if denominator else 0.0,
            "policy_intervention_skills": sorted(skills),
        }

    def _skill_memory_metrics(self) -> dict:
        events = [
            event for event in self.events
            if event.get("type") == "skill_memory_hint"
        ]
        task_families = {}
        total_hints = 0
        for event in events:
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            family = str(data.get("task_family") or "unknown")
            task_families[family] = task_families.get(family, 0) + 1
            try:
                total_hints += int(data.get("hint_count") or 0)
            except (TypeError, ValueError):
                hints = data.get("hints", [])
                total_hints += len(hints) if isinstance(hints, list) else 0
        return {
            "skill_memory_hint_event_count": len(events),
            "skill_memory_hint_count": total_hints,
            "skill_memory_task_families": task_families,
        }

    def _action_verification_metrics(self) -> dict:
        events = [event for event in self.events if event.get("type") == "action_verification"]
        statuses = {}
        action_types = {}
        blocked = 0
        for event in events:
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            verification = data.get("verification", {}) if isinstance(data.get("verification", {}), dict) else {}
            action = data.get("action", {}) if isinstance(data.get("action", {}), dict) else {}
            status = str(verification.get("status") or "unknown")
            statuses[status] = statuses.get(status, 0) + 1
            action_type = str(verification.get("action_type") or action.get("type") or "unknown")
            action_types[action_type] = action_types.get(action_type, 0) + 1
            if status == "reject":
                blocked += 1
        return {
            "action_verification_event_count": len(events),
            "action_verification_status_counts": statuses,
            "action_verification_action_types": action_types,
            "action_verification_blocked_count": blocked,
        }

    def _action_candidate_selection_metrics(self) -> dict:
        events = [event for event in self.events if event.get("type") == "action_candidate_selection"]
        selected_types = {}
        repaired_rejects = 0
        for event in events:
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            selection = data.get("selection", {}) if isinstance(data.get("selection", {}), dict) else {}
            selected = selection.get("selected_action", {}) if isinstance(selection.get("selected_action", {}), dict) else {}
            selected_type = str(selected.get("type") or "unknown")
            selected_types[selected_type] = selected_types.get(selected_type, 0) + 1
            original_verification = selection.get("original_verification", {}) if isinstance(selection.get("original_verification", {}), dict) else {}
            selected_verification = selection.get("selected_verification", {}) if isinstance(selection.get("selected_verification", {}), dict) else {}
            original_status = str(original_verification.get("status") or "")
            selected_status = str(selected_verification.get("status") or "")
            if original_status == "reject" and selected_status != "reject":
                repaired_rejects += 1
        return {
            "action_candidate_selection_event_count": len(events),
            "action_candidate_selection_repaired_reject_count": repaired_rejects,
            "action_candidate_selection_selected_types": selected_types,
        }

    def _visual_action_metrics(self) -> dict:
        suggestion_events = [
            event for event in self.events
            if event.get("type") == "visual_action_suggestion"
        ]
        intervention_events = [
            event for event in self.events
            if event.get("type") == "visual_action_intervention"
        ]
        suggestion_kinds = {}
        intervention_kinds = {}
        intervention_phases = {}
        action_types = {}
        goals = set()
        suggestion_count = 0

        for event in suggestion_events:
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            if data.get("goal"):
                goals.add(str(data["goal"]))
            suggestions = data.get("suggestions", [])
            if not isinstance(suggestions, list):
                continue
            suggestion_count += len(suggestions)
            for suggestion in suggestions:
                if not isinstance(suggestion, dict):
                    continue
                kind = str(suggestion.get("kind", "unknown"))
                suggestion_kinds[kind] = suggestion_kinds.get(kind, 0) + 1
                action_type = suggestion.get("action", {}).get("type") if isinstance(suggestion.get("action", {}), dict) else ""
                if action_type:
                    action_types[str(action_type)] = action_types.get(str(action_type), 0) + 1

        for event in intervention_events:
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            if data.get("goal"):
                goals.add(str(data["goal"]))
            phase = str(data.get("phase", "unknown"))
            intervention_phases[phase] = intervention_phases.get(phase, 0) + 1
            suggestion = data.get("suggestion", {}) if isinstance(data.get("suggestion", {}), dict) else {}
            kind = str(suggestion.get("kind", "unknown"))
            intervention_kinds[kind] = intervention_kinds.get(kind, 0) + 1
            action = suggestion.get("action", {}) if isinstance(suggestion.get("action", {}), dict) else {}
            action_type = action.get("type")
            if action_type:
                action_types[str(action_type)] = action_types.get(str(action_type), 0) + 1

        return {
            "visual_action_suggestion_event_count": len(suggestion_events),
            "visual_action_suggestion_count": suggestion_count,
            "visual_action_intervention_count": len(intervention_events),
            "visual_action_suggestion_kinds": suggestion_kinds,
            "visual_action_intervention_kinds": intervention_kinds,
            "visual_action_intervention_phases": intervention_phases,
            "visual_action_action_types": action_types,
            "visual_action_goals": sorted(goals),
        }

    def _goal_verification_metrics(self) -> dict:
        events = [event for event in self.events if event.get("type") == "goal_verification"]
        accepted = 0
        rejected = 0
        reasons = {}
        data_by_event = []
        for event in events:
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            data_by_event.append(data)
            context = data.get("context", {}) if isinstance(data.get("context", {}), dict) else {}
            if context.get("accepted") is True:
                accepted += 1
            elif context.get("accepted") is False:
                rejected += 1
            reason = context.get("acceptance_reason")
            if reason:
                reasons[reason] = reasons.get(reason, 0) + 1
        return {
            "count": len(events),
            "achieved": sum(1 for data in data_by_event if data.get("achieved")),
            "failed": sum(1 for data in data_by_event if data.get("status") == "failed"),
            "unknown": sum(1 for data in data_by_event if data.get("status") == "unknown"),
            "accepted": accepted,
            "rejected": rejected,
            "acceptance_reasons": reasons,
        }

    def close(self):
        """Write session summary."""
        summary = self.get_summary()
        summary_path = os.path.join(self.log_dir, f"session_{self.session_id}_summary.json")
        try:
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to write session summary: {e}")
        logger.info(f"Session {self.session_id} ended: {summary}")
