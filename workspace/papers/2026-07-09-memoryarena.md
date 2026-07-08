# Paper Card: MemoryArena

**Title**: MemoryArena: Benchmarking Agent Memory in Interdependent Multi-Session Agentic Tasks
**Source**: https://arxiv.org/abs/2602.16313
**Date**: 2026
**Type**: Agent memory benchmark / multi-session evaluation
**Core Problem**: Existing memory benchmarks often test recall separately from action, while real agents need memories that improve later decisions across dependent tasks.
**Core Method**: Defines multi-session Memory-Agent-Environment loops with human-authored interdependent subtasks, requiring agents to distill earlier feedback into memory and use it in later actions.
**Memory / Task Mechanism**:
  - Couples memory acquisition, retrieval, and action success across sessions.
  - Evaluates whether memory changes decisions, not only whether facts are recalled.
  - Uses explicitly dependent subtasks as the pressure test for useful memory.
**Borrowable Points**:
  - Audit memory by task outcome and follow-up action quality.
  - Keep task metadata next to retrieved memories so the planner can use memory as a decision prior.
  - Prefer evaluation reports that expose memory-to-task evidence over raw recall counts.
**Singularity Adaptation**:
  - `MemorySystem.task_memory_profile()` now combines goal, active task metadata, scoped memory matches, transfer-axis experience matches, and read-filter diagnostics.
  - `Agent._task_memory_context()` injects task-centric memory into planner context and logs a `memory_read` event for later policy reports.
  - `skill-memory-quality-report` now adds a skill-memory version of memory-to-action evaluation by comparing typed retrieved hints with later actions and goal outcomes in session logs.
**Next Action**: Run `task-memory-report` and `skill-memory-quality-report` on real multi-session M1/M2/autonomous traces and compare memory matches against verifier outcomes.
