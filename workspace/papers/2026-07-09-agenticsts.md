# Paper Card: AgenticSTS

**Title**: AgenticSTS: A Bounded-Memory Testbed for Long-Horizon LLM Agents
**Source**: https://arxiv.org/abs/2607.02255
**Date**: 2026
**Type**: Bounded-memory contract testbed for long-horizon agents
**Core Problem**: Accumulating every past observation, tool call, and reflection into future prompts makes long-horizon behavior hard to attribute, ablate, or keep within a stable memory contract.
**Core Method**: Replaces raw cross-decision transcript accumulation with fresh decision prompts assembled from typed retrieval layers, then freezes memory/skill snapshots and condition tags for reproducible ablations.
**Memory / Task Mechanism**:
  - Treats memory as an explicit contract about what a future decision is allowed to see.
  - Requires typed retrieval layers rather than unstructured prompt history.
  - Uses prompt records and frozen memory/skill snapshots to compare layer effects.
**Borrowable Points**:
  - Every Minecraft planning cycle should have auditable typed memory-read evidence before planner calls.
  - Raw transcript or oversized context windows should be treated as policy failures, not harmless convenience.
  - Planner-context reports should be usable for layer ablations without reconstructing full prompt text.
**Singularity Adaptation**:
  - `bounded-context-report` groups `memory_read` events before each `plan` event, checks per-read and per-cycle character budgets, flags raw/transcript-like context sources, and reports typed retrieval diversity.
  - The report emits `bounded_context_feedback` hints such as `tighten_planner_context_budget` and `replace_raw_transcript_with_typed_retrieval`.
  - The report stores only metadata and counts, not full memory contents or prompts.
**Next Action**: Run `bounded-context-report` on real M1/M2/autonomous logs and compare flagged cycles against planner errors, context drift, and memory-policy decisions.
