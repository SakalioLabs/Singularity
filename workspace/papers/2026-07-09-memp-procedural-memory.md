# Paper Card: Mem^p Procedural Memory

**Title**: Mem^p: Exploring Agent Procedural Memory
**Source**: https://arxiv.org/abs/2508.06433
**Date**: 2025
**Type**: Procedural-memory construction, retrieval, and update framework
**Core Problem**: LLM agents often rely on hand-written procedures or brittle prompt templates, while learned procedural knowledge lacks explicit lifecycle operations for build, retrieval, update, correction, and removal.
**Core Method**: Distills past trajectories into fine-grained instructions plus higher-level scripts, then studies retrieval and update strategies such as validation filtering, reflection, and dynamic discarding.
**Memory / Task Mechanism**:
  - Procedural memory is built from past task trajectories and execution feedback.
  - Retrieval should select relevant procedural memories without overloading context.
  - Update policies add, correct, or discard procedure records as new outcomes arrive.
**Borrowable Points**:
  - Minecraft skill memory should carry both successful replay hints and failure/correction anti-patterns.
  - More retrieved procedures are not always better; runtime defaults need bounded, task-family scoped evidence.
  - Strong-run memories can help weaker models only when transferred through explicit validation.
**Singularity Adaptation**:
  - Skill-local memories are typed as `REUSE`, `AVOID`, and `REVIEW_ONLY`.
  - `skill-memory-quality-report`, `skill-memory-quality-gate`, and `skill-runtime-default-gate` keep procedural memories review-gated until localized outcome evidence supports reuse.
  - Runtime Agent startup now applies approved `skill-runtime-default-gate` profiles before learned skill-memory hints or failure-correction skills can influence planner/action behavior by default.
  - Benchmark runtime-default preflight requires approved procedural candidates to overlap the selected suite's task families, keeping irrelevant retrieved procedures out of live evaluation.
**Next Action**: Compare default-off versus gated-default skill profiles on live M1/M2 and autonomous logs, then demote any procedure whose quality labels conflict with later failures.
