"""Policy helpers for memory lifecycle decisions."""
from dataclasses import dataclass, field
import json
import re
from typing import Optional


PROMPTWARE_THREAT_PATTERNS = (
    (
        "instruction_override",
        re.compile(
            r"\b(ignore|disregard|forget|bypass|override)\b.{0,80}"
            r"\b(previous|prior|system|developer|safety|policy|instructions?)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "role_hijack",
        re.compile(
            r"\b(you are now|act as|become)\b.{0,50}"
            r"\b(system|developer|root|administrator|operator)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "secret_exfiltration_request",
        re.compile(
            r"\b(reveal|print|dump|send|upload|exfiltrate|leak|post)\b.{0,120}"
            r"\b(api[-_ ]?key|token|secret|password|credential|github[-_]?pat|sk-[a-z0-9])\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "tool_hijack_request",
        re.compile(
            r"\b(run|execute|spawn|start|call)\b.{0,60}"
            r"\b(shell|terminal|powershell|cmd|curl|wget|python|subprocess|command)\b.{0,120}"
            r"\b(token|secret|credential|delete|exfiltrate|upload|c2|callback)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "promptware_c2_loop",
        re.compile(
            r"\b(register as (a )?node|heartbeat|pull tasking|command\s*&?\s*control|"
            r"c2 server|one[- ]liners? only|never.{0,40}script.{0,40}disk)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "memory_persistence_payload",
        re.compile(
            r"\b(save|store|write|remember)\b.{0,80}\b(this|following|new)\b.{0,80}"
            r"\b(instruction|rule|policy|system message|developer message)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
)


def content_text(content) -> str:
    """Return a stable string representation for policy scanners."""
    try:
        return json.dumps(content, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        return str(content or "")


def promptware_threat_flags(content) -> list[str]:
    """Detect obvious promptware or memory-injection payloads in memory content."""
    text = content_text(content)
    if not text.strip():
        return []
    flags = []
    for flag, pattern in PROMPTWARE_THREAT_PATTERNS:
        if pattern.search(text):
            flags.append(flag)
    if flags:
        flags.append("promptware_threat")
    return sorted(set(flags))


@dataclass
class MemoryPolicyDecision:
    """Decision attached to a memory write/read/manage operation."""

    operation: str
    layer: str
    memory_type: str
    decision: str
    reason: str
    priority: str = "normal"
    should_persist: bool = True
    should_retrieve: bool = True
    should_log: bool = True
    should_review: bool = False
    should_consolidate: bool = False
    quality_flags: list[str] = field(default_factory=list)
    feedback_hints: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        data = {
            "operation": self.operation,
            "layer": self.layer,
            "memory_type": self.memory_type,
            "decision": self.decision,
            "reason": self.reason,
            "priority": self.priority,
            "should_persist": self.should_persist,
            "should_retrieve": self.should_retrieve,
            "should_log": self.should_log,
            "should_review": self.should_review,
            "should_consolidate": self.should_consolidate,
        }
        if self.quality_flags:
            data["quality_flags"] = list(self.quality_flags)
        if self.feedback_hints:
            data["feedback_hints"] = list(self.feedback_hints)
        return data


class MemoryLifecyclePolicy:
    """Advisory memory policy that can later enforce stricter write gates."""

    def __init__(self, feedback: Optional[dict] = None, enforce_write_gate: bool = False):
        self.enforce_write_gate = enforce_write_gate
        self._feedback_by_policy: dict[str, dict] = {}
        if feedback:
            self.record_memory_policy_feedback(feedback)

    def record_memory_policy_feedback(self, feedback: dict) -> int:
        stored = 0
        for hint in feedback.get("policy_hints", []) if isinstance(feedback, dict) else []:
            if not isinstance(hint, dict):
                continue
            policy_name = str(hint.get("memory_policy") or "")
            if not policy_name:
                continue
            self._feedback_by_policy[policy_name] = dict(hint)
            stored += 1
        return stored

    def decide_write(
        self,
        layer: str,
        memory_type: str,
        operation: str,
        content,
        source: str = "",
        confidence: float = 0.7,
    ) -> MemoryPolicyDecision:
        normalized_layer = str(layer or "unknown").lower()
        normalized_type = str(memory_type or "unknown").lower()
        normalized_operation = str(operation or "write").lower()
        flags = self._quality_flags(content, normalized_type, source, confidence)
        feedback_hints = self._active_hints()

        if flags:
            feedback_requested_gate = self._has_hint("tighten_memory_write_gate")
            has_promptware = "promptware_threat" in flags
            reason = (
                "potential promptware or memory-injection payload requires review"
                if has_promptware
                else "low-confidence or raw memory candidate"
            )
            if feedback_requested_gate and not has_promptware:
                reason = "low-confidence or raw memory candidate; feedback requested stricter write gate"
            return MemoryPolicyDecision(
                operation=normalized_operation,
                layer=normalized_layer,
                memory_type=normalized_type,
                decision="write_suppressed" if self.enforce_write_gate else "write_review_needed",
                reason=reason,
                priority="high" if has_promptware else self._hint_priority("tighten_memory_write_gate", "medium"),
                should_persist=not self.enforce_write_gate,
                should_review=True,
                quality_flags=flags,
                feedback_hints=feedback_hints,
            )

        if self._is_verified_outcome(normalized_type, content):
            feedback_requested_promotion = self._has_hint("promote_verified_outcomes")
            return MemoryPolicyDecision(
                operation=normalized_operation,
                layer=normalized_layer,
                memory_type=normalized_type,
                decision="semantic_promotion_candidate",
                reason=(
                    "verified outcome should be reviewed for durable memory; feedback found missed semantic writes"
                    if feedback_requested_promotion
                    else "verified outcome should be reviewed for durable memory"
                ),
                priority=self._hint_priority("promote_verified_outcomes", "high"),
                should_review=True,
                should_consolidate=True,
                feedback_hints=feedback_hints,
            )

        if self._is_failure_learning(normalized_type):
            feedback_requested_failures = self._has_hint("record_failure_corrections")
            return MemoryPolicyDecision(
                operation=normalized_operation,
                layer=normalized_layer,
                memory_type=normalized_type,
                decision="failure_learning_candidate",
                reason=(
                    "failure or correction trace can become reusable experience; feedback requested failure learning"
                    if feedback_requested_failures
                    else "failure or correction trace can become reusable experience"
                ),
                priority=self._hint_priority("record_failure_corrections", "medium"),
                should_review=True,
                should_consolidate=True,
                feedback_hints=feedback_hints,
            )

        if normalized_layer in {"semantic", "l3", "long_term"} or normalized_type in {"fact", "semantic"}:
            return MemoryPolicyDecision(
                operation=normalized_operation,
                layer=normalized_layer,
                memory_type=normalized_type,
                decision="durable_write_allowed",
                reason="explicit durable memory write",
                priority="high",
                should_review=True,
                feedback_hints=feedback_hints,
            )

        return MemoryPolicyDecision(
            operation=normalized_operation,
            layer=normalized_layer,
            memory_type=normalized_type,
            decision="write_allowed",
            reason="default memory write path",
            feedback_hints=feedback_hints,
        )

    def decide_read(
        self,
        query: str,
        layer: str,
        memory_type: str,
        operation: str = "retrieve",
    ) -> MemoryPolicyDecision:
        feedback_hints = self._active_hints()
        priority = self._hint_priority("instrument_memory_retrieval", "normal")
        reason = "retrieval should be instrumented" if priority == "high" else "default memory read path"
        return MemoryPolicyDecision(
            operation=str(operation or "retrieve").lower(),
            layer=str(layer or "unknown").lower(),
            memory_type=str(memory_type or "unknown").lower(),
            decision="read_instrumented",
            reason=reason,
            priority=priority,
            should_persist=False,
            should_retrieve=True,
            should_review=not bool(str(query or "").strip()),
            feedback_hints=feedback_hints,
        )

    def decide_manage(
        self,
        operation: str,
        layer: str = "memory",
        memory_type: str = "lifecycle",
    ) -> MemoryPolicyDecision:
        feedback_hints = self._active_hints()
        should_consolidate = "queue_consolidation_review" in feedback_hints or str(operation).lower() in {
            "consolidate", "save_session", "compact", "prune",
        }
        priority = self._hint_priority("queue_consolidation_review", "low") if should_consolidate else "low"
        return MemoryPolicyDecision(
            operation=str(operation or "manage").lower(),
            layer=str(layer or "memory").lower(),
            memory_type=str(memory_type or "lifecycle").lower(),
            decision="manage_allowed",
            reason="memory lifecycle management operation",
            priority=priority,
            should_persist=False,
            should_review=should_consolidate,
            should_consolidate=should_consolidate,
            feedback_hints=feedback_hints,
        )

    def feedback_hints(self) -> dict:
        return {name: dict(hint) for name, hint in self._feedback_by_policy.items()}

    def feedback_profile(self) -> dict:
        return {
            name: {
                "priority": str(hint.get("priority") or "normal"),
                "count": int(hint.get("count") or 0),
                "reason": str(hint.get("reason") or ""),
            }
            for name, hint in sorted(self._feedback_by_policy.items())
        }

    def _active_hints(self) -> list[str]:
        return sorted(self._feedback_by_policy)

    def _has_hint(self, name: str) -> bool:
        return name in self._feedback_by_policy

    def _hint_priority(self, name: str, default: str) -> str:
        hint = self._feedback_by_policy.get(name, {})
        return str(hint.get("priority") or default)

    def _quality_flags(self, content, memory_type: str, source: str, confidence: float) -> list[str]:
        flags = []
        text = self._content_text(content)
        metadata = content if isinstance(content, dict) else {}
        dependency = str(
            metadata.get("dependency")
            or metadata.get("dependency_type")
            or metadata.get("evidence_dependency")
            or ""
        ).lower()
        validity = str(metadata.get("validity") or metadata.get("evidence_status") or "").lower()
        has_supersession = bool(
            metadata.get("supersedes")
            or metadata.get("invalidates")
            or metadata.get("previous_value") is not None
            or metadata.get("state_revision")
        )
        if text and len(text.strip()) < 12:
            flags.append("too_short")
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            confidence_value = 1.0
        if confidence_value < 0.4:
            flags.append("low_confidence")
        if memory_type in {"raw_observation", "observation_dump"}:
            flags.append("raw_observation")
        if str(source or "").lower() in {"raw_observation", "observation"} and len(text) > 500:
            flags.append("raw_observation_dump")
        if dependency in {
            "copied",
            "copied_source",
            "shared_prompt",
            "shared_tool",
            "same_agent_echo",
            "low_trust",
            "unknown",
        }:
            flags.append("correlated_evidence")
        if validity in {"stale", "out_of_scope", "adversarial", "contradicted"}:
            flags.append("unsafe_scope")
        if has_supersession or validity in {"implicit_conflict", "state_revision", "superseded", "supersedes_previous"}:
            flags.append("state_revision")
        if validity == "implicit_conflict":
            flags.append("implicit_conflict")
        flags.extend(promptware_threat_flags(content))
        return sorted(set(flags))

    def _is_verified_outcome(self, memory_type: str, content) -> bool:
        if memory_type in {"goal_end", "goal_verification", "auto_goal_complete"}:
            text = self._content_text(content).lower()
            return any(marker in text for marker in ("success", "completed", "achieved", "accepted"))
        return memory_type in {"fact", "semantic"}

    def _is_failure_learning(self, memory_type: str) -> bool:
        return "failure" in memory_type or memory_type in {
            "reflection",
            "failure_correction_selected",
            "failure_correction_action",
            "failure_correction_completed",
            "failure_correction_failed",
        }

    def _content_text(self, content) -> str:
        return content_text(content)
