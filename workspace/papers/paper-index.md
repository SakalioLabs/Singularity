# Paper Index — Minecraft Agent Research

> Last updated: 2026-07-09
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
- **Value to Project**: Motivates `ActionValueProfile` and `action-value-report` as a non-parametric staging layer for consolidation-worthiness, failure-correction learning, and eventual slow/fast skill internalization
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
- **Value to Project**: Direct match for `ExperienceRecord`, dimension-weighted transfer retrieval, and `transfer-memory-report` audits
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

## P-030: AutoMem

- **Title**: AutoMem: Automated Learning of Memory as a Cognitive Skill
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2607.01224
- **Type**: Paper
- **Task Type**: Long-horizon game-agent memory optimization
- **Core Method**: Treats memory management as a trainable cognitive skill with scaffold revision and training from good memory decisions
- **Action Space**: Task actions plus explicit file-system memory actions
- **Memory**: File-system memory operations, scaffold revision, and memory proficiency learning
- **Key Results**: Reports that optimizing memory alone improves long-horizon game-agent performance without changing task actions
- **Scores**: R=5, N=5, R=4, E=4
- **Value to Project**: Blueprint for turning Singularity memory reports into a feedback policy for what to write, retrieve, consolidate, or ignore
- **Reproduction Priority**: P2
- **Card**: `2026-07-08-automem.md`

---

## P-031: Memory for Autonomous LLM Agents

- **Title**: Memory for Autonomous LLM Agents: Mechanisms, Evaluation, and Open Challenges
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2603.07670
- **Type**: Survey
- **Task Type**: General long-horizon autonomous-agent memory
- **Core Method**: Formalizes agent memory as a write-manage-read loop across temporal scope, representation, and control policy
- **Action Space**: Memory lifecycle operations linked to perception and action
- **Memory**: Write, management, retrieval, update, and evaluation mechanisms
- **Key Results**: Provides a taxonomy and evaluation framing for memory as a controlled agent subsystem
- **Scores**: R=5, N=4, R=4, E=5
- **Value to Project**: Direct justification for separating Singularity memory write/read/manage policy metrics in session-log reports
- **Reproduction Priority**: P1
- **Card**: `2026-07-08-agent-memory-survey.md`

---

## P-032: Agentic Memory

- **Title**: Agentic Memory: Learning Unified Long-Term and Short-Term Memory Management for Large Language Model Agents
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2601.01885
- **Type**: Paper
- **Task Type**: Unified long-horizon memory policy
- **Core Method**: Exposes store, retrieve, update, summarize, and discard as tool-like memory actions trained by progressive reinforcement learning
- **Action Space**: Task actions plus memory operations
- **Memory**: Unified short-term and long-term memory management policy
- **Key Results**: Reports improved task performance, memory quality, and context efficiency on long-horizon benchmarks
- **Scores**: R=5, N=5, R=3, E=4
- **Value to Project**: Blueprint for turning Singularity memory lifecycle instrumentation into a policy that can eventually enforce write gates
- **Reproduction Priority**: P2
- **Card**: `2026-07-08-agentic-memory.md`

---

## P-033: GovMem

- **Title**: When Not to Write Memory: Governing False Promotion from Correlated Agent Traces
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2607.02579
- **Type**: Paper
- **Task Type**: Memory write-path governance for long-running and multi-agent LLM agents
- **Core Method**: Dependency-aware support checks with promote, reject, and needs-review routes for candidate memories
- **Action Space**: Memory write decisions linked to agent traces
- **Memory**: Candidate durable memories with provenance, scope, counterevidence, and dependency metadata
- **Key Results**: Identifies false promotion from correlated traces and proposes conservative write governance
- **Scores**: R=5, N=5, R=3, E=5
- **Value to Project**: Direct blueprint for preventing noisy or correlated M7 traces from becoming durable shared memory
- **Reproduction Priority**: P2
- **Card**: `2026-07-08-govmem.md`

---

## P-034: STALE

- **Title**: STALE: Can LLM Agents Know When Their Memories Are No Longer Valid?
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2605.06527
- **Type**: Paper + Benchmark
- **Task Type**: Long-term memory validity, implicit conflict, and stale-state evaluation
- **Core Method**: Probes state resolution, premise resistance, and implicit policy adaptation under changing user/world state
- **Action Space**: Memory write/read/use decisions linked to downstream behavior
- **Memory**: Mutable state memories with supersession and propagation-aware revision
- **Key Results**: Shows a gap between retrieving updated evidence and acting on it under implicit conflicts
- **Scores**: R=5, N=5, R=4, E=5
- **Value to Project**: Blueprint for M7 shared-memory supersession and stale-world-state review before stale facts influence task scheduling
- **Reproduction Priority**: P2
- **Card**: `2026-07-08-stale.md`

---

## P-035: MemConflict

- **Title**: MemConflict: Evaluating Long-Term Memory Systems Under Memory Conflicts
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2605.20926
- **Type**: Paper + Diagnostic Benchmark
- **Task Type**: Long-term memory retrieval under temporal, factual, and conditional conflicts
- **Core Method**: Query-conditioned memory validity evaluation with white-box retrieval/ranking diagnostics
- **Action Space**: Memory evidence selection before answer/action generation
- **Memory**: Competing memory candidates with temporal validity, factual correctness, and contextual applicability
- **Key Results**: Shows retrieval/ranking failures can diverge from final-answer correctness under conflicting evidence
- **Scores**: R=5, N=5, R=4, E=5
- **Value to Project**: Blueprint for read-time stale and condition-mismatch filtering before memories enter Minecraft planning prompts
- **Reproduction Priority**: P2
- **Card**: `2026-07-08-memconflict.md`

---

## P-036: ActMem

- **Title**: ActMem: Bridging the Gap Between Memory Retrieval and Reasoning in LLM Agents
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2603.00026
- **Type**: Paper + Evaluation Dataset
- **Task Type**: Actionable memory retrieval and reasoning under implicit constraints
- **Core Method**: Causal-semantic memory graph with counterfactual reasoning and conflict resolution
- **Action Space**: Memory-conditioned decisions and downstream actions
- **Memory**: Structured causal and semantic graph extracted from long-term histories
- **Key Results**: Reports better handling of complex memory-dependent decisions than passive retrieval baselines
- **Scores**: R=4, N=5, R=3, E=5
- **Value to Project**: Supports combining durable memory, causal events, and action context into one conflict-aware retrieval substrate
- **Reproduction Priority**: P2
- **Card**: `2026-07-08-actmem.md`

---

## P-037: MineNPC-Task

