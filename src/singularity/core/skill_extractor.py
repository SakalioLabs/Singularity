"""Skill extractor - extracts reusable skills and experience atoms from task traces."""
import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Optional

from singularity.core.causal_index import (
    LOW_VALUE_ACTIONS,
    CausalEvent,
    CausalEventIndex,
    CausalEventSummary,
    aggregate_causal_events,
)

logger = logging.getLogger("singularity.skill_extractor")


@dataclass
class SkillCandidate:
    """A reviewable skill promotion candidate derived from a session trace."""

    name: str
    goal: str
    description: str
    implementation: str
    score: float
    signals: dict = field(default_factory=dict)
    layer: str = "composite"
    review_status: str = "pending"
    reason: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: float = field(default_factory=time.time)


@dataclass
class SkillPromotionValidationReport:
    """Auditable explanation for a skill candidate promotion decision."""

    candidate_id: str
    candidate_name: str
    decision: str
    status: str
    reason: str
    score: float
    evidence: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    matched_rules: list[str] = field(default_factory=list)
    postconditions: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    gate: dict = field(default_factory=dict)
    discovery_gate: dict = field(default_factory=dict)
    critic: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class SkillPromotionCritic:
    """LLM-backed fallback critic for candidates without deterministic proof."""

    def __init__(self, llm, min_confidence: float = 0.55):
        self.llm = llm
        self.min_confidence = min_confidence

    def review_candidate(self, candidate: SkillCandidate, gate: dict, postconditions: dict = None) -> dict:
        """Return a sanitized approve/reject/unknown review for a skill candidate."""
        visual_evidence = candidate.signals.get("visual_evidence", {}) if isinstance(candidate.signals, dict) else {}
        payload = {
            "candidate": {
                "id": candidate.id,
                "name": candidate.name,
                "goal": candidate.goal,
                "description": candidate.description,
                "score": candidate.score,
                "implementation": self._safe_json(candidate.implementation),
                "signals": candidate.signals,
            },
            "deterministic_gate": gate,
            "current_postconditions": postconditions or {},
            "visual_evidence": visual_evidence if isinstance(visual_evidence, dict) else {},
        }
        prompt = (
            "Review this Minecraft skill promotion candidate. The deterministic verifier could not prove "
            "the goal, so use only the provided trace summary, actions, score, and signals. "
            "If visual_evidence is present, use the screenshot references, VLM summaries, grounded resources, "
            "landmarks, structures, and nearby entities as supporting or contradictory evidence for visual-only "
            "goals and environment-state claims. "
            "Reject candidates that look like false completion, unsafe overgeneralization, or missing evidence. "
            "Approve only when the action sequence and signals plausibly establish a reusable skill. "
            "Return strict JSON with keys: decision ('approve', 'reject', or 'unknown'), confidence (0-1), "
            "reason, evidence (array), missing (array), matched_rules (array), postconditions (object), warnings (array)."
        )
        try:
            response = self.llm.chat([
                {"role": "system", "content": "You are a concise Minecraft skill promotion critic. Output JSON only."},
                {"role": "user", "content": f"{prompt}\n\nCandidate payload:\n{json.dumps(payload, ensure_ascii=False, default=str)[:6000]}"},
            ], response_format={"type": "json_object"})
            raw = json.loads(response)
        except Exception as e:
            logger.warning(f"Promotion critic failed: {type(e).__name__}")
            return {
                "decision": "unknown",
                "status": "unknown",
                "confidence": 0.0,
                "reason": "critic_unavailable",
                "evidence": [],
                "missing": [],
                "matched_rules": ["promotion_critic"],
                "postconditions": {},
                "warnings": ["promotion critic call or JSON parse failed"],
            }
        return self._normalize_review(raw)

    def _normalize_review(self, raw: dict) -> dict:
        if not isinstance(raw, dict):
            raw = {}
        decision = str(raw.get("decision", "unknown")).lower()
        if decision not in {"approve", "reject", "unknown"}:
            decision = "unknown"
        confidence = self._safe_float(raw.get("confidence", 0.0))
        warnings = self._string_list(raw.get("warnings", []))
        if decision in {"approve", "reject"} and confidence < self.min_confidence:
            warnings.append("critic_confidence_below_threshold")
            decision = "unknown"

        if decision == "approve":
            status = "critic_approved"
        elif decision == "reject":
            status = "critic_rejected"
        else:
            status = "unknown"

        matched_rules = self._string_list(raw.get("matched_rules", []))
        if "promotion_critic" not in matched_rules:
            matched_rules.append("promotion_critic")

        return {
            "decision": decision,
            "status": status,
            "confidence": confidence,
            "reason": self._safe_text(raw.get("reason", f"{status}_candidate")),
            "evidence": self._string_list(raw.get("evidence", [])),
            "missing": self._string_list(raw.get("missing", [])),
            "matched_rules": matched_rules,
            "postconditions": raw.get("postconditions", {}) if isinstance(raw.get("postconditions", {}), dict) else {},
            "warnings": warnings,
        }

    def _safe_json(self, text: str):
        try:
            return json.loads(text)
        except Exception:
            return text

    def _safe_float(self, value) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0

    def _safe_text(self, value, limit: int = 240) -> str:
        text = str(value or "").strip()
        return text[:limit] if text else "no_reason"

    def _string_list(self, value, limit: int = 12) -> list[str]:
        if not isinstance(value, list):
            value = [value] if value else []
        return [self._safe_text(item, limit=240) for item in value[:limit] if str(item or "").strip()]


class SkillCandidateQueue:
    """Durable review queue for extracted skill candidates."""

    def __init__(self, path: str = "workspace/skills/skill_candidates.jsonl"):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.candidates: dict[str, SkillCandidate] = {}
        self._load()

    def enqueue(self, candidate: SkillCandidate) -> SkillCandidate:
        self.candidates[candidate.id] = candidate
        self._rewrite()
        return candidate

    def pending(self) -> list[SkillCandidate]:
        return [c for c in self.candidates.values() if c.review_status == "pending"]

    def all(self) -> list[SkillCandidate]:
        return list(self.candidates.values())

    def approve(
        self,
        candidate_id: str,
        skill_library,
        promotion_critic=None,
        discovery_gate_paths: list[str] = None,
    ) -> SkillCandidate | None:
        candidate = self.candidates.get(candidate_id)
        if not candidate:
            return None
        skill = SkillExtractor(
            skill_library,
            promotion_critic=promotion_critic,
            discovery_gate_paths=discovery_gate_paths,
        ).approve_candidate(candidate)
        if skill is not None:
            candidate.review_status = "approved"
        self._rewrite()
        return candidate

    def reject(self, candidate_id: str, reason: str = "") -> SkillCandidate | None:
        candidate = self.candidates.get(candidate_id)
        if not candidate:
            return None
        candidate.review_status = "rejected"
        candidate.reason = reason or candidate.reason
        self._rewrite()
        return candidate

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    candidate = SkillCandidate(**self._filter_candidate_fields(data))
                    self.candidates[candidate.id] = candidate
        except Exception as e:
            logger.warning(f"Could not load skill candidate queue: {e}")

    def _rewrite(self):
        with open(self.path, "w", encoding="utf-8") as f:
            for candidate in self.candidates.values():
                f.write(json.dumps(asdict(candidate), ensure_ascii=False, default=str) + "\n")

    def _filter_candidate_fields(self, data: dict) -> dict:
        allowed = set(SkillCandidate.__dataclass_fields__.keys())
        return {k: v for k, v in data.items() if k in allowed}


