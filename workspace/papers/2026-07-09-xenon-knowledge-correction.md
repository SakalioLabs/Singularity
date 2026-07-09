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
**Next Action**: Run the report on fresh M1/M2 retries, review dependency corrections against `KnowledgeBase`, then add gated planner-context loading without mutating built-in recipes.