- **Title**: MineNPC-Task: Task Suite for Memory-Aware Minecraft Agents
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2601.05215
- **Type**: Benchmark / evaluation harness
- **Task Type**: Memory-aware, mixed-initiative player-authored Minecraft requests
- **Core Method**: Parametric templates with dependencies, required slots, one targeted clarification, bounded Mineflayer perception/action constraints, and machine-checkable validators
- **Action Space**: Public Mineflayer APIs under bounded-knowledge policy
- **Memory**: Scoped landmarks, artifacts, preferences, commitments, and breakdown records with provenance
- **Key Results**: Reports 216 subtasks across 8 expert-player co-play sessions and highlights recurring execution, inventory/tool, referencing, and navigation failures
- **Scores**: R=5, N=4, R=4, E=5
- **Value to Project**: Direct blueprint for user-authored task templates, clarification-to-memory flow, and bounded-evidence validation in Singularity benchmarks
- **Reproduction Priority**: P2
- **Card**: `2026-07-08-minenpc-task.md`

---

## P-038: NitroGen

- **Title**: NitroGen: An Open Foundation Model for Generalist Gaming Agents
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2601.02427
- **Type**: Foundation model / dataset / benchmark
- **Task Type**: Cross-game vision-action control and generalist game-agent transfer
- **Core Method**: Unified vision-action model trained from 40,000 hours of gameplay videos across more than 1,000 games
- **Action Space**: Shared gamepad / vision-action behavior cloning interface
- **Memory**: Mostly parametric visual-action priors rather than explicit symbolic memory
- **Key Results**: Reports transfer to unseen games and procedurally generated worlds with stronger task success than training from scratch
- **Scores**: R=3, N=5, R=4, E=4
- **Value to Project**: Validates Singularity's two-lane strategy: keep Mineflayer API for reproducible tasks while logging visual/action traces and identifying task families that may need learned low-level control
- **Reproduction Priority**: P3
- **Card**: `2026-07-08-nitrogen.md`

---

## P-039: GameWorld

- **Title**: GameWorld: Towards Standardized and Verifiable Evaluation of Multimodal Game Agents
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2604.07429
- **Type**: Benchmark / verifiable evaluation framework
- **Task Type**: Browser-game multimodal agent tasks with standardized semantic and keyboard/mouse action interfaces
- **Core Method**: 34 games and 170 tasks with deterministic Semantic Action Parsing and state-verifiable outcome metrics
- **Action Space**: Direct computer-use controls plus semantic action parsing
- **Memory**: Evaluates context-memory sensitivity as part of repeated benchmark analysis
- **Key Results**: Reports that current model-interface pairs remain far from human-level play and exposes real-time, memory, and action-validity challenges
- **Scores**: R=4, N=5, R=4, E=5
- **Value to Project**: Reinforces Singularity's direction of pairing semantic action abstractions with bounded, state-verifiable task validators
- **Reproduction Priority**: P2
- **Card**: `2026-07-08-gameworld.md`

---

## P-040: OmniGameArena

- **Title**: OmniGameArena: A Unified UE5 Benchmark for VLM Game Agents with Improvement Dynamics
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2606.09826
- **Type**: Benchmark / reflection-harness evaluation
- **Task Type**: Real-time solo, PvP, and cooperative VLM game tasks
- **Core Method**: Unified UE5 benchmark plus Improvement Dynamics Curve for bounded multi-round skill-prompt refinement and held-out variants
- **Action Space**: Unified real-time game action interfaces
- **Memory**: Tests whether reflection-derived skill prompts improve or overfit across repeated rounds
- **Key Results**: Adds improvement dynamics and held-out task behavior as evaluation signals beyond one cold-start score
- **Scores**: R=3, N=5, R=3, E=4
- **Value to Project**: Suggests extending Singularity's ablation reports into repeated replay curves before promoting visual-action policies or mixed-initiative templates
- **Reproduction Priority**: P3
- **Card**: `2026-07-08-omnigamearena.md`

---

## P-041: SciCrafter

- **Title**: Can Current Agents Close the Discovery-to-Application Gap? A Case Study in Minecraft
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2604.24697
- **Type**: Benchmark / diagnostic evaluation
- **Task Type**: Minecraft redstone discovery-to-application tasks
- **Core Method**: Parameterized redstone circuits that require knowledge-gap identification, experimental discovery, consolidation, and final construction
- **Action Space**: Minecraft construction and experiment actions
- **Memory**: Experiment hypotheses, causal observations, and consolidated rules
- **Key Results**: Reports a large gap between discovering causal rules and applying them reliably in scaled Minecraft build tasks
- **Scores**: R=5, N=5, R=3, E=5
- **Value to Project**: Blueprint for adding experiment-before-build task phases and gating generated redstone/building skills on held-out application evidence
- **Reproduction Priority**: P2
- **Card**: `2026-07-09-scicrafter.md`

---

## P-042: WhisperBench / MemGhost

- **Title**: When Claws Remember but Do Not Tell: Stealthy Memory Injection in Persistent Personal Agents
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2607.05189
- **Type**: Security benchmark / attack study
- **Task Type**: Persistent-agent memory injection across real workflow surfaces
- **Core Method**: End-to-end benchmark and one-shot payload generator for poisoning durable memories without visible user warning
- **Action Space**: External-content processing, memory writes, and later agent actions
- **Memory**: Persistent fact and preference memories with provenance-sensitive trust boundaries
- **Key Results**: Shows memory poisoning can persist and transfer across persistent-agent architectures and memory backends
- **Scores**: R=5, N=5, R=3, E=5
- **Value to Project**: Direct support for gate-first promotion plus read-time filtering of promptware-like memory, skills, shared-state consolidations, and mixed-policy patches before runtime use
- **Reproduction Priority**: P1
- **Card**: `2026-07-09-whisperbench.md`

---

## P-043: SkillDAG

- **Title**: SkillDAG: Self-Evolving Typed Skill Graphs for LLM Skill Selection at Scale
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2606.03056
- **Type**: Skill retrieval / skill graph framework
- **Task Type**: Large-scale agent skill selection and graph evolution
- **Core Method**: Typed directed skill graph with vector matches, graph neighbors, conflict signals, and execution-backed propose-then-commit edge updates
- **Action Space**: General agent skills and typed inter-skill relationships
- **Memory**: Skill graph edges, provenance, conflicts, and execution-backed updates
- **Key Results**: Reports stronger ALFWorld/SkillsBench success, reward, and Ret@K than Graph-of-Skills baselines as skill pools scale
- **Scores**: R=4, N=5, R=4, E=5
- **Value to Project**: Blueprint for turning Singularity's reviewed custom skills into a typed, gate-aware graph rather than a flat list
- **Reproduction Priority**: P2
- **Card**: `2026-07-09-skilldag.md`

---

## P-044: MineEvolve

- **Title**: MineEvolve: Self-Evolution with Accumulated Knowledge for Long-Horizon Embodied Minecraft Agents
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2603.13131
- **Type**: Minecraft self-evolution / execution-feedback framework
- **Task Type**: Long-horizon Minecraft planning, skill induction, and failure repair
- **Core Method**: Monitor typed execution feedback, induce successful skills and failed/stagnant remedies, curate accumulated knowledge, and adapt unfinished plan suffixes
- **Action Space**: Minecraft subgoals and structured action traces
- **Memory**: Accumulated behavioral knowledge from state changes, inventory changes, failures, progress, and stagnation
- **Key Results**: Reports consistent long-horizon improvement across multiple planners, especially on high-dependency task groups
- **Scores**: R=5, N=5, R=3, E=5
- **Value to Project**: Direct blueprint for turning Singularity session logs into progress/stagnation feedback, remedy candidates, and plan-adaptor hints
- **Reproduction Priority**: P1
- **Card**: `2026-07-09-mineevolve.md`

