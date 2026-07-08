# Paper Index — Minecraft Agent Research

> Last updated: 2026-07-08
> Scoring: Relevance / Novelty / Reproducibility / Engineering Value (1-5 each)

---

## P-001: Voyager: An Open-Ended Embodied Agent with Large Language Models

- **Title**: Voyager: An Open-Ended Embodied Agent with Large Language Models
- **Year**: 2023
- **Link**: https://arxiv.org/abs/2305.16291
- **Authors**: Guanzhi Wang, Yuqi Xie, Yunfan Jiang, Ajay Mandlekar, Chaowei Xiao, Yuke Zhu, Linxi Fan, Anima Anandkumar
- **Type**: Paper + Code
- **Task Type**: Open-ended exploration, skill acquisition
- **Core Method**: LLM-powered curriculum + code-as-skill library + self-verification
- **Action Space**: JavaScript code (Mineflayer API)
- **Memory**: Skill library (code), environment feedback
- **Key Results**: Explored 3.3x more unique items, traveled 2.3x longer distances vs baselines
- **Open Source**: Yes (Apache 2.0)
- **Reproducibility**: High (code available, Mineflayer-based)
- **Scores**: R=5, N=5, R=5, E=5
- **Value to Project**: Foundational — directly informs skill library, curriculum, and code-as-action design
- **Singularity Status**: Deterministic automatic curriculum layer now implemented in `CurriculumManager`; deterministic self-verification now implemented in `GoalVerifier`; live autonomous comparison still pending
- **Reproduction Priority**: P1 (core reference)

---

## P-002: MineDojo: Building Open-Ended Embodied Agents with Internet-Scale Knowledge

- **Title**: MineDojo: Building Open-Ended Embodied Agents with Internet-Scale Knowledge
- **Year**: 2022
- **Link**: https://arxiv.org/abs/2206.08853
- **Authors**: Linxi Fan, Guanzhi Wang, Yunfan Jiang, Ajay Mandlekar, Yuncong Yang, Haoyi Zhu, Ling Tang, Yuke Zhu
- **Type**: Paper + Benchmark + Code
- **Task Type**: 1000+ tasks (creative, survival, exploration)
- **Core Method**: Foundation model + YouTube video pretraining + simulation benchmark
- **Action Space**: MineRL action space (discrete)
- **Memory**: None (feedforward)
- **Key Results**: Large-scale benchmark with diverse tasks; demonstrated RL/LLM evaluation framework
- **Open Source**: Yes (MIT)
- **Reproducibility**: Medium (MineRL dependency, complex setup)
- **Scores**: R=5, N=4, R=3, E=4
- **Value to Project**: Benchmark suite design, task taxonomy
- **Reproduction Priority**: P2 (benchmark reference)

---

## P-003: JARVIS-1: Open-World Multi-task Agents with Memory-Augmented Multimodal Language Models

- **Title**: JARVIS-1: Open-World Multi-task Agents with Memory-Augmented Multimodal Language Models
- **Year**: 2023
- **Link**: https://arxiv.org/abs/2311.05997
- **Authors**: Zihao Wang, Shaofei Cai, Guanzhou Chen, Anji Liu, Xiaojian Ma, Yitao Liang
- **Type**: Paper + Code
- **Task Type**: Multi-task (700+ Minecraft tasks)
- **Core Method**: Multimodal memory + pretrained visual backbone + LLM planning
- **Action Space**: MineRL / keyboard-level
- **Memory**: Multimodal episodic memory (visual + language)
- **Key Results**: Near-human performance on many tasks; strong memory-augmented retrieval
- **Open Source**: Partial (models and some code)
- **Reproducibility**: Medium (complex multimodal setup)
- **Scores**: R=5, N=5, R=3, E=3
- **Value to Project**: Memory system design, multimodal grounding
- **Reproduction Priority**: P2 (memory system reference)

---

## P-004: GITM: Ghost in the Minecraft — Generally Capable Agents for Minecraft with Text-based Knowledge and Memory

