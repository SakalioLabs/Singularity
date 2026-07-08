# Paper Card: GameWorld

**Title**: GameWorld: Towards Standardized and Verifiable Evaluation of Multimodal Game Agents
**Source**: https://arxiv.org/abs/2604.07429
**Date**: 2026-04-08
**Type**: Benchmark / verifiable evaluation framework
**Core Problem**: Multimodal game agents are difficult to compare because games expose heterogeneous action interfaces and many evaluations rely on heuristic or weak success checks.
**Core Method**: Defines a browser-game benchmark with both direct keyboard/mouse control and semantic action parsing, pairing each task with state-verifiable outcome metrics.
**Memory / Task Mechanism**:
  - Studies context-memory sensitivity as a benchmark dimension.
  - Separates action-interface validity from final task success.
  - Uses deterministic state checks instead of relying only on model self-reports.
**Borrowable Points**:
  - Keep Singularity's semantic action lane while preserving a path toward visual/desktop control.
  - Treat every new task family as incomplete until it has a bounded, state-verifiable success metric.
  - Report invalid actions and interface mismatches separately from planning failures.
**Singularity Adaptation**:
  - `GoalVerifier`, mixed-initiative bounded validators, `action-abstraction-report`, and visual-action ablations together form a Minecraft-specific version of standardized semantic actions plus verifiable metrics.
  - New mixed-initiative templates should ship with a validator and at least one replayable trace test, not just a prompt pattern.
  - Future live benchmark reports should separate semantic action validity, Mineflayer backend success, and final task evidence.
**Implemented Hook**: `mixed-initiative-trace-report` now separates raw action success, bounded-policy-valid success, invalid action counts, action type counts, and per-template action-validity aggregates.
**Next Action**: Feed live M1/M2/M7 session logs into the trace report and compare action-validity regressions by task family.
