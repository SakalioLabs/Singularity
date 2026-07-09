# Paper Card: MAGE Execution-State Memory

**Title**: Beyond Semantic Organization: Memory as Execution State Management for Long-Horizon Agents

**Source**: https://arxiv.org/abs/2606.06090

**Date Reviewed**: 2026-07-10

**Core Method**: Represents long-horizon execution as a hierarchical state tree. The active root-to-current path supplies decision state, while failed branches remain isolated and available as hints rather than contaminating the active trajectory.

**Memory Operations**:
- **Grow** records a new execution trace.
- **Compress** summarizes a completed subgoal.
- **Maintain** validates summaries and state integrity.
- **Revise** restores a prior boundary and resumes on a new branch.

**Evidence**:
- Reports 7.8 to 20.4 percentage-point average task-success improvements over baselines on MemoryArena.
- Reports a 55.1% token reduction while preserving coherent execution state.

**Useful Transfer**:
- Minecraft memory should preserve the active task path, completed checkpoints, failed branches, and revision boundaries separately.
- Planner context should be rebuilt per decision from typed active-state records, not an accumulated transcript.
- Repeated action failure should revise from the nearest verified checkpoint rather than append another reflection to the same branch.

**Project Action**: Schema-v2 `TaskContinuityRecord` now captures execution branches, parent/root checkpoints, depth, validation, terminal state, and revision provenance. Planner context follows one selected path and isolates failed/proposed branches as hints. `task-continuity-revision` only records a proposal to the nearest verified ancestor; automatic Minecraft restoration remains disabled until reachability and non-regression gates pass.
