# Paper Card: AgentOdyssey

**Title**: AgentOdyssey: Open-Ended Long-Horizon Text Game Generation for Test-Time Continual Learning Agents
**Source**: https://arxiv.org/abs/2606.24893
**Date**: 2026
**Type**: Open-ended long-horizon game generation and test-time continual learning benchmark
**Core Problem**: Agents deployed in long-horizon worlds must keep learning during interaction, but many evaluations still treat test-time behavior as static inference over short tasks.
**Core Method**: Procedurally generates open-ended text games with rich entities, world dynamics, and long-horizon tasks, then evaluates world-knowledge acquisition, episodic memory, object/action exploration, action diversity, progress, and cost.
**Memory / Task Mechanism**:
  - Separates game progress from diagnostic probes of memory, exploration, and action diversity.
  - Treats short-term memory as an important mechanism for test-time training.
  - Measures meaningful horizon rather than only final task success.
**Borrowable Points**:
  - Minecraft autonomous reports should expose progress plus diagnostic axes: world knowledge, episodic recall, object/action exploration, action diversity, and cost.
  - Session traces should reveal where the agent's meaningful horizon collapses, not only whether a benchmark passed.
  - Procedural or replayed tasks should include hidden prerequisites and state dynamics.
**Singularity Adaptation**:
  - Existing `exploration-trace-report`, `world-model-report`, `memory-policy-report`, and `bounded-context-report` cover parts of AgentOdyssey's diagnostic surface.
  - `continual-learning-report` now combines progress, world knowledge, episodic/semantic memory use, object/action exploration, action diversity, bounded-context quality, and meaningful-horizon signals from the same session logs.
  - The report emits reviewable `continual_learning_policy` hints for weak memory loops, low action diversity, short horizons, and unbounded context cycles.
**Next Action**: Run `continual-learning-report` on real autonomous/M7 session logs and compare axis scores against later task success, transfer-memory matches, and skill-candidate reuse.
