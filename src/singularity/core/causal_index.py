"""Causal event index for which/why memory over agent trajectories."""
import json
import logging
import math
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Optional

logger = logging.getLogger("singularity.causal")

HIGH_VALUE_ACTIONS = {"dig", "craft", "place", "attack", "use_item", "equip", "smelt"}
LOW_VALUE_ACTIONS = {"move_to", "walk_to", "look_at", "wait", "chat"}
VALUABLE_SUBJECT_TOKENS = {
    "log", "wood", "planks", "stick", "coal", "torch", "stone", "cobblestone",
    "ore", "iron", "diamond", "gold", "copper", "furnace", "crafting_table",
    "bed", "shield", "sword", "pickaxe", "axe", "shovel", "food", "bread",
}


def _event_key_part(value: str) -> str:
    text = str(value or "").strip().lower()
    cleaned = []
    for ch in text:
        cleaned.append(ch if ch.isalnum() or ch == "_" else " ")
    return "_".join("".join(cleaned).split()) or "unknown"


@dataclass
class CausalEvent:
    """A compact which/why event extracted from an observation-action-result transition."""

    event_type: str
    subject: str
    action_type: str = ""
    outcome: str = ""
    which: str = ""
    why: str = ""
    tags: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    context: dict = field(default_factory=dict)
    confidence: float = 0.7
    value_score: float = 0.0
    value_reasons: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: float = field(default_factory=time.time)
    uses: int = 0

    def searchable_text(self) -> str:
        parts = [
            self.event_type,
            self.subject,
            self.action_type,
            self.outcome,
            self.which,
            self.why,
            " ".join(self.tags),
            json.dumps(self.evidence, default=str),
            json.dumps(self.context, default=str),
        ]
        return " ".join(parts).lower()

    def prompt_line(self) -> str:
        subject = self.subject or self.action_type or self.event_type
        return f"[causal:{self.outcome}] {self.which or subject} -> {self.why}"

    def summary_key(self) -> tuple[str, str, str]:
        return (
            _event_key_part(self.action_type or self.event_type),
            _event_key_part(self.subject or self.which),
            _event_key_part(self.outcome or "unknown"),
        )


@dataclass
class CausalEventSummary:
    """Aggregated causal evidence for repeated action/subject/outcome transitions."""

    key: tuple[str, str, str]
    representative: CausalEvent
    events: list[CausalEvent]
    repeat_count: int
    tags: list[str] = field(default_factory=list)
    event_ids: list[str] = field(default_factory=list)
    value_score: float = 0.0
    avg_value_score: float = 0.0
    confidence: float = 0.0
    value_reasons: list[str] = field(default_factory=list)


def aggregate_causal_events(
    events: list[CausalEvent],
    limit: Optional[int] = None,
) -> list[CausalEventSummary]:
    """Collapse repeated causal events into compact skill-level summaries."""
    buckets: dict[tuple[str, str, str], list[CausalEvent]] = {}
    for event in events:
        buckets.setdefault(event.summary_key(), []).append(event)

    summaries = []
    for key, bucket in buckets.items():
        ordered = sorted(
            bucket,
            key=lambda event: (event.value_score, event.confidence, event.created_at),
            reverse=True,
        )
        representative = ordered[0]
        tags = []
        tag_seen = set()
        reasons = []
        reason_seen = set()
        for event in ordered:
            for tag in [event.subject, event.action_type, event.outcome] + event.tags:
                tag_text = str(tag).lower()
                if tag_text and tag_text not in tag_seen:
                    tag_seen.add(tag_text)
                    tags.append(str(tag))
            for reason in event.value_reasons:
                reason_text = str(reason).lower()
                if reason_text and reason_text not in reason_seen:
                    reason_seen.add(reason_text)
                    reasons.append(str(reason))

        value_scores = [event.value_score for event in ordered]
        summaries.append(CausalEventSummary(
            key=key,
            representative=representative,
            events=ordered,
            repeat_count=len(ordered),
            tags=tags[:24],
            event_ids=[event.id for event in ordered[:24]],
            value_score=round(max(value_scores), 3) if value_scores else 0.0,
            avg_value_score=round(sum(value_scores) / len(value_scores), 3) if value_scores else 0.0,
            confidence=round(max(event.confidence for event in ordered), 3),
            value_reasons=reasons[:12],
        ))

    summaries.sort(
        key=lambda summary: (
            summary.value_score,
            summary.repeat_count,
            summary.confidence,
            summary.representative.created_at,
        ),
        reverse=True,
    )
    return summaries[:limit] if limit is not None else summaries


