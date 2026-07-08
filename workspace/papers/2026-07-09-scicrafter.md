# Paper Card: SciCrafter

**Title**: Can Current Agents Close the Discovery-to-Application Gap? A Case Study in Minecraft
**Source**: https://arxiv.org/abs/2604.24697
**Date**: 2026
**Type**: Minecraft benchmark / diagnostic evaluation
**Core Problem**: General agents can often apply known recipes, but still struggle to discover missing causal rules and turn those discoveries into working Minecraft systems.
**Core Method**: Uses parameterized redstone circuit tasks to test a discovery-to-application loop: identify knowledge gaps, run experiments, consolidate findings, then build a target circuit.
**Memory / Task Mechanism**:
  - Separates discovery, consolidation, and application as distinct measurable phases.
  - Uses scalable task parameters so success cannot come only from memorized fixed solutions.
  - Treats "asking the right experiment" as a first-class capability.
**Borrowable Points**:
  - Add task templates that require the agent to run small Minecraft experiments before final construction.
  - Store experiment hypotheses, observations, and causal rules separately from ordinary episodic memory.
  - Gate new redstone/building skills on successful held-out application, not just one solved instance.
**Singularity Adaptation**:
  - Extend `TaskSystem` with experiment subtasks that produce causal notes before construction subtasks unlock.
  - `discovery-application-report` now audits session logs for hypothesis, experiment, causal consolidation, and held-out application evidence.
  - Reuse mixed-policy gates for experiment-derived skills: no runtime default unless discovery, consolidation, and application evidence all pass.
  - Add future M8-style redstone diagnostics once M1/M2/M7 runtime stability is stronger.
**Next Action**: Draft a tiny redstone-light benchmark spec with hypothesis, experiment, and application phases.