- **Title**: GITM: Ghost in the Minecraft
- **Year**: 2023
- **Link**: https://arxiv.org/abs/2305.17209
- **Authors**: Zihao Wang, Shaofei Cai, Anji Liu, Xiaojian Ma, Yitao Liang
- **Type**: Paper + Code
- **Task Type**: Long-horizon survival (obtain diamond)
- **Core Method**: Text-only LLM + structured action primitives + knowledge base
- **Action Space**: 300+ structured text actions
- **Memory**: Text-based knowledge and memory
- **Key Results**: 67.5% success rate on diamond task; outperformed RL baselines
- **Open Source**: Yes
- **Reproducibility**: High (text-based, minimal dependencies)
- **Scores**: R=5, N=4, R=4, E=4
- **Value to Project**: Demonstrates text-only LLM viability, structured action space design
- **Reproduction Priority**: P1 (action space reference)

---

## P-005: DEPS: Describe, Explain, Plan and Select — Interactive Planning with LLMs for Open-World Multi-task Agents

- **Title**: DEPS
- **Year**: 2023
- **Link**: https://arxiv.org/abs/2302.01560
- **Authors**: Zihao Wang, Shaofei Cai, Anji Liu, Yonggang Jin, Jinbing Hou, Bowei Zhang, Haowei Lin, Zhenghao Xing, Zilong Zheng, Yitao Liang
- **Type**: Paper
- **Task Type**: Multi-task planning in Minecraft
- **Core Method**: Describe-Explain-Plan-Select framework with LLM feedback loops
- **Action Space**: Text-based plans
- **Memory**: Goal and subtask state tracking
- **Key Results**: Improved multi-task completion via iterative feedback
- **Open Source**: Partial
- **Reproducibility**: Medium
- **Scores**: R=4, N=3, R=3, E=3
- **Value to Project**: Planning loop design (describe-explain-plan-select)
- **Reproduction Priority**: P3

---

## P-006: STEVE-1: A Generative Model for Text-to-Behavior in Minecraft

- **Title**: STEVE-1
- **Year**: 2023
- **Link**: https://arxiv.org/abs/2306.00937
- **Authors**: Shalev Lifshitz, Keiran Paster, Harris Chan, Jimmy Ba, Sheila McIlraith
- **Type**: Paper + Code
- **Task Type**: Text-conditioned behavior generation
- **Core Method**: Latent action pretraining + text-conditioned RL
- **Action Space**: MineRL behavior tokens
- **Memory**: None (reactive)
- **Key Results**: Zero-shot text-to-behavior without human demonstrations
- **Open Source**: Yes
- **Reproducibility**: Medium (MineRL dependency)
- **Scores**: R=3, N=4, R=3, E=2
- **Value to Project**: VLA reference, text-conditioned action generation
- **Reproduction Priority**: P3

---

## P-007: OmniJARVIS: Vision-Language-Action World Models for Open-World Agents

- **Title**: OmniJARVIS
- **Year**: 2024
- **Link**: https://arxiv.org/abs/2407.03439
- **Authors**: Yining Zhou, Zihao Wang, Shaofei Cai, Anji Liu, Xiaojuan Qi, Yitao Liang
- **Type**: Paper
- **Task Type**: Open-world multimodal agent
- **Core Method**: VLA world model with multimodal memory
- **Action Space**: Behavior tokens + language
- **Memory**: Multimodal episodic + semantic
- **Key Results**: Unified vision-language-action model for open-world Minecraft
- **Open Source**: Partial
- **Reproducibility**: Low (large model, complex training)
- **Scores**: R=4, N=5, R=2, E=2
- **Value to Project**: State-of-the-art VLA reference
- **Reproduction Priority**: P4 (research reference only)

---

## P-008: Mindcraft: An Extensible Platform for Language-Guided Minecraft Agents

