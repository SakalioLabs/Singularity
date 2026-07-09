# Paper Card: CausalGame

**Title**: CausalGame: Benchmarking Causal Thinking of LLM Agents in Games
**Source**: https://arxiv.org/abs/2607.04293
**Date**: 2026-07-05
**Type**: Interactive game benchmark for causal thinking in LLM agents
**Core Problem**: LLM agents can collect observations and write plausible explanations while still confusing correlation, hidden confounding, measurement error, and selection bias.
**Core Method**:
  - Uses interactive games where agents design protocols, collect observations, and produce explanation reports.
  - Tests causal reasoning failures that ordinary game-score benchmarks can hide.
  - Includes failure-mode analysis, threshold calibration, and anomalous behavior audits.
**Why It Matters for Minecraft**:
  - Minecraft logs already expose causal event summaries, world-model frontiers, discovery/application evidence, and action transition windows.
  - A Minecraft agent can overfit to repeated co-occurrence such as "visible coal near danger" or "action returned success" without proving causal progress.
  - CausalGame suggests evaluating whether the agent deliberately gathers contrastive evidence before turning repeated observations into skills, memory, or knowledge corrections.
**Singularity Adaptation**:
  - Extend `discovery-application-report` and `causal_index` with contrastive experiment markers: intervention, control, outcome, confounder, and measurement-risk fields.
  - Add counterexample-aware checks before promoting mined causal summaries into skills or runtime memory.
  - Compare causal explanations against later verifier/action-value evidence so false causal shortcuts are routed to review.
  - `causal-evidence-report` now audits session logs for hypothesis/intervention/outcome protocols, contrast controls, selection/measurement/confounder risk mitigation, causal-memory writes, and unresolved counterexamples.
**Next Action**: Run `causal-evidence-report` on fresh discovery/redstone/autonomous logs before approving causal-summary skills, causal memories, or discovery-derived knowledge corrections.
