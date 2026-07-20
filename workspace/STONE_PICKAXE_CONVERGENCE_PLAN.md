# Stone Pickaxe Skill Convergence Plan

## Claim Boundary

This project isolates two bounded Minecraft capabilities:

1. `SP-001`: acquire three cobblestone from observed allowlisted sources.
2. `SP-002`: craft one exact stone pickaxe from fixed materials at an observed crafting table.

`SP-003` composes them only after both independent skills pass their existing lifecycle gates. This project does not run or complete BM-012, does not establish iron acquisition, and does not change canonical M1-M4 capability status.

## Current Gate

| Microbenchmark | Eligible live successes | Extraction gate | Current learned skill |
|---|---:|---:|---|
| SP-001 Acquire Cobblestone | 3 | 3 | `learned:acquire_cobblestone@1.1.0` executable; `1.0.0` retained advisory |
| SP-002 Craft Stone Pickaxe | 3 | 3 | `learned:craft_stone_pickaxe@1.0.1` executable; `1.0.0` retained advisory |
| SP-003 Composite Chain | 0 | One baseline, then 3 candidate successes | Phase 144 step-up Planner-contract repair is offline verified; commit push and one bounded provider probe remain |

Current phase: **Phase 143 evidence commit `1ebbb35a` is pushed and synchronized. Phase 144 offline repair preserves the step-up marker, makes navigation-only table staging explicit, and passes exact retained-state counterfactual and schema checks. It is pending commit push followed by one bounded no-Minecraft provider probe. SP-003 remains 0/1 baseline and 0/3 candidate successes**.

Current authorization: **none**. All prior SP-001/SP-002 authorizations remain consumed or excluded, and all thirty-three SP-003 baseline authorizations through `sp003_baseline_20260720_173513_afba21cd` cannot be reused. Phases 139-143 each ran exactly once and cannot be retried. Phase 144 must be committed and pushed before one zero-retry no-Minecraft provider probe may test the exact retained step-up state. A fresh live authorization cannot be created unless that probe passes and its evidence is separately pushed. Automatic retry, authorization reuse, candidate execution before a passing baseline, full BM-012, Probe 24, and iron mining remain locked.

Phase 144 replays the exact retained target `sp003_clearance_shaft_step_up_egress:120:141:-37`. The compact state now carries `stone_clearance_shaft_step_up_egress=true`, the prompt requires one `move_to` for any navigation-only table-staging target, and targets with a stand position use exact x/y/z while earlier targets retain the position x/z fallback. The Phase 143 wrong `place` receives one pre-dispatch replan and no backend invocation, action-budget consumption, same-call retry, or world mutation; a duplicate fails closed. The exact move is normalized by the Phase 122 guard with inventory preservation, and forged skill context remains non-recoverable. Audit `77f94ee9...` and its Draft 2020-12 schema pass 7/7 focused checks without a provider or Minecraft process. Phase 134-144 evidence checks pass 45/45, all stone-pickaxe checks pass 424/424, the full repository passes 1177/1177, and all 1839 prospective deliverable JSON files parse; compilation, diff, and credential gates pass.

## Fixed Protocol

- Protocol: `stone-pickaxe-skill-fixed-v1`
- Artifact: `workspace/evals/stone_pickaxe_protocol.json`
- Protocol SHA-256: `e0722422b62da73d9c1c1c449ae6a3392913125e85c72adad8fa2c9bd0970006`
- Base protocol: `m4-fixed-v1` at SHA-256 `378689bc96d28580b2debcccb12efb4f955de38dd031e681ace529d4f75d157d`
- Minecraft: 1.20.4
- Server: Paper 1.20.4 build 499, hash pinned
- Mineflayer: 4.37.1
- World seed: `12345`
- Planner: `llm-autonomous-planner-v1`, OpenAI-compatible provider, `deepseek-v4-flash`, temperature 0, thinking disabled, zero provider retries
- Action backend: `mineflayer-bridge-v1`
- Goal verifier: `stone-pickaxe-machine-verifier-v1`
- Task system: `singularity-task-system-v1`
- Skill DSL: `bounded_action_template_v1`
- Default skill execution: off
- Quarantined skill execution: forbidden
- Automatic retry: forbidden

Fixture identity, initial state, deadlines, action limits, nearby-table policy, source allowlist, and eligibility rules are part of the protocol. A live run must additionally prove the immutable fixture snapshot identity before authorization can be consumed.

## SP-001 Contract

Initial machine state:

- Exact `wooden_pickaxe:1`
- `cobblestone:0`
- `stone_pickaxe:0`
- Safe and movable player state
- At least one reachable observed `stone` source

Bounded execution:

- Only `acquire_block_drop`
- Only source block `stone`
- `selector=nearest_observed`
- Quantity range 1-8, default 3
- Maximum eight actions
- One grounded action per observation followed by mandatory re-observation
- No stored coordinates, source IDs, session IDs, or arbitrary code in the template