def build_discovery_skill_gate(
    discovery_report_paths: list[str] = None,
    feedback: dict = None,
    source: str = "",
) -> dict:
    """Build an approve/review/reject gate from discovery-to-application evidence."""
    inputs = []
    errors = []
    if isinstance(feedback, dict) and feedback:
        inputs.append({"source": source or "candidate", "feedback": feedback})
    for path in discovery_report_paths or []:
        if not path:
            continue
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                payload = json.load(f)
            report_feedback = payload.get("discovery_feedback", payload)
            if not isinstance(report_feedback, dict):
                raise ValueError("missing discovery_feedback object")
            inputs.append({"source": path, "feedback": report_feedback})
        except Exception as e:
            errors.append(f"{path}: {e}")

    if not inputs and not errors:
        return {
            "required": False,
            "readiness": "not_required",
            "decision": "allow",
            "reason": "no_discovery_gate_required",
            "sources": [],
            "evidence": [],
            "missing": [],
            "warnings": [],
            "errors": [],
        }

    totals = {
        "complete_loop_count": 0,
        "successful_application_count": 0,
        "failed_application_count": 0,
        "causal_memory_write_count": 0,
        "failed_experiment_action_count": 0,
    }
    all_ready = True
    sources = []
    evidence = []
    missing = []
    warnings = []
    for item in inputs:
        source_name = item["source"]
        item_feedback = item["feedback"]
        sources.append(source_name)
        ready = bool(item_feedback.get("ready_for_skill_gate"))
        all_ready = all_ready and ready
        for key in totals:
            totals[key] += _safe_int(item_feedback.get(key, 0))
        if ready:
            evidence.append(f"{source_name}: discovery loop ready for skill gate")
        else:
            missing.append(f"{source_name}: discovery loop incomplete")
        recommendations = item_feedback.get("recommendations", [])
        if isinstance(recommendations, list):
            warnings.extend(str(item) for item in recommendations[:8] if str(item or "").strip())

    if errors:
        readiness = "error"
        decision = "reject"
        reason = "discovery_skill_gate_error"
    elif all_ready and inputs:
        readiness = "approved"
        decision = "allow"
        reason = "discovery_loop_and_application_evidence_approved"
    elif totals["failed_application_count"] > 0 and totals["successful_application_count"] <= 0:
        readiness = "rejected"
        decision = "reject"
        reason = "discovery_application_failed_without_success"
    else:
        readiness = "review"
        decision = "reject"
        reason = "discovery_skill_gate_requires_review"

    return {
        "required": True,
        "readiness": readiness,
        "decision": decision,
        "reason": reason,
        "sources": sources,
        "evidence": evidence,
        "missing": missing,
        "warnings": _dedupe_strings(warnings),
        "errors": errors,
        **totals,
    }


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _dedupe_strings(values: list) -> list[str]:
    seen = set()
    result = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