- **Title**: Mindcraft
- **Year**: 2024
- **Link**: https://github.com/kolbytn/mindcraft
- **Authors**: Kolby Nottingham, Prithviraj Ammanabrolu, et al.
- **Type**: Code + Platform
- **Task Type**: General-purpose Minecraft LLM agent
- **Core Method**: LLM + Mineflayer, modular agent design
- **Action Space**: Mineflayer API + natural language
- **Memory**: Conversation + skills
- **Key Results**: Open platform for LLM Minecraft agents
- **Open Source**: Yes (MIT)
- **Reproducibility**: High
- **Scores**: R=5, N=3, R=5, E=5
- **Value to Project**: Direct engineering reference, possible integration base
- **Reproduction Priority**: P1 (must evaluate)

---

## P-009: Optimus-1: A Unified Multi-Agent Framework for Long-Horizon Minecraft Tasks

- **Title**: Optimus-1
- **Year**: 2024
- **Link**: https://arxiv.org/abs/2407.04901
- **Authors**: Honghao Cai, Zewei Lin, et al.
- **Type**: Paper
- **Task Type**: Long-horizon (diamond obtainment, multi-step survival)
- **Core Method**: Hierarchical multi-agent with knowledge graph
- **Action Space**: Structured text actions
- **Memory**: Knowledge graph + episodic
- **Key Results**: Strong long-horizon performance via structured knowledge injection
- **Open Source**: TBD
- **Reproducibility**: Low-Medium
- **Scores**: R=4, N=4, R=2, E=3
- **Value to Project**: Knowledge graph integration, long-horizon planning
- **Reproduction Priority**: P3

---

## P-010: Generative Interactive Environments (Genie / GameGen)

- **Title**: Generative Interactive Environments
- **Year**: 2024
- **Link**: https://arxiv.org/abs/2402.01604
- **Authors**: Jake Bruce, Michael Dennis, et al.
- **Type**: Paper
- **Task Type**: World model / environment generation
- **Core Method**: Video generation model as interactive environment
- **Action Space**: Learned latent actions
- **Memory**: None
- **Key Results**: Learned playable environments from video data
- **Open Source**: No
- **Reproducibility**: Low
- **Scores**: R=2, N=5, R=1, E=1
- **Value to Project**: Long-term vision for world models (not immediate use)
- **Reproduction Priority**: P5

---

## P-011: ReAct: Synergizing Reasoning and Acting in Language Models

- **Title**: ReAct
- **Year**: 2022
- **Link**: https://arxiv.org/abs/2210.03629
- **Authors**: Shunyu Yao, Jeffrey Zhao, et al.
- **Type**: Paper
- **Task Type**: General reasoning + acting framework
- **Core Method**: Interleaved reasoning and acting traces
- **Action Space**: Tool use / text
- **Memory**: Reasoning trace
- **Key Results**: Improved factuality and task success via explicit reasoning
- **Open Source**: Yes
- **Reproducibility**: High
- **Scores**: R=3, N=3, R=5, E=4
- **Value to Project**: Reasoning-acting loop design for planner
- **Reproduction Priority**: P2

---

## P-012: Reflexion: Language Agents with Verbal Reinforcement Learning

- **Title**: Reflexion
- **Year**: 2023
- **Link**: https://arxiv.org/abs/2303.11366
- **Authors**: Noah Shinn, Federico Cassano, et al.
- **Type**: Paper + Code
- **Task Type**: Self-reflection and improvement
- **Core Method**: Verbal self-reflection after failure for retry improvement
- **Action Space**: Text / code
- **Memory**: Reflection traces
- **Key Results**: Significant improvement on coding and reasoning benchmarks via reflection
- **Open Source**: Yes
- **Reproducibility**: High
- **Scores**: R=4, N=3, R=5, E=4
- **Value to Project**: Reflection module design, failure recovery
- **Reproduction Priority**: P2

---

## P-013: Code as Policies: Language Model Programs for Embodied Control