---

## P-045: VLM-AR3L

- **Title**: VLM-AR3L: Vision-Language Models for Absolute and Relative Rewards in Reinforcement Learning
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2607.00483
- **Type**: VLM reward learning / embodied progress evaluation
- **Task Type**: Open-ended visual RL and Minecraft progress evaluation
- **Core Method**: Combines absolute state rewards with relative rewards over consecutive observations using VLM preference labels
- **Action Space**: General RL and open-world embodied tasks
- **Memory**: Consecutive visual observations as progress/regression evidence
- **Key Results**: Reports improved reward learning across control, manipulation, and Minecraft-style open-world tasks
- **Scores**: R=4, N=4, R=3, E=4
- **Value to Project**: Supports adding separate absolute-quality and relative-progress fields before future screenshot/VLM reward labels
- **Reproduction Priority**: P2
- **Card**: `2026-07-09-vlm-ar3l.md`

---

## P-046: EmbodiSkill

- **Title**: EmbodiSkill: Skill-Aware Reflection for Self-Evolving Embodied Agents
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2605.10332
- **Type**: Skill-aware self-evolution / embodied reflection
- **Task Type**: Embodied task execution and skill revision
- **Core Method**: Separates skill-changing evidence from execution-lapse evidence, then performs targeted revision while preserving valid guidance
- **Action Space**: Embodied skills, object search, action execution, and state changes
- **Memory**: Trajectory evidence interpreted against current skill content
- **Key Results**: Reports improved ALFWorld and EmbodiedBench task success through skill-aware reflection
- **Scores**: R=4, N=5, R=3, E=5
- **Value to Project**: Justifies treating perception/action-heavy Minecraft failures as execution lapses before mutating reviewed skills
- **Reproduction Priority**: P2
- **Card**: `2026-07-09-embodiskill.md`

---

## P-047: VASO

- **Title**: VASO: Formally Verifiable Self-Evolving Skills for Physical AI Agents
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2606.05395
- **Type**: Verification-guided self-evolving skill contracts
- **Task Type**: Physical AI skill verification and repair
- **Core Method**: Checks skill contract consistency, verifies induced plans against temporal specifications, and turns counterexamples into textual gradients
- **Action Space**: Robot control commands and planner-facing semantic skill contracts
- **Memory**: Counterexample traces as skill-evolution feedback
- **Key Results**: Reports high formal-specification compliance using fewer than 100 optimization samples on robot tasks
- **Scores**: R=3, N=5, R=3, E=5
- **Value to Project**: Supports keeping Singularity self-evolution feedback advisory until verifier/gate reports approve durable plan or skill changes
- **Reproduction Priority**: P2
- **Card**: `2026-07-09-vaso.md`

---

## P-048: MemoryArena

- **Title**: MemoryArena: Benchmarking Agent Memory in Interdependent Multi-Session Agentic Tasks
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2602.16313
- **Type**: Agent memory benchmark / multi-session evaluation
- **Task Type**: Interdependent multi-session agentic tasks
- **Core Method**: Memory-Agent-Environment loops that require earlier feedback to be distilled into memory and used in later dependent actions
- **Action Space**: Web navigation, preference-constrained planning, progressive information search, and formal reasoning tasks
- **Memory**: Cross-session task memories as decision priors, not passive recall records
- **Key Results**: Shows strong long-context memory benchmark performance does not imply success in agentic memory-use settings
- **Scores**: R=5, N=4, R=3, E=5
- **Value to Project**: Supports task-centric memory reports that tie retrieved memories to active task metadata and downstream verifier outcomes
- **Reproduction Priority**: P2
- **Card**: `2026-07-09-memoryarena.md`

---

## P-049: AGI Maze

- **Title**: AGI Maze as a Benchmark Framework for World-Modeling Agents
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2607.00627
- **Type**: World-modeling benchmark / partially observable grid environments
- **Task Type**: Stateful maze exploration and hidden-map reasoning
- **Core Method**: Lightweight maze environments that require agents to build and manipulate persistent world-state representations from local observations
- **Action Space**: Navigation and observation actions under step budgets
- **Memory**: Explicit world-state map beyond message-history working memory
- **Key Results**: Shows vanilla LLMs struggle to represent even simple mazes internally; message-history working memory helps but remains insufficient
- **Scores**: R=4, N=5, R=3, E=5
- **Value to Project**: Supports explicit Minecraft world-model reports and curriculum feedback with visited cells, transitions, frontier candidates, resources, and dangers for autonomous exploration
- **Reproduction Priority**: P2
- **Card**: `2026-07-09-agimaze.md`

---

## P-050: COS-PLAY

- **Title**: Co-Evolving LLM Decision and Skill Bank Agents for Long-Horizon Tasks
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2604.20987
- **Type**: Co-evolving game-agent skill bank and decision policy
- **Task Type**: Long-horizon game tasks with reusable skill discovery and retrieval
- **Core Method**: A decision agent retrieves skills from a learnable skill bank while a skill-bank agent segments rollouts, learns effect contracts, and curates skill entries
- **Action Space**: Primitive game actions guided by retrieved skill protocols
- **Memory**: Reusable skill bank with contracts, retrieval evidence, and maintenance operations
- **Key Results**: Reports over 25.1% average reward improvement against frontier LLM baselines on single-player game benchmarks while staying competitive on multiplayer social reasoning games
- **Scores**: R=5, N=5, R=4, E=5
- **Value to Project**: Supports contract-aware Minecraft skill retrieval, explicit readiness states, and skill-bank maintenance before online reuse
- **Reproduction Priority**: P1
- **Card**: `2026-07-09-cosplay.md`

---

## P-051: AgenticSTS

- **Title**: AgenticSTS: A Bounded-Memory Testbed for Long-Horizon LLM Agents
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2607.02255
- **Type**: Bounded-memory contract testbed for long-horizon agents
- **Task Type**: Long-horizon game decisions with typed memory/skill snapshots and ablations
- **Core Method**: Replaces raw accumulated prompt history with fresh prompts assembled from typed retrieval layers, then releases trajectories, condition tags, snapshots, prompt records, and analysis scripts
- **Action Space**: Game decisions in a closed-rule stochastic deck-building environment
- **Memory**: Typed retrieval layers and frozen memory/skill snapshots instead of raw cross-decision transcript accumulation
- **Key Results**: Finds the largest directional win-rate difference when triggered strategic skills are enabled in a fixed-A0 ablation
- **Scores**: R=5, N=5, R=4, E=5
- **Value to Project**: Supports bounded planner-context auditing, typed retrieval layer accounting, and raw-transcript risk checks for Minecraft planning cycles
- **Reproduction Priority**: P1
- **Card**: `2026-07-09-agenticsts.md`