class CausalEventIndex:
    """Small persistent index keyed by action, observed object, outcome, and causal tags."""

    def __init__(self, path: str, persist: bool = True):
        self.path = path
        self.persist = persist
        self.events: dict[str, CausalEvent] = {}
        if os.path.dirname(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
        if self.persist:
            self._load()

    def add_event(
        self,
        event_type: str,
        subject: str,
        action_type: str = "",
        outcome: str = "",
        which: str = "",
        why: str = "",
        tags: Optional[list[str]] = None,
        evidence: Optional[dict] = None,
        context: Optional[dict] = None,
        confidence: float = 0.7,
        value_score: float = 0.0,
        value_reasons: Optional[list[str]] = None,
    ) -> CausalEvent:
        event = CausalEvent(
            event_type=event_type,
            subject=subject,
            action_type=action_type,
            outcome=outcome,
            which=which,
            why=why,
            tags=sorted(set(str(tag) for tag in (tags or []) if tag)),
            evidence=evidence or {},
            context=context or {},
            confidence=max(0.0, min(1.0, confidence)),
            value_score=max(0.0, min(1.0, value_score)),
            value_reasons=value_reasons or [],
        )
        self.events[event.id] = event
        self._append(event)
        return event

    def record_transition(
        self,
        observation_before: Optional[dict],
        action: dict,
        result: dict,
        observation_after: Optional[dict] = None,
        goal: str = "",
        task: str = "",
        context: Optional[dict] = None,
    ) -> CausalEvent:
        before = observation_before or {}
        after = observation_after or {}
        action_type = action.get("type") or result.get("action_type", "unknown")
        subject = self._infer_subject(action, result)
        outcome = "success" if result.get("success") else "failure"
        effects = self._infer_effects(before, after, result)
        why = self._infer_why(outcome, subject, effects, result)
        tags = self._infer_tags(goal, task, action, result, before, after, effects)
        value_score, value_reasons = self._score_event(action_type, outcome, subject, effects, result, tags)
        evidence = {
            "action": action,
            "result": self._compact_result(result),
            "effects": effects,
            "before": self._compact_observation(before),
            "after": self._compact_observation(after),
        }
        event_context = {"goal": goal, "task": task}
        event_context.update(context or {})
        return self.add_event(
            event_type="action_transition",
            subject=subject,
            action_type=action_type,
            outcome=outcome,
            which=f"{action_type}:{subject}" if subject else action_type,
            why=why,
            tags=tags,
            evidence=evidence,
            context=event_context,
            confidence=0.85 if after else 0.65,
            value_score=value_score,
            value_reasons=value_reasons,
        )

    def ingest_session_events(self, events: list[dict], goal: str = "") -> list[CausalEvent]:
        """Extract causal transitions from structured session events."""
        created = []
        session_goal = goal or self._session_goal(events)
        for idx, event in enumerate(events):
            if event.get("type") != "action":
                continue
            before = self._nearest_observation(events, idx, -1)
            after = self._nearest_observation(events, idx, 1)
            data = event.get("data", {})
            created.append(self.record_transition(
                before,
                data.get("action", {}),
                data.get("result", {}),
                after,
                goal=session_goal,
                context={"source": "session_log", "event_index": idx},
            ))
        return created

    def query(
        self,
        query: str = "",
        current_state: Optional[dict] = None,
        tags: Optional[list[str]] = None,
        limit: int = 5,
        min_value_score: float = 0.0,
    ) -> list[CausalEvent]:
        query_words = self._keywords(query)
        state_words = self._state_words(current_state or {})
        tag_words = self._keywords(" ".join(tags or []))
        desired = query_words | state_words | tag_words
        if not desired:
            return []

        scored = []
        for event in self.events.values():
            if event.value_score < min_value_score:
                continue
            event_words = self._keywords(event.searchable_text())
            overlap = len(query_words & event_words) * 2
            overlap += len(state_words & event_words)
            overlap += len(tag_words & event_words) * 2
            overlap += 1 if event.outcome == "success" else 0
            overlap += event.confidence
            overlap += event.value_score
            if overlap > event.confidence:
                scored.append((overlap, event.created_at, event))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        selected = [event for _, _, event in scored[:limit]]
        for event in selected:
            event.uses += 1
        return selected

    def format_for_prompt(self, query: str, current_state: Optional[dict] = None, limit: int = 4) -> str:
        events = self.query(query, current_state=current_state, limit=limit)
        if not events:
            return ""
        return "\n".join(event.prompt_line() for event in events)

    def _infer_subject(self, action: dict, result: dict) -> str:
        params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
        for key in ("block", "item", "entity", "target", "name"):
            if result.get(key):
                return str(result[key])
            if params.get(key):
                return str(params[key])
        if params.get("x") is not None and params.get("z") is not None:
            return f"pos:{params.get('x')},{params.get('z')}"
        return action.get("type") or result.get("action_type", "unknown")

    def _infer_effects(self, before: dict, after: dict, result: dict) -> dict:
        before_inv = before.get("inventory", {}) if isinstance(before.get("inventory", {}), dict) else {}
        after_inv = after.get("inventory", {}) if isinstance(after.get("inventory", {}), dict) else {}
        inventory_delta = self._dict_delta(before_inv, after_inv)
        health_delta = self._number_delta(before.get("health"), after.get("health"))
        position_delta = self._position_distance(before.get("position", {}), after.get("position", {}))
        effects = {
            "inventory_delta": inventory_delta,
            "health_delta": health_delta,
            "position_delta": position_delta,
        }
        if result.get("block"):
            effects["block"] = result.get("block")
        if result.get("item"):
            effects["item"] = result.get("item")
        if result.get("error"):
            effects["error"] = result.get("error")
        return {k: v for k, v in effects.items() if v not in ({}, None, 0.0)}

    def _infer_why(self, outcome: str, subject: str, effects: dict, result: dict) -> str:
        if outcome == "failure":
            return result.get("error") or f"{subject} action failed"
        inventory_delta = effects.get("inventory_delta", {})
        gained = [f"+{count} {item}" for item, count in inventory_delta.items() if count > 0]
        spent = [f"{count} {item}" for item, count in inventory_delta.items() if count < 0]
        if gained:
            return "changed inventory by " + ", ".join(gained[:4])
        if spent:
            return "consumed inventory by " + ", ".join(spent[:4])
        if effects.get("block"):
            return f"interacted with block {effects['block']}"
        if effects.get("item"):
            return f"produced or used item {effects['item']}"
        if effects.get("position_delta"):
            return f"moved about {effects['position_delta']:.1f} blocks"
        return f"{subject} action succeeded"

    def _infer_tags(self, goal: str, task: str, action: dict, result: dict, before: dict, after: dict, effects: dict) -> list[str]:
        tags = set()
        tags.update(self._keywords(goal))
        tags.update(self._keywords(task))
        tags.add(action.get("type", ""))
        tags.add("success" if result.get("success") else "failure")
        subject = self._infer_subject(action, result)
        tags.add(subject)
        for value in effects.get("inventory_delta", {}).keys():
            tags.add(str(value))
        for obs in (before, after):
            for block in obs.get("nearby_blocks", [])[:10]:
                tags.add(str(block.get("name", "")))
            for resource in obs.get("grounded_resources", [])[:10]:
                tags.add(str(resource.get("name", "")))
                tags.add(str(resource.get("drop", "")))
            for entity in obs.get("nearby_entities", [])[:10]:
                tags.add(str(entity.get("type", entity.get("name", ""))))
        if result.get("error"):
            tags.update(self._keywords(str(result.get("error"))))
        return sorted(tag for tag in tags if tag)[:24]

    def _score_event(self, action_type: str, outcome: str, subject: str, effects: dict, result: dict, tags: list[str]) -> tuple[float, list[str]]:
        score = 0.1
        reasons = []
        action = str(action_type or "").lower()
        subject_text = str(subject or "").lower()
        tag_text = " ".join(str(tag).lower() for tag in tags)

        if action in HIGH_VALUE_ACTIONS:
            score += 0.25
            reasons.append("actionable_action")
        elif action in LOW_VALUE_ACTIONS:
            score -= 0.05

        inventory_delta = effects.get("inventory_delta", {})
        if any(change > 0 for change in inventory_delta.values()):
            score += 0.35
            reasons.append("inventory_gain")
        if any(change < 0 for change in inventory_delta.values()):
            score += 0.1
            reasons.append("inventory_cost")
        if effects.get("block"):
            score += 0.2
            reasons.append("block_interaction")
        if effects.get("item"):
            score += 0.25
            reasons.append("item_interaction")
        if outcome == "failure" and result.get("error"):
            score += 0.3
            reasons.append("failure_signal")
        health_delta = effects.get("health_delta")
        if health_delta:
            score += 0.25
            reasons.append("health_change")

        if subject_text.startswith("pos:"):
            score -= 0.15
        if self._contains_valuable_token(subject_text) or self._contains_valuable_token(tag_text):
            score += 0.2
            reasons.append("valuable_subject")

        if action in LOW_VALUE_ACTIONS and not reasons:
            reasons.append("low_value_navigation")
        return round(max(0.0, min(1.0, score)), 3), reasons

    def _contains_valuable_token(self, text: str) -> bool:
        return any(token in text for token in VALUABLE_SUBJECT_TOKENS)

    def _compact_observation(self, observation: dict) -> dict:
        return {
            "position": observation.get("position", {}),
            "health": observation.get("health"),
            "hunger": observation.get("hunger"),
            "inventory": observation.get("inventory", {}),
            "time_of_day": observation.get("time_of_day"),
            "nearby_blocks": observation.get("nearby_blocks", [])[:5],
            "nearby_entities": observation.get("nearby_entities", [])[:5],
            "grounded_resources": observation.get("grounded_resources", [])[:5],
        }

    def _compact_result(self, result: dict) -> dict:
        return {
            key: result.get(key)
            for key in ("success", "error", "block", "item", "action_type", "duration_ms", "backend", "backend_command")
            if key in result
        }

    def _nearest_observation(self, events: list[dict], start: int, step: int) -> dict:
        idx = start + step
        while 0 <= idx < len(events):
            if events[idx].get("type") == "observation":
                return events[idx].get("data", {})
            idx += step
        return {}

    def _session_goal(self, events: list[dict]) -> str:
        for event in events:
            if event.get("type") == "goal_start":
                return event.get("data", {}).get("goal", "")
        return ""

    def _dict_delta(self, before: dict, after: dict) -> dict:
        delta = {}
        for key in set(before) | set(after):
            change = after.get(key, 0) - before.get(key, 0)
            if change:
                delta[key] = change
        return delta

    def _number_delta(self, before, after) -> Optional[float]:
        if before is None or after is None:
            return None
        try:
            return round(float(after) - float(before), 3)
        except (TypeError, ValueError):
            return None

    def _position_distance(self, before: dict, after: dict) -> Optional[float]:
        try:
            dx = float(after.get("x", 0)) - float(before.get("x", 0))
            dy = float(after.get("y", 0)) - float(before.get("y", 0))
            dz = float(after.get("z", 0)) - float(before.get("z", 0))
        except (TypeError, ValueError):
            return None
        distance = math.sqrt(dx * dx + dy * dy + dz * dz)
        return round(distance, 3) if distance else None

    def _state_words(self, state: dict) -> set[str]:
        words = set()
        words.update(k for k, v in state.get("inventory", {}).items() if v)
        for block in state.get("nearby_blocks", []):
            words.add(str(block.get("name", "")))
        for resource in state.get("grounded_resources", []):
            words.add(str(resource.get("name", "")))
            words.add(str(resource.get("drop", "")))
        for entity in state.get("nearby_entities", []):
            words.add(str(entity.get("type", entity.get("name", ""))))
        return {word.lower() for word in words if word}

    def _keywords(self, text: str) -> set[str]:
        cleaned = []
        for ch in str(text).lower():
            cleaned.append(ch if ch.isalnum() or ch == "_" else " ")
        return {word for word in "".join(cleaned).split() if len(word) > 2}

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
                    event = CausalEvent(**self._filter_event_fields(data))
                    self.events[event.id] = event
        except Exception as e:
            logger.warning(f"Could not load causal event index: {e}")

    def _append(self, event: CausalEvent):
        if not self.persist:
            return
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(event), ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.warning(f"Could not append causal event: {e}")

    def _filter_event_fields(self, data: dict) -> dict:
        allowed = set(CausalEvent.__dataclass_fields__.keys())
        return {key: value for key, value in data.items() if key in allowed}
