# Paper Card: OpenSkill

**Title**: OpenSkill: Open-World Self-Evolution for LLM Agents
**Source**: https://arxiv.org/abs/2606.06741
**Date**: 2026-06-04
**Authors**: Zhiling Yan, Dingjie Song, Hanrong Zhang, Wei Liang, Yuxuan Zhang, Yutong Dai, Lifang He, Philip S. Yu, Ran Xu, Xiang Li, Lichao Sun
**Type**: Agent self-evolution framework
**Core Problem**: Self-evolving agents often assume curated skills, successful trajectories, or verifier signals already exist, which is unrealistic in open-world deployment.
**Core Method**:
  - Acquire grounded knowledge and verification anchors from documentation, repositories, and web resources.
  - Synthesize transferable skills from those anchors.
  - Build virtual practice tasks grounded in the anchors, then refine skills without target-task supervision.
**Why It Matters for Minecraft**:
  - Minecraft has rich public structure: wiki recipes, block drops, tool requirements, biome/entity rules, and Mineflayer APIs.
  - These resources can supply verifier anchors such as "crafting_table in inventory", "stone_pickaxe required for iron_ore", or "torch count increases after crafting".
**Singularity Adaptation**:
  - Current `GoalVerifier` is hand-written deterministic verification.
  - `VerifierAnchor` mining now converts `KnowledgeBase` recipes and `MinecraftKnowledgeGraph.resource_drops` into deterministic inventory postconditions automatically.
  - Generated verifier anchors are tagged by source (`recipe`, `resource_drop`, or manual) so completion gates remain auditable.
  - Reviewed/custom skill postconditions now also generate verifier anchors, and before/after inventory deltas are recorded in verification evidence.
  - Skill-candidate approval is now gated by verifier outcomes: explicit failed verification blocks promotion, and achieved verification becomes reusable skill postconditions.
  - `SkillPromotionValidationReport` now records the promotion explanation, including approve/reject/unknown decisions and warnings.
  - Benchmark ingestion now aggregates these validation reports into suite-level approve/reject/unknown readiness counts before candidates enter human review.
  - Unknown verifier gates can now route through an explicit LLM `SkillPromotionCritic`, preserving the same audit report while keeping the default path deterministic and offline.
  - Unknown runtime goal completions can route through an opt-in `GoalVerificationCritic`, preserving deterministic anchors as the first gate while allowing open-world claims to be audited by a critic.
  - Offline `goal-verification-ablation` now measures whether API visual summaries or screenshot/VLM references add verifier coverage beyond generated anchors.
**Next Action**: Compare live M1/M2 traces with deterministic-only versus LLM-critic-assisted goal and skill verification.
