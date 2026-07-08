# Paper Card: VistaWise

**Title**: VistaWise: Building Cost-Effective Agent with Cross-Modal Knowledge Graph for Minecraft
**Source**: https://arxiv.org/abs/2508.18722
**Date**: 2025
**Authors**: Honghao Fu, Junlong Ren, Qi Chai, Deheng Ye, Yujun Cai, Hao Wang
**Type**: Paper
**Core Problem**: Large-scale domain finetuning for Minecraft agents is expensive, while plain LLMs lack domain-specific multimodal knowledge.
**Core Method**: Cross-modal knowledge graph combining visual information and textual dependencies, paired with a lightweight object detector and retrieval.
**System Architecture**:
  - Dedicated detector grounds visual objects.
  - Cross-modal KG links visual objects, textual dependencies, and tasks.
  - Retrieval-based pooling selects task-relevant KG entries.
  - Desktop-level skill library controls mouse and keyboard.
**Memory Mechanism**: Knowledge graph that bridges visual perception and textual reasoning.
**Task Mechanism**: Retrieve task-specific knowledge from KG instead of finetuning a huge model.
**Key Results**: Reports strong Minecraft open-world performance with much lower domain-specific data cost.
**Reproduction Difficulty**: Medium-high; detector training and desktop control add setup cost.
**Borrowable Points**:
  - Use KG retrieval as a cheap substitute for large finetuning.
  - Connect block/object recognition to recipe/tool dependencies.
  - Pool only task-relevant graph facts into prompts.
**Current Singularity Mapping**:
  - `MinecraftKnowledgeGraph` now links recipes, drops, tools, and mining requirements.
  - `VisionAnalyzer` now emits graph-backed grounded resources for API observations.
  - Skill candidates now carry compact `visual_evidence` from session logs, allowing promotion review to connect visual observations and textual task claims.
  - `promotion-review-ablation` now compares deterministic-only review, API visual summaries, and screenshot/VLM-assisted review.
  - `goal-verification-ablation` applies the same split to goal completion checks, separating structured cross-modal summaries from screenshot/VLM references.
  - Both visual ablations can now consume manual label files, turning cross-modal evidence experiments into agreement measurements against reviewed judgments.
**Next Action**: Run the three-way ablations with label files on real screenshot-backed sessions and measure whether cross-modal evidence improves unknown candidate review and goal verification.
