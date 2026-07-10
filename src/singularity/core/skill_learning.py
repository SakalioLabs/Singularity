"""Durable evidence ledgers and lifecycle gates for learned skills."""

from __future__ import annotations

import json
import hashlib
import os
import time
from dataclasses import asdict, is_dataclass
from typing import Any


LEARNING_LEDGER_TYPE = "skill_learning_ledger"
REGRESSION_LEDGER_TYPE = "skill_regressions"
EXECUTABLE_PROMOTION_GATE_TYPE = "skill_executable_promotion_gate"
EVALUATION_AUTHORIZATION_TYPE = "skill_evaluation_authorization"


def executable_promotion_gate_issues(
    gate: dict,
    skill_id: str = "",
    version: str = "",
) -> list[str]:
    """Return machine-readable reasons a learned skill cannot execute at runtime."""
    if not isinstance(gate, dict):
        return ["executable_promotion_gate_required"]
    issues = []
    if gate.get("type") != EXECUTABLE_PROMOTION_GATE_TYPE:
        issues.append("executable_promotion_gate_type_invalid")
    if int(gate.get("schema_version", 0) or 0) != 1:
        issues.append("executable_promotion_gate_schema_invalid")
    if str(gate.get("readiness") or "").lower() != "approved":
        issues.append("executable_promotion_gate_not_approved")
    if gate.get("decision") != "promote_executable":
        issues.append("executable_promotion_decision_invalid")
    if skill_id and str(gate.get("skill_id") or "") != str(skill_id):
        issues.append("executable_promotion_skill_mismatch")
    gate_version = str(gate.get("promoted_skill_version") or gate.get("skill_version") or "")
    if version and gate_version not in {"", str(version)}:
        issues.append("executable_promotion_version_mismatch")

    thresholds = gate.get("thresholds", {}) if isinstance(gate.get("thresholds"), dict) else {}
    required_pairs = max(3, int(thresholds.get("min_paired_live_sessions", 3) or 3))
    baseline_ids = _unique_strings(gate.get("baseline_session_ids", []))
    candidate_ids = _unique_strings(gate.get("candidate_session_ids", []))
    if len(baseline_ids) < required_pairs:
        issues.append("insufficient_distinct_baseline_sessions")
    if len(candidate_ids) < required_pairs:
        issues.append("insufficient_distinct_candidate_sessions")
    if set(baseline_ids).intersection(candidate_ids):
        issues.append("baseline_candidate_session_overlap")
    if int(gate.get("paired_live_session_count", 0) or 0) < required_pairs:
        issues.append("insufficient_paired_live_sessions")

    required_true = (
        "single_target_skill",
        "shadow_plan_verified",
        "advisory_hint_verified",
        "fixed_controls_match",
        "live_minecraft_only",
        "goal_verifier_enforced",
        "action_verifier_enforced",
        "action_controller_enforced",
        "candidate_steps_reobserved",
        "candidate_steps_verified",
        "fallback_verified",
        "no_completion_rate_regression",
        "no_action_failure_regression",
        "no_verifier_reject_regression",
        "no_no_progress_regression",
        "rollback_path_present",
    )
    for key in required_true:
        if gate.get(key) is not True:
            issues.append(f"promotion_gate_check_failed:{key}")
    if int(gate.get("synthetic_evidence_count", 0) or 0) != 0:
        issues.append("synthetic_evidence_cannot_grant_runtime")
    transfer_scope = gate.get("transfer_scope", {})
    if not isinstance(transfer_scope, dict) or not transfer_scope.get("task_family"):
        issues.append("verified_transfer_scope_required")
    return sorted(set(issues))