Machine success requires at least three distinct source removals, pre/post observations for each dig, approved tool proof, corresponding cobblestone pickup provenance, and terminal `cobblestone` delta of at least three. Planner text and action-result success are insufficient.

## SP-002 Contract

Initial machine state:

- Exact `cobblestone:3`
- Exact `stick:2`
- `stone_pickaxe:0`
- Observable, interactive crafting table within 4.5 blocks

Bounded execution:

- Only `craft_item`
- Exact `item=stone_pickaxe`
- Exact `count=1`
- Exact terminal `target_item=stone_pickaxe`
- Maximum one action
- The `recipe` alias and family substitutes are rejected

Machine success requires exact material consumption, positive stone-pickaxe inventory delta, table interaction evidence, and a distinct stable re-observation at least 0.25 seconds after the immediate post-state. A transient inventory ghost is failure.

## SP-003 Contract

The supplemental `stone-pickaxe-sp003-empty-hand-runtime-v2` policy is bound to the unchanged v1 protocol and existing executable skill records. Every episode uses a fresh seed-12345 survival world and exact empty inventory, then follows the fixed five-node graph: three same-family logs, one placed crafting table, one wooden pickaxe, three verified stone removals, and one stone pickaxe.

The action guard permits exactly one grounded action per Planner cycle. It binds navigation and digging to the nearest observed same-family source, retains the machine-proven table position for bounded return navigation, permits exactly five single-attempt craft actions, and rejects extra resources, duplicate mutation, support-column stone, iron mining, family substitution, target injection, or retry. A requested table reference may be rewritten once only when that exact solid is observed within placement range but its target is unsafe; the deterministic replacement is the nearest clear observed candidate. SP-003 normally uses horizontal movement goals. Stone-probe targets are centered in their unchanged Pathfinder cell and use a 1.6 continuous-distance bound that covers the far corner of one adjacent cell. The empty leaf-canopy gate binds an exact observed clear stand above eligible distant ground. A stone more than one block below the player first becomes a horizontal clearance probe. A stable complete radius-one scan below the frozen backend's 50-result limit may bind only the highest `grass_block` or `dirt` obstruction over the nearest exact stone support, outside the player's column, with three removals maximum across the episode. Every removal carries scan, support, shaft, order, block-delta, and proof-fingerprint evidence; the full shaft must be clear before descent. Its process-local Pathfinder policy still forbids digging and scaffolding, tightens only three-dimensional unit-range `GoalNear` instances to exact range 0, and fails any guarded move with machine-observed inventory loss. Before the first table-bound wooden- or stone-pickaxe craft, the same preload opens and validates the exact structured crafting table once, closes it, and requires unchanged inventory; this readiness preflight makes no craft call or world mutation, cannot retry, and is reused by the second tool craft. The preload also retains the existing 1000ms post-resolution settlement only for interactive table crafts so the frozen bridge refresh cannot race the transaction; it adds no craft call or retry. The wrapper is installed exactly once on `inject_allowed`, after Mineflayer's internal plugins, and never requires `bot.craft` synchronously at `createBot` return. Wooden- and stone-pickaxe crafts must use the same placed table.

Success requires the full five-node TaskSystem graph, both frozen component machine verifiers, stable terminal re-observation, and no skill-store mutation. The baseline keeps learned skills off. Each candidate must separately attribute the cobblestone stage to `learned:acquire_cobblestone@1.1.0` and the final craft to `learned:craft_stone_pickaxe@1.0.1`. Reset reuses BM-012 only as an empty natural-state substrate; BM-012 terminal execution and M4 credit are forbidden.

## Evidence Policy

- Offline fixtures exercise verifier behavior but always record `counts_toward_skill_gate=false`, `counts_toward_capability=false`, and `counts_toward_m4=false`.
- Live evidence requires unique session, episode, and session hashes; exact protocol identity; clean reset; no forbidden intervention; no post-deadline work; and zero quarantined-skill selections.
- One live episode is allowed per explicit authorization. There is no automatic retry or batch execution.
- Failed and quarantined skill versions remain immutable. A repair uses a new version.
- Future evidence paths are repository-relative. Run and promotion artifacts are created only after corresponding evidence exists.

## Lifecycle Gates

1. SP-001 must reach 3/3 independent eligible live successes before candidate extraction.
2. `learned:acquire_cobblestone` must move through candidate, advisory, three paired baseline/candidate evaluations, and only then executable review.
3. SP-002 must separately reach 3/3 independent eligible live successes before candidate extraction.
4. `learned:craft_stone_pickaxe` follows the same non-skippable lifecycle.
5. SP-003 remains locked until both skills are executable, then requires a baseline plus three independent eligible candidate successes.

No threshold, GoalVerifier relaxation, or synthetic evidence can bypass these gates.

## Offline Harness

Base implementation: `src/singularity/evaluation/stone_pickaxe_protocol.py`

SP-003 implementation: `src/singularity/evaluation/stone_pickaxe_sp003_runtime.py`

