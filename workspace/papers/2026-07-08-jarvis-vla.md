# Paper Card: JARVIS-VLA

**Title**: JARVIS-VLA: Post-Training Large-Scale Vision Language Models to Play Visual Games with Keyboards and Mouse
**Source**: https://arxiv.org/abs/2503.16365
**Project**: https://craftjarvis.github.io/JarvisVLA/
**Date**: 2025
**Authors**: Muyao Li, Zihao Wang, Kaichen He, Xiaojian Ma, Yitao Liang
**Type**: Paper + Code/Models/Datasets
**Core Problem**: VLA agents need better visual recognition, world knowledge, and spatial grounding before action imitation alone can work well.
**Core Method**: Act from Visual Language Post-Training, refining VLMs with visual and linguistic guidance before action policy use.
**System Architecture**:
  - Post-train VLM on non-trajectory visual-language tasks.
  - Add trajectory and GUI-style expert data for Minecraft actions.
  - Execute with keyboard and mouse action space.
**Memory Mechanism**: Mostly model-internal multimodal grounding rather than explicit memory.
**Task Mechanism**: Follow human instructions across many atomic Minecraft tasks.
**Key Results**: Reports broad Minecraft atomic-task coverage and strong gains from non-trajectory post-training.
**Reproduction Difficulty**: High; large models, datasets, and GPU training required.
**Borrowable Points**:
  - Improve perception before expecting action imitation to generalize.
  - Treat crafting/smelting GUI actions as separate structured expert data.
  - Keep keyboard-mouse pathway in mind for future desktop control.
**Current Singularity Mapping**:
  - Current agent uses Mineflayer API; M6 can compare API observations against visual grounding.
  - Promotion review can now consume screenshot references and VLM summaries from session logs as `visual_evidence`, which is a low-cost bridge before full keyboard/mouse VLA control.
  - `promotion-review-ablation` provides the first deterministic/API-visual/screenshot-VLM split for M6 promotion review.
  - `GoalVerificationCritic` now extends the same critic pathway to runtime unknown goal verification.
  - `goal-verification-ablation` replays session goals through deterministic-only, API visual summary, and screenshot/VLM-assisted verification so visual evidence value can be measured before adding keyboard/mouse VLA control.
**Next Action**: Run the split on real screenshot/VLM traces for both promotion review and goal verification tasks.