def evaluation_authorization_issues(
    authorization: dict,
    skill_id: str,
    experiment_id: str,
) -> list[str]:
    """Validate an explicit one-skill advisory trial authorization."""
    if not isinstance(authorization, dict):
        return ["skill_evaluation_authorization_required"]
    checks = {
        "authorization_type_invalid": authorization.get("type") == EVALUATION_AUTHORIZATION_TYPE,
        "authorization_schema_invalid": int(authorization.get("schema_version", 0) or 0) == 1,
        "authorization_not_allowed": authorization.get("allowed") is True,
        "authorization_skill_mismatch": str(authorization.get("skill_id") or "") == str(skill_id or ""),
        "authorization_experiment_mismatch": bool(experiment_id)
        and str(authorization.get("experiment_id") or "") == str(experiment_id),
        "authorization_not_single_skill": authorization.get("single_target_skill") is True,
        "authorization_action_verifier_missing": authorization.get("action_verifier_enforced") is True,
        "authorization_action_controller_missing": authorization.get("action_controller_enforced") is True,
        "authorization_goal_verifier_missing": authorization.get("goal_verifier_enforced") is True,
        "authorization_reobservation_missing": authorization.get("reobserve_each_cycle") is True,
        "authorization_fallback_missing": authorization.get("fallback_to_agentic_planning") is True,
        "authorization_live_protocol_missing": bool(authorization.get("world_protocol_sha256")),
    }
    return sorted(name for name, passed in checks.items() if not passed)


def evidence_fingerprint(payload: dict) -> str:
    canonical = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class SkillLearningLedger:
    """Append evidence without turning artifact presence into a capability claim."""

    def __init__(self, path: str = "workspace/evals/skill_learning_ledger.json"):
        self.path = path
        self.data = self._load_or_default()

    def record_candidate(self, candidate: Any, promotion_report: dict | None = None) -> dict:
        payload = _plain(candidate)
        candidate_id = str(payload.get("id") or payload.get("skill_id") or "").strip()
        if not candidate_id:
            raise ValueError("candidate id is required")
        item = {
            "candidate_id": candidate_id,
            "skill_id": payload.get("skill_id", ""),
            "name": payload.get("name", ""),
            "version": payload.get("version", ""),
            "task_family": payload.get("task_family", ""),
            "status": payload.get("status", "candidate"),
            "review_status": payload.get("review_status", "pending"),
            "dedupe_key": payload.get("dedupe_key", ""),
            "runtime_eligible": payload.get("runtime_eligible") is True,
            "evidence_kind": payload.get("evidence_kind", "unknown"),
            "source_session_ids": list(payload.get("source_session_ids", [])),
            "source_environment_ids": list(payload.get("source_environment_ids", [])),
            "success_count": int(payload.get("success_count", 0) or 0),
            "failure_count": int(payload.get("failure_count", 0) or 0),
            "observed_failure_count": int(payload.get("observed_failure_count", 0) or 0),
            "failure_type_counts": payload.get("failure_type_counts", {}),
            "confidence_interval": payload.get("confidence_interval", {}),
            "transfer_scope": payload.get("transfer_scope", {}),
            "provenance": payload.get("provenance", {}),
            "validation_issues": list(payload.get("validation_issues", [])),
            "promotion_report": promotion_report or payload.get("signals", {}).get("promotion_report", {}),
            "updated_at": time.time(),
        }
        self.data["candidates"][candidate_id] = item
        self._refresh_stage()
        self._write()
        return item

    def record_skill(self, skill: Any) -> dict:
        payload = _plain(skill)
        skill_id = str(payload.get("skill_id") or payload.get("name") or "").strip()
        if not skill_id:
            raise ValueError("skill id is required")
        key = f"{skill_id}@{payload.get('version', '')}"
        item = {
            "skill_id": skill_id,
            "name": payload.get("name", ""),
            "version": payload.get("version", ""),
            "task_family": payload.get("task_family", ""),
            "status": payload.get("status", "candidate"),
            "parent_version": payload.get("parent_version", ""),
            "rollback_target": payload.get("rollback_target", ""),
            "source_session_ids": list(payload.get("source_session_ids", [])),
            "source_environment_ids": list(payload.get("source_environment_ids", [])),
            "verifier_version": payload.get("verifier_version", ""),
            "success_count": int(payload.get("success_count", 0) or 0),
            "failure_count": int(payload.get("failure_count", 0) or 0),
            "observed_failure_count": int(payload.get("observed_failure_count", 0) or 0),
            "failure_type_counts": payload.get("failure_type_counts", {}),
            "confidence_interval": payload.get("confidence_interval", {}),
            "transfer_scope": payload.get("transfer_scope", {}),
            "provenance": payload.get("provenance", {}),
            "gate": payload.get("gate", {}),
            "lifecycle_history": list(payload.get("lifecycle_history", [])),
            "updated_at": time.time(),
        }
        self.data["skills"][key] = item
        self._refresh_stage()
        self._write()
        return item

    def record_experiment(self, report: dict) -> dict:
        payload = _plain(report)
        identity = str(
            payload.get("experiment_id")
            or payload.get("report_id")
            or f"experiment-{len(self.data['experiments']) + 1}"
        )
        item = {"experiment_id": identity, "recorded_at": time.time(), **payload}
        existing = next(
            (index for index, value in enumerate(self.data["experiments"]) if value.get("experiment_id") == identity),
            None,
        )
        if existing is None:
            self.data["experiments"].append(item)
        else:
            self.data["experiments"][existing] = item
        self._refresh_stage()
        self._write()
        return item

    def record_decision(
        self,
        skill_id: str,
        decision: str,
        reason: str,
        evidence: dict | None = None,
    ) -> dict:
        item = {
            "timestamp": time.time(),
            "skill_id": str(skill_id or ""),
            "decision": str(decision or ""),
            "reason": str(reason or "")[:500],
            "evidence": evidence or {},
        }
        self.data["decisions"].append(item)
        self._refresh_stage()
        self._write()
        return item

    def _refresh_stage(self):
        statuses = {
            str(item.get("status") or "candidate")
            for item in self.data["skills"].values()
        }
        if "executable" in statuses:
            stage = "executable"
        elif "advisory" in statuses:
            stage = "advisory"
        else:
            stage = "candidate"
        self.data["current_learning_stage"] = stage
        self.data["updated_at"] = time.time()

    def _load_or_default(self) -> dict:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8-sig") as handle:
                    payload = json.load(handle)
                if isinstance(payload, dict) and payload.get("type") == LEARNING_LEDGER_TYPE:
                    payload.setdefault("candidates", {})
                    payload.setdefault("skills", {})
                    payload.setdefault("experiments", [])
                    payload.setdefault("decisions", [])
                    return payload
            except Exception:
                pass
        return {
            "type": LEARNING_LEDGER_TYPE,
            "schema_version": 1,
            "current_learning_stage": "candidate",
            "claim": "self-learning mechanism under evaluation",
            "candidates": {},
            "skills": {},
            "experiments": [],
            "decisions": [],
            "updated_at": time.time(),
        }

    def _write(self):
        _atomic_json_write(self.path, self.data)