SP-003 navigation preload: `src/bot/sp003_inventory_preserving_navigation.js`

SP-003 tests: `tests/test_stone_pickaxe_sp003_runtime.py`

SP-003 navigation tests: `tests/test_sp003_inventory_preserving_navigation.js`

The 30 numbered cases cover:

- Cases 1-10: exact acquire preconditions, allowlisted deterministic selection, quantity bounds, coordinate-free templates, source deduplication, pickup provenance, and wrong-drop rejection.
- Cases 11-20: exact craft materials/table, exact terminal item, ghost rejection, stable re-observation, one-action bound, recipe-alias rejection, and no family substitution.
- Cases 21-27: dependency release, terminal-task idempotency, one recovery child per fingerprint, stale-sibling removal, quarantine-safe fallback, and local attribution.
- Cases 28-30: M1/M2/M3 regression obligations, immutable wooden-pickaxe skill history, and immutable Probe 21/22/23 evidence hashes.

## Controlled Runtime

- `scripts/stone-pickaxe-runtime.ps1` owns only the Paper/Bridge processes it starts, restores `server.properties`, verifies the existing EULA state, and refuses occupied ports, a dirty or unsynchronized `main`, reused worlds, or a mismatched Paper hash.
- `scripts/stone_pickaxe_episode_runner.py` gives the normal Agent/Planner one high-level preparation or SP-001 goal. It does not issue benchmark reset, target-result injection, or a scripted gameplay action sequence.
- `src/singularity/evaluation/stone_pickaxe_runtime.py` seals canonical `world`, `world_nether`, and `world_the_end` trees under one content identity; restoration is hash-checked before Paper starts.
- Fixture preparation permits ordinary survival wood/table/wooden-pickaxe actions but rejects stone mining, duplicate wooden-pickaxe craft, and wooden-pickaxe craft without an observed table within 4.5 blocks. Its output is non-counting.
- SP-001 keeps learned skills off and allows only bounded observation/navigation, exact wooden-pickaxe equip, and the nearest reachable observed `stone` dig. Every dig requires strict tool, block-removal, pickup, and pre/post-observation proof.
- `scripts/stone-pickaxe-sp003-runtime.ps1` requires clean synchronized `main`, a pushed one-file authorization commit, a fresh unique world and evidence directory, the pinned Paper/protocol identities, free owned ports, and bridge craft attempts fixed to one. It preloads the SP-003-only inventory-preserving `Movements` constructor before the unchanged bridge, starts exactly one episode, and has no retry loop.
- `scripts/stone_pickaxe_sp003_episode_runner.py` retains the authorization, reset, preflight, raw session, episode, component verification, audit, and manifest in one append-only run directory. It never starts BM-012 terminal evaluation or grants capability/M4 credit.
- `Agent.run_goal` can now bind Planner and ActionController to one supplied absolute deadline and suppress every action beyond a supplied total budget. Existing callers retain their previous behavior when those optional bounds are absent.
- Offline status: Phase 130 focused tests pass 6/6, cross-phase SP-003 tests pass 62/62, all stone-pickaxe Python tests pass 343/343, and the repository-wide Python gate passes 1098/1098. Seven Node suites pass 84/84 machine-counted internal cases; 1753 deliverable JSON files parse. Compilation, diff checks, retained Phase 129 evidence hashes, capability/GoalVerifier/M1/M2/M3 regressions, historical policy compatibility, and credential scanning also pass.
- Phase 129 runs one fresh baseline from authorization commit `1c70c093`. All thirteen real Planner calls use one provider attempt and zero retries; twelve are schema-valid. All ten attempted actions succeed, producing three removed logs, twelve planks, four sticks, one carried crafting table, and two valid surface-clearance removals. Four pre-dispatch checks expose a base-guard/effective-guard dispatch mismatch. The terminal response is provider-identity-preserved at 596 bytes and 280 reasoning characters, but `status=planning` carries zero actions and fails only `planning_action_count_must_equal_one` while an unblocked machine target remains. Manifest `32e7c5c6...` binds all thirteen payloads. Evidence replay passes 3/3, Phase 127/128 regression passes 10/10, all stone-pickaxe Python tests pass 339/339, the full repository passes 1092/1092, and all 1752 JSON files parse. Compilation, diff checks, and credential scanning pass. No retry, baseline credit, skill credit, capability credit, or M4 credit is granted.
- Phase 130 resolves the current effective SP-003 guard at both pre-dispatch and execution verification boundaries, so Phase 116/118/120/122 overlays retain their stricter machine-grounded permissions consistently. It also intercepts only the exact Phase 129 actionless-planning schema failure before generic `empty_plan`, requests a fresh observation and next-cycle replan once per fingerprint and twice per episode, and otherwise fails closed. Generic Agent behavior is unchanged because the base recovery hook returns false. Audit `214b853d...` binds the repair, current harness policy `231ebbed...`, Phase 129 evidence commit `f9bd709c`, and protected historical identities. This is offline engineering evidence only; no live episode, authorization, success credit, capability credit, or M4 credit is created.
- Phase 131 consumes exactly one authorization from pushed commit `67f44122`. All 23 real Planner calls are schema-valid and use one transport attempt with zero retries. Twenty-two actions succeed and the entire behavior chain completes, including exact table/tool crafts, three distinct stone removals, a passing SP-002 component, and terminal `stone_pickaxe:1`. Call 18 nevertheless contradicts its own machine target: despite `navigation_only=true` and `stone_pickup_approach=true`, it emits a direct dig at `(124,138,-38)` without `source_id`. The effective guard rejects that action before the backend or mutation. A following move and two grounded digs finish the chain, but strict validation correctly reports `exact_three_stone_actions`, `sp001_machine_verifier`, and `zero_unreconciled_action_failures`. Manifest `2ae4db2d...` binds all thirteen payloads. Evidence replay passes 3/3, all stone-pickaxe tests pass 346/346, the full repository passes 1101/1101, and 1765 JSON files parse; compilation, diff, and credential gates pass. No retry, baseline credit, skill credit, capability credit, or M4 credit is granted.
- Phase 132 adds only the exact Phase 131 grounded-approach guard issue to bounded pre-dispatch replanning. The effective guard must first prove the target is navigation-only; recovery then emits no backend call or world mutation, consumes no action budget, and waits for a fresh observation. Duplicate fingerprints, exhausted episode bounds, mixed issue sets, and every other safety issue still reach the original guard rejection. Exact retained replay removes only the rejected fourth stone attempt and projects 22/22 successful actions with three distinct grounded stone digs and terminal `stone_pickaxe:1`. Audit `2c997729...` binds the repair and protected identities. Focused tests pass 5/5, Phase 128-132 regression 24/24, all stone-pickaxe tests 351/351, full Python 1106/1106, targeted TaskSystem/GoalVerifier/capability/M1/M2/M3 161/161, and seven Node suites 84/84; 1766 JSON files parse and compilation, diff, and credential gates pass. No live process, authorization, baseline, skill, capability, or M4 credit is created.
- Phase 133 pushes Phase 132 at `0393ba45`, consumes exactly one separately pushed authorization `77199001`, and retains episode `sp003_baseline_20260720_111853_3cd46332`. The root plan is valid and all four executed actions succeed: one canopy egress move plus three distinct oak-log removals, with terminal `oak_log:3` and zero raw failures. External Planner latency dominates `272.248s` of the 300-second budget across five single-attempt calls. Call 4 returns after its action window and is retained as `stone_planner_response_missed_action_window`; the run ends `max_duration` before planks, table, either pickaxe, or stone. Phase 132 is not exercised. Manifest `8faabcec...` and all thirteen files replay 3/3; stone-pickaxe tests pass 354/354, full Python 1109/1109, and 1778 JSON files parse with compilation, diff, and credential gates clean. No retry, baseline, skill, capability, or M4 credit is granted.
- Phase 128 adds bounded reasoning normalization and pre-dispatch semantic replanning. It does not rewrite actions, invoke the backend, consume action budget, mutate the world, retry transport, or change the shared Bridge, protocol, verifier thresholds, or runtime limit. Repair commit `599fc76e` is pushed and synchronized.
- Phase 126 adds no Planner action rewrite, schema retry, runtime retry, Bridge change, preload change, protocol change, verifier-threshold change, or action-budget change. Its Phase 125 full-observation counterfactual passes SP-001 with no issues, while legacy retained evidence without the new source-order contract remains byte-identical and failed. No Minecraft process or live authorization runs in the offline transaction.
- Phase 127 runs one fresh baseline from authorization commit `a9ead681`. Eleven of twelve real Planner calls are schema-valid; all twelve use one provider attempt and zero retries. Ten of eleven actions succeed, three logs and the exact plank/stick/table crafts complete, and two literal surface-clearance actions succeed. The guard-rejected extra-plank request and terminal `reasoning_too_long` schema rejection prevent table placement and all downstream tool/stone stages. Evidence replay passes 3/3; after one unrelated scheduling-ablation case transiently failed and passed its 1/1 isolated replay, the final full repository rerun passes 1082/1082. All 1868 deliverable JSON files parse, all 13 evidence hashes match, and credential scanning finds zero matches. No retry, baseline credit, skill credit, capability credit, or M4 credit is granted.
- Phase 102 keeps the action guard and fixed protocol unchanged while replacing unbounded planner history with a strict allowlist, one target, and an authoritative fine-grained machine stage. The retained Phase 101 root, first drift, and terminal observations remain under 2,500 compact characters and 5,000 user-prompt characters; stale stage actions remain guard-rejected and no scripted action rewrite is permitted. Audit `686b7eca...` binds the repair.
- Phase 103 live-exercises that repair through exact table and wooden-pickaxe completion with zero action failures. Calls 10-12 remain at `acquire_cobblestone` under bounded prompts. Call 12 returns one navigation-only clearance-probe move and fails only `action_parameter_y_invalid`: the prompt says to emit only `x/z`, while the generic validator requires `x/y/z`. Manifest `fcce5b84...` binds the immutable run; no retry or stone removal occurs.
- Phase 104 narrows the correction to the strict SP-003 planner envelope. Horizontal `move_to` requires finite `x/z`; an explicitly present `y` must also be finite. `look_at`, SP-001, SP-002, and generic stone modes retain the original `x/y/z` contract. The runtime guard still binds machine-proven movement coordinates and no action rewrite is allowed. Audit `649dc406...` binds current source and policy hashes plus the immutable Phase 103 replay, protocol, Bridge, and Probe 21/22 identities.
- Phase 89 retains target `stone:124:139:-37` and first exposes only a tolerance-one horizontal clearance probe. A later 63-cell radius-one scan is complete only when its response is below the frozen backend's 50-result cap and the player cell is stable. Exact stone support plus clear stand/head cells bind stand `(124,140,-37)`; direct probe or anchor digs are rejected. Once grounded, the support stone is excluded and an adjacent same-level stone dig is allowed. Missing, full-limit, obstructed, forged, or position-drifted proof fails closed. No live process ran.
- Fixture session `sp_fixture_prep_20260715_143222_b0e58483` exposed the first blocker: Planner call 0 consumed the completion budget as hidden reasoning, returned zero response bytes, and caused `empty_plan` before any action. The fixed request path now sends thinking-disabled controls, uses one deadline-bounded zero-retry call, rejects empty output, and independently audits Planner controls before fixture sealing or SP-001 eligibility.
- Fixture session `sp_fixture_prep_20260715_152529_b99f05dd` then proved those request controls on its first two calls and executed two successful moves. Its second plan nevertheless contained nine actions; the first dig suffix omitted the exact `block` field and was rejected before execution. The old generic envelope also admitted three `recipe` aliases and created ten tasks across two root IDs. Call 2 then reached `finish_reason=length` with truncated JSON, so the session stopped at `empty_plan` without retry.
- The second repair gives the stone protocol a dedicated compact schema: one root plan, two to six root subtasks, no continuation/replan subtasks, exactly one immediate planning action, canonical exact parameters, bounded reasoning, mode-bound compact observations, and failure reason propagation into the same root. Missing `dig.block`, `recipe`, unbounded action lists, duplicate roots, and malformed terminal output all fail before action execution.
- Fixture session `sp_fixture_prep_20260717_001130_678ddb1e` returned one compact root plan with six subtasks and one action under fully compliant request controls. It failed closed before task creation or action execution because subtask 5 had the only schema issue, `priority_invalid`; no other transport, deadline, size, action-count, or finish-reason check failed.
- The third repair explicitly states that every root priority is a JSON integer from 1 through 5 and directs the Planner to use 1 when no ordering distinction is needed. The validator remains strict and offline tests reject both zero and string priorities.
- Fixture session `sp_fixture_prep_20260717_154044_81052541` then completed six valid survival actions: three log digs, plank craft, table craft, and stick craft. At cycle 7 the table existed only in inventory, no nearby table was observed, and the Planner emitted wooden-pickaxe craft. The backend reported `crafting_table_found=false` and no recipe; seven identical failed crafts consumed the remaining deadline. The old root schema also admitted unsupported `{"placed":true}`, leaving one task active and two accepted. The terminal timeout was downstream, not the earliest blocker.
- The fourth repair distinguishes inventory table items from observed tables. The action guard rejects wooden-pickaxe craft unless a table is observed within 4.5 blocks, the fixed prompt requires placement first, unsupported task-state keys fail schema validation, and each post-action observation reconciles only dependency-ready `inventory` or `nearby_block_present` tasks.
- Fixture session `sp_fixture_prep_20260717_221520_064dd337` passed in 18 actions and 157.313 seconds. It ended with exact `wooden_pickaxe:1`, zero cobblestone/stone-pickaxe, 13 reachable observed stone sources, compliant request controls across 18 Planner calls, and no forbidden intervention. The sealed 45-file snapshot is 14,684,703 bytes with tree SHA-256 `996b2a1f989626e9c44ddca5c24f81ae55a5dca03b246f0d72723c46fd6a7636`.
- Independent `AuditFixture` initially exposed a local Windows PowerShell compatibility gap because the host .NET lacks `Path.GetRelativePath`. A repository-bounded substring helper now serves both audit and SP-001 paths, and a real audit rerun passes. Post-action task reconciliation also closes machine-satisfied tasks after consumptive preconditions disappear.
- SP-001 episode `sp001_episode_20260717_223525_23696e33` restored the exact fixture and passed infrastructure, request, deadline, and eligibility controls. It stopped at `max_actions` after 35.188 seconds: all eight actions were successful equips, no dig ran, and removals, pickups, and cobblestone delta were zero. The first equip changed machine main hand from `dark_oak_log` to `wooden_pickaxe`, but the stone compact state omitted equipment and the guard accepted seven redundant equips.
- The offline repair adds exact `held_item` from machine equipment slot 0 to the compact planner state, directs the LLM to advance to nearest-stone dig when the wooden pickaxe is already held, and rejects redundant equip in the runtime guard. The retained live transition is replayed in tests and all ten run artifacts are hash-bound without modifying them.
- SP-001 episode `sp001_episode_20260717_230318_23d8bdf3` then removed four distinct stones and ended with `cobblestone:4`, but one transition failed strict pickup provenance. Its drop entity `322` survived a `GoalNear(1)` false completion at distance `1.503` and was recovered only by a later fallback, whose delta 2 cannot retroactively repair the failed transition.
- The second repair permits one safe adjacent standable fallback candidate within a fixed 0.5-block selection margin. Direct range 1, the one-fallback limit, and completion by measured range or real inventory delta remain unchanged; no unsupported candidate can self-certify success.
- SP-001 episode `sp001_episode_20260717_232454_5c05abf0` then passed in 4 actions and 19.297 seconds. It equipped once, removed three distinct observed stones, proved one corresponding pickup and `cobblestone:+1` delta for every dig, ended with `cobblestone:3`, and passed reset, request-control, deadline, intervention, task-graph, machine-verification, and eligibility checks.
- SP-001 episode `sp001_episode_20260718_012012_0349d399` independently passed the same contract in 4 actions and 21.422 seconds, with distinct episode, session, session hash, and restored level identities. It recorded zero action failures, zero false-success digs, zero post-deadline actions, zero selected skills, and zero forbidden interventions.
- SP-001 episode `sp001_episode_20260718_013304_7c162864` then encountered `APIConnectionError -> ConnectError -> SSLEOFError` on its sole root planning attempt. It emitted zero response bytes, created zero tasks, executed zero actions, preserved exact inventory, and stopped without retry. This is retained external transport evidence; the framework already failed closed, so no protocol or runtime change is justified.
- SP-001 episode `sp001_episode_20260718_014459_7a1a9b49` removed three stones but grounded only one pickup before the eight-action limit. On action 3, drop entity `321` remained at measured distance `1.503`; the safe fallback cell `(95,131,-32)` had expected pickup distance `1.425` but aliased the player's current block cell at center distance `0.079`, so `GoalBlock` resolved without movement. The same entity persisted into the next dig, and the later nearest-source rejects were downstream.
- The third behavioral repair performs one bounded 100ms forward nudge toward the validated safe position when a fallback cell aliases the current player cell. Forward control is cleared in `finally`; the fallback attempt limit remains one; measured one-block distance or a real inventory delta is still mandatory. A retained-session replay, a positive recovery case, and a negative no-delta case pass without changing the protocol.
- SP-001 episode `sp001_episode_20260718_022202_615c7b84` then hit the same external transport chain on its sole root call: `APIConnectionError -> ConnectError -> ConnectError -> SSLEOFError`. It emitted zero response bytes, tasks, transitions, actions, retries, or world mutations and preserved exact inventory. The same-cell repair was not exercised, and retained replay confirms that the existing single-attempt path failed closed without justifying a code or protocol change.
- SP-001 episode `sp001_episode_20260718_023754_912de280` independently passed after five TLS probes and one authenticated minimal completion confirmed provider health. Four successful actions removed three distinct stones, grounded three pickups, and ended with exact `cobblestone:+3` in 23.391 seconds. Its episode, session, restored level, and session hash identities are distinct, completing the extraction gate at 3/3.
- All four failed machine audits remain non-counting and immutable; the fifth successful preparation is also non-capability evidence, and all five failed SP-001 episodes grant no skill or capability credit. The three eligible SP-001 successes count only toward the completed extraction gate. Twenty preparation evidence files, eighty SP-001 evidence files, and the tracked fixture manifest are hash-bound in `workspace/evals/stone_pickaxe_failure_ledger.json`; the protocol JSON and hash are unchanged.
- Candidate extraction preview exposed a generic discovery-feedback source-path `NameError` and showed why raw fixture inventory must not become a learned precondition. Pushed repair `64243de` rechecks all three source bundles and emits only the exact contract. Candidate commit `a40425f` then froze the pending record before a separate command created `learned:acquire_cobblestone@1.0.0` as advisory. The real queue, learning ledger, promotion history, and advisory record are cross-checked; no executable gate exists. The first advisory write also replaced an obsolete whole-file freeze with canonical hashes for each of the eight pre-existing skill records, so authorized appends cannot mask any history rewrite.
- Supplemental policy `stone-pickaxe-sp001-paired-evaluation-v1` leaves the base protocol byte-identical and binds the exact advisory record, candidate queue record, promotion artifact, fixture tree, and three retained successful baseline bundles by SHA-256. All three baseline records independently pass and share one fixed-control fingerprint plus one contract-relevant initial-state fingerprint.
- The paired runtime exposes only `shadow`, `advisory`, fail-closed `fallback`, and exact `candidate` arms. Every arm consumes one explicit replicate authorization; duplicate arm/replicate records reject the report. Shadow/advisory/fallback cannot directly execute the skill. Candidate mode is restricted to `learned:acquire_cobblestone@1.0.0`, and every skill action must retain ActionController, ActionVerifier, post-action re-observation, and the unchanged SP-001 machine verifier.
- Evaluation loads the skill library read-only and disables its learning ledger, so a live trial cannot rewrite the advisory record in place. Source hashes alone are insufficient: each run record is recomputed from its bound authorization, episode, session events, verification, fixed controls, initial state, and skill metrics. Fifteen dedicated offline cases pass, including duplicate consumption, source/metric tampering, missing support arms, and the separate `1.1.0` executable-review boundary.
- `workspace/evals/acquire_cobblestone_baseline_index.json` is 3/3. `workspace/evals/acquire_cobblestone_paired_evaluation.json` is intentionally `retain_advisory` at 0/3 candidate pairs with shadow, advisory, and fallback all verified. Candidate `r1` matched fixed controls and initial state but failed on its first skill action because tied nearest-observed sources were ordered differently by the skill runtime and SP-001 guard; ordinary planning recovered, but the pair is ineligible. It grants no normal runtime, capability, or M4 authority.
- Recovery policy `stone-pickaxe-sp001-paired-evaluation-v2` is a separate window over the pushed runtime fix. It authorizes only fresh candidate replicates `r4/r5/r6`, maps them one-to-one to the three retained baselines, inherits the three successful support arms by exact immutable bindings, and explicitly excludes prior `r1/r2/r3`. The v1 policy/report/harness and failed `r1` remain byte-identical. Its initial report is `retain_advisory` at 0/3 with inherited support 3/3; ten dedicated v2 cases and all fifteen v1 cases pass. No v2 live arm may start before the window commit is pushed.
- Recovery candidate `r4` ran exactly once from pushed authorization `e8d0808`. It machine-verified SP-001 with one Planner call, four successful actions, three exact skill-selected digs, zero action failures/rejects/fallbacks, and terminal `cobblestone:+3`, but evaluation recorded zero skill executions because `StonePickaxeRuntimeAgent` replaced the shared action in place and deleted `skill_context` before attribution. Evidence commit `31b9cc3` freezes all eleven artifacts and the failed v2 report; `r4` is consumed, `r5/r6` are unauthorized, and v2 cannot reach 3/3.
- The bounded offline repair retains only structured internal skill provenance with a `skill_id` across SP-001 guard normalization while leaving guard-controlled `type/parameters`, nearest-source `source_id`, ActionVerifier, ActionController, and machine verification unchanged. The exact r4 regression proves that the shared plan action keeps its context and a successful guarded dig increments skill attribution. Protocol is 34/34, runtime 32/32, v1/v2 evaluation 15/15 and 10/10, all 41 non-live Python scripts and six Node suites with 55 internal cases pass. No live run occurred; the next gate is a fresh non-overlapping window with candidate IDs outside `r1..r6`.
- Recovery policy `stone-pickaxe-sp001-paired-evaluation-v3` is isolated under `workspace/evals/sp001_skill_evaluation_v3`. It binds fix commit `36f03ee7`, the exact v1/v2 policies and reports, both failed run records and payload hashes, and the unchanged v1 support arms. Only fresh candidates `r7/r8/r9` can be authorized, with new pair IDs and explicit exclusion of `r1..r6`. Its initial report is `retain_advisory` at 0/3 with inherited support 3/3, normal runtime/capability/M4 authority false, and prior evidence unmodified. Eleven v3 cases, all prior evaluation suites, 42 non-live Python scripts, six Node suites with 55 internal cases, compilation, and 1210 JSON artifacts pass. No live run occurred; the v3 commit must be pushed before a separate `r7` authorization commit.
- Recovery policy `stone-pickaxe-sp001-paired-evaluation-v4` is isolated under `workspace/evals/sp001_skill_evaluation_v4`. It binds route-scope fix commit `18525025`, exact `agent.py` hash `c7425d93...`, immutable v1-v3 policy/report identities, retained failed records `r1/r4/r7`, and unchanged v1 support arms. Only `r10/r11/r12` were eligible for one-arm authorizations; `r1..r9`, support reruns, retries, and normal runtime fail closed. Candidates `r10` and `r11` each passed exactly once and are frozen at evidence commits `90e4e230` and `ef40eec7`; r12 is a consumed infrastructure-ineligible startup failure. V4 is closed at 2/3 with inherited support 3/3 and 13/13 cases passing.
- Recovery policy `stone-pickaxe-sp001-paired-evaluation-v5` is isolated under `workspace/evals/sp001_skill_evaluation_v5`. It inherits the three immutable v1 support arms, binds the frozen v4 policy/report and r12 infrastructure evidence, excludes `r1..r12`, and permits only fresh candidates `r13/r14/r15`. Candidates/r13 and r14 are frozen at evidence commits `24f28911` and `fe15719a`; candidate/r15 passed exactly once from authorization commit `fb6e434a`. V5 is 3/3 with an approved `promote_executable` gate for new version `1.1.0`; r15 evidence and the later promotion review remain separate commits.

