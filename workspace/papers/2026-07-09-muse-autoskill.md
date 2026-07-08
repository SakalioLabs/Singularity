# Paper Card: MUSE-Autoskill

**Title**: MUSE-Autoskill: Self-Evolving Agents via Skill Creation, Memory, Management, and Evaluation
**Source**: https://arxiv.org/abs/2605.27366
**Date**: 2026
**Type**: Skill-centric self-evolving agent framework
**Core Problem**: Reusable agent skills are often static, isolated artifacts without runtime context, per-skill memory, validation, or refinement loops.
**Core Method**: Treats skills as long-lived assets with creation, skill-level memory, catalog management, evaluation, and refinement stages.
**Memory / Task Mechanism**:
  - Stores experience around individual skills, not only around whole sessions.
  - Retrieves skills through a catalog and updates/refines them from runtime feedback.
  - Uses evaluation and feedback to keep created skills testable before reuse.
**Borrowable Points**:
  - Minecraft skills should carry per-skill memories about prerequisites, failure modes, and successful world-state variants.
  - Transfer gates should decide when a skill can move from review to runtime default.
  - Skill lifecycle records should track creation, use, evaluation, refinement, and deprecation.
**Singularity Adaptation**:
  - `skill-contract-report` already audits prerequisites/postconditions and governance.
  - `task-stream-transfer-gate` now adds cross-task transfer evidence before memory or skill promotion.
  - Skill candidate approval now stores task-stream gate readiness in promotion reports and skill governance metadata.
  - `Skill.skill_memory` and `skill-memory-report` now store and audit skill-local replay notes, failure/anti-pattern notes, task-family zones, and approved/review transfer memories instead of relying only on global episodic memory.
  - Approved skill candidates now seed promotion/transfer memories automatically, and runtime failure-correction skills append success or anti-pattern memories as they execute.
**Next Action**: Retrieve `get_skill_memory_hints()` into planner context and compare skill-memory-assisted runs against policy-skill-only baselines.
