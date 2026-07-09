"""Memory system - multi-layered memory for the Singularity agent."""
import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Optional

from singularity.core.causal_index import CausalEvent, CausalEventIndex, aggregate_causal_events
from singularity.core.memory_policy import promptware_threat_flags

logger = logging.getLogger("singularity.memory")


TRANSFER_AXIS_WEIGHTS = {
    "structure": 1.15,
    "attribute": 1.25,
    "process": 1.65,
    "function": 1.45,
    "interaction": 1.20,
}

TRANSFER_AXIS_ALIASES = {
    "structure": ("structure", "struct"),
    "attribute": ("attribute", "attr"),
    "process": ("process", "procedure", "procedural", "proc"),
    "function": ("function", "func"),
    "interaction": ("interaction", "inter"),
}


@dataclass
class MemoryEntry:
    """A bounded, curated memory entry that can be injected or retrieved."""

    content: str
    layer: str = "semantic"
    memory_type: str = "fact"
    tags: list[str] = field(default_factory=list)
    importance: float = 0.5
    confidence: float = 1.0
    source: str = ""
    metadata: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    uses: int = 0
    recall_queries: list[str] = field(default_factory=list)
    last_recalled_at: float = 0.0

    def prompt_line(self) -> str:
        tag_text = f" tags={','.join(self.tags)}" if self.tags else ""
        return f"[{self.layer}:{self.memory_type}{tag_text}] {self.content}"


@dataclass
class ExperienceRecord:
    """Transferable experience distilled from an agent trajectory.

    The dimensions follow Echo-style transfer slots: structure, attribute,
    process, function, and interaction. The causal field keeps WISE-style
    which/why context close to the experience.
    """

    goal: str
    task: str
    outcome: str
    actions: list[dict] = field(default_factory=list)
    observations: list[dict] = field(default_factory=list)
    dimensions: dict = field(default_factory=dict)
    causal: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    success: bool = False
    correction: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: float = field(default_factory=time.time)
    uses: int = 0
    recall_queries: list[str] = field(default_factory=list)
    last_recalled_at: float = 0.0

    def searchable_text(self) -> str:
        parts = [
            self.goal,
            self.task,
            self.outcome,
            self.correction,
            " ".join(self.tags),
            json.dumps(self.dimensions, default=str),
            json.dumps(self.causal, default=str),
        ]
        return " ".join(parts).lower()


@dataclass
class TaskContinuityRecord:
    """Compact source-of-truth checkpoint for resuming long-running tasks."""

    goal: str
    source: str = ""
    summary: str = ""
    status_counts: dict = field(default_factory=dict)
    ready_tasks: list[dict] = field(default_factory=list)
    active_tasks: list[dict] = field(default_factory=list)
    blocked_tasks: list[dict] = field(default_factory=list)
    failed_tasks: list[dict] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    plan_status: str = ""
    plan_reasoning: str = ""
    state_summary: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: float = field(default_factory=time.time)

    def searchable_text(self) -> str:
        return " ".join([
            self.goal,
            self.source,
            self.summary,
            self.plan_status,
            self.plan_reasoning,
            json.dumps(self.status_counts, default=str),
            json.dumps(self.ready_tasks, default=str),
            json.dumps(self.active_tasks, default=str),
            json.dumps(self.blocked_tasks, default=str),
            json.dumps(self.failed_tasks, default=str),
            " ".join(self.next_actions),
            json.dumps(self.state_summary, default=str),
        ]).lower()


