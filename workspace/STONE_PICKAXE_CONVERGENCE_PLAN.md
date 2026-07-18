# Stone Pickaxe Skill Convergence Plan

## Claim Boundary

This project isolates two bounded Minecraft capabilities:

1. `SP-001`: acquire three cobblestone from observed allowlisted sources.
2. `SP-002`: craft one exact stone pickaxe from fixed materials at an observed crafting table.

`SP-003` composes them only after both independent skills pass their existing lifecycle gates. This project does not run or complete BM-012, does not establish iron acquisition, and does not change canonical M1-M4 capability status.

## Current Gate

| Microbenchmark | Eligible live successes | Extraction gate | Current learned skill |
|---|---:|---:|---|
| SP-001 Acquire Cobblestone | 3 | 3 | `learned:acquire_cobblestone@1.0.0` advisory only |
| SP-002 Craft Stone Pickaxe | 0 | 3 | `learned:craft_stone_pickaxe` not created |
| SP-003 Composite Chain | 0 | Both skills executable, then 3 candidate successes | Locked |

Current phase: **Phase 7 paired evaluation recovery with three immutable baseline arms, all three support arms verified, candidates `r1`, `r4`, and `r7` retained failed, v4 closed at 2/3 after `r10` and `r11` passed and r12 failed before bot readiness, and isolated v5 at 1/3 after `r13` passed; `learned:acquire_cobblestone@1.0.0` remains advisory and non-executable**.

Current authorization: **exactly one `candidate/r14` episode after this separate ledger commit is pushed**. Replicates `r1..r13` are excluded or consumed and cannot re-enter v5; r12 is infrastructure-ineligible, r13 passed from authorization commit `02269113`, and its evidence is pushed at `24f28911`. R15 remains unauthorized. Another fixture session, support reruns, retries, SP-002/SP-003, Probe 24, full BM-012, and iron mining remain locked.

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

The composite task starts with `wooden_pickaxe:1`, `stick:2`, a nearby table, no cobblestone, and no stone pickaxe. The TaskSystem path is fixed as `SP-001 -> SP-002`.

Success requires both component machine verifiers, acquisition completion releasing the craft dependency, exactly three source removals, no repeated wooden-pickaxe or crafting-table craft, no iron-mining action, and separate local attribution for each learned skill. Full BM-012 terminal criteria are forbidden.

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

Implementation: `src/singularity/evaluation/stone_pickaxe_protocol.py`

Tests: `tests/test_stone_pickaxe_protocol.py`

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
- `Agent.run_goal` can now bind Planner and ActionController to one supplied absolute deadline and suppress every action beyond a supplied total budget. Existing callers retain their previous behavior when those optional bounds are absent.
- Offline status: 34/34 protocol cases and 32/32 runtime cases pass. The repository-wide non-live regression gate is rerun before each evidence or offline-fix commit.
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
- Recovery policy `stone-pickaxe-sp001-paired-evaluation-v5` is isolated under `workspace/evals/sp001_skill_evaluation_v5`. It inherits the three immutable v1 support arms, binds the frozen v4 policy/report and r12 infrastructure evidence, excludes `r1..r12`, and permits only fresh candidates `r13/r14/r15`. Candidate/r13 passed exactly once from authorization commit `02269113`; evidence commit `24f28911` advances v5 to 1/3. This separate ledger commit authorizes exactly one fresh `candidate/r14` run after push.

## Phase Status

| Phase | Status |
|---|---|
| 0. Freeze and audit | Complete |
| 1. Protocol and offline harness | Complete; pushed at `8a5cd0c3` |
| 2. SP-001 controlled live convergence | Complete at 3/3; evidence pushed at `6c8c995` |
| 3. SP-001 3/3 gate | Complete; evidence pushed at `6c8c995` |
| 4. Acquire candidate/advisory | Complete; advisory pushed at `822057b` |
| 5. SP-002 controlled live convergence | Not started |
| 6. Craft candidate/advisory | Not started |
| 7. Paired promotion evaluations | In progress; v1 `r1`, v2 `r4`, and v3 `r7` are consumed failures, v4 is closed at 2/3, and v5 is 1/3 after `r13` passed |
| 8. SP-003 composite acceptance | Locked |

## Frozen Baseline

- Freeze commit: `e4e06980caebaa79528b7bc187db0c8422e4f5c8`
- Frozen branches: `main` only
- Existing executable skills: `learned:gather_wood@1.0.1`, `learned:craft_crafting_table@1.0.1`, `learned:craft_wooden_pickaxe@1.0.2`
- Retained quarantined wooden-pickaxe version: `1.0.1`
- Probe 21/22/23 tracked run artifacts: 26 SHA-256 entries in `workspace/evals/stone_pickaxe_failure_ledger.json`

## Stop Boundary

The retained fixture blockers plus all three controlled SP-001 behavioral failures are reproduced and fixed; the two provider TLS EOF traces are retained as zero-action fail-closed failures. All source sessions remain immutable. The fixture snapshot still passes independent identity audit, and three eligible SP-001 successes establish 3/3. The acquire skill is advisory only. Shadow, advisory, and fallback each ran exactly once from pushed predecessors and passed. Candidates `r1`, `r4`, and `r7` each ran exactly once and remain immutable ineligible failures; candidates `r10` and `r11` passed all checks, while r12 is a consumed infrastructure-ineligible startup failure. Candidate/r13 passed and is frozen at evidence commit `24f28911`, advancing v5 to 1/3. Push this single-arm authorization, run exactly one `candidate/r14` experiment, then stop for immutable evidence review. Do not retry consumed candidates, run excluded IDs `r1..r13`, reuse prior pair IDs, rerun support arms, batch candidates, run r15, run SP-002/SP-003 before their gates unlock, run full BM-012, run Probe 24, or begin iron mining.