---

## P-052: AgentOdyssey

- **Title**: AgentOdyssey: Open-Ended Long-Horizon Text Game Generation for Test-Time Continual Learning Agents
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2606.24893
- **Type**: Open-ended long-horizon game generation and test-time continual learning benchmark
- **Task Type**: Procedurally generated text games with exploration, world dynamics, and long-horizon goals
- **Core Method**: Generates open-ended games and evaluates progress plus world-knowledge acquisition, episodic memory, object/action exploration, action diversity, and cost
- **Action Space**: Text-game actions over generated entities and dynamics
- **Memory**: Short-term and episodic memory as mechanisms for test-time continual learning
- **Key Results**: Shows strong agents remain far below human performance and that short-term memory helps multiple agent paradigms
- **Scores**: R=4, N=5, R=4, E=5
- **Value to Project**: Motivates a unified Minecraft continual-learning diagnostic over exploration, world model, memory, action diversity, and meaningful horizon
- **Reproduction Priority**: P2
- **Card**: `2026-07-09-agentodyssey.md`

---

## P-053: AgentCL

- **Title**: AgentCL: Toward Rigorous Evaluation of Continual Learning in Language Agents
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2606.02461
- **Type**: Continual-learning evaluation framework for language agents
- **Task Type**: Controlled task streams with reusable sub-solutions, evidence, and workflows
- **Core Method**: Constructs compositional streams and measures transfer gains while probing memory designs that store interactions, insights, and skills
- **Action Space**: Language-agent task actions across coding, research, and reasoning domains
- **Memory**: Non-parametric memory with consolidation filters for unreliable experiences
- **Key Results**: Shows controlled reusable streams distinguish memory designs better than naive streams and exposes memory-induced degradation in some settings
- **Scores**: R=4, N=5, R=4, E=5
- **Value to Project**: Motivates controlled Minecraft task streams to measure whether transfer memories and approved skills improve later held-out goals without causing interference
- **Reproduction Priority**: P2
- **Card**: `2026-07-09-agentcl.md`

---

## P-054: MUSE-Autoskill

- **Title**: MUSE-Autoskill: Self-Evolving Agents via Skill Creation, Memory, Management, and Evaluation
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2605.27366
- **Type**: Skill-centric self-evolving agent framework
- **Task Type**: General long-horizon agent tasks with reusable skills and transfer
- **Core Method**: Unifies skill creation, skill-level memory, catalog management, evaluation, and refinement
- **Action Space**: Tool and code-backed agent actions wrapped as reusable skill packages
- **Memory**: Short-term, long-term, and per-skill memory for reusable procedures
- **Key Results**: Reports stronger self-created skill performance than static human-authored skills on covered tasks and effective skill transfer into Hermes-style agents
- **Scores**: R=4, N=5, R=4, E=5
- **Value to Project**: Supports treating Minecraft skills as long-lived assets with skill-local memory, evaluation history, and transfer gates before default reuse
- **Reproduction Priority**: P2
- **Card**: `2026-07-09-muse-autoskill.md`

---

## P-055: RIZZ

- **Title**: RIZZ: Routing Interactions to Near Zero-Interference Zones for Continual Adaptation of Black-Box Agents
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2606.20638
- **Type**: Verifier-gated routed memory for continual black-box adaptation
- **Task Type**: Nonstationary task streams with recurring and interfering task families
- **Core Method**: Routes interactions into memory zones, retrieves bounded branch-local/global context, and updates memory only after verifier feedback
- **Action Space**: Black-box language-agent actions over tool and benchmark tasks
- **Memory**: Branch-local examples, failures, procedural rules, anti-patterns, and verifier-gated updates
- **Key Results**: Shows routed memory can improve recurring tasks while reducing cross-task interference and token cost
- **Scores**: R=4, N=5, R=4, E=5
- **Value to Project**: Motivates Minecraft task-family routing and rejection of memories/skills that hurt held-out or second-pass streams
- **Reproduction Priority**: P2
- **Card**: `2026-07-09-rizz.md`

---

## P-056: Memory Management and Experience-Following

- **Title**: How Memory Management Impacts LLM Agents: An Empirical Study of Experience-Following Behavior
- **Year**: 2026
- **Link**: https://aclanthology.org/2026.acl-long.27/
- **Type**: Empirical study of LLM-agent memory addition/deletion and long-term behavior
- **Task Type**: Agent tasks with retrieved past executions used as future experience
- **Core Method**: Measures experience-following behavior and studies how future task outcomes can label memory quality
- **Action Space**: LLM-agent tool/task outputs influenced by retrieved memory records
- **Memory**: Memory bank quality control, addition/deletion, error propagation, and misaligned experience replay
- **Key Results**: Shows retrieved experience can strongly steer outputs, while inaccurate or misaligned memories can degrade later performance
- **Scores**: R=5, N=4, R=4, E=5
- **Value to Project**: Supports typed Minecraft skill-memory hints and future-task quality labels before replay memories become planner defaults
- **Reproduction Priority**: P1
- **Card**: `2026-07-09-memory-management-experience-following.md`

---

## P-057: Agent-Native Memory System

- **Title**: Are We Ready For An Agent-Native Memory System?
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2606.24775
- **Type**: System-level study of long-term memory for LLM agents
- **Task Type**: Agent memory workloads across storage, extraction, retrieval/routing, and maintenance modules
- **Core Method**: Decomposes memory systems into module-level axes and measures retrieval precision, update correctness, cost, and long-horizon stability
- **Action Space**: Agent tasks with persistent textual, structured, and system-level memory
- **Memory**: Representation/storage, extraction, retrieval/routing, localized maintenance, and dynamic knowledge updates
- **Key Results**: Shows no single architecture dominates and localized maintenance can be more cost-efficient than global reorganization
- **Scores**: R=5, N=4, R=4, E=5
- **Value to Project**: Supports module-level Minecraft memory diagnostics and localized skill-memory retrieval maintenance before mutating skill stores
- **Reproduction Priority**: P1
- **Card**: `2026-07-09-agent-native-memory-system.md`

---

## P-058: MemTier

- **Title**: MemTier: Tiered Memory Architecture and the Retrieval Bottleneck in Long-Running LLM Agents
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2605.03675
- **Type**: OpenClaw runtime memory architecture
- **Task Type**: Long-running agent memory retrieval, attribution, and consolidation
- **Core Method**: Structured episodic store, weighted retrieval, outcome attribution, and asynchronous consolidation into semantic tiers
- **Action Space**: Persistent agent tasks with tool calls and evolving external memory
- **Memory**: Tiered episodic/semantic stores, retrieval weighting, attribution-based weight updates, and consolidation
- **Key Results**: Reports large retrieval gains over no-retrieval baselines and diagnoses when raw BM25 dominance blocks weight learning
- **Scores**: R=5, N=4, R=4, E=4
- **Value to Project**: Supports outcome-attributed skill-memory feedback and runtime gates before retrieval weights affect Minecraft planning
- **Reproduction Priority**: P2
- **Card**: `2026-07-09-memtier.md`

