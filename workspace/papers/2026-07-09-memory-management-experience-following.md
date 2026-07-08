# Paper Card: Memory Management and Experience-Following

**Title**: How Memory Management Impacts LLM Agents: An Empirical Study of Experience-Following Behavior
**Source**: https://aclanthology.org/2026.acl-long.27/
**Date**: 2026
**Type**: Empirical study of LLM-agent memory addition/deletion and long-term behavior
**Core Problem**: Retrieved past executions can strongly steer later outputs, so low-quality or misaligned memories may degrade future tasks instead of helping them.
**Core Method**: Studies memory addition and deletion choices, measures experience-following behavior, and evaluates how future task outcomes can label memory quality.
**Memory / Task Mechanism**:
  - Agents tend to produce outputs similar to retrieved memories when task inputs are similar.
  - Error propagation can compound inaccurate past experiences.
  - Seemingly correct traces can still be misaligned experience replay for future tasks.
**Borrowable Points**:
  - Minecraft skill memories should not be injected as undifferentiated replay text.
  - Future task outcomes and transfer gates should become quality labels for stored skill memories.
  - Runtime prompts should distinguish reusable instructions from warnings and review-only memories.
**Singularity Adaptation**:
  - `SkillLibrary.get_skill_memory_hints()` now marks planner-facing memories as `REUSE`, `AVOID`, or `REVIEW_ONLY`.
  - Failure and anti-pattern memories become explicit cautions instead of hidden negative examples.
  - Review/rejected/error transfer gates keep memories visible for audit while preventing default reuse.
  - `skill-memory-quality-report` now labels typed hint traces against later action failures, repeated failures, and goal outcomes so future-task evidence can promote, review, or demote retrieved skill memories.
**Next Action**: Run quality reports on real autonomous/M7 logs, then compare typed skill-memory ablations on controlled Minecraft task streams and demote hints that correlate with retries, regressions, or held-out failures.