class MemorySystem:
    """Multi-layer memory: L0 Context, L1 Working, L2 Episodic, L3 Semantic, L4 Skill, L5 Decision, L6 Research."""

    def __init__(self, memory_dir: str = "workspace/memory", max_context_tokens: int = 4000, curated_char_limit: int = 2200, persist: bool = True):
        self.memory_dir = memory_dir
        self.max_context_tokens = max_context_tokens
        self.curated_char_limit = curated_char_limit
        self.persist = persist
        os.makedirs(memory_dir, exist_ok=True)
        # In-memory layers
        self.l0_context: list[dict] = []     # Current cycle context
        self.l1_working: dict = {}           # Session working memory
        self.l2_episodic: list[dict] = []    # Episode log
        self.l3_semantic: dict = {}          # Verified facts
        self.l4_skill: dict = {}             # Skill metadata
        self.l5_decision: list[dict] = []    # Architecture decisions
        self.l6_research: list[dict] = []    # Paper/repo cards
        self.entries: dict[str, MemoryEntry] = {}
        self.experiences: dict[str, ExperienceRecord] = {}
        self.task_continuity_records: list[TaskContinuityRecord] = []
        self.memory_attribution_profile = {
            "enabled": False,
            "hints_by_id": {},
            "hint_count": 0,
        }
        self.last_retrieval_trace: dict = {}
        self.entries_path = os.path.join(memory_dir, "memory_entries.jsonl")
        self.experiences_path = os.path.join(memory_dir, "experience_records.jsonl")
        self.task_continuity_path = os.path.join(memory_dir, "task_continuity.jsonl")
        self.causal_events_path = os.path.join(memory_dir, "causal_events.jsonl")
        self.causal_index = CausalEventIndex(self.causal_events_path, persist=persist)
        if self.persist:
            self._load_durable_memory()

    def write_context(self, entry: dict):
        """L0: Write to current context window."""
        entry["timestamp"] = time.time()
        self.l0_context.append(entry)
        if len(self.l0_context) > 50:
            self.l0_context = self.l0_context[-30:]

    def write_working(self, key: str, value):
        """L1: Write to working memory."""
        self.l1_working[key] = value

    def write_episode(self, event_type: str, data: dict):
        """L2: Write episodic memory entry."""
        entry = {"timestamp": time.time(), "type": event_type, "data": data}
        self.l2_episodic.append(entry)

    def write_fact(self, key: str, value: str, source: str = ""):
        """L3: Write verified semantic fact. Only use for confirmed information."""
        self.l3_semantic[key] = {"value": value, "source": source, "verified": True, "timestamp": time.time()}
        self.add_memory(
            content=f"{key}: {value}",
            layer="semantic",
            memory_type="fact",
            tags=[key],
            importance=0.7,
            confidence=1.0,
            source=source,
        )

    def add_memory(
        self,
        content: str,
        layer: str = "semantic",
        memory_type: str = "fact",
        tags: Optional[list[str]] = None,
        importance: float = 0.5,
        confidence: float = 1.0,
        source: str = "",
        metadata: Optional[dict] = None,
    ) -> MemoryEntry:
        """Add a durable memory entry.

        This is deliberately bounded and auditable: entries are plain text with
        explicit type, tags, source, importance, and confidence.
        """
        entry = MemoryEntry(
            content=content.strip(),
            layer=layer,
            memory_type=memory_type,
            tags=tags or [],
            importance=max(0.0, min(1.0, importance)),
            confidence=max(0.0, min(1.0, confidence)),
            source=source,
            metadata=metadata or {},
        )
        self.entries[entry.id] = entry
        self._append_jsonl(self.entries_path, asdict(entry))
        return entry

    def replace_memory(self, old_text: str, new_content: str) -> Optional[MemoryEntry]:
        """Replace one memory entry by unique substring match."""
        matches = [e for e in self.entries.values() if old_text.lower() in e.content.lower()]
        if len(matches) != 1:
            return None
        entry = matches[0]
        entry.content = new_content.strip()
        entry.updated_at = time.time()
        self._rewrite_entries()
        return entry

    def remove_memory(self, old_text: str) -> bool:
        """Remove one memory entry by unique substring match."""
        matches = [e for e in self.entries.values() if old_text.lower() in e.content.lower()]
        if len(matches) != 1:
            return False
        del self.entries[matches[0].id]
        self._rewrite_entries()
        return True

    def record_experience(
        self,
        goal: str,
        task: str,
        outcome: str,
        actions: Optional[list[dict]] = None,
        observations: Optional[list[dict]] = None,
        dimensions: Optional[dict] = None,
        causal: Optional[dict] = None,
        metrics: Optional[dict] = None,
        tags: Optional[list[str]] = None,
        success: bool = False,
        correction: str = "",
    ) -> ExperienceRecord:
        """Store a trajectory as a transferable experience."""
        record = ExperienceRecord(
            goal=goal,
            task=task,
            outcome=outcome,
            actions=actions or [],
            observations=observations or [],
            dimensions=dimensions or {},
            causal=causal or {},
            metrics=metrics or {},
            tags=tags or [],
            success=success,
            correction=correction,
        )
        self.experiences[record.id] = record
        self._append_jsonl(self.experiences_path, asdict(record))
        return record

    def record_causal_event(
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
        """Store a WISE-style which/why causal event."""
        return self.causal_index.add_event(
            event_type=event_type,
            subject=subject,
            action_type=action_type,
            outcome=outcome,
            which=which,
            why=why,
            tags=tags or [],
            evidence=evidence or {},
            context=context or {},
            confidence=confidence,
            value_score=value_score,
            value_reasons=value_reasons or [],
        )

    def record_causal_transition(
        self,
        observation_before: Optional[dict],
        action: dict,
        result: dict,
        observation_after: Optional[dict] = None,
        goal: str = "",
        task: str = "",
        context: Optional[dict] = None,
    ) -> CausalEvent:
        """Extract and store a causal event from one observe-act-observe transition."""
        return self.causal_index.record_transition(
            observation_before,
            action,
            result,
            observation_after,
            goal=goal,
            task=task,
            context=context or {},
        )

    def ingest_causal_events_from_session(self, events: list[dict], goal: str = "") -> list[CausalEvent]:
        """Extract causal events from a structured session event list."""
        return self.causal_index.ingest_session_events(events, goal=goal)

    def retrieve_causal_events(
        self,
        query: str = "",
        current_state: Optional[dict] = None,
        tags: Optional[list[str]] = None,
        limit: int = 5,
        min_value_score: float = 0.0,
    ) -> list[CausalEvent]:
        """Return relevant causal events ranked by query and current state overlap."""
        return self.causal_index.query(
            query,
            current_state=current_state,
            tags=tags or [],
            limit=limit,
            min_value_score=min_value_score,
        )

    def get_causal_opportunity_context(
        self,
        query: str = "",
        current_state: Optional[dict] = None,
        limit: int = 5,
        min_value_score: float = 0.55,
    ) -> dict:
        """Return compact causal tags/events that can bias task scheduling."""
        if limit <= 0:
            return {"causal_tags": [], "causal_events": []}

        events = self.retrieve_causal_events(
            query,
            current_state=current_state,
            limit=max(limit * 4, limit),
            min_value_score=min_value_score,
        )
        summaries = aggregate_causal_events(events, limit=limit)
        tags = set()
        compact_events = []
        for summary in summaries:
            event = summary.representative
            tags.update(summary.tags)
            compact_events.append({
                "id": event.id,
                "summary_key": list(summary.key),
                "subject": event.subject,
                "action_type": event.action_type,
                "outcome": event.outcome,
                "which": event.which,
                "why": event.why,
                "tags": summary.tags[:12],
                "confidence": summary.confidence,
                "value_score": summary.value_score,
                "avg_value_score": summary.avg_value_score,
                "repeat_count": summary.repeat_count,
                "event_ids": summary.event_ids,
                "value_reasons": summary.value_reasons,
            })
        return {
            "causal_tags": sorted(str(tag).lower() for tag in tags if tag),
            "causal_events": compact_events,
        }

    def rank_transfer_experiences(
        self,
        query: str,
        current_state: Optional[dict] = None,
        limit: int = 5,
        min_score: float = 0.1,
        mark_recalled: bool = False,
    ) -> list[dict]:
        """Rank experiences with Echo-style transfer-axis evidence."""
        query_words = self._transfer_tokens(query)
        state_words = self._transfer_tokens(json.dumps(current_state or {}, default=str))
        ranked = []
        for record in self.experiences.values():
            if self._experience_filter_reasons(record):
                continue
            score, axis_scores, axis_matches, base_matches = self._transfer_experience_score(
                record,
                query_words,
                state_words,
            )
            attribution = self._attribution_hint_for_id(record.id)
            score = self._apply_attribution_weight(score, attribution)
            if score < min_score:
                continue
            ranked.append({
                "record": record,
                "id": record.id,
                "goal": record.goal,
                "task": record.task,
                "outcome": record.outcome,
                "success": record.success,
                "score": round(score, 4),
                "matched_axes": [axis for axis, value in axis_scores.items() if value > 0],
                "axis_scores": {axis: round(value, 4) for axis, value in axis_scores.items() if value > 0},
                "axis_matches": axis_matches,
                "attribution_weight_delta": attribution.get("weight_delta", 0.0),
                "attribution_policy": attribution.get("policy", ""),
                "base_matches": base_matches,
                "tags": list(record.tags),
                "causal": dict(record.causal),
                "correction": record.correction,
            })
        ranked.sort(
            key=lambda item: (
                item["score"],
                len(item["matched_axes"]),
                1 if item["success"] else 0,
                item["record"].created_at,
            ),
            reverse=True,
        )
        selected = ranked[:limit] if limit and limit > 0 else ranked
        if mark_recalled and selected:
            for item in selected:
                self._mark_experience_recalled(item["record"], query)
            self._rewrite_experiences()
        return selected

    def retrieve_relevant_experiences(self, query: str, current_state: Optional[dict] = None, limit: int = 5) -> list[ExperienceRecord]:
        """Return experience records ranked by text overlap, context fit, and transfer axes."""
        return [
            item["record"]
            for item in self.rank_transfer_experiences(
                query,
                current_state=current_state,
                limit=limit,
                mark_recalled=True,
            )
        ]

    def apply_memory_attribution_runtime_gate(self, runtime_gate: dict) -> dict:
        """Load an approved attribution profile for conservative retrieval weighting."""
        profile = {
            "enabled": False,
            "hint_count": 0,
            "hints_by_id": {},
            "reason": "memory attribution gate is not approved",
        }
        if not isinstance(runtime_gate, dict):
            self.memory_attribution_profile = profile
            return profile
        if not runtime_gate.get("effective_enable_weighted_memory_retrieval"):
            profile["reason"] = str(runtime_gate.get("reason") or profile["reason"])
            self.memory_attribution_profile = profile
            return profile
        hints = runtime_gate.get("retrieval_weight_hints", [])
        if not isinstance(hints, list):
            hints = []
        for hint in hints:
            if not isinstance(hint, dict):
                continue
            memory_id = str(hint.get("memory_id") or "").strip()
            if not memory_id:
                continue
            profile["hints_by_id"][memory_id] = {
                "memory_id": memory_id,
                "weight_delta": self._bounded_attribution_delta(hint.get("weight_delta")),
                "policy": str(hint.get("policy") or ""),
                "reason": str(hint.get("reason") or "")[:160],
                "supported_read_count": _safe_int(hint.get("supported_read_count", 0)),
                "conflicting_read_count": _safe_int(hint.get("conflicting_read_count", 0)),
                "no_result_read_count": _safe_int(hint.get("no_result_read_count", 0)),
            }
        profile["hint_count"] = len(profile["hints_by_id"])
        profile["enabled"] = bool(profile["hint_count"])
        profile["reason"] = (
            "approved memory attribution gate loaded retrieval weights"
            if profile["enabled"]
            else "approved memory attribution gate did not include memory-id weight hints"
        )
        self.memory_attribution_profile = profile
        return profile

    def curate_entries(self, char_limit: Optional[int] = None) -> list[MemoryEntry]:
        """Return the highest-value memories that fit within a character budget."""
        limit = char_limit or self.curated_char_limit
        entries = sorted(
            self.entries.values(),
            key=lambda e: (self._memory_consolidation_score(e), e.importance * e.confidence, e.updated_at),
            reverse=True,
        )
        selected = []
        total = 0
        for entry in entries:
            if self._entry_filter_reasons(entry):
                continue
            length = len(entry.prompt_line()) + 1
            if total + length > limit:
                continue
            selected.append(entry)
            total += length
        return selected

    def get_context_window(self) -> str:
        """Get L0+L1 combined context for LLM, token-bounded."""
        parts = []
        for entry in self.l0_context[-10:]:
            parts.append(json.dumps(entry, default=str)[:200])
        for k, v in list(self.l1_working.items())[:5]:
            parts.append(f"{k}: {json.dumps(v, default=str)[:100]}")
        for entry in self.curate_entries()[:8]:
            parts.append(entry.prompt_line()[:300])
        return "\n".join(parts)[:self.max_context_tokens]

    def get_relevant_memory(self, query: str, current_state: Optional[dict] = None) -> str:
        """Search L2+L3 and transfer records for information relevant to query."""
        parts = []
        memory_matches = self._rank_memory_entries_for_query(query, current_state=current_state, limit=5, mark_recalled=True)
        for item in memory_matches:
            entry = self.entries.get(item["id"])
            if entry:
                parts.append(f"Memory: {entry.prompt_line()}")
        semantic_match_count = 0
        for key, fact in self.l3_semantic.items():
            if any(word in key.lower() or word in fact["value"].lower() for word in query.lower().split()[:3]):
                semantic_match_count += 1
                parts.append(f"Fact: {key} = {fact['value']}")
        episodic_match_count = 0
        for ep in self.l2_episodic[-20:]:
            if any(word in json.dumps(ep, default=str).lower() for word in query.lower().split()[:3]):
                episodic_match_count += 1
                parts.append(f"Experience: {ep['type']} - {json.dumps(ep['data'], default=str)[:100]}")
        transfer_matches = self.rank_transfer_experiences(query, current_state=current_state, limit=3, mark_recalled=True)
        for item in transfer_matches:
            axes = ",".join(item["matched_axes"][:5]) or "text"
            why = item["causal"].get("why", "")
            parts.append(
                f"Transfer[{axes} score={item['score']:.2f}]: "
                f"{item['task']} -> {item['outcome']}; why={why}"
            )
        causal_events = self.retrieve_causal_events(query, limit=3)
        for event in causal_events:
            parts.append(f"Causal: {event.prompt_line()}")
        self.last_retrieval_trace = self._build_retrieval_trace(
            query,
            memory_matches,
            transfer_matches,
            semantic_match_count=semantic_match_count,
            episodic_match_count=episodic_match_count,
            causal_match_count=len(causal_events),
            source="relevant_memory",
        )
        return "\n".join(parts[:10])

    def transfer_memory_report(
        self,
        query: str,
        current_state: Optional[dict] = None,
        limit: int = 10,
        min_score: float = 0.1,
    ) -> dict:
        """Return an offline Echo-style audit of transferable experience retrieval."""
        matches = self.rank_transfer_experiences(
            query,
            current_state=current_state,
            limit=limit,
            min_score=min_score,
            mark_recalled=False,
        )
        axis_counts = {}
        filtered_reasons = {}
        filtered_experience_count = 0
        for record in self.experiences.values():
            reasons = self._experience_filter_reasons(record)
            if reasons:
                filtered_experience_count += 1
                for reason in reasons:
                    filtered_reasons[reason] = filtered_reasons.get(reason, 0) + 1
        for item in matches:
            for axis in item["matched_axes"]:
                axis_counts[axis] = axis_counts.get(axis, 0) + 1
        return {
            "query": query,
            "current_state": current_state or {},
            "experience_count": len(self.experiences),
            "match_count": len(matches),
            "filtered_experience_count": filtered_experience_count,
            "experience_filter_reasons": filtered_reasons,
            "min_score": min_score,
            "axis_counts": axis_counts,
            "matches": [
                {key: value for key, value in item.items() if key != "record"}
                for item in matches
            ],
        }

    def task_memory_profile(
        self,
        goal: str,
        task=None,
        current_state: Optional[dict] = None,
        limit: int = 5,
        min_score: float = 0.1,
        mark_recalled: bool = False,
    ) -> dict:
        """Build a task-scoped memory profile for planner context and audits."""
        task_payload = self._task_payload(task)
        query = self._task_memory_query(goal, task_payload)
        transfer_matches = self.rank_transfer_experiences(
            query,
            current_state=current_state,
            limit=limit,
            min_score=min_score,
            mark_recalled=mark_recalled,
        )
        memory_matches = self._rank_memory_entries_for_query(
            query,
            current_state=current_state,
            limit=limit,
            mark_recalled=mark_recalled,
        )
        read_filter_report = self.memory_read_filter_report(query, current_state=current_state)
        self.last_retrieval_trace = self._build_retrieval_trace(
            query,
            memory_matches,
            transfer_matches,
            semantic_match_count=0,
            episodic_match_count=0,
            causal_match_count=0,
            source="task_memory",
        )
        axis_counts = {}
        for item in transfer_matches:
            for axis in item["matched_axes"]:
                axis_counts[axis] = axis_counts.get(axis, 0) + 1
        return {
            "goal": goal,
            "task": task_payload,
            "query": query,
            "current_state": current_state or {},
            "transfer_match_count": len(transfer_matches),
            "memory_match_count": len(memory_matches),
            "axis_counts": axis_counts,
            "read_filter_report": read_filter_report,
            "transfer_matches": [
                {key: value for key, value in item.items() if key != "record"}
                for item in transfer_matches
            ],
            "memory_matches": memory_matches,
        }

    def task_memory_context(
        self,
        goal: str,
        task=None,
        current_state: Optional[dict] = None,
        limit: int = 3,
    ) -> str:
        """Format task-centric memory evidence for the planner prompt."""
        profile = self.task_memory_profile(
            goal,
            task=task,
            current_state=current_state,
            limit=limit,
            mark_recalled=True,
        )
        task_payload = profile["task"]
        if not task_payload and not profile["transfer_matches"] and not profile["memory_matches"]:
            return ""
        title = task_payload.get("title") or goal
        lines = [f"Task-centric memory (task={title}):"]
        if task_payload.get("preconditions"):
            lines.append(f"- preconditions: {json.dumps(task_payload.get('preconditions'), default=str)[:180]}")
        if task_payload.get("success_criteria"):
            lines.append(f"- success criteria: {json.dumps(task_payload.get('success_criteria'), default=str)[:180]}")
        if task_payload.get("blockers"):
            lines.append(f"- blockers: {'; '.join(str(item) for item in task_payload.get('blockers', [])[:3])}")
        for memory in profile["memory_matches"][:limit]:
            tags = ",".join(memory.get("tags", [])[:4])
            tag_text = f" tags={tags}" if tags else ""
            lines.append(f"- scoped memory{tag_text}: {memory.get('content', '')[:180]}")
        for match in profile["transfer_matches"][:limit]:
            axes = ",".join(match.get("matched_axes", [])[:5]) or "text"
            lines.append(
                f"- transfer[{axes} score={match.get('score', 0):.2f}]: "
                f"{match.get('task', '')} -> {match.get('outcome', '')}"
            )
        filtered = profile.get("read_filter_report", {}).get("filtered_entries", 0)
        if filtered:
            lines.append(f"- filtered unsafe/stale/conditional memories: {filtered}")
        return "\n".join(lines)

    def record_task_continuity(
        self,
        goal: str,
        task_system=None,
        current_state: Optional[dict] = None,
        plan: Optional[dict] = None,
        source: str = "agent",
        max_tasks: int = 12,
    ) -> TaskContinuityRecord:
        """Persist a compact task-continuity checkpoint for future planning turns."""
        record = self._build_task_continuity_record(
            goal,
            task_system=task_system,
            current_state=current_state or {},
            plan=plan or {},
            source=source,
            max_tasks=max_tasks,
        )
        self._store_task_continuity_record(record)
        return record

    def import_task_continuity_from_session_log(
        self,
        session_log_path: str,
        source: str = "session_import",
    ) -> dict:
        """Import a conservative task-continuity checkpoint from a session JSONL log."""
        try:
            events = self._read_jsonl(session_log_path)
        except Exception as e:
            return {
                "type": "task_continuity_import",
                "source_log": session_log_path,
                "imported": False,
                "error": str(e),
            }
        return self.import_task_continuity_from_session_events(
            events,
            source_log=session_log_path,
            source=source,
        )

    def import_task_continuity_from_session_events(
        self,
        events: list[dict],
        source_log: str = "",
        source: str = "session_import",
    ) -> dict:
        """Import one durable checkpoint from already-loaded session events."""
        record = self._build_task_continuity_record_from_session_events(
            events,
            source_log=source_log,
            source=source,
        )
        if record is None:
            return {
                "type": "task_continuity_import",
                "source_log": source_log,
                "imported": False,
                "event_count": len(events or []),
                "reason": "session log did not contain enough goal, plan, action, or observation evidence",
            }
        self._store_task_continuity_record(record)
        return {
            "type": "task_continuity_import",
            "source_log": source_log,
            "imported": True,
            "event_count": len(events or []),
            "record": asdict(record),
            "status_counts": record.status_counts,
            "ready_task_count": len(record.ready_tasks),
            "blocked_task_count": len(record.blocked_tasks),
            "failed_task_count": len(record.failed_tasks),
            "next_actions": list(record.next_actions),
        }

    def task_continuity_context(
        self,
        goal: str,
        current_state: Optional[dict] = None,
        limit: int = 3,
    ) -> str:
        """Format recent task-continuity checkpoints for planner context."""
        matches = self._rank_task_continuity_records(goal, current_state or {}, limit=limit)
        if not matches:
            return ""
        lines = ["Task continuity ledger (durable checkpoints; resume from latest unresolved tasks):"]
        for item in matches:
            record = item["record"]
            age_s = max(0, int(time.time() - record.created_at))
            lines.append(
                f"- checkpoint {record.id} age={age_s}s source={record.source} "
                f"goal={record.goal[:90]} score={item['score']:.2f}"
            )
            if record.summary:
                lines.append(f"  summary: {record.summary[:220]}")
            if record.plan_status or record.plan_reasoning:
                lines.append(
                    f"  plan: {record.plan_status or 'unknown'} "
                    f"{record.plan_reasoning[:180]}"
                )
            for label, tasks in (
                ("ready", record.ready_tasks),
                ("active", record.active_tasks),
                ("blocked", record.blocked_tasks),
                ("failed", record.failed_tasks),
            ):
                if not tasks:
                    continue
                task_bits = []
                for task in tasks[:3]:
                    bit = str(task.get("title") or task.get("id") or "task")[:80]
                    missing = task.get("missing_preconditions", {})
                    if missing:
                        bit += f" missing={json.dumps(missing, default=str)[:120]}"
                    blockers = task.get("blockers", [])
                    if blockers:
                        bit += f" blockers={'; '.join(str(v) for v in blockers[:2])[:120]}"
                    task_bits.append(bit)
                lines.append(f"  {label}: " + " | ".join(task_bits))
            if record.next_actions:
                lines.append("  next: " + "; ".join(record.next_actions[:4]))
        return "\n".join(lines)

    def task_continuity_report(
        self,
        goal: str = "",
        current_state: Optional[dict] = None,
        limit: int = 10,
    ) -> dict:
        """Build a reviewable resume report from durable task-continuity checkpoints."""
        current_state = current_state or {}
        ranked = self._task_continuity_report_matches(goal, current_state, limit=limit)
        records = [self._task_continuity_report_record(item) for item in ranked]
        status_counts = {}
        missing_precondition_counts = {}
        missing_precondition_totals = {}
        blocker_counts = {}
        resume_candidates = []
        next_actions = []

        for item in ranked:
            record = item["record"]
            for status, count in (record.status_counts or {}).items():
                self._increment_count(status_counts, status, self._safe_int(count))
            for task in record.ready_tasks:
                resume_candidates.append(self._task_continuity_resume_candidate(record, task, "ready"))
            for task in record.blocked_tasks:
                candidate = self._task_continuity_resume_candidate(record, task, "blocked")
                resume_candidates.append(candidate)
                self._accumulate_task_missing_preconditions(
                    task.get("missing_preconditions", {}),
                    missing_precondition_counts,
                    missing_precondition_totals,
                )
                for blocker in task.get("blockers", []) or []:
                    self._increment_count(blocker_counts, str(blocker)[:160])
            for task in record.failed_tasks:
                resume_candidates.append(self._task_continuity_resume_candidate(record, task, "failed"))
            next_actions.extend(record.next_actions or [])

        resume_candidates = self._dedupe_task_continuity_candidates(resume_candidates)
        next_actions = self._dedupe_text(next_actions)[:12]
        ready_count = sum(1 for item in resume_candidates if item.get("status_bucket") == "ready")
        blocked_count = sum(1 for item in resume_candidates if item.get("status_bucket") == "blocked")
        failed_count = sum(1 for item in resume_candidates if item.get("status_bucket") == "failed")
        unresolved_count = ready_count + blocked_count + failed_count
        latest = max(records, key=lambda item: item.get("created_at", 0), default={})

        policy_hints = []
        recommendations = []
        if ready_count:
            policy_hints.append("resume_ready_tasks_before_new_goal_expansion")
            recommendations.append("continue the highest-priority ready task before decomposing new subtasks")
        if missing_precondition_counts:
            policy_hints.append("resolve_hidden_prerequisites_before_retry")
            recommendations.append("satisfy repeated missing inventory/flag preconditions before retrying blocked tasks")
        if blocker_counts:
            policy_hints.append("review_repeated_task_blockers")
            recommendations.append("inspect recurring blockers and convert stable ones into gated task-precondition feedback")
        if failed_count:
            policy_hints.append("replan_failed_tasks_with_transfer_memory")
            recommendations.append("retrieve transferable experiences before retrying failed tasks")
        if not records:
            policy_hints.append("collect_task_continuity_checkpoints")
            recommendations.append("run an Agent cycle with task-continuity context enabled to create durable resume checkpoints")

        readiness = "resume" if unresolved_count else "monitor" if records else "empty"
        decision = "resume_unresolved_tasks" if unresolved_count else "no_unresolved_tasks"
        if not records:
            decision = "no_task_continuity_records"

        return {
            "type": "task_continuity_report",
            "generated_at": round(time.time(), 3),
            "memory_dir": self.memory_dir,
            "ledger_path": self.task_continuity_path,
            "goal": str(goal or ""),
            "current_state_keys": sorted(str(key) for key in current_state.keys())[:20],
            "readiness": readiness,
            "decision": decision,
            "record_count": len(records),
            "total_record_count": len(self.task_continuity_records),
            "status_counts": dict(sorted(status_counts.items())),
            "ready_task_count": ready_count,
            "blocked_task_count": blocked_count,
            "failed_task_count": failed_count,
            "unresolved_task_count": unresolved_count,
            "missing_precondition_counts": dict(sorted(missing_precondition_counts.items())),
            "missing_precondition_totals": dict(sorted(missing_precondition_totals.items())),
            "blocker_counts": dict(sorted(blocker_counts.items())),
            "policy_hints": policy_hints,
            "recommendations": recommendations,
            "next_actions": next_actions,
            "latest_checkpoint": latest,
            "resume_candidates": resume_candidates[:20],
            "records": records,
        }

    def memory_read_filter_report(self, query: str = "", current_state: Optional[dict] = None) -> dict:
        """Summarize durable memory entries excluded from read-time evidence."""
        report = {
            "query": query,
            "total_entries": len(self.entries),
            "usable_entries": 0,
            "filtered_entries": 0,
            "filter_reasons": {},
            "filtered_ids": [],
        }
        query_words = self._keywords(query)
        for entry in self.entries.values():
            if query_words and not (query_words & self._keywords(entry.prompt_line())):
                continue
            reasons = self._entry_filter_reasons(entry, current_state)
            if reasons:
                report["filtered_entries"] += 1
                report["filtered_ids"].append(entry.id)
                for reason in reasons:
                    report["filter_reasons"][reason] = report["filter_reasons"].get(reason, 0) + 1
            else:
                report["usable_entries"] += 1
        return report

    def get_last_retrieval_trace(self) -> dict:
        """Return the latest retrieval trace without raw query text or memory content."""
        if not isinstance(self.last_retrieval_trace, dict):
            return {}
        try:
            return json.loads(json.dumps(self.last_retrieval_trace, default=str))
        except (TypeError, ValueError):
            return dict(self.last_retrieval_trace)

    def memory_promptware_report(self, query: str = "", current_state: Optional[dict] = None) -> dict:
        """Audit durable memories and experiences for promptware-like payloads."""
        query_words = self._keywords(query)
        flagged_entries = []
        flagged_experiences = []
        reason_counts = {}

        for entry in self.entries.values():
            if query_words and not (query_words & self._keywords(entry.prompt_line())):
                continue
            payload = self._entry_security_payload(entry)
            flags = promptware_threat_flags(payload)
            if not flags:
                continue
            for flag in flags:
                reason_counts[flag] = reason_counts.get(flag, 0) + 1
            flagged_entries.append({
                "id": entry.id,
                "layer": entry.layer,
                "memory_type": entry.memory_type,
                "tags": list(entry.tags),
                "source": entry.source,
                "flags": flags,
                "payload_hash": self._payload_fingerprint(payload),
                "read_filter_reasons": self._entry_filter_reasons(entry, current_state),
            })

        for record in self.experiences.values():
            if query_words and not (query_words & self._keywords(record.searchable_text())):
                continue
            payload = self._experience_security_payload(record)
            flags = promptware_threat_flags(payload)
            if not flags:
                continue
            for flag in flags:
                reason_counts[flag] = reason_counts.get(flag, 0) + 1
            flagged_experiences.append({
                "id": record.id,
                "tags": list(record.tags),
                "success": record.success,
                "flags": flags,
                "payload_hash": self._payload_fingerprint(payload),
                "read_filter_reasons": self._experience_filter_reasons(record),
            })

        return {
            "type": "memory_promptware_report",
            "query": query,
            "current_state": current_state or {},
            "total_entries": len(self.entries),
            "total_experiences": len(self.experiences),
            "flagged_entry_count": len(flagged_entries),
            "flagged_experience_count": len(flagged_experiences),
            "reason_counts": reason_counts,
            "flagged_entries": flagged_entries,
            "flagged_experiences": flagged_experiences,
        }

    def memory_consolidation_candidates(
        self,
        min_score: float = 0.65,
        min_recall_count: int = 2,
        min_unique_queries: int = 2,
        limit: int = 20,
    ) -> list[dict]:
        """Return memories/experiences that look worth durable consolidation.

        Inspired by agent-memory "dreaming" gates: a candidate must be useful,
        recalled often enough, and recalled from diverse enough queries.
        """
        candidates = []
        for entry in self.entries.values():
            score = self._memory_consolidation_score(entry)
            unique_queries = len(set(entry.recall_queries))
            if entry.uses >= min_recall_count and unique_queries >= min_unique_queries and score >= min_score:
                candidates.append({
                    "kind": "memory_entry",
                    "id": entry.id,
                    "content": entry.content,
                    "layer": entry.layer,
                    "memory_type": entry.memory_type,
                    "tags": entry.tags,
                    "score": round(score, 4),
                    "recall_count": entry.uses,
                    "unique_query_count": unique_queries,
                    "last_recalled_at": entry.last_recalled_at,
                    "source": entry.source,
                })
        for record in self.experiences.values():
            score = self._experience_consolidation_score(record)
            unique_queries = len(set(record.recall_queries))
            if record.uses >= min_recall_count and unique_queries >= min_unique_queries and score >= min_score:
                candidates.append({
                    "kind": "experience_record",
                    "id": record.id,
                    "goal": record.goal,
                    "task": record.task,
                    "outcome": record.outcome,
                    "tags": record.tags,
                    "success": record.success,
                    "score": round(score, 4),
                    "recall_count": record.uses,
                    "unique_query_count": unique_queries,
                    "last_recalled_at": record.last_recalled_at,
                    "causal": record.causal,
                })
        candidates.sort(
            key=lambda item: (item["score"], item["recall_count"], item["unique_query_count"]),
            reverse=True,
        )
        return candidates[:limit] if limit and limit > 0 else candidates

    def memory_maintenance_report(
        self,
        query: str = "",
        current_state: Optional[dict] = None,
        attribution_gate_paths: Optional[list[str]] = None,
        min_consolidation_score: float = 0.65,
        min_recall_count: int = 2,
        min_unique_queries: int = 2,
        limit: int = 80,
    ) -> dict:
        """Build review-only memory-management skill candidates.

        This keeps memory evolution auditable: the report proposes consolidate,
        quarantine, prune/revise, and retrieval-weight maintenance actions, but
        does not mutate durable memory.
        """
        current_state = current_state or {}
        candidates = []
        errors = []

        for item in self.memory_consolidation_candidates(
            min_score=min_consolidation_score,
            min_recall_count=min_recall_count,
            min_unique_queries=min_unique_queries,
            limit=0,
        ):
            candidates.append(self._maintenance_consolidation_candidate(item))

        promptware_report = self.memory_promptware_report(query=query, current_state=current_state)
        for item in promptware_report.get("flagged_entries", []):
            candidates.append(self._maintenance_promptware_candidate(item, "memory_entry"))
        for item in promptware_report.get("flagged_experiences", []):
            candidates.append(self._maintenance_promptware_candidate(item, "experience_record"))

        for entry in self.entries.values():
            reasons = self._entry_filter_reasons(entry, current_state)
            if not reasons:
                continue
            candidates.append(self._maintenance_filtered_entry_candidate(entry, reasons))

        attribution_report = evaluate_memory_attribution_runtime_gate(
            attribution_gate_paths or [],
            enable_requested=bool(attribution_gate_paths),
        )
        errors.extend(attribution_report.get("errors", []))
        for hint in attribution_report.get("retrieval_weight_hints", []):
            candidates.append(self._maintenance_attribution_candidate(hint, attribution_report))

        deduped = self._dedupe_maintenance_candidates(candidates)
        deduped.sort(
            key=lambda item: (
                self._maintenance_priority_rank(item.get("priority")),
                float(item.get("score") or 0.0),
                str(item.get("operation") or ""),
                str(item.get("memory_id") or ""),
            ),
            reverse=True,
        )
        selected = deduped[:limit] if limit and limit > 0 else deduped
        operation_counts = {}
        priority_counts = {}
        skill_counts = {}
        for item in selected:
            self._increment_count(operation_counts, item.get("operation", "unknown"))
            self._increment_count(priority_counts, item.get("priority", "review"))
            self._increment_count(skill_counts, item.get("recommended_skill", "unknown"))

        policy_hints = []
        recommendations = []
        if operation_counts.get("quarantine_promptware_memory") or operation_counts.get("quarantine_promptware_experience"):
            policy_hints.append("review_or_quarantine_promptware_memories")
            recommendations.append("run_promptware_gate_before_memory_write_enforcement")
        if operation_counts.get("revise_or_prune_filtered_memory"):
            policy_hints.append("revise_or_prune_filtered_memories")
            recommendations.append("review_stale_superseded_or_conditional_memories_before_retrieval")
        if operation_counts.get("consolidate_memory_entry") or operation_counts.get("consolidate_experience_record"):
            policy_hints.append("run_memory_consolidation_skill_on_recalled_items")
            recommendations.append("merge_recalled_memory_into_verified_task_or_semantic_entries")
        if operation_counts.get("promote_supported_retrieval_weight"):
            policy_hints.append("keep_supported_retrieval_weights_gate_controlled")
            recommendations.append("apply_positive_weight_hints_only_from_approved_attribution_gates")
        if operation_counts.get("repair_or_demote_retrieval_weight"):
            policy_hints.append("review_conflicting_retrievals_before_reuse")
            recommendations.append("route_conflicting_weight_hints_to_memory_repair_or_demotion")

        return {
            "type": "memory_maintenance_report",
            "generated_at": round(time.time(), 3),
            "memory_dir": self.memory_dir,
            "query_signature": self._query_hash(query),
            "current_state_keys": sorted(str(key) for key in current_state.keys())[:20],
            "total_entries": len(self.entries),
            "total_experiences": len(self.experiences),
            "candidate_count": len(selected),
            "total_candidate_count": len(deduped),
            "operation_counts": dict(sorted(operation_counts.items())),
            "priority_counts": dict(sorted(priority_counts.items())),
            "recommended_skill_counts": dict(sorted(skill_counts.items())),
            "policy_hints": policy_hints,
            "recommendations": recommendations,
            "attribution_gate_summary": {
                "gate_count": attribution_report.get("gate_count", 0),
                "gate_readiness": attribution_report.get("gate_readiness", "not_required"),
                "retrieval_weight_hint_count": attribution_report.get("retrieval_weight_hint_count", 0),
            },
            "promptware_summary": {
                "flagged_entry_count": promptware_report.get("flagged_entry_count", 0),
                "flagged_experience_count": promptware_report.get("flagged_experience_count", 0),
                "reason_counts": promptware_report.get("reason_counts", {}),
            },
            "candidates": selected,
            "errors": errors,
        }

    def _maintenance_consolidation_candidate(self, item: dict) -> dict:
        kind = str(item.get("kind") or "memory_entry")
        operation = "consolidate_experience_record" if kind == "experience_record" else "consolidate_memory_entry"
        recommended_skill = (
            "memory_consolidate_transfer_experience"
            if kind == "experience_record"
            else "memory_consolidate_recalled_evidence"
        )
        score = float(item.get("score") or 0.0)
        return {
            "operation": operation,
            "recommended_skill": recommended_skill,
            "priority": "high" if score >= 0.8 else "medium",
            "kind": kind,
            "memory_id": str(item.get("id") or ""),
            "score": round(score, 4),
            "review_status": "review_only",
            "reason": "memory or experience was recalled often from diverse queries",
            "evidence": {
                "recall_count": _safe_int(item.get("recall_count", 0)),
                "unique_query_count": _safe_int(item.get("unique_query_count", 0)),
                "tags": list(item.get("tags", []))[:12] if isinstance(item.get("tags", []), list) else [],
                "source": str(item.get("source") or "")[:120],
                "payload_hash": self._maintenance_item_hash(item),
            },
        }

    def _maintenance_promptware_candidate(self, item: dict, kind: str) -> dict:
        operation = "quarantine_promptware_experience" if kind == "experience_record" else "quarantine_promptware_memory"
        return {
            "operation": operation,
            "recommended_skill": "memory_quarantine_promptware_payload",
            "priority": "critical",
            "kind": kind,
            "memory_id": str(item.get("id") or ""),
            "score": 1.0,
            "review_status": "review_only",
            "reason": "durable memory payload matched promptware or memory-injection threat patterns",
            "evidence": {
                "flags": list(item.get("flags", []))[:12] if isinstance(item.get("flags", []), list) else [],
                "read_filter_reasons": list(item.get("read_filter_reasons", []))[:12]
                if isinstance(item.get("read_filter_reasons", []), list)
                else [],
                "payload_hash": str(item.get("payload_hash") or "")[:80],
                "tags": list(item.get("tags", []))[:12] if isinstance(item.get("tags", []), list) else [],
            },
        }

    def _maintenance_filtered_entry_candidate(self, entry: MemoryEntry, reasons: list[str]) -> dict:
        high_reasons = {"stale", "superseded", "contradicted", "invalidated", "adversarial", "promptware_threat"}
        priority = "high" if high_reasons & set(reasons) else "medium"
        return {
            "operation": "revise_or_prune_filtered_memory",
            "recommended_skill": "memory_revise_or_prune_filtered_entry",
            "priority": priority,
            "kind": "memory_entry",
            "memory_id": entry.id,
            "score": round(self._memory_consolidation_score(entry), 4),
            "review_status": "review_only",
            "reason": "memory is excluded or risky under current read-time filters",
            "evidence": {
                "read_filter_reasons": list(reasons)[:12],
                "layer": entry.layer,
                "memory_type": entry.memory_type,
                "tags": list(entry.tags)[:12],
                "source": entry.source[:120],
                "payload_hash": self._payload_fingerprint(self._entry_security_payload(entry)),
            },
        }

    def _maintenance_attribution_candidate(self, hint: dict, attribution_report: dict) -> dict:
        memory_id = str(hint.get("memory_id") or "").strip()
        delta = self._bounded_attribution_delta(hint.get("weight_delta"))
        if delta < 0:
            operation = "repair_or_demote_retrieval_weight"
            recommended_skill = "memory_repair_conflicting_retrieval"
            priority = "high"
            reason = "retrieval hint has conflicting or no-result outcome evidence"
        elif delta > 0:
            operation = "promote_supported_retrieval_weight"
            recommended_skill = "memory_apply_supported_retrieval_weight"
            priority = "medium"
            reason = "retrieval hint has supported downstream outcome evidence"
        else:
            operation = "review_retrieval_weight_hint"
            recommended_skill = "memory_review_attribution_hint"
            priority = "low"
            reason = "retrieval hint needs more decisive outcome evidence"
        return {
            "operation": operation,
            "recommended_skill": recommended_skill,
            "priority": priority,
            "kind": self._memory_id_kind(memory_id),
            "memory_id": memory_id,
            "score": round(abs(delta), 4),
            "review_status": "review_only",
            "reason": reason,
            "evidence": {
                "policy": str(hint.get("policy") or "")[:100],
                "reason": str(hint.get("reason") or "")[:160],
                "weight_delta": delta,
                "supported_read_count": _safe_int(hint.get("supported_read_count", 0)),
                "conflicting_read_count": _safe_int(hint.get("conflicting_read_count", 0)),
                "no_result_read_count": _safe_int(hint.get("no_result_read_count", 0)),
                "gate_readiness": attribution_report.get("gate_readiness", "unknown"),
            },
        }

    def _memory_id_kind(self, memory_id: str) -> str:
        if memory_id in self.entries:
            return "memory_entry"
        if memory_id in self.experiences:
            return "experience_record"
        return "unknown_memory_id"

    def _maintenance_item_hash(self, item: dict) -> str:
        payload = {
            key: item.get(key)
            for key in ("kind", "id", "layer", "memory_type", "tags", "source", "goal", "task", "outcome", "causal")
            if key in item
        }
        return self._payload_fingerprint(payload)

    def _dedupe_maintenance_candidates(self, candidates: list[dict]) -> list[dict]:
        deduped = {}
        for item in candidates:
            if not isinstance(item, dict):
                continue
            key = (
                str(item.get("operation") or ""),
                str(item.get("kind") or ""),
                str(item.get("memory_id") or ""),
            )
            existing = deduped.get(key)
            if existing and self._maintenance_priority_rank(existing.get("priority")) >= self._maintenance_priority_rank(item.get("priority")):
                continue
            deduped[key] = item
        return list(deduped.values())

    def _maintenance_priority_rank(self, priority: str) -> int:
        return {
            "critical": 4,
            "high": 3,
            "medium": 2,
            "low": 1,
        }.get(str(priority or "").lower(), 0)

    def _increment_count(self, counts: dict, key: str, amount: int = 1):
        key = str(key or "unknown")
        counts[key] = counts.get(key, 0) + amount

    def _safe_int(self, value) -> int:
        return _safe_int(value)

    def _dedupe_text(self, values: list[str]) -> list[str]:
        seen = set()
        result = []
        for value in values or []:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    def _store_task_continuity_record(self, record: TaskContinuityRecord):
        self.l1_working["task_continuity"] = asdict(record)
        self.task_continuity_records.append(record)
        if len(self.task_continuity_records) > 200:
            self.task_continuity_records = self.task_continuity_records[-200:]
        self._append_jsonl(self.task_continuity_path, asdict(record))

    def save_session(self, session_id: str):
        """Save episodic memory to daily journal file."""
        date_str = time.strftime("%Y-%m-%d")
        filepath = os.path.join(self.memory_dir, f"{date_str}.md")
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(f"\n## Session {session_id}\n")
            for entry in self.l2_episodic:
                f.write(f"- [{entry['type']}] {json.dumps(entry['data'], default=str)[:200]}\n")
            if self.experiences:
                f.write("\n### Transferable Experiences\n")
                for record in self.experiences.values():
                    f.write(f"- [{record.id}] {record.task}: {record.outcome}\n")
        logger.info(f"Session saved to {filepath}")

    def clear_session(self):
        """Clear L0 and L1 (session-specific). Keep L2+ for long-term."""
        self.l0_context.clear()
        self.l1_working.clear()

    def _load_durable_memory(self):
        """Load durable memory entries and experience records from JSONL sidecars."""
        for data in self._read_jsonl(self.entries_path):
            try:
                entry = MemoryEntry(**self._filter_dataclass_fields(data, MemoryEntry))
                self.entries[entry.id] = entry
            except Exception as e:
                logger.warning(f"Skipping invalid memory entry: {e}")
        for data in self._read_jsonl(self.experiences_path):
            try:
                record = ExperienceRecord(**self._filter_dataclass_fields(data, ExperienceRecord))
                self.experiences[record.id] = record
            except Exception as e:
                logger.warning(f"Skipping invalid experience record: {e}")
        for data in self._read_jsonl(self.task_continuity_path):
            try:
                record = TaskContinuityRecord(**self._filter_dataclass_fields(data, TaskContinuityRecord))
                self.task_continuity_records.append(record)
            except Exception as e:
                logger.warning(f"Skipping invalid task continuity record: {e}")
        if len(self.task_continuity_records) > 200:
            self.task_continuity_records = self.task_continuity_records[-200:]

    def _read_jsonl(self, path: str) -> list[dict]:
        if not os.path.exists(path):
            return []
        rows = []
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
        except Exception as e:
            logger.warning(f"Could not read {path}: {e}")
        return rows

    def _append_jsonl(self, path: str, data: dict):
        if not self.persist:
            return
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.warning(f"Could not append durable memory to {path}: {e}")

    def _rewrite_entries(self):
        if not self.persist:
            return
        try:
            with open(self.entries_path, "w", encoding="utf-8") as f:
                for entry in self.entries.values():
                    f.write(json.dumps(asdict(entry), ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.warning(f"Could not rewrite memory entries: {e}")

    def _rewrite_experiences(self):
        if not self.persist:
            return
        try:
            with open(self.experiences_path, "w", encoding="utf-8") as f:
                for record in self.experiences.values():
                    f.write(json.dumps(asdict(record), ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.warning(f"Could not rewrite experience records: {e}")

    def _filter_dataclass_fields(self, data: dict, cls) -> dict:
        allowed = set(cls.__dataclass_fields__.keys())
        return {k: v for k, v in data.items() if k in allowed}

    def _keywords(self, text: str) -> set[str]:
        cleaned = []
        for ch in text.lower():
            cleaned.append(ch if ch.isalnum() or ch == "_" else " ")
        words = set("".join(cleaned).split())
        return {w for w in words if len(w) > 2}

    def _transfer_tokens(self, text: str) -> set[str]:
        tokens = set()
        for word in self._keywords(text):
            tokens.add(word)
            for part in word.split("_"):
                if len(part) > 2:
                    tokens.add(part)
        tokens.update(self._transfer_family_tokens(tokens))
        return tokens

    def _transfer_family_tokens(self, tokens: set[str]) -> set[str]:
        families = set()
        material_groups = {
            "mat_wood": {"wood", "wooden", "oak", "birch", "spruce", "jungle", "acacia", "dark", "mangrove", "log", "logs", "plank", "planks"},
            "mat_stone": {"stone", "cobblestone", "deepslate", "granite", "diorite", "andesite"},
            "mat_metal": {"iron", "gold", "copper", "ingot", "ore"},
            "mat_fuel": {"coal", "charcoal", "fuel"},
            "mat_light": {"torch", "torches", "lantern", "light"},
        }
        tool_groups = {
            "tool_pickaxe": {"pickaxe", "pick"},
            "tool_axe": {"axe"},
            "tool_sword": {"sword"},
            "tool_shovel": {"shovel"},
            "tool_hoe": {"hoe"},
        }
        process_groups = {
            "proc_craft": {"craft", "crafted", "crafting", "recipe", "recipes"},
            "proc_mine": {"mine", "mined", "mining", "dig", "dug"},
            "proc_smelt": {"smelt", "smelting", "furnace"},
            "proc_build": {"build", "building", "place", "placed"},
            "proc_combat": {"attack", "combat", "defend", "hostile"},
        }
        for family, words in {**material_groups, **tool_groups, **process_groups}.items():
            if tokens & words:
                families.add(family)
        return families

    def _transfer_experience_score(
        self,
        record: ExperienceRecord,
        query_words: set[str],
        state_words: set[str],
    ) -> tuple[float, dict, dict, list[str]]:
        core_text = " ".join([
            record.goal,
            record.task,
            record.outcome,
            record.correction,
            " ".join(record.tags),
            json.dumps(record.causal, default=str),
        ])
        core_words = self._transfer_tokens(core_text)
        base_matches = sorted((query_words & core_words) | (state_words & core_words))
        score = len(query_words & core_words) * 1.6 + len(state_words & core_words) * 0.8
        if record.success:
            score += 0.8
        if record.correction:
            score += 0.4
        score += min(2.0, float(record.metrics.get("success_delta", 0) or 0) * 0.5)

        axis_scores = {}
        axis_matches = {}
        for axis in TRANSFER_AXIS_WEIGHTS:
            axis_words = self._transfer_tokens(json.dumps(self._dimension_axis_value(record.dimensions, axis), default=str))
            if not axis_words:
                axis_scores[axis] = 0.0
                axis_matches[axis] = []
                continue
            query_matches = query_words & axis_words
            state_matches = state_words & axis_words
            axis_score = TRANSFER_AXIS_WEIGHTS[axis] * (len(query_matches) * 2.0 + len(state_matches))
            if axis_score and axis in {"process", "function"} and record.success:
                axis_score += 0.3
            axis_scores[axis] = axis_score
            axis_matches[axis] = sorted(query_matches | state_matches)[:12]
            score += axis_score
        return score, axis_scores, axis_matches, base_matches[:16]

    def _dimension_axis_value(self, dimensions: dict, axis: str):
        if not isinstance(dimensions, dict):
            return ""
        for key in TRANSFER_AXIS_ALIASES.get(axis, (axis,)):
            if key in dimensions:
                return dimensions.get(key)
        return ""

    def _task_payload(self, task) -> dict:
        if task is None:
            return {}
        if isinstance(task, dict):
            payload = dict(task)
        elif hasattr(task, "__dataclass_fields__"):
            payload = asdict(task)
        else:
            payload = {
                "title": getattr(task, "title", ""),
                "type": getattr(task, "type", ""),
                "status": getattr(getattr(task, "status", None), "value", getattr(task, "status", "")),
                "priority": getattr(task, "priority", None),
                "preconditions": getattr(task, "preconditions", {}),
                "success_criteria": getattr(task, "success_criteria", {}),
                "failure_criteria": getattr(task, "failure_criteria", {}),
                "assigned_skill": getattr(task, "assigned_skill", ""),
                "tags": getattr(task, "tags", []),
                "opportunity_triggers": getattr(task, "opportunity_triggers", []),
                "blockers": getattr(task, "blockers", []),
                "rationale": getattr(task, "rationale", ""),
            }
        status = payload.get("status")
        if hasattr(status, "value"):
            payload["status"] = status.value
        return payload

    def _task_memory_query(self, goal: str, task_payload: dict) -> str:
        parts = [goal]
        for key in ("title", "type", "assigned_skill", "rationale"):
            if task_payload.get(key):
                parts.append(str(task_payload.get(key)))
        for key in ("tags", "opportunity_triggers", "blockers"):
            values = task_payload.get(key, [])
            if isinstance(values, list):
                parts.extend(str(value) for value in values)
        for key in ("preconditions", "success_criteria", "failure_criteria"):
            value = task_payload.get(key)
            if value:
                parts.append(json.dumps(value, default=str))
        return " ".join(part for part in parts if str(part or "").strip())

    def _build_task_continuity_record(
        self,
        goal: str,
        task_system=None,
        current_state: Optional[dict] = None,
        plan: Optional[dict] = None,
        source: str = "agent",
        max_tasks: int = 12,
    ) -> TaskContinuityRecord:
        current_state = current_state or {}
        plan = plan or {}
        task_payloads = self._task_continuity_payloads(task_system, current_state, max_tasks=max_tasks)
        status_counts = {}
        for task in task_payloads:
            status = str(task.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1

        ready_tasks = [task for task in task_payloads if task.get("continuity_ready")]
        active_tasks = [task for task in task_payloads if task.get("status") == "active"]
        blocked_tasks = [
            task for task in task_payloads
            if task.get("status") in {"blocked", "waiting"} or task.get("missing_preconditions") or task.get("blockers")
        ]
        failed_tasks = [task for task in task_payloads if task.get("status") == "failed"]
        plan_actions = self._task_continuity_plan_actions(plan)
        next_actions = self._task_continuity_next_actions(ready_tasks, blocked_tasks, failed_tasks, plan_actions)
        summary = self._task_continuity_summary(goal, status_counts, ready_tasks, blocked_tasks, failed_tasks, plan_actions)
        return TaskContinuityRecord(
            goal=str(goal or ""),
            source=str(source or "agent"),
            summary=summary,
            status_counts=dict(sorted(status_counts.items())),
            ready_tasks=ready_tasks[:6],
            active_tasks=active_tasks[:6],
            blocked_tasks=blocked_tasks[:6],
            failed_tasks=failed_tasks[:6],
            next_actions=next_actions[:8],
            plan_status=str(plan.get("status") or ""),
            plan_reasoning=str(plan.get("reasoning") or "")[:500],
            state_summary=self._task_continuity_state_summary(current_state),
        )

    def _build_task_continuity_record_from_session_events(
        self,
        events: list[dict],
        source_log: str = "",
        source: str = "session_import",
    ) -> Optional[TaskContinuityRecord]:
        events = [event for event in events or [] if isinstance(event, dict)]
        if not events:
            return None
        goal = self._session_continuity_goal(events)
        current_state = self._session_continuity_current_state(events)
        plan = self._session_continuity_plan(events)
        failed_actions = self._session_failed_action_summaries(events)
        if not goal and not plan and not current_state and not failed_actions:
            return None

        task_payloads = self._session_continuity_task_payloads(plan, current_state, failed_actions, goal)
        status_counts = {}
        for task in task_payloads:
            self._increment_count(status_counts, task.get("status") or "unknown")
        ready_tasks = [task for task in task_payloads if task.get("continuity_ready")]
        active_tasks = [task for task in task_payloads if task.get("status") == "active"]
        blocked_tasks = [
            task for task in task_payloads
            if task.get("status") in {"blocked", "waiting"} or task.get("missing_preconditions") or task.get("blockers")
        ]
        failed_tasks = [task for task in task_payloads if task.get("status") == "failed"]
        plan_actions = self._task_continuity_plan_actions(plan)
        next_actions = self._task_continuity_next_actions(ready_tasks, blocked_tasks, failed_tasks, plan_actions)
        if source_log:
            next_actions.append(f"review source session log: {source_log}")
        summary = self._task_continuity_summary(goal, status_counts, ready_tasks, blocked_tasks, failed_tasks, plan_actions)
        if failed_actions:
            summary = (summary + f" | failed_actions={len(failed_actions)}").strip(" |")
        return TaskContinuityRecord(
            goal=str(goal or ""),
            source=str(source or "session_import"),
            summary=summary,
            status_counts=dict(sorted(status_counts.items())),
            ready_tasks=ready_tasks[:6],
            active_tasks=active_tasks[:6],
            blocked_tasks=blocked_tasks[:6],
            failed_tasks=failed_tasks[:6],
            next_actions=self._dedupe_text(next_actions)[:8],
            plan_status=str(plan.get("status") or "session_import"),
            plan_reasoning=str(plan.get("reasoning") or self._session_continuity_reasoning(events))[:500],
            state_summary={
                **self._task_continuity_state_summary(current_state),
                "source_log": source_log,
                "event_count": len(events),
            },
        )

    def _session_continuity_goal(self, events: list[dict]) -> str:
        for event in reversed(events):
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            event_type = event.get("type")
            if event_type in {"goal_start", "goal_end"} and data.get("goal"):
                return str(data.get("goal"))
            if isinstance(data.get("goal"), str) and data.get("goal"):
                return str(data.get("goal"))
            context = data.get("action_context", {}) if isinstance(data.get("action_context", {}), dict) else {}
            if context.get("goal"):
                return str(context.get("goal"))
        return ""

    def _session_continuity_current_state(self, events: list[dict]) -> dict:
        for event in reversed(events):
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            if event.get("type") == "action":
                post = data.get("post_observation", {})
                if isinstance(post, dict) and post:
                    return post
                pre = data.get("pre_observation", {})
                if isinstance(pre, dict) and pre:
                    return pre
            if event.get("type") == "observation" and data:
                return data
            if event.get("type") == "vision" and data:
                return data
        return {}

    def _session_continuity_plan(self, events: list[dict]) -> dict:
        for event in reversed(events):
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            if event.get("type") == "plan" and data:
                return data
            if event.get("type") in {"planner_fallback", "plan_cache_hit"}:
                plan = data.get("plan", {})
                if isinstance(plan, dict) and plan:
                    return plan
        return {}

    def _session_continuity_reasoning(self, events: list[dict]) -> str:
        for event in reversed(events):
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            if event.get("type") == "reflection":
                return str(data.get("analysis") or data.get("suggestion") or "")
            if event.get("type") == "error":
                return str(data.get("error") or data)
        return ""

    def _session_failed_action_summaries(self, events: list[dict], limit: int = 6) -> list[dict]:
        failures = []
        for event in reversed(events):
            if event.get("type") != "action":
                continue
            data = event.get("data", {}) if isinstance(event.get("data", {}), dict) else {}
            action = data.get("action", {}) if isinstance(data.get("action", {}), dict) else {}
            result = data.get("result", {}) if isinstance(data.get("result", {}), dict) else {}
            if result.get("success") is not False:
                continue
            action_type = str(action.get("type") or result.get("action_type") or "action")
            params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
            target = params.get("item") or params.get("block") or params.get("target") or params.get("entity")
            error = str(result.get("error") or "action failed")[:180]
            failures.append({
                "action_type": action_type,
                "target": str(target or "")[:120],
                "error": error,
            })
            if len(failures) >= limit:
                break
        return list(reversed(failures))

    def _session_continuity_task_payloads(
        self,
        plan: dict,
        current_state: dict,
        failed_actions: list[dict],
        goal: str,
    ) -> list[dict]:
        payloads = []
        subtasks = plan.get("subtasks", []) if isinstance(plan, dict) else []
        if isinstance(subtasks, list):
            for index, subtask in enumerate(subtasks[:10], start=1):
                if not isinstance(subtask, dict):
                    continue
                compact = {
                    "id": f"imported_subtask_{index}",
                    "title": str(subtask.get("title") or f"Imported subtask {index}")[:120],
                    "type": str(subtask.get("type") or "general")[:60],
                    "status": "accepted",
                    "priority": subtask.get("priority", 3),
                    "attempts": 0,
                    "preconditions": subtask.get("preconditions", {}) if isinstance(subtask.get("preconditions", {}), dict) else {},
                    "success_criteria": subtask.get("success_criteria", {}) if isinstance(subtask.get("success_criteria", {}), dict) else {},
                    "blockers": [],
                    "depends_on": list(subtask.get("depends_on", []) or [])[:6] if isinstance(subtask.get("depends_on", []), list) else [],
                    "tags": list(subtask.get("tags", []) or [])[:8] if isinstance(subtask.get("tags", []), list) else [],
                    "opportunity_triggers": list(subtask.get("opportunity_triggers", []) or [])[:8] if isinstance(subtask.get("opportunity_triggers", []), list) else [],
                    "rationale": str(subtask.get("rationale") or "")[:180],
                }
                missing = self._task_continuity_missing_preconditions(compact["preconditions"], current_state or {})
                if missing:
                    compact["missing_preconditions"] = missing
                compact["continuity_ready"] = not bool(compact.get("depends_on")) and not bool(missing)
                payloads.append(compact)
        plan_status = str(plan.get("status") or "").lower() if isinstance(plan, dict) else ""
        actions = plan.get("actions", []) if isinstance(plan, dict) and isinstance(plan.get("actions", []), list) else []
        if plan_status in {"blocked", "error"} or (plan and not actions and not payloads):
            reason = str(plan.get("reasoning") or plan_status or "plan produced no executable actions")[:180]
            payloads.append({
                "id": "imported_blocked_plan",
                "title": f"Resolve blocked plan for {goal or 'session goal'}"[:120],
                "type": "recovery",
                "status": "blocked",
                "priority": 1,
                "attempts": 0,
                "preconditions": {},
                "success_criteria": {},
                "blockers": [reason],
                "depends_on": [],
                "tags": ["session_import", "blocked_plan"],
                "opportunity_triggers": [],
                "rationale": "Imported from stalled or blocked planner output",
                "continuity_ready": False,
            })
        for index, failure in enumerate(failed_actions[:4], start=1):
            label = f"{failure.get('action_type', 'action')}:{failure.get('target')}" if failure.get("target") else failure.get("action_type", "action")
            payloads.append({
                "id": f"imported_failed_action_{index}",
                "title": f"Recover from failed {label}"[:120],
                "type": "recovery",
                "status": "failed",
                "priority": 2,
                "attempts": 1,
                "preconditions": {},
                "success_criteria": {},
                "blockers": [failure.get("error", "action failed")],
                "depends_on": [],
                "tags": ["session_import", "failed_action", str(failure.get("action_type") or "")],
                "opportunity_triggers": [str(failure.get("target") or "")] if failure.get("target") else [],
                "rationale": "Imported from failed action trace",
                "continuity_ready": False,
            })
        return payloads

    def _task_continuity_payloads(self, task_system, current_state: dict, max_tasks: int = 12) -> list[dict]:
        tasks = getattr(task_system, "tasks", {}) if task_system is not None else {}
        if not isinstance(tasks, dict):
            return []
        ready_ids = set()
        try:
            for task in task_system.get_ready_tasks(current_state or {}):
                ready_ids.add(str(getattr(task, "id", "")))
        except Exception:
            ready_ids = set()
        payloads = []
        for task in tasks.values():
            payload = self._task_payload(task)
            task_id = str(payload.get("id") or getattr(task, "id", ""))
            compact = {
                "id": task_id,
                "title": str(payload.get("title") or "")[:120],
                "type": str(payload.get("type") or "general")[:60],
                "status": str(payload.get("status") or "unknown"),
                "priority": payload.get("priority"),
                "attempts": payload.get("attempts", 0),
                "preconditions": payload.get("preconditions", {}) if isinstance(payload.get("preconditions", {}), dict) else {},
                "success_criteria": payload.get("success_criteria", {}) if isinstance(payload.get("success_criteria", {}), dict) else {},
                "blockers": list(payload.get("blockers", []) or [])[:5] if isinstance(payload.get("blockers", []), list) else [],
                "depends_on": list(payload.get("depends_on", []) or [])[:6] if isinstance(payload.get("depends_on", []), list) else [],
                "tags": list(payload.get("tags", []) or [])[:8] if isinstance(payload.get("tags", []), list) else [],
                "opportunity_triggers": list(payload.get("opportunity_triggers", []) or [])[:8] if isinstance(payload.get("opportunity_triggers", []), list) else [],
                "rationale": str(payload.get("rationale") or "")[:180],
                "continuity_ready": bool(task_id and task_id in ready_ids),
            }
            missing = self._task_continuity_missing_preconditions(compact["preconditions"], current_state or {})
            if missing:
                compact["missing_preconditions"] = missing
            payloads.append(compact)
        payloads.sort(key=lambda item: (
            0 if item.get("continuity_ready") else 1,
            self._status_continuity_rank(item.get("status")),
            self._safe_int(item.get("priority") or 5),
            -self._safe_int(item.get("attempts") or 0),
            item.get("title", ""),
        ))
        return payloads[:max(1, self._safe_int(max_tasks or 12))]

    def _task_continuity_missing_preconditions(self, preconditions: dict, current_state: dict) -> dict:
        if not isinstance(preconditions, dict):
            return {}
        missing = {}
        inventory = current_state.get("inventory", {}) if isinstance(current_state.get("inventory", {}), dict) else {}
        required_inventory = preconditions.get("inventory", {}) if isinstance(preconditions.get("inventory", {}), dict) else {}
        inventory_missing = {}
        for item, count in required_inventory.items():
            needed = self._safe_int(count)
            have = self._safe_int(inventory.get(item, 0))
            if needed > have:
                inventory_missing[str(item)] = needed - have
        if inventory_missing:
            missing["inventory"] = dict(sorted(inventory_missing.items()))
        required_flags = preconditions.get("flags", []) if isinstance(preconditions.get("flags", []), list) else []
        flags = {str(flag) for flag in current_state.get("flags", [])} if isinstance(current_state.get("flags", []), list) else set()
        flag_missing = [str(flag) for flag in required_flags if str(flag) not in flags]
        if flag_missing:
            missing["flags"] = flag_missing
        nearby_required = preconditions.get("nearby_block_present", [])
        nearby_missing = self._task_continuity_missing_observed_names(nearby_required, current_state or {})
        if nearby_missing:
            missing["nearby_block_present"] = nearby_missing
        return missing

    def _task_continuity_missing_observed_names(self, required, current_state: dict) -> list[str]:
        required_names = self._task_continuity_required_names(required)
        if not required_names:
            return []
        observed = self._task_continuity_observed_names(current_state or {})
        return sorted(name for name in required_names if name not in observed)

    def _task_continuity_required_names(self, required) -> set[str]:
        if isinstance(required, str):
            return {required.lower()} if required else set()
        if isinstance(required, dict):
            return {
                str(value).lower()
                for value in required.values()
                if value
            }
        if isinstance(required, list):
            return {
                str(value).lower()
                for value in required
                if value
            }
        return set()

    def _task_continuity_observed_names(self, current_state: dict) -> set[str]:
        names = set()
        for key in ("nearby_blocks", "grounded_resources", "trees_found", "nearby_entities", "landmarks"):
            values = current_state.get(key, []) if isinstance(current_state, dict) else []
            if not isinstance(values, list):
                continue
            for item in values:
                if isinstance(item, str):
                    names.add(item.lower())
                    continue
                if not isinstance(item, dict):
                    continue
                for field_name in ("name", "type", "block", "resource", "drop", "entity"):
                    value = item.get(field_name)
                    if value:
                        names.add(str(value).lower())
        if isinstance(current_state, dict) and current_state.get("landmarks"):
            names.add("landmark")
        return names

    def _task_continuity_plan_actions(self, plan: dict) -> list[str]:
        actions = plan.get("actions", []) if isinstance(plan, dict) else []
        if not isinstance(actions, list):
            return []
        labels = []
        for action in actions[:8]:
            if not isinstance(action, dict):
                continue
            action_type = str(action.get("type") or "action")
            params = action.get("parameters", {}) if isinstance(action.get("parameters", {}), dict) else {}
            target = params.get("item") or params.get("block") or params.get("target") or params.get("entity")
            labels.append(f"{action_type}:{target}" if target else action_type)
        return labels

    def _task_continuity_next_actions(
        self,
        ready_tasks: list[dict],
        blocked_tasks: list[dict],
        failed_tasks: list[dict],
        plan_actions: list[str],
    ) -> list[str]:
        actions = []
        for task in ready_tasks[:3]:
            if task.get("title"):
                actions.append(f"continue ready task: {task['title']}")
        for task in blocked_tasks[:3]:
            missing = task.get("missing_preconditions", {})
            if missing:
                actions.append(f"satisfy missing preconditions for {task.get('title', 'task')}: {json.dumps(missing, default=str)[:120]}")
            elif task.get("blockers"):
                actions.append(f"resolve blocker for {task.get('title', 'task')}: {str(task['blockers'][0])[:100]}")
        for task in failed_tasks[:2]:
            actions.append(f"replan failed task: {task.get('title', 'task')}")
        for action in plan_actions[:3]:
            actions.append(f"candidate action from last plan: {action}")
        return self._dedupe_text(actions)

    def _task_continuity_summary(
        self,
        goal: str,
        status_counts: dict,
        ready_tasks: list[dict],
        blocked_tasks: list[dict],
        failed_tasks: list[dict],
        plan_actions: list[str],
    ) -> str:
        parts = [f"goal={str(goal or '')[:100]}"]
        if status_counts:
            parts.append("statuses=" + ",".join(f"{key}:{value}" for key, value in sorted(status_counts.items())))
        if ready_tasks:
            parts.append("ready=" + "; ".join(task.get("title", "")[:80] for task in ready_tasks[:3]))
        if blocked_tasks:
            parts.append("blocked=" + "; ".join(task.get("title", "")[:80] for task in blocked_tasks[:3]))
        if failed_tasks:
            parts.append("failed=" + "; ".join(task.get("title", "")[:80] for task in failed_tasks[:3]))
        if plan_actions:
            parts.append("last_actions=" + ",".join(plan_actions[:5]))
        return " | ".join(part for part in parts if part)

    def _task_continuity_state_summary(self, current_state: dict) -> dict:
        if not isinstance(current_state, dict):
            return {}
        inventory = current_state.get("inventory", {}) if isinstance(current_state.get("inventory", {}), dict) else {}
        nearby_blocks = current_state.get("nearby_blocks", []) if isinstance(current_state.get("nearby_blocks", []), list) else []
        nearby_entities = current_state.get("nearby_entities", []) if isinstance(current_state.get("nearby_entities", []), list) else []
        position = current_state.get("position", {}) if isinstance(current_state.get("position", {}), dict) else {}
        return {
            "inventory": {
                str(item): self._safe_int(count)
                for item, count in sorted(inventory.items())
                if self._safe_int(count) > 0
            },
            "nearby_blocks": self._dedupe_text([
                str(block.get("name") or block.get("type") or "")
                for block in nearby_blocks
                if isinstance(block, dict) and (block.get("name") or block.get("type"))
            ])[:12],
            "nearby_entities": self._dedupe_text([
                str(entity.get("type") or entity.get("name") or "")
                for entity in nearby_entities
                if isinstance(entity, dict) and (entity.get("type") or entity.get("name"))
            ])[:8],
            "position": {
                key: round(float(position.get(key)), 2)
                for key in ("x", "y", "z")
                if key in position and isinstance(position.get(key), (int, float))
            },
            "health": current_state.get("health"),
            "time_of_day": current_state.get("time_of_day"),
        }

    def _task_continuity_report_matches(self, goal: str, current_state: dict, limit: int = 10) -> list[dict]:
        if str(goal or "").strip() or current_state:
            return self._rank_task_continuity_records(goal, current_state, limit=limit)
        latest = list(reversed(self.task_continuity_records[-max(1, self._safe_int(limit or 10)):]))
        return [
            {
                "record": record,
                "score": round(1.0 / max(1, index + 1), 4),
                "matches": [],
            }
            for index, record in enumerate(latest)
        ]

    def _task_continuity_report_record(self, item: dict) -> dict:
        record = item["record"]
        return {
            "id": record.id,
            "goal": record.goal,
            "source": record.source,
            "summary": record.summary,
            "score": item.get("score", 0),
            "matches": item.get("matches", []),
            "created_at": round(float(record.created_at or 0.0), 3),
            "age_s": max(0, int(time.time() - record.created_at)),
            "status_counts": dict(record.status_counts or {}),
            "ready_task_count": len(record.ready_tasks),
            "blocked_task_count": len(record.blocked_tasks),
            "failed_task_count": len(record.failed_tasks),
            "next_actions": list(record.next_actions or [])[:8],
            "plan_status": record.plan_status,
            "plan_reasoning": record.plan_reasoning[:300],
            "state_summary": dict(record.state_summary or {}),
        }

    def _task_continuity_resume_candidate(self, record: TaskContinuityRecord, task: dict, bucket: str) -> dict:
        return {
            "checkpoint_id": record.id,
            "checkpoint_goal": record.goal,
            "checkpoint_source": record.source,
            "task_id": str(task.get("id") or ""),
            "title": str(task.get("title") or "")[:160],
            "type": str(task.get("type") or "general")[:80],
            "status": str(task.get("status") or "unknown"),
            "status_bucket": bucket,
            "priority": task.get("priority"),
            "attempts": self._safe_int(task.get("attempts", 0)),
            "missing_preconditions": task.get("missing_preconditions", {}) if isinstance(task.get("missing_preconditions", {}), dict) else {},
            "blockers": list(task.get("blockers", []) or [])[:5] if isinstance(task.get("blockers", []), list) else [],
            "depends_on": list(task.get("depends_on", []) or [])[:6] if isinstance(task.get("depends_on", []), list) else [],
            "tags": list(task.get("tags", []) or [])[:8] if isinstance(task.get("tags", []), list) else [],
            "rationale": str(task.get("rationale") or "")[:240],
        }

    def _accumulate_task_missing_preconditions(self, missing: dict, counts: dict, totals: dict):
        if not isinstance(missing, dict):
            return
        for group, value in missing.items():
            if isinstance(value, dict):
                for key, amount in value.items():
                    label = f"{group}.{key}"
                    self._increment_count(counts, label)
                    self._increment_count(totals, label, self._safe_int(amount))
            elif isinstance(value, list):
                for item in value:
                    label = f"{group}.{item}"
                    self._increment_count(counts, label)
                    self._increment_count(totals, label)
            elif value:
                label = f"{group}.{value}"
                self._increment_count(counts, label)
                self._increment_count(totals, label)

    def _dedupe_task_continuity_candidates(self, candidates: list[dict]) -> list[dict]:
        seen = set()
        result = []
        for candidate in candidates:
            key = (
                candidate.get("status_bucket"),
                candidate.get("task_id") or candidate.get("title"),
                json.dumps(candidate.get("missing_preconditions", {}), sort_keys=True, default=str),
                ";".join(str(item) for item in candidate.get("blockers", [])[:3]),
            )
            if key in seen:
                continue
            seen.add(key)
            result.append(candidate)
        result.sort(key=lambda item: (
            self._status_continuity_rank(item.get("status")),
            self._safe_int(item.get("priority") or 5),
            -self._safe_int(item.get("attempts") or 0),
            item.get("title", ""),
        ))
        return result

    def _task_continuity_tokens(self, text: str) -> set[str]:
        generic = {
            "action",
            "actions",
            "active",
            "accepted",
            "attempts",
            "block",
            "blocks",
            "blocked",
            "blocker",
            "blockers",
            "candidate",
            "checkpoint",
            "continuity",
            "created",
            "criteria",
            "current",
            "depends",
            "failed",
            "flags",
            "general",
            "goal",
            "inventory",
            "missing",
            "nearby",
            "nearby_blocks",
            "nearby_entities",
            "parameters",
            "planning",
            "precondition",
            "preconditions",
            "priority",
            "rationale",
            "ready",
            "source",
            "state",
            "status",
            "success",
            "summary",
            "task",
            "tasks",
            "type",
            "unknown",
        }
        return self._transfer_tokens(text) - generic

    def _rank_task_continuity_records(self, goal: str, current_state: dict, limit: int = 3) -> list[dict]:
        query_words = self._task_continuity_tokens(goal)
        state_words = self._task_continuity_tokens(json.dumps(current_state or {}, default=str))
        ranked = []
        for index, record in enumerate(self.task_continuity_records):
            text_words = self._task_continuity_tokens(record.searchable_text())
            query_matches = query_words & text_words
            state_matches = state_words & text_words
            if (query_words or state_words) and not query_matches and not state_matches:
                continue
            matches = sorted(query_matches | state_matches)
            recency_bonus = min(2.0, 1.0 / max(1, len(self.task_continuity_records) - index))
            unresolved_bonus = 0.8 * (len(record.ready_tasks) + len(record.blocked_tasks) + len(record.failed_tasks))
            score = len(query_matches) * 1.4 + len(state_matches) * 0.7 + recency_bonus + unresolved_bonus
            if score <= 0:
                continue
            ranked.append({
                "record": record,
                "score": round(score, 4),
                "matches": matches[:12],
            })
        ranked.sort(key=lambda item: (item["score"], item["record"].created_at), reverse=True)
        return ranked[:max(1, self._safe_int(limit or 3))]

    def _status_continuity_rank(self, status: str) -> int:
        return {
            "active": 0,
            "accepted": 1,
            "waiting": 2,
            "blocked": 3,
            "failed": 4,
            "proposed": 5,
            "completed": 8,
            "cancelled": 9,
        }.get(str(status or "").lower(), 6)

    def _rank_memory_entries_for_query(
        self,
        query: str,
        current_state: Optional[dict] = None,
        limit: int = 5,
        mark_recalled: bool = False,
    ) -> list[dict]:
        query_words = self._transfer_tokens(query)
        state_words = self._transfer_tokens(json.dumps(current_state or {}, default=str))
        ranked = []
        for entry in self.entries.values():
            if not self._entry_applicable(entry, current_state):
                continue
            entry_words = self._transfer_tokens(entry.prompt_line())
            matches = sorted((query_words & entry_words) | (state_words & entry_words))
            if not matches:
                continue
            tag_matches = sorted(query_words & self._transfer_tokens(" ".join(entry.tags)))
            score = (
                len(query_words & entry_words) * 1.3
                + len(state_words & entry_words) * 0.7
                + len(tag_matches) * 0.5
                + entry.importance * entry.confidence
            )
            attribution = self._attribution_hint_for_id(entry.id)
            score = self._apply_attribution_weight(score, attribution)
            ranked.append({
                "id": entry.id,
                "content": entry.content,
                "layer": entry.layer,
                "memory_type": entry.memory_type,
                "tags": list(entry.tags),
                "score": round(score, 4),
                "matches": matches[:12],
                "attribution_weight_delta": attribution.get("weight_delta", 0.0),
                "attribution_policy": attribution.get("policy", ""),
                "source": entry.source,
            })
        ranked.sort(key=lambda item: (item["score"], len(item["matches"])), reverse=True)
        selected = ranked[:limit] if limit and limit > 0 else ranked
        if mark_recalled and selected:
            for item in selected:
                entry = self.entries.get(item["id"])
                if entry:
                    self._mark_entry_recalled(entry, query)
            self._rewrite_entries()
        return selected

    def _build_retrieval_trace(
        self,
        query: str,
        memory_matches: list[dict],
        transfer_matches: list[dict],
        semantic_match_count: int = 0,
        episodic_match_count: int = 0,
        causal_match_count: int = 0,
        source: str = "retrieval",
    ) -> dict:
        profile = self.memory_attribution_profile if isinstance(self.memory_attribution_profile, dict) else {}
        memory_matches = memory_matches if isinstance(memory_matches, list) else []
        transfer_matches = transfer_matches if isinstance(transfer_matches, list) else []
        weighted_memory_ids = self._weighted_retrieval_ids(memory_matches)
        weighted_transfer_ids = self._weighted_retrieval_ids(transfer_matches)
        deltas = []
        policy_counts = {}
        for item in memory_matches + transfer_matches:
            policy = str(item.get("attribution_policy") or "").strip()
            if policy:
                policy_counts[policy] = policy_counts.get(policy, 0) + 1
            delta = self._bounded_attribution_delta(item.get("attribution_weight_delta"))
            if delta:
                deltas.append(delta)
        positive_deltas = [delta for delta in deltas if delta > 0]
        negative_deltas = [delta for delta in deltas if delta < 0]
        total_match_count = (
            len(memory_matches)
            + len(transfer_matches)
            + max(0, int(semantic_match_count or 0))
            + max(0, int(episodic_match_count or 0))
            + max(0, int(causal_match_count or 0))
        )
        return {
            "trace_version": "weighted_retrieval_v1",
            "source": str(source or "retrieval"),
            "query_hash": self._query_hash(query),
            "weighted_retrieval_enabled": bool(profile.get("enabled")),
            "attribution_hint_count": _safe_int(profile.get("hint_count", 0)),
            "total_match_count": total_match_count,
            "memory_match_count": len(memory_matches),
            "transfer_match_count": len(transfer_matches),
            "semantic_match_count": max(0, int(semantic_match_count or 0)),
            "episodic_match_count": max(0, int(episodic_match_count or 0)),
            "causal_match_count": max(0, int(causal_match_count or 0)),
            "weighted_match_count": len(weighted_memory_ids) + len(weighted_transfer_ids),
            "weighted_memory_match_count": len(weighted_memory_ids),
            "weighted_transfer_match_count": len(weighted_transfer_ids),
            "top_memory_ids": self._retrieval_ids(memory_matches),
            "top_transfer_ids": self._retrieval_ids(transfer_matches),
            "top_weighted_memory_ids": weighted_memory_ids,
            "top_weighted_transfer_ids": weighted_transfer_ids,
            "attribution_policy_counts": dict(sorted(policy_counts.items())),
            "max_positive_weight_delta": round(max(positive_deltas), 3) if positive_deltas else 0.0,
            "max_negative_weight_delta": round(min(negative_deltas), 3) if negative_deltas else 0.0,
            "max_abs_weight_delta": round(max((abs(delta) for delta in deltas), default=0.0), 3),
        }

    def _retrieval_ids(self, items: list[dict], limit: int = 8) -> list[str]:
        ids = []
        for item in (items if isinstance(items, list) else []):
            memory_id = str(item.get("id") or item.get("memory_id") or "").strip()
            if memory_id and memory_id not in ids:
                ids.append(memory_id)
            if len(ids) >= limit:
                break
        return ids

    def _weighted_retrieval_ids(self, items: list[dict], limit: int = 8) -> list[str]:
        weighted = []
        for item in (items if isinstance(items, list) else []):
            delta = self._bounded_attribution_delta(item.get("attribution_weight_delta"))
            if not delta:
                continue
            memory_id = str(item.get("id") or item.get("memory_id") or "").strip()
            if memory_id and memory_id not in weighted:
                weighted.append(memory_id)
            if len(weighted) >= limit:
                break
        return weighted

    def _query_hash(self, query: str) -> str:
        text = str(query or "").strip().lower()
        if not text:
            return ""
        return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:12]

    def _mark_entry_recalled(self, entry: MemoryEntry, query: str):
        entry.uses += 1
        entry.last_recalled_at = time.time()
        entry.updated_at = entry.last_recalled_at
        self._remember_query(entry.recall_queries, query)

    def _mark_experience_recalled(self, record: ExperienceRecord, query: str):
        record.uses += 1
        record.last_recalled_at = time.time()
        self._remember_query(record.recall_queries, query)

    def _remember_query(self, recall_queries: list[str], query: str):
        signature = self._query_signature(query)
        if not signature:
            return
        if signature not in recall_queries:
            recall_queries.append(signature)
        if len(recall_queries) > 20:
            del recall_queries[:-20]

    def _attribution_hint_for_id(self, memory_id: str) -> dict:
        profile = self.memory_attribution_profile if isinstance(self.memory_attribution_profile, dict) else {}
        if not profile.get("enabled"):
            return {}
        hints = profile.get("hints_by_id", {}) if isinstance(profile.get("hints_by_id", {}), dict) else {}
        return hints.get(str(memory_id or "").strip(), {}) if hints else {}

    def _apply_attribution_weight(self, score: float, attribution: dict) -> float:
        if not attribution:
            return score
        delta = self._bounded_attribution_delta(attribution.get("weight_delta"))
        return max(0.0, float(score or 0.0) * (1.0 + delta))

    def _bounded_attribution_delta(self, value) -> float:
        try:
            delta = float(value or 0.0)
        except (TypeError, ValueError):
            delta = 0.0
        return max(-0.5, min(0.5, delta))

    def _entry_applicable(self, entry: MemoryEntry, current_state: Optional[dict] = None) -> bool:
        return not self._entry_filter_reasons(entry, current_state)

    def _entry_filter_reasons(self, entry: MemoryEntry, current_state: Optional[dict] = None) -> list[str]:
        metadata = entry.metadata or {}
        validity = str(metadata.get("validity") or metadata.get("evidence_status") or "").lower()
        reasons = []
        if validity in {"stale", "superseded", "contradicted", "invalidated", "out_of_scope", "adversarial"}:
            reasons.append(validity)
        if metadata.get("superseded_by") or metadata.get("invalidated_by"):
            reasons.append("superseded")
        if metadata.get("state_revision") and validity in {"implicit_conflict", "superseded"}:
            reasons.append("state_revision_review")

        applies_when = metadata.get("applies_when", {})
        if isinstance(applies_when, dict) and applies_when and current_state is not None:
            for key, expected in applies_when.items():
                actual = self._nested_value(current_state, str(key))
                if actual != expected:
                    reasons.append("conditional_mismatch")
                    break
        reasons.extend(promptware_threat_flags(self._entry_security_payload(entry)))
        return sorted(set(reasons))

    def _experience_filter_reasons(self, record: ExperienceRecord) -> list[str]:
        return promptware_threat_flags(self._experience_security_payload(record))

    def _entry_security_payload(self, entry: MemoryEntry) -> dict:
        return {
            "content": entry.content,
            "tags": entry.tags,
            "source": entry.source,
            "metadata": entry.metadata,
        }

    def _experience_security_payload(self, record: ExperienceRecord) -> dict:
        return {
            "goal": record.goal,
            "task": record.task,
            "outcome": record.outcome,
            "correction": record.correction,
            "actions": record.actions,
            "observations": record.observations,
            "dimensions": record.dimensions,
            "causal": record.causal,
            "metrics": record.metrics,
            "tags": record.tags,
        }

    def _payload_fingerprint(self, payload: dict) -> str:
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def _nested_value(self, data: dict, dotted_key: str):
        current = data
        for part in dotted_key.split("."):
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        return current

    def _query_signature(self, query: str) -> str:
        words = sorted(self._keywords(query))
        return " ".join(words[:8])

    def _memory_consolidation_score(self, entry: MemoryEntry) -> float:
        quality = entry.importance * entry.confidence
        return self._consolidation_score(quality, entry.uses, len(set(entry.recall_queries)), entry.last_recalled_at)

    def _experience_consolidation_score(self, record: ExperienceRecord) -> float:
        quality = 0.55 if record.success else 0.25
        if record.correction:
            quality += 0.1
        quality += min(0.2, float(record.metrics.get("success_delta", 0) or 0) * 0.05)
        return self._consolidation_score(min(1.0, quality), record.uses, len(set(record.recall_queries)), record.last_recalled_at)

    def _consolidation_score(self, quality: float, uses: int, unique_queries: int, last_recalled_at: float) -> float:
        recall_signal = min(1.0, uses / 5)
        diversity_signal = min(1.0, unique_queries / 3)
        if last_recalled_at:
            age_days = max(0.0, (time.time() - last_recalled_at) / 86400)
            recency_signal = max(0.0, 1.0 - min(1.0, age_days / 14))
        else:
            recency_signal = 0.0
        return (
            0.45 * max(0.0, min(1.0, quality))
            + 0.25 * recall_signal
            + 0.20 * diversity_signal
            + 0.10 * recency_signal
        )


def build_memory_promptware_gate(
    report_paths: list[str] = None,
    reports: list[dict] = None,
    max_flagged_entries: int = 0,
    max_flagged_experiences: int = 0,
) -> dict:
    """Gate stricter memory enforcement on saved promptware audit reports."""
    report_paths = [str(path or "").strip() for path in (report_paths or []) if str(path or "").strip()]
    max_flagged_entries = max(0, int(max_flagged_entries or 0))
    max_flagged_experiences = max(0, int(max_flagged_experiences or 0))
    gate = {
        "type": "memory_promptware_gate",
        "readiness": "review",
        "decision": "hold_memory_promptware_enforcement",
        "reason": "memory promptware gate needs saved audit reports",
        "report_paths": list(report_paths),
        "report_count": 0,
        "max_flagged_entries": max_flagged_entries,
        "max_flagged_experiences": max_flagged_experiences,
        "total_entries": 0,
        "total_experiences": 0,
        "flagged_entry_count": 0,
        "flagged_experience_count": 0,
        "promptware_threat_count": 0,
        "reason_counts": {},
        "reports": [],
        "checks": [],
        "missing": [],
        "errors": [],
    }
    loaded_reports = []
    for index, payload in enumerate(reports or [], start=1):
        if isinstance(payload, dict):
            loaded_reports.append((f"inline:{index}", payload))
        else:
            gate["errors"].append(f"inline:{index}: memory promptware report must be a JSON object")
    for path in report_paths:
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                raise ValueError("memory promptware report must be a JSON object")
            loaded_reports.append((path, payload))
        except Exception as exc:
            gate["errors"].append(f"{path}: {exc}")

    if not loaded_reports and not gate["errors"]:
        gate["missing"].append("memory_promptware_report")
        gate["checks"].append(_memory_promptware_gate_check(
            "memory_promptware_report",
            "warn",
            "no memory promptware report was provided",
            {"report_count": 0},
        ))

    for source, payload in loaded_reports:
        report_type = str(payload.get("type") or "").strip()
        if report_type and report_type != "memory_promptware_report":
            gate["errors"].append(f"{source}: report type must be memory_promptware_report")
            continue
        if "flagged_entry_count" not in payload or "flagged_experience_count" not in payload:
            gate["errors"].append(f"{source}: missing flagged memory promptware counts")
            continue
        entry_count = _safe_int(payload.get("flagged_entry_count", 0))
        experience_count = _safe_int(payload.get("flagged_experience_count", 0))
        reason_counts = payload.get("reason_counts", {}) if isinstance(payload.get("reason_counts", {}), dict) else {}
        normalized_reasons = {
            str(reason): _safe_int(count)
            for reason, count in reason_counts.items()
        }
        summary = {
            "path": source,
            "query": str(payload.get("query") or ""),
            "total_entries": _safe_int(payload.get("total_entries", 0)),
            "total_experiences": _safe_int(payload.get("total_experiences", 0)),
            "flagged_entry_count": entry_count,
            "flagged_experience_count": experience_count,
            "reason_counts": normalized_reasons,
        }
        gate["reports"].append(summary)
        gate["report_count"] += 1
        gate["total_entries"] += summary["total_entries"]
        gate["total_experiences"] += summary["total_experiences"]
        gate["flagged_entry_count"] += entry_count
        gate["flagged_experience_count"] += experience_count
        for reason, count in normalized_reasons.items():
            gate["reason_counts"][reason] = gate["reason_counts"].get(reason, 0) + count
        gate["checks"].append(_memory_promptware_gate_check(
            source,
            "pass" if entry_count <= max_flagged_entries and experience_count <= max_flagged_experiences else "fail",
            (
                "memory promptware report is within configured thresholds"
                if entry_count <= max_flagged_entries and experience_count <= max_flagged_experiences
                else "memory promptware report exceeds configured thresholds"
            ),
            {
                "flagged_entry_count": entry_count,
                "flagged_experience_count": experience_count,
                "max_flagged_entries": max_flagged_entries,
                "max_flagged_experiences": max_flagged_experiences,
            },
        ))

    gate["promptware_threat_count"] = _safe_int(gate["reason_counts"].get("promptware_threat", 0))
    if gate["errors"]:
        gate["readiness"] = "error"
        gate["decision"] = "block_memory_promptware_enforcement"
        gate["reason"] = "memory promptware gate inputs could not be loaded"
    elif gate["flagged_entry_count"] > max_flagged_entries or gate["flagged_experience_count"] > max_flagged_experiences:
        gate["readiness"] = "rejected"
        gate["decision"] = "block_memory_promptware_enforcement"
        gate["reason"] = "memory promptware audit found flagged durable memory content"
    elif gate["missing"]:
        gate["readiness"] = "review"
        gate["decision"] = "hold_memory_promptware_enforcement"
        gate["reason"] = "memory promptware gate is missing audit evidence"
    elif gate["report_count"]:
        gate["readiness"] = "approved"
        gate["decision"] = "allow_strict_memory_promptware_enforcement"
        gate["reason"] = "memory promptware audits are within configured thresholds"
    return gate


def evaluate_memory_promptware_runtime_gate(
    gate_paths: list[str] = None,
    enforce_requested: bool = False,
) -> dict:
    """Evaluate saved memory-promptware-gate reports before enabling strict writes."""
    clean_paths = [str(path or "").strip() for path in (gate_paths or []) if str(path or "").strip()]
    report = {
        "type": "memory_promptware_runtime_gate",
        "required": bool(enforce_requested),
        "requested_enforce_write_gate": bool(enforce_requested),
        "effective_enforce_write_gate": False,
        "readiness": "not_required" if not enforce_requested else "review",
        "decision": "skip_memory_promptware_runtime_gate" if not enforce_requested else "hold_strict_memory_write_gate",
        "reason": "strict memory write gate is not requested",
        "gate_paths": clean_paths,
        "gate_count": 0,
        "approved_gate_count": 0,
        "review_gate_count": 0,
        "rejected_gate_count": 0,
        "error_gate_count": 0,
        "gate_readiness": "not_required" if not enforce_requested else "missing",
        "gate_approved": not bool(enforce_requested),
        "gate_reports": [],
        "missing": [],
        "errors": [],
    }
    if not enforce_requested:
        return report
    if not clean_paths:
        report["reason"] = "strict memory write gate requires approved memory promptware gate reports"
        report["missing"].append("memory_promptware_gate")
        return report

    readinesses = []
    for path in clean_paths:
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                raise ValueError("memory promptware gate must be a JSON object")
            if str(payload.get("type") or "").strip() != "memory_promptware_gate":
                raise ValueError("report type must be memory_promptware_gate")
            readiness = str(payload.get("readiness") or "").strip().lower() or "unknown"
            summary = {
                "path": path,
                "readiness": readiness,
                "decision": str(payload.get("decision") or "").strip(),
                "reason": str(payload.get("reason") or "").strip()[:300],
                "report_count": _safe_int(payload.get("report_count", 0)),
                "flagged_entry_count": _safe_int(payload.get("flagged_entry_count", 0)),
                "flagged_experience_count": _safe_int(payload.get("flagged_experience_count", 0)),
                "promptware_threat_count": _safe_int(payload.get("promptware_threat_count", 0)),
            }
            report["gate_reports"].append(summary)
            report["gate_count"] += 1
            readinesses.append(readiness)
            if readiness == "approved":
                report["approved_gate_count"] += 1
            elif readiness == "rejected":
                report["rejected_gate_count"] += 1
            elif readiness == "error":
                report["error_gate_count"] += 1
            else:
                report["review_gate_count"] += 1
        except Exception as exc:
            report["errors"].append(f"{path}: {exc}")

    if report["errors"]:
        report["readiness"] = "error"
        report["gate_readiness"] = "error"
        report["decision"] = "disable_strict_memory_write_gate"
        report["reason"] = "memory promptware runtime gate inputs could not be loaded"
    elif any(readiness == "error" for readiness in readinesses):
        report["readiness"] = "error"
        report["gate_readiness"] = "error"
        report["decision"] = "disable_strict_memory_write_gate"
        report["reason"] = "memory promptware gate has error readiness"
    elif any(readiness == "rejected" for readiness in readinesses):
        report["readiness"] = "rejected"
        report["gate_readiness"] = "rejected"
        report["decision"] = "disable_strict_memory_write_gate"
        report["reason"] = "memory promptware gate rejected strict enforcement"
    elif readinesses and all(readiness == "approved" for readiness in readinesses):
        report["readiness"] = "approved"
        report["gate_readiness"] = "approved"
        report["gate_approved"] = True
        report["effective_enforce_write_gate"] = True
        report["decision"] = "enable_strict_memory_write_gate"
        report["reason"] = "approved memory promptware gates allow strict memory write enforcement"
    else:
        report["readiness"] = "review"
        report["gate_readiness"] = "review" if readinesses else "missing"
        report["decision"] = "hold_strict_memory_write_gate"
        report["reason"] = "memory promptware gate is not approved"
    return report


def evaluate_memory_attribution_runtime_gate(
    gate_paths: list[str] = None,
    enable_requested: bool = False,
) -> dict:
    """Evaluate saved memory-attribution-gate reports before weighted retrieval."""
    clean_paths = [str(path or "").strip() for path in (gate_paths or []) if str(path or "").strip()]
    report = {
        "type": "memory_attribution_runtime_gate",
        "required": bool(enable_requested),
        "requested_enable_weighted_memory_retrieval": bool(enable_requested),
        "effective_enable_weighted_memory_retrieval": False,
        "readiness": "not_required" if not enable_requested else "review",
        "decision": "skip_memory_attribution_runtime_gate" if not enable_requested else "hold_weighted_memory_retrieval",
        "reason": "weighted memory retrieval is not requested",
        "gate_paths": clean_paths,
        "gate_count": 0,
        "approved_gate_count": 0,
        "review_gate_count": 0,
        "rejected_gate_count": 0,
        "error_gate_count": 0,
        "gate_readiness": "not_required" if not enable_requested else "missing",
        "gate_approved": not bool(enable_requested),
        "gate_reports": [],
        "retrieval_weight_hints": [],
        "retrieval_weight_hint_count": 0,
        "missing": [],
        "errors": [],
    }
    if not enable_requested:
        return report
    if not clean_paths:
        report["reason"] = "weighted memory retrieval requires approved memory attribution gate reports"
        report["missing"].append("memory_attribution_gate")
        return report

    readinesses = []
    for path in clean_paths:
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                raise ValueError("memory attribution gate must be a JSON object")
            if str(payload.get("type") or "").strip() != "memory_attribution_gate":
                raise ValueError("report type must be memory_attribution_gate")
            readiness = str(payload.get("readiness") or "").strip().lower() or "unknown"
            summary = {
                "path": path,
                "readiness": readiness,
                "decision": str(payload.get("decision") or "").strip(),
                "reason": str(payload.get("reason") or "").strip()[:300],
                "memory_read_count": _safe_int(payload.get("memory_read_count", 0)),
                "attributed_read_count": _safe_int(payload.get("attributed_read_count", 0)),
                "supported_read_count": _safe_int(payload.get("supported_read_count", 0)),
                "conflicting_read_count": _safe_int(payload.get("conflicting_read_count", 0)),
                "no_result_read_count": _safe_int(payload.get("no_result_read_count", 0)),
            }
            report["gate_reports"].append(summary)
            hints = payload.get("retrieval_weight_hints", [])
            if isinstance(hints, list):
                for hint in hints:
                    if not isinstance(hint, dict):
                        continue
                    memory_id = str(hint.get("memory_id") or "").strip()
                    if not memory_id:
                        continue
                    report["retrieval_weight_hints"].append({
                        "memory_id": memory_id,
                        "layer": str(hint.get("layer") or "unknown")[:80],
                        "memory_type": str(hint.get("memory_type") or "unknown")[:80],
                        "policy": str(hint.get("policy") or "")[:80],
                        "reason": str(hint.get("reason") or "")[:160],
                        "weight_delta": max(-0.5, min(0.5, _safe_float(hint.get("weight_delta"), 0.0))),
                        "supported_read_count": _safe_int(hint.get("supported_read_count", 0)),
                        "conflicting_read_count": _safe_int(hint.get("conflicting_read_count", 0)),
                        "no_result_read_count": _safe_int(hint.get("no_result_read_count", 0)),
                    })
            report["gate_count"] += 1
            readinesses.append(readiness)
            if readiness == "approved":
                report["approved_gate_count"] += 1
            elif readiness == "rejected":
                report["rejected_gate_count"] += 1
            elif readiness == "error":
                report["error_gate_count"] += 1
            else:
                report["review_gate_count"] += 1
        except Exception as exc:
            report["errors"].append(f"{path}: {exc}")

    if report["errors"]:
        report["readiness"] = "error"
        report["gate_readiness"] = "error"
        report["decision"] = "disable_weighted_memory_retrieval"
        report["reason"] = "memory attribution runtime gate inputs could not be loaded"
    elif any(readiness == "error" for readiness in readinesses):
        report["readiness"] = "error"
        report["gate_readiness"] = "error"
        report["decision"] = "disable_weighted_memory_retrieval"
        report["reason"] = "memory attribution gate has error readiness"
    elif any(readiness == "rejected" for readiness in readinesses):
        report["readiness"] = "rejected"
        report["gate_readiness"] = "rejected"
        report["decision"] = "disable_weighted_memory_retrieval"
        report["reason"] = "memory attribution gate rejected weighted retrieval"
    elif readinesses and all(readiness == "approved" for readiness in readinesses):
        report["readiness"] = "approved"
        report["gate_readiness"] = "approved"
        report["gate_approved"] = True
        report["effective_enable_weighted_memory_retrieval"] = True
        report["decision"] = "enable_weighted_memory_retrieval"
        report["reason"] = "approved memory attribution gates allow weighted memory retrieval"
    else:
        report["readiness"] = "review"
        report["gate_readiness"] = "review" if readinesses else "missing"
        report["decision"] = "hold_weighted_memory_retrieval"
        report["reason"] = "memory attribution gate is not approved"
    report["retrieval_weight_hints"] = report["retrieval_weight_hints"][:80]
    report["retrieval_weight_hint_count"] = len(report["retrieval_weight_hints"])
    return report


def _memory_promptware_gate_check(source: str, status: str, detail: str, metrics: dict) -> dict:
    return {
        "source": source,
        "kind": "memory_promptware_report",
        "status": status,
        "detail": detail,
        "metrics": metrics or {},
    }


def _safe_int(value) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        return default