- **Title**: Code as Policies
- **Year**: 2022
- **Link**: https://arxiv.org/abs/2209.07753
- **Authors**: Jacky Liang, Wenlong Huang, et al.
- **Type**: Paper
- **Task Type**: Robot control via generated code
- **Core Method**: LLM generates Python code for robot policy execution
- **Action Space**: Python code (robot API)
- **Memory**: Code library
- **Key Results**: Effective robot control from natural language via code generation
- **Open Source**: Partial
- **Reproducibility**: High
- **Scores**: R=4, N=4, R=5, E=5
- **Value to Project**: Code-as-skill methodology, action controller design
- **Reproduction Priority**: P1

---

## P-014: Tree of Thoughts: Deliberate Problem Solving with Large Language Models

- **Title**: Tree of Thoughts (ToT)
- **Year**: 2023
- **Link**: https://arxiv.org/abs/2305.10601
- **Authors**: Shunyu Yao, Dian Yu, et al.
- **Type**: Paper
- **Task Type**: Deliberate reasoning
- **Core Method**: Tree-structured exploration of reasoning paths
- **Action Space**: Text
- **Memory**: Reasoning tree
- **Key Results**: Improved problem-solving on tasks requiring exploration
- **Open Source**: Yes
- **Reproducibility**: High
- **Scores**: R=3, N=3, R=5, E=3
- **Value to Project**: Planner design for complex multi-step tasks
- **Reproduction Priority**: P3

---

## P-015: Toolformer: Language Models Can Teach Themselves to Use Tools

- **Title**: Toolformer
- **Year**: 2023
- **Link**: https://arxiv.org/abs/2302.04761
- **Authors**: Timo Schick, et al.
- **Type**: Paper
- **Task Type**: Tool use
- **Core Method**: Self-taught API call insertion in text
- **Action Space**: Tool API calls
- **Memory**: Learned tool patterns
- **Key Results**: LLMs can learn when and how to use external tools
- **Open Source**: Partial
- **Reproducibility**: Medium
- **Scores**: R=3, N=3, R=3, E=3
- **Value to Project**: Tool use design, Minecraft API as "tool"
- **Reproduction Priority**: P3

---

## P-016: SkillForge: Toward Generalist Embodied Agents via Skill Mining and Composition

- **Title**: SkillForge (conceptual, from literature survey)
- **Year**: 2024
- **Link**: TBD (preprint/search)
- **Type**: Paper
- **Task Type**: Skill discovery and composition
- **Core Method**: Automated skill mining from successful trajectories
- **Action Space**: Variable
- **Memory**: Skill library
- **Key Results**: Demonstrates automated skill extraction and reuse
- **Open Source**: TBD
- **Reproducibility**: TBD
- **Scores**: R=4, N=4, R=2, E=3
- **Value to Project**: Skill library automation
- **Reproduction Priority**: P3

---

## P-017: Minecraft Universe (MCU) / Collaborative Agents

- **Title**: Multi-agent collaboration in Minecraft
- **Year**: 2024
- **Link**: TBD (various preprints)
- **Type**: Papers
- **Task Type**: Multi-agent cooperation
- **Core Method**: Shared memory / communication / role assignment
- **Action Space**: Variable
- **Memory**: Shared memory
- **Key Results**: Limited but growing work on multi-agent Minecraft
- **Open Source**: TBD
- **Reproducibility**: Low
- **Scores**: R=4, N=3, R=1, E=2
- **Value to Project**: M7 multi-agent reference
- **Reproduction Priority**: P4

---

## P-018: PEAM: Parametric Embodied Agent Memory

- **Title**: PEAM: Parametric Embodied Agent Memory through Contrastive Internalization of Experience in Minecraft
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2605.27762
- **Type**: Paper
- **Task Type**: Long-horizon Minecraft memory consolidation
- **Core Method**: Slow deliberative LLM + fast parametric MoE-LoRA memory internalized from selected experiences
- **Action Space**: Minecraft embodied actions
- **Memory**: Episodic staging plus parameter-resident skill memory
- **Key Results**: Improved long-horizon performance, retention, and parametric-vs-retrieval efficiency
- **Scores**: R=5, N=5, R=2, E=4
- **Value to Project**: Consolidation-worthiness, failure-correction learning, slow/fast split
- **Reproduction Priority**: P3
- **Card**: `2026-07-08-peam.md`

