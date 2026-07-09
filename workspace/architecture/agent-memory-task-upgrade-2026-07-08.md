# Agent Memory and Task System Upgrade Notes - 2026-07-08

## Purpose

Continue Singularity toward a complete Minecraft agent by borrowing durable ideas from current general agent systems and recent Minecraft/game-agent research. This note is intentionally implementation-facing: every idea below maps to a module we can build or benchmark.

## External Agent Systems Reviewed

### Hermes Agent

Sources:
- https://github.com/NousResearch/hermes-agent
- https://hermes-agent.nousresearch.com/docs/user-guide/features/memory/
- https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/skills.md

Borrowable ideas:
- Bounded curated memory: small, explicit, capacity-limited memories beat unbounded notes for prompt focus.
- Frozen session snapshot: memory is loaded at session start while writes land for the next session, preserving prompt-cache stability.
- Memory write primitives: add, replace, remove are enough if entries are short and auditable.
- Skills as procedural memory: long procedures should not live in always-on memory; load them by relevance.
- Agent-managed skill evolution should be gated or staged for review when safety matters.

Singularity adaptation:
- Add `MemoryEntry` with layer, type, tags, importance, confidence, and source.
- Keep short memories in `MemorySystem.curate_entries()` with a character budget.
- Keep long procedures in `SkillLibrary`, and only retrieve them when a goal/task matches.

### OpenClaw

Sources:
- https://github.com/openclaw/openclaw
- https://openclaw.ai/
- https://mem0.ai/blog/openclaw-vs-hermes-agent-memory-comparison

Borrowable ideas:
- Always-on gateway process that separates user channels from agent execution.
- Workspace-oriented setup with channels, skills, and local runtime configuration.
- Pairing/allowlist defaults for untrusted inbound messages.
- Memory "dreaming" gates should require usefulness, repeated recall, and query diversity before treating a note as durable knowledge.

Singularity adaptation:
- Treat Mineflayer bridge as a gateway service, not as part of the planner.
- Add an operator-facing runtime profile later: Minecraft server, bot bridge, model provider, benchmark suite.
- Keep external inputs and model outputs behind typed action controllers and session logs.
- Track recall counts and distinct query signatures for durable memory entries and experience records, then expose a `memory-consolidation-report` for reviewable consolidation candidates.

## Latest Game and Minecraft Agent Research

### Echo: Experience Transfer for Multimodal LLM Agents in Minecraft Game

Source: https://arxiv.org/abs/2604.05533

Core idea:
- Memory should transfer actionable knowledge, not merely retrieve old logs.
- Reusable experience is decomposed into structure, attribute, process, function, and interaction dimensions.
- In-context analogy learning adapts prior experience to new tasks.

Singularity adaptation:
- Add `ExperienceRecord.dimensions` with the five transfer dimensions.
- Retrieval should rank experiences by goal, inventory, nearby context, and dimension overlap.

### PEAM: Parametric Embodied Agent Memory

Source: https://arxiv.org/abs/2605.27762

Core idea:
- Some experiences should become fast reflexes instead of retrieval-time text memories.
- Failure-correction pairs are first-class learning signals.
- Consolidation should be controlled by a parameterization-worthiness score.

Singularity adaptation:
- In the near term, compute a `consolidation_score` for session traces.
- Promote high-score traces from episode logs to skill candidates.
- Store failed action plus corrected action together for future contrastive prompts.
- Use `action-value-report` as the lightweight non-parametric staging layer before any LoRA/MoE internalization: it aggregates action signatures, outcome values, and failed-action -> recovery-action pairs.

### XENON: Experience-based Knowledge Correction for Robust Planning

Source: https://openreview.net/forum?id=N22lDHYrXe

Core idea:
- Robust Minecraft planning needs explicit correction for wrong or missing dependency/action knowledge.
- Failed-action memory and dependency-graph correction should be separated.
- Corrections should come from grounded experience, not unreviewed self-edits.

Singularity adaptation:
- Mine failed-action -> successful-recovery pairs from session logs.
- Keep correction candidates as reviewable JSON artifacts before planner/runtime use.
- Preserve Echo-style transfer dimensions so corrected knowledge can be retrieved by structure, process, function, and interaction.

### WISE: Why-Which Reasoning for Long-Horizon Minecraft Agents

Source: https://arxiv.org/abs/2606.12852

Core idea:
- What/where/when episodic memory is not enough; the agent also needs which/why causal links.
- Opportunistic task scheduling can reorder subtasks when the world exposes a useful chance.

Singularity adaptation:
- Add `ExperienceRecord.causal` with `which` and `why`.
- Add task `opportunity_triggers` so the scheduler can prefer tasks that match nearby blocks, entities, or inventory.

### Parallelized Planning-Acting for Minecraft MAS

Source: https://arxiv.org/abs/2503.03505

Core idea:
- Serial plan-then-act loops are too slow for dynamic Minecraft.
- A planning thread can update global memory while an acting thread executes interruptible skills.

Singularity adaptation:
- Keep M1 simple, then split `Agent.run_goal()` into planner loop and actor loop.
- Every action must remain interruptible and logged.

### TickingCollabBench / Time-Sensitive Collaboration

Source: https://arxiv.org/abs/2606.15684

Core idea:
- Useful collaboration benchmarks require heterogeneity, mandatory cooperation, dynamic environments, and time limits.
- Declarative task specs make benchmark generation easier.

Singularity adaptation:
- Encode M7 tasks as structured YAML/JSON benchmark specs with agent roles, deadlines, and feasibility checks.

### VistaWise

Source: https://arxiv.org/abs/2508.18722

Core idea:
- Cross-modal knowledge graphs can reduce data needs by combining visual observations and textual dependencies.

Singularity adaptation:
- Build a lightweight knowledge graph over items, recipes, tools, blocks, biomes, and observed landmarks before attempting heavyweight VLA training.

### Optimus-2, JARVIS-VLA, Game-TARS, NitroGen, OpenHA / CrossAgent

Sources:
- https://arxiv.org/abs/2502.19902
- https://arxiv.org/abs/2503.16365
- https://arxiv.org/abs/2510.23691
- https://arxiv.org/abs/2601.02427
- https://arxiv.org/abs/2509.13347
- https://arxiv.org/abs/2512.09706

Core idea:
- Strong game agents increasingly combine high-level language planning with low-level behavior/action policies.
- Unified keyboard-mouse or goal-observation-action representations generalize better than narrow APIs, but are expensive to train.
- NitroGen suggests that scalable visual-action priors can transfer across many games, but Singularity should collect narrow Minecraft screenshot/action traces first and only train/apply low-level policies where API-level control demonstrably fails.
- OpenHA/CrossAgent adds that action abstraction itself should be task-dependent: abstract actions can be intermediate reasoning steps, while some steps need lower-level visual/keyboard-mouse control.

Singularity adaptation:
- Keep Mineflayer API control for reproducible M1-M5 progress.
- Add optional screenshot/VLM diagnostics in M6 before considering keyboard-mouse policy learning.
- Record canonical-to-backend action traces so future reports can compare API-level and low-level control needs by task.
- Use `action-abstraction-report` plus `mixed-initiative-trace-report` to rank task families for future visual-action data collection.

### LLM-Based Game Agent Survey v5

Source: https://arxiv.org/html/2404.02039v5

Core idea:
- A useful reference architecture groups game agents around memory, reasoning, and perception-action interfaces, plus multi-agent communication and organization.
- Sandbox worlds especially need open-ended goal formation.

Singularity adaptation:
- Keep the module map explicit: Observation -> Memory -> GoalGenerator/Planner -> TaskSystem -> SkillLibrary -> ActionController -> Evaluator.

### MineExplorer: Evaluating Open-World Exploration of MLLM Agents in Minecraft

Source: https://arxiv.org/abs/2605.30931

Core idea:
- Open-world ability should not be measured only by short-horizon item unlocks.
- Exploration benchmarks should separate perception, reasoning, and action failure modes.
- Evaluation should reduce over-crediting memorized Minecraft priors.

