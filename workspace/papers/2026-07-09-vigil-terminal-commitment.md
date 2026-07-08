# Paper Card: VIGIL Terminal Commitment

**Title**: Done, But Not Sure: Disentangling World Completion from Self-Termination in Embodied Agents
**Source**: https://arxiv.org/abs/2605.08747
**Date**: 2026
**Type**: Embodied-agent terminal commitment evaluation
**Core Problem**: Standard embodied benchmarks often collapse execution failure, unsupported success claims, and failure to stop after achieving the world state into one terminal success/failure score.
**Core Method**: VIGIL separates world-state completion from the agent's terminal report, producing categories such as missed execution, post-attainment drift, unsupported commitment, and verified success.
**Memory / Task Mechanism**:
  - Treat final state verification and terminal self-report as separate evidence channels.
  - Penalize reporting completion without world evidence.
  - Penalize failing to commit after the world state is already achieved.
**Borrowable Points**:
  - Minecraft goals should not trust `goal_end.completed` alone.
  - Offline reports should compare final observed inventory/world state against terminal completion claims.
  - Runtime completion policy can later use these categories to decide whether to execute more, stop, or gather more evidence.
**Singularity Adaptation**:
  - Added `terminal-commitment-report` for session JSONL logs.
  - The report replays final goal observations through `GoalVerifier`, reads terminal `goal_end` completion claims, and classifies each goal as `verified_success`, `unsupported_commitment`, `post_attainment_drift`, `missed_execution`, or `unknown`.
  - Saved `logs/benchmarks/terminal_commitment_m1_2026-07-09.json` as the current M1 baseline: all five tracked goals are missed execution, with no unsupported completion claims or post-attainment drift.
**Next Action**: Re-run terminal commitment on live M1/M2 retries after blocked-plan fallback; if world completion rises while terminal commitment remains low, add explicit stop/commit reminders or terminal-report verification gates.
