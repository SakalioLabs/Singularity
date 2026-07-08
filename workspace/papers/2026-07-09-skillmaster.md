# Paper Card: SkillMaster

**Title**: SkillMaster: Toward Autonomous Skill Mastery in LLM Agents
**Source**: https://arxiv.org/abs/2605.08693
**Date**: 2026
**Type**: Autonomous skill-bank creation, refinement, selection, and training framework
**Core Problem**: Many agent frameworks treat skills as external static assets. That leaves skill creation, repair, and selection outside the agent's learned policy, so skill libraries can grow stale, redundant, or weakly tied to downstream utility.
**Core Method**: Trains agents to propose, update, retain, and select skills from trajectory evidence. Candidate skill edits are credited by counterfactual utility on related probe tasks, with separate learning signals for task actions and skill-management decisions.
**Memory / Task Mechanism**:
  - Trajectory-informed skill review converts completed episodes into skill edit decisions.
  - Probe tasks estimate whether a skill edit improves future utility rather than only matching the current trace.
  - Skill-management actions are optimized separately from ordinary task-solving actions.
**Borrowable Points**:
  - Minecraft skill candidates should not be approved only because a trace looked successful once.
  - Skill edits need held-out or related-task probes that measure future utility and interference.
  - Skill libraries should expose create/update/retain/select decisions as explicit audited actions.
**Singularity Adaptation**:
  - Existing `skill-candidates`, verifier gates, `skill-memory-report`, and `task-stream-transfer-gate` already form the review boundary SkillMaster would require.
  - The new `workspace/evals/minecraft_task_streams.json` seed streams act as counterfactual utility probes for related Minecraft tasks before skill or transfer memories become defaults.
  - Future work should add a skill-edit proposal report that compares keep/update/reject decisions against task-stream gates and skill-memory quality gates.
**Next Action**: Add an offline skill-edit proposal report that routes candidate updates through task-stream probes before approved custom skills are rewritten.
