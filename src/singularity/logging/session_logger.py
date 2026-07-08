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

    def log_action(self, action: dict, result: dict):
        self.log("action", {"action": action, "result": result})

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
        goal_verification_metrics = self._goal_verification_metrics()
        memory_policy_metrics = self._memory_policy_metrics()
        return {
            "session_id": self.session_id,
            "duration_s": round(elapsed, 2),
            "total_events": len(self.events),
            "action_count": action_count,
            "error_count": error_count,
            "intervention_metrics": intervention_metrics,
            "visual_action_metrics": visual_action_metrics,
            "goal_verification_metrics": goal_verification_metrics,
            "memory_policy_metrics": memory_policy_metrics,
            "log_path": self._log_path,
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