Singularity adaptation:
- Add an exploration trace report over autonomous session logs: visited position spread, new block/entity/resource types, visual evidence coverage, hazards encountered, multi-step plans, and failed action categories.
- Feed exploration coverage back into curriculum novelty scoring once live autonomous traces are available.

### MineNPC-Task: Task Suite for Memory-Aware Minecraft Agents

Source: https://arxiv.org/abs/2601.05215

Core idea:
- Natural player requests should be evaluated as mixed-initiative tasks with explicit slots, dependencies, plan previews, bounded public-API perception/action, and machine-checkable validators.
- Missing slots should trigger a single targeted clarification, and answers should become scoped memory with provenance rather than unbounded global facts.
- Valid completion evidence should come from in-world signals such as inventory/equipment deltas, position changes, loaded-chunk blocks/entities, and recent chat; privileged commands or global map introspection should invalidate runs.

Singularity adaptation:
- Add a lightweight template compiler for user-authored Minecraft requests.
- Add bounded-evidence validators that complement `GoalVerifier`: template validators can judge subtask-level outcomes, while goal verification gates final planner completion.
- Treat clarification answers as scoped preference memory candidates so repeated user corrections improve future slot binding without polluting global memory.

### AutoMem, Agentic Memory, GovMem, STALE, MemConflict, and ActMem

Sources:
- https://arxiv.org/abs/2607.01224
- https://arxiv.org/abs/2601.01885
- https://arxiv.org/abs/2607.02579
- https://arxiv.org/abs/2605.06527
- https://arxiv.org/abs/2605.20926
- https://arxiv.org/abs/2603.00026

Core idea:
- Memory management should be an explicit trainable or feedback-driven skill, not an invisible side effect of planning.
- Memory policies need separate write, read, manage, summarize, update, and discard decisions.
- Repeated traces are not always independent evidence; shared prompts, copied sources, stale context, or narrow scope can create false memory promotion.
- Mutable state memory needs supersession semantics, because later observations can implicitly invalidate old assumptions without explicit negation.
- Retrieval needs query-conditioned fitness-for-use: temporally valid, factually correct, and contextually applicable memories should outrank or replace stale alternatives.
- Actionable memory should connect retrieval to causal reasoning and downstream decisions, not just prompt stuffing.

Singularity adaptation:
- Keep `memory_write`, `memory_read`, and `memory_manage` events visible in session logs.
- Use `memory-policy-report` to convert trace gaps into `memory_policy_feedback`.
- Let `MemoryLifecyclePolicy` consume feedback hints and tag candidate writes with reviewable decisions.
- Add GovMem-style provenance flags (`correlated_evidence`, `unsafe_scope`) before candidate facts can become durable semantic memory.
- Add STALE-style `state_revision` and `implicit_conflict` flags when new evidence supersedes a prior shared state.
- Filter read-time durable memories whose metadata says they are stale, superseded, invalidated, contradicted, or conditionally inapplicable to the current observation.
- Log and report read-time filters so retrieval quality can be audited against later task outcomes and benchmark summaries.

## Proposed Singularity Delta Architecture

1. Experience atoms

Each successful or corrected trace becomes a compact atom:
- goal, task, outcome
- actions and key observations
- transfer dimensions: structure, attribute, process, function, interaction
- causal fields: which decision mattered, why it mattered
- metrics: duration, attempts, success_delta, risk

2. Causal opportunity scheduler

Tasks should no longer be selected by priority alone. The scheduler should consider:
- dependency completion
- inventory and block/entity preconditions
- deadline urgency
- opportunity triggers from nearby blocks/entities or current inventory
- failed-attempt penalty

3. Skill promotion pipeline

Session log -> experience atom -> consolidation score -> skill candidate -> gated skill write.

Promotion score should reward:
- repeated success
- high time savings
- low risk
- reusable preconditions
- clear correction after failure

4. Dual-loop runtime

Short term:
- keep one loop, but make tasks interruptible and memories transferable.

Medium term:
- split into planner and actor loops.
- planner updates goals/tasks/memory.
- actor executes current skill/action and yields to interrupts.

5. Research benchmark gates

New architecture claims need benchmark proof:
- M1: BM-001 to BM-005 basic survival actions.
- M2: multi-step crafting and replanning.
- M3: skill extraction and reuse improves second-run time.
- M4: survival loop improves first-night survival.
- M5: exploration returns to base under inventory/distance pressure.
- M7: time-sensitive complementary collaboration tasks.

6. Automatic curriculum

Open-ended autonomous play needs a curriculum layer above fixed survival rules:
- preserve emergency goals from the rule generator
- rank progression, crafting, resource, and exploration goals by readiness, novelty, skill gap, opportunity, and recent outcomes
- penalize repeated failures and repeated successes so the agent does not loop on stale goals
- record selected curriculum goals in episodic memory for later benchmark analysis

7. Goal self-verification

Planner-reported `complete` is not enough for an embodied agent:
- deterministic postconditions should verify common inventory, safety, shelter, and exploration goals directly from the latest observation
- verified success should be logged as evidence; known missing evidence should block false completion
- unknown goals should remain auditable and can later route to an LLM/VLM critic
- benchmark summaries should count achieved, failed, unknown, accepted, and rejected verification decisions
- verifier anchors should be mined from recipes, resource drops, and skill postconditions so coverage scales with structured game knowledge instead of hand-written aliases only
- before/after inventory deltas should be preserved as evidence, because post-action change is stronger than a static final inventory snapshot alone

8. Visual action grounding

Structured perception should affect the action interface before a full VLA policy exists:
- far-but-visible harvestable resources can produce an approach action before the harvest attempt
- visible harvestable resources can produce a focus/look action before a grounded `dig`
- visible, harvestable resources can provide exact action coordinates for underspecified `dig` actions
- nearby hostile entities can inject a conservative safety action before the current plan continues
- every visual intervention should be logged separately from planner reasoning so ablations can compare online policy changes against visual-context-only runs
- session and benchmark summaries should expose visual intervention counts and phases so live runs can prove when perception changed action, not just prompt context
- before live traces are plentiful, built-in disabled-versus-enabled ablation cases should lock in expected visual grounding behaviors and no-op safeguards
- as live traces arrive, session-log replay cases should reconstruct disabled baselines from logged visual interventions so offline evaluation stays tied to real behavior
- the visual review pipeline should summarize promotion, goal-verification, and action-grounding ablations together so one session trace can be audited end-to-end
- live benchmark suites should be able to flip visual action grounding independently from policy skills so perception-to-action gains can be measured as a controlled runtime ablation

9. Governed memory lifecycle

Memory should be treated as a policy-controlled subsystem:
- every write/read/manage operation receives an explicit decision
- offline reports should produce feedback hints for missed semantic writes, failure-learning traces, noisy writes, retrieval instrumentation, and consolidation review
- correlated or stale evidence should be routed to review before semantic promotion
- multi-agent shared-state writes should carry provenance, dependency, validity, scope, and confidence metadata so repeated role claims can be audited before becoming shared durable memory
- changes to an already-provenanced shared key should preserve the previous value/source and route the revision through state-adjudication review
- read-time retrieval should filter stale/superseded/invalidated/condition-mismatched durable entries before they can influence planner prompts
- strict write gates should remain off until real trace audits show high precision

10. Mixed-initiative task templates

User-authored Minecraft requests need a benchmark layer between free-form chat and raw live execution:
- compile requests into short plan previews with explicit dependencies and slot bindings
- ask at most one targeted clarification when a required slot is missing or a risky default should be confirmed
- persist clarification answers as scoped preferences with provenance
- validate each subtask against bounded in-world evidence, not planner self-report or privileged state
- invalidate traces that use admin commands, global map/seed introspection, or scans beyond the loaded observation envelope

## Implemented in this pass

