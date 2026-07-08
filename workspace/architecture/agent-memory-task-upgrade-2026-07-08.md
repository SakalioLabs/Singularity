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

### Optimus-2, JARVIS-VLA, Game-TARS, OpenHA / CrossAgent

Sources:
- https://arxiv.org/abs/2502.19902
- https://arxiv.org/abs/2503.16365
- https://arxiv.org/abs/2510.23691
- https://arxiv.org/abs/2509.13347
- https://arxiv.org/abs/2512.09706

Core idea:
- Strong game agents increasingly combine high-level language planning with low-level behavior/action policies.
- Unified keyboard-mouse or goal-observation-action representations generalize better than narrow APIs, but are expensive to train.
- OpenHA/CrossAgent adds that action abstraction itself should be task-dependent: abstract actions can be intermediate reasoning steps, while some steps need lower-level visual/keyboard-mouse control.

Singularity adaptation:
- Keep Mineflayer API control for reproducible M1-M5 progress.
- Add optional screenshot/VLM diagnostics in M6 before considering keyboard-mouse policy learning.
- Record canonical-to-backend action traces so future reports can compare API-level and low-level control needs by task.

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

## Implemented in this pass

- Fixed `KnowledgeBase` recipe loading path.
- Added `MemoryEntry` for bounded, curated durable memory.
- Added `ExperienceRecord` for Echo-style transferable experience and WISE-style causal fields.
- Added retrieval and curation methods to `MemorySystem`.
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
- Added `GoalVerificationCritic`, an opt-in runtime fallback for planner-reported completion when deterministic goal verification returns `unknown`. `--goal-critic` enables the configured LLM critic for run/autonomous/benchmark/collaboration modes; deterministic failures still reject directly, while critic-achieved and critic-failed unknown goals receive distinct session-log acceptance reasons.
- Added `goal-verification-ablation`, an offline replay report for session-log goals that runs the same `GoalVerifier` three ways: deterministic-only, critic with API-style structured visual summaries, and critic with screenshot/VLM references. This creates a direct measurement for when screenshot-backed evidence changes unknown visual/environment goals into accepted or rejected completion judgments.
- Extended `goal-verification-ablation` with optional manual labels (`--label-file` JSON/JSONL). Reports now count deterministic/API-visual/screenshot-VLM agreement against reviewed `approved/rejected/unknown` labels, plus screenshot/VLM improvements over API summaries, so real screenshot traces can be evaluated against human judgment before changing online policy.
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
- Added `exploration-trace-report`, an offline MineExplorer-style report for session logs. It summarizes visited position spread, path distance, discovered block/entity/resource types, visual evidence coverage, hostile encounters, multi-hop goals, multi-step plans, and perception/reasoning/action failure categories.
- Added the first exploration-to-curriculum feedback bridge: `exploration-trace-report` emits a `curriculum_feedback` payload, `BenchmarkRunner.apply_exploration_feedback_to_curriculum()` applies it, and `CurriculumManager.record_exploration_feedback()` uses discovered resources, low-movement logs, and failure categories to adjust future exploration candidates.
- Added OpenHA/CrossAgent research notes and mapped Chain-of-Action style cross-level action abstraction onto the existing `ActionMapper` roadmap.
- Added `action-abstraction-report`, an offline session-log report that counts canonical action types, observed backend commands, planned desktop mappings, unknown canonical actions, failed mappings, and lower-level visual-control candidates.
- Added `action_abstraction_feedback`, which converts those traces into action-policy hints such as `mineflayer_api_ok`, `consider_low_level_visual_control`, and `define_canonical_mapping`.
- Added `ActionGranularityPolicy`, which consumes action-abstraction feedback and records per-action `control_policy` decisions while keeping Mineflayer as the safe executable fallback until desktop control is implemented.
- Added `memory-policy-report`, an AutoMem-style offline audit that compares explicit memory write/read/manage events with inferred context, episodic, semantic, failure-learning, and consolidation needs from session logs, then emits `memory_policy_feedback`.
- Instrumented Agent memory lifecycle calls so online runs log `memory_write`, `memory_read`, and `memory_manage` events, and `SessionLogger` summaries include memory policy metrics for writes, reads, management operations, layers, and memory types.
- Added `MemoryLifecyclePolicy`, an advisory consumer of `memory_policy_feedback` that labels writes, reads, and management operations with decisions such as `semantic_promotion_candidate`, `failure_learning_candidate`, and `write_review_needed`; `enforce_memory_write_gate` can suppress noisy writes when enough trace evidence exists.
- Closed the first feedback loop from `memory_policy_feedback` back into `MemoryLifecyclePolicy`, so missed semantic writes, failure-learning traces, noisy writes, retrieval instrumentation, and consolidation review hints alter future policy priorities and reasons.
- Added GovMem-style write governance flags to `MemoryLifecyclePolicy`: correlated/shared evidence and stale/out-of-scope/contradicted validity metadata now route candidate writes through review or strict suppression.
- Added M7 shared-memory provenance: collaboration tasks can declare `shared_state_provenance`, execution stores per-key `_shared_memory_provenance` histories, and reports summarize `_shared_memory_governance` counts including false-promotion review, correlated evidence, and unsafe scope.
- Added STALE-style shared-state revision detection: when M7 execution changes a previously provenanced shared key, the runner records `supersedes` metadata, marks the candidate as `implicit_conflict`, and reports state revision counts.
- Added MemConflict-style read filtering: `MemorySystem.get_relevant_memory()` accepts current state, excludes stale/superseded/invalidated/contradicted/out-of-scope or condition-mismatched durable entries, and exposes `memory_read_filter_report()` for retrieval diagnostics.
- Wired read-filter diagnostics into Agent `memory_read` events, session summaries, benchmark result JSON, and added `memory-read-filter-report` CLI for offline memory-directory audits.