class SkillRegressionLedger:
    def __init__(self, path: str = "workspace/evals/skill_regressions.json"):
        self.path = path
        self.data = self._load_or_default()

    def record(self, event: dict) -> dict:
        item = {
            "timestamp": time.time(),
            "automatic_delete_allowed": False,
            **_plain(event),
        }
        self.data["events"].append(item)
        self.data["updated_at"] = time.time()
        _atomic_json_write(self.path, self.data)
        return item

    def _load_or_default(self) -> dict:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8-sig") as handle:
                    payload = json.load(handle)
                if isinstance(payload, dict) and payload.get("type") == REGRESSION_LEDGER_TYPE:
                    payload.setdefault("events", [])
                    return payload
            except Exception:
                pass
        return {
            "type": REGRESSION_LEDGER_TYPE,
            "schema_version": 1,
            "automatic_delete_allowed": False,
            "events": [],
            "updated_at": time.time(),
        }


def _plain(value: Any) -> dict:
    if is_dataclass(value):
        value = asdict(value)
    if not isinstance(value, dict):
        raise TypeError("ledger records must be dictionaries or dataclasses")
    return json.loads(json.dumps(value, ensure_ascii=True, default=str))


def _unique_strings(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        values = [values] if values else []
    return list(dict.fromkeys(str(value) for value in values if str(value or "").strip()))


def _atomic_json_write(path: str, payload: dict):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, path)