- Fixed `KnowledgeBase` recipe loading path.
- Added `MemoryEntry` for bounded, curated durable memory.
- Added `ExperienceRecord` for Echo-style transferable experience and WISE-style causal fields.
- Added retrieval and curation methods to `MemorySystem`.
- Added Echo-style transfer-axis scoring to `MemorySystem.rank_transfer_experiences()`, so structure, attribute, process, function, and interaction matches can be surfaced in planner context and audited with `transfer-memory-report`.
- Added MemoryArena-style task-centric memory profiles. `MemorySystem.task_memory_profile()` and `task-memory-report` combine active task metadata, scoped memory matches, transfer-axis matches, and read-filter diagnostics, while `Agent._task_memory_context()` injects that evidence into LLM planning.
- Added task dependencies, preconditions, opportunity triggers, deadlines, and dynamic scoring to `TaskSystem`.
- Added unit coverage for knowledge loading, experience retrieval, and opportunity scheduling.
- Added first conservative visual action grounding from structured visual observations into executable actions.
- Added visual focus actions so the agent can look at grounded resources before digging them.
- Added visual action grounding metrics to session and benchmark summaries.
- Added offline visual action grounding ablation cases for resource approach, coordinate fill, target focus, danger retreat, and unrelated-resource no-op behavior.
- Added session-log replay support for visual action grounding ablations.
- Integrated visual action grounding ablations into the unified visual review pipeline report.
- Added live benchmark visual action grounding ablation reporting.
- Wired `Agent._think_llm()` through `Planner.plan_from_goal()` so relevant memory and curated context influence LLM planning while subtasks populate `TaskSystem`.
- Extended `Planner` to preserve LLM-provided dependency, precondition, skill, deadline, tag, rationale, and opportunity metadata.
- Extended `SkillExtractor` with session-log to experience-atom extraction and consolidation scoring for skill promotion.
- Added tests for planner scheduling metadata and skill/experience extraction.
- Added JSONL sidecars for durable memory entries and transferable experience records.
- Added a reviewable `SkillCandidate` gate before extracted traces become skills.
- Added benchmark preflight checks and CLI hooks for dependency/server readiness.
- Wired autonomous mode to prefer ready `TaskSystem` opportunities over default generated goals.
- Added durable skill candidate queue plus CLI listing, extraction, approval, and rejection commands.
- Added remediation hints to preflight checks so failed readiness gates point to the next action.
- Added benchmark trace ingestion so passing BM runs can create transferable experience records and reviewable skill candidates.
- Added action-result driven task updates so successful evidence completes tasks and repeated action failures can fail them.
- Installed Mineflayer dependencies locally and added bot-session health checks for live benchmark readiness.
- Fixed bot bridge response decoding so action commands and malformed bridge responses return reliable structured results.
- Added a lightweight item/block/tool knowledge graph over recipes, resource drops, tool tiers, mining requirements, and raw resource plans.
- Fed graph-derived recipe and mining summaries into the planner prompt to reduce noisy raw JSON context.
- Added `RuntimeSupervisor` as the first dual-loop planner/actor layer: the actor checks health, hostiles, deadlines, and return-to-base interrupts before each action.
- Extended `use_item` actions so emergency food use can equip the requested item before activating it.
- Added indexed paper cards for PEAM, Echo, WISE, TickingCollabBench, VistaWise, Optimus-2, JARVIS-VLA, and Game-TARS.
- Updated the research implementation map: Echo -> dimension-weighted experience retrieval, WISE -> causal event index, TickingCollabBench -> M7 schema, VistaWise/JARVIS-VLA -> graph-backed visual grounding.
- Added `CollaborationBenchmarkSpec` and feasibility checks for M7 time-sensitive collaboration tasks.
- Added BM-701, a JSON collaboration benchmark with heterogeneous roles, handoff dependencies, shared-state success keys, deadlines, and hostile nightfall risk.
- Added `CollaborationBenchmarkRunner` and `collab-benchmark` CLI dry-run to prepare shared state and assign M7 tasks through `LeaderAgent`.
- Added `ActionMapper` and backend command metadata so canonical actions can target Mineflayer now and planned desktop keyboard/mouse control later.
- Added graph-backed `VisionAnalyzer` grounding so visible resources include drops, minimum tool tiers, recommended/current tools, harvestability, source blocks, and direct craft uses.
- Added `CausalEventIndex` as the first WISE-style event memory: action transitions are stored in `causal_events.jsonl`, indexed by subject/action/outcome/tags, retrieved into planner memory, and populated from both live agent actions and session-log experience extraction.
- Fed causal event tags back into scheduling: `Agent` enriches observations with causal opportunity context, and `TaskSystem` gives secondary opportunity credit to task triggers that match causal memory even when no direct block/entity match is currently visible.
- Added a causal scheduling ablation switch and offline report: `TaskSystem(use_causal_opportunities=False)` disables causal opportunity credit, and `scheduling-ablation` compares direct-only versus causal-enabled task selection on deterministic cases.
- Extended `scheduling-ablation` with `--session-log` replay so successful and failed session transitions can be converted into direct-only versus causal-enabled scheduling cases; the first real log replay surfaced 5/5 causal-triggered choices, highlighting the need for high-value event filtering before live scheduling.
- Added causal event value scoring and scheduling filters: `CausalEvent.value_score` rewards actionable resource/craft/failure/health events, `MemorySystem.get_causal_opportunity_context()` defaults to a minimum score, and session-log replay can tune the threshold with `--min-value-score`. A real wood-gathering replay now filters low-value `move_to` transitions and keeps `dig:oak_log` events.
- Added causal event aggregation so repeated action/subject/outcome transitions collapse into compact summaries with `repeat_count`, max/average value score, event ids, merged tags, and representative evidence. Memory scheduling context and session-log replay now consume these summaries instead of emitting one candidate per repeated event.
- Added causal-summary skill candidate promotion: `SkillExtractor.extract_causal_skill_candidates()` converts repeated high-value successful summaries into reviewable `SkillCandidate`s, benchmark ingestion queues them alongside trace-level candidates, and the `skill-candidates --causal-summaries` CLI can extract them from existing session logs.
- Added failure-correction candidate promotion: repeated high-value failures are paired with the nearest useful successful corrective action sequence, then queued as `failure_correction_summary` candidates through `SkillExtractor.extract_failure_correction_candidates()`, benchmark ingestion, and `skill-candidates --failure-corrections`.
- Wired reviewed causal/correction skills into online behavior: `SkillLibrary` now parses approved JSON policy skills for planner hints and failure-action matching, `Agent` loads the configured persistent skill directory via `Config.skill_dir`, and failed actions can trigger an approved correction sequence before falling back to reflection/replanning.
- Added online intervention metrics for reviewed policy skills: `SessionLogger.get_summary()` now reports policy hint counts, correction intervention attempts/actions/successes/failures, success rate, and skill names; `BenchmarkResult`, saved benchmark JSON, and benchmark summary output carry those metrics.
- Added an offline reviewed-skill on/off ablation: `Config.enable_policy_skills` gates planner hints and failure correction, `policy-skill-ablation` runs deterministic disabled/enabled cases, and the report shows whether reviewed skills directly changed online correction behavior.
- Extended `policy-skill-ablation` to generate multiple cases from approved custom skills: pass `--skill-storage-path` to load `custom_skills.jsonl`, convert each approved `failure_correction_skill` into a disabled/enabled correction test, and use `--no-builtin` to focus only on real reviewed skills.
- Added live benchmark policy-skill ablation: `benchmark --policy-skill-ablation` runs the selected M1/M2/all suite once with `Config.enable_policy_skills` disabled and once enabled, then saves a suite comparison report with pass counts and intervention metrics.
- Added the first M7 collaboration execution loop: assigned tasks now move through `assigned -> in_progress -> completed/failed`, dependency and shared-state precondition gates block downstream tasks, and `collab-benchmark --execute` can run a synchronous state-transition pass before live worker adapters are attached.
- Added an Agent-backed M7 executor adapter: `AgentCollaborationExecutor` converts each assigned collaboration task into an `Agent.run_goal()` objective, applies task success criteria back into shared state when completed, and can be selected with `collab-benchmark --execute --executor agent`.
- Added configurable bot bridge endpoints: `BotConfig.bridge_host/bridge_port` replace the hardcoded Python bridge target, preflight checks the configured endpoint, and M7 Agent execution can assign sequential role bridge ports with `--bridge-port-base` for true multi-bot runs.
- Added M7 Agent bridge preflight: `collab-benchmark --preflight --executor agent --bridge-port-base N` checks every role bridge in expected execution order, verifies bot readiness and username/role alignment, then can proceed to live execution only when all role bridges are ready.
- Added explicit M7 role bridge mapping: repeated `--role-bridge-port role=port` flags override sequential bridge-port assignment, so live collaboration can pin each role to the intended Mineflayer bridge regardless of dispatch order.
- Added structured M7 report output: `collab-benchmark --output` saves dry-run assignments, Agent bridge preflight checks, execution task results, shared-state success keys, deadline misses, and errors as JSON for later baseline comparison.
- Added M7 single-agent baseline support: `--single-agent-baseline` transforms the same collaboration spec into one sequential `single_agent` role, runs it through the same executor interface, and stores a collaboration-vs-baseline comparison in the JSON report.
- Added M7 static schedule analysis: the runner estimates task start/finish times from dependencies, priority, deadline, role locks, and duration hints, then compares predicted collaboration makespan against the transformed single-agent baseline.
- Added M7 schedule-vs-execution comparison: execution records now include measured task start/finish/duration, and the saved report aligns live or simulated task traces with the static schedule to expose overhead, missing tasks, and deadline deltas.
- Added M7 role-parallel dispatch: each execution wave selects at most one runnable task per role, runs different roles concurrently through the executor, then serializes task completion and shared-state updates back into the file-backed coordination state.
- Hardened the M7 live Agent executor for role-parallel dispatch: agent creation, bridge-port assignment, and connection state are lock-protected, with per-role locks preserving one active `run_goal()` per bot while allowing separate roles to run concurrently.
- Added actual M7 overlap metrics: schedule-vs-execution comparison now sweeps measured task intervals to report peak parallelism, overlap seconds, task-seconds, busy window, parallel efficiency, and explicit overlapping task pairs.
- Added M7 Agent bridge launch plans: `--executor agent` now prints and saves exact role usernames, bridge ports, launch commands, and duplicate-port conflict warnings so live setup uses the same mapping as preflight and execution.
- Added a duplicate-port fail-fast gate to M7 Agent bridge preflight so multi-role live runs cannot accidentally bind multiple roles to one Mineflayer bridge.
- Added a Parallelized Planning-Acting-style `plan-act-latency-report`. It reads Agent session logs directly or extracts role logs from saved `collab-benchmark` JSON, then reports planner wait, plan-to-action delay, long-running action windows, stale-plan actions, unfinished plan suffixes, and cross-log action overlap before any interruptible executor changes are allowed.
- Added `plan-act-latency-gate`, which keeps interruptible role execution disabled until baseline and candidate plan-act reports plus verifier reports prove stale-plan actions dropped without increasing verifier rejections.
- Added `CurriculumManager` as a Voyager-style automatic curriculum layer for autonomous mode. It proposes open-ended Minecraft goals from inventory, visible resources, durable memory, skill coverage, and recent goal outcomes, while keeping emergency survival goals from `GoalGenerator` intact.
- Wired `Agent.run_autonomous()` through the curriculum selector after task-system opportunity checks, records `curriculum_goal` episodes when a generated goal is replaced, and includes curriculum state in autonomous run summaries.
- Added `GoalVerifier` as a deterministic self-verification layer for common Minecraft goals. It checks inventory targets, safety/hostile distance, food/health, shelter evidence, and exploration evidence before accepting planner-reported completion.
- Wired goal verification into `Agent.run_goal()` and `Agent.run_autonomous()`: verified observations can complete goals directly; known missing evidence rejects false `complete`; unknown goals remain accepted with an audit trail for future LLM/VLM critic routing.
- Added `goal_verification_metrics` to session summaries so benchmark runs can report verification count, achieved/failed/unknown decisions, accepted/rejected gates, and acceptance reasons.
- Added `VerifierAnchor` mining inside `GoalVerifier`: anchors are generated from `KnowledgeBase` recipes and `MinecraftKnowledgeGraph.resource_drops`, so newly known craft targets and mineable drops become deterministic postconditions automatically. Manual anchors remain for ambiguous aliases such as generic logs, planks, and charcoal.
- Extended `VerifierAnchor` mining to `SkillLibrary` postconditions. Reviewed/custom skills with inventory postconditions now contribute deterministic anchors, and post-action verification carries before/after inventory deltas into the evidence payload.
- Wired verifier outcomes into skill promotion: `SkillCandidate` signals now carry a `verification_gate`; approval rejects candidates with explicit failed verification before writing to `custom_skills.jsonl`, while achieved verification is converted into skill `postconditions.inventory`.
- Added `SkillPromotionValidationReport` so every candidate promotion decision has an auditable approve/reject/unknown explanation with evidence, missing requirements, matched verifier rules, inferred postconditions, and warnings. The `skill-candidates` CLI now displays verifier gate summaries during review.
- Extended benchmark ingestion with suite-level promotion validation aggregation: every queued candidate now carries its `promotion_report`, while `BenchmarkIngestionReport` counts raw approve/reject decisions, verifier statuses, and approved/rejected/unknown readiness for the whole run.
- Added `SkillPromotionCritic`, an explicit LLM fallback for candidates whose deterministic verifier status remains `unknown`. It is opt-in through `skill-candidates --promotion-critic` or `benchmark --ingest --promotion-critic`, returns sanitized JSON, can contribute inferred inventory postconditions, and is recorded inside the same promotion report without storing provider secrets.
- Added `visual_evidence` extraction for skill candidates: session observations and visual events are compacted into screenshot references, VLM summaries, grounded resources, landmarks, structures, flags, nearby blocks, and nearby entities, then passed to `SkillPromotionCritic` for visual-only goals and environment-state claims without storing image payloads.
- Added `promotion-review-ablation`, an offline session-log report that validates the same candidates three ways: deterministic-only, API visual summary, and screenshot/VLM-assisted review. The report counts changed decisions, API-visual helped cases, screenshot/VLM helped cases, and screenshot-added-value cases so visual context can be evaluated before becoming part of live promotion policy.
- Extended `promotion-review-ablation` with optional manual labels (`--label-file` JSON/JSONL). Reports now count deterministic/API-visual/screenshot-VLM agreement against reviewed `approved/rejected/unknown` candidate labels, letting real screenshot-backed traces measure promotion-review quality instead of only decision deltas.
- Added `GoalVerificationCritic`, an opt-in fallback for planner-reported completion when deterministic goal verification returns `unknown`. Offline ablations can invoke `--goal-critic` directly, while run/autonomous/benchmark/collaboration modes require an approved `--goal-critic-gate` before the critic can affect completion decisions; deterministic failures still reject directly, while critic-achieved and critic-failed unknown goals receive distinct session-log acceptance reasons.
- Added `goal-verification-ablation`, an offline replay report for session-log goals that runs the same `GoalVerifier` three ways: deterministic-only, critic with API-style structured visual summaries, and critic with screenshot/VLM references. This creates a direct measurement for when screenshot-backed evidence changes unknown visual/environment goals into accepted or rejected completion judgments.
- Extended `goal-verification-ablation` with optional manual labels (`--label-file` JSON/JSONL). Reports now count deterministic/API-visual/screenshot-VLM agreement against reviewed `approved/rejected/unknown` labels, plus screenshot/VLM improvements over API summaries, so real screenshot traces can be evaluated against human judgment before changing online policy.
- Added `goal-verification-critic-gate`, which consumes saved goal-verification ablations plus review-label validation reports and rejects runtime critic use on unreadable inputs, failed labels, manual mismatches, dangerous false approvals, or screenshot/VLM regressions against API/manual agreement.
- Added `review-label-template`, a JSONL template generator for manual review. It extracts promotion candidates and/or goal-verification segments from session logs, includes label keys, screenshot references, and visual-evidence keys, and leaves `readiness: "unknown"` for reviewers to convert into `approved`, `rejected`, or `unknown` before feeding the files back into the ablations.
- Added `visual-trace-report`, a pre-labeling coverage report for session logs. It counts screenshot paths, VLM/textual visual analyses, API visual evidence keys, visual-covered goal segments, and visual-covered promotion candidates so real traces can be triaged before spending manual review time.
- Wired `VisionAnalyzer` into Agent observation flow. Live `run`, `autonomous`, `benchmark`, and Agent-backed collaboration now enrich observations with structured `grounded_resources`, `visual_resources`, and `dangers`, and log lightweight `vision` events by default; `--no-vision-analysis` preserves baseline behavior.
- Wired short-term `VisualMemory` into the LLM planning context. Recent grounded resources, dangers, and visual summaries are compacted into a `Recent visual memory` block alongside episodic memory, causal context, and reviewed skill hints.
- Added screenshot-capture plumbing behind an explicit `--capture-screenshots` switch. Agent observations can request a bridge renderer screenshot path, feed it to `VisionAnalyzer`, log it as visual evidence, and store it in `VisualMemory`; plain Mineflayer bridges return an unsupported result until a renderer/plugin implements the hook.
- Added a Node bridge `--screenshot-plugin` loader for renderer modules. Plugins may export attach/install/capture functions, return screenshot file paths, `Buffer`, or base64 bytes, and the bridge writes byte outputs to the requested path while reporting `file_exists` and `file_size` for downstream visual-trace gates.
- Added `src/bot/screenshot_plugin_prismarine_viewer.js`, an optional prismarine-viewer renderer plugin that can produce first-person screenshots once `prismarine-viewer`, `three`, and `PrismarineJS/node-canvas-webgl` are installed. The default install remains lightweight, while `npm run start:screenshot` gives a concrete bridge launch path for real screenshot traces.
- Added screenshot renderer preflight: `node src/bot/screenshot_plugin_prismarine_viewer.js --check` emits a JSON dependency report, `preflight --screenshot-renderer` surfaces it as a `screenshot_renderer` gate, and `benchmark --preflight --capture-screenshots` automatically checks the optional renderer before live screenshot suites.
- Added a Docker screenshot bridge recipe under `docker/screenshot-bridge` so `node-canvas-webgl` and Xvfb can live in a Linux container while the default local Node install stays lightweight. The Node bridge now supports `--bridge-host`, allowing `0.0.0.0` inside the container with host-side `--bridge-host 127.0.0.1` from Python.
- Added `screenshot-smoke-test`, a runtime gate that requests one screenshot from the live bridge, verifies PNG/JPEG/GIF/WebP headers from Python, and points Docker users to the `logs/screenshots:/app/logs/screenshots` volume mount when the bridge reports a file that Python cannot see.
- Added a screenshot evidence quality gate to `visual-trace-report`: raw screenshot references are now separated from verified local image files, missing files, and invalid payloads, so screenshot-backed ablations can avoid treating arbitrary path strings as visual proof.
- Extended the screenshot quality gate into `review-label-template`, `promotion-review-ablation`, and `goal-verification-ablation`. Verified local image files are the only screenshot references passed to screenshot/VLM critics, and screenshot-backed improvement counters require at least one verified screenshot file.
- Added `review-label-validate` as a pre-ablation manual-review QA step. It validates label readiness values, match keys, and screenshot file evidence so noisy or partially filled label files do not pollute agreement metrics.
- Added `visual-review-pipeline`, a one-shot offline report that runs visual trace coverage, builds review-label templates, validates filled labels, and optionally executes promotion plus goal-verification visual ablations. Combined label files are split by record type before loading manual agreement labels, so promotion labels and goal-verification labels do not cross-match on shared goal text.
- Added OpenClaw-style recall diversity tracking for durable memories and transferable experiences. `get_relevant_memory()` and `retrieve_relevant_experiences()` now update recall counts, distinct query signatures, and last-recalled timestamps, while `memory-consolidation-report` surfaces candidates that meet usefulness, recall, and query-diversity gates.
- Added MineExplorer as an open-world exploration evaluation reference and mapped it to a future autonomous `exploration-trace-report`.
- Added SciCrafter and WhisperBench as research anchors for the next phase: discovery-to-application Minecraft tasks should record experiment hypotheses and held-out application evidence, while persistent memory/skill/policy writes should keep provenance gates before runtime use.
- Added `exploration-trace-report`, an offline MineExplorer-style report for session logs. It summarizes visited position spread, path distance, discovered block/entity/resource types, visual evidence coverage, hostile encounters, multi-hop goals, multi-step plans, and perception/reasoning/action failure categories.
- Added the first exploration-to-curriculum feedback bridge: `exploration-trace-report` emits a `curriculum_feedback` payload, `BenchmarkRunner.apply_exploration_feedback_to_curriculum()` applies it, and `CurriculumManager.record_exploration_feedback()` uses discovered resources, low-movement logs, and failure categories to adjust future exploration candidates.
- Added AGI-Maze-style `world-model-report`: session observations are discretized into X/Z cells with visit counts, transitions, resource hotspots, danger cells, unexplored frontiers, and suggested next exploration goals so long-horizon Minecraft exploration can audit an explicit world-state model instead of only path-distance metrics.
- Wired world-model feedback into curriculum scoring. `world-model-report` now emits `world_model_feedback`, `BenchmarkRunner.apply_world_model_feedback_to_curriculum()` applies it, and `CurriculumManager` can propose frontier, resource-hotspot, and danger-aware route goals from explicit map state.
- Added `discovery-application-report`, an offline SciCrafter-style report that checks whether a session contains an explicit knowledge gap/hypothesis, controlled experiment evidence, causal-rule memory consolidation, and a held-out application goal before experiment-derived skills are promoted.
- Wired discovery-to-application evidence into skill promotion. `SkillExtractor` now attaches `discovery_feedback` to candidates mined from discovery sessions, `SkillPromotionValidationReport` records a `discovery_gate`, and `skill-candidates --approve --discovery-skill-gate ...` blocks experiment-derived skills unless the discovery loop is approved.
- Added SkillDAG-style skill graph governance. `Skill` now stores structured dependencies, provenance, and gate metadata; approved candidate writes populate those fields; `skill-graph-report` audits typed skill dependencies, action/postcondition edges, missing prerequisites, cycles, and ungoverned custom skills.
- Added COS-PLAY-style skill contract retrieval. `skill-contract-report` scores reusable skills against a goal and world state, reports ready/review/blocked contract readiness, and `SkillLibrary.get_recommended_skills()` now considers contract matches alongside proven usage and approved policy skills.
- Added MineEvolve/VLM-AR3L-style self-evolution tracing. `self-evolution-report` converts session logs into progress/regression/stagnation signals, typed monitor feedback, heuristic absolute/relative reward summaries, remedy candidates, and adaptor recommendations before any automatic plan-suffix repair is enabled.
- Added an EmbodiSkill/VASO-inspired advisory `SelfEvolutionPolicy`. Runtime `Agent` can load saved `self_evolution_feedback` JSON and inject planner context that distinguishes execution-lapse-first repairs from skill-revision candidates, while preserving the verifier/gate boundary for any future automatic plan or skill mutation.
- Added `self-evolution-gate` as the verifier/counterexample boundary before automatic plan-suffix repair. The gate approves only when self-evolution feedback is actionable, verifier evidence passes, and explicit counterexample reports show no unresolved cases; otherwise feedback stays advisory.
- Added VASO-style self-evolution counterexample reporting. `self-evolution-counterexample-report` aggregates unresolved failures from self-evolution, terminal-commitment, plan-action compliance, action-verification, and action-value reports; the current M1 baseline produces 32 unresolved counterexamples and `self-evolution-gate` rejects automatic plan repair with `do_not_mutate_plan`.
- Added OpenHA/CrossAgent research notes and mapped Chain-of-Action style cross-level action abstraction onto the existing `ActionMapper` roadmap.
- Added `action-abstraction-report`, an offline session-log report that counts canonical action types, observed backend commands, planned desktop mappings, unknown canonical actions, failed mappings, and lower-level visual-control candidates.
- Added `action_abstraction_feedback`, which converts those traces into action-policy hints such as `mineflayer_api_ok`, `consider_low_level_visual_control`, and `define_canonical_mapping`.
- Added `ActionGranularityPolicy`, which consumes action-abstraction feedback and records per-action `control_policy` decisions while keeping Mineflayer as the safe executable fallback until desktop control is implemented.
- Added `memory-policy-report`, an AutoMem-style offline audit that compares explicit memory write/read/manage events with inferred context, episodic, semantic, failure-learning, and consolidation needs from session logs, then emits `memory_policy_feedback`.
- Instrumented Agent memory lifecycle calls so online runs log `memory_write`, `memory_read`, and `memory_manage` events, and `SessionLogger` summaries include memory policy metrics for writes, reads, management operations, layers, and memory types.
- Added `MemoryLifecyclePolicy`, an advisory consumer of `memory_policy_feedback` that labels writes, reads, and management operations with decisions such as `semantic_promotion_candidate`, `failure_learning_candidate`, and `write_review_needed`; `enforce_memory_write_gate` can suppress noisy writes when enough trace evidence exists.
- Closed the first feedback loop from `memory_policy_feedback` back into `MemoryLifecyclePolicy`, so missed semantic writes, failure-learning traces, noisy writes, retrieval instrumentation, and consolidation review hints alter future policy priorities and reasons.
- Added AgenticSTS-style bounded planning-context auditing. `bounded-context-report` groups `memory_read` events before each `plan`, checks typed retrieval diversity, per-read and per-cycle context budgets, missing read traces, and raw transcript risks before planner prompts are trusted as ablation-friendly evidence.
- Added AgentOdyssey/AgentCL-style continual learning diagnostics. `continual-learning-report` aggregates progress, world knowledge, memory read/write learning loops, object/action exploration, action diversity, bounded-context quality, and meaningful-horizon signals into per-session axis scores plus reviewable policy hints.
- Added AgentCL-style controlled task-stream transfer diagnostics. `task-stream-transfer-report` measures baseline-to-first-pass plasticity, second-pass stability, held-out generalization, expected reuse-tag coverage, and interference/regression so memory or skill promotion can be tested across compositional Minecraft goal streams.
- Added a MUSE-Autoskill/RIZZ-inspired transfer gate. `task-stream-transfer-gate` converts controlled stream reports into `approved`, `review`, `rejected`, or `error` readiness for memory/skill promotion based on positive transfer, stable replay, held-out generalization, reuse coverage, and zero interference.
- Wired transfer gates into promotion consumers. `skill-candidates --approve --task-stream-transfer-gate ...` stores transfer readiness in the candidate promotion report and skill governance metadata, while `MemoryLifecyclePolicy` uses approved/review/rejected transfer gates to promote, review, or block durable semantic/experience writes.
- Added seed controlled Minecraft streams in `workspace/evals/minecraft_task_streams.json` for wood-to-tools, shelter, mining, navigation, and redstone variants. These streams give `task-stream-transfer-report` a reproducible offline probe before real autonomous/M7 logs are available, while preserving the expectation that real scores or session logs replace seed values before default promotion.
- Added `skill-edit-proposal-report`, a SkillMaster-style offline review layer over queued skill candidates. It compares each candidate against the current skill bank, reuses verifier/discovery/transfer validation, requires approved transfer probes by default, and emits create/update/retain/reject proposals without mutating custom skills.
- Added MUSE-style skill-level memory. `Skill` records can now carry compact replay, failure, anti-pattern, evidence, and transfer-gate notes; `skill-memory-report` summarizes success/failure memory balance, task-family zones, approved/review transfer memories, missing skill-local evidence, and runtime-default candidates.
- Closed the first skill-memory write loop. Approved skill candidates now seed promotion/transfer memories, and live failure-correction skills append success or anti-pattern memories during `Agent._attempt_failure_correction()` so skill assets accumulate runtime feedback without bypassing verifier gates.
- Wired skill-level memory into planner context. `Agent._think_llm()` now retrieves `SkillLibrary.get_skill_memory_hints()` by inferred task family, logs `skill_memory_hint` events, and `benchmark --skill-memory-ablation` compares policy-skill-only baselines against policy plus skill-memory context.
- Typed runtime skill-memory hints as `REUSE`, `AVOID`, or `REVIEW_ONLY`. This keeps MUSE-style skill experience useful while applying RIZZ/AgentCL-style anti-interference controls and ACL 2026 memory-management warnings about error propagation and misaligned experience replay before memories enter planner prompts.
- Added `skill-memory-quality-report`, an offline session-log audit that labels typed skill-memory hints against later actions and goal outcomes. It surfaces candidate promotion labels such as `reuse_supported_by_goal_success` and review labels such as `reuse_conflicted_with_failures`, `avoid_unheeded_post_hint_failures`, and `review_only_present_keep_gated` before spending live Minecraft runtime on ablations.
- Closed the first quality-feedback read loop for skill memory. `SkillLibrary.record_skill_memory_quality_feedback()` consumes `skill-memory-quality-report` feedback, `Agent` can load it via `--skill-memory-quality-feedback`, and retrieval ranking conservatively demotes conflicted `REUSE` hints, boosts operational `AVOID` warnings, and keeps `REVIEW_ONLY` hints audit-gated without mutating skill files.
- Made skill-memory quality feedback local to `skill + task_family + hint_type` when reports contain `hint_quality_items`. This follows Agent-native-memory localized maintenance: a conflicted torch-crafting `REUSE` can be demoted without suppressing unrelated successful `REUSE` memories in the same family.
- Added `skill-memory-quality-ablation`, an offline before/after ranking report for quality feedback. It compares baseline skill-memory hints against feedback-adjusted hints, reports promoted/demoted items, and exposes quality-policy applications before live Minecraft runtime is spent on the same feedback.
- Added `skill-memory-quality-gate`, a conservative offline promotion gate that joins `skill-memory-report` skill-local memories with localized `hint_quality_items`. It approves only repeatedly supported `REUSE` evidence, keeps thin or review-gated evidence in review, and rejects conflicted/blocked reuse before any skill-memory default promotion.
- Gated runtime skill-memory quality feedback loading with approved `skill-memory-quality-gate` reports. `run`, `autonomous`, `benchmark`, and Agent-backed `collab-benchmark` can now require `--skill-memory-quality-gate` before `--skill-memory-quality-feedback` changes retrieval ranking.
- Added benchmark-level skill-memory quality preflight. `benchmark` now automatically checks configured `--skill-memory-quality-feedback` before live suite execution, requiring an approved gate plus an offline `skill-memory-quality-ablation` ranking effect against the current skill store.
- Added GovMem-style write governance flags to `MemoryLifecyclePolicy`: correlated/shared evidence and stale/out-of-scope/contradicted validity metadata now route candidate writes through review or strict suppression.
- Added M7 shared-memory provenance: collaboration tasks can declare `shared_state_provenance`, execution stores per-key `_shared_memory_provenance` histories, and reports summarize `_shared_memory_governance` counts including false-promotion review, correlated evidence, and unsafe scope.
- Added STALE-style shared-state revision detection: when M7 execution changes a previously provenanced shared key, the runner records `supersedes` metadata, marks the candidate as `implicit_conflict`, and reports state revision counts.
- Added MemConflict-style read filtering: `MemorySystem.get_relevant_memory()` accepts current state, excludes stale/superseded/invalidated/contradicted/out-of-scope or condition-mismatched durable entries, and exposes `memory_read_filter_report()` for retrieval diagnostics.
- Wired read-filter diagnostics into Agent `memory_read` events, session summaries, benchmark result JSON, `memory-policy-report`, and added `memory-read-filter-report` CLI for offline memory-directory audits.
- Added WhisperBench/Hermes-style promptware scanning to the memory lifecycle. `MemoryLifecyclePolicy` now routes obvious instruction override, role hijack, credential exfiltration, tool hijack, persistence, and C2-loop payloads to high-priority review or strict suppression; `MemorySystem` filters matching durable entries and transferable experiences before planner recall; `memory-promptware-report` audits memory stores without printing raw memory content.
- Added `memory-promptware-gate`, which turns saved promptware audit reports into approved/review/rejected evidence before stricter memory enforcement is enabled. The gate aggregates only counts, flags, and hashed report metadata, preserving the no-raw-memory-content property of the audit path.
- Added MineNPC-style mixed-initiative task templates and bounded validators: `mixed-initiative-report` compiles natural player requests into subtask records with dependencies, slot bindings, a surfaced clarification, scoped memory-write candidates, and optional bounded-evidence validation.
- Added `mixed-initiative-trace-report` to replay session logs through those bounded validators, summarize clarification pressure and policy violations, and compare template-level evidence with logged `GoalVerifier` accept/reject decisions.
- Updated mixed-initiative trace replay so unsupported goals are not forced into the oak-log template; reports now aggregate unsupported player requests into template candidates with suggested slots and validators.
- Added NitroGen as a cross-game visual-action foundation-model reference for Singularity's long-term low-level control and trace-collection roadmap.
- Promoted the first recurring mixed-initiative template gaps into executable built-ins: generic craft/process requests validate produced inventory, generic collect/mine requests separate source blocks from inventory drops, and build/place requests accept equivalent successful placement actions.
- Added `mixed-initiative-variant-report` as a lightweight OmniGameArena-style held-out replay harness: built-in and JSON/JSONL natural-language variants now check auto template selection, expected slot binding, clarification pressure, and optional bounded evidence validation before templates are promoted or heuristics are changed.
- Added GameWorld-style action-validity metrics to `mixed-initiative-trace-report`: reports now separate raw action success, valid action success after bounded-policy checks, invalid action counts, action type counts, and per-template action validity aggregates.
- Added `mixed_initiative_feedback` to trace JSON so template metrics become actionable hints: reject invalid actions, inspect backend execution, improve low-success action policies, audit validator/GoalVerifier disagreements, and promote recurring unsupported template candidates.
- Added `MixedInitiativeFeedbackPolicy` as the first consumer for those hints, producing per-template review decisions and template-candidate promotion recommendations for later action/template policy experiments.
- Wired `MixedInitiativeFeedbackPolicy.recommendations()` back into trace report JSON/CLI as `mixed_initiative_recommendations`, so downstream template-review or action-policy ablations can consume decisions without rehydrating policy state manually.
- Added `mixed-initiative-review-queue` as the first downstream consumer for `mixed_initiative_recommendations`: saved trace reports or raw session logs now aggregate into stable pending review items with source goals, active policies, and concrete action items for template promotion, backend/action-policy inspection, or validator audits.
- Added `mixed-initiative-review-plan` to route review queue items into follow-up experiment cases. This keeps Echo-style transfer evidence tied to source logs/goals while turning MineExplorer-style milestone failures into template approval, backend inspection, validator audit, or action-policy ablation commands and success metrics.
- Added mixed-initiative approval labels: `mixed-initiative-review-label-template` exports operator-fillable JSONL records from review plans, and `mixed-initiative-review-label-validate` turns approved labels back into executable review cases. This follows runtime-governance guidance by keeping template promotion and policy/validator experiment execution behind an explicit approval boundary.
- Added `mixed-initiative-review-execute`, a whitelisted executor for approved review labels. It validates approvals first, then calls internal trace, variant, action-abstraction, and visual-action ablation builders by route instead of executing free-form command strings from labels.
- Added `mixed-initiative-policy-patch`, which converts approved execution artifacts back into reusable `action_abstraction_feedback`, `mixed_initiative_feedback`, and template-policy update records. The helper `apply_mixed_initiative_policy_patch()` can hydrate `ActionGranularityPolicy` and `MixedInitiativeFeedbackPolicy` without mutating global config files.
- Wired approved mixed-initiative policy patches into live Agent startup. `Config.mixed_policy_patch_paths` loads action-policy hints into `ActionGranularityPolicy` and template review decisions into `MixedInitiativeFeedbackPolicy` before `ActionController` is created, preserving Mineflayer fallback safety while making offline review artifacts reusable in live runs and benchmarks.
- Added `mixed-initiative-policy-ablation`, an offline baseline-vs-patched decision report for approved policy patches. It compares action backend/preferred-control decisions, template review decisions, candidate-promotion decisions, and mixed-policy recommendations before spending live Minecraft runtime on the same patch.
- Added `benchmark --mixed-policy-ablation`, a live suite mode that runs tasks without and with approved mixed-policy patches, parses session action logs for `control_policy` summaries, and reports status, inventory, backend/preferred-control, fallback, and patch-decision changes.
- Wired `--mixed-policy-patch` through Agent-backed M7 collaboration execution so each role-specific Agent config preserves approved policy patch paths while still overriding username and bridge port per role.
- Added `collab-benchmark --mixed-policy-ablation`, which runs an Agent-backed collaboration spec through independent unpatched and patched shared-state files, reports both schedule-vs-execution comparisons, and summarizes execution deltas plus patch-decision previews for BM-701-style M7 runs.
- Extended M7 mixed-policy ablation comparisons with role session-log `control_policy` summaries, so reports show whether patched collaboration actually changed preferred controls, backends, fallbacks, and action/backend counts per role task.
- Added `mixed-initiative-policy-gate`, a promotion gate that combines offline policy-ablation reports, live benchmark patch ablations, and M7 collaboration patch ablations into `approved`, `review`, or `rejected` readiness before patches are treated as safe runtime defaults.
- Wired approved policy-gate reports into runtime patch loading. When `Config.mixed_policy_gate_paths` is set, `Agent` only applies mixed-policy patches if every gate report has `readiness=approved`; review, rejected, unknown, or unreadable gates skip patch loading and report the skip.
- Added Solaris as a multiplayer Minecraft visual world-model reference and tightened self-evolution monitoring accordingly: `self-evolution-report` now audits successful action returns against the next observed state signature, records `no_progress_success_count` and `repeated_success_loop_count`, and no longer treats success-without-state-delta as planner progress. This keeps MineExplorer-style milestone pressure, NitroGen-style action evaluation, and Solaris-style trace-quality requirements aligned before any automatic plan repair or VLA/world-model data collection.
- Added a blocked-plan prerequisite fallback for the current M1 failure mode. LLM `blocked`/empty/error plans now try the deterministic Minecraft rule planner before execution, direct cobblestone goals can bootstrap wooden-pickaxe prerequisites, `run_goal()` logs and exits unrecoverable `blocked_plan` loops instead of spinning 100 cycles, and `self-evolution-report` records blocked/empty/zero-action failures as high-priority feedback without enabling ungated automatic plan-suffix mutation.
- Added a Plan-to-Action-style compliance report. `plan-action-compliance-report` windows each plan against subsequent actions, counts ordered matches, unordered matches, missing planned actions, unplanned actions, order violations, blocked/empty plans, and emits advisory feedback so benchmark success can be separated from actual plan following.
- Added a VIGIL-style terminal commitment report. `terminal-commitment-report` replays final goal observations through the verifier, compares world completion against the `goal_end` completion claim, and separates verified success, unsupported commitment, post-attainment drift, missed execution, and unknown-world cases before any completion policy is trusted.
- Added a VeGAS/SVA-style action verification layer. `ActionVerifier` checks craft ingredients, mining tools/targets, inventory-backed item actions, and attack targets before live execution; Agent now logs `action_verification` events and blocks deterministic rejects when enforcement is enabled; `action-verification-report` replays session logs to track accepted, review, rejected, rejected-success, and failed-without-reject action gaps.
- Added a conservative verifier-guided candidate selector. `ActionCandidateSelector` keeps accepted/review planner actions unchanged, but when the original action is rejected it proposes feasible prerequisite repairs such as mining visible missing resources or crafting available tool/material prerequisites; Agent logs changed `action_candidate_selection` events, and `action-candidate-report` tracks original rejects, repaired rejects, unchanged rejects, and replacement examples before broadening the policy.
- Added an action-value memory bridge. `ActionValueProfile` records action signatures, successes, failures, verifier statuses, and task families; Agent updates the profile after each action and can load offline `--action-value-feedback` to bias `ActionCandidateSelector` scores; `action-value-report` exports reusable value items plus PEAM-style failure-correction pairs.
- Wired PEAM-style failure-correction pairs back into action selection. `ActionValueProfile` now stores failed-signature -> recovery-action examples from `action-value-report`, and `ActionCandidateSelector` can use them as provenance-preserving `value_repair` candidates when the original planner action is verifier-rejected. Memory-derived dig repairs are only admitted when the target block is visible, keeping this path conservative while ASV-style state-transition scores are collected and reviewed.
- Added deterministic ASV-style state-transition value to `action-value-report`. When session logs expose before/after observations, the report now emits per-signature `state_transition_value_items` with positive, negative, and no-progress counts from bounded Minecraft deltas such as inventory gain/loss, movement, visible resource discovery, health change, and new danger exposure.
- Regenerated the current M1 action-value baseline with transition values. The old trace still reports 200/200 action successes, but all 198 transition windows are low-confidence shared-observation attributions, so the next runtime logging step is to capture narrower per-action pre/post observations before transition scores become policy-updating evidence.
- Added action-local observation windows to runtime action logging. Goal-directed, autonomous, runtime-interrupt, and failure-correction actions now log compact `pre_observation` and `post_observation` snapshots on the action event itself, preserving ASV replay evidence without duplicating screenshots or raw image payloads.
- Added a confidence gate for ASV feedback consumption. `ActionValueProfile.merge_feedback()` loads only trusted `state_transition_value_items` into runtime scoring, skips low-confidence/shared-window transition values with explicit reasons, and blends trusted transition scores conservatively with outcome success rates.
- Added an offline `action-value-transition-gate` so saved ASV feedback artifacts have an explicit runtime-readiness decision. The gate aggregates trusted transition signatures, trusted attempts, and low-confidence rates across one or more `action-value-report` JSON files, approving only high-confidence action-local evidence and otherwise returning review hints to collect tighter transition windows.
- Added `action-value-transition-evaluator-report`, a state-grounded evaluator comparison layer for ASV traces. `action-value-report` transition items now carry compact before/after state summaries, and the evaluator report can call a configured LLM to compare deterministic Minecraft transition labels/scores against state-grounded judgments before any automatic policy-update path is opened.
- Added ASV transition-window diagnostics. `action-value-report` now reports transition coverage, action-local windows, next-observation windows, shared-observation windows, wide gaps, missing windows, and readiness hints; rerunning the current M1 session shows 198/198 transition windows are shared-observation attributions with 0 action-local windows, so the old baseline is audit-only until fresh pre/post action logs are collected.
- Added XENON-style knowledge correction staging. `knowledge-correction-report` mines repeated failed/no-progress actions plus failed-action -> successful-recovery pairs into reviewable failed-action memories and dependency-correction candidates with Echo-style transfer dimensions; `knowledge-correction-gate` requires ready logs and correction candidates before these artifacts can be treated as planner/runtime feedback.
- Wired approved XENON feedback into planner context. `--knowledge-correction-feedback` now requires an approved `--knowledge-correction-gate` before Agent startup loads dependency corrections or failed-action memories, and the planner receives only compact advisory hints instead of mutating built-in recipes or bypassing verifier checks.
- Added benchmark-level XENON feedback preflight. `benchmark --knowledge-correction-feedback ...` now runs `knowledge-correction-preflight` automatically, requiring approved gates plus at least one selected-suite goal that overlaps the correction candidates before live benchmark execution.
- Added offline XENON context ablation. `knowledge-correction-ablation` compares baseline empty correction context against gated Agent planner-context output for suite goals, explicit goals, or JSON/JSONL cases so operators can inspect which corrections would affect prompts before live runs.
- Added item-level XENON review labels. `knowledge-correction-review-template` emits JSONL records per dependency correction or failed-action memory, and `knowledge-correction-review-validate` repackages only manually approved items as `knowledge_correction_feedback` for gate/runtime consumption.
- Wired ASV transition readiness into runtime action-value feedback loading. `Config.action_value_transition_gate_paths` and `Config.action_value_transition_evaluator_report_paths` let live runs require approved transition/evaluator reports before `state_transition_value_items` enter `ActionValueProfile`; review, rejected, unknown, or unreadable gates suppress only transition scores while preserving ordinary action-outcome values and failure-correction pairs.
- Added benchmark-level ASV transition preflight. `benchmark --action-value-transition-preflight` checks saved `--action-value-feedback`, `--action-value-transition-gate`, and optional `--action-value-transition-evaluator-report` inputs before live Minecraft tasks run, requiring trusted transition items plus approved gates when transition scoring is intended.
- Added a MUSE-style skill lifecycle audit. `skill-lifecycle-report` joins skill definitions, skill-local memories, dependency/governance gates, postcondition/evaluation evidence, failure-refinement signals, and transfer readiness into one ready/review/blocked report before any task-family skill is treated as a runtime-default candidate.
- Added gated world-model curriculum feedback. `world-model-feedback-gate` approves only structured frontier/resource/danger map evidence from `world-model-report`, and runtime `--world-model-feedback` is loaded into `CurriculumManager` only when an approved `--world-model-gate` is supplied.
- Added Coachable Agents-style runtime coaching. `CoachPolicy` turns optional `--coach-style` profiles into advisory planner context and post-candidate curriculum score bias, while preserving ready-task priority plus verifier, safety, memory, and action-selection gates.
- Added a sandbox-style offline coaching replay. `coach-style-ablation` compares baseline curriculum choices with advisory style-biased choices over built-in cases, saved JSON/JSONL observations, or session-log observations, keeping style-control changes inspectable before live autonomous runs.
- Added `coach-style-gate`, which aggregates saved coaching ablations by style and approves only styles with enough replay cases plus score-changing evidence before they are treated as benchmark-ready.
- Added benchmark-level coach-style preflight. `benchmark --coach-style ...` now checks saved `--coach-style-ablation` and approved `--coach-style-gate` reports before style-biased benchmark execution, with optional `--require-coach-style-goal-change` for stricter style-effect evidence.
- Added a procedural-memory runtime-default gate. `skill-runtime-default-gate` joins `skill-lifecycle-report`, approved task-stream transfer gates, and optional localized skill-memory quality gates before task-family skills are allowed to move from review-only candidates toward runtime-default profiles.
- Wired runtime-default gates into Agent startup. `--skill-runtime-default-gate` loads approved profiles into `SkillLibrary`, filters learned policy skills, failure corrections, and skill-memory hints by approved task family, and suppresses learned defaults when the configured gate is review/rejected/error while leaving built-in primitive skills usable.
- Added benchmark-level runtime-default preflight. `benchmark --skill-runtime-default-gate ...` now automatically checks that every configured runtime-default gate is approved, has approved candidates, and covers at least one task family in the selected suite before live Minecraft tasks run.
- Added reusable runtime profiles. `runtime-profile-validate` checks profile JSON for approved gate reports, missing artifact paths, and required gate/artifact pairings, while `--runtime-profile` lets run/autonomous/benchmark/M7 Agent roles load the same approved goal-critic, mixed-policy, world-model, correction, action-value, skill-memory, runtime-default, and coaching configuration without copying long CLI flag sets.
- Added `runtime-profile-build`, a validating packager that writes profile JSON from approved gates, feedback artifacts, patches, and safe switches. This keeps Echo-style transferable feedback and Hermes/OpenClaw-style runtime profiles out of hand-edited deployment files and subjects the package to the same gate checks before use.
- Added `runtime-profile-security-audit`, which scans profile-referenced artifacts with the memory promptware detector before live startup. The report records fields, paths, JSON locations, flags, and content hashes without printing raw artifact text; `runtime-profile-build` and live `--runtime-profile` loading reject unreadable or promptware-like referenced artifacts.
- Seeded `workspace/runtime/m1_observed_action_value_profile.json` from the real M1 action-value feedback artifact and saved approved validation/security reports. The security audit now defaults to a 2MB complete-read limit so realistic offline feedback artifacts are scanned fully instead of being rejected by the old 200KB development default.
- Added `runtime-profile-suite-report`, which discovers profile JSON files in `workspace/runtime`, runs the existing validation and promptware security audit per profile, and reports required-suite coverage such as M1/M2/M7 before live profile-assisted benchmarks.
- Added benchmark-level runtime-profile suite preflight. `benchmark --runtime-profile ...` now requires an approved `--runtime-profile-suite-report` that covers the configured profile paths and the benchmark suite label before spending live Minecraft runtime on profile-assisted runs.
- Added M7 collaboration runtime-profile suite preflight. Agent-backed `collab-benchmark --runtime-profile ...` now performs the same approved-suite evidence check for the `m7` profile label before bridge launch plans, bridge preflight, or live execution.
