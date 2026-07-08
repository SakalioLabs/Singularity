"""Policy helpers for choosing action granularity and execution backend."""
from dataclasses import dataclass, field
from typing import Optional

from singularity.action.mapping import ActionMapper


@dataclass
class ActionPolicyDecision:
    """Decision made before mapping a canonical action to a backend command."""

    action_type: str
    backend: str
    preferred_backend: str
    preferred_control: str = "mineflayer_api_ok"
    reason: str = "default_backend"
    fallback_reason: str = ""
    hint: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        data = {
            "action_type": self.action_type,
            "backend": self.backend,
            "preferred_backend": self.preferred_backend,
            "preferred_control": self.preferred_control,
            "reason": self.reason,
        }
        if self.fallback_reason:
            data["fallback_reason"] = self.fallback_reason
        if self.hint:
            data["hint"] = dict(self.hint)
        return data


class ActionGranularityPolicy:
    """Consumes action-abstraction feedback and chooses a safe backend.

    The policy keeps Mineflayer as the default executable path while preserving
    an explicit preference for lower-level desktop/visual control when reports
    show that a canonical action is visually or spatially sensitive.
    """

    CONTROL_TO_BACKEND = {
        "mineflayer_api_ok": "mineflayer",
        "consider_low_level_visual_control": "desktop",
    }

    def __init__(
        self,
        feedback: Optional[dict] = None,
        executable_backends: Optional[set[str]] = None,
        allow_planned_backend: bool = False,
    ):
        self.executable_backends = set(executable_backends or {"mineflayer"})
        self.allow_planned_backend = allow_planned_backend
        self._hints_by_action_type: dict[str, dict] = {}
        if feedback:
            self.record_action_abstraction_feedback(feedback)

    def record_action_abstraction_feedback(self, feedback: dict) -> int:
        """Store policy hints from `BenchmarkRunner.action_abstraction_feedback()`."""
        stored = 0
        for hint in feedback.get("policy_hints", []) if isinstance(feedback, dict) else []:
            if not isinstance(hint, dict):
                continue
            action_type = str(hint.get("action_type") or "")
            if not action_type:
                continue
            self._hints_by_action_type[action_type] = dict(hint)
            stored += 1
        return stored

    def select_backend(
        self,
        action: dict,
        default_backend: str = "mineflayer",
        mapper: Optional[ActionMapper] = None,
    ) -> ActionPolicyDecision:
        """Select a backend for a canonical action without hiding fallbacks."""
        action_type = str(action.get("type") or "unknown")
        backend_override = action.get("backend")
        if backend_override:
            backend = str(backend_override)
            return ActionPolicyDecision(
                action_type=action_type,
                backend=backend,
                preferred_backend=backend,
                preferred_control="backend_override",
                reason="action_backend_override",
            )

        hint = dict(self._hints_by_action_type.get(action_type, {}))
        preferred_control = str(hint.get("preferred_control") or "mineflayer_api_ok")
        preferred_backend = self.CONTROL_TO_BACKEND.get(preferred_control, default_backend)
        reason = str(hint.get("reason") or "default_backend")
        fallback_reason = ""
        backend = preferred_backend

        if preferred_control == "define_canonical_mapping":
            backend = default_backend
            preferred_backend = default_backend
            fallback_reason = "canonical action needs an explicit mapping before backend switching"
        elif backend != default_backend:
            if backend not in self.executable_backends and not self.allow_planned_backend:
                fallback_reason = f"preferred backend {backend} is not enabled"
                backend = default_backend
            elif mapper is not None and not self.allow_planned_backend:
                preferred_command = mapper.map(action, backend)
                if not preferred_command.executable:
                    fallback_reason = preferred_command.notes or f"preferred backend {backend} is not executable"
                    backend = default_backend

        return ActionPolicyDecision(
            action_type=action_type,
            backend=backend,
            preferred_backend=preferred_backend,
            preferred_control=preferred_control,
            reason=reason,
            fallback_reason=fallback_reason,
            hint=hint,
        )

    def hints(self) -> dict:
        return {action_type: dict(hint) for action_type, hint in self._hints_by_action_type.items()}