---

## P-059: SkillMaster

- **Title**: SkillMaster: Toward Autonomous Skill Mastery in LLM Agents
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2605.08693
- **Type**: Autonomous skill-bank creation, refinement, selection, and training framework
- **Task Type**: Long-horizon agent tasks with trajectory-informed skill review and related-task probes
- **Core Method**: Trains agents to create, update, retain, and select skills, crediting edits by counterfactual utility on probe tasks
- **Action Space**: LLM-agent tool actions plus explicit skill-management actions
- **Memory**: Skill bank maintenance, procedural memory edits, trajectory evidence, and future-task utility attribution
- **Key Results**: Reports higher success than standard RL and externally managed skill-library baselines, with gains from both utility reward and decoupled optimization
- **Scores**: R=4, N=5, R=4, E=4
- **Value to Project**: Supports using controlled Minecraft task streams as counterfactual utility probes before approved skills or transfer memories become runtime defaults
- **Reproduction Priority**: P2
- **Card**: `2026-07-09-skillmaster.md`

---

## P-060: Solaris

- **Title**: Solaris: Building a Multiplayer Video World Model in Minecraft
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2602.22208
- **Type**: Multiplayer Minecraft data engine / video world model
- **Task Type**: Cooperative multiplayer Minecraft episodes with aligned controller actions and visual observations
- **Core Method**: Docker-orchestrated server, camera bots, controller bots, Mineflayer primitives, and communication layers collect scalable multiplayer visual gameplay traces
- **Action Space**: Mineflayer-style programmable primitives plus visually captured multiplayer state
- **Memory**: Episode traces, reusable skill primitives, role interaction state, and visual-action sequence data for future world-model learning
- **Key Results**: Demonstrates a controllable multiplayer visual Minecraft data engine and positions rich cooperative traces as a foundation for world-model and VLA training
- **Scores**: R=4, N=5, R=3, E=4
- **Value to Project**: Supports Singularity's M7 role-bridge, screenshot, and shared-state trace roadmap, and motivates verifying that action success returns correspond to observed state deltas before using traces for training or promotion
- **Reproduction Priority**: P2
- **Card**: `2026-07-09-solaris.md`

---

## P-061: From Plan to Action

- **Title**: From Plan to Action: How Well Do Agents Follow the Plan?
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2604.12147
- **Type**: Agent plan-compliance evaluation
- **Task Type**: Long-horizon agent trajectories with explicit plan-following expectations
- **Core Method**: Measures plan phase compliance, plan order compliance, and phase fidelity to distinguish successful task completion from genuine plan following
- **Action Space**: Generic agent actions; adapted here to Minecraft JSONL `plan` and `action` windows
- **Memory**: Trajectory-level evidence of missing plan steps, order drift, and unplanned actions that can feed planner reminders or repair policies
- **Key Results**: Shows that plan quality and reminders affect agent outcomes, while bad or misaligned plans can degrade performance
- **Scores**: R=5, N=4, R=4, E=5
- **Value to Project**: Motivates `plan-action-compliance-report`, which audits whether Singularity executes planned Minecraft actions before trusting benchmark completion, self-evolution feedback, or skill promotion traces
- **Reproduction Priority**: P1
- **Card**: `2026-07-09-plan-to-action.md`

---

## P-062: VIGIL Terminal Commitment

- **Title**: Done, But Not Sure: Disentangling World Completion from Self-Termination in Embodied Agents
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2605.08747
- **Type**: Embodied-agent terminal commitment evaluation
- **Task Type**: Embodied episodes with separate world-state completion and terminal self-report scoring
- **Core Method**: Separates world completion from benchmark success so missed execution, post-attainment drift, unsupported commitment, and verified success are visible
- **Action Space**: Embodied action trajectories with final semantic terminal reports; adapted here to Minecraft `goal_end` and verifier evidence
- **Memory**: Terminal evidence traces that can feed completion-policy reminders, verifier gates, and self-evolution feedback
- **Key Results**: Shows models with similar world completion can differ substantially in benchmark success because terminal commitment failures persist after execution improvements
- **Scores**: R=5, N=5, R=4, E=5
- **Value to Project**: Motivates `terminal-commitment-report`, which prevents Singularity from conflating missed execution, unsupported completion claims, and post-attainment drift in Minecraft session logs
- **Reproduction Priority**: P1
- **Card**: `2026-07-09-vigil-terminal-commitment.md`

---

## P-063: VeGAS Action Verification

- **Title**: Think Twice, Act Once: Verifier-Guided Action Selection For Embodied Agents
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2605.12620
- **Type**: Embodied-agent verifier-guided action selection
- **Task Type**: Long-horizon embodied action selection with candidate verification
- **Core Method**: Samples candidate actions at test time and uses a trained verifier to select the most reliable action without changing the base policy
- **Action Space**: High-level embodied actions; adapted here to structured Minecraft action dictionaries
- **Memory**: Failure-case and verifier-decision traces that can train or calibrate action-selection policies
- **Key Results**: Reports improved generalization over CoT baselines on Habitat and ALFRED, especially for challenging multi-object long-horizon tasks
- **Scores**: R=5, N=5, R=4, E=5
- **Value to Project**: Motivates `ActionVerifier`, `ActionCandidateSelector`, `action-verification-report`, and `action-candidate-report`, which block infeasible Minecraft actions, repair rejected actions with feasible prerequisites, and expose verifier gaps for later learned ranking
- **Reproduction Priority**: P1
- **Card**: `2026-07-09-vegas-action-verification.md`

---

## P-064: SVA Action Evaluation

- **Title**: Look Before You Leap: Distilling Tree Search into Action Evaluation for Frozen VLA Models
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2607.03751
- **Type**: Test-time action evaluation for frozen VLA policies
- **Task Type**: Embodied candidate-action selection under frozen policy generalization limits
- **Core Method**: Distills MCTS return labels into a lightweight Q-value evaluator, then selects among multiple generated actions at deployment
- **Action Space**: VLA low-level/action-token candidates; adapted here as future Minecraft candidate-action scoring
- **Memory**: Return-labeled trajectories and evaluator decisions that can feed a reusable action-value model
- **Key Results**: Shows pass@k exposes latent good actions and that a smaller VLA plus evaluator can outperform a larger VLA with lower latency
- **Scores**: R=4, N=5, R=3, E=5
- **Value to Project**: Motivates `ActionValueProfile` plus `action-value-report`, giving conservative candidate scoring a reusable outcome-value memory before broader pass@k-style Minecraft action ranking
- **Reproduction Priority**: P1
- **Card**: `2026-07-09-sva-action-evaluation.md`