class SkillExtractor:
    """Extracts reusable skills and transferable experience from session logs."""

    def __init__(
        self,
        skill_library,
        memory_system=None,
        auto_promote: bool = True,
        promotion_critic=None,
        discovery_gate_paths: list[str] = None,
    ):
        self.skill_library = skill_library
        self.memory_system = memory_system
        self.auto_promote = auto_promote
        self.promotion_critic = promotion_critic
        self.discovery_gate_paths = list(discovery_gate_paths or [])

    def extract_from_session(self, session_log_path: str) -> list:
        """Extract skills from a successful session log."""
        skills = []
        try:
            candidates = self.extract_skill_candidates(session_log_path)
            if not self.auto_promote:
                logger.info(f"Created {len(candidates)} skill candidate(s), awaiting review")
                return []
            for candidate in candidates:
                skills.append(self.approve_candidate(candidate))
        except Exception as e:
            logger.error(f"Skill extraction failed: {e}")
        return skills

    def extract_skill_candidates(self, session_log_path: str) -> list[SkillCandidate]:
        """Create reviewable skill candidates from a session log."""
        events = self._load_events(session_log_path)
        actions = self._successful_action_sequence(events)
        if not actions:
            return []
        goal = self._session_goal(events)
        score = self.consolidation_score_from_events(events)
        if not score["should_promote"]:
            logger.info(f"Session not promoted to skill candidate: score={score['score']:.2f}")
            return []
        verification_gate = self._verification_gate_from_events(events, goal)
        visual_evidence = self._visual_evidence_from_events(events, goal)
        discovery_feedback = self._discovery_feedback_from_events(events)
        skill_name = self._generate_skill_name(goal)
        signals = {**score["signals"], "verification_gate": verification_gate}
        if visual_evidence:
            signals["visual_evidence"] = visual_evidence
        if discovery_feedback:
            signals["discovery_feedback"] = discovery_feedback
            signals["discovery_skill_gate"] = build_discovery_skill_gate(
                feedback=discovery_feedback,
                source=session_log_path,
            )
        return [
            SkillCandidate(
                name=skill_name,
                goal=goal,
                description=f"Extracted from goal: {goal}",
                implementation=json.dumps(actions),
                score=score["score"],
                signals=signals,
                reason="score passed consolidation threshold",
            )
        ]

    def extract_causal_skill_candidates(
        self,
        session_log_path: str,
        min_repeats: int = 3,
        min_value_score: float = 0.65,
    ) -> list[SkillCandidate]:
        """Create reviewable candidates from repeated high-value causal summaries."""
        events = self._load_events(session_log_path)
        goal = self._session_goal(events)
        discovery_feedback = self._discovery_feedback_from_events(events)
        index = CausalEventIndex("", persist=False)
        causal_events = index.ingest_session_events(events, goal=goal)
        summaries = aggregate_causal_events(causal_events)
        candidates = []
        for summary in summaries:
            if not self._causal_summary_should_promote(summary, min_repeats, min_value_score):
                continue
            candidate = self._causal_summary_candidate(summary, goal)
            candidate.signals["verification_gate"] = self._verification_gate_from_events(events, goal)
            if discovery_feedback:
                candidate.signals["discovery_feedback"] = discovery_feedback
                candidate.signals["discovery_skill_gate"] = build_discovery_skill_gate(
                    feedback=discovery_feedback,
                    source=session_log_path,
                )
            visual_evidence = self._visual_evidence_from_events(events, goal)
            if visual_evidence:
                candidate.signals["visual_evidence"] = visual_evidence
            candidates.append(candidate)
        return candidates

    def extract_failure_correction_candidates(
        self,
        session_log_path: str,
        min_failures: int = 2,
        min_value_score: float = 0.55,
    ) -> list[SkillCandidate]:
        """Create reviewable candidates from repeated failures followed by corrective actions."""
        events = self._load_events(session_log_path)
        goal = self._session_goal(events)
        discovery_feedback = self._discovery_feedback_from_events(events)
        index = CausalEventIndex("", persist=False)
        causal_events = index.ingest_session_events(events, goal=goal)
        summaries = aggregate_causal_events(causal_events)
        candidates = []
        for summary in summaries:
            if not self._failure_summary_should_consider(summary, min_failures, min_value_score):
                continue
            correction = self._best_correction_for_failure(summary, causal_events)
            if not correction:
                continue
            candidate = self._failure_correction_candidate(summary, correction, goal)
            candidate.signals["verification_gate"] = self._verification_gate_from_events(events, goal)
            if discovery_feedback:
                candidate.signals["discovery_feedback"] = discovery_feedback
                candidate.signals["discovery_skill_gate"] = build_discovery_skill_gate(
                    feedback=discovery_feedback,
                    source=session_log_path,
                )
            visual_evidence = self._visual_evidence_from_events(events, goal)
            if visual_evidence:
                candidate.signals["visual_evidence"] = visual_evidence
            candidates.append(candidate)
        return candidates

    def approve_candidate(self, candidate: SkillCandidate):
        """Approve and write a candidate into the skill library."""
        report = self.validate_candidate_for_promotion(candidate)
        gate = report.gate
        candidate.signals = {
            **candidate.signals,
            "verification_gate": gate,
            "promotion_report": report.to_dict(),
        }
        if report.decision == "reject":
            candidate.review_status = "rejected"
            candidate.reason = f"{candidate.reason}; promotion_gate={report.reason}"
            logger.warning(f"Rejected skill candidate '{candidate.name}' by promotion gate: {report.reason}")
            return None

        candidate.review_status = "approved"
        skill = self.skill_library.create_skill(
            name=candidate.name,
            description=candidate.description,
            implementation=candidate.implementation,
            layer=candidate.layer,
            postconditions=report.postconditions,
            dependencies=self._skill_dependencies_from_candidate(candidate),
            provenance={
                "candidate_id": candidate.id,
                "goal": candidate.goal,
                "reason": report.reason,
                "created_at": candidate.created_at,
                "score": candidate.score,
            },
            gate={
                "decision": report.decision,
                "status": report.status,
                "reason": report.reason,
                "verification": report.gate,
                "discovery": report.discovery_gate,
                "matched_rules": report.matched_rules,
                "warnings": report.warnings,
            },
            notes=f"consolidation_score={candidate.score:.2f}; signals={candidate.signals}; review={candidate.review_status}",
        )
        logger.info(f"Approved skill '{candidate.name}' from goal: {candidate.goal}")
        return skill

    def validate_candidate_for_promotion(self, candidate: SkillCandidate) -> SkillPromotionValidationReport:
        """Explain whether a candidate is ready for promotion."""
        gate = self._candidate_verification_gate(candidate)
        discovery_gate = self._candidate_discovery_gate(candidate)
        if discovery_gate.get("required"):
            gate = {
                **gate,
                "discovery_skill_gate": discovery_gate,
                "matched_rules": self._merge_list(gate.get("matched_rules", []), ["discovery_skill_gate"]),
                "evidence": self._merge_list(gate.get("evidence", []), discovery_gate.get("evidence", [])),
                "missing": self._merge_list(gate.get("missing", []), discovery_gate.get("missing", [])),
            }
            if discovery_gate.get("decision") == "reject":
                gate.update({
                    "decision": "reject",
                    "status": f"discovery_{discovery_gate.get('readiness', 'review')}",
                    "reason": discovery_gate.get("reason", "discovery_skill_gate_requires_review"),
                })
        critic = {}
        if gate.get("status") == "unknown" and self.promotion_critic:
            gate, critic = self._apply_promotion_critic(candidate, gate)
        postconditions = self._postconditions_from_verification_gate(gate)
        warnings = []
        if discovery_gate.get("warnings"):
            warnings.extend(discovery_gate.get("warnings", []))
        if discovery_gate.get("errors"):
            warnings.extend(discovery_gate.get("errors", []))
        if gate.get("status") == "unknown":
            warnings.append("no deterministic verification proof; approval relies on consolidation score and human/operator review")
        if not postconditions:
            warnings.append("no inventory postconditions available for future self-verification")
        warnings.extend(critic.get("warnings", []) if isinstance(critic.get("warnings", []), list) else [])
        if critic and critic.get("decision") == "unknown":
            warnings.append("promotion critic could not resolve unknown verifier status")

        decision = "reject" if gate.get("decision") == "reject" else "approve"
        reason = gate.get("reason") or "verification_gate_missing_reason"
        if decision == "approve" and gate.get("status") == "achieved":
            reason = "verified_postconditions_satisfied"
        elif decision == "approve" and gate.get("status") == "critic_approved":
            reason = "critic_approved"
        elif decision == "reject" and gate.get("status") == "critic_rejected":
            reason = "critic_rejected"

        return SkillPromotionValidationReport(
            candidate_id=candidate.id,
            candidate_name=candidate.name,
            decision=decision,
            status=gate.get("status", "unknown"),
            reason=reason,
            score=candidate.score,
            evidence=gate.get("evidence", []) if isinstance(gate.get("evidence", []), list) else [],
            missing=gate.get("missing", []) if isinstance(gate.get("missing", []), list) else [],
            matched_rules=gate.get("matched_rules", []) if isinstance(gate.get("matched_rules", []), list) else [],
            postconditions=postconditions,
            warnings=warnings,
            gate=gate,
            discovery_gate=discovery_gate,
            critic=critic,
        )

    def extract_experience_atoms(self, session_log_path: str) -> list:
        """Extract transferable experience atoms from a session log.

        If a MemorySystem was provided, the atoms are also recorded there as
        ExperienceRecord objects and returned.
        """
        try:
            events = self._load_events(session_log_path)
        except Exception as e:
            logger.error(f"Experience extraction failed: {e}")
            return []

        goal = self._session_goal(events)
        actions = self._action_sequence(events)
        observations = [e.get("data", {}) for e in events if e.get("type") == "observation"]
        failures = self._failure_events(events)
        success = self._goal_succeeded(events)
        score = self.consolidation_score_from_events(events)
        dimensions = self._infer_dimensions(goal, actions, observations)
        causal = self._infer_causal(actions, failures, success)
        tags = self._infer_tags(goal, actions, observations)
        correction = self._infer_correction(failures, actions)

        atom = {
            "goal": goal,
            "task": goal,
            "outcome": "completed" if success else "failed_or_incomplete",
            "actions": actions,
            "observations": observations[-3:],
            "dimensions": dimensions,
            "causal": causal,
            "metrics": {
                "action_count": len(actions),
                "success_rate": score["signals"]["action_success_rate"],
                "consolidation_score": score["score"],
                "total_events": len(events),
            },
            "tags": tags,
            "success": success,
            "correction": correction,
        }

        if self.memory_system:
            record = self.memory_system.record_experience(**atom)
            self.memory_system.ingest_causal_events_from_session(events, goal=goal)
            return [record]
        return [atom]

    def consolidation_score(self, session_log_path: str) -> dict:
        """Score whether a session trace is worth promoting to a reusable skill."""
        try:
            return self.consolidation_score_from_events(self._load_events(session_log_path))
        except Exception as e:
            logger.error(f"Consolidation scoring failed: {e}")
            return {"score": 0.0, "should_promote": False, "signals": {"error": str(e)}}

    def consolidation_score_from_events(self, events: list[dict]) -> dict:
        actions = [e for e in events if e.get("type") == "action"]
        if not actions:
            return {"score": 0.0, "should_promote": False, "signals": {"action_success_rate": 0.0}}

        successes = 0
        for event in actions:
            if event.get("data", {}).get("result", {}).get("success"):
                successes += 1
        action_success_rate = successes / len(actions)
        completed = self._goal_succeeded(events)
        failures = self._failure_events(events)
        correction_signal = 1.0 if failures and successes else 0.0
        reusable_sequence = 1.0 if len(actions) >= 2 else 0.0
        low_error_rate = 1.0 - min(1.0, len(failures) / max(1, len(actions)))

        score = (
            0.35 * action_success_rate
            + 0.30 * (1.0 if completed else 0.0)
            + 0.15 * reusable_sequence
            + 0.10 * correction_signal
            + 0.10 * low_error_rate
        )
        signals = {
            "action_success_rate": round(action_success_rate, 3),
            "completed": completed,
            "failure_count": len(failures),
            "correction_signal": bool(correction_signal),
            "reusable_sequence": bool(reusable_sequence),
            "low_error_rate": round(low_error_rate, 3),
        }
        return {"score": round(score, 3), "should_promote": score >= 0.65, "signals": signals}

    def extract_failure_case(self, session_log_path: str) -> dict:
        """Extract failure analysis from a failed session."""
        try:
            events = self._load_events(session_log_path)
            errors = [e for e in events if e.get("type") == "error"]
            reflections = [e for e in events if e.get("type") == "reflection"]
            failures = self._failure_events(events)
            return {
                "errors": [e.get("data", {}) for e in errors],
                "reflections": [e.get("data", {}) for e in reflections],
                "failures": [e.get("data", {}) for e in failures],
                "total_events": len(events),
            }
        except Exception as e:
            logger.error(f"Failure extraction failed: {e}")
            return {}

    def _load_events(self, session_log_path: str) -> list[dict]:
        events = []
        with open(session_log_path, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events

    def _session_goal(self, events: list[dict]) -> str:
        goal_event = next((e for e in events if e.get("type") == "goal_start"), None)
        return goal_event.get("data", {}).get("goal", "unknown") if goal_event else "unknown"

    def _goal_succeeded(self, events: list[dict]) -> bool:
        goal_end = next((e for e in reversed(events) if e.get("type") == "goal_end"), None)
        if not goal_end:
            return False
        data = goal_end.get("data", {})
        result = data.get("result", {})
        return bool(data.get("success") or result.get("completed") or result.get("success"))

    def _discovery_feedback_from_events(self, events: list[dict]) -> dict:
        """Infer a compact discovery-to-application gate payload from session events."""
        hypothesis_count = 0
        experiment_count = 0
        consolidation_count = 0
        application_count = 0
        successful_application_count = 0
        failed_application_count = 0
        causal_memory_write_count = 0
        failed_experiment_action_count = 0
        recommendations = []

        for event in events:
            event_type = str(event.get("type") or "").lower()
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            text = self._compact_discovery_text(data)
            if event_type in {"discovery_hypothesis", "hypothesis", "knowledge_gap"}:
                hypothesis_count += 1
            elif event_type in {"discovery_experiment", "experiment"}:
                experiment_count += 1
                if self._event_success(data) is False:
                    failed_experiment_action_count += 1
            elif event_type in {"discovery_consolidation", "causal_rule", "knowledge_consolidation"}:
                consolidation_count += 1
            elif event_type in {"discovery_application", "knowledge_application"}:
                application_count += 1
                success = self._event_success(data)
                if success is True:
                    successful_application_count += 1
                elif success is False:
                    failed_application_count += 1
            elif event_type == "memory_write" and self._looks_like_causal_discovery_memory(data, text):
                consolidation_count += 1
                causal_memory_write_count += 1
            elif event_type == "action" and self._looks_like_discovery_experiment_text(text):
                experiment_count += 1
                result = data.get("result", {}) if isinstance(data.get("result", {}), dict) else {}
                if result.get("success") is False:
                    failed_experiment_action_count += 1

        for event in events:
            if event.get("type") != "goal_end":
                continue
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            goal = str(data.get("goal", ""))
            if not self._looks_like_discovery_application_text(goal.lower()):
                continue
            application_count += 1
            success = self._event_success(data)
            if success is True:
                successful_application_count += 1
            elif success is False:
                failed_application_count += 1

        if not any((
            hypothesis_count,
            experiment_count,
            consolidation_count,
            application_count,
            causal_memory_write_count,
        )):
            return {}

        phase_counts = {
            "knowledge_gap_identification": hypothesis_count,
            "experimental_discovery": experiment_count,
            "knowledge_consolidation": consolidation_count,
            "knowledge_application": application_count,
        }
        complete_loop_count = min(phase_counts.values())
        if hypothesis_count <= 0:
            recommendations.append("record_explicit_knowledge_gap_or_hypothesis")
        if experiment_count <= 0:
            recommendations.append("run_small_controlled_minecraft_experiment")
        if consolidation_count <= 0 or causal_memory_write_count <= 0:
            recommendations.append("write_causal_rule_with_provenance_before_skill_promotion")
        if application_count <= 0:
            recommendations.append("test_discovered_rule_on_held_out_application_goal")
        elif successful_application_count <= 0:
            recommendations.append("repeat_application_until_discovered_rule_succeeds")
        if failed_experiment_action_count > 0:
            recommendations.append("review_failed_experiment_actions_before_consolidation")

        return {
            "ready_for_skill_gate": bool(
                complete_loop_count > 0
                and successful_application_count > 0
                and causal_memory_write_count > 0
            ),
            "phase_counts": phase_counts,
            "complete_loop_count": complete_loop_count,
            "hypothesis_count": hypothesis_count,
            "experiment_count": experiment_count,
            "consolidation_count": consolidation_count,
            "application_count": application_count,
            "successful_application_count": successful_application_count,
            "failed_application_count": failed_application_count,
            "causal_memory_write_count": causal_memory_write_count,
            "failed_experiment_action_count": failed_experiment_action_count,
            "recommendations": recommendations,
        }

    def _verification_gate_from_events(self, events: list[dict], goal: str = "") -> dict:
        """Summarize goal verification evidence that can gate skill promotion."""
        verifications = [
            event.get("data", {})
            for event in events
            if event.get("type") == "goal_verification" and isinstance(event.get("data", {}), dict)
        ]
        if not verifications:
            return {
                "decision": "allow",
                "status": "unknown",
                "reason": "no_goal_verification_event",
                "target_inventory": {},
                "inventory_delta": {},
                "evidence": [],
            }

        relevant = []
        for verification in verifications:
            verification_goal = str(verification.get("goal", ""))
            if not goal or not verification_goal or verification_goal.lower() == goal.lower():
                relevant.append(verification)
        if not relevant:
            relevant = verifications

        rejected = next(
            (
                verification for verification in reversed(relevant)
                if self._verification_context(verification).get("accepted") is False
                or verification.get("status") == "failed"
            ),
            None,
        )
        if rejected:
            return self._verification_gate_payload(
                rejected,
                decision="reject",
                reason=self._verification_context(rejected).get("acceptance_reason")
                or "deterministic_verification_failed",
            )

        achieved = next(
            (
                verification for verification in reversed(relevant)
                if verification.get("achieved") or verification.get("status") == "achieved"
            ),
            None,
        )
        if achieved:
            return self._verification_gate_payload(
                achieved,
                decision="allow",
                reason="deterministic_verification_achieved",
            )

        unknown = relevant[-1]
        return self._verification_gate_payload(
            unknown,
            decision="allow",
            reason=self._verification_context(unknown).get("acceptance_reason")
            or "verification_unknown",
        )

    def _candidate_verification_gate(self, candidate: SkillCandidate) -> dict:
        gate = candidate.signals.get("verification_gate", {})
        if not isinstance(gate, dict) or not gate:
            return {
                "decision": "allow",
                "status": "unknown",
                "reason": "candidate_has_no_verification_gate",
                "target_inventory": {},
                "inventory_delta": {},
                "evidence": [],
            }
        if gate.get("decision") == "reject":
            return gate
        if gate.get("status") == "failed":
            return {**gate, "decision": "reject", "reason": gate.get("reason") or "verification_failed"}
        return {**gate, "decision": gate.get("decision", "allow")}

    def _candidate_discovery_gate(self, candidate: SkillCandidate) -> dict:
        if self.discovery_gate_paths:
            return build_discovery_skill_gate(discovery_report_paths=self.discovery_gate_paths)
        gate = candidate.signals.get("discovery_skill_gate", {}) if isinstance(candidate.signals, dict) else {}
        if isinstance(gate, dict) and gate:
            return gate
        feedback = candidate.signals.get("discovery_feedback", {}) if isinstance(candidate.signals, dict) else {}
        if isinstance(feedback, dict) and feedback:
            return build_discovery_skill_gate(feedback=feedback, source=f"candidate:{candidate.id}")
        return build_discovery_skill_gate()

    def _skill_dependencies_from_candidate(self, candidate: SkillCandidate) -> list[str]:
        try:
            implementation = json.loads(candidate.implementation)
        except (TypeError, ValueError):
            return []
        actions = []
        if isinstance(implementation, list):
            actions = [action for action in implementation if isinstance(action, dict)]
        elif isinstance(implementation, dict):
            for key in ("action_template", "avoid_action_template", "primary_correction"):
                if isinstance(implementation.get(key), dict):
                    actions.append(implementation[key])
            for action in implementation.get("correction_sequence", []):
                if isinstance(action, dict):
                    actions.append(action)
        action_to_skill = {
            "move_to": "move_to",
            "look_at": "look_at",
            "dig": "dig_block",
            "dig_block": "dig_block",
            "place": "place_block",
            "place_block": "place_block",
            "craft": "craft_item",
            "craft_item": "craft_item",
            "attack": "attack_entity",
            "attack_entity": "attack_entity",
            "eat": "eat_food",
            "eat_food": "eat_food",
        }
        dependencies = []
        for action in actions:
            dep = action_to_skill.get(str(action.get("type", "")).strip())
            if dep and dep not in dependencies:
                dependencies.append(dep)
        return dependencies

    def _event_success(self, record: dict):
        if not isinstance(record, dict):
            return None
        for key in ("success", "completed", "passed", "ok"):
            if isinstance(record.get(key), bool):
                return record.get(key)
        result = record.get("result")
        if isinstance(result, dict):
            return self._event_success(result)
        return None

    def _compact_discovery_text(self, value) -> str:
        parts = []

        def collect(item):
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                for key, nested in item.items():
                    if isinstance(key, str):
                        parts.append(key)
                    collect(nested)
            elif isinstance(item, list):
                for nested in item:
                    collect(nested)

        collect(value)
        return " ".join(parts).lower()

    def _looks_like_discovery_experiment_text(self, text: str) -> bool:
        return any(token in text for token in ("experiment", "trial", "test", "probe", "redstone", "circuit", "lever", "lamp"))

    def _looks_like_discovery_application_text(self, text: str) -> bool:
        return any(token in text for token in ("apply", "application", "build", "construct", "redstone", "circuit", "lamp"))

    def _looks_like_causal_discovery_memory(self, record: dict, text: str) -> bool:
        layer = str(record.get("layer", "")).lower() if isinstance(record, dict) else ""
        memory_type = str(record.get("memory_type", "")).lower() if isinstance(record, dict) else ""
        if layer == "causal" or "causal" in memory_type or "rule" in memory_type:
            return True
        return any(token in text for token in ("causal rule", "because", "if ", "then "))

    def _visual_evidence_from_events(self, events: list[dict], goal: str = "") -> dict:
        observations = [
            event.get("data", {})
            for event in events
            if event.get("type") == "observation" and isinstance(event.get("data", {}), dict)
        ]
        visual_events = [
            event.get("data", {})
            for event in events
            if event.get("type") in {"vision", "visual_analysis"}
            and isinstance(event.get("data", {}), dict)
        ]
        if not observations and not visual_events:
            return {}

        goal_lower = str(goal or "").lower()
        visual_terms = (
            "see", "visible", "look", "inspect", "scout", "find", "locate", "landmark",
            "shelter", "built", "place", "nearby", "biome", "cave", "village", "ravine",
            "hostile", "mob", "danger", "resource", "ore",
        )
        requires_visual_review = any(term in goal_lower for term in visual_terms)
        evidence = {
            "requires_visual_review": requires_visual_review,
            "reason": "goal_mentions_visual_or_environment_state" if requires_visual_review else "visual_context_available",
            "observation_count": len(observations),
        }
        screenshots = []
        analyses = []
        grounded = []
        landmarks = []
        structures = []
        flags = []
        nearby_blocks = []
        nearby_entities = []

        for obs in observations[-5:]:
            screenshots.extend(self._visual_paths_from_observation(obs))
            for key in ("visual_analysis", "vlm_analysis", "screenshot_analysis"):
                if obs.get(key):
                    analyses.append(str(obs.get(key))[:500])
            grounded.extend(self._compact_visual_items(obs.get("grounded_resources", []), limit=5))
            landmarks.extend(self._compact_visual_items(obs.get("landmarks", []), limit=5))
            if isinstance(obs.get("structures", {}), dict) and obs.get("structures"):
                structures.append(self._safe_visual_value(obs.get("structures", {})))
            flags.extend(str(flag) for flag in obs.get("flags", [])[:8] if flag)
            nearby_blocks.extend(self._compact_visual_items(obs.get("nearby_blocks", []), limit=5))
            nearby_entities.extend(self._compact_visual_items(obs.get("nearby_entities", []), limit=5))

        for event in visual_events[-5:]:
            screenshots.extend(self._visual_paths_from_observation(event))
            for key in ("visual_analysis", "summary", "analysis", "description"):
                if event.get(key):
                    analyses.append(str(event.get(key))[:500])
            grounded.extend(self._compact_visual_items(event.get("grounded_resources", []), limit=5))
            landmarks.extend(self._compact_visual_items(event.get("landmarks", []), limit=5))
            nearby_entities.extend(self._compact_visual_items(event.get("nearby_entities", []), limit=5))

        for key, value in (
            ("screenshots", self._dedupe_visual_list(screenshots)[:3]),
            ("visual_analysis", self._dedupe_visual_list(analyses)[-3:]),
            ("grounded_resources", self._dedupe_visual_dicts(grounded)[:8]),
            ("landmarks", self._dedupe_visual_dicts(landmarks)[:8]),
            ("structures", self._dedupe_visual_dicts(structures)[:5]),
            ("flags", self._dedupe_visual_list(flags)[:12]),
            ("nearby_blocks", self._dedupe_visual_dicts(nearby_blocks)[:8]),
            ("nearby_entities", self._dedupe_visual_dicts(nearby_entities)[:8]),
        ):
            if value:
                evidence[key] = value

        if len(evidence) <= 3 and not requires_visual_review:
            return {}
        return evidence

    def _visual_paths_from_observation(self, observation: dict) -> list[str]:
        paths = []
        for key in ("screenshot_path", "screenshot", "image_path", "frame_path"):
            value = observation.get(key)
            if isinstance(value, str) and value.strip():
                paths.append(value.strip()[:260])
        return paths

    def _compact_visual_items(self, value, limit: int = 5) -> list[dict]:
        if not isinstance(value, list):
            return []
        compacted = []
        allowed = {
            "name", "type", "distance", "dist", "position", "drop", "can_harvest",
            "required_tool_tier", "recommended_tool", "best_available_tool", "hostile",
            "health", "confidence", "source", "description",
        }
        for item in value[:limit]:
            if isinstance(item, dict):
                compacted.append({
                    str(key): self._safe_visual_value(val)
                    for key, val in item.items()
                    if key in allowed and val not in (None, "", [], {})
                })
            elif item not in (None, ""):
                compacted.append({"value": str(item)[:160]})
        return [item for item in compacted if item]

    def _safe_visual_value(self, value):
        if isinstance(value, dict):
            return {str(k): self._safe_visual_value(v) for k, v in value.items() if v not in (None, "", [], {})}
        if isinstance(value, list):
            return [self._safe_visual_value(v) for v in value[:8]]
        if isinstance(value, (int, float, bool)):
            return value
        return str(value)[:240]

    def _dedupe_visual_list(self, values: list[str]) -> list[str]:
        deduped = []
        for value in values:
            text = str(value)
            if text and text not in deduped:
                deduped.append(text)
        return deduped

    def _dedupe_visual_dicts(self, values: list[dict]) -> list[dict]:
        deduped = []
        seen = set()
        for value in values:
            if not isinstance(value, dict) or not value:
                continue
            key = json.dumps(value, sort_keys=True, default=str)
            if key not in seen:
                seen.add(key)
                deduped.append(value)
        return deduped

    def _apply_promotion_critic(self, candidate: SkillCandidate, gate: dict) -> tuple[dict, dict]:
        critic = self.promotion_critic.review_candidate(
            candidate,
            gate,
            self._postconditions_from_verification_gate(gate),
        )
        if not isinstance(critic, dict):
            return gate, {}

        merged_gate = {
            **gate,
            "critic": critic,
            "evidence": self._merge_list(gate.get("evidence", []), critic.get("evidence", [])),
            "missing": self._merge_list(gate.get("missing", []), critic.get("missing", [])),
            "matched_rules": self._merge_list(gate.get("matched_rules", []), critic.get("matched_rules", [])),
        }
        inventory_postconditions = self._critic_inventory_postconditions(critic)
        if inventory_postconditions:
            merged_gate["target_inventory"] = {
                **(merged_gate.get("target_inventory", {}) if isinstance(merged_gate.get("target_inventory", {}), dict) else {}),
                **inventory_postconditions,
            }

        if critic.get("decision") == "reject":
            merged_gate.update({
                "decision": "reject",
                "status": "critic_rejected",
                "reason": "critic_rejected",
                "achieved": False,
            })
        elif critic.get("decision") == "approve":
            merged_gate.update({
                "decision": "allow",
                "status": "critic_approved",
                "reason": "critic_approved",
                "achieved": True,
            })
        return merged_gate, critic

    def _critic_inventory_postconditions(self, critic: dict) -> dict:
        postconditions = critic.get("postconditions", {}) if isinstance(critic, dict) else {}
        inventory = postconditions.get("inventory", {}) if isinstance(postconditions, dict) else {}
        if not isinstance(inventory, dict):
            return {}
        normalized = {}
        for item, count in inventory.items():
            try:
                value = int(count)
            except (TypeError, ValueError):
                continue
            if value > 0:
                normalized[str(item)] = value
        return normalized

    def _merge_list(self, left, right) -> list[str]:
        merged = []
        for values in (left, right):
            if not isinstance(values, list):
                continue
            for value in values:
                text = str(value)
                if text and text not in merged:
                    merged.append(text)
        return merged

    def _postconditions_from_verification_gate(self, gate: dict) -> dict:
        target_inventory = gate.get("target_inventory", {}) if isinstance(gate, dict) else {}
        inventory_delta = gate.get("inventory_delta", {}) if isinstance(gate, dict) else {}
        inventory = {}
        for source in (target_inventory, inventory_delta):
            if not isinstance(source, dict):
                continue
            for item, count in source.items():
                try:
                    value = int(count)
                except (TypeError, ValueError):
                    continue
                if value > 0:
                    inventory[str(item)] = max(inventory.get(str(item), 0), value)
        return {"inventory": inventory} if inventory else {}

    def _verification_gate_payload(self, verification: dict, decision: str, reason: str) -> dict:
        return {
            "decision": decision,
            "status": verification.get("status", "unknown"),
            "achieved": bool(verification.get("achieved")),
            "reason": reason,
            "target_inventory": verification.get("target_inventory", {}) if isinstance(verification.get("target_inventory", {}), dict) else {},
            "inventory_delta": verification.get("inventory_delta", {}) if isinstance(verification.get("inventory_delta", {}), dict) else {},
            "evidence": verification.get("evidence", []) if isinstance(verification.get("evidence", []), list) else [],
            "missing": verification.get("missing", []) if isinstance(verification.get("missing", []), list) else [],
            "matched_rules": verification.get("matched_rules", []) if isinstance(verification.get("matched_rules", []), list) else [],
        }

    def _verification_context(self, verification: dict) -> dict:
        context = verification.get("context", {}) if isinstance(verification, dict) else {}
        return context if isinstance(context, dict) else {}

    def _action_sequence(self, events: list[dict]) -> list[dict]:
        sequence = []
        for event in events:
            if event.get("type") != "action":
                continue
            action_data = event.get("data", {}).get("action", {})
            result = event.get("data", {}).get("result", {})
            sequence.append({
                "type": action_data.get("type"),
                "parameters": action_data.get("parameters", {}),
                "success": bool(result.get("success")),
                "error": result.get("error"),
            })
        return sequence

    def _successful_action_sequence(self, events: list[dict]) -> list[dict]:
        sequence = []
        for action in self._action_sequence(events):
            if action.get("success"):
                sequence.append({"type": action.get("type"), "parameters": action.get("parameters", {})})
        return sequence

    def _failure_events(self, events: list[dict]) -> list[dict]:
        failures = []
        for event in events:
            if event.get("type") in ("error", "reflection", "failure"):
                failures.append(event)
            elif event.get("type") == "action" and not event.get("data", {}).get("result", {}).get("success", True):
                failures.append(event)
        return failures

    def _infer_dimensions(self, goal: str, actions: list[dict], observations: list[dict]) -> dict:
        action_types = [a.get("type", "unknown") for a in actions]
        last_obs = observations[-1] if observations else {}
        return {
            "structure": " -> ".join(action_types) if action_types else "none",
            "attribute": {
                "inventory": last_obs.get("inventory", {}),
                "time_of_day": last_obs.get("time_of_day"),
            },
            "process": f"Use {len(action_types)} ordered actions to pursue: {goal}",
            "function": goal,
            "interaction": {
                "entities": last_obs.get("nearby_entities", [])[:5],
                "blocks": last_obs.get("nearby_blocks", [])[:5],
            },
        }

    def _infer_causal(self, actions: list[dict], failures: list[dict], success: bool) -> dict:
        failed_action = next((a for a in actions if not a.get("success")), None)
        if failed_action:
            return {
                "which": failed_action.get("type"),
                "why": failed_action.get("error") or "action failed and changed the plan",
            }
        if actions:
            return {
                "which": actions[-1].get("type"),
                "why": "final successful action completed the reusable sequence" if success else "sequence reached a stable stopping point",
            }
        if failures:
            return {"which": "failure", "why": json.dumps(failures[-1].get("data", {}), default=str)[:160]}
        return {"which": "none", "why": "no causal signal available"}

    def _infer_tags(self, goal: str, actions: list[dict], observations: list[dict]) -> list[str]:
        tags = set(self._keywords(goal))
        tags.update(a.get("type") for a in actions if a.get("type"))
        if observations:
            tags.update(k for k, v in observations[-1].get("inventory", {}).items() if v)
        return sorted(str(t) for t in tags if t)[:12]

    def _infer_correction(self, failures: list[dict], actions: list[dict]) -> str:
        if not failures:
            return ""
        later_success = next((a for a in actions if a.get("success")), None)
        if later_success:
            return f"After failure, successful action was {later_success.get('type')}"
        return "Failure recorded without a later successful correction"

    def _causal_summary_should_promote(
        self,
        summary: CausalEventSummary,
        min_repeats: int,
        min_value_score: float,
    ) -> bool:
        event = summary.representative
        action = str(event.action_type or "").lower()
        subject = str(event.subject or "").lower()
        if summary.repeat_count < min_repeats:
            return False
        if summary.value_score < min_value_score:
            return False
        if event.outcome != "success":
            return False
        if action in LOW_VALUE_ACTIONS:
            return False
        if subject.startswith("pos:") or subject in {"", "unknown"}:
            return False
        return True

    def _causal_summary_candidate(self, summary: CausalEventSummary, goal: str) -> SkillCandidate:
        event = summary.representative
        score = self._causal_summary_score(summary)
        action_template = self._action_template_from_causal_event(event)
        name = self._safe_skill_name(["causal", event.action_type, event.subject])
        implementation = {
            "type": "causal_summary_skill",
            "summary_key": list(summary.key),
            "action_template": action_template,
            "repeat_count": summary.repeat_count,
            "evidence": {
                "why": event.why,
                "effects": event.evidence.get("effects", {}),
                "result": event.evidence.get("result", {}),
            },
        }
        signals = {
            "source": "causal_summary",
            "summary_key": list(summary.key),
            "action_type": event.action_type,
            "subject": event.subject,
            "outcome": event.outcome,
            "repeat_count": summary.repeat_count,
            "value_score": summary.value_score,
            "avg_value_score": summary.avg_value_score,
            "confidence": summary.confidence,
            "value_reasons": summary.value_reasons,
            "event_ids": summary.event_ids,
            "tags": summary.tags[:12],
        }
        return SkillCandidate(
            name=name,
            goal=goal,
            description=(
                f"Repeated causal skill for {event.action_type}:{event.subject} "
                f"observed {summary.repeat_count} times"
            ),
            implementation=json.dumps(implementation, ensure_ascii=False, default=str),
            score=score,
            signals=signals,
            reason=(
                "causal summary passed stability threshold; "
                f"repeat_count={summary.repeat_count}; value_score={summary.value_score:.2f}"
            ),
        )

    def _causal_summary_score(self, summary: CausalEventSummary) -> float:
        repeat_signal = min(1.0, summary.repeat_count / 5)
        score = (
            0.40 * summary.value_score
            + 0.25 * summary.avg_value_score
            + 0.20 * repeat_signal
            + 0.15 * summary.confidence
        )
        return round(max(0.0, min(1.0, score)), 3)

    def _failure_summary_should_consider(
        self,
        summary: CausalEventSummary,
        min_failures: int,
        min_value_score: float,
    ) -> bool:
        event = summary.representative
        action = str(event.action_type or "").lower()
        subject = str(event.subject or "").lower()
        if event.outcome != "failure":
            return False
        if summary.repeat_count < min_failures:
            return False
        if summary.value_score < min_value_score:
            return False
        if action in LOW_VALUE_ACTIONS:
            return False
        if subject.startswith("pos:") or subject in {"", "unknown"}:
            return False
        return True

    def _best_correction_for_failure(
        self,
        failure_summary: CausalEventSummary,
        causal_events: list[CausalEvent],
    ) -> Optional[dict]:
        candidates = {}
        sorted_failures = sorted(
            failure_summary.events,
            key=lambda event: self._event_index(event),
        )
        for failure in sorted_failures:
            sequence = self._correction_sequence_after_failure(failure, causal_events)
            if not sequence:
                continue
            primary = sequence[0]
            key = primary.summary_key()
            record = candidates.setdefault(key, {
                "primary": primary,
                "sequences": [],
                "failure_ids": [],
                "correction_ids": [],
                "correction_count": 0,
            })
            record["sequences"].append(sequence)
            record["failure_ids"].append(failure.id)
            record["correction_ids"].extend(event.id for event in sequence)
            record["correction_count"] += 1

        if not candidates:
            return None
        return sorted(
            candidates.values(),
            key=lambda item: (
                item["correction_count"],
                item["primary"].value_score,
                item["primary"].confidence,
            ),
            reverse=True,
        )[0]

    def _correction_sequence_after_failure(
        self,
        failure: CausalEvent,
        causal_events: list[CausalEvent],
        max_actions: int = 4,
        max_event_gap: int = 8,
    ) -> list[CausalEvent]:
        failure_index = self._event_index(failure)
        sequence = []
        for event in sorted(causal_events, key=lambda item: self._event_index(item)):
            event_index = self._event_index(event)
            if event_index <= failure_index:
                continue
            if event_index - failure_index > max_event_gap:
                break
            if event.outcome == "failure":
                break
            if not self._is_useful_correction_event(event):
                continue
            if event.summary_key() == failure.summary_key() and not sequence:
                continue
            sequence.append(event)
            if len(sequence) >= max_actions:
                break
        return sequence

    def _is_useful_correction_event(self, event: CausalEvent) -> bool:
        action = str(event.action_type or "").lower()
        subject = str(event.subject or "").lower()
        if event.outcome != "success":
            return False
        if action in LOW_VALUE_ACTIONS:
            return False
        if subject.startswith("pos:") or subject in {"", "unknown"}:
            return False
        return event.value_score >= 0.45

    def _failure_correction_candidate(
        self,
        failure_summary: CausalEventSummary,
        correction: dict,
        goal: str,
    ) -> SkillCandidate:
        failure = failure_summary.representative
        primary = correction["primary"]
        sequence = correction["sequences"][0]
        score = self._failure_correction_score(failure_summary, correction)
        name = self._safe_skill_name([
            "correct",
            failure.action_type,
            failure.subject,
            "via",
            primary.action_type,
            primary.subject,
        ])
        implementation = {
            "type": "failure_correction_skill",
            "failure_summary_key": list(failure_summary.key),
            "avoid_action_template": self._action_template_from_causal_event(failure),
            "primary_correction": self._action_template_from_causal_event(primary),
            "correction_sequence": [
                self._action_template_from_causal_event(event) for event in sequence
            ],
            "policy": "When the avoid action fails in this way, run the correction sequence before retrying.",
            "evidence": {
                "failure_why": failure.why,
                "primary_correction_why": primary.why,
                "failure_count": failure_summary.repeat_count,
                "correction_count": correction["correction_count"],
            },
        }
        signals = {
            "source": "failure_correction_summary",
            "failure_summary_key": list(failure_summary.key),
            "primary_correction_key": list(primary.summary_key()),
            "failed_action_type": failure.action_type,
            "failed_subject": failure.subject,
            "failure_count": failure_summary.repeat_count,
            "correction_count": correction["correction_count"],
            "failure_value_score": failure_summary.value_score,
            "correction_value_score": primary.value_score,
            "failure_reason": failure.why,
            "primary_correction_action_type": primary.action_type,
            "primary_correction_subject": primary.subject,
            "failure_event_ids": correction["failure_ids"],
            "correction_event_ids": sorted(set(correction["correction_ids"])),
            "tags": sorted(set(failure_summary.tags + primary.tags))[:12],
        }
        return SkillCandidate(
            name=name,
            goal=goal,
            description=(
                f"Correction for repeated {failure.action_type}:{failure.subject} failures "
                f"using {primary.action_type}:{primary.subject}"
            ),
            implementation=json.dumps(implementation, ensure_ascii=False, default=str),
            score=score,
            signals=signals,
            reason=(
                "failure correction summary passed stability threshold; "
                f"failures={failure_summary.repeat_count}; corrections={correction['correction_count']}"
            ),
        )

    def _failure_correction_score(self, failure_summary: CausalEventSummary, correction: dict) -> float:
        repeat_signal = min(1.0, failure_summary.repeat_count / 4)
        correction_signal = min(1.0, correction["correction_count"] / max(1, failure_summary.repeat_count))
        primary = correction["primary"]
        score = (
            0.30 * failure_summary.value_score
            + 0.30 * primary.value_score
            + 0.20 * repeat_signal
            + 0.20 * correction_signal
        )
        return round(max(0.0, min(1.0, score)), 3)

    def _action_template_from_causal_event(self, event: CausalEvent) -> dict:
        action = event.evidence.get("action", {}) if isinstance(event.evidence, dict) else {}
        parameters = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
        return {
            "type": event.action_type or action.get("type"),
            "parameters": parameters,
        }

    def _event_index(self, event: CausalEvent) -> int:
        try:
            return int(event.context.get("event_index", 0))
        except (TypeError, ValueError):
            return 0

    def _keywords(self, text: str) -> set[str]:
        cleaned = []
        for ch in text.lower():
            cleaned.append(ch if ch.isalnum() or ch == "_" else " ")
        return {w for w in "".join(cleaned).split() if len(w) > 2}

    def _generate_skill_name(self, goal: str) -> str:
        words = goal.lower().split()[:4]
        return "_".join(words).replace(",", "").replace(".", "")

    def _safe_skill_name(self, parts: list[str]) -> str:
        cleaned_parts = []
        for part in parts:
            text = str(part or "").lower()
            cleaned = []
            for ch in text:
                cleaned.append(ch if ch.isalnum() or ch == "_" else " ")
            normalized = "_".join("".join(cleaned).split())
            if normalized:
                cleaned_parts.append(normalized)
        return "_".join(cleaned_parts)[:80] or "causal_skill"
