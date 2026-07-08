# Paper Card: MemConflict

**Title**: MemConflict: Evaluating Long-Term Memory Systems Under Memory Conflicts
**Source**: https://arxiv.org/abs/2605.20926
**Date**: 2026
**Type**: Paper + diagnostic benchmark
**Core Problem**: Long-term memory systems can retrieve plausible but invalid evidence when temporal, factual, or contextual conflicts compete for the same query.
**Core Method**:
  - Treats memory validity as query-conditioned fitness-for-use.
  - Builds dynamic, static, and conditional conflicts into multi-session histories.
  - Evaluates both final answers and which supporting memories were retrieved and ranked.
**Borrowable Points**:
  - Retrieval must filter by temporal validity and current context, not only semantic similarity.
  - Conditional applicability should be explicit metadata, otherwise stale or wrong-context memories can steer downstream behavior.
  - White-box retrieval diagnostics are useful before judging only task outcomes.
**Singularity Adaptation**:
  - `MemorySystem.get_relevant_memory()` now accepts `current_state` and filters stale, superseded, contradicted, invalidated, and condition-mismatched durable entries before planner prompt construction.
  - `memory_read_filter_report()` exposes filtered-entry counts and reasons so future benchmark reports can audit retrieval quality.
**Next Action**: Run memory read filter reports on live autonomous and M7 logs, then add query-conditioned retrieval metrics to benchmark summaries.