---

## P-065: Agent Step Value

- **Title**: Agent Step Value: State-Transition Measurement with State-Grounded LLM Evaluators
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2607.04419
- **Type**: Agent trace state-transition evaluation
- **Task Type**: Per-step credit assignment for black-box agent trajectories
- **Core Method**: Compares evaluator beliefs over candidate outcomes before and after an action to score the state transition induced by that action
- **Action Space**: Generic agent actions; adapted here to Minecraft session-log actions and bounded before/after observations
- **Memory**: Step-value traces that can feed action-value memory, repair candidate ranking, and future state-delta skill promotion
- **Key Results**: Argues final-answer scores hide helpful and harmful intermediate transitions, and introduces ASV as a replayable measurement framework
- **Scores**: R=5, N=5, R=4, E=5
- **Value to Project**: Motivates `state_transition_value_items`, `action-value-transition-gate`, and `action-value-transition-evaluator-report`, extending result success rates with bounded Minecraft before/after labels plus state-grounded evaluator comparison
- **Reproduction Priority**: P1
- **Card**: `2026-07-09-agent-step-value.md`

---

## P-066: Coachable Agents

- **Title**: Coachable agents for interactive gameplay
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2607.00642
- **Type**: Runtime style control for game and embodied agents
- **Task Type**: Interactive gameplay with user-selectable execution style
- **Core Method**: Style-conditioned policies using UVFA-style conditioning, training scenarios, algorithms, and augmentation
- **Action Space**: Game and humanoid control policies; adapted here as planner and curriculum preferences
- **Memory**: Style preference state and outcome traces can feed later runtime policy audits
- **Key Results**: Demonstrates coherent runtime style requests while maintaining the main task in multiple interactive domains
- **Scores**: R=4, N=5, R=3, E=5
- **Value to Project**: Motivates `CoachPolicy`, which lets Singularity bias planner context and autonomous curriculum style without bypassing verifier, safety, task, or memory gates
- **Reproduction Priority**: P2
- **Card**: `2026-07-09-coachable-agents.md`

---

## P-067: LLM-in-Sandbox

- **Title**: LLM-in-Sandbox Elicits General Agentic Intelligence
- **Year**: 2026
- **Link**: https://arxiv.org/abs/2601.16206
- **Type**: General agentic intelligence via minimal computer sandbox
- **Task Type**: Broad non-code and code tasks with externalized file/script workflows
- **Core Method**: Provides an LLM with file management, script execution, and resource access so it can externalize reasoning, store intermediate artifacts, and verify work
- **Action Space**: Computer sandbox operations; adapted here as offline replay reports and gated promotion artifacts
- **Memory**: Files, scripts, and generated artifacts act as inspectable external memory for long-horizon work
- **Key Results**: Reports that sandbox access elicits broader agentic capabilities than prompt-only interaction in multiple task categories
- **Scores**: R=4, N=5, R=3, E=5
- **Value to Project**: Motivates making Minecraft policy updates pass through explicit offline report files, replay scripts, and gates before runtime mutation or live-server spending
- **Reproduction Priority**: P2
- **Card**: `2026-07-09-llm-in-sandbox.md`

---

### P-068: Managing Procedural Memory in LLM Agents

- **Source**: https://arxiv.org/abs/2606.23127
- **Year**: 2026
- **Type**: Procedural-memory transfer benchmark and management study
- **Task Type**: Recurring role-scoped agent workflows with local, cross-task, cross-role, and cross-model transfer probes
- **Core Method**: AFTER benchmark separates local skill refinement from broader procedural-memory transfer and specialization
- **Memory**: Procedural skills are evaluated as deployable memories with transfer scope, refinement evidence, and specialization risk
- **Key Results**: Reports consistent gains from procedural memory refinement and shows some skills transfer broadly while others become role-specialized
- **Scores**: R=5, N=5, R=4, E=5
- **Value to Project**: Supports task-family-scoped runtime-default gates for Minecraft skills before they are allowed to influence planning by default
- **Reproduction Priority**: P1
- **Card**: `2026-07-09-after-procedural-memory.md`

### P-069: Mem^p Procedural Memory

- **Source**: https://arxiv.org/abs/2508.06433
- **Year**: 2025
- **Type**: Procedural-memory construction, retrieval, and update framework
- **Task Type**: Long-horizon household and information-seeking agent tasks with reusable procedures
- **Core Method**: Distills trajectories into fine-grained procedural instructions and higher-level scripts, then updates them through validation, reflection, and discarding
- **Memory**: Lifelong procedural memory with build, retrieval, update, correction, and deletion operations
- **Key Results**: Reports improved task success and efficiency from refined procedural memories, including transfer from stronger to weaker model backbones
- **Scores**: R=4, N=5, R=4, E=4
- **Value to Project**: Supports typed Minecraft skill memories, quality gates, and review-only defaults until localized outcome evidence proves reuse value
- **Reproduction Priority**: P2
- **Card**: `2026-07-09-memp-procedural-memory.md`

### P-070: XENON Knowledge Correction

- **Title**: Experience-based Knowledge Correction for Robust Planning in LLM-based Agents
- **Source**: https://openreview.net/forum?id=N22lDHYrXe
- **Year**: 2026
- **Type**: Minecraft agent planning and experience-based knowledge correction
- **Task Type**: Robust long-horizon Minecraft planning under missing or wrong dependency/action knowledge
- **Core Method**: Splits experience-based correction into dependency-graph updates and failed-action memories
- **Memory**: Failure traces plus successful recovery actions become reviewable correction candidates
- **Key Results**: Positions correction as trace-grounded planning knowledge rather than unstructured reflection
- **Scores**: R=5, N=5, R=4, E=5
- **Value to Project**: Supports `knowledge-correction-report` and `knowledge-correction-gate` before planner knowledge is updated from live failures
- **Reproduction Priority**: P1
- **Card**: `2026-07-09-xenon-knowledge-correction.md`

---

## P-071: When Claws Remember: Stealthy and Persistent Memory Injections in OpenClaw Agents

- **Title**: When Claws Remember: Stealthy and Persistent Memory Injections in OpenClaw Agents
- **Source**: https://arxiv.org/abs/2607.05189
- **Year**: 2026
- **Type**: Agent memory security / persistent attack paper
- **Task Type**: Persistent memory, tool use, autonomous agents
- **Core Method**: Demonstrates stealthy indirect memory injection attacks that persist across sessions in OpenClaw-style agents
- **Memory**: Shows durable memory as an attack surface when user-controlled content can be saved and recalled later
- **Key Results**: Positions persistent memory injection as a long-lived risk for agents with memory, tool use, and closed-loop autonomy
- **Scores**: R=5, N=5, R=3, E=5
- **Value to Project**: Reinforces promptware scanning, gate-reviewed feedback artifacts, and runtime-profile packaging that avoids raw memory/prompts/secrets
- **Reproduction Priority**: P1
- **Card**: `2026-07-09-openclaw-memory-injection.md`

