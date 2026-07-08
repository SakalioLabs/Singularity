# Paper Card: SVA Action Evaluation

**Title**: Look Before You Leap: Distilling Tree Search into Action Evaluation for Frozen VLA Models
**Source**: https://arxiv.org/abs/2607.03751
**Date**: 2026-07-04
**Type**: Test-time action evaluation for frozen VLA policies
**Core Problem**: Frozen VLA models can generate good actions in their candidate distribution, but pass@1 execution fails because the policy lacks a strong action evaluator.
**Core Method**: Uses simulation-time MCTS to collect return-labeled trajectories, distills them into a lightweight Q-value evaluator, and deploys by selecting among multiple candidate actions with an uncertainty-regularized score.
**Memory / Task Mechanism**:
  - Separate action proposal from consequence evaluation.
  - Use offline rollouts to create action-value supervision.
  - Deploy a lightweight evaluator without requiring simulator access at inference time.
**Borrowable Points**:
  - Use session logs and verifier outcomes to build Minecraft action-value datasets.
  - Rank multiple planner outputs by expected prerequisite satisfaction, safety, and progress.
  - Track pass@k-style evidence: whether good Minecraft actions exist among alternatives even when the first executed action fails.
**Singularity Adaptation**:
  - Current implementation starts with deterministic `ActionVerifier` status and score rather than learned Q-values.
  - `action-verification-report` exposes the review/reject/failure buckets needed to collect future value-model labels.
  - The next natural step is a candidate action selector that scores several planner or rule-planner proposals before execution.
**Next Action**: Add a small candidate-action evaluation harness that compares planner top-1 against verifier-ranked alternatives on logged Minecraft goals.