---

## P-019: Echo: Experience Transfer for Multimodal LLM Agents

- **Title**: Experience Transfer for Multimodal LLM Agents in Minecraft Game
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2604.05533
- **Type**: Paper
- **Task Type**: Experience transfer and object unlocking
- **Core Method**: Transfer-oriented memory with structure, attribute, process, function, and interaction dimensions
- **Action Space**: Multimodal Minecraft agent actions
- **Memory**: Dimensioned experience atoms plus in-context analogy learning
- **Key Results**: Reports faster object unlocking and transfer to related tasks
- **Scores**: R=5, N=4, R=3, E=5
- **Value to Project**: Direct match for `ExperienceRecord` and memory retrieval upgrades
- **Reproduction Priority**: P2
- **Card**: `2026-07-08-echo.md`

---

## P-020: WISE: Why-Which Reasoning

- **Title**: WISE: A Long-Horizon Agent in Minecraft with Why-Which Reasoning
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2606.12852
- **Type**: Paper
- **Task Type**: Long-horizon sparse Minecraft tasks
- **Core Method**: Causal event graph plus opportunistic task scheduler and progressive exploration
- **Action Space**: Minecraft low-level controller actions
- **Memory**: Which-why causal event memory
- **Key Results**: Reports better success and efficiency under sparse long-horizon conditions
- **Scores**: R=5, N=4, R=3, E=5
- **Value to Project**: Causal memory and opportunistic scheduling are already partially implemented
- **Reproduction Priority**: P2
- **Card**: `2026-07-08-wise.md`

---

## P-021: TickingCollabBench

- **Title**: Multi-agent Framework for Time-Sensitive Complementary Collaboration in Minecraft
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2606.15684
- **Type**: Paper + Benchmark
- **Task Type**: Multi-agent time-sensitive complementary collaboration
- **Core Method**: Heterogeneous roles, mandatory cooperation, dynamic environments, deadlines, feasibility-checked task generation
- **Action Space**: Abstracted Minecraft primitive APIs
- **Memory**: Shared state and communication under evaluation
- **Key Results**: Shows LLM agents struggle with latency, dynamic coordination, and partial observability
- **Scores**: R=5, N=5, R=3, E=5
- **Value to Project**: Blueprint for M7 benchmark schema
- **Reproduction Priority**: P2
- **Card**: `2026-07-08-tickingcollabbench.md`

---

## P-022: VistaWise

- **Title**: VistaWise: Building Cost-Effective Agent with Cross-Modal Knowledge Graph for Minecraft
- **Year**: 2025
- **Link**: https://arxiv.org/abs/2508.18722
- **Type**: Paper
- **Task Type**: Open-world embodied decision-making in Minecraft
- **Core Method**: Cross-modal knowledge graph, visual detector, retrieval pooling, desktop skill library
- **Action Space**: Minecraft desktop-level control
- **Memory**: Cross-modal knowledge graph
- **Key Results**: Reports strong open-world performance with lower domain-specific data cost
- **Scores**: R=4, N=4, R=3, E=4
- **Value to Project**: Validates the lightweight graph direction before M6 vision
- **Reproduction Priority**: P3
- **Card**: `2026-07-08-vistawise.md`

---

## P-023: Optimus-2

- **Title**: Optimus-2: Multimodal Minecraft Agent with Goal-Observation-Action Conditioned Policy
- **Year**: 2025
- **Link**: https://arxiv.org/abs/2502.19902
- **Type**: Paper + Dataset
- **Task Type**: Atomic, long-horizon, and open-ended Minecraft tasks
- **Core Method**: MLLM planner plus goal-observation-action conditioned low-level policy
- **Action Space**: Goal-observation-action action prediction
- **Memory**: Compact behavior tokens over observation-action history
- **Key Results**: Reports strong performance across multiple Minecraft task categories
- **Scores**: R=4, N=4, R=2, E=3
- **Value to Project**: Supports compact action-history summaries and planner/actor split
- **Reproduction Priority**: P3
- **Card**: `2026-07-08-optimus2.md`