---

## P-072: Parallelized Planning-Acting for Efficient LLM-based Multi-Agent Systems in Minecraft

- **Title**: Parallelized Planning-Acting for Efficient LLM-based Multi-Agent Systems in Minecraft
- **Source**: https://arxiv.org/abs/2503.03505
- **Year**: 2025; revised 2026
- **Type**: Minecraft multi-agent execution architecture
- **Task Type**: Real-time collaborative Minecraft tasks with high-latency LLM planning
- **Core Method**: Separates planning and acting into parallel threads so execution can continue while fresher plans are prepared and interrupt unfinished action suffixes
- **Memory**: Uses shared memory and communication state as the coordination substrate between planning and acting
- **Key Results**: Targets better real-time efficiency for Minecraft multi-agent systems under dynamic world changes
- **Scores**: R=5, N=4, R=3, E=5
- **Value to Project**: Supports an M7 plan/act latency report and a future gated interruptible execution mode for role agents
- **Reproduction Priority**: P2
- **Card**: `2026-07-09-parallelized-planning-acting.md`

---

## P-073: AgenticCache: Cache-Driven Asynchronous Planning for Embodied AI Agents

- **Title**: AgenticCache: Cache-Driven Asynchronous Planning for Embodied AI Agents
- **Source**: https://arxiv.org/abs/2604.24039
- **Year**: 2026
- **Type**: Embodied planning cache / latency architecture
- **Task Type**: Long-horizon embodied planning with repeated local plan transitions
- **Core Method**: Runtime cache of frequent plan transitions plus asynchronous LLM updater and optional offline prefilling
- **Memory**: Treats plan transitions as reusable short-horizon procedural memory
- **Key Results**: Reports higher task success plus lower latency and token usage across embodied benchmarks
- **Scores**: R=4, N=5, R=4, E=5
- **Value to Project**: Directly motivates default-off `plan-cache-report` artifacts, runtime cache hits before LLM planning, and runtime-profile security scanning of cache artifacts
- **Reproduction Priority**: P1
- **Card**: `2026-07-09-agenticcache.md`

---

## P-074: Orak: A Foundational Benchmark for Training and Evaluating LLM Agents on Diverse Video Games

- **Title**: Orak: A Foundational Benchmark for Training and Evaluating LLM Agents on Diverse Video Games
- **Source**: https://arxiv.org/abs/2506.03610
- **Year**: 2025; active versions in 2026
- **Type**: Multi-game LLM-agent benchmark and training dataset
- **Task Type**: General game agents across genres; module evaluation and fine-tuning trajectories
- **Core Method**: 12-game benchmark with MCP-style plug-and-play interface, score leaderboards, battle arenas, visual-input studies, strategy analyses, and gameplay trajectories
- **Memory**: Provides an evaluation lens for memory, perception, planning, and agentic module choices rather than a single memory architecture
- **Key Results**: Establishes a systematic benchmark for training and evaluating generic gaming agents across diverse real-world games
- **Scores**: R=4, N=4, R=4, E=5
- **Value to Project**: Motivates suite-level module comparison reports and gate-backed runtime-profile packaging for plan cache, action values, visual grounding, skill memory, and mixed-policy patches
- **Reproduction Priority**: P2
- **Card**: `2026-07-09-orak.md`

---

## P-075: CausalGame: Benchmarking Causal Thinking of LLM Agents in Games

- **Title**: CausalGame: Benchmarking Causal Thinking of LLM Agents in Games
- **Source**: https://arxiv.org/abs/2607.04293
- **Year**: 2026
- **Type**: Interactive game benchmark for causal thinking in LLM agents
- **Task Type**: Experimental design, observation collection, causal explanation, and failure-mode analysis in games
- **Core Method**: Agents actively design protocols, collect observations, and produce explanation reports under selection-bias, measurement-error, and hidden-confounder challenges
- **Memory**: Emphasizes that repeated observations should not become durable memories or skills without causal evidence and counterexample checks
- **Key Results**: Frames games as causal-discovery environments where plausible post-hoc explanations can diverge from grounded causal reasoning
- **Scores**: R=5, N=5, R=4, E=5
- **Value to Project**: Motivates contrastive causal-evidence audits over Minecraft session logs before promoting causal summaries, discovery skills, or knowledge corrections
- **Reproduction Priority**: P1
- **Card**: `2026-07-09-causalgame.md`

---

## P-076: WorldLines

- **Title**: WorldLines: Benchmarking and Modeling Long-Horizon Stateful Embodied Agents
- **Source**: https://arxiv.org/abs/2606.18847
- **Year**: 2026
- **Type**: Long-horizon embodied memory benchmark and observer-grounded memory framework
- **Task Type**: Temporally extended embodied projects with actions, feedback, partial observability, and mutable world state
- **Core Method**: Evidence-linked traces plus ObsMem visibility-aware memories and action-native state trails
- **Memory**: Preserves observation scope, state revisions, and action provenance rather than flat textual recall
- **Key Results**: Reports persistent difficulty with partial observability, overwritten states, and translating long-term memory into embodied plans
- **Scores**: R=5, N=5, R=4, E=5
- **Value to Project**: Motivates visibility-aware M3/M5 live acceptance and state-grounded memory claims
- **Reproduction Priority**: P1
- **Card**: `2026-07-10-worldlines.md`

---

## P-077: Agent Memory System Characterization

- **Title**: Agent Memory: Characterization and System Implications of Stateful Long-Horizon Workloads
- **Source**: https://arxiv.org/abs/2606.06448
- **Year**: 2026
- **Type**: Systems characterization of stateful long-horizon agent memory
- **Task Type**: Construction, retrieval, and generation profiling across memory systems and long-horizon benchmarks
- **Core Method**: Phase-aware profiling of cost, latency, freshness, and maintenance behavior
- **Memory**: Treats memory as a systems workload whose costs move between write, read, and generation paths
- **Key Results**: Derives deployment recommendations around scheduling, capability floors, amortization, freshness, and fleet-scale management
- **Scores**: R=5, N=5, R=4, E=5
- **Value to Project**: Motivates cost/freshness evidence in M3 acceptance instead of recall quality alone
- **Reproduction Priority**: P1
- **Card**: `2026-07-10-agent-memory-characterization.md`

---

## P-078: SelfMem

- **Title**: SelfMem: Self-Optimizing Memory for AI Agents
- **Source**: https://arxiv.org/abs/2607.03726
- **Year**: 2026
- **Type**: Self-optimizing agent-memory framework
- **Task Type**: Long-context memory strategy search and refinement with feedback
- **Core Method**: Lets an agent use memory tools and evaluation feedback to refine its own memory strategy
- **Memory**: Treats storage, retrieval, and summarization policy as an optimizable strategy rather than a fixed pipeline
- **Key Results**: Reports 48.7%, 40.8%, and 41.9% gains over the strongest baseline at 100K, 500K, and 1M-token BEAM settings
- **Scores**: R=4, N=5, R=4, E=4
- **Value to Project**: Motivates gated offline optimization of typed Minecraft memory budgets and retrieval mixes
- **Reproduction Priority**: P2
- **Card**: `2026-07-10-selfmem.md`