## SP-002 Offline Harness

- Supplemental policy `stone-pickaxe-sp002-controlled-runtime-v1` binds protocol hash `e0722422...`, acquire promotion artifact `d03a4e97...`, runtime-default gate `6a918872...`, and executable version `1.1.0` without changing any source evidence.
- Fixture preparation starts from the immutable SP-001 snapshot and uses normal survival actions only. The sealed target must prove exact `cobblestone:3`, `stick:2`, `stone_pickaxe:0`, survival safety/mobility, and one observed interactive crafting table within 4.5 blocks. Target-result injection and active-episode reset are forbidden.
- The SP-002 episode keeps learned skills off and admits exactly one `craft` action with `item=stone_pickaxe,count=1`. The Bridge starts with `craft-max-attempts=1`, so a transient output fails rather than retrying. Evidence must prove exact material consumption, action verification, table interaction tied to the pre-observation, and a distinct stable observation at least 0.25 seconds later.
- Fixture preparation and live episodes use separate one-time authorizations bound to the fixture bytes, policy bytes, episode ID, and authorization commit parent. Runtime requires clean synchronized `main`; a consumed or reused output path cannot run again.
- Offline validation is 18/18 for the isolated SP-002 harness, 32/32 for the retained stone runtime, 34/34 for the unchanged protocol, 46/46 for repository non-live Python files, and 6/6 for Node suites. The frozen SP-001 runtime/launcher and all v1-v5 policy identities remain exact.
- Four fixture-preparation authorizations were consumed: three failed closed and the fourth sealed a 48-file, 14,962,077-byte fixture with tree `e5201d33a5eb2b9a0d52c0c8be5165363c95e61ef5fc3e88644b3c3d70e2dc0c`.
- Five live SP-002 authorizations were consumed. The first failed root-graph validation before action; the second crafted a real stone pickaxe but exposed stale stick inventory and remained ineligible. Both failures are immutable.
- The final three episodes independently passed. Each made one real schema-valid Planner call, executed one accepted Mineflayer craft with one backend attempt and no retry, completed both task nodes, and machine-proved exact `cobblestone:-3`, `stick:-2`, and `stone_pickaxe:+1` after authoritative table-window refresh.
- Sessions `e6cebfbe-dfe`, `009dafd7-659`, and `102aa710-b41` have distinct episode IDs and session hashes. They passed in 5.453, 5.515, and 6.250 seconds and complete the 3/3 extraction gate without granting capability, M4, executable-skill, or SP-003 authority.

