# Paper Card: XENON Knowledge Correction

**Title**: Experience-based Knowledge Correction for Robust Planning in LLM-based Agents
**Source**: https://openreview.net/forum?id=N22lDHYrXe
**Date**: 2026
**Type**: Minecraft agent planning and experience-based knowledge correction
**Core Problem**: LLM agents can repeatedly fail when their internal or prompted Minecraft knowledge misses prerequisites, ordering constraints, or invalid action assumptions.
**Core Method**: Separate experience-based correction into dependency-graph knowledge and failed-action memory so future planning can avoid repeated invalid steps and insert needed recovery/precondition actions.
**Memory / Task Mechanism**:
  - Successful recoveries after failed actions are treated as candidate corrections to task ordering or dependency knowledge.
  - Failed action traces become reusable action memories rather than free-form reflections.
  - Corrections stay grounded in environment experience instead of direct model self-editing.
**Borrowable Points**:
  - Keep failed-action memory separate from positive skill memory.
  - Convert repeated failures plus later recovery into reviewed prerequisite edges.
  - Require trace evidence before adding planner knowledge.
**Singularity Adaptation**:
  - `knowledge-correction-report` mines repeated failed/no-progress action signatures and failed-action -> successful-recovery pairs from session logs.
  - Candidate corrections include Echo-style structure, attribute, process, function, and interaction dimensions for later transfer retrieval.
  - `knowledge-correction-gate` holds these candidates until enough ready logs and reviewable correction evidence exist.
  - Approved reports can now be passed with `--knowledge-correction-feedback` plus `--knowledge-correction-gate` so the planner receives short advisory dependency and failed-action hints without mutating built-in recipes.
  - `benchmark --knowledge-correction-preflight` verifies approved gates plus selected-suite goal overlap before spending live benchmark time on correction-assisted runs.
  - `knowledge-correction-ablation` shows exact planner-context changes for suite goals, explicit goals, or case files before live runs.
**Next Action**: Run report, gate, ablation, and benchmark preflight on fresh M1/M2 retries, then compare gated planner-context runs against the ungated baseline.
