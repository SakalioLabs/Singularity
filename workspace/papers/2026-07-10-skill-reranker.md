# Paper Card: Task Decomposition-Guided Skill Reranking

**Title**: Task Decomposition-Guided Reranking for Adaptive Agent Skill Retrieval

**Source**: https://arxiv.org/abs/2607.06283

**Date Reviewed**: 2026-07-10

**Core Method**: Decomposes both tasks and skills into execution-state transitions, builds a directed acyclic graph over intermediate states, and reranks candidate skills for each task interval.

**Evidence**:
- Evaluates three backbone LLMs on ALFWorld and ScienceWorld.
- Reports higher task performance with fewer environment interactions and lower token use than semantic skill-selection baselines.
- Uses a cross-encoder after structured decomposition; the graph alone is not claimed as the complete method.

**Useful Transfer**:
- Route Minecraft skills against the active task frontier rather than only the root goal.
- Give missing preconditions and explicit assigned skills stronger weight than broad semantic similarity.
- Preserve a fixed legacy ranker for controlled ablation.

**Project Action**: Added `frontier_transition_skill_router_v1`. It uses readiness tasks, missing state, target state, assigned skill, task family, skill contracts, and governance to produce a bounded, auditable route. It is deterministic rather than a reproduction of the paper's learned cross-encoder.