## Phase Status

| Phase | Status |
|---|---|
| 0. Freeze and audit | Complete |
| 1. Protocol and offline harness | Complete; pushed at `8a5cd0c3` |
| 2. SP-001 controlled live convergence | Complete at 3/3; evidence pushed at `6c8c995` |
| 3. SP-001 3/3 gate | Complete; evidence pushed at `6c8c995` |
| 4. Acquire candidate/advisory | Complete; advisory pushed at `822057b` |
| 5. SP-002 controlled live convergence | Complete at 3/3; evidence pushed at `05b6c1fb` |
| 6. Craft candidate/advisory | Complete; retained advisory 1.0.0 plus append-only executable 1.0.1 under approved runtime gate |
| 7. Paired promotion evaluations | Complete at v5 3/3; executable 1.1.0 promotion pushed at `f1926e7f` |
| 8. SP-003 composite acceptance | Phase 144 offline repair is verified after thirty-three consumed authorizations; baseline 0/1 and candidates 0/3; repair commit push and one bounded no-Minecraft step-up provider probe are next |

## Frozen Baseline

- Freeze commit: `e4e06980caebaa79528b7bc187db0c8422e4f5c8`
- Frozen branches: `main` only
- Existing executable skills: `learned:gather_wood@1.0.1`, `learned:craft_crafting_table@1.0.1`, `learned:craft_wooden_pickaxe@1.0.2`
- Retained quarantined wooden-pickaxe version: `1.0.1`
- Probe 21/22/23 tracked run artifacts: 26 SHA-256 entries in `workspace/evals/stone_pickaxe_failure_ledger.json`

## Stop Boundary

The retained fixture blockers, controlled SP-001 failures, first two SP-002 source failures, v1 `shadow-1` failure, and all SP-003 runs remain immutable. Three eligible SP-001 successes and three eligible SP-002 successes establish both extraction gates; v5 remains frozen at 3/3, and the append-only acquire 1.1.0 and craft 1.0.1 executable promotions are complete. Do not retry consumed arms or Phases 140-143; reuse prior IDs; alter the frozen base protocol or retained evidence; run SP-003 before the Phase 144 repair and its bounded provider-probe evidence are each pushed; authorize a candidate before a passing baseline; run full BM-012; run Probe 24; or begin iron mining.
