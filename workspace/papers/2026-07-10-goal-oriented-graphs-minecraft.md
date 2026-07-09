# Paper Card: Goal-Oriented Graphs for Minecraft

**Title**: From Entity-Centric to Goal-Oriented Graphs: Enhancing LLM Knowledge Retrieval in Minecraft

**Sources**:
- https://arxiv.org/abs/2505.18607
- https://doi.org/10.1016/j.knosys.2026.115706

**Date Reviewed**: 2026-07-10

**Core Method**: Represents procedural knowledge as goals connected by explicit prerequisite relations. Retrieval starts from the requested high-level goal and recursively follows required subgoals, producing one coherent reasoning path instead of a bag of entity-relation fragments.

**Evidence**:
- Evaluates procedural reasoning in Minecraft using wiki and recipe-derived knowledge.
- Reports that goal-driven dependency retrieval outperforms GraphRAG and other retrieval baselines on complex multi-step tasks.
- The journal version was published in Knowledge-Based Systems 341 (2026), article 115706.

**Useful Transfer**:
- A compact task-continuity prompt must retain the active goal, current leaf, unresolved prerequisite frontier, and next action together.
- Entity or checkpoint relevance alone is insufficient when the planner needs an ordered dependency chain.
- Failed branches should remain retrievable but must not interrupt the active goal-to-prerequisite path.

**Limitations**:
- The work evaluates knowledge retrieval and planning, not persistent execution-state recovery.
- Text-to-control uses an existing controller; it does not establish live Mineflayer recovery safety.

**Project Action**: The Goal Frontier Capsule now injects one branch-isolated execution path plus ready/active/blocked frontier tasks, compact missing preconditions, and continuation actions. Full checkpoint records remain durable and reviewable outside the planner prompt.
