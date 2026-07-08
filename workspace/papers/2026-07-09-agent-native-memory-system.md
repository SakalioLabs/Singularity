# Paper Card: Agent-Native Memory System

**Title**: Are We Ready For An Agent-Native Memory System?
**Source**: https://arxiv.org/abs/2606.24775
**Date**: 2026
**Type**: System-level study of long-term memory for LLM agents
**Core Problem**: Agent memory is often evaluated as a monolithic task-success component, hiding retrieval precision, update correctness, maintenance cost, and long-horizon stability issues.
**Core Method**: Decomposes agent memory into representation/storage, extraction, retrieval/routing, and maintenance, then compares representative memory systems across workloads.
**Memory / Task Mechanism**:
  - Separates memory retrieval/routing quality from write and maintenance quality.
  - Emphasizes update correctness and long-horizon stability under dynamic knowledge changes.
  - Finds localized maintenance can be more efficient than global reorganization.
**Borrowable Points**:
  - Minecraft memory should expose module-level diagnostics instead of only end-to-end goal success.
  - Skill-memory feedback should tune local retrieval/routing before mutating the skill store.
  - Reports should distinguish stale, conflicted, review-only, and reusable memories as maintenance states.
**Singularity Adaptation**:
  - `skill-memory-quality-report` measures planner-facing skill-memory hints against later actions and goal outcomes.
  - `skill-memory-quality-report` now emits `hint_quality_items` keyed by skill, task family, and hint type.
  - `SkillLibrary.record_skill_memory_quality_feedback()` performs localized retrieval-ranking maintenance: conflicted `REUSE` hints are demoted only for matching skill/family/type items, `AVOID` warnings can be made more visible, and `REVIEW_ONLY` remains gated.
  - `skill-memory-quality-ablation` compares baseline and maintained retrieval rankings offline, exposing promoted/demoted hints before live runtime cost.
  - `--skill-memory-quality-feedback` loads this maintenance profile into runtime retrieval without rewriting skill files.
**Next Action**: Run quality-feedback-assisted and plain skill-memory ablations on real M1/M2/autonomous logs to quantify retrieval precision and stability improvements.
