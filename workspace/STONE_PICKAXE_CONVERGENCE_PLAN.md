# Stone Pickaxe Skill Convergence Plan

## Claim Boundary

This project isolates two bounded Minecraft capabilities:

1. `SP-001`: acquire three cobblestone from observed allowlisted sources.
2. `SP-002`: craft one exact stone pickaxe from fixed materials at an observed crafting table.

`SP-003` composes them only after both independent skills pass their existing lifecycle gates. This project does not run or complete BM-012, does not establish iron acquisition, and does not change canonical M1-M4 capability status.

## Current Gate

| Microbenchmark | Eligible live successes | Extraction gate | Current learned skill |
|---|---:|---:|---|
| SP-001 Acquire Cobblestone | 0 | 3 | `learned:acquire_cobblestone` not created |
| SP-002 Craft Stone Pickaxe | 0 | 3 | `learned:craft_stone_pickaxe` not created |
| SP-003 Composite Chain | 0 | Both skills executable, then 3 candidate successes | Locked |

Current phase: **Phase 2 after one retained SP-001 failure; the redundant-equip machine-state disconnect is reproduced and fixed offline, while SP-001 remains 0/3**.

Current authorization: **one conditional SP-001 only, pending retained-failure/offline-fix commit push**. The first SP-001 authorization was consumed by one failed episode and no retry ran. The standing single-episode authorization permits one new experiment only after its evidence, root-cause repair, and full offline gate are committed and pushed. Automatic retry, concurrent or batch SP-001, another fixture session, SP-002/SP-003, Probe 24, full BM-012, and iron mining remain forbidden.

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
- Offline status: 30/30 protocol cases and 25/25 runtime cases pass. The repository-wide non-live regression gate is rerun before each offline-fix commit.
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
- All four failed machine audits remain non-counting and immutable; the fifth successful preparation is also non-capability evidence, and the failed SP-001 grants no skill or capability credit. Twenty preparation evidence files, ten SP-001 evidence files, and the tracked fixture manifest are hash-bound in `workspace/evals/stone_pickaxe_failure_ledger.json`; the protocol JSON and hash are unchanged.

## Phase Status

| Phase | Status |
|---|---|
| 0. Freeze and audit | Complete |
| 1. Protocol and offline harness | Complete; pushed at `8a5cd0c3` |
| 2. SP-001 controlled live convergence | First episode failed; redundant-equip repair verified offline; one conditional episode after fix push |
| 3. SP-001 3/3 gate | 0/3 |
| 4. Acquire candidate/advisory | Not started |
| 5. SP-002 controlled live convergence | Not started |
| 6. Craft candidate/advisory | Not started |
| 7. Paired promotion evaluations | Not started |
| 8. SP-003 composite acceptance | Locked |

## Frozen Baseline

- Freeze commit: `e4e06980caebaa79528b7bc187db0c8422e4f5c8`
- Frozen branches: `main` only
- Existing executable skills: `learned:gather_wood@1.0.1`, `learned:craft_crafting_table@1.0.1`, `learned:craft_wooden_pickaxe@1.0.2`
- Retained quarantined wooden-pickaxe version: `1.0.1`
- Probe 21/22/23 tracked run artifacts: 26 SHA-256 entries in `workspace/evals/stone_pickaxe_failure_ledger.json`

## Stop Boundary

The retained fixture blockers plus `sp001_redundant_equip_machine_state_disconnect` are reproduced and fixed offline; all source sessions remain immutable. The fixture snapshot still passes independent identity audit. No automatic batch resume is allowed. After the SP-001 failure evidence and redundant-equip repair are pushed, run at most one conditional SP-001 episode, then stop and audit. Do not create either learned skill, promote a candidate, run SP-002/SP-003, run full BM-012, run Probe 24, or begin iron mining.