---

## P-024: JARVIS-VLA

- **Title**: JARVIS-VLA: Post-Training Large-Scale Vision Language Models to Play Visual Games with Keyboards and Mouse
- **Year**: 2025
- **Link**: https://arxiv.org/abs/2503.16365
- **Type**: Paper + Code/Models/Datasets
- **Task Type**: Visual Minecraft atomic tasks
- **Core Method**: Visual-language post-training before VLA action training
- **Action Space**: Keyboard and mouse
- **Memory**: Mostly parametric multimodal grounding
- **Key Results**: Reports broad instruction following across 1k+ atomic tasks and gains from non-trajectory post-training
- **Scores**: R=4, N=4, R=3, E=3
- **Value to Project**: M6 vision baseline and future desktop-control reference
- **Reproduction Priority**: P3
- **Card**: `2026-07-08-jarvis-vla.md`

---

## P-025: Game-TARS

- **Title**: Game-TARS: Pretrained Foundation Models for Scalable Generalist Multimodal Game Agents
- **Year**: 2025
- **Link**: https://arxiv.org/abs/2510.23691
- **Type**: Paper + Foundation Model
- **Task Type**: Cross-game generalist multimodal agents
- **Core Method**: Unified keyboard-mouse action space, large-scale multimodal pretraining, sparse-thinking
- **Action Space**: Native keyboard and mouse
- **Memory**: Parametric pretraining
- **Key Results**: Reports strong open-world Minecraft and cross-game generalization
- **Scores**: R=3, N=5, R=1, E=3
- **Value to Project**: Long-term action abstraction and sparse reasoning reference
- **Reproduction Priority**: P4
- **Card**: `2026-07-08-game-tars.md`

---

## P-026: Odyssey

- **Title**: Odyssey: Empowering Minecraft Agents with Open-World Skills
- **Year**: 2025
- **Link**: https://arxiv.org/abs/2407.15325
- **Type**: Paper + Code/Dataset
- **Task Type**: Long-term planning, dynamic-immediate planning, autonomous exploration
- **Core Method**: Planner-actor-critic with open-world skill library and self-validation
- **Action Space**: Mineflayer/code skills
- **Memory**: Skill library plus successful/failed task feedback
- **Key Results**: Introduces 40 primitive skills, 183 compositional skills, and open-world Minecraft capability benchmarks
- **Scores**: R=5, N=4, R=4, E=5
- **Value to Project**: Direct reference for skill-level critic/self-validation, suite-level candidate quality tracking, and broader open-world skill taxonomy
- **Reproduction Priority**: P2
- **Card**: `2026-07-08-odyssey.md`

---

## P-027: OpenSkill

- **Title**: OpenSkill: Open-World Self-Evolution for LLM Agents
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2606.06741
- **Type**: Paper / self-evolution framework
- **Task Type**: Open-world self-improvement without pre-existing verifier signals
- **Core Method**: Mine open resources for knowledge and verification anchors, synthesize skills, and refine them on virtual practice tasks
- **Action Space**: General agent skills
- **Memory**: Transferable skill/anchor library
- **Key Results**: Reports higher automated pass rates while avoiding target-task supervision
- **Scores**: R=4, N=5, R=2, E=5
- **Value to Project**: Blueprint for generating verifier anchors and aggregating verifier-gated skill readiness instead of hand-writing every postcondition
- **Reproduction Priority**: P2
- **Card**: `2026-07-08-openskill.md`

---

## P-028: MineExplorer

- **Title**: Evaluating Open-World Exploration of MLLM Agents in Minecraft
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2605.30931
- **Type**: Benchmark / evaluation framework
- **Task Type**: Open-world exploration
- **Core Method**: ReAct-style evaluation across perception, reasoning, and action while reducing Minecraft-prior confounds
- **Action Space**: MLLM agent actions in Minecraft
- **Memory**: Exploration trace evidence
- **Key Results**: Introduces a Minecraft benchmark focused on sustained open-world exploration capability
- **Scores**: R=4, N=4, R=3, E=4
- **Value to Project**: Blueprint for autonomous-mode exploration coverage metrics beyond inventory unlocks
- **Reproduction Priority**: P2
- **Card**: `2026-07-08-mineexplorer.md`

