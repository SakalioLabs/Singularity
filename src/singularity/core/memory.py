"""Memory system - multi-layered memory for the Singularity agent."""
import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Optional

from singularity.core.causal_index import CausalEvent, CausalEventIndex, aggregate_causal_events

logger = logging.getLogger("singularity.memory")


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
        self.entries_path = os.path.join(memory_dir, "memory_entries.jsonl")
        self.experiences_path = os.path.join(memory_dir, "experience_records.jsonl")
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

    def retrieve_relevant_experiences(self, query: str, current_state: Optional[dict] = None, limit: int = 5) -> list[ExperienceRecord]:
        """Return experience records ranked by text overlap and context fit."""
        query_words = self._keywords(query)
        state_words = self._keywords(json.dumps(current_state or {}, default=str))
        scored = []
        for record in self.experiences.values():
            text_words = self._keywords(record.searchable_text())
            overlap = len(query_words & text_words) * 2 + len(state_words & text_words)
            if record.success:
                overlap += 1
            overlap += min(3, int(record.metrics.get("success_delta", 0)))
            if overlap > 0:
                scored.append((overlap, record))
        scored.sort(key=lambda item: item[0], reverse=True)
        selected = [record for _, record in scored[:limit]]
        recalled = False
        for record in selected:
            self._mark_experience_recalled(record, query)
            recalled = True
        if recalled:
            self._rewrite_experiences()
        return selected

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
        query_words = self._keywords(query)
        recalled_entries = False
        for entry in self.entries.values():
            if not self._entry_applicable(entry, current_state):
                continue
            entry_words = self._keywords(entry.prompt_line())
            if query_words & entry_words:
                self._mark_entry_recalled(entry, query)
                recalled_entries = True
                parts.append(f"Memory: {entry.prompt_line()}")
        if recalled_entries:
            self._rewrite_entries()
        for key, fact in self.l3_semantic.items():
            if any(word in key.lower() or word in fact["value"].lower() for word in query.lower().split()[:3]):
                parts.append(f"Fact: {key} = {fact['value']}")
        for ep in self.l2_episodic[-20:]:
            if any(word in json.dumps(ep, default=str).lower() for word in query.lower().split()[:3]):
                parts.append(f"Experience: {ep['type']} - {json.dumps(ep['data'], default=str)[:100]}")
        for record in self.retrieve_relevant_experiences(query, limit=3):
            parts.append(f"Transfer: {record.task} -> {record.outcome}; why={record.causal.get('why', '')}")
        for event in self.retrieve_causal_events(query, limit=3):
            parts.append(f"Causal: {event.prompt_line()}")
        return "\n".join(parts[:10])

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
        return sorted(set(reasons))

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