---

## P-079: MAGE Execution-State Memory

- **Title**: Beyond Semantic Organization: Memory as Execution State Management for Long-Horizon Agents
- **Source**: https://arxiv.org/abs/2606.06090
- **Year**: 2026
- **Type**: Hierarchical execution-state memory for long-horizon agents
- **Task Type**: Interdependent decisions, checkpoint maintenance, error isolation, and branch revision
- **Core Method**: Grow/Compress/Maintain/Revise operations over an active root-to-current state tree
- **Memory**: Separates the active execution path from failed historical branches while retaining revision hints
- **Key Results**: Reports 7.8--20.4 percentage-point success gains and 55.1% lower token use on MemoryArena
- **Scores**: R=5, N=5, R=4, E=5
- **Value to Project**: Direct blueprint for branching task continuity and checkpoint-based failure recovery
- **Reproduction Priority**: P1
- **Card**: `2026-07-10-mage-execution-state.md`

---

## P-080: MemGym

- **Title**: MemGym: a Long-Horizon Memory Environment for LLM Agents
- **Source**: https://arxiv.org/abs/2605.20833
- **Year**: 2026
- **Type**: Long-horizon agent-memory evaluation environment
- **Task Type**: Tool-use dialogue, deep research, coding, and computer-use memory evaluation
- **Core Method**: Memory-isolated scoring behind a shared memory-reasoning interface, with controlled synthetic pipelines and compression-quality evaluation
- **Memory**: Separates memory formation and compression value from reasoning, retrieval, and tool-use confounders
- **Key Results**: Provides five evaluation tracks across four agentic regimes plus a lightweight compression reward model for expensive coding rollouts
- **Scores**: R=4, N=5, R=4, E=4
- **Value to Project**: Defines the ablation discipline for testing execution-state lineage without crediting planner or action-backend changes to memory
- **Reproduction Priority**: P2
- **Card**: `2026-07-10-memgym.md`

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
| P-030 | AutoMem | 2026 | R5/N5/R4/E4 | P2 |
| P-031 | Memory for Autonomous LLM Agents | 2026 | R5/N4/R4/E5 | P1 |
| P-032 | Agentic Memory | 2026 | R5/N5/R3/E4 | P2 |
| P-033 | GovMem | 2026 | R5/N5/R3/E5 | P2 |
| P-034 | STALE | 2026 | R5/N5/R4/E5 | P2 |
| P-035 | MemConflict | 2026 | R5/N5/R4/E5 | P2 |
| P-036 | ActMem | 2026 | R4/N5/R3/E5 | P2 |
| P-037 | MineNPC-Task | 2026 | R5/N4/R4/E5 | P2 |
| P-038 | NitroGen | 2026 | R3/N5/R4/E4 | P3 |
| P-039 | GameWorld | 2026 | R4/N5/R4/E5 | P2 |
| P-040 | OmniGameArena | 2026 | R3/N5/R3/E4 | P3 |
| P-041 | SciCrafter | 2026 | R5/N5/R3/E5 | P2 |
| P-042 | WhisperBench / MemGhost | 2026 | R5/N5/R3/E5 | P1 |
| P-043 | SkillDAG | 2026 | R4/N5/R4/E5 | P2 |
| P-044 | MineEvolve | 2026 | R5/N5/R3/E5 | P1 |
| P-045 | VLM-AR3L | 2026 | R4/N4/R3/E4 | P2 |
| P-046 | EmbodiSkill | 2026 | R4/N5/R3/E5 | P2 |
| P-047 | VASO | 2026 | R3/N5/R3/E5 | P2 |
| P-048 | MemoryArena | 2026 | R5/N4/R3/E5 | P2 |
| P-049 | AGI Maze | 2026 | R4/N5/R3/E5 | P2 |
| P-050 | COS-PLAY | 2026 | R5/N5/R4/E5 | P1 |
| P-051 | AgenticSTS | 2026 | R5/N5/R4/E5 | P1 |
| P-052 | AgentOdyssey | 2026 | R4/N5/R4/E5 | P2 |
| P-053 | AgentCL | 2026 | R4/N5/R4/E5 | P2 |
| P-054 | MUSE-Autoskill | 2026 | R4/N5/R4/E5 | P2 |
| P-055 | RIZZ | 2026 | R4/N5/R4/E5 | P2 |
| P-056 | Memory Management and Experience-Following | 2026 | R5/N4/R4/E5 | P1 |
| P-057 | Agent-Native Memory System | 2026 | R5/N4/R4/E5 | P1 |
| P-058 | MemTier | 2026 | R5/N4/R4/E4 | P2 |
| P-059 | SkillMaster | 2026 | R4/N5/R4/E4 | P2 |
| P-060 | Solaris | 2026 | R4/N5/R3/E4 | P2 |
| P-061 | From Plan to Action | 2026 | R5/N4/R4/E5 | P1 |
| P-062 | VIGIL Terminal Commitment | 2026 | R5/N5/R4/E5 | P1 |
| P-063 | VeGAS Action Verification | 2026 | R5/N5/R4/E5 | P1 |
| P-064 | SVA Action Evaluation | 2026 | R4/N5/R3/E5 | P1 |
| P-065 | Agent Step Value | 2026 | R5/N5/R4/E5 | P1 |
| P-066 | Coachable Agents | 2026 | R4/N5/R3/E5 | P2 |
| P-067 | LLM-in-Sandbox | 2026 | R4/N5/R3/E5 | P2 |
| P-068 | AFTER Procedural Memory | 2026 | R5/N5/R4/E5 | P1 |
| P-069 | Mem^p Procedural Memory | 2025 | R4/N5/R4/E4 | P2 |
| P-070 | XENON Knowledge Correction | 2026 | R5/N5/R4/E5 | P1 |
| P-071 | OpenClaw Memory Injection | 2026 | R5/N5/R3/E5 | P1 |
| P-072 | Parallelized Planning-Acting | 2025/2026 | R5/N4/R3/E5 | P2 |
| P-073 | AgenticCache | 2026 | R4/N5/R4/E5 | P1 |
| P-074 | Orak | 2025/2026 | R4/N4/R4/E5 | P2 |
| P-075 | CausalGame | 2026 | R5/N5/R4/E5 | P1 |
| P-076 | WorldLines | 2026 | R5/N5/R4/E5 | P1 |
| P-077 | Agent Memory System Characterization | 2026 | R5/N5/R4/E5 | P1 |
| P-078 | SelfMem | 2026 | R4/N5/R4/E4 | P2 |
| P-079 | MAGE Execution-State Memory | 2026 | R5/N5/R4/E5 | P1 |
| P-080 | MemGym | 2026 | R4/N5/R4/E4 | P2 |