---

## P-029: OpenHA / CrossAgent

- **Title**: OpenHA: A Series of Open-Source Hierarchical Agentic Models in Minecraft
- **Year**: 2025-2026
- **Link**: https://arxiv.org/abs/2509.13347
- **Type**: Paper + code + model/dataset release
- **Task Type**: Hierarchical Minecraft action-space generalization
- **Core Method**: Chain of Action treats abstract actions as intermediate reasoning, while CrossAgent learns heterogeneous action-space switching
- **Action Space**: Mixed abstract actions, VLA actions, and low-level controls
- **Memory**: Trained hierarchical policy traces
- **Key Results**: Reports stronger generalization from mixed action spaces and CoA-style abstraction
- **Scores**: R=4, N=5, R=4, E=4
- **Value to Project**: Direct reference for extending `ActionMapper` into a cross-level action abstraction benchmark
- **Reproduction Priority**: P2
- **Card**: `2026-07-08-openha.md`

---

## Summary Table

| ID | Paper | Year | Scores | Priority |
|----|-------|------|--------|----------|
| P-001 | Voyager | 2023 | R5/N5/R5/E5 | P1 |
| P-002 | MineDojo | 2022 | R5/N4/R3/E4 | P2 |
| P-003 | JARVIS-1 | 2023 | R5/N5/R3/E3 | P2 |
| P-004 | GITM | 2023 | R5/N4/R4/E4 | P1 |
| P-005 | DEPS | 2023 | R4/N3/R3/E3 | P3 |
| P-006 | STEVE-1 | 2023 | R3/N4/R3/E2 | P3 |
| P-007 | OmniJARVIS | 2024 | R4/N5/R2/E2 | P4 |
| P-008 | Mindcraft | 2024 | R5/N3/R5/E5 | P1 |
| P-009 | Optimus-1 | 2024 | R4/N4/R2/E3 | P3 |
| P-010 | Genie | 2024 | R2/N5/R1/E1 | P5 |
| P-011 | ReAct | 2022 | R3/N3/R5/E4 | P2 |
| P-012 | Reflexion | 2023 | R4/N3/R5/E4 | P2 |
| P-013 | Code as Policies | 2022 | R4/N4/R5/E5 | P1 |
| P-014 | ToT | 2023 | R3/N3/R5/E3 | P3 |
| P-015 | Toolformer | 2023 | R3/N3/R3/E3 | P3 |
| P-016 | SkillForge | 2024 | R4/N4/R2/E3 | P3 |
| P-017 | Multi-Agent MC | 2024 | R4/N3/R1/E2 | P4 |
| P-018 | PEAM | 2026 | R5/N5/R2/E4 | P3 |
| P-019 | Echo | 2026 | R5/N4/R3/E5 | P2 |
| P-020 | WISE | 2026 | R5/N4/R3/E5 | P2 |
| P-021 | TickingCollabBench | 2026 | R5/N5/R3/E5 | P2 |
| P-022 | VistaWise | 2025 | R4/N4/R3/E4 | P3 |
| P-023 | Optimus-2 | 2025 | R4/N4/R2/E3 | P3 |
| P-024 | JARVIS-VLA | 2025 | R4/N4/R3/E3 | P3 |
| P-025 | Game-TARS | 2025 | R3/N5/R1/E3 | P4 |
| P-026 | Odyssey | 2025 | R5/N4/R4/E5 | P2 |
| P-027 | OpenSkill | 2026 | R4/N5/R2/E5 | P2 |
| P-028 | MineExplorer | 2026 | R4/N4/R3/E4 | P2 |
| P-029 | OpenHA / CrossAgent | 2025-2026 | R4/N5/R4/E4 | P2 |
