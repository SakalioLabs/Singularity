# Paper Card: VeGAS Action Verification

**Title**: Think Twice, Act Once: Verifier-Guided Action Selection For Embodied Agents
**Source**: https://arxiv.org/abs/2605.12620
**Date**: 2026-05-12
**Type**: Embodied-agent verifier-guided action selection
**Core Problem**: MLLM embodied agents often commit to the first decoded action even when out-of-distribution scenes or long-horizon dependencies make that action brittle.
**Core Method**: Samples multiple candidate actions at inference time and uses a trained generative verifier to choose the most reliable one without modifying the underlying policy.
**Memory / Task Mechanism**:
  - Treat candidate action selection as a separate verification step.
  - Train or tune the verifier on diverse failure cases instead of trusting an off-the-shelf MLLM judge.
  - Preserve the base planner/policy while adding a test-time action evaluator.
**Borrowable Points**:
  - Add a deterministic first-pass Minecraft verifier for obvious missing ingredients, tools, and targets.
  - Log verifier decisions separately from action execution so offline reports can measure false rejects and uncovered failures.
  - Later expand from single-action checking to candidate action ranking.
**Singularity Adaptation**:
  - Added `ActionVerifier` for structured Minecraft actions.
  - Agent now logs `action_verification` events and blocks deterministic rejects before live Mineflayer execution when enforcement is enabled.
  - Added `action-verification-report` and saved `logs/benchmarks/action_verification_m1_2026-07-09.json`; current M1 replay has 200 verified actions, 195 accepts, 5 reviews, 0 rejects, and 0 failed-without-reject gaps.
**Next Action**: Re-run on live M1/M2 retries and add candidate-generation/ranking once repeated review or failed-without-reject categories appear.
