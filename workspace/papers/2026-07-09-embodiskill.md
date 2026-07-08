# Paper Card: EmbodiSkill

**Title**: EmbodiSkill: Skill-Aware Reflection for Self-Evolving Embodied Agents
**Source**: https://arxiv.org/abs/2605.10332
**Date**: 2026
**Type**: Skill-aware self-evolution / embodied reflection
**Core Problem**: Failed embodied execution does not always mean the skill itself is wrong; it may be an execution lapse caused by layout, object state, perception, or action grounding.
**Core Method**: Interprets trajectories relative to the current skill, separates skill-changing evidence from execution-lapse evidence, then performs targeted revision while preserving valid guidance.
**Memory / Task Mechanism**:
  - Treats skill evolution as a reflection problem grounded in trajectory evidence.
  - Preserves useful skill bodies when failure came from execution drift.
  - Updates skills only when evidence indicates a real procedural gap.
**Borrowable Points**:
  - Classify perception/action failures as execution-lapse candidates before mutating skill bodies.
  - Keep planner-facing repair advice separate from durable skill updates.
  - Require stronger evidence for skill revision than for one-off plan repair.
**Singularity Adaptation**:
  - `SelfEvolutionPolicy` marks perception/action-heavy feedback as `execution_lapse_first`.
  - Planner context now receives advisory repair hints while custom skill mutation remains gated by verifier, discovery, and skill-graph checks.
**Next Action**: Compare self-evolution advice against live retry outcomes before allowing any generated skill-body revisions.
