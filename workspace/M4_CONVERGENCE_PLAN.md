# M4 Autonomous Survival Convergence Plan

## Current Gate

- Protocol: `m4-fixed-v1`
- Protocol SHA-256: `378689bc96d28580b2debcccb12efb4f955de38dd031e681ace529d4f75d157d`
- Current target: BM-012 Get 8 iron resources
- Current-target eligible successes: 0/3
- Completed target: BM-011 Survive the first night, `repeat_verified` at 3/3
- M4 canonical status: `failing`
- M1, M2, and M3 regression baseline: `repeat_verified`

BM-011 is closed at 3/3 independently eligible fresh live successes. BM-012 Probes 1 through 21 remain ineligible at 0/3. Probe 21 live-activated the exact ready-task binding gate with 61 fail-closed reports and zero improper allow decisions. Broader progression recovered through a crafting table and wooden pickaxe, but readiness recovery then machine-completed an inventory-family task without closing or redirecting its exact-item root. The bounded root-completion fix now passes offline under `m4-readiness-recovery-inventory-family-root-completion-v1`; exactly one fresh Probe 22 is authorized only after this gate commit is pushed. BM-013/BM-014 remain sequentially locked.

## Scope

The protocol is independent from M1/M2 task semantics. It reuses the pinned Paper runtime, bridge, machine evidence shape, content hashing, and anti-replay controls. It does not inherit peaceful difficulty, prepared inventory, terminal fixtures, or scripted intermediate goals.

The M4 baseline keeps learned executable skills off. Built-in primitive actions and the LLM planner remain available. Strategic root skills cannot bypass GoalGenerator, Curriculum, or ActionVerifier, and quarantined skills are forbidden.

## Gate Ladder

| Gate | Requirement | State |
|---|---|---|
| G0 | Fixed protocol, fresh episode, natural time, one absolute deadline, independent eligibility | passed_probe_18_zero_death_acceptance |
| G1 | Deterministic survival-goal priority cases | passed |
| G2 | One live preparation episode with machine-visible progress | passed_probe_6 |
| G3 | Machine-checkable shelter or approved natural safe-state verification | passed_live_probe_18_direct_commit |
| G4 | Hostile, health, hunger, dusk, and night interrupt continuity | passed_live_probe_18_safe_state |
| G5 | First eligible survival-to-dawn episode | passed_probes_15_17_18 |
| G6 | Three independent fresh eligible episodes | passed_probe_18_3_of_3 |
| BM012-G0 | Task-bound reset, autonomous goal chain, machine resource provenance, deadline, independent eligibility | probe_22_authorized_after_readiness_recovery_gate_commit_push |

G0 passes both sides of live validation. Probes 15, 17, and 18 exercised zero-transition acceptance and each reached an independently eligible terminal state. Probe 16 exercised rejection: six Mineflayer death/respawn transitions matched six Paper death messages, no terminal event was emitted after later health-20 respawns and a verified shelter, missing lifecycle evidence after bridge loss failed closed, and the independent gate also rejected a 0.031-second duration overrun plus the late Planner return without allowing a post-deadline action.

G1 passed offline validation. GoalGenerator and Curriculum preserve the fixed order of immediate threat, critical health, hunger/food, shelter preparation, night safety maintenance, and tool/resource progression. Shelter safety requires machine-state verification, and every `auto_goal` event carries source, reason, priority, and priority class.

G2 passed in Probe 6. The Agent gained `oak_log:1` and `dark_oak_sapling:1` before dusk at world time 9952 under the fixed live protocol, with all 32 real Planner calls schema-valid and the absolute deadline intact.

G3 passed offline validation. `m4-sealed-cell-shelter-verifier-v1` consumes a complete 36-coordinate Mineflayer snapshot and accepts only a solid floor, two passable interior cells, four two-block-high full-block wall columns, a full-block roof, no hostile inside, complete coordinate evidence, and all nine structural positions attributed to successful placements in the current episode. No natural safe-point strategy is approved in this baseline.

G4 passed strict offline integration and live safe-state grounding. RuntimeSupervisor applies the fixed hostile, critical-health, hunger, dusk-shelter, and night-safety order; Observer preserves hostile IDs and positions for grounded attack or flee actions. In Probe 18, a zombie 4.8 blocks outside the complete pinned shelter produced one `m4_hostile_safe_state_grounding` event: direct reachability was blocked, no hostile was inside, the outward `move_to` was suppressed, and night maintenance continued through dawn. Agent records one trigger per actionable condition, suspends rather than fails a non-emergency root, keeps its task frontier active, allows the aligned survival goal to act, emits a matching recovery when the condition clears, and never holds two root goals concurrently.

## Current Hypothesis

The frozen-code replication hypothesis passed in Probe 18. The episode completed with no first unrecovered transition, zero death/respawn transitions, a preserved 9/9 shelter, natural dawn, all 66 independent checks passing, and 505.000 seconds remaining before the absolute deadline. This is the third distinct eligible BM-011 episode, so BM-011 is `repeat_verified` at 3/3.

Probe 18 also closed two live-observation gaps without changing the protocol. Planner call `llm-731730e6669b4683` received one `APIConnectionError -> ConnectError -> ConnectError -> SSLEOFError`; the same dawn-maintenance goal was preserved and the next-cycle real/schema-valid call `llm-52111d9e3d3a455c` resumed successful waits. Later, a zombie 4.8 blocks outside the verified cell triggered safe-state grounding, and the outward move was suppressed while the shelter remained valid.

The `bm012_protocol_and_machine_evidence_preflight` hypothesis passed offline and the frozen gate ran exactly once in Probe 1. The base protocol remained `378689bc96d28580b2debcccb12efb4f955de38dd031e681ace529d4f75d157d`; the BM-012 task contract remained `389bafa8651cd6d46b259a708e1f82144615d1a8ae90aa840b00c3751404b45d`. Preflight, fresh time-0 reset, exact 600-second deadline, task binding, zero-death lifecycle, and content hashes all passed.

The new earliest unrecovered transition is `goal_verifier_purpose_phrase_semantic_conflation`. Curriculum selected `Gather 6 oak logs for tools and shelter`, a valid prerequisite goal. Action event 208 at monotonic 39289.093 / cycle 9 successfully raised machine inventory from `oak_log:5` to `oak_log:6`; event 212 then completed thirteen inventory-grounded gather tasks. GoalVerifier nevertheless interpreted the purpose phrase `for tools and shelter` as a conjunctive shelter requirement, returning machine evidence `inventory has 6/6 oak_log` but missing `no shelter flag, structure, or sufficient placed-block evidence`, so the fulfilled root remained active.

The immediate next Planner call at event 215 treated the resource objective as satisfied and returned no executable action, which the M4 schema correctly rejected as `planning_actions_missing`. Later shelter construction, the event-711 40-cycle root failure, twenty-one repeated `Craft oak_planks from logs` roots, and `max_goals_or_stopped` are downstream cascade. The next hypothesis is limited to GoalVerifier intent parsing for resource goals whose shelter/tool text is a purpose phrase. Probe 1 consumed this round's only live authorization; no fix or rerun occurs in this round.

The bounded `goal_verifier_purpose_phrase_semantic_conflation` fix passes its offline gate. GoalVerifier now treats `shelter` or `nightfall` as non-binding only when every such mention occurs inside a `for`, `to`, or `so that` purpose clause attached to a grounded inventory objective. The exact Probe 1 goal completes from `oak_log:6`; `oak_log:5` remains incomplete; explicit `and build shelter`, semicolon/`then` follow-ups, and direct shelter/nightfall goals still require world evidence. Agent completion integration records `deterministic_evidence_satisfied`. The base protocol and BM-012 task contract hashes are unchanged, and exactly one fresh Probe 2 is authorized after the gate commit.

Probe 2 live-validates that fix. Goal verification event 177 completed `Gather 6 oak logs for tools and shelter` in eight cycles with `inventory:oak_log`, `anchor:manual`, and `intent:shelter_purpose_phrase`; the missing shelter rule did not recur. The Agent then crafted a machine-observed crafting table, planks, and sticks.

The new earliest unrecovered transition is `curriculum_crafting_station_world_readiness_grounding`. Curriculum event 308 at monotonic 41502.359 selected `Craft wooden pickaxe` with score 59 because `crafting_table:1` existed in inventory, while observation event 313 had zero nearby placed crafting tables. Planner event 321 reasoned that an inventory table was sufficient and omitted placement; event 369 repeated that assumption. Canonical craft action event 395 then failed with underlying bridge error `No recipe for wooden_pickaxe`, `crafting_table_found=false`, and unchanged inventory despite six planks and four sticks. Thirteen later `place(block=crafting_table)` alias rejections, the event-1121 max-cycle failure, dusk progression, and the 0.031-second Agent deadline overrun are downstream. Probe 2 consumed the round's only authorization; no code fix or second episode occurs in this round.

The bounded `curriculum_crafting_station_world_readiness_grounding` fix passes offline. GoalGenerator and Curriculum now distinguish an inventory table from a nearby placed station, select a placement goal before either wooden- or stone-pickaxe crafting when the station is still in inventory, and preserve survival preemption. Strict-M4 Planner grounding canonicalizes Probe 2's `place(block=crafting_table,x,y,z)` into executable `place(item=crafting_table,x,y,z)` while rejecting missing coordinates, conflicts, and unknown aliases. GoalVerifier accepts placement only from a nearby machine-observed `crafting_table`, including the terminal state of `Craft and place...` after the inventory item is consumed. The exact event-308 observation replays to placement first and to wooden-pickaxe crafting only after the table is nearby. Protocol and task-contract hashes are unchanged; the gate's one Probe 3 authorization has now been consumed.

Probe 3 reaches that placement boundary but does not execute it. Planner event 510 / call `llm-d1e4384adc0045e6` emitted canonical `place(item=crafting_table,x=106,y=135,z=-29)` with passing action-parameter grounding, so the Probe 2 alias rejection did not recur. The same accepted plan also created a dependent task whose success criterion was `inventory.oak_planks=">=8"` and whose precondition was `inventory.oak_log=">=1"`. At event 525 / monotonic 44047.687 / global cycle 25, inventory-only machine-state reconciliation compared an observed integer count to the string criterion and raised `'>=' not supported between instances of 'int' and 'str'`. The exception repeated 280 times through cycle 304; seven `Place crafting_table` roots each exhausted 40 cycles without a Planner call or action. The earliest failure layer is now `planner_subtask_numeric_criteria_type_grounding`. No code fix or second episode occurs in this round.

The bounded `planner_subtask_numeric_criteria_type_grounding` fix now passes offline. Strict-M4 Planner traverses only `subtasks[*].preconditions.inventory` and `subtasks[*].success_criteria.inventory`, converts exact positive `>=N` strings to the equivalent integer because inventory criteria already mean at least N, and records each conversion in `m4_subtask_numeric_criteria_grounding`. Booleans, nonpositive integers, floats, bare numeric strings, alternate comparators, prose counts, non-object inventory criteria, and other non-equivalent values reject the plan before task creation. TaskSystem independently treats malformed required counts as unsatisfied and reports invalid preconditions instead of throwing or treating them as zero. The exact Probe 3 plan replays to `oak_planks:8` and `oak_log:1`; the base protocol and BM-012 task contract hashes are unchanged. Its one fresh Probe 4 authorization was consumed by the live result below.

Probe 4 live-validates the integer-only path but does not exercise alias normalization: 31/31 real Planner calls were schema-valid, all 31 numeric-grounding reports passed, every observed requirement was integer `6`, normalization count was zero, and no runtime error occurred. The initial root gathered `oak_log:4` plus `dark_oak_log:2`; GoalVerifier event 170 accepted the six-member log family. TaskSystem's exact `inventory.oak_log=6` reconciliation did not close the planner frontier: readiness event 160 reported seven ready tasks, event 167 selected `Find and gather 6 oak logs`, and event 175 began 23 consecutive `ready_task_selected` roots. All completed in one cycle under GoalVerifier family semantics, no action executed after event 155, and nine tasks remained accepted when the 24-goal budget ended. The earliest failure layer is now `m4_task_inventory_family_reconciliation_grounding`. No code fix or second episode occurs in this round.

The bounded `m4_task_inventory_family_reconciliation_grounding` fix passes offline. Strict-M4 task reconciliation projects the existing pinned `GoalVerifier.LOG_ITEMS` family into a copied inventory state under canonical `oak_log`, records `m4-task-inventory-family-grounding-v1` evidence, and never mutates the source observation. It completes state-satisfied inventory tasks during the active cycle and once more before root selection, so the final task created by the last accepted plan cannot consume another goal slot. Completed task transitions are flushed at the reconciliation point rather than the next Planner acceptance. Replaying event 157 completes all seven event-160 stale tasks, clears a newly created post-plan task before selection, and selects `Craft crafting table` from the actual GoalGenerator/Curriculum combination. A five-log family remains incomplete, urgent survival fallback still preempts tasks, non-inventory claims remain excluded, and non-M4 profiles are unchanged. The protocol and BM-012 task-contract hashes remain fixed; its one fresh Probe 5 authorization was consumed by the live result below.

Probe 5 live-validates both reconciliation boundaries. Event 192 completed seven stale gather tasks before the next root, event 244 completed two crafting-table inventory tasks, and event 535 activated `m4-task-inventory-family-grounding-v1` for `oak_log:5 + birch_log:1`, projected the canonical count from five to six, and completed eight more tasks. No repeated fulfilled wood root recurred, and progression reached `Craft crafting table` and then `Place crafting table for tool progression`.

The new earliest failure layer is `planner_place_success_criteria_grounding`. Planner calls `llm-747a78336a3e4e79` and `llm-4efc1e7d2e9b4aef` each contained one canonical place action with passing action-parameter grounding, but strict-M4 rejected the envelope as `subtask[0]:success_criteria_inventory_count_invalid:crafting_table`. The canonical trace retains response hashes and byte counts rather than raw response bodies, so it proves a noncanonical inventory count but does not support a stronger claim about its exact raw value. Both rejected plans produced `empty_plan`, no place action executed, the crafting table remained in inventory, and the iron progression chain never started. Later pathfinding, task-deadline interrupts, dusk shelter work, and the final deadline-bound timeout are downstream. Probe 5 consumed this round's sole live authorization; no fix or second episode occurs in this round.

The bounded `planner_place_success_criteria_grounding` fix now passes offline. Strict-M4 Planner runs `m4-place-success-criteria-grounding-v1` after action-parameter grounding and before numeric-criteria validation. It rewrites only a placement subtask's inventory criterion for the exact item that the immediate canonical place action and explicit root goal both request, replacing that non-proof with `nearby_block_present` machine state. The report records source-value, original-subtasks, and grounded-subtasks hashes without retaining raw count text. Goal mismatch, missing placement intent, conflicting nearby-block criteria, a different action item, and malformed preconditions remain rejected; unrelated inventory criteria and non-M4 protocols are unchanged. The Probe 5 failure class creates one executable place action, TaskSystem completes from a post-action nearby `crafting_table`, and the GoalVerifier's existing `world:nearby_crafting_table` rule remains the root authority. Probe 6 consumed this gate's one live authorization.

Probe 6 live-validates the prompt path without exercising the normalization branch. Planner call event 277 / call `llm-28be82216c5b42ed` emitted `success_criteria.nearby_block_present=crafting_table` directly; all 129 real responses were schema-valid, all 129 placement-grounding reports passed, and zero subtasks required rewriting. The prior numeric placement-criterion rejection did not recur.

The new earliest failure layer is `place_backend_requested_item_equip_grounding`. Observation event 273 showed `crafting_table:1` in inventory while selected slot 0 held `dark_oak_sapling:1`. The canonical action was accepted at event 292, but action event 298 called generic `createPlaceHandler` without selecting or equipping the requested item; Mineflayer placed the held sapling at `(104,136,-31)`, the requested-item postcondition failed, and event 302 showed the sapling consumed while the crafting table remained in inventory. Thirty later place actions failed `must be holding an item to place`. Task-deadline interrupts, the later shelter timeout and bridge disconnect, missing terminal lifecycle evidence, and the deadline rejection are downstream. Probe 6 was this round's only live episode; no code fix or second run occurs in the round.

The bounded `place_backend_requested_item_equip_grounding` fix now passes offline. Generic `createPlaceHandler` requires a nonempty requested item, finds the exact positive inventory stack, equips that stack to `hand`, confirms the actual held item from Mineflayer state, and only then calls `placeBlock`. A missing stack, equip exception, or held-item mismatch returns fail-closed evidence before any block mutation. Success requires the target to change to the exact requested block and records `m4-place-requested-item-equip-v1`, the equipped item, and requested-item confirmation. The exact Probe 6 state with `crafting_table:1` in inventory and `dark_oak_sapling` held now performs zero place calls and zero target mutations when equip is ineffective. Protocol, BM-012 task contract, Planner, ActionVerifier, M1/M2 fixed protocols, deadlines, and success thresholds are unchanged. Exactly one fresh Probe 7 is authorized after this gate commit is pushed.

Probe 7 live-validates the requested-item equip gate on all 17 place actions: each result records `item=crafting_table`, `equipped_item=crafting_table`, `requested_item_equipped=true`, and policy `m4-place-requested-item-equip-v1`. The prior sapling placement and empty-hand cascade did not recur.

The new earliest failure layer is `planner_place_target_occupancy_grounding`. Planner call event 245 / call `llm-433910d52edd4327` and plan event 247 selected dirt reference `(93,134,-38)` but did not check its placement target `(93,135,-38)`, even though observations showed `dark_oak_log` there. ActionVerifier event 273 accepted the place from inventory evidence alone; action event 278 then timed out waiting for `blockUpdate`. The next 16 actions targeted `(93,135,-36)`, which each immediately preceding machine observation showed as `grass_block`, and all timed out identically. Later task deadlines, the successful 9/9 bounded shelter, and the post-deadline wait completion are downstream. Probe 7 was this round's sole live episode; no code fix or second run occurs in the round.

The bounded `planner_place_target_occupancy_grounding` fix now passes offline under `m4-place-target-occupancy-v1`. The strict-M4 prompt defines the actual placement target as `floor(x),floor(y)+1,floor(z)`. ActionVerifier checks exact-position machine observations, rejects observed solid targets at zero execution duration, and requests a next-cycle replan naming the occupied block and required air-or-replaceable state. The generic Mineflayer place bridge independently reads the exact target and rejects a solid occupant before equip, `placeBlock`, or mutation. The exact Probe 7 `dark_oak_log` and `grass_block` states fail closed; replaceable, target-absent, non-M4 ActionVerifier, and successful air-target controls pass. The protocol and BM-012 task-contract hashes, deadlines, and success thresholds are unchanged. Full regression passes 709 Python tests and six Node suites with 38 internal cases. No live episode ran in this offline round; exactly one fresh Probe 8 is authorized after this gate commit is pushed.

Probe 8 live-validates that gate. ActionVerifier event 243 rejected target `(93,135,-38)` because exact machine state showed `dark_oak_log`, action event 248 recorded zero execution duration, and the verifier requested a target-aware replan. Plan event 259 selected reference `(92,134,-37)`; event 271 accepted its air target and action event 278 placed `crafting_table` at `(92,135,-37)` in 516 ms. The Probe 7 occupied-target timeout did not recur.

The new earliest failure layer is `m4_task_world_state_reconciliation_grounding`. Replan call `llm-f8f98d5795a541e6` created task `2f1081b4` at event 258 and accepted it at event 260 with `success_criteria.nearby_block_present=crafting_table`. The successful placement completed sibling task `e0d4ebe1` at event 276 and parent goal `Place crafting table for tool progression` at event 282, while post-action machine state proved the same criterion for `2f1081b4`. Strict-M4 pre-goal reconciliation allowed only `inventory`, left `2f1081b4` accepted, and event 286 reselected the already-satisfied task as a root at monotonic 62264.359.

That stale root was verified complete at event 307 before executing its plan, but the plan had already accepted four descendants. `Dig dirt to clear space` was selected at event 384; two such roots consumed 80 cycles, including 27 successful dirt digs, without one root GoalVerifier event. The first failed at event 1037 and the second was interrupted by dusk at event 1698. Forty-nine task-deadline interrupts, shelter work, the terminal observation fallback, and the deadline-bound wait are downstream. Probe 8 was this round's only live episode; no code fix or second run occurs in the round.

The bounded offline fix now passes. Strict-M4 pre-goal reconciliation accepts only the explicit `inventory` and `nearby_block_present` criteria under `m4-task-world-state-reconciliation-v1`; the latter reads only `observation.nearby_blocks`. The exact Probe 8 task `2f1081b4`, root plan `root-c60df46942bc4cd1`, Planner call `llm-f8f98d5795a541e6`, and event-278 machine state replay to completion before ready-task selection, so fallback progression is selected instead of the stale root. Inventory, entity, landmark, absent-block, empty-list, object-valued, unmet, and non-M4 pre-goal controls fail closed. Full regression passes 711 Python tests and six Node suites with 38 internal cases. No live episode ran in this offline round; exactly one fresh Probe 9 is authorized after this commit is pushed.

Probe 9 exercises the policy on live nearby-block state without reaching the exact crafting-table boundary. All six reconciliation events carry `m4-task-world-state-reconciliation-v1`; event 1797 completes five accepted shelter tasks whose `nearby_block_present=oak_planks` criteria are satisfied by `observation.nearby_blocks`, and no satisfied world-state task is later selected as a root. The exact Probe 8 crafting-table transition remains live-unexercised because progression stopped earlier.

The new earliest failure layer is `m4_planner_schema_rejection_recovery_scope`. At inventory `oak_log:2`, world time 1059, real continuation call event 115 / `llm-3bbb8772f5f0473e` returned three subtasks and six inventory requirements. Strict grounding correctly rejected `subtask[2]:preconditions_inventory_count_invalid:oak_log`; the raw source value is not retained, and zero equivalent numeric normalizations applied. The Agent recovery path recognizes transport errors and `planning_actions_missing`, but not this typed schema rejection. Error plan event 116 therefore became `empty_plan` at event 120 / cycle 6 and permanently failed the root at event 122 without executing an action from the invalid response. Later ready-task roots, repeated stale-coordinate digs, 56 distinct task-deadline recoveries, dusk shelter work, and the terminal deadline are downstream. Probe 9 was the round's only live episode; no code fix or second run occurs in this round.

The bounded offline fix now passes under `m4-typed-schema-recovery-v1`. Recovery is restricted to a real `m4-fixed-v1` Planner call whose rejected plan has empty task/action output and whose complete issue set comes from typed subtask inventory-count grounding. Each autonomous goal gets at most one next-cycle replan; the Agent hashes its nonterminal task frontier at rejection and verifies the same goal and frontier before reconciliation or the next Planner call. The exact Probe 9 shape replays three subtasks, six requirements, the one oak-log issue, zero normalization, zero invalid task acceptance, and zero action execution into a `replan` on the same root. A second typed rejection emits one exhausted event and reaches the existing `empty_plan`; frontier drift, malformed metrics, untrusted calls, leaked actions, mixed schema issues, deadline exhaustion, and M2 use reject recovery. Full regression passes 714 Python tests and six Node suites with 38 internal assertions. No live episode ran in this offline round; exactly one fresh Probe 10 is authorized after this commit is pushed.

Probe 10 did not reproduce that rejection. All 50 real Planner calls passed schema validation, no typed inventory-count issue appeared, and zero `m4_planner_output_recovery` events were emitted. The offline gate remains valid but its runtime branch was not exercised.

The new earliest failure layer is `planner_subtask_opportunity_trigger_type_grounding`. Real call event 262 / `llm-0cd847107eb747db` returned a three-subtask plan whose `Mine coal ore` task used an object-valued `opportunity_triggers` item. The envelope reported no issue, task event 265 accepted the malformed task, and plan event 266 exposed the object. The same class appeared in nine plans. Bounded planning-context readiness calls warned and returned empty context, but the direct readiness call in `_select_autonomous_goal` after event 1185 reached `TaskSystem._opportunity_bonus`, called `.lower()` on the object, and aborted the runner. Repeated wooden-pickaxe craft failures, 21 task-deadline recoveries, and the missing terminal resource event are downstream. Probe 10 was the only live episode in this round; no code fix or second run occurs here.

The bounded offline fix now passes under `m4-subtask-opportunity-trigger-type-grounding-v1`. Strict M4 validates every explicit `subtasks[*].opportunity_triggers` field before task creation, accepts only arrays of non-empty strings, and emits deterministic element-indexed issues for the Probe 10 object, non-array containers, nulls, numbers, dictionaries, and empty strings. A rejected response exposes zero subtasks and actions and creates zero tasks. Valid string lists remain byte-for-byte unchanged, and TaskSystem defensively skips legacy malformed containers and non-string hints while preserving valid causal scoring. The prompt now forbids object, coordinate, numeric, and null trigger values. Full regression passes 716 Python tests and six Node suites with 38 internal assertions; no protocol, task contract, deadline, verifier, recovery whitelist, or success threshold changed. No live episode ran in this offline round; exactly one fresh BM-012 Probe 11 is authorized after this commit is pushed.

Probe 11 live-validates the accepted path: all 110 real Planner responses were schema-valid, 110/110 opportunity-trigger reports passed, and all 117 trigger values were valid strings. No malformed trigger entered TaskSystem, no `.lower()` exception occurred, and the prior failure did not recur. The strict rejection branch remains live-unexercised.

The new earliest failure layer is `dig_expected_drop_pickup_postcondition`. Action event 81 / monotonic 74061.859 / cycle 4 removed `oak_log` at `(93,139,-36)` but returned success with `pickup_observed=false`, empty pickup delta, and `pickup_collection.detected=false, attempted=false`; inventory stayed `dark_oak_log:1`. Action event 152 removed another oak log and detected its drop, but exact-position pickup navigation timed out after 6000 ms and inventory again did not change. The runner's event-127 move tolerance miss was followed by that successful block removal and is not the earliest blocker. Event 176's action-deadline timeout, loss of lifecycle/machine observations, 32 later bridge-disconnected actions, and the final 0.015-second evidence overrun are downstream.

The next hypothesis is bounded to the Mineflayer dig pickup/postcondition path: an expected-drop resource dig must not report successful acquisition until the drop reaches inventory, and collection must use a deadline-bounded reachable-proximity strategy with fail-closed evidence. No code changes or second live run occur in Probe 11's round.

The bounded offline fix passes under `m4-expected-drop-pickup-postcondition-v1`. Only `m4-fixed-v1` asks the bridge to enforce the postcondition. The exact event-81 fixture still removes the oak log but now returns `success=false`, `expected block drop was not acquired`, and a failed machine-readable postcondition when inventory remains `dark_oak_log:1`. Strict M4 polls up to 1.5 seconds for a delayed expected drop, approaches it with a one-block `GoalNear`, retains the existing 6000 ms navigation limit, and accepts success only after the expected inventory delta is observed. A delayed oak drop reaches inventory in the positive control; the same missing-drop fixture without the strict flag preserves the fixed M1/M2 success response. Full regression passes 718 Python tests and six Node suites with 40 internal assertions.

Probe 12 live-validates the outer postcondition and recovery path. All five strict digs emitted the policy; three acquired the expected drop, two correctly returned failure, zero false-positive successes occurred, and the event-72 failure recovered through successful digs at events 97 and 116. The new earliest failure layer is `pickup_collection_pathfinder_completion_grounding`: event 169 removed the exact oak log and detected its entity, but the inner collector reported pathfinder success at 2.091618 blocks against the 1-block goal with no inventory delta. The outer strict-M4 postcondition remained fail-closed. A later 60-second movement deadline and bridge disconnect are downstream. Probe 12 consumed the only live authorization, and no further live episode may run before an offline completion-grounding gate passes and is pushed.

The bounded offline fix now passes under `m4-pickup-collection-completion-grounding-v1`. Strict M4 records direct `GoalNear` resolution separately from measured completion, accepts only a final distance inside the one-block acquisition envelope or the expected inventory delta, and performs at most one fallback to a machine-validated standable `GoalBlock`. Direct and fallback navigation share one monotonic 6000 ms budget. The exact Probe 12 coordinates reproduce 2.114415 initial and 2.091618 false-final distances, validate `(93,138,-36)` from solid support plus passable feet/head cells, reserve 4000 ms after a 2000 ms direct attempt, and acquire `oak_log:+1`. A second out-of-range completion fails closed without a third navigation; an unsupported cell is rejected before fallback; the non-M4 control retains its prior single-navigation response. No live episode ran in this offline round, and one fresh BM-012 Probe 13 is authorized only after the gate commit is pushed.

Probe 13 live-validates that gate. Event 96 rejected direct completion at 1.014387 blocks, used one standable-cell fallback with 5317 ms remaining, reached 0.875760 blocks, and then observed `oak_log:+1`; the prior failure did not recur. The new earliest failure layer is `place_target_player_occupancy_grounding`. Event 974 used reference grass block `(103,135,-31)` and target air cell `(103,136,-31)`, while the player stood at `(103.383542,136,-30.5)` and therefore floored to that exact target cell. Equip and target-occupancy policies accepted, but `placeBlock` made no world or inventory change and timed out after 5000 ms. Six same-goal attempts and one later shelter retry repeated the failure. That live round ended without a code fix or second episode.

The bounded offline fix now passes under `m4-place-target-player-occupancy-v1`. Strict M4 derives the player's intersected block cells from the machine observation and a fixed 0.6-by-1.8 collision box, rejects feet, head, and horizontal-boundary intersections before equip or `placeBlock`, and fails closed when the position is missing or invalid. The exact Probe 13 replay rejects target `(103,136,-31)` at zero duration, preserves collision cells `(103,136,-31)` and `(103,137,-31)`, and supplies the four adjacent references `(104,135,-31)`, `(102,135,-31)`, `(103,135,-30)`, and `(103,135,-32)` for one next-cycle replan. Adjacent strict placement executes, while the no-flag/non-M4 path remains unchanged. No live episode ran in this offline gate round.

Probe 14 live-validates the player-occupancy gate. Twenty-one attempts against target `(106,136,-29)` were rejected at zero duration with 21 replan calls, then action event 1554 used adjacent reference `(107,135,-29)` and placed the crafting table successfully in 46 ms. The Probe 13 `blockUpdate` timeout did not recur, so the runner's earlier max-cycle placement candidate is not the first unrecovered transition.

The new earliest failure layer is `dig_backend_required_tool_equip_grounding`. Planner call event 1712 and action-verification event 1719 produced and accepted a canonical stone dig because `wooden_pickaxe:1` was available, but action event 1724 kept `oak_planks` selected. The backend removed stone at `(114,133,-29)`, observed no cobblestone entity or inventory delta, and correctly failed the existing expected-drop postcondition only after irreversible mutation. Seven stone blocks were removed under the same held-item mismatch, with zero successful stone digs and zero cobblestone acquired. Probe 14 was the round's only live episode. The next hypothesis is bounded to selecting, equipping, and machine-confirming a block-compatible harvest tool before strict-M4 dig mutation; no second live episode is authorized before that offline gate passes and is pushed.

The bounded offline fix now passes under `m4-dig-required-tool-equip-v1`. ActionController adds `require_tool_equip=true` only for `m4-fixed-v1`; BotBridge forwards it independently from `require_pickup`. The Mineflayer dig handler reads `block.harvestTools`, selects a positive inventory item accepted by `block.canHarvest`, equips it to hand, and confirms the exact held name/type before calling `bot.dig`. The exact Probe 14 ineffective-equip state now performs one equip attempt, zero dig calls, and zero world mutations. Missing-tool and equip-error controls also fail before mutation; a successful stone path records `equip:wooden_pickaxe -> dig:stone -> cobblestone:+1`, and an iron-tier control rejects wooden pickaxe and selects stone pickaxe for `raw_iron:+1`. Hand-harvestable blocks require no tool, the non-M4 path is unchanged, and the existing expected-drop postcondition remains authoritative. No live episode ran in this offline round.

Probe 15 live-validates that gate. All 19 dig actions emitted `m4-dig-required-tool-equip-v1`; all 13 stone digs required, selected, equipped, and confirmed `wooden_pickaxe`. Twelve stone digs succeeded for `cobblestone:+12`. Event 914's isolated expected-drop failure recovered at event 936, and event 940 completed the 12-cobblestone goal, so Probe 14's held-item mismatch did not recur.

The new earliest failure layer is `deadline_bound_navigation_bridge_recovery`. Planner call event 966 / plan event 969 targeted observed coal ore `(108,130,-34)` from `(112.585511,127,-28.503399)`. Action-verification event 975 accepted the navigation; action event 981 then exhausted its fixed 60-second budget at monotonic 90944.203, returned `command_replayed=false`, `bridge_reconnected=false`, and `navigation_target_unreached`, while the episode still had 281.859 seconds. Sixteen later actions had zero successes, including 15 direct `Not connected to bot bridge` failures. This live round contains no code fix or second episode. The next hypothesis is limited to restoring a fresh bridge connection for the next cycle without replaying the timed-out command, extending the action budget, or weakening the absolute episode deadline.

The bounded offline fix now passes under `m4-deadline-bound-bridge-recovery-v1`. A deadline-bound transport timeout closes the stale socket, records a pending recovery, and returns the old action after exactly one send with `command_replayed=false`; it never reconnects inside that expired action. At the next strict-M4 observation boundary, BotBridge limits socket attempts and exponential backoff to the remaining absolute episode budget, establishes a fresh connection, and requires a structurally valid `get_player_state` response before clearing the pending state. The confirmed state is consumed once by Observer. Expired recovery performs zero connects, failed confirmation closes the fresh socket and prevents Observer/Planner from receiving fabricated defaults, and the non-deadline single-shot reconnect path remains unchanged. Five exact gate tests, 30 focused bridge/deadline tests, 727 full Python tests, and all six Node suites with 50 internal cases pass. No live episode ran in this offline round.

Probe 16 did not exercise that bridge branch: no deadline-bound action failure, bridge-recovery event, or disconnected-bridge action error occurred, all 10 `move_to` actions succeeded, and the terminal bot remained connected. The new earliest failure layer is `planner_place_replan_feedback_grounding`. Event 283 rejected reference `(106,135,-29)`, supplied four bounded adjacent candidates, and prohibited retry. Real schema-valid replan events 292/294 nevertheless repeated the rejected reference, and action event 304 failed again without changing position or inventory. The original root used 40 real schema-valid calls, 17 replans, and 17 rejected actions before failing at event 1024; adjacent placement recovered only at event 1413 after 268.812 seconds. Probe 16 was the round's only live episode.

The bounded offline fix now passes under `m4-place-replan-feedback-grounding-v1`. Agent forwards the rejected reference and verifier candidates as structured feedback, which Planner consumes once on the next strict-M4 `replan`. Exactly one place action must select one supplied candidate. The exact Probe 16 repeated response, missing or multiple place actions, external coordinates, and malformed/duplicate/unbounded feedback all reject before task creation and action execution; all four adjacent candidates pass independently, and non-M4 behavior is unchanged. Three exact cross-layer tests, 37 M4 deadline definitions, 729 full Python regression definitions, all 35 non-live Python scripts, and six Node suites with 50 internal cases pass. Probe 17 exercised both live outcomes: event 311 failed closed on a repeat, while event 354 selected candidate index 0 and event 367 placed the table.

Probe 17 then exposed `deadline_bound_bridge_recovery_pathfinder_readiness`. Recovery event 550 reconnected a fresh transport and confirmed machine player state after the 60-second `move_to` timeout recorded at action event 555. The first next navigation at event 578 failed immediately with `Path was stopped before it could be completed`; all nineteen subsequent navigation actions failed with the same error and unchanged position, including a move toward the previously reachable crafting-table coordinate. Non-navigation commands still succeeded. The next experiment must reproduce this boundary offline and require evidence that the recovered bridge can accept a fresh navigation without replaying the expired command or weakening either deadline.

The bounded offline fix now passes under `m4-deadline-bound-pathfinder-readiness-v1`. Strict-M4 `move_to` failures execute `stop()`, `setGoal(null)`, and `clearControlStates()` so Mineflayer consumes its deferred stop flag instead of rearming it. A deadline-bound transport recovery now records the strict navigation flag, reconnects without replay, sends `recover_navigation`, and requires policy-bound goal-cleared, movement-stopped, control-cleared, no-mutation evidence before requesting `get_player_state`; pending recovery clears only after both confirmations. The recovery command performs two reset passes around one event-loop yield to cover the old `goto()` cleanup race. M1/M2 navigation remains unchanged. Three exact Python gate cases, two exact Node cases, 38 M4 deadline definitions, 730 full Python regression definitions, all 35 non-live Python scripts, and six Node suites with 52 internal cases pass. No live episode ran in this offline round.

Probe 18 did not exercise that policy branch: no deadline-bound action failed, no bridge or navigation-recovery event was emitted, and no `PathStopped` error occurred. Ten moves executed before health became critical, eight succeeded, and each of the two bounded completion failures was followed by a successful navigation. The prior failure did not recur, but pathfinder recovery remains passed offline rather than live-validated.

The new earliest failure layer is `critical_health_survival_action_precondition_deadlock`. A hostile interrupt at event 781 preserved the placement frontier and emergency move event 785 succeeded, but health fell from 20 to 2.33 while the zombie distance increased from 2.4 to 6.4 blocks. Goal event 796 selected immediate-threat flight; real schema-valid plan event 807 emitted a retreat move and event 812 accepted it. Observation event 814 showed health 3.33, food 17, and the zombie at 5.3 blocks, but action event 817 failed at zero duration with `Pre-condition failed: Health critical`. The same blanket check blocked fourteen aligned survival actions. Goal indices 12 through 24 selected the critical-health no-food goal thirteen times; twelve failed through blocked actions and one through a downstream length-truncated Planner response. The 24-goal limit ended the episode after 355.531 seconds with 244.437 seconds remaining. The next experiment must reproduce this boundary offline and permit only bounded, survival-aligned low-health actions without weakening normal action verification or M1/M2 behavior.

The bounded offline fix now passes under `m4-critical-health-survival-action-precondition-v1`. Only strict M4 may cross the blanket health guard. A finite `move_to` is permitted only when the machine inventory contains no known food; `use_item` is permitted only when its named known food is present. Probe 18's exact event-817 move reaches bot execution in the gate fixture, while `craft oak_planks`, movement despite available food, non-food use, missing/non-finite/boolean coordinates, and fixed M1/M2 controls remain blocked before execution. Every activated decision emits a machine-readable policy report. Three exact gate cases, 41 M4 deadline definitions, 733 full Python regression definitions, all 35 non-live Python scripts, and six Node suites with 52 internal cases pass. No live episode ran in this offline round.

Probe 19 did not exercise that policy branch. All 155 complete observations held health and food at 20, no action entered the critical-health path, and no `m4-critical-health-survival-action-precondition-v1` report was emitted. The Probe 18 deadlock did not recur, but the gate remains live-unverified.

Independent review rejects the Runner's event-424 coal `empty_plan` as causal because goal 8 later verified `coal:+1` at dig event 574, and stone-tool progression subsequently recovered. The new earliest failure layer is `post_place_crafting_table_machine_observation_grounding`. Action event 621 machine-confirmed a crafting table at `(106,136,-36)`, while post-action observation event 623 omitted it and task reconciliation did not close the placement prerequisite. Planner event 677 then asserted the table remained unplaced, and action event 686 was the first of fourteen zero-duration failures against that occupied target. The torch root consumed all 40 real schema-valid calls and 209.688 seconds before failing at event 1419. Moving adjacent later exposed the original table at observation event 1437 and event 1445 machine-verified the placement objective, but the elapsed dusk budget was not recovered. The next experiment must reproduce this exact cross-layer boundary offline and ground successful placement in machine state/task readiness without trusting Planner text or weakening generic placement verification.

The bounded offline fix now passes under `m4-post-place-crafting-table-machine-observation-v1`. It accepts only strict-M4 `place(item=crafting_table)` results where success is true, the result item matches, action and result references match, the placed target is exactly one block above the integral reference, both target-block coordinates match that target, and the before/after names prove a change to `crafting_table`. The confirmed block is projected into the immediate post-action observation and one next planner-facing observation, feeds both TaskSystem action-result completion and existing M4 state reconciliation, then expires. Probe 19's exact event-621 state completes the placement task despite the event-623 omission. Failed results, item/name/position drift, malformed coordinates, non-table actions, and non-M4 controls produce no projection. Observer scan radius and 50-block truncation remain unchanged. Two exact gate cases, 43 M4 deadline definitions, 735 full Python regression definitions, all 35 non-live Python scripts, and six Node suites with 52 internal cases pass. No live episode ran in this offline round.

Probe 20 live-activated the policy twice. Event 269 accepted exact machine evidence; observation event 271 carried the policy report, event 273 completed the placement task, event 278 verified the goal, and event 288 carried the second bounded observation into wooden-pickaxe planning. Nine unsuccessful place results failed closed, and event 1063 accepted a later exact placement. Observer directly included both successful tables, so the live `projected` flag remained false and omission projection is still offline-only. The Probe 19 occupied-target repeat did not recur on the first table.

Independent review rejects the Runner's event-820 torch `empty_plan` as causal because goal 8 later placed a table, goal 9 crafted a stone pickaxe, and action event 1172 acquired `raw_iron:+1`. The new earliest failure layer is `m4_ready_task_goal_verifier_success_criteria_bypass`. Goal 11 came from `ready_task_selected`; readiness event 1186 reported one ready task, plan event 1189 required `raw_iron:2` and supplied a valid dig, but pre-plan verification event 1193 accepted the generic `Mine iron ore` text from existing `raw_iron:1` without a delta. Fourteen schema-valid plans through event 1436 continued to require `raw_iron:2`, while fourteen verifier events through 1440 accepted `raw_iron:1/1`; no action executed after event 1172. The 24-goal limit ended the episode with 190.516 seconds remaining. The next experiment must reproduce this exact Agent/GoalVerifier integration boundary offline and require a selected ready task's machine success criteria before pre-plan root completion, without globally changing generic goal semantics.

The bounded offline fix now passes under `m4-ready-task-goal-verifier-success-criteria-v1`. Agent captures the exact task ID selected by `ready_task_selected` and a deep-copied criteria snapshot. Pre-plan, Planner-complete, and post-action verification can close that root only when the same task is already machine-completed by existing state reconciliation or action feedback; generic GoalVerifier output is otherwise suppressed. The exact `raw_iron:1`/required-`raw_iron:2` replay executes the planned dig and releases only after action feedback completes the bound task. Accepted and active status, same-title replacement, criteria mutation, status-only completion without an approved machine source, missing or malformed binding, invalid or expired deadline, and M1/M2 controls all behave fail-closed or unchanged as required. Four exact gate tests, 47 M4 deadline definitions, 739 full Python regression definitions, all 35 non-live Python scripts, and six Node suites with 52 internal cases pass. No live episode ran in this offline round.

Probe 21 live-validates that gate. Across 61 binding reports, 37 retained an unverified goal and 24 suppressed generic completion until exact machine completion; none allowed an unproven ready-task root to finish. Task `7790c984` activated at event 814 and failed at event 851. Event 970 later placed the requested table, event 973 achieved the generic GoalVerifier rule, and event 974 correctly suppressed completion because the exact bound task remained failed. The added suppression caused local churn, but the episode recovered through the event-1491 wooden-pickaxe craft and event-1495 root completion.

The new earliest failure layer is `m4_readiness_recovery_inventory_family_root_completion_disconnect`. Event 1504 selected `Acquire 4 oak_log for Craft oak_planks from oak_logs` for stale blocked task `d37f41ea`, replacing the iron-progression fallback. Event 1509 already held `dark_oak_log:4`, a wooden pickaxe, and a nearby crafting table. Recovery task `25fa2b53` was created at event 1511 and machine-completed at events 1512/1513 when the existing inventory-family policy projected the four dark-oak logs to canonical `oak_log:4`. Planner event 1519 nevertheless reasoned that exact oak-log inventory was zero, created another collection chain, and event 1532 moved away. The root consumed nine cycles and event 1721 suspended it at dusk with six stale accepted crafting tasks. No stone-pickaxe or iron progression followed. The next experiment is limited to this readiness-recovery root/task completion boundary; no fix or second episode occurs in this round.

## BM-012 Offline Preflight

- Task contract: `m4-bm012-resource-contract-v1`; SHA-256 `389bafa8651cd6d46b259a708e1f82144615d1a8ae90aa840b00c3751404b45d`
- Base protocol: unchanged `m4-fixed-v1` SHA-256 `378689bc96d28580b2debcccb12efb4f955de38dd031e681ace529d4f75d157d`
- Runtime: fresh level, empty inventory, survival/normal, natural time from 0, no item grants or fixtures, 600-second absolute deadline, 24 goals, 40 cycles per goal, 320 total cycles
- Autonomous progression: GoalGenerator selects wood, crafting table, wooden pickaxe, cobblestone, stone pickaxe, and iron collection while hostile, health, hunger, dusk, and night priorities remain higher
- Machine terminal: `m4-resource-inventory-verifier-v1` emits `terminal_resource_verification` only for `raw_iron:8` or `iron_ore:8`, positive health, online bot, and uninterrupted zero-death lifecycle
- Independent provenance: initial target inventory is zero; terminal target inventory and positive net delta are required; at least eight successful verified `dig` actions must remove `iron_ore` or `deepslate_iron_ore`
- Fail closed: preloaded inventory, missing source actions, text-only completion, task-contract drift, runtime-limit drift, content-hash drift, lifecycle failure, and deadline overrun are rejected
- Regression baseline: 739 Python regression definitions, all 35 non-live Python scripts, all six fixed Node suites with 52 internal assertions, Node syntax, and Python compilation passed before Probe 21
- Live authorization: consumed by BM-012 Probe 21; no Probe 22 is authorized before the readiness-recovery inventory-family root-completion offline gate is implemented, validated, committed, and pushed
- Report: `workspace/evals/m4_resource_verification.json`

## BM-012 GoalVerifier Purpose-Phrase Gate

- Root hypothesis: `goal_verifier_purpose_phrase_semantic_conflation`
- Exact reproduction: `Gather 6 oak logs for tools and shelter` with `oak_log:6` previously matched both `inventory:oak_log` and `world:shelter`; it now matches `inventory:oak_log` plus `intent:shelter_purpose_phrase` and completes
- Incomplete control: the same resource intent with five logs remains failed with `need 6 oak_log, have 5`
- Compound controls: `Gather 6 oak logs and build shelter`, `Gather 6 oak logs for tools; then build shelter`, and `Build verified shelter before nightfall` still require `world:shelter`
- Scope: GoalVerifier intent parsing only; no protocol, task contract, Planner, ActionVerifier, GoalGenerator, runtime, success threshold, M1, or M2 behavior changed
- Validation: 57 focused tests, 696 full Python tests, six Node suites with 36 PASS cases, and Python compilation pass
- Live result: Probe 2 emitted the expected purpose-phrase matched rule and completed the original resource root in eight cycles
- Authorization: consumed by BM-012 Probe 2; no second episode may run in this round

## BM-012 Crafting-Station World-Readiness Gate

- Root hypothesis: `curriculum_crafting_station_world_readiness_grounding`
- Exact reproduction: Probe 2 event 308 inventory `oak_log:4`, `crafting_table:1`, `oak_planks:4` with no nearby table now selects `Place crafting table for tool progression`, reason `bm012_crafting_table_unplaced`; `Craft wooden pickaxe` is absent from the slate
- Ready control: adding a nearby machine-observed `crafting_table` removes the placement candidate and selects `Craft wooden pickaxe`
- Rule control: BM-012 GoalGenerator also selects `Place the crafting table nearby` whenever the item is in inventory but no nearby table is observed, before replenishing wood
- Action grounding: strict-M4 converts only the nonconflicting `block` alias to canonical `item` and requires finite top-level reference coordinates `x`, `y`, and `z`
- Completion grounding: `Place crafting table...` and `Craft and place a crafting table...` require `world:nearby_crafting_table`; inventory possession alone fails
- Scope: BM-012 autonomous crafting-station readiness, strict-M4 place parameters, and machine placement completion; M1/M2 fixed protocols, action execution, task contract, deadline, and success thresholds are unchanged
- Validation: 50 focused tests, 700 full Python tests, six Node suites with 36 PASS cases, Python compilation, and `git diff --check` pass
- Live result: Probe 3 emitted one canonical place plan with `item` and finite coordinates, but the current plank goal verified before that action ran; the next `Place crafting_table` root then hit the earlier subtask numeric-type failure
- Authorization: consumed by BM-012 Probe 3; no second episode may run in this round

## BM-012 Planner Subtask Numeric-Criteria Gate

- Root hypothesis: `planner_subtask_numeric_criteria_type_grounding`
- Exact reproduction: Probe 3 plan event 510 now normalizes `success_criteria.inventory.oak_planks=">=8"` to `8` and `preconditions.inventory.oak_log=">=1"` to `1` before creating scheduler tasks
- Evidence: `m4_subtask_numeric_criteria_grounding` records four inventory requirements, two exact normalizations, their source-value hashes, canonical counts, and any rejection issues in both the accepted plan and Planner call evidence
- Rejection controls: booleans, zero, negatives, floats, bare numeric strings, alternate comparators, prose counts, and non-object inventory criteria fail schema validation and create no tasks
- Runtime defense: malformed success counts remain unsatisfied without raising; malformed precondition counts appear as `invalid_inventory_requirements` and keep the task blocked
- Prompt grounding: M4 requires positive integer inventory counts and states that the built-in criterion already means at least N
- Scope: strict-M4 Planner subtask inventory criteria and TaskSystem numeric fail-closed defense only; M1/M2 fixed contracts, protocol data, action execution, GoalGenerator, GoalVerifier, deadline, and success thresholds are unchanged
- Validation: 3 exact new gate tests, 134 related tests, 703 full Python tests, six Node suites with 36 cases, Python compilation, and `git diff --check` pass
- Live result: Probe 4 emitted 31 passing numeric-grounding reports with integer-only counts and zero runtime errors; the exact `>=N` normalization branch was not exercised live
- Authorization: consumed by BM-012 Probe 4; no second episode may run in the round

## BM-012 Task Inventory-Family Reconciliation Gate

- Root hypothesis: `m4_task_inventory_family_reconciliation_grounding`
- Exact reproduction: Probe 4 event-157 inventory `oak_log:4 + dark_oak_log:2` now completes all seven exact `inventory.oak_log=6` tasks reported ready at event 160
- Family grounding: `m4-task-inventory-family-grounding-v1` reuses the pinned `GoalVerifier.LOG_ITEMS`, records observed members plus canonical before/after counts, and operates on a copied observation
- Root-boundary control: a task created by the final Planner response is reconciled at `pre_goal_machine_observation` before scheduler selection, preventing one residual repeated root
- Progression replay: BM-012 GoalGenerator still emits its exact-species fallback, but Curriculum sees the six-log family and selects `Craft crafting table` after stale tasks close
- Fail-closed controls: `oak_log:4 + dark_oak_log:1` does not complete the threshold; non-inventory criteria, non-M4 profiles, and urgent survival fallback retain prior behavior
- Transition evidence: completed task transitions are flushed immediately with source `m4_task_state_reconciliation`, reconciliation source, goal, and cycle
- Scope: strict-M4 Agent task lifecycle only; GoalVerifier rules, TaskSystem generic semantics, Planner schema, action execution, M1/M2 contracts, protocol data, deadline, and success thresholds are unchanged
- Validation: 2 exact new tests, 136 related tests, 705 full Python tests, six Node suites with 36 cases, Python compilation, and `git diff --check` pass
- Live result: Probe 5 emitted four reconciliation events, completed 18 tasks at those boundaries, activated family projection for `oak_log:5 + birch_log:1`, and produced no repeated fulfilled wood root
- Authorization: consumed by BM-012 Probe 5; no second episode may run in the round

## BM-012 Placement Success-Criteria Grounding Gate

- Root hypothesis: `planner_place_success_criteria_grounding`
- Failure-class replay: a `Place crafting table for tool progression` subtask with `success_criteria.inventory.crafting_table` and one canonical `place(item=crafting_table,x,y,z)` action no longer loses the executable plan at numeric validation
- Semantic contract: possession of the item is never placement proof; strict-M4 uses `success_criteria.nearby_block_present=crafting_table`, which TaskSystem verifies from the post-action machine observation
- Alignment gate: the root goal, subtask title/type, immediate place action, and inventory criterion must identify the same exact item
- Evidence: `m4-place-success-criteria-grounding-v1` records source-value SHA-256, original/grounded subtasks SHA-256, item, canonical field/value, and whether the source count was already a positive integer
- Fail-closed controls: goal mismatch, missing placement intent, conflicting nearby-block evidence, different action item, invalid preconditions, and unrelated invalid inventory criteria remain rejected
- Machine completion: the grounded task stays incomplete without a nearby block and completes only after a successful action is followed by a machine observation containing `crafting_table`
- Scope: strict-M4 Planner prompt and plan grounding only; TaskSystem generic semantics, GoalVerifier, ActionVerifier, action execution, protocol/task-contract hashes, M1/M2 fixed protocols, deadlines, and success thresholds are unchanged
- Validation: 2 exact new tests, 138 related tests, 707 full Python tests, six Node suites with 36 cases, Python compilation, and `git diff --check` pass
- Live result: Probe 6 emitted canonical `nearby_block_present=crafting_table` directly on the first placement plan; 129/129 real Planner responses were schema-valid, the prior rejection did not recur, and the normalization branch remained unexercised
- Authorization: consumed by BM-012 Probe 6; no second episode may run in that live round

## BM-012 Requested-Item Equip Gate

- Root hypothesis: `place_backend_requested_item_equip_grounding`
- Exact reproduction: inventory contains `crafting_table:1`, the bot holds `dark_oak_sapling`, and an ineffective equip attempt must fail before `placeBlock`; the target remains unchanged
- Runtime policy: `m4-place-requested-item-equip-v1`
- Inventory gate: the requested item name is required and must match an exact positive Mineflayer inventory stack
- Equip gate: the exact stack is equipped to `hand`, then Mineflayer `heldItem` or hand equipment must report the same requested name
- Mutation boundary: missing inventory, equip exceptions, and held-item mismatch return before any `placeBlock` call or world mutation
- Success evidence: the result records policy ID, requested item, equipped item, confirmation, reference/target coordinates, and before/after target block state; success requires the exact requested block
- Fail-closed controls: missing item, unavailable item, ineffective equip, wrong held item, and wrong observed target block cannot pass
- Scope: generic Mineflayer place bridge only; Planner, ActionVerifier, GoalVerifier, task semantics, protocol/task-contract hashes, M1/M2 fixed protocols, deadlines, and thresholds are unchanged
- Validation: three exact place cases, 166 related Python tests, 707 full Python tests, six Node suites with 37 internal cases, Node/Python syntax checks, and `git diff --check` pass
- Authorization: consumed by BM-012 Probe 7; no second episode ran in the live round

## BM-012 Placement Target Occupancy Gate

- Root hypothesis: `planner_place_target_occupancy_grounding`
- Runtime policy: `m4-place-target-occupancy-v1`
- Coordinate contract: `place(x,y,z)` names the reference block; the actual target is `floor(x),floor(y)+1,floor(z)`
- Exact replay: Probe 7 reference `(93,134,-38)` with target `dark_oak_log` and reference `(93,134,-36)` with target `grass_block` both reject before execution
- ActionVerifier boundary: strict-M4 uses exact positioned machine observations, requires air or a conservative replaceable block, returns zero-duration rejection evidence, and requests a target-aware next-cycle replan
- Bridge boundary: Mineflayer reads the exact target and rejects a solid occupant before item equip, `placeBlock`, or world mutation
- Controls: `short_grass`, a target absent from the observed non-air set, non-M4 ActionVerifier behavior, and the existing air-target success path remain accepted
- Scope: M4 placement grounding plus the generic impossible-target bridge preflight; GoalVerifier, task semantics, fixed protocol/task-contract hashes, deadlines, and success thresholds are unchanged
- Validation: 22 focused M4 Python tests, 149 cross-module Python tests, 709 full Python tests, and six Node suites with 38 internal cases pass
- Live result: Probe 8 rejected one exact occupied target at zero duration, requested a target-aware replan, and successfully placed on the next air target; the Probe 7 timeout did not recur
- Live count: eight BM-012 attempts and 0/3 eligible successes
- Authorization: consumed by BM-012 Probe 8; no second episode ran in the live round

## BM-012 Task World-State Reconciliation Gate

- Root hypothesis: `m4_task_world_state_reconciliation_grounding`
- Exact reproduction: task `2f1081b4` remained accepted after event 278 placed the required nearby `crafting_table`, then event 286 selected that already-satisfied task as the next autonomous root
- Policy: `m4-task-world-state-reconciliation-v1` permits only `inventory` and `nearby_block_present`; sources are `observation.inventory` and `observation.nearby_blocks`
- Exact replay: task `2f1081b4` completes before ready-task selection from the event-278 machine state, and fallback iron-tool progression is selected instead of the stale root
- Fail-closed controls: inventory, entities, landmarks, absent blocks, empty lists, object-valued criteria, unmet criteria, unrelated criterion families, and non-M4 pre-goal reconciliation do not retire the placement task
- Priority control: hostile, health, hunger, dusk, and night fallback precedence remains unchanged
- Scope: strict-M4 Agent task lifecycle plus criterion-specific TaskSystem machine-evidence evaluation; Planner, GoalVerifier, ActionVerifier, bridge execution, protocol/task-contract hashes, deadlines, success thresholds, and fixed M1/M2 protocols remain unchanged
- Validation: 3 exact gate tests, 95 TaskSystem tests, 86 related M4/GoalVerifier lifecycle tests, 711 full Python tests, six Node suites with 38 internal cases, and Python compilation pass
- Live result: Probe 9 event 1797 completed five nearby-block shelter tasks under the new policy; no satisfied world-state task was reselected, while the exact crafting-table boundary was not reached
- Status: passed offline; policy branch exercised live in Probe 9
- Authorization: consumed by BM-012 Probe 9

## BM-012 Typed Schema-Rejection Recovery Gate

- Root hypothesis: `m4_planner_schema_rejection_recovery_scope`
- Exact reproduction: real continuation call event 115 / `llm-3bbb8772f5f0473e` failed only `subtask[2]:preconditions_inventory_count_invalid:oak_log`; event 120 emitted `empty_plan`, and event 122 failed the root
- Prior boundary: `_recover_m4_invalid_plan` preserved M4 goals only for typed transport failures or `planning_actions_missing`; other fail-closed schema issues fell through to immediate `empty_plan`
- Required proof: one typed numeric-criteria schema rejection preserves the same autonomous goal and task frontier for a bounded next-cycle replan, while no invalid task or action is accepted
- Policy: `m4-typed-schema-recovery-v1` admits only real strict-M4 subtask inventory-count rejection evidence, allows one next-cycle replan per autonomous goal, and verifies the same goal plus a hash-identical nonterminal task frontier before that call
- Exact replay: the Probe 9 shape retains three subtasks and six requirements only in hashed Planner evidence, returns zero tasks/actions for execution, then replans on the same root after one verified resume
- Fail-closed controls: a second typed rejection emits one exhausted event and reaches `empty_plan`; frontier drift, mixed issues, untrusted evidence, leaked actions, malformed metrics, non-M4 behavior, and deadline exhaustion reject recovery
- Scope: Agent M4 planner-output recovery only; Planner validation, TaskSystem criteria, GoalVerifier, ActionVerifier, bridge execution, protocol/task-contract hashes, deadlines, and fixed M1/M2 protocols remain unchanged
- Validation: 3 exact gate tests, 25 M4 deadline tests, 51 combined M4 tests, 714 full Python tests, six Node suites with 38 internal assertions, and Python compilation pass
- Status: passed offline; Probe 10 did not reproduce the typed rejection, so the recovery branch remains live-unexercised
- Authorization: consumed by BM-012 Probe 10; the next live run is blocked on a new offline opportunity-trigger type gate

## BM-012 Opportunity-Trigger Type Gate

- Root hypothesis: `planner_subtask_opportunity_trigger_type_grounding`
- Policy: `m4-subtask-opportunity-trigger-type-grounding-v1` validates explicit strict-M4 subtask trigger metadata before TaskSystem creation
- Exact replay: Probe 10's `Mine coal ore` object trigger at call event 262 produces `subtask[2]:opportunity_triggers[0]_not_string`, zero accepted subtasks/actions, and zero created tasks
- Fail-closed controls: non-array containers, nulls, numbers, dictionaries, empty strings, and whitespace-only strings reject; no malformed value is coerced into a valid trigger
- Valid control: string trigger lists remain unchanged and still contribute direct or causal opportunity scoring
- Consumer defense: TaskSystem ignores legacy non-list containers and non-string elements instead of iterating or calling `.lower()` on them; valid string hints in a valid list remain active
- Scope: strict-M4 Planner metadata validation and the TaskSystem trigger consumer guard only; typed schema recovery, Agent root selection, GoalVerifier, ActionVerifier, bridge execution, deadlines, success thresholds, protocol hash, task contract, and fixed M1/M2 behavior are unchanged
- Validation: 2 focused gate tests, 27 M4 deadline tests, 95 TaskSystem tests, 76 fixed M4 Python tests, 716 full Python tests, six Node suites with 38 internal assertions, and Python compilation pass
- Status: passed offline and accepted-path live-validated in Probe 11; 110/110 reports passed with 117/117 valid trigger values, while the rejection branch remains live-unexercised
- Authorization: consumed by BM-012 Probe 11

## BM-012 Expected-Drop Pickup/Postcondition Gate

- Root hypothesis: `dig_expected_drop_pickup_postcondition`
- Source transition: Probe 11 action event 81 / monotonic 74061.859 / cycle 4 removed `oak_log` at `(93,139,-36)` but recorded no pickup, no inventory delta, and no collection attempt while returning `success=true`
- Confirmation: action event 152 removed another oak log, detected the expected drop, attempted collection, and timed out after 6000 ms with inventory still `dark_oak_log:1`
- Required proof: expected-drop resource digs acquire the drop into machine inventory before success, or return a bounded fail-closed result that preserves enough state for a next-cycle recovery
- Policy: `m4-expected-drop-pickup-postcondition-v1`; `ActionController` sends `require_pickup=true` only under `m4-fixed-v1`
- Exact replay: the event-81 state returns `success=false`, preserves `block_removed=true`, names `oak_log` as the expected drop, records no pickup, and emits a failed postcondition instead of resource success
- Collection control: strict M4 polls up to 1500 ms for the drop, uses `GoalNear(...,1)` under a 6000 ms navigation bound, and verifies the expected inventory delta after collection
- Compatibility control: the identical missing-drop fixture without `require_pickup` retains legacy success and emits no M4 postcondition; fixed M1/M2 behavior is unchanged
- Scope: Mineflayer dig pickup collection and M4 resource-action postcondition only; protocol/task-contract hashes, Planner schema, task semantics, deadlines, and success thresholds remain unchanged
- Validation: 2 exact Python forwarding tests, 2 exact Node gate tests, 36 related Python tests, 718 full Python tests, six Node suites with 40 internal assertions, Python compilation, and `git diff --check` pass
- Status: passed offline and live-validated in Probe 12; 3/5 strict digs acquired their expected drop, 2/5 failed closed, zero false-positive successes occurred, and the first failure recovered through two later successful digs
- Authorization: consumed by BM-012 Probe 12

## BM-012 Pickup-Collection Completion-Grounding Gate

- Root hypothesis: `pickup_collection_pathfinder_completion_grounding`
- Source transition: Probe 12 action event 169 / monotonic 77764.312 / cycle 8 removed `oak_log` at `(93,138,-36)`, detected entity 871, and entered pickup collection with `dark_oak_log:3`
- Failure: the inner collector returned `success=true` even though final distance was 2.091618 blocks against `GoalNear(...,1)` and the expected `oak_log` inventory delta remained zero; the outer strict-M4 postcondition correctly returned failure
- Policy: `m4-pickup-collection-completion-grounding-v1`; collector success is grounded in expected inventory acquisition or measured final distance, never merely resolution of `pathfinder.goto`
- Exact replay: the direct `GoalNear` reproduces 2.114415 initial and 2.091618 final distance and is marked ungrounded; solid support at `(93,137,-36)` plus passable feet/head cells validate fallback `(93,138,-36)`
- Bounded alternate: one exact `GoalBlock` fallback receives 4000 ms after the deterministic direct attempt consumes 2000 ms of the shared 6000 ms budget, then acquires `oak_log:+1`
- Fail-closed controls: a still-distant fallback performs no third navigation, an unsupported candidate is rejected before navigation, and final resource success still requires the expected inventory delta
- Compatibility control: the same direct false completion without strict M4 retains one legacy navigation and no new policy evidence
- Scope: strict-M4 pickup collector completion semantics only; Planner, TaskSystem, GoalVerifier, deadlines, success thresholds, protocol/task-contract hashes, fixed M1/M2 behavior, skills, vision, and multi-agent execution remain unchanged
- Validation: 12 benchmark-reset Node cases, six fixed Node suites with 44 internal PASS cases, 36 focused Python tests, 718 full Python tests, syntax check, Python compilation, and `git diff --check`
- Status: passed offline; no live episode ran in this gate round
- Authorization: exactly one fresh BM-012 Probe 13 only after this gate commit is pushed

## BM-012 Place Target Player Occupancy Gate

- Root hypothesis: `place_target_player_occupancy_grounding`
- Source transition: Probe 13 action event 974 / monotonic 82047.437 / elapsed 404.37 / cycle 40 under autonomous goal `Place crafting_table`
- Planner lineage: real schema-valid call event 956 / plan event 958 / action-verification event 969 / call ID `llm-cce9a8671b604d6f`
- Reference and target: grass block `(103,135,-31)` with an unoccupied block target `(103,136,-31)`
- Player collision: pre-action player position `(103.38354189850078,136,-30.5)` floors to `(103,136,-31)`, exactly the target cell
- Existing controls: `m4-place-requested-item-equip-v1` confirmed the crafting table in hand and `m4-place-target-occupancy-v1` accepted the air target
- Failure: Mineflayer emitted no target mutation, retained `crafting_table:1`, retained the same player position, and timed out waiting 5000 ms for `blockUpdate:(103,136,-31)`
- Persistence: the initial action plus five same-goal retries and one later shelter attempt failed with the same timeout; no successful place followed the first unrecovered transition
- Policy: `m4-place-target-player-occupancy-v1`; strict M4 computes all block cells intersecting a fixed 0.6-wide, 1.8-high player box from the machine observation
- Exact replay: target `(103,136,-31)` intersects the Probe 13 feet cell and is rejected at zero duration before equip, `placeBlock`, or world mutation; the head cell `(103,137,-31)` is also protected
- Bounded recovery: preserve target/player/collision coordinates and expose at most four non-colliding adjacent references for exactly one next-cycle replan without retrying the rejected reference
- Fail-closed controls: horizontal-boundary overlap and missing/invalid player positions reject; Node floors fractional reference coordinates before target and collision checks
- Compatibility controls: a strict adjacent target executes, and the legacy/no-clearance path retains its previous behavior
- Scope: place target/player collision grounding only; pickup completion, Planner schema, TaskSystem, GoalVerifier, deadlines, protocols, success thresholds, skills, vision, and multi-agent execution remain unchanged
- Validation: 117 cross-module Python tests, 722 full Python tests, all six fixed Node suites with 45 internal PASS cases including 12 M4 protocol cases, Node syntax, Python compilation, and repository checks
- Status: passed offline and live-validated in Probe 14; 21 collision rejects preceded one successful adjacent placement, and the prior timeout did not recur
- Authorization: consumed by BM-012 Probe 14; no second episode may run in the live round

## BM-012 Dig Required-Tool Equip Gate

- Root hypothesis: `dig_backend_required_tool_equip_grounding`
- Source transition: Probe 14 action event 1724 / monotonic 87571.656 / elapsed 476.2 / cycle 90 under autonomous goal `Mine 12 cobblestone for stone tools and furnace`
- Planner lineage: real schema-valid call event 1712 / plan event 1714 / action-verification event 1719 / call ID `llm-204302efb42d4fd7`
- Machine state: target `(114,133,-29)` was `stone`, inventory contained `wooden_pickaxe:1`, but selected slot 3 held `oak_planks`
- Failure: the bridge removed the stone before equipping a harvest tool; no cobblestone entity or inventory delta appeared, and the existing postcondition returned `expected block drop was not acquired`
- Persistence: seven stone blocks were removed without a drop at events 1724, 1746, 1768, 1811, 1833, 1856, and 1878; zero stone digs succeeded and zero cobblestone was acquired
- Policy: `m4-dig-required-tool-equip-v1`; strict M4 forwards an explicit `require_tool_equip` bridge flag independently from `require_pickup`
- Required policy: resolve `block.harvestTools`, select an exact positive inventory item that passes `block.canHarvest`, equip it to hand, and confirm matching held name/type before any dig mutation
- Exact replay: Probe 14's `wooden_pickaxe:1` plus held `oak_planks` state with ineffective equip performs one equip attempt, zero dig calls, and zero world mutations; target stone remains stone
- Positive controls: wooden pickaxe is equipped before stone and yields `cobblestone:+1`; inventory containing wooden and stone pickaxes selects only stone pickaxe for iron ore and yields `raw_iron:+1`
- Mutation boundary: missing tools, equip exceptions, and held-item mismatch fail closed before `bot.dig`; the existing expected-drop pickup and inventory-delta postcondition remains required after mutation
- Compatibility controls: a hand-harvestable log performs no equip and succeeds under strict M4; the non-M4 path emits no new policy evidence and retains prior behavior
- Scope: strict-M4 dig backend required-tool grounding only; Planner schema, ActionVerifier acceptance, pickup completion, task semantics, protocol/task-contract hashes, deadlines, success thresholds, skills, vision, and multi-agent execution remain unchanged
- Validation: 40 focused Python tests, 722 full Python tests, five exact Node gate cases, all six Node suites with 50 internal PASS cases, Node syntax, Python compilation, and repository checks
- Status: passed offline and live-validated in Probe 15; all 13 stone digs confirmed the required wooden pickaxe and 12 acquired cobblestone
- Authorization: consumed by BM-012 Probe 15; no second episode may run in the live round

## BM-012 Deadline-Bound Navigation Bridge-Recovery Gate

- Root hypothesis: `deadline_bound_navigation_bridge_recovery`
- Source transition: Probe 15 action event 981 / monotonic 90944.203 / elapsed 321.74 / cycle 41 under autonomous goal `Collect coal or charcoal for torches`
- Planner lineage: real schema-valid call event 966 / plan event 969 / action-verification event 975 / call ID `llm-24a053c80ce2455e`
- Machine state: player `(112.58551109325079,127,-28.50339949004437)`, observed coal ore `(108,130,-34)` at distance 7.071, health 20, hunger 20, inventory including `wooden_pickaxe:1` and `cobblestone:12`
- Failure: `move_to(108,130,-34)` consumed 60000 ms, did not reach the target, correctly did not replay, and closed the deadline-bound bridge socket without reconnecting
- Remaining budget: action failure occurred 281.859 seconds before the absolute episode deadline, so the unrecovered bridge state was not caused by exhausting the episode budget
- Persistence: 16 later actions had zero successes; 15 returned `Not connected to bot bridge`, while task-deadline recovery continued to run without restoring transport
- Required policy: preserve single-attempt/no-replay semantics, then establish and machine-confirm a fresh bridge connection before the next observation/planning cycle when episode time remains
- Fail closed: never replay the timed-out action, never reconnect synchronously inside the expired action, never extend either deadline, and never treat empty fallback observations as machine state
- Scope: BotBridge deadline-bound transport recovery after navigation timeout only; Node pathfinder semantics, Planner goals, task contract, success threshold, skills, vision, multi-agent execution, M1, and M2 remain unchanged
- Policy: `m4-deadline-bound-bridge-recovery-v1`; timeout records pending recovery, strict-M4 pre-observation reconnects a fresh socket within the remaining episode deadline, and `get_player_state` must machine-confirm the connection
- Exact controls: old command one send/no replay/no synchronous reconnect; successful next-observation recovery; expired recovery with zero connect attempts; invalid machine confirmation fail-closed before Observer; non-deadline reconnect unchanged
- Validation: five exact gate tests, 30 focused Python tests, 727 full Python tests, six fixed Node suites with 50 internal PASS cases, Node syntax, Python compilation, and repository checks
- Status: passed offline but not live-exercised in Probe 16; no deadline-bound action failure or bridge recovery event occurred, all 10 navigation actions succeeded, and terminal connectivity remained valid
- Authorization: consumed by BM-012 Probe 16; no second episode may run in the live round

## BM-012 Planner Place-Replan Feedback-Grounding Gate

- Root hypothesis: `planner_place_replan_feedback_grounding`
- Source transition: Probe 16 action event 304 / monotonic 8936.656 / elapsed 103.85 / cycle 13 under autonomous goal `Place crafting table for tool progression`
- Required precursor: event 283 rejected reference `(106,135,-29)` because target `(106,136,-29)` intersected the player's collision cells, supplied `(107,135,-29)`, `(105,135,-29)`, `(106,135,-28)`, and `(106,135,-30)`, and explicitly prohibited retry
- Violating lineage: real schema-valid replan call event 292 / plan event 294 / action-verification event 299 / call ID `llm-7aea1a8f6bfa4281` / root plan `root-2a952d3aa6424a33`
- Planner evidence: response SHA-256 `298670e24839bb6d9be9eec99e2926129caf26c52f3eb6bad16bd9fbb688369e`, 1003 bytes, 3452 ms, and 3498 tokens; the returned action repeated the exact rejected reference
- Machine state: position `(106.31411726239254,136,-28.508541454767705)` and inventory `oak_log:5, crafting_table:1` were unchanged across the zero-duration rejection
- Persistence: the rejected reference was attempted 20 times; the original root used 40 real schema-valid calls, 17 replans, and 17 rejected actions before event 1024 failed it at 40 cycles
- Delayed recovery: event 1413 used adjacent reference `(107,135,-29)` and placed the table successfully at monotonic 9205.468, 268.812 seconds after the first violating retry; remaining episode budget fell from 499.594 to 230.782 seconds
- Required policy: after a strict-M4 place verifier rejection, the next replan must exclude the rejected reference and select at most one verifier-supplied adjacent candidate
- Fail closed: if a replan repeats the rejected reference, reject the plan before action execution; do not widen candidate count, synthesize unbounded coordinates, weaken player occupancy, or alter deadlines
- Scope: Planner/replan feedback grounding only; ActionVerifier, bridge placement, protocol/task-contract hashes, success thresholds, skills, vision, multi-agent execution, M1, and M2 remain unchanged
- Policy: `m4-place-replan-feedback-grounding-v1`; Agent records the rejected reference and one-to-four verifier candidates as structured feedback, and Planner consumes it exactly once on the next strict-M4 `replan`
- Selection gate: exactly one place action must use one supplied candidate; all four Probe 16 candidates pass independently and expose the selected candidate index
- Fail-closed gate: the exact Probe 16 repeated reference, missing place, multiple place actions, candidate-external coordinates, empty/over-limit candidate sets, duplicates, rejected-reference candidates, non-finite candidates, and malformed rejected references produce no tasks and no executable actions
- Compatibility controls: continuation calls without pending feedback and non-M4 Planner behavior remain unchanged; ActionVerifier, bridge placement, task semantics, interrupts, deadlines, skills, vision, and multi-agent behavior are untouched
- Validation: three exact cross-layer tests, 37 M4 deadline definitions, 729 full Python regression definitions, all 35 non-live Python scripts, six fixed Node suites with 50 internal PASS cases, Node syntax, Python compilation, and repository checks pass; the real M2 integration test skips without `OPENAI_API_KEY`
- Status: passed offline and live-exercised in Probe 17; one repeated response failed closed and one supplied candidate passed through successful placement
- Authorization: consumed by BM-012 Probe 17; no second episode or new live authorization exists in this round

## BM-012 Deadline-Bound Pathfinder Readiness Gate

- Root hypothesis: `deadline_bound_bridge_recovery_pathfinder_readiness`
- Exact reproduction: Probe 17 recovery event 550 confirmed transport/player state after action event 555 timed out, but event 578 and all 18 later navigations failed `PathStopped`; event 1801 also failed toward the previously reachable crafting-table coordinate
- Policy: `m4-deadline-bound-pathfinder-readiness-v1`; strict-M4 move failures drain the deferred stop state, and reconnect recovery validates `recover_navigation` before `get_player_state`
- Recovery evidence: goal cleared, movement stopped, control states cleared, no command replay, and no world mutation; pending recovery remains set and the socket closes if either pathfinder or player-state confirmation fails
- Race control: two reset passes around one event-loop yield cover the old `goto()` rejection cleanup without extending the action or episode deadline
- Compatibility: M1/M2 move requests omit the strict flag and preserve their established path; protocol/task-contract hashes, Planner, GoalVerifier, success thresholds, skills, vision, and multi-agent behavior are unchanged
- Validation: three exact Python gate cases, 76 focused Python definitions, 38 M4 deadline definitions, two exact Node navigation cases, 730 full Python regression definitions, all 35 non-live Python scripts, and six fixed Node suites with 52 internal PASS cases; Node syntax, Python compilation, JSON, capability consistency, and repository checks pass
- Status: passed offline; Probe 18 had no timeout/recovery branch activation and no `PathStopped` recurrence
- Authorization: consumed by BM-012 Probe 18; no second episode or new live authorization exists in this round

## BM-012 Critical-Health Survival-Action Precondition Gate

- Root hypothesis: `critical_health_survival_action_precondition_deadlock`
- Exact reproduction: Probe 18 action event 817 attempted `move_to(108.69,136,-13.56)` after real schema-valid planning and ActionVerifier acceptance at event 812, then failed at 0 ms with `Pre-condition failed: Health critical`
- Persistence: the blanket ActionController check blocked 14 actions, including 13 moves and one `craft oak_planks`; thirteen critical-health goals consumed the remaining goal budget with 244.437 seconds still available
- Policy: `m4-critical-health-survival-action-precondition-v1`; only strict M4 permits finite `move_to` with no available known food or `use_item` naming available known food
- Fail closed: non-survival actions, movement while food is available, non-food use, missing/non-finite/boolean navigation coordinates, and all fixed M1/M2 low-health controls execute zero bot calls
- Evidence: activated pass/fail decisions are attached to the action result with policy ID, health threshold, action class, available food, reason, and pre-execution fail-closed status
- Compatibility: ActionVerifier, GoalGenerator priority, RuntimeSupervisor interrupt/frontier contracts, protocol/task-contract hashes, deadlines, success thresholds, skills, vision, and multi-agent behavior are unchanged
- Validation: three exact gate cases, 41 M4 deadline definitions, 733 full Python regression definitions, all 35 non-live Python scripts, and six fixed Node suites with 52 internal PASS cases; Python compilation, Node syntax, JSON, capability consistency, and repository checks pass
- Status: passed offline; Probe 19 stayed at health/food 20 and emitted no policy report, so the branch remains live-unverified
- Authorization: consumed by BM-012 Probe 19; no second episode or new live authorization exists in this round

## BM-012 Post-Place Crafting-Table Machine-Observation Gate

- Root hypothesis: `post_place_crafting_table_machine_observation_grounding`
- Exact reproduction: Probe 19 action event 621 placed `crafting_table` from reference `(106,135,-36)` to target `(106,136,-36)` with a machine-confirmed air-to-table delta; observation event 623 omitted that target and left the placement task open
- Policy: `m4-post-place-crafting-table-machine-observation-v1`; only strict-M4 successful crafting-table results with exact item, reference, placed-target, before/after-name, and integral-coordinate agreement may create a bounded projection
- Lifetime: the verified target appears in the immediate post-action observation and one next planner-facing observation, drives TaskSystem completion and M4 state reconciliation, and then expires
- Fail closed: unsuccessful results, result-item mismatch, placed-target mismatch, after-name mismatch, before/after-position mismatch, malformed/non-integral coordinates, non-table actions, and non-M4 profiles create no projection
- Compatibility: Observer radius and truncation, bridge placement, ActionVerifier, GoalVerifier rules, protocol/task-contract hashes, deadlines, success thresholds, skills, vision, multi-agent behavior, M1, and M2 are unchanged
- Validation: two exact gate cases, 43 M4 deadline definitions, 735 full Python regression definitions, all 35 non-live Python scripts, and six fixed Node suites with 52 internal PASS cases; Python compilation, Node syntax, 1066 JSON files, capability consistency, credential scan, and repository checks pass
- Status: passed offline and live-activated in Probe 20; two exact successful results were accepted and nine unsuccessful results failed closed, while the Observer-omission projection branch remains offline-only
- Authorization: consumed by BM-012 Probe 20; no second episode or new live authorization exists in this round

## BM-012 Ready-Task GoalVerifier Success-Criteria Gate

- Root hypothesis: `m4_ready_task_goal_verifier_success_criteria_bypass`
- Exact reproduction: a `ready_task_selected` `Mine iron ore` task requires `raw_iron:2` while observation and generic GoalVerifier hold only `raw_iron:1`; the generic achieved result is suppressed and the planned dig remains executable
- Policy: `m4-ready-task-goal-verifier-success-criteria-v1`; strict M4 binds the exact selected task ID, title, selection reason, and deep-copied machine success criteria
- Completion rule: pre-plan, Planner-complete, and post-action root acceptance requires that exact task to be `completed` with `completed_by=machine_state` or `completed_by=action_result`
- Evidence: every applied decision records task ID, criteria, task status, selection reason, verifier result, binding issues, deadline state, suppression decision, and machine completion source
- Fail closed: accepted or active task, completed same-title replacement, criteria mutation, unproven status-only completion, missing/malformed binding, invalid deadline, and expired deadline cannot finish the root
- Compatibility: global GoalVerifier semantics, TaskSystem criteria, goal priority, runtime interrupts, protocol/task-contract hashes, deadlines, success thresholds, M1, and M2 are unchanged
- Validation: four exact gate cases, 47 M4 deadline definitions, 739 full Python regression definitions, all 35 non-live Python scripts, and six fixed Node suites with 52 internal PASS cases; Python compilation, Node syntax, JSON, capability consistency, credential scan, and repository checks pass
- Status: passed offline; no live episode ran in this gate round
- Live validation: Probe 21 emitted 61 reports (`37` retain, `24` suppress, `0` allow); event 974 suppressed generic completion because exact bound task `7790c984` had failed
- Authorization: consumed by BM-012 Probe 21; stop before any further live episode

## BM-012 Readiness-Recovery Inventory-Family Root-Completion Gate

- Root hypothesis: `m4_readiness_recovery_inventory_family_root_completion_disconnect`
- Exact reproduction: event 1511 creates recovery task `25fa2b53` for `oak_log:4`; events 1512/1513 machine-complete it from `dark_oak_log:4`, while plan event 1519 still reasons from exact `oak_log:0` and continues the same root
- Policy: `m4-readiness-recovery-inventory-family-root-completion-v1` binds the machine-completable recovery child to a stable synthetic root and a canonical requirement fingerprint over item family, count, exact/family semantics, consumer provenance, and task family
- Completion boundary: a child completed by machine state or action result recomputes the normalized inventory postcondition and closes the root in the same scheduler cycle before Planner execution
- Stale-task handling: the binding freezes the matching active sibling IDs that existed when recovery began; once the requirement is satisfied, those tasks become `cancelled_as_satisfied`, leave readiness/frontier context, and retain status history, while later same-fingerprint consumers remain untouched
- Fail closed: exact `oak_log` does not accept dark oak, insufficient family totals leave the root active, replayed observations/ticks emit no duplicate completion, and unrelated/non-M4 tasks cannot complete the root
- Planner context: at most four normalized inventory requirements and 640 characters expose exact count, family total, required count, satisfaction, and root status; lifecycle propagation remains independent of this text
- Compatibility: generic GoalVerifier, global TaskSystem inventory-family semantics, Planner schema, priority order, deadlines, success thresholds, M1, M2, and M3 remain unchanged
- Validation: five exact gate cases, 100 Memory/TaskSystem definitions, 47 M4 deadline definitions, all 743 definitions across 35 non-live Python files (744 repository definitions total), and six Node suites with 52 internal PASS cases; Python compilation, Probe 21 eight-file hashes, protocol identity, JSON, capability consistency, credential scan, and repository checks pass
- Status: passed offline; no live episode ran in this gate round
- Authorization: exactly one fresh BM-012 Probe 22 only after this gate commit is pushed; do not run it in this round

## BM-012 Live Evidence

### Probe 21: Ready-Task Gate Held; Recovery Root Ignored Inventory-Family Completion

- Episode: `m4_episode_20260714_073801_99ea1735`
- Session: `ce75c8dc-5d3`
- Level: `m4_episode_20260714_073801_99ea1735_bm012`
- Frozen code: `84ca601`; protocol and BM-012 task-contract hashes unchanged
- Prior gate: 61 machine-readable reports emitted 37 `retain_unverified_goal`, 24 `suppress_until_bound_task_machine_completion`, and zero allow decisions; task `7790c984` activated at event 814, failed at event 851, and event 974 suppressed generic completion after event 970 placed the table and event 973 achieved the GoalVerifier rule
- Runner review: event 318's placement-replan `empty_plan` recovered through seven sibling task reconciliations at events 963-968, successful placement at event 970, wooden-pickaxe craft at event 1491, and root completion at event 1495
- Earliest unrecovered transition: event 1504 selected an exact-`oak_log` recovery for stale blocked task `d37f41ea`; event 1511 created task `25fa2b53`, events 1512/1513 machine-completed it from `dark_oak_log:4`, but event 1519 still planned from exact `oak_log:0`
- Persistence: event 1532 executed the unnecessary move; the recovery root consumed nine cycles and event 1721 suspended it at dusk with six stale `Craft oak_planks from oak_logs` tasks still accepted
- Autonomous progress: nine goals attempted, three completed, five failed, and one interrupted across 77 cycles; the table and wooden pickaxe recovered, but no stone-pickaxe or iron progression followed
- Planner/actions: 77 real calls, 73 schema-valid, 278025 tokens, maximum 27905 ms; 64 actions attempted and 38 succeeded, including move 17/21, dig 11/12, craft 6/7, place 3/23, and equip 1/1
- Interrupts: 18 triggers and 17 recoveries; 17 task-deadline triggers recovered, while the final dusk-shelter trigger suspended the root
- Last valid machine state: event 1787, health/food 20, world time 11752, connected zero-death lifecycle, `dark_oak_log:4`, `oak_log:4`, `oak_planks:3`, `stick:2`, `wooden_pickaxe:1`, and no iron
- Deadline: start 34051.656, deadline 34651.656, Agent/evidence end 34651.671; elapsed 600.015 seconds, result `episode_deadline`, and independent deadline checks failed closed
- Eligibility: 64/74 checks passed with ten issues; BM-012 remains 0/3 after twenty-one attempts
- Skills: baseline remained off; selected, executed, quarantined, vision, and multi-agent contributions were zero
- Round boundary: this was the only live episode; Probe 21 authorization is consumed, no code fix or second run occurs, and Probe 22 remains locked behind the offline readiness-recovery root-completion gate
- Evidence: `logs/benchmarks/m4/m4_episode_20260714_073801_99ea1735/`

### Probe 20: Post-Place Gate Activated; Ready-Task Verification Bypassed Criteria

- Episode: `m4_episode_20260714_061205_a52cd5f7`
- Session: `1f007d99-08f`
- Level: `m4_episode_20260714_061205_a52cd5f7_bm012`
- Frozen code: `06957bd`; protocol and BM-012 task-contract hashes unchanged
- Prior gate: event 269 accepted exact post-place evidence, events 271/288 carried its two bounded observations, event 273 completed the task, and event 278 verified placement; a second successful placement activated at event 1063, while nine unsuccessful results failed closed
- Projection scope: Observer directly saw both successful tables, so live observations recorded `projected=false`; the omission-projection branch remains exact-offline validated rather than live-exercised
- Runner review: event 820's malformed torch response recovered through the event-1083 table, event-1116 stone-pickaxe craft, and event-1172 machine-verified iron dig; it is not the earliest unrecovered transition
- Earliest unrecovered transition: readiness event 1186 exposed a ready `Mine iron ore` task, plan event 1189 required `raw_iron:2` and supplied a valid dig, but pre-plan verifier event 1193 accepted generic root completion from existing `raw_iron:1` without an inventory delta
- Persistence: goal indices 11..24 each selected `Mine iron ore` from the ready frontier; fourteen real schema-valid plans required `raw_iron:2`, fourteen verifier events accepted `raw_iron:1/1`, and zero actions executed after event 1172
- Autonomous progress: 24 goals selected, 23 completed, 1 failed, and 0 interrupted across 63 cycles; one raw iron was acquired from a verified iron-ore dig
- Planner/actions: 63 real calls, 62 schema-valid, 224707 tokens, maximum 8344 ms; 51 actions attempted and 39 succeeded, including move 10/13, dig 18/18, craft 9/9, and place 2/11
- Interrupts: five task-deadline interrupts and five matching recoveries; no hostile, health, hunger, dusk, or night interrupt fired
- Terminal machine state: health/food 20, world time 8295, connected zero-death lifecycle, position `(100.434373,132,-40.499992)`, raw iron 1, stone pickaxe 1, and four nearby iron-ore blocks
- Deadline: start 28892.078, deadline 29492.078, Agent end 29301.562, manifest end 29301.609; Agent elapsed 409.484 seconds, evidence elapsed 409.531 seconds, and 190.516 seconds remained
- Eligibility: 68/74 checks passed with six issues; BM-012 remains 0/3 after twenty attempts
- Skills: baseline remained off; selected, executed, quarantined, vision, and multi-agent contributions were zero
- Round boundary: this was the only live episode; no code fix, second run, or new authorization exists before a bounded offline ready-task GoalVerifier criteria-binding gate passes and is pushed
- Evidence: `logs/benchmarks/m4/m4_episode_20260714_061205_a52cd5f7/`

### Probe 19: Placement Succeeded; Machine Observation Lost the Table

- Episode: `m4_episode_20260714_043836_18afe612`
- Session: `4593446f-4ff`
- Level: `m4_episode_20260714_043836_18afe612_bm012`
- Frozen code: `692cf77`; protocol and BM-012 task-contract hashes unchanged
- Prior gate: health and food remained 20 in all 155 complete observations; no critical-health action or policy report occurred, so the Probe 18 deadlock did not recur and the branch was not exercised
- Runner review: event 424's coal `empty_plan` recovered through goal 8 and machine-verified `coal:+1` at dig event 574; it is not the earliest unrecovered transition
- Earliest unrecovered transition: action event 621 verified `crafting_table` at `(106,136,-36)`, but observation event 623 exposed no nearby table and did not close the placement task; event 686 first failed because the same target was already occupied
- Persistence: the torch root made 40 real schema-valid Planner calls, issued 15 place actions and two craft actions, and repeated the occupied target fourteen times before event 1419 ended it at 40 cycles
- Recovery boundary: goal 10 moved adjacent, observation event 1437 exposed the original table, and event 1445 machine-verified placement completion; the machine objective recovered after 221.016 seconds, but the 209.688-second root cost and 4080 world ticks were not recovered
- Autonomous progress: 15 goals selected, 10 completed, 5 failed, and 0 interrupted across 89 cycles; coal, twelve cobblestone, and a stone pickaxe were obtained, but no iron source action occurred
- Planner/actions: 89 real calls, 85 schema-valid, 322059 tokens, maximum 19297 ms; 66 actions attempted and 41 succeeded, including move 9/11, dig 19/22, craft 11/11, place 2/20, and shelter 0/2
- Interrupts: all 23 triggers and 23 recoveries were task-deadline churn inside the torch root; no hostile, health, hunger, dusk, or night interrupt fired
- Shelter cascade: preparation started at world time 10039 with 103.641 seconds remaining; two bounded shelter actions timed out, their bridge recoveries succeeded, and the final move crossed the deadline
- Last complete machine state: event 1987, health/food 20, world time 11599, connected zero-death lifecycle, position `(106.5,128,-35.5)`, coal 1, cobblestone 7, and stone pickaxe 1
- Deadline: start 23290.250, deadline 23890.250, Agent end 23890.265, manifest end 23890.281; Agent overrun 0.015 seconds, evidence overrun 0.031 seconds, and one action result was recorded post-deadline
- Eligibility: 64/74 checks passed with 10 issues; BM-012 remains 0/3 after nineteen attempts
- Skills: baseline remained off; selected, executed, quarantined, vision, and multi-agent contributions were zero
- Round boundary: this was the only live episode; the subsequent offline post-place crafting-table machine-observation gate authorized Probe 20, and that authorization is now consumed
- Evidence: `logs/benchmarks/m4/m4_episode_20260714_043836_18afe612/`

### Probe 18: Pathfinder Cascade Absent; Critical-Health Actions Deadlocked

- Episode: `m4_episode_20260714_032037_563a7040`
- Session: `5f33e80d-10a`
- Level: `m4_episode_20260714_032037_563a7040_bm012`
- Frozen code: `e78ccfc`; protocol and BM-012 task-contract hashes unchanged
- Prior gate: no deadline-bound action failure, bridge recovery, navigation-recovery report, or `PathStopped`; pre-critical navigation succeeded 8/10, and event 51/event 699 recovered after the two bounded completion failures
- Runner review: event 303's placement `empty_plan` recovered through successful placement at event 379 and machine goal completion at event 383; it is not the earliest unrecovered transition
- Hostile transition: event 781 interrupted `Place crafting_table`, preserved seven frontier tasks, and selected an emergency retreat; event 785 moved successfully while health fell from 20 to 2.33 and hostile distance rose from 2.4 to 6.4 blocks
- Earliest unrecovered transition: immediate-threat goal event 796, real schema-valid plan event 807, and ActionVerifier event 812 produced an accepted retreat move; observation event 814 had health 3.33/food 17 and action event 817 rejected it at 0 ms with `Pre-condition failed: Health critical`
- Persistence: fourteen survival actions were blocked by the same precondition, including thirteen moves and one craft; critical-health goal indices 12..24 all failed, and the 24-goal limit ended the run
- Autonomous progress: 24 goals selected, 7 completed, 16 failed, and 1 interrupted across 46 cycles; wood, crafting tables, wooden pickaxe, coal/charcoal, and torches completed, but no iron source action occurred
- Planner: 46/46 calls were real, 44 schema-valid, total usage 170939 tokens, and maximum duration 28203 ms; the later `finish_reason=length` malformed response is downstream
- Actions: 47 attempted and 28 successful; move 8/23, dig 9/9, craft 9/10, and place 2/5; ActionVerifier accepted 44 and rejected 3
- Interrupts: one task deadline recovered, one hostile interrupt preserved the frontier, and event 868 escalated it to critical health; no critical-health recovery completed
- Terminal machine state: connected bot, health 3.33, food 17, world time 7230, position `(109.689280,136,-21.5)`, zero deaths/respawns, and no raw iron or iron ore
- Deadline: start 18603.562, deadline 19203.562, Agent end 18959.093, manifest end 18959.125; 244.437 seconds remained and no post-deadline execution occurred
- Eligibility: 67/74 checks passed with 7 issues; BM-012 remains 0/3 after eighteen attempts
- Skills: baseline remained off; selected, executed, quarantined, vision, and multi-agent contributions were zero
- Round boundary: this was the only live episode; the subsequent offline critical-health survival-action precondition gate authorized Probe 19, and that authorization is now consumed
- Evidence: `logs/benchmarks/m4/m4_episode_20260714_032037_563a7040/`

### Probe 17: Feedback Gate Recovered; Pathfinder Stayed Stopped After Recovery

- Episode: `m4_episode_20260714_015708_91dfb104`
- Session: `5bbb10cb-8c2`
- Level: `m4_episode_20260714_015708_91dfb104_bm012`
- Frozen code: `8ebacf9`; protocol and BM-012 task-contract hashes unchanged
- Prior gate: event 311 live-exercised fail-closed rejection of repeated reference `(103,135,-31)` with zero tasks/actions; event 354 selected supplied candidate `(104,135,-31)` and event 367 placed the table successfully
- Runner review: event 316's placement `empty_plan` recovered at event 367 after 9.547 seconds; it is not the earliest unrecovered transition
- Earliest unrecovered transition: after action event 555 exhausted 60000 ms, recovery event 550 reported `bridge_reconnected=true` and machine state confirmed; event 578 was the first fresh navigation to fail immediately with `Path was stopped before it could be completed`
- Persistence: all 19 later `move_to` actions failed with the same pathfinder-stopped error and no position change; 18 targeted observed coal ore `(115,133,-30)` and event 1801 also failed toward previously reachable `(104,136,-31)`
- Isolation: craft event 1823, bounded shelter event 1845, and wait event 2014 succeeded after the recovery, so generic bridge transport remained usable while pathfinder navigation did not
- Autonomous progress: 9 goals selected, 5 completed, 3 failed, and 1 interrupted across 95 cycles; wood, crafting table, wooden pickaxe, and a verified dusk shelter completed, but no iron source was observed or mined
- Planner: 95/95 calls were real, 94 were schema-valid, one was the intentional fail-closed feedback rejection, 339769 tokens were recorded, and maximum call duration was 9719 ms
- Actions: 46 attempted and 22 successful; move 6/27, dig 6/6, craft 7/7, place 1/3, bounded shelter 1/1, and wait 1/2
- Interrupts: 48 unique task-deadline triggers recovered 107 unique expired tasks; one dusk trigger suspended mining, preserved the frontier, and selected the aligned shelter goal
- Shelter: event 1845 placed 9/9 final blocks; machine verification passed at event 1841 / world time 10728 and the result terminal state retained the sealed cell
- Terminal machine state: connected bot, health/food 20/20, world time 12108, position `(109.5,136,-33.5)`, zero deaths/respawns, and no raw iron or iron ore
- Deadline: start 13593.39, deadline 14193.39, Agent end 14193.406, manifest end 14193.453; no post-deadline Planner call or plan occurred, but one in-flight wait result logged 0.016 seconds late and failed closed
- Eligibility: 55/74 checks passed with 19 issues; BM-012 remains 0/3 after seventeen attempts
- Skills: baseline remained off; selected, executed, quarantined, vision, and multi-agent contributions were zero
- Round boundary: this was the only live episode; the subsequent offline pathfinder-readiness gate passes and authorizes exactly one fresh Probe 18 only after its commit is pushed
- Evidence: `logs/benchmarks/m4/m4_episode_20260714_015708_91dfb104/`

### Probe 16: Bridge Stable; Replan Repeated Rejected Placement

- Episode: `m4_episode_20260714_003738_56b0cd9f`
- Session: `4ae6c3ba-783`
- Level: `m4_episode_20260714_003738_56b0cd9f_bm012`
- Frozen code: `a7b9d42`; protocol and BM-012 task-contract hashes unchanged
- Prior gate: no deadline-bound action failures, bridge-recovery events, or `Not connected to bot bridge` action errors occurred; `move_to` succeeded 10/10 and the terminal bot remained connected, so the offline bridge gate was not live-exercised
- Earliest causal blocker: event 283 rejected `(106,135,-29)`, supplied four adjacent references, and prohibited retry; replan events 292/294 repeated the rejected reference and action event 304 failed again with unchanged position and inventory
- Planner lineage: call `llm-7aea1a8f6bfa4281`, root `root-2a952d3aa6424a33`, response SHA-256 `298670e24839bb6d9be9eec99e2926129caf26c52f3eb6bad16bd9fbb688369e`, 1003 bytes, 3452 ms, 3498 tokens, real and schema-valid
- Persistence: 20 actions attempted the rejected reference; the original placement root made 40 real schema-valid calls with 17 replans and 17 verifier rejections before failing at event 1024
- Delayed recovery: adjacent reference `(107,135,-29)` succeeded at event 1413 / monotonic 9205.468, 268.812 seconds after event 304; the machine objective recovered but the failed root and elapsed budget did not
- Autonomous progress: 14 goals selected, 12 completed, and 2 failed across 103 cycles; the Agent gathered wood, placed the table, made torches and planks, then entered dusk shelter preparation without iron progression
- Planner: 103 calls, 101 real schema-valid responses, 2 transport failures, 358579 total tokens, and maximum duration 10156 ms
- Actions: 53 attempted and 30 successful; move 10/10, dig 8/8, craft 11/11, place 1/23, and bounded shelter 0/1
- Interrupts: 46 unique task-deadline triggers each emitted one recovery; no duplicate expired task ID or concurrent-root violation occurred
- Downstream shelter: event 2066 rejected the bounded sealed cell mutation-free because no grounded neighbor existed; event 2062 scheduled relocation to `(114.5,136,-45.5)`, but only 1.688 seconds remained and no relocation action ran
- Terminal machine state: health/food 20/20, world time 12154, connected bot, zero deaths/respawns, inventory `oak_planks:13`, `stick:5`, `torch:4`, `crafting_table:1`, `dirt:1`, and `wooden_pickaxe:1`; raw iron and iron ore remained zero
- Deadline: start 8836.25, deadline 9436.25, Agent end 9436.265, manifest end 9436.343; one Planner call and one error plan appeared after the deadline, no post-deadline action ran, and the 0.015-second Agent overrun failed closed
- Eligibility: 66/74 checks passed with 8 issues; BM-012 remains 0/3 after sixteen attempts
- Skills: baseline remained off; selected, executed, quarantined, vision, and multi-agent contributions were zero
- Round boundary: this was the only live episode; no code fix, second run, or next live authorization occurs before the new offline gate passes and is pushed
- Evidence: `logs/benchmarks/m4/m4_episode_20260714_003738_56b0cd9f/`

### Probe 15: Required Tool Equipped Live; Navigation Timeout Left Bridge Offline

- Episode: `m4_episode_20260713_211548_0605186f`
- Session: `7b62bffb-ce9`
- Level: `m4_episode_20260713_211548_0605186f_bm012`
- Frozen code: `b5a74d4`; protocol and BM-012 task-contract hashes unchanged
- Prior gate: 19/19 dig actions emitted equip policy evidence; 13/13 stone digs required, selected, equipped, and confirmed `wooden_pickaxe`; 12 succeeded and acquired 12 cobblestone
- Recovery review: event 914 removed one stone without a drop, but event 936 acquired the twelfth cobblestone and event 940 machine-verified the goal; the prior held-item mismatch did not recur
- Earliest unrecovered transition: event 981 / monotonic 90944.203 / cycle 41, `move_to(108,130,-34)` timed out after 60000 ms with no replay and no bridge reconnect while 281.859 seconds remained
- Persistence: all 16 later actions failed, including 15 `Not connected to bot bridge` results; five goals completed before the transition and no action succeeded afterward
- Autonomous progress: 7 goals selected, 5 completed, and 2 failed across 82 cycles; the Agent gathered six logs, placed a crafting table, crafted a wooden pickaxe, and acquired 12 cobblestone, but acquired no iron
- Planner: 81 real calls were schema-valid; one deadline-time request timed out; 82 Planner events consumed 271917 tokens with zero schema-invalid real responses
- Actions: 61 attempted and 39 successful; move 14/30, dig 18/19, craft 6/7, and place 1/5
- Interrupts: 24 unique task-deadline triggers each recovered and expired 170 unique tasks, but recovery did not restore bridge transport
- Last complete machine state: event 962 / world time 5228 / health 20 / hunger 20 / uninterrupted lifecycle / inventory `oak_sapling:1`, `oak_log:3`, `stick:2`, `oak_planks:3`, `dirt:3`, `wooden_pickaxe:1`, and `cobblestone:12`
- Deadline: start 90626.062, deadline 91226.062, Agent and manifest end 91226.078; no Planner call, plan, or action occurred strictly after the deadline, while six housekeeping events and the 0.016-second overrun failed closed
- Eligibility: 54/74 checks passed with 20 issues; BM-012 remains 0/3 after fifteen attempts
- Skills: baseline remained off; selected, executed, quarantined, vision, and multi-agent contributions were zero
- Round boundary: this was the only live episode; no code fix, second run, or next live authorization occurs before the new offline gate passes and is pushed
- Evidence: `logs/benchmarks/m4/m4_episode_20260713_211548_0605186f/`

### Probe 14: Player Occupancy Passed Live; Stone Dug Without Required Tool

- Episode: `m4_episode_20260713_201657_0e6b213e`
- Session: `ff915dec-db4`
- Level: `m4_episode_20260713_201657_0e6b213e_bm012`
- Frozen code: `a6e13c1`; protocol and BM-012 task-contract hashes unchanged
- Prior gate: 21 same-reference player-collision placements were rejected at zero duration with 21 replan calls; action event 1554 used adjacent reference `(107,135,-29)` and placed the crafting table at `(107,136,-29)` in 46 ms
- Prior failure recurrence: Probe 13's placement `blockUpdate` timeout did not recur; the player-occupancy gate recovered live
- Earliest unrecovered transition: action event 1724 / monotonic 87571.656 / cycle 90 accepted `dig stone` at `(114,133,-29)` because `wooden_pickaxe:1` was available, but the backend held `oak_planks`, removed stone, and acquired no cobblestone
- Repetition: seven stones were removed without drops, every completed attempt retained `oak_planks` in hand, zero stone digs succeeded, and cobblestone inventory delta stayed zero
- Autonomous progress: 7 goals selected, 4 completed, 2 failed, and 1 interrupted across 98 cycles; crafting table and wooden pickaxe progression completed, but no iron source or iron delta appeared
- Planner: 98/98 calls were real and schema-valid, with zero output or transport recovery and 343212 total tokens
- Actions: 50 attempted and 20 successful; move 7/8, dig 6/14, craft 6/6, and place 1/22
- Interrupts: 52 unique task-deadline triggers each recovered, then one dusk interrupt suspended cobblestone progression; no duplicate task expiry occurred
- Last complete machine state: event 1882 / world time 11853 / health 20 / hunger 20 / uninterrupted lifecycle / inventory `wooden_pickaxe:1`, `oak_log:3`, `stick:2`, `dirt:3`, and `oak_planks:3`
- Deadline: start 87099.828, deadline and Agent end 87699.828, manifest end 87699.843; no Planner call, plan, or action occurred strictly after the deadline, while independent duration and terminal checks failed closed
- Eligibility: 54/74 checks passed with 20 issues; BM-012 remains 0/3 after fourteen attempts
- Skills: baseline remained off; selected, executed, quarantined, vision, and multi-agent contributions were zero
- Round boundary: this was the only live episode; no code fix, second run, or next live authorization occurs in this round
- Evidence: `logs/benchmarks/m4/m4_episode_20260713_201657_0e6b213e/`

### Probe 13: Pickup Gate Passed Live; Place Target Matched Player Cell

- Episode: `m4_episode_20260713_184611_5bd188fc`
- Session: `d37a5ff5-44d`
- Level: `m4_episode_20260713_184611_5bd188fc_bm012`
- Frozen code: `05f0397`; protocol and BM-012 task-contract hashes unchanged
- Pickup gate: event 96 rejected direct distance 1.014387, attempted one `GoalBlock` fallback with 5317 ms remaining, reached 0.875760, and observed `oak_log:+1`
- Autonomous progress: 9 goals selected, 7 completed, 1 interrupted, 1 failed; wooden pickaxe and four torches crafted; `iron_ore` first observed at event 428 / distance 5; zero iron acquired
- Planner: 60/60 real responses schema-valid, zero transport errors, zero empty plans, 211913 total tokens
- Actions: 51 attempted, 37 successful; 15 move, 11 dig, 12 craft, and 13 place attempts
- Earliest unrecovered transition: event 974 / monotonic 82047.437 / cycle 40, `place(crafting_table,103,135,-31)` targeting the player's own floored feet cell `(103,136,-31)`
- Repetition: seven post-transition crafting-table placement timeouts at the same target across the interrupted placement and shelter goals; zero later successful place actions
- Interrupts: 14 unique task-deadline interrupts all recovered, then one dusk-shelter interrupt paused the placement frontier
- Last complete machine state: event 1362 / time 11844 / health 20 / hunger 20 / uninterrupted lifecycle / inventory without iron
- Deadline: start 81646.078, deadline and Agent end 82246.078, manifest end 82246.093; no Planner call, plan, or action after the deadline, but independent duration and terminal checks fail closed
- Eligibility: 54/74 checks passed; BM-012 remains 0/3
- Round boundary: this was the only live episode; no code fix or second run is authorized
- Evidence: `logs/benchmarks/m4/m4_episode_20260713_184611_5bd188fc/`

### Probe 12: Dig Postcondition Passed; Pickup Completion Was Ungrounded

- Episode: `m4_episode_20260713_173959_8843046c`
- Session: `72f32a34-ee9`
- Level: `m4_episode_20260713_173959_8843046c_bm012`
- Frozen gate: committed and pushed `65fa34f`; preflight passed under unchanged protocol/task-contract hashes and exact `600/24/40/320` controls
- Prior hypothesis: five strict digs emitted `m4-expected-drop-pickup-postcondition-v1`; three acquired their expected drops, two failed closed, zero false-positive successes occurred, and the first failure at event 72 recovered through successful digs at events 97 and 116
- Runner candidates overridden: event 29's movement-tolerance miss was followed by a successful exact-target dig at event 51, and event 148's miss was followed by removal of the exact target at event 169
- First unrecovered transition: action event 169 / monotonic 77764.312 / cycle 8 removed `oak_log` at `(93,138,-36)` and detected entity 871, but inner pickup navigation reported success while final distance remained 2.091618 blocks against a 1-block goal; inventory stayed `dark_oak_log:3`
- Recovery cascade: immediate replanning produced a deeper dig, a task-deadline interrupt suppressed it, and action event 212 exhausted a 60-second move deadline and disconnected the bridge; 39 later actions failed `Not connected to bot bridge`
- Planner: 117 call events, 115 real responses, 115/115 schema-valid, 115 passing opportunity-trigger reports, one transport recovery, one final deadline timeout, maximum latency 50.360 seconds, 296133 tokens, and zero reasoning bytes
- Autonomy: three failed roots across 117 cycles; 68 unique task-deadline triggers produced 68 recoveries over 92 unique expired tasks with no duplicate expiry or concurrent-root violation
- Actions: 3/47 succeeded; `dig` succeeded 3/5 and `move_to` 0/42; all 47 actions were verifier-accepted, 44 failures suppressed legacy reflection, and zero actions succeeded after event 169
- Last complete machine state: observation event 192 / monotonic 77816.031, world time 2994, health/food 20, position `(93.34238234601303,140.07472379453523,-35.48680946380416)`, inventory `dark_oak_log:3`, and zero deaths/respawns; 147 later observations were incomplete after bridge loss
- Resource and shelter: zero iron-source actions or iron delta, five shelter verification events with zero passes, and canonical terminal state failed closed
- Deadline: start 77672.828, absolute boundary 78272.828, Agent end 78272.843, evidence end 78272.859, and last action 12.157 seconds before the boundary; eight post-boundary bookkeeping/planner events but zero post-deadline actions made three deadline checks fail
- Eligibility: 54/74 checks passed with 20 issues; BM-012 remains 0/3
- Skills: baseline remained off; selected, executed, quarantined, vision, and multi-agent contributions were zero
- Round boundary: this was the only live episode; no code fix, second run, or next live authorization occurs in this round
- Evidence: `logs/benchmarks/m4/m4_episode_20260713_173959_8843046c/`

### Probe 11: Trigger Gate Passed; Removed Oak Drops Were Not Acquired

- Episode: `m4_episode_20260713_163910_b9c148fa`
- Session: `c6939e6f-d6e`
- Level: `m4_episode_20260713_163910_b9c148fa_bm012`
- Frozen gate: committed and pushed `d37b201`; preflight passed under unchanged protocol/task-contract hashes and exact `600/24/40/320` controls
- Prior hypothesis: 110/110 real calls were schema-valid; all 110 trigger-grounding reports passed over 117/117 valid string triggers, malformed trigger/task count was zero, and the rejection branch was not exercised
- First unrecovered transition: action event 81 / monotonic 74061.859 / cycle 4 removed `oak_log` at `(93,139,-36)` but returned success with no expected-drop pickup, no inventory delta, and no collection attempt
- Confirmation: action event 152 removed a second oak log, detected its drop 2.084 blocks away, attempted collection, and timed out after 6000 ms; inventory stayed `dark_oak_log:1`
- Downstream: action event 176 exhausted a 60-second navigation deadline; observation event 172 lost position/lifecycle state, and 32 later actions failed `Not connected to bot bridge`
- Autonomy: three curriculum roots, all failed; 112 cycles, 112 Planner-call events, 39 actions, 71 task-deadline interrupts with 71 recoveries, and no external step script
- Actions: 4/39 succeeded; `dig` 3/3 removed blocks but only 1/3 acquired a drop, while `move_to` succeeded 1/36
- Resource state: initial and terminal iron counts were zero, no iron-source action occurred, and the last valid machine inventory was `dark_oak_log:1`
- Lifecycle: 15 observations retained complete machine/lifecycle state through event 154 with zero deaths/respawns; the next 137 observations were incomplete after bridge loss, so terminal continuity failed closed
- Deadline: start 74022.953, absolute boundary 74622.953, manifest end 74622.968; no Planner call, plan, or action occurred after the boundary, but two bookkeeping events at +0.015 seconds made duration/no-post-deadline checks fail
- Eligibility: 54/74 checks passed with 20 issues; BM-012 remains 0/3
- Skills: baseline remained off; selected, executed, quarantined, vision, and multi-agent contributions were zero
- Round boundary: this was the only live episode; no code fix, second run, or next live authorization occurs in this round
- Evidence: `logs/benchmarks/m4/m4_episode_20260713_163910_b9c148fa/`

### Probe 10: Typed Rejection Absent; Object Trigger Crashed Readiness

- Episode: `m4_episode_20260713_154035_5459816d`
- Session: `d6831d21-e78`
- Level: `m4_episode_20260713_154035_5459816d_bm012`
- Frozen gate: committed and pushed `d11c633`; preflight passed under unchanged protocol and task-contract hashes
- Prior hypothesis: 50/50 real calls were schema-valid, zero typed inventory-count issues and zero output-recovery events occurred; the Probe 9 failure did not recur and the recovery branch was not live-exercised
- First unrecovered transition: call event 262 / `llm-0cd847107eb747db`, task event 265, and plan event 266 at monotonic 70596.703 / cycle 12 accepted an object-valued `opportunity_triggers` item for `Mine coal ore`
- Confirmation: nine malformed-trigger plans entered the task frontier; the unguarded goal-selection readiness call after event 1185 raised `'dict' object has no attribute 'lower'` in `TaskSystem._opportunity_bonus` and the runner did not emit `autonomous_end`
- Before state: health/food 20, world time 1783, inventory `oak_log:5`, `oak_planks:4`, `oak_sapling:1`, and machine-observed `coal_ore` at `(115,134,-29)`
- Autonomy: two curriculum goals; the six-oak-log bootstrap completed in 10 cycles, while `Collect coal or charcoal for torches` failed at 40 cycles before the next goal selection crashed
- Actions: 30 attempted, 14 successful; six successful oak-log digs, five successful crafts, zero iron-source actions, and no executable learned skill
- Interrupts: 21 unique task-deadline triggers and 21 recoveries covering 88 unique expired tasks; the interrupt cascade is downstream
- Last machine observation: event 1151, health/food 20, world time 6483, inventory `oak_log:3`, `oak_planks:6`, `stick:4`, `oak_sapling:1`, `crafting_table:1`, and uninterrupted zero-death lifecycle
- Deadline: start 70508.437, absolute boundary 71108.437, last canonical event 70832.671, and 275.766 seconds remained; no Planner call, plan, or action occurred after the boundary, but the aborted result is duration-ineligible
- Eligibility: 67/74 checks passed with seven issues, including missing `autonomous_end`, terminal resource verification, iron delta/source actions, terminal machine verification, and result duration eligibility; BM-012 remains 0/3
- Round boundary: this was the only live episode; no code fix, second run, or new live authorization occurs in this round

### Probe 9: World-State Policy Exercised; Typed Schema Rejection Failed Root

- Episode: `m4_episode_20260713_143233_5fe50b8f`
- Session: `53044286-3a8`
- Level: `m4_episode_20260713_143233_5fe50b8f_bm012`
- Frozen gate: committed and pushed `9d370bf`; preflight passed under unchanged protocol and task-contract hashes
- Reconciliation retest: six policy events; event 1797 completed five `nearby_block_present=oak_planks` tasks from machine block state, with no satisfied world-state root later selected; exact crafting-table boundary not reached
- First unrecovered transition: call event 115 / `llm-3bbb8772f5f0473e`, error plan event 116, `empty_plan` event 120, and root failure event 122 at monotonic 66480.359 / cycle 6
- Before state: `oak_log:2`, health/food 20, world time 1059, and one observed oak log at `(93,137,-36)` after two successful source digs
- Schema evidence: one of 97 real calls was invalid with `subtask[2]:preconditions_inventory_count_invalid:oak_log`; strict rejection passed, zero equivalent normalization occurred, and no action from that response executed
- Recovery gap: zero `m4_planner_output_recovery` events; the existing policy did recover one independent transport error
- Autonomy: seven goals, three completed, three failed, one interrupted; one machine-verified 9/9 shelter was built after the resource chain stalled
- Actions: 43 attempted, 22 successful; four successful digs, one craft, one bounded shelter success, and zero iron-source actions
- Interrupts: 57 triggers and 57 recoveries; 56 distinct expired-task triggers plus one dusk shelter trigger, with 126 unique expired tasks and no repeated expired task
- Deadline: Agent ended exactly at 67030.984; manifest ended at 67031.062, 0.078 seconds late; the last wait action was recorded unsuccessful exactly at the deadline and no Planner call or plan occurred after it
- Eligibility: 55/74 checks passed, 19 issues, no terminal resource verification, no iron delta, deadline-ineligible, BM-012 remains 0/3
- Round boundary: this was the only live episode; no code fix or second BM-012 run is authorized

### Probe 8: Occupancy Gate Passed; Satisfied World-State Task Reentered

- Episode: `m4_episode_20260713_132135_a98f59e5`
- Session: `e1c11192-bd9`
- Level: `m4_episode_20260713_132135_a98f59e5_bm012`
- Preflight: passed with unchanged protocol/task-contract hashes, empty inventory, fresh time-0 survival/normal level, zero-death lifecycle baseline, and exact `600/24/40/320` controls
- Result: ineligible; BM-012 remains 0/3, 55/74 independent checks passed, no terminal resource event was emitted, and no iron-source action occurred
- Prior gate live evidence: event 243 rejected occupied target `(93,135,-38)` under `m4-place-target-occupancy-v1`, event 248 recorded zero execution duration and a target-aware replan request, and event 278 successfully placed on air at `(92,135,-37)`; the Probe 7 timeout did not recur
- Earliest invalid transition: replan task `2f1081b4`, accepted at event 260 with `nearby_block_present=crafting_table`, remained accepted after event 278 supplied exact machine proof and parent goal event 282 completed; inventory-only pre-goal reconciliation did not close it, so event 286 selected it as `ready_task_selected` at monotonic 62264.359
- Confirmation: stale-root plan event 298 accepted four descendants before GoalVerifier event 307 immediately completed the already-satisfied root. The resulting two `Dig dirt to clear space` roots consumed 80 cycles; 27 dirt digs succeeded, but no root GoalVerifier event completed either root
- Goals: ten roots; seven completed, two failed, and one was interrupted. Wood, crafting-table creation and placement, and a verified shelter completed; one dirt root hit 40 cycles, a second spent 40 cycles before dusk preemption, and night maintenance ended at the episode deadline
- Planner: 103 calls; 102 real and schema-valid responses, one next-cycle transport recovery, 345446 tokens, maximum latency 12.093 seconds, zero retries, zero reasoning bytes, and zero provider-control violations
- Actions: 47/55 succeeded; `move_to` 8/8, `dig` 31/36, `craft` 3/4, `place` 1/2, `build_shelter_cell` 3/3, and `wait` 1/2. ActionVerifier accepted 54 and rejected the one occupied placement
- Tasks and interrupts: 108 tasks produced 340 transitions; final states were 30 completed, 71 failed, and seven accepted. All 50 interrupt events had matching recoveries; 49 were unique task deadlines and one was dusk
- Shelter and lifecycle: two of 16 shelter verifications passed with 9/9 attributed positions; all three bounded shelter actions succeeded. Of 159 observations, 158 carried lifecycle state with zero valid deaths or respawns; the deadline-time fallback observation omitted lifecycle state, so the independent lifecycle and terminal checks failed closed
- Terminal state: the canonical result retained health/food 20, time 12232, online bot, and inventory `oak_planks:8`, `dark_oak_log:2`, `dirt:27`, `crafting_table:1`, `oak_sapling:1`; target iron remained zero
- Deadline: start 62176.359, absolute boundary and Agent end 62776.359, manifest end 62776.406. The final bounded wait returned at the boundary as failed and not accepted within deadline; one boundary action event made `no_post_deadline_execution` false, while no Planner call or plan occurred after the boundary
- Skills: baseline remained off; selected, executed, successful, failed, quarantined, vision, and multi-agent contributions were zero
- Round boundary: this was the only live episode; no code fix, second BM-012 run, or new live authorization occurs in this round
- Evidence: `logs/benchmarks/m4/m4_episode_20260713_132135_a98f59e5/`

### Probe 7: Requested Item Equipped; Placement Target Was Occupied

- Episode: `m4_episode_20260713_121120_75d9ae7d`
- Session: `81a9bdef-b92`
- Level: `m4_episode_20260713_121120_75d9ae7d_bm012`
- Preflight: passed with unchanged protocol/task-contract hashes, empty inventory, fresh daylight level, zero-death lifecycle baseline, and exact `600/24/40/320` controls
- Result: ineligible; BM-012 remains 0/3, 66/74 independent checks passed, no terminal resource event was emitted, and no iron-source action occurred
- Prior gate live evidence: all 17 place results recorded `crafting_table` as requested and equipped, `requested_item_equipped=true`, and policy `m4-place-requested-item-equip-v1`; the Probe 6 sapling placement and empty-hand cascade did not recur
- Earliest invalid transition: Planner event 245 / call `llm-433910d52edd4327` and plan event 247 chose dirt reference `(93,134,-38)` without checking target `(93,135,-38)`, which observation event 255 already showed as `dark_oak_log`; ActionVerifier event 273 accepted the action from inventory evidence and action event 278 timed out after 5.062 seconds
- Confirmation: the next 16 place actions used reference `(93,134,-36)` while every immediately preceding observation showed target `(93,135,-36)` as `grass_block`; all 16 timed out waiting for the same impossible `blockUpdate`, with the crafting table still equipped and retained
- Goals: six roots; three completed, two failed, one interrupted. Wood gathering and crafting-table creation completed, the 40-cycle placement root failed, and survival preemption later built a verified shelter
- Planner: 54 calls; 51 real and schema-valid responses, three recovered connection errors, 170941 tokens, maximum successful latency 22.078 seconds, zero retries, and zero reasoning bytes
- Actions: 26/44 succeeded; `move_to` 16/17, `dig` 5/5, `craft` 3/3, `place` 0/17, `build_shelter_cell` 1/1, and `wait` 1/1
- Tasks and interrupts: 55 tasks produced 175 transitions; final states were 12 completed, 38 failed, four accepted, and one active. All 22 interrupt triggers had recoveries; 21 were task deadlines and one was dusk, terminalizing 38 unique expired tasks
- Shelter and survival: one of eight shelter verifications passed with all 9/9 positions attributed to the bounded build; all 99 observations carried lifecycle state, with zero deaths and respawns. Terminal health/food were 20 and inventory was `dark_oak_log:4`, `oak_planks:2`, `crafting_table:1`, `dirt:5`
- Deadline: the absolute boundary was 58555.562. A bounded wait accepted before the boundary completed afterward; Agent ended at 58559.875 and manifest evidence at 58559.984, 4.313 and 4.422 seconds late, with one post-boundary action completion. The independent deadline checks rejected the run
- Skills: baseline remained off; selected/executed/quarantined contribution was zero
- Round boundary: this was the only live episode; no code fix, second BM-012 run, or new live authorization occurs in this round
- Evidence: `logs/benchmarks/m4/m4_episode_20260713_121120_75d9ae7d/`

### Probe 6: Placement Criterion Passed; Requested Item Was Not Equipped

- Episode: `m4_episode_20260713_112039_496a9152`
- Session: `19e3c9df-8e3`
- Level: `m4_episode_20260713_112039_496a9152_bm012`
- Preflight: passed with unchanged protocol/task-contract hashes, empty inventory, fresh daylight level, zero-death lifecycle baseline, and exact `600/24/40/320` controls
- Result: ineligible; BM-012 remains 0/3, 54/74 independent checks passed, no terminal resource event was emitted, and no iron-source action occurred
- Prior gate live evidence: Planner event 277 / call `llm-28be82216c5b42ed` was real and schema-valid; event 279 emitted one canonical `place(item=crafting_table,x=104,y=135,z=-31)` and `success_criteria.nearby_block_present=crafting_table`; all 129 real calls and placement-grounding reports passed, with zero rewrites
- Earliest invalid transition: observation event 273 showed the requested crafting table in inventory but `dark_oak_sapling` equipped; action event 298 at monotonic 55017.875 placed that sapling at the target, failed `placed block was not observed at the target`, and left the crafting table unplaced
- Confirmation: event 302 showed the sapling consumed and no held item; the next 30 place attempts all failed `must be holding an item to place` while connected observations continued to report `crafting_table:1`
- Source attribution: generic `createPlaceHandler` reads `params.item` only for post-placement comparison and calls `placeBlock` without inventory lookup or `equip`; the bounded shelter handlers independently perform requested-material lookup and equip
- Goals: six roots; two completed, three failed, one interrupted; the successful roots gathered six logs and crafted the table before three placement roots stalled
- Planner: 130 calls; 129 real and schema-valid responses, one deadline-bound timeout, 418842 tokens, maximum successful latency 6.281 seconds, zero retries, and zero reasoning bytes
- Actions: 19/63 succeeded; `move_to` 9/20, `dig` 6/7, `craft` 3/3, `place` 0/31, and `build_shelter_cell` 1/2
- Interrupts and shelter: 73 triggers had 73 recoveries; 72 were task deadlines and one was dusk. One bounded shelter action placed 9/9 blocks, but the misplaced sapling occupied the interior so all nine machine shelter checks failed; a second build timed out and disconnected the bridge
- Deadline: Agent stopped at 55526.765, exactly the absolute deadline; canonical evidence ended at 55526.781, 0.016 seconds late. No Planner call, plan, verification, or action began after the boundary, but the independent duration/no-post-deadline checks rejected the run
- Skills: baseline remained off; selected/executed/quarantined contribution was zero
- Round boundary: this was the only live episode; no code fix or second BM-012 run is authorized
- Evidence: `logs/benchmarks/m4/m4_episode_20260713_112039_496a9152/`

### Probe 5: Family Reconciliation Passed; Placement Success Criterion Rejected

- Episode: `m4_episode_20260713_092629_6eeeab70`
- Session: `43503d04-512`
- Level: `m4_episode_20260713_092629_6eeeab70_bm012`
- Preflight: passed with unchanged protocol/task-contract hashes, empty inventory, fresh daylight level, zero-death lifecycle baseline, and exact `600/24/40/320` controls
- Result: ineligible; BM-012 remains 0/3, 66/74 independent checks passed, no terminal resource event was emitted, and no iron-source action occurred
- Prior gate live evidence: four `m4_task_state_reconciliation` events completed 18 tasks; event 192 closed seven stale gather tasks before root selection, and event 535 activated the pinned family projection for `oak_log:5 + birch_log:1` and completed eight tasks; stale fulfilled wood roots did not recur
- Earliest invalid transition: Planner call event 255 / call `llm-747a78336a3e4e79` at monotonic 48146.609 had one place action with passing action grounding, but failed numeric criteria grounding on `success_criteria.inventory.crafting_table`; empty-plan event 258 at 48146.796 ended the root
- Confirmation: event 273 / call `llm-4efc1e7d2e9b4aef` repeated the same sole schema issue and empty-plan event 276 ended the retry; raw response bodies are not retained, so only the invalid-count class, response hashes, and byte counts are canonical evidence
- Cascade: the crafting table remained in inventory and unplaced; later exploration, one recovered Planner connection error, 70 task-deadline interrupts, one dusk interrupt, shelter construction, and the final deadline-bound timeout did not recover iron progression
- Goals: 12 roots; seven completed, four failed, one interrupted, 105 planner tasks created, and final task states were 21 completed, 78 failed, and six accepted
- Planner: 106 calls; 104 real responses, 102 schema-valid real responses, two placement-criterion schema rejections, one recovered connection error, one deadline-bound timeout, 334971 tokens, maximum latency 17.734 seconds, and zero reasoning bytes
- Actions: 25/30 succeeded; `move_to` 12/17, `dig` 6/6, `craft` 3/3, `build_shelter_cell` 1/1, and `wait` 3/3; no crafting-table place or iron-source action executed
- Shelter and survival: one machine shelter verification passed with 9/9 episode placements; terminal health/food were 20, lifecycle remained uninterrupted with zero deaths/respawns, world time was 12081, and inventory was `oak_planks:11`, `crafting_table:1`, `birch_log:2`, `dark_oak_log:1`, `dirt:3`
- Deadline: Agent ended 0.016 seconds late and manifest evidence ended 0.063 seconds late; one timed-out Planner call and error plan were recorded after the boundary, with zero post-deadline actions
- Skills: baseline remained off; selected/executed/quarantined contribution was zero
- Round boundary: this was the only live episode; no code fix or second BM-012 run is authorized
- Evidence: `logs/benchmarks/m4/m4_episode_20260713_092629_6eeeab70/`

### Probe 4: Numeric Crash Cleared; Log-Family Task Reconciliation Repeated Completed Roots

- Episode: `m4_episode_20260713_085253_4a8a6b25`
- Session: `e86fce97-657`
- Level: `m4_episode_20260713_085253_4a8a6b25_bm012`
- Preflight: passed with unchanged protocol/task-contract hashes, empty inventory, fresh daylight level, zero-death lifecycle baseline, and exact `600/24/40/320` controls
- Result: ineligible; BM-012 remains 0/3, 68/74 independent checks passed, no terminal resource event was emitted, and no iron-source action occurred
- Prior gate live evidence: 31/31 real Planner calls were schema-valid; all 31 numeric-grounding reports passed with one integer requirement each, zero issues, zero normalization, and zero runtime errors; Probe 3's `int >= str` failure did not recur
- Family boundary: observation event 157 held `oak_log:4` and `dark_oak_log:2`; GoalVerifier event 170 reported `inventory has 6/6 oak_log` using the pinned log family
- Earliest invalid transition: task-readiness event 160 still reported seven ready exact-`oak_log:6` tasks; opportunity event 167 selected one, and auto-goal event 175 began the repeated frontier
- Cascade: 23 later roots used `ready_task_selected`; all verified in one cycle, no action executed after event 155, 31 tasks were created, 22 completed, and nine remained accepted when `max_goals_or_stopped` ended the episode
- Goals: 24 roots; 24 completed, zero failed, zero interrupted, 31 total cycles
- Planner: 31/31 calls were real and schema-valid, maximum latency 5.562 seconds, 100594 tokens, zero transport retries/errors, and zero reasoning bytes
- Actions: 7/8 succeeded; `move_to` 3/4 and `dig` 4/4; no craft, place, shelter, or iron-source action executed
- Terminal: health/food 20, lifecycle uninterrupted with zero deaths/respawns, world time 3157, inventory `oak_log:4`, `dark_oak_log:2`
- Deadline: evidence ended at 46199.984 against deadline 46649.515, leaving 449.531 seconds; no post-deadline execution occurred
- Skills: baseline remained off; selected/executed/quarantined contribution was zero
- Round boundary: this was the only live episode; no second BM-012 run is authorized
- Evidence: `logs/benchmarks/m4/m4_episode_20260713_085253_4a8a6b25/`

### Probe 3: Canonical Place Plan Emitted; String Subtask Threshold Crashed Reconciliation

- Episode: `m4_episode_20260713_081730_337b2b6b`
- Session: `bc72df1e-a54`
- Level: `m4_episode_20260713_081730_337b2b6b_bm012`
- Preflight: passed with unchanged protocol/task-contract hashes, empty inventory, fresh daylight level, zero-death lifecycle baseline, and exact `600/24/40/320` controls
- Result: ineligible; BM-012 remains 0/3, 68/74 independent checks passed, no terminal resource event was emitted, and no iron-source action occurred
- Prior gate live evidence: plan event 510 emitted `place(item=crafting_table,x=106,y=135,z=-29)` and `m4_action_parameter_grounding` passed with one place action and zero normalization; Probe 2's `block` alias rejection did not recur
- Earliest invalid transition: the same plan accepted `success_criteria.inventory.oak_planks=">=8"` and `preconditions.inventory.oak_log=">=1"` as strings and created scheduler tasks
- First runtime failure: event 525 / monotonic 44047.687 / global cycle 25 raised `int >= str` before the `Place crafting_table` root could call Planner or execute an action
- Cascade: 280 identical error events covered cycles 25 through 304; goals 18 through 24 each failed after 40 cycles, while the crafting table remained in inventory and absent from nearby blocks
- Goals: 24 roots; 17 completed, seven failed, zero interrupted
- Planner: 24/24 calls were real and schema-valid under the current envelope/action checks, maximum latency 7.796 seconds, 76533 tokens, and zero reasoning bytes
- Actions: 11/11 succeeded; `move_to` 2/2, `dig` 6/6, and `craft` 3/3; no place action executed
- Terminal: health/food 20, lifecycle uninterrupted with zero deaths/respawns, world time 2962, inventory `oak_log:4`, `crafting_table:1`, `oak_planks:4`, `oak_sapling:1`
- Deadline: evidence ended at 44063.468 against deadline 44521.859, leaving 458.391 seconds; no post-deadline execution occurred
- Skills: baseline remained off; selected/executed/quarantined contribution was zero
- Round boundary: this was the only live episode; no second BM-012 run is authorized
- Evidence: `logs/benchmarks/m4/m4_episode_20260713_081730_337b2b6b/`

### Probe 2: Purpose Phrase Passed; Unplaced Crafting Table Blocked Tool Progression

- Episode: `m4_episode_20260713_073547_798a7440`
- Session: `4fc81174-b01`
- Level: `m4_episode_20260713_073547_798a7440_bm012`
- Preflight: passed with the unchanged base and BM-012 task-contract hashes, empty inventory, fresh time-0 level, and exact `600/24/40/320` limits
- Result: ineligible; BM-012 remains 0/3, with no terminal resource event and zero iron-source actions
- Prior hypothesis: passed live at goal-verification event 177; `oak_log:6` completed the exact Probe 1 root with `intent:shelter_purpose_phrase`, and auto-goal event 178 closed it after eight cycles
- Earliest blocker: Curriculum event 308 / monotonic 41502.359 selected `Craft wooden pickaxe` while `crafting_table:1` was only in inventory and the nearby placed-table count was zero
- Planner corroboration: event 321 said `Already have crafting_table` and omitted a place prerequisite; event 369 said an inventory table allowed immediate wooden-pickaxe craft
- First failed action: event 395 / monotonic 41523.562 used canonical `craft(item=wooden_pickaxe,count=1)` with six planks and four sticks, but the bridge reported `No recipe for wooden_pickaxe`, `crafting_table_found=false`, and no inventory delta
- Downstream cascade: thirteen `place(block=crafting_table)` aliases were rejected for missing canonical `item`; the wooden-pickaxe and place-table roots exhausted 40 cycles before dusk survival preempted progression
- Goals: 11 roots; seven completed, three failed, and one interrupted
- Planner: 120/120 real calls, 119 schema-valid, maximum latency 6.656 seconds, 385894 tokens, and zero reasoning bytes
- Actions: 43 attempted and 29 successful; `move_to` 8/8, `dig` 6/6, `craft` 6/7, `place` 0/13, `look_at` 5/5, `build_shelter_cell` 1/1, and `wait` 3/3
- Resource state: initial and terminal iron counts were zero; terminal inventory was `crafting_table:1`, `stick:4`, `oak_planks:9`, `wheat_seeds:1`, `oak_log:1`
- Survival state: 164 lifecycle-bound observations, zero deaths/respawns, health/food 20, and one machine shelter pass
- Interrupts: 84 task-deadline triggers plus one dusk trigger, all with matching recoveries
- Deadline: Agent ended 0.031 seconds and evidence 0.156 seconds after the absolute deadline; no task success is eligible
- Round boundary: this was the only live episode; no second BM-012 run is authorized
- Evidence: `logs/benchmarks/m4/m4_episode_20260713_073547_798a7440/`

### Probe 1: Resource Goal Fulfilled but Purpose Phrase Blocked Completion

- Episode: `m4_episode_20260713_065904_b2b7b898`
- Session: `6dbc69ab-4d7`
- Level: `m4_episode_20260713_065904_b2b7b898_bm012`
- Preflight: passed with the pinned base and BM-012 task-contract hashes, empty inventory, fresh time-0 level, and exact `600/24/40/320` limits
- Result: ineligible; BM-012 remains 0/3, with no terminal resource event and zero iron-source actions
- Earliest blocker: action event 208 / monotonic 39289.093 / cycle 9 raised oak logs from 5 to 6, but GoalVerifier required shelter because it treated `for tools and shelter` as another completion clause
- Corroboration: event 212 completed thirteen gather tasks from the same machine inventory; Planner event 215 then emitted a no-action fulfilled response and was correctly rejected as `planning_actions_missing`
- Goals: 24 roots; 23 completed and one failed. The first root exhausted 40 cycles; twenty-one later roots repeated `Craft oak_planks from logs`
- Planner: 70/70 real calls, 54 schema-valid, 16 schema-invalid `planning_actions_missing` recoveries, maximum latency 7.171 seconds, 220858 tokens, and zero reasoning bytes
- Actions: 32 attempted and 25 successful; `move_to` 5/7, `dig` 11/11, `wait` 1/1, `craft` 4/4, and `build_shelter_cell` 4/9
- Resource state: initial and terminal iron counts were zero; terminal inventory was `oak_log:6`, `oak_planks:3`, `oak_sapling:1`
- Survival state: 103 lifecycle-bound observations, zero deaths/respawns, health/food 20, and four machine shelter passes
- Interrupts: four `task_deadline_elapsed` triggers and four recoveries; no conflicting root remained open
- Deadline: Agent ended at 39583.046 and evidence at 39583.109 against deadline 39823.390, leaving 240.281 seconds with no post-deadline execution
- Round boundary: this was the only live episode; no second BM-012 run is authorized
- Evidence: `logs/benchmarks/m4/m4_episode_20260713_065904_b2b7b898/`

### Historical BM-011 Hypotheses

Probe 7 confirms the M4 action-parameter-grounding fix in live execution. All 22 real Planner calls were schema-valid, every `dig` used canonical top-level coordinates and optional `block`, all nine `dig` actions passed ActionVerifier, and nine succeeded. The Agent accumulated 11 oak logs, so Probe 6's alias rejection did not recur.

The new earliest unrecovered transition is task-completion/readiness grounding. At session event index 366 the machine observation already contained `oak_log:9`. Planner call `llm-1ef73e3cdfab47e3` at index 376 nevertheless treated the fulfilled `Gather 6 oak logs` task as ready and emitted another `dig` rather than the dependent craft/build step. The next successful action raised inventory to 10 logs, and subsequent plans continued gathering. Across 21 actions there were 15 successes but zero crafting actions and zero placement actions; the shelter remained unverified.

The dusk interrupt itself behaved coherently: one `dusk_shelter_required` trigger suspended the resource goal, preserved its frontier, selected the aligned shelter goal, and escalated the same trigger to `night_shelter_required` without creating a competing root. The run ultimately consumed the remaining 58.14 seconds in a deadline-bound `move_to`, ended 0.016 seconds after the absolute deadline, and was independently rejected.

The task-completion/readiness hypothesis passed live in Probe 8. At cycle 9, one `m4_task_state_reconciliation` event completed seven duplicate gather nodes as soon as the machine observation reached `oak_log:6`; the next selected behavior entered crafting instead of gathering. Non-inventory criteria remained outside the reconciliation path.

The new earliest unrecovered transition is craft action-parameter grounding. Session event index 207 at monotonic 280930.390 attempted `craft` with `recipe=oak_planks` and `count=4`; ActionVerifier requires canonical `item`, so it rejected the action before execution. All 11 craft attempts repeated the same alias family, producing zero planks and no shelter placements. Later readiness-format warnings and the final deadline overrun do not displace this earlier transition.

Craft parameter grounding passed live in Probe 9. Planner output was normalized to canonical `item`, ActionVerifier accepted it, and one craft action converted four oak logs into 16 observed oak planks.

The new earliest unrecovered transition is shelter-phase progression. Immediately after the 16-plank observation and task reconciliation, Planner call `llm-05670ca498a34ebf` at session event index 302 expanded the shelter goal into additional logs, sticks, a crafting table, pickaxe, cobblestone, and furnace. Its first actions returned to gathering, even though the same plan declared the shelter build precondition as 16 oak planks and that machine state already held. No place action occurred, and the first shelter root exhausted eight cycles at event index 414.

Shelter-phase progression passed live in Probe 10. The autonomous chain gathered six oak logs, crafted 24 oak planks, activated one machine-grounded `build_shelter_cell`, placed the nine final structure blocks, removed the temporary scaffold, and obtained a 9/9 current-episode match from the unchanged G3 verifier. All 11 actions succeeded.

The new earliest unrecovered transition is autonomous goal-budget lifecycle. After shelter verification, GoalGenerator correctly selected `Enter and maintain verified shelter through nightfall`, but GoalVerifier immediately completed that maintenance goal from the already-safe state. The same one-cycle goal was selected twice, consuming goal slots 3 and 4. `autonomous_end` event index 304 then terminated with `max_goals_or_stopped` at world time 11226 before night, despite 135.297 seconds remaining.

Maintenance-goal lifecycle passed live in Probe 11. `Remain in verified shelter until dawn` stayed active, emitted two bounded waits, and ended only when the absolute episode deadline fired; it did not allocate another goal or terminate on `max_goals`.

Probe 11 exposed runtime-harness limit drift, not a contradiction in the fixed protocol. Probe 12 confirms that fix live: the manifest used exactly 1200 seconds, 24 autonomous goals, and 40 cycles per goal, while the protocol retained its 320-cycle total cap and unchanged hash. The Agent gathered resources, crafted planks, built a 9/9 machine-verified shelter by world time 11282, and maintained it into night.

The new earliest unrecovered transition is `planner_transport_failure_goal_abandonment`. At session event index 506, Planner call `llm-24dd4cd454db4e1e` made its one allowed transport attempt for `Remain in verified shelter until dawn` and received `APIConnectionError -> ConnectError -> SSLEOFError`. The immediately preceding machine observation at index 502 still showed health 20, food 20, world time 14902, an online verified shelter, and one nearby hostile, with more than 900 seconds of episode budget remaining. The error plan became `empty_plan` at index 511, and the autonomous loop failed and discarded the active maintenance root instead of preserving it for a next-cycle transport recovery.

Later events are a secondary cascade, not the earliest blocker. GoalGenerator selected an immediate-threat flee goal, the Agent left its verified shelter, and shelter verification became false at world time 15362. Eleven rebuild attempts lacked a grounded neighbor, one later rebuild timed out and disconnected the Agent-side bridge, and all subsequent observations fell back to empty position/inventory and time zero. The exact-profile run then ended at the absolute deadline without a terminal machine verification.

The `planner_transport_failure_goal_lifecycle` patch remained bounded in Probe 13. There were no live transport exceptions and therefore zero `m4_planner_transport_recovery` events; the Probe 12 failure did not recur. Sixteen real model responses with `planning_actions_missing` were correctly handled by the pre-existing `m4_planner_output_recovery` branch, producing zero `empty_plan` events and demonstrating that transport and schema recovery remain separate.

The new earliest unrecovered transition is `verified_shelter_hostile_flee`. At session observation index 920, world time 21672, the Agent had health/food 20, was inside the pinned 9/9 sealed-cell shelter, and observed one skeleton 5.1 blocks away. The G3 report proved `direct_reachability=blocked`, a fully sealed entrance, and no hostile inside. Runtime interrupt event 933 nevertheless generated an outward `move_to` target, and action event 943 moved the Agent 7.894 blocks before reporting a tolerance miss. Observation 940 then showed shelter verification false at world time 22152. The dawn observation at event 1057 had health 19 and natural time 23092 but no verified shelter, so no terminal machine event could be emitted.

The Probe 14 hypothesis was `runtime_interrupt_safe_state_grounding`: a hostile outside a complete machine-verified sealed shelter must not trigger an emergency action that exits that safe state. The patch alters only strict-M4 hostile interrupt grounding for this proven-safe condition; hostile handling without a verified shelter, hostiles inside the cell, health/hunger interrupts, priority order, and the G3 contract remain unchanged.

The offline safe-state gate passes. Replaying Probe 13 observation event 920 through the patched RuntimeSupervisor selects `night_safety_maintenance`, emits no emergency action, and records that the previously generated outward `move_to` was suppressed. The full report is accepted only when the pinned verifier and contract pass, the report and observation floor to the same player cell, the report saw every actionable hostile, `direct_reachability=blocked`, and `hostiles_inside=[]`. Spoofed reports, stale player positions, reachable threats, hostiles in the player cell, and non-M4 profiles retain the original `hostile_nearby` behavior. Critical health still wins when the outside hostile is proven blocked.

Probe 14 produced a runner-reported eligible terminal state, but independent audit rejects it. Paper recorded `Singularity was slain by Zombie` at 00:34:41 and again at 00:35:04. The first death is corroborated by canonical observation event 1183 (`health=7.999998`, `oak_planks:32`, world time 15472) followed by event 1198 (`health=20`, planks gone, world time 15692); the second is corroborated by event 1224 (`health=8.000002`, `stick:1`) followed by event 1238 (`health=20`, empty inventory). The later 9/9 shelter, natural dawn, terminal event, and deadline pass cannot repair a death inside the active survival interval.

The fixed-code Probe 16 replication failed, leaving BM-011 at 1/3. Runner reported a later `empty_plan` at event 682 after one real Planner response contained an invalid control character, but independent causal ordering finds an earlier irreversible transition at action event 217 / monotonic 21178.031 / world time 10701. `build_shelter_cell` started with 16 oak planks at origin `(93,136,-36)`, placed two blocks, then returned `no grounded neighbor exists` while leaving those placements and reducing inventory to 14. Nine same-origin partial failures consumed or stranded enough material to reach nine planks, followed by fourteen same-goal material-threshold rejections before the malformed Planner output. No movement or alternate origin occurred inside that shelter root.

The `bounded_shelter_partial_failure_atomicity` hypothesis passed live in Probe 17. At action event 301 the original shelter origin failed mutation-free preflight with `placed_count=0` and oak planks unchanged at 16. Recovery event 297 scheduled the bounded relocation from `(90,133,-38)` to `(88,131,-38)`; the next grounded plan contained exactly one canonical `move_to`, event 318 completed the move, and the second bounded build placed all 9/9 final blocks. The machine verifier passed at world time 11345 and remained valid through terminal world time 23125. BM-011 advanced to 2/3, and the subsequent frozen-code Probe 18 replication completed the task at 3/3.

## G5 Preflight: Bounded Shelter Partial-Failure Atomicity

- Scope: strict-M4 `build_shelter_cell`, Agent recovery state, and shelter-phase Planner grounding only; the fixed protocol, G3 success verifier, goal order, deadline, and M1/M2 behavior are unchanged
- Mutation-free rejection: the bridge simulates all nine final placements and the temporary roof scaffold before equip, dig, or place; Probe 16's origin now returns zero placements with unchanged material inventory
- Unexpected failure: any block placed by the bounded action is removed in reverse order, material recovery is observed for up to two seconds, and residual blocks or missing inventory fail the atomicity check closed
- Atomicity scope: final placements and the selected material inventory; existing terrain clearing remains separately reported and is not claimed as a whole-world transaction
- Relocation: after an atomic failure, the bridge deterministically scans a maximum Chebyshev radius of six and vertical offset of two for a standable origin whose complete template preflight passes
- Agent boundary: relocation origin, centered movement target, radius, and offsets are validated before `m4_shelter_atomicity_recovery` is scheduled; malformed or out-of-bounds machine output clears the pending recovery
- Planner recovery: while a validated relocation is pending, the next shelter plan is exactly one canonical `move_to`; a failed move retains the recovery and a successful move clears it before template retry
- Offline tests: `tests/test_bot_server_m4_protocol.js` has 8/8 M4 cases and `tests/test_m4_shelter.py` has 18/18 cases, including exact Probe 16 geometry, rollback success/failure, bounded-output rejection, and relocation-before-retry
- Regression: 686 Python tests and 35 internal PASS cases across all six fixed Node suites pass; syntax compilation and `git diff --check` also pass
- Protocol integrity: `m4-fixed-v1` SHA-256 remains `378689bc96d28580b2debcccb12efb4f955de38dd031e681ace529d4f75d157d`; reset and validation contract hashes remain unchanged
- Live result: Probe 17 exercised the mutation-free rejection, bounded relocation, canonical move, complete retry, 9/9 verification, and eligible dawn terminal path
- Live authorization: consumed by Probe 18; no BM-012 live episode is authorized in this round

## G0 Offline Evidence: Active-Episode Death Continuity

- Probe 14 runner claim: `completed=true`, `terminal_survival_verified`, and `eligible=true`
- Independent rejection: Paper server stdout contains two `Singularity was slain by Zombie` messages at 00:34:41 and 00:35:04; diagnostic log SHA-256 is `9cbe6e2533298e1c989fb8bedb713df2498bccbf7682185aec47322e26351a4d`
- Canonical corroboration: observation transitions 1183 to 1198 and 1224 to 1238 reset health to 20 while dropping held inventory during active night
- Bridge source: `m4-player-lifecycle-verifier-v1` consumes Mineflayer `death` and `spawn` events and exposes cumulative totals plus episode-relative death, respawn, spawn, pending-respawn, and uninterrupted fields
- Reset binding: the M4 reset establishes one episode/level/protocol-bound baseline only after an initial Mineflayer spawn and rejects nonzero episode deltas; historical pre-reset deaths do not contaminate the fresh interval
- Canonical propagation: every strict-M4 observation carries a fresh lifecycle snapshot, while `m4_player_lifecycle` records the baseline and each deduplicated transition with validation status
- Terminal fail-closed behavior: Agent obtains a fresh lifecycle snapshot and emits `terminal_survival_verification` only for a valid zero-death, zero-respawn, uninterrupted interval
- Independent eligibility: all observation and lifecycle-event counters must be valid, baseline-consistent, monotonic, and zero; terminal observation, terminal event, and result lifecycle signatures must match
- Probe 14 fixture: a death followed by respawn, restored health 20, online bot, verified shelter, and dawn terminal claim is independently rejected; missing, rolled-back, event-only, and malformed evidence also fail closed
- Anti-spoof result: a final positive health value, online bot, verified shelter, or later respawn cannot erase an earlier active-episode death
- Protocol boundary: strict M4 only; M1/M2 fixed task semantics and evidence remain unchanged
- Offline regression: 686 Python tests and all six fixed Node suites pass; M4 bridge reset also rejects a missing initial-spawn baseline
- Protocol integrity: current SHA-256 `378689bc96d28580b2debcccb12efb4f955de38dd031e681ace529d4f75d157d`, reset contract `0df412101c5c01bf89b32e26d2d9beead7f9b64d10ba5de714caab51b1b63e52`, validation contract `bd2e7466d18d72927c7ca84a11736597a05eab5adf4b788627fe9377542d1e02`
- Live validation: Probes 15, 17, and 18 passed the uninterrupted zero-death path; Probe 16 recorded six valid death/respawn transitions matching Paper, blocked terminalization after later respawns and shelter verification, and rejected the subsequent missing lifecycle snapshot
- Live authorization: consumed by Probe 18; no BM-012 live episode is authorized in this round

## G5 Preflight: Verified Shelter Hostile Safe-State Grounding

- Scope: strict-M4 RuntimeSupervisor hostile evaluation and Agent audit logging only; GoalGenerator, G3 verifier contract, Planner, ActionVerifier, M1/M2 behavior, and protocol data are unchanged
- Trigger: complete pinned G3 shelter report, report and current observation in the same integral player cell, fully sealed entrance, `complete_local_collision_enclosure`, `direct_reachability=blocked`, empty `hostiles_inside`, and a report hostile count covering every actionable nearby hostile
- Grounding: suppress only the `hostile_nearby` decision for the proven blocked outside threat and continue evaluating health, hunger, night maintenance, deadlines, and return-to-base under their existing priorities
- Night behavior: an aligned `Remain in verified shelter until dawn` root stays active with `night_safety_maintenance`; no outward runtime emergency action executes and no competing hostile root is opened
- Audit: `m4_hostile_safe_state_grounding` records the hostile identity/cell, observed and verified player cells, verifier ID, contract hash, blocked reachability, suppressed action, selected surviving interrupt, and a deduplicated fingerprint
- Fail-closed exclusions: spoofed or incomplete reports, stale player cells, missing hostile coordinates, report count mismatch, reachable threats, hostiles inside the player cell, and non-M4 profiles
- Probe 13 replay: archived observation event 920 now returns `night_safety_maintenance`, `emergency_action=null`, hostile ID 1789, player cell `(107,140,-29)`, and `outward_move_suppressed=true`
- Offline tests: `tests/test_runtime_supervisor.py`; 15/15 cases pass, including exact Probe 13 reproduction and Agent no-action integration
- Regression: 679 Python tests and all six fixed Node suites pass; Python compilation and repository checks remain required before commit
- Protocol integrity: `m4-fixed-v1` SHA-256 remains `a3ff6b9d39fa4955b4c52739f9059ae5969b82c74c4d33d751c79aa7f3b7f202`
- Live result: Probe 18 exercised the branch with a zombie 4.8 blocks outside the verified shelter; blocked direct reachability suppressed the outward move and the safe state persisted through dawn
- Next live authorization: none; BM-012 remains at its offline preflight gate

## G5 Preflight: Planner Transport Next-Cycle Recovery

- Scope: strict-M4 autonomous goal lifecycle only; Planner transport policy, protocol hash, goal priority, shelter verifier, and action execution are unchanged
- Trigger: `status=error`, no actions, `real_llm_call=false`, `schema_valid=false`, exact `single-attempt` evidence, one failed attempt, and an allowlisted connection/timeout exception chain
- Live coverage: Probe 18 observed `APIConnectionError -> ConnectError -> ConnectError -> SSLEOFError`
- Recovery: emit `m4_planner_transport_recovery`, preserve the current goal, and retry planning from a fresh observation in the next autonomous cycle
- Retry boundary: same-call retry count remains zero; each failed call consumes one normal cycle and remains bounded by 40 per goal, 320 total, and the absolute episode deadline
- Fail-closed exclusions: authentication failures, real-response schema/JSON errors, non-transport exceptions, missing evidence, and all deadline errors
- Existing recovery: `planning_actions_missing` continues to use `m4_planner_output_recovery` and is unchanged
- Evidence fields: goal, cycle, Planner call ID, error type/chain, transport policy, goal-preserved flag, resume policy, deadline, and remaining budget
- Offline tests: `tests/test_m4_deadline.py`
- Regression: 675 Python tests, all six fixed Node suites, Python compilation, and `git diff --check` passed
- Protocol integrity: `m4-fixed-v1` SHA-256 remains `a3ff6b9d39fa4955b4c52739f9059ae5969b82c74c4d33d751c79aa7f3b7f202`
- Live result: Probe 18 emitted one recovery event, preserved the same dawn-maintenance goal, and resumed successful waits after the next-cycle real/schema-valid Planner call
- Next live authorization: none; BM-012 remains at its offline preflight gate

## G5 Preflight: Exact Runtime Harness and Terminalization

- Scope: M4 runtime harness and terminal evidence only; the protocol, goal priority, bounded shelter action, maintenance cadence, and G3 verifier are unchanged
- Exact BM-011 profile: 1200-second episode timeout, 24 autonomous goals, 40 cycles per goal, and 320 total cycles
- Harness enforcement: PowerShell and Python defaults are protocol-derived; either runner rejects any runtime-limit mismatch before episode execution
- Eligibility enforcement: `manifest_runtime_limits` requires exact protocol equality rather than accepting a shortened preparation envelope
- Terminal event: `terminal_survival_verification` requires an `until dawn` maintenance goal, finite dawn-boundary machine time, positive finite health, an online bot bridge, and a complete pinned shelter report
- Result binding: `completed=true` and `termination_reason=terminal_survival_verified` are produced only from the Agent terminal event path
- Fail-closed behavior: missing/non-finite time, missing health, disconnection, or an incomplete/spoofed shelter report cannot terminalize the episode
- Offline tests: `tests/test_m4_protocol.py` and `tests/test_m4_shelter.py`
- Regression: 674 Python tests, all six fixed Node suites, PowerShell syntax parsing, Python compilation, and `git diff --check` passed
- Protocol integrity: `m4-fixed-v1` SHA-256 remains `a3ff6b9d39fa4955b4c52739f9059ae5969b82c74c4d33d751c79aa7f3b7f202`
- Live result: Probe 12 used the exact profile; the harness fix passed, but BM-011 remained ineligible because an earlier Planner transport error abandoned the active dawn-maintenance goal
- Next live authorization: unlocked by the strict-M4 next-cycle Planner transport preflight above

## G5 Preflight: Maintenance Goal Lifecycle

- Scope: M4 verified-shelter maintenance only; max goals, max cycles, total cycles, deadline, priority order, and G3 verifier are unchanged
- Dusk boundary: `Enter and maintain verified shelter through nightfall` requires verified shelter and world time in `[12000, 23000)`
- Dawn boundary: `Remain in verified shelter until dawn` requires verified shelter and world time at or after 23000, or after natural wrap below 1000
- Pending behavior: one `wait` action capped at 15000 ms, then a fresh machine observation and runtime interrupt evaluation
- Root semantics: the current maintenance root remains active; pending safety is not logged as goal completion and does not allocate another goal slot
- Fail-closed behavior: missing/non-finite time or lost shelter verification cannot satisfy a boundary
- Evidence: `m4_maintenance_phase_grounding` records boundary, current world time, boundary state, and wait duration
- Offline tests: `tests/test_m4_shelter.py`
- Regression: 672 Python tests and all six fixed Node suites passed
- Protocol integrity: max goals remains 24, max cycles per goal remains 40, and protocol SHA-256 remains `a3ff6b9d39fa4955b4c52739f9059ae5969b82c74c4d33d751c79aa7f3b7f202`
- Historical live authorization: consumed by Probe 11; current authorization is governed by the reopened G0 gate above

## G5 Preflight: Bounded Shelter Action

- Scope: M4 shelter construction only; autonomous goal priority, task reconciliation, M1/M2 contracts, and the fixed G3 verifier are unchanged
- Action: `build_shelter_cell` with current machine `player_cell` origin and an allowlisted inventory material
- Final structure: four two-block-high wall columns plus one center roof, exactly nine current-episode structural placements
- Temporary support: one bounded roof scaffold is placed and removed inside the same action; minimum starting inventory is 10 blocks
- Grounding: Planner replaces unrelated shelter-plan expansion only after a trusted machine snapshot and material threshold; evidence is `m4_shelter_phase_grounding`
- Verification: ActionVerifier rejects stale origins, untrusted verifier reports, already-verified shelters, unsupported materials, and insufficient inventory
- Backend evidence: every final target has before/after state; cleared and temporary positions are reported separately
- Agent evidence: nine final positions enter `_m4_episode_block_delta` and must still pass `m4-sealed-cell-shelter-verifier-v1`
- Offline tests: `tests/test_m4_shelter.py` and `tests/test_bot_server_m4_protocol.js`
- Regression: 670 Python tests and all six fixed Node suites passed
- Protocol integrity: `m4-fixed-v1` SHA-256 remains `a3ff6b9d39fa4955b4c52739f9059ae5969b82c74c4d33d751c79aa7f3b7f202`
- Historical live authorization: consumed by Probe 10; current authorization is governed by the reopened G0 gate above

## G5 Preflight: Craft Parameter Grounding

- Scope: M4 Planner output only; ActionVerifier, task reconciliation, M1/M2 contracts, and protocol hash are unchanged
- Canonical `craft`: nonempty `item`, with optional positive integer `count`
- Accepted normalization: `recipe` to `item` only when values are nonconflicting
- Rejected drift: unknown keys, missing/invalid item, `item`/`recipe` conflicts, booleans, fractions, zero, and negative counts
- Evidence: `m4_action_parameter_grounding` now reports `craft_action_count`, original parameter hash, alias list, and canonical parameters
- Prompt grounding: M4 fixed output contract now states `item` and forbids `recipe`
- Offline tests: `tests/test_m4_deadline.py`
- Regression: 667 Python tests and all six fixed Node suites passed
- Historical live authorization: consumed by Probe 9; current authorization is governed by the reopened G0 gate above

## G5 Preflight: Task Completion Readiness

- Scope: M4 autonomous loop and task lifecycle only; Planner schema, ActionVerifier, M1/M2 contracts, and protocol hash are unchanged
- Trigger: current machine observation satisfies every item/count in a task's pure `inventory` success criteria
- Transition: accepted or active task becomes completed with reason `machine_state_success_criteria_satisfied`
- Dependency effect: dependent craft/build tasks become schedulable before the next Planner context is assembled
- Evidence: `m4_task_state_reconciliation` records cycle, root goal, task ID/title, and machine-checkable criteria
- Fail-closed boundary: criteria containing flags, structure, action, result, position, observed names, or mixed keys are not auto-completed
- Protocol boundary: reconciliation is disabled unless `planner_protocol=m4-fixed-v1`
- Offline tests: `tests/test_memory_task_system.py`
- Regression: 665 Python tests and all six fixed Node suites passed
- Historical live authorization: consumed by Probe 8; current authorization is governed by the reopened G0 gate above

## G5 Preflight: Action Parameter Grounding

- Scope: M4 Planner output only; ActionVerifier, M1/M2 contracts, protocol hash, and provider controls are unchanged
- Canonical `dig`: finite top-level `x`, `y`, and `z`, with optional top-level `block` and positive `timeout_ms`
- Accepted normalization: `position.{x,y,z}` to top-level coordinates and `block_name` to `block` only when values are complete and nonconflicting
- Rejected drift: unknown keys such as `target`, incomplete/non-finite coordinates, top-level/nested coordinate conflicts, and `block`/`block_name` conflicts
- Evidence: `m4_action_parameter_grounding` is embedded in plan schema validation and accepted plan events
- Prompt grounding: the M4 fixed output contract now states the canonical shape and forbids aliases
- Offline tests: `tests/test_m4_deadline.py`
- Regression: 663 Python tests and 30 Node tests passed
- Protocol integrity: `m4-fixed-v1` SHA-256 remains `a3ff6b9d39fa4955b4c52739f9059ae5969b82c74c4d33d751c79aa7f3b7f202`
- Historical live authorization: consumed by Probe 7; current authorization is governed by the reopened G0 gate above

## G4 Offline Evidence

- Required cases: hostile, critical health, hunger, dusk shelter, and night safety maintenance
- Priority: hostile threat, critical health, hunger, unverified night shelter, verified night maintenance, dusk shelter, task deadline, and return-to-base
- Grounded actions: weapon equip followed by entity-ID attack, vector flee when unarmed, and verified inventory item use for health or hunger
- Pause semantics: a non-emergency autonomous root ends with `status=suspended` and `auto_goal_interrupted`, not `auto_goal_failed`
- Frontier semantics: proposed, accepted, active, waiting, and blocked tasks are preserved; trigger and recovery evidence carry the same paused task ID and trigger ID
- Takeover semantics: the matching GoalGenerator survival goal runs without recursively interrupting itself
- Recovery semantics: condition clearance emits exactly one `runtime_interrupt_recovery` with `resume_preserved_frontier`
- Hysteresis: repeated same-state checks emit maintenance under one trigger; dusk-to-night emits escalation under that trigger rather than another root transition
- Root exclusivity: strict integration observed only zero or one open root between every `goal_start` and `goal_end`
- Offline tests: `tests/test_runtime_supervisor.py`
- Live evidence: Probe 15 exercised one successful dusk-shelter trigger/recovery chain. Probe 16 exercised five hostile triggers and five emergency flee actions, but six deaths followed while shelter remained unverified, so the hostile case remains rejected. Probe 18 exercised the verified-shelter outside-hostile branch live: a zombie 4.8 blocks away was outside the sealed cell, direct reachability was blocked, the outward move was suppressed, and the shelter remained valid through dawn.

## G3 Offline Evidence

- Verifier: `m4-sealed-cell-shelter-verifier-v1`
- Contract SHA-256: `5660b2ea4cbfb8e09c3919db714006961e1eeb9ee7b7c8d8dfec8a3217c4479f`
- Strategy: `sealed_cell_v1`; one standable interior cell, four two-block-high sealed wall columns, and one full-block roof
- Machine input: exact 3x3x4 Mineflayer snapshot, 36 unique block coordinates, player position/cell, collision state, and nearby hostile positions
- Provenance: all eight wall blocks and the roof must match successful observed placement deltas from the current episode; pre-existing structures and partial attribution fail
- Path-risk rule: complete local collision enclosure plus overhead cover and no hostile in the interior cell; an unproven aperture fails closed
- Entrance evidence: all four boundary columns carry lower/upper coordinates and are recorded as fully sealed; exit requires a later controlled removal
- Natural alternatives: none approved in this baseline
- Runtime wiring: Agent records observed `place`, `dig`, and bounded-template deltas, attaches the report to every strict-M4 observation, logs only state changes, and sends a compact decision to Planner
- Acceptance wiring: GoalGenerator and GoalVerifier require the pinned verifier ID, contract hash, all checks, empty issues, 9/9 placement attribution, and sealed coordinate evidence
- Offline tests: `tests/test_m4_shelter.py` and `tests/test_bot_server_m4_protocol.js`
- Live evidence: Probes 15, 17, and 18 built and preserved complete sealed cells through eligible dawn. Probe 17 additionally exercised mutation-free rejection and deterministic relocation before its successful 9/9 retry; Probe 18 passed the first bounded preflight and committed 9/9 directly. Probe 16 remains the rejected counterexample whose first shelter root produced nine partial failures and exhausted its complete-build reserve.

## G2 Live Evidence

### Probe 18: Third Eligible BM-011 Success; Repeat Verification Complete

- Episode: `m4_episode_20260713_055737_6d976e6d`
- Session: `c2594597-28b`
- Preflight: passed on fresh level `m4_episode_20260713_055737_6d976e6d_bm011` under unchanged protocol `378689bc96d28580b2debcccb12efb4f955de38dd031e681ace529d4f75d157d`
- G2: passed; pre-dusk inventory gained `oak_log:2` from initial world time 9198
- BM-011 eligible: true; all 66 independent checks passed, accepted successes reached 3/3, and BM-011 is `repeat_verified`
- Planner controls: 45 calls; 44 real/schema-valid successes, one single-attempt transport error, maximum successful latency 6.391 seconds, 139004 total tokens, and zero reasoning bytes
- Transport recovery: event 675 preserved `Remain in verified shelter until dawn` after `APIConnectionError -> ConnectError -> ConnectError -> SSLEOFError`; next-cycle event 681 was a real/schema-valid same-goal call and resumed successful waits
- Shelter: the first bounded action passed preflight and committed all 9/9 placements at origin `(107,136,-29)`; machine verification passed at event 311 / world time 11438 and remained valid through terminal world time 23098
- Safe-state grounding: event 832 observed a zombie 4.8 blocks away outside the verified cell, proved blocked direct reachability and no hostile inside, suppressed the outward move, and selected `night_safety_maintenance`
- Goals: four roots; resource gathering was suspended by dusk after six cycles, then shelter build, nightfall maintenance, and dawn maintenance completed in 8, 3, and 28 cycles
- Interrupts: two triggers and two recoveries, one `dusk_shelter_required` and one `task_deadline_elapsed`, with no concurrent root
- Actions: 43 attempted and 42 successful; `wait` 29/29, `dig` 6/7, `move_to` 4/4, `craft` 2/2, and `build_shelter_cell` 1/1
- Lifecycle: 89 active observations, one valid baseline event, zero deaths/respawns, uninterrupted terminal state, and zero Paper death messages
- Terminal: event 897 passed with health/food 20, bot online, verified shelter, inventory `oak_log:5` and `oak_planks:3`, and natural dawn at world time 23098
- Deadline: Agent ended at 36233.500 and canonical evidence at 36233.562 against deadline 36738.562, leaving 505.000 seconds with no post-deadline execution
- First unrecovered transition: none
- Round boundary: Probe 18 was the only live episode; no BM-012 live episode ran or is authorized in this round
- Evidence: `logs/benchmarks/m4/m4_episode_20260713_055737_6d976e6d/`

### Probe 17: Atomic Relocation Passed Live; Second Eligible BM-011 Success

- Episode: `m4_episode_20260713_053155_0f5a150e`
- Session: `0040d0d4-ecf`
- Preflight: passed on a fresh level under unchanged protocol `378689bc96d28580b2debcccb12efb4f955de38dd031e681ace529d4f75d157d`
- G2: passed; pre-dusk inventory gained `oak_log:3` and `dark_oak_sapling:1` from world time 9165
- BM-011 eligible: true; all 66 independent checks passed and accepted eligible successes advance to 2/3
- Atomic failure: action event 301 / monotonic 34085.812 / world time 10985 rejected origin `(90,133,-38)` before mutation, with zero placements and oak planks preserved at 16
- Relocation: event 297 scheduled `(88,131,-38)` within radius six, the next shelter grounding emitted only `move_to(88.5,131,-37.5)`, and event 318 completed it successfully
- Shelter retry: action event 341 committed the full template with 9 final blocks and one removed scaffold; machine verification passed at event 337 / world time 11345 and stayed valid through terminal world time 23125
- Planner controls: 48/48 calls were real and schema-valid, maximum latency 5.390 seconds, zero reasoning bytes, zero errors, and zero provider-control violations
- Goals: four roots; resource gathering was suspended by dusk, then shelter build, dusk maintenance, and dawn maintenance all completed
- Interrupts: four triggers and four matching recoveries; one `dusk_shelter_required` and three bounded `task_deadline_elapsed`, with no concurrent root
- Actions: 48 attempted and 43 successful; `build_shelter_cell` 1/2, `move_to` 6/7, `dig` 5/8, `craft` 1/1, and `wait` 30/30
- Lifecycle: 97 active observations, one valid baseline event, zero deaths/respawns, uninterrupted terminal state, and zero Paper death messages
- Terminal: event 956 passed with health/food 20, bot online, verified shelter, and natural dawn at world time 23125
- Deadline: Agent ended at 34692.625 and canonical evidence at 34692.687 against deadline 35194.515, leaving 501.828 seconds with no post-deadline execution
- First unrecovered transition: none
- Round boundary: Probe 17's round ran no second episode; the subsequent frozen-code Probe 18 authorization was consumed successfully
- Evidence: `logs/benchmarks/m4/m4_episode_20260713_053155_0f5a150e/`

### Probe 16: Replication Failed; Partial Shelter Failures Consumed the Build Reserve

- Episode: `m4_episode_20260713_015708_c2d96dd3`
- Session: `aae8c680-4f8`
- Preflight: passed with a fresh level and lifecycle baseline under unchanged protocol `378689bc96d28580b2debcccb12efb4f955de38dd031e681ace529d4f75d157d`
- G2: false because the completed evidence was deadline-ineligible; pre-dusk progress itself gained `oak_log:1` by world time 9861
- BM-011 eligible: false; accepted eligible successes remain 1/3
- Independent earliest blocker: action event 217 at monotonic 21178.031 / world time 10701; `build_shelter_cell` placed two blocks, failed on an ungrounded third position, left the partial structure, and changed inventory from 16 to 14 oak planks
- Shelter failure cascade: nine same-origin `no grounded neighbor` failures reduced the reserve to nine planks, then the same shelter root emitted fourteen material-threshold rejections without a relocation action; across the episode bounded shelter was 1/36 successful
- Runner-reported later transition: event 682 at monotonic 21379.171 ended the original shelter root with `empty_plan` after real call `llm-cab685fd8d7142d9` returned an invalid control character; it occurred after 23 shelter failures and does not displace the earlier material-loss transition
- Planner controls: 203 calls, 201 real, 200 schema-valid; one early connection error recovered next-cycle, one malformed real response, one deadline-bound final timeout, zero provider-control violations, and 537061 total tokens
- Hostile/death chain: five hostile triggers and five emergency flee actions preceded six Mineflayer death/respawn transitions; Paper independently recorded six matching deaths between 02:03:09 and 02:05:40
- Lifecycle gate: baseline plus six valid 1/1 through 6/6 transition events were canonical; a later missing snapshot after bridge loss emitted an invalid fail-closed lifecycle event, no terminal event was produced, and eligibility rejected all death/respawn and continuity checks
- Late shelter: one 9/9 bounded shelter finally passed at event 1487 / world time 20301 after all six deaths, then was lost after dawn at world time 23341; it cannot restore eligibility
- Goals: 15 total; 4 completed, 5 failed, and 6 interrupted
- Actions: 108 attempted and 29 successful; `build_shelter_cell` 1/36, `move_to` 9/53, `dig` 9/9, `craft` 2/2, `look_at` 1/1, and `wait` 7/7
- Deadline: Agent ended at 22299.750 and evidence ended at 22299.765 against deadline 22299.734; one Planner call/error plan returned 0.016 seconds late, no action executed after the deadline, and independent duration/no-post-deadline checks rejected the episode
- Skill attribution: skills remained off; selected/executed/quarantined counts were all zero
- Next hypothesis: `bounded_shelter_partial_failure_atomicity`; the subsequent offline gate passes and authorizes exactly one Probe 17, while this live result remains ineligible
- Evidence: `logs/benchmarks/m4/m4_episode_20260713_015708_c2d96dd3/`

### Probe 15: First Independently Eligible BM-011 Success

- Episode: `m4_episode_20260713_012907_b900a160`
- Session: `bdf58b2b-51a`
- Preflight: passed under protocol `378689bc96d28580b2debcccb12efb4f955de38dd031e681ace529d4f75d157d`; lifecycle baseline established after the initial Mineflayer spawn with 0/0 episode death/respawn counts
- G2: passed; pre-dusk inventory gained `oak_log:2` and `dark_oak_sapling:1` by world time 9821
- BM-011 eligible: true; accepted eligible successes are now 1/3
- Lifecycle continuity: 84 active observations, one canonical baseline event, maximum death/respawn counts 0/0, no baseline drift, uninterrupted terminal state, and zero Paper death messages
- Planner controls: 42/42 real calls were schema-valid, zero reasoning bytes, maximum latency 10.750 seconds, and zero output or transport recoveries
- Goals: four roots; resource gathering was suspended by dusk, then shelter build, nightfall maintenance, and dawn maintenance completed with no failed root
- Interrupt: one `dusk_shelter_required` trigger at session index 137 and matching recovery at index 342; the paused frontier remained active and no concurrent root appeared
- Actions: 41 attempted and 40 successful; `move_to` 6/7, `dig` 4/4, `craft` 1/1, `build_shelter_cell` 1/1, and `wait` 28/28
- Shelter: pinned G3 verification passed at session index 317 / world time 11801 with all 9/9 placements and remained valid through terminal world time 23281
- Terminal: event index 849 passed with health/food 20, bot online, verified shelter, matching lifecycle signatures, and natural dawn
- Deadline: Agent ended at 20125.703 and canonical evidence ended at 20125.750 against deadline 20618.453, leaving 492.703 seconds; no post-deadline execution
- Skill attribution: skills remained off; selected/executed/quarantined counts were all zero
- First unrecovered transition: none
- Evidence: `logs/benchmarks/m4/m4_episode_20260713_012907_b900a160/`

### Probe 14: Runner Eligible False Positive; Two Zombie Deaths Reopen G0

- Episode: `m4_episode_20260713_002858_94ea560e`
- Session: `2f005489-d89`
- Preflight: passed; manifest limits were exactly `1200/24/40`
- G2: passed; pre-dusk machine progress gained `oak_log:2`
- BM-011 accepted eligible: false; eligible successes remain 0/3 despite runner `eligible=true`
- Death continuity: Paper recorded zombie deaths at 00:34:41 and 00:35:04; canonical health/inventory reset transitions corroborate both, but no death event reached the session or eligibility gate
- First irreversible transition: after hostile interrupt event 1145, the aligned flee root's first real plan emitted `build_shelter_cell`; action event 1179 was rejected as a stale origin while the zombie closed to 1.1 blocks and health fell to about 8, followed by the first death before the next `move_to` executed
- Planner recovery: 80 calls, 78 real schema-valid responses, two single-attempt `APIConnectionError -> ConnectError -> ConnectError -> SSLEOFError` failures, and two matching `m4_planner_transport_recovery` events preserving the same goal; zero empty/output recoveries
- Actions: 78 attempted, 32 successful; all 10 digs and 12 waits succeeded, 4/5 crafts succeeded, and 1/43 bounded shelter builds succeeded
- Shelter: the emergency shelter root recovered after both deaths, passed the pinned G3 verifier with 9/9 placements at world time 17832, and remained verified through terminal world time 23172
- Safe-state retest: no hostile entered the verified-shelter threat window; zero `m4_hostile_safe_state_grounding` events, so the Probe 13 branch was not exercised live
- Terminal snapshot: machine event passed at world time 23172 with health/food 20, bot online, verified shelter, and `dark_oak_planks:3`; it is insufficient because uninterrupted survival was false
- Deadline: Agent ended at 16511.000 and evidence at 16511.046 against deadline 17010.046, leaving 499.000 seconds; no post-deadline execution
- Skill attribution: skills remained off; selected/executed/quarantined counts were all zero
- Evidence: `logs/benchmarks/m4/m4_episode_20260713_002858_94ea560e/`

### Probe 13: Natural Dawn Observed; Hostile Interrupt Exited Verified Shelter

- Episode: `m4_episode_20260712_234515_7644ff79`
- Session: `56274454-2cf`
- Preflight: passed; manifest limits were exactly `1200/24/40`
- G2: passed; pre-dusk machine progress gained `oak_log:2`
- BM-011 eligible: false; eligible successes remain 0/3
- Eligibility narrowed to three issues: missing `terminal_survival_verification`, missing matching terminal machine verification, and `completed=false`
- Planner controls: 98/98 real calls, 82 schema-valid plans, 16 `planning_actions_missing` recoveries, zero transport errors, zero `m4_planner_transport_recovery`, zero empty plans, and no provider-control violations
- Shelter: one bounded action eventually succeeded after eight recovered terrain/origin failures; G3 passed with 9/9 episode placements at world time 12592
- Maintenance: the same `Remain in verified shelter until dawn` root stayed active for 22 cycles and 21 successful waits before the hostile interrupt
- Earliest blocker: observation event 920 / interrupt event 933 / action event 943; a skeleton 5.1 blocks outside a fully sealed, direct-reachability-blocked shelter caused an outward `move_to`
- Safety delta: the emergency action moved 7.894 blocks, changed shelter verification from true to false, and suspended the dawn root at world time 22152
- Dawn: natural dawn was observed at event 1057, world time 23092, health 19, bot online, but shelter verification remained false and no terminal event was emitted
- Episode end: 24 goals consumed the exact goal budget at world time 5392 with 187.156 seconds of Agent budget remaining; 18 goals completed, 6 were interrupted, and none were reported failed
- Actions: 65 attempted, 49 successful; all 21 waits, 14 digs, and two crafts succeeded
- Deadline: eligible; no post-deadline action, plan, or Planner call
- Skill attribution: skills remained off; selected/executed/quarantined counts were all zero
- Evidence: `logs/benchmarks/m4/m4_episode_20260712_234515_7644ff79/`

### Probe 12: Exact Runtime Profile Passed; Planner Transport Error Abandoned Dawn Root

- Episode: `m4_episode_20260712_230251_393445f7`
- Session: `90c6c4f5-6bb`
- Preflight: passed; manifest limits were exactly `1200/24/40`
- G2: failed only because the completed evidence crossed the absolute deadline; pre-dusk machine progress gained `oak_log:2` by world time 9862
- BM-011 eligible: false; eligible successes remain 0/3
- Planner controls: 231 calls, 229 real schema-valid calls, zero provider-control violations, and two transport failures; maximum successful-call latency was 13.093 seconds
- Shelter and maintenance: one bounded shelter action passed with 9/9 current-episode placements at world time 11282; the same verified shelter remained valid through world time 14902
- First unrecovered transition: Planner call event 506 / empty-plan event 511, call ID `llm-24dd4cd454db4e1e`, cycle 23 of `Remain in verified shelter until dawn`; one `APIConnectionError` caused `termination_reason=empty_plan` with more than 900 seconds remaining
- State at failure: health 20, food 20, `oak_planks:19`, `oak_log:1`, world time 14902, machine shelter verified, and one nearby hostile
- Secondary cascade: the next immediate-threat goal fled the verified cell; shelter verification was lost at time 15362, 11 rebuilds lacked grounded support, one rebuild timed out, and the Agent-side bridge disconnected
- Actions: 76 attempted, 25 successful; one craft, one successful bounded shelter build, eight successful waits, and 51 later failures
- Deadline: Agent ended 0.016 seconds late and manifest evidence 0.031 seconds late; one returned Planner error plan was recorded after the deadline, with no post-deadline action
- Terminal evidence: no `terminal_survival_verification`; terminal bot connection false, and zero-valued fallback observations failed natural-time progression and machine-terminal checks
- Evidence: `logs/benchmarks/m4/m4_episode_20260712_230251_393445f7/`

### Probe 11: Maintenance Root Persisted; Shortened Harness Drift Exposed

- Episode: `m4_episode_20260712_224016_31e10f7d`
- Session: `a9cf79b4-53c`
- Preflight: passed
- G2: failed because terminal evidence crossed the deadline; pre-dusk inventory gained `oak_log:2`
- BM-011 eligible: false; eligible successes remain 0/3
- Planner controls: 21/21 real calls schema-valid, zero reasoning bytes, maximum latency 16.953 seconds
- Maintenance retest: one dawn-maintenance root remained active, two `m4_maintenance_phase_grounding` waits executed, and no replacement goal slot was allocated
- Shelter: bounded action succeeded with 9/9 placements; post-cleanup machine shelter verification remained true
- Terminal state: health 20, food 20, connected, world time 13943, night observed, next dawn not observed
- Runtime-profile finding: world time advanced about 4943 ticks under the nonconforming `240/4/8` harness; the fixed protocol already allows `1200/24/40`, so this run does not prove a protocol temporal-horizon failure
- Deadline: ineligible; Agent reached 9529.859 exactly and manifest evidence ended 0.062 seconds later; no new post-deadline action was started
- Evidence: `logs/benchmarks/m4/m4_episode_20260712_224016_31e10f7d/`

### Probe 10: Bounded Shelter Passed; Goal Budget Ended Before Night

- Episode: `m4_episode_20260712_222631_806bb698`
- Session: `4e5911f8-7d3`
- Preflight: passed
- G2: passed; pre-dusk inventory gained `oak_log:3` by world time 9866
- BM-011 eligible: false; eligible successes remain 0/3
- Planner controls: 13/13 real calls schema-valid, zero reasoning bytes, maximum latency 7.281 seconds
- Shelter retest: six oak logs gathered, 24 planks crafted, one bounded action succeeded, temporary scaffold removed, and G3 verifier passed with 9/9 episode placements
- Actions: 11 attempted and 11 successful; one craft and one bounded shelter action
- First unrecovered transition: two one-cycle verified-shelter maintenance goals consumed goal slots 3 and 4, then event index 304 ended the autonomous loop before night
- Terminal state: health 20, food 20, connected, machine shelter verified, world time 11226; night and next dawn were not observed
- Deadline: eligible; Agent ended with 135.297 seconds and manifest evidence with 135.266 seconds remaining, with no post-deadline execution
- Evidence: `logs/benchmarks/m4/m4_episode_20260712_222631_806bb698/`

### Probe 9: Craft Grounding Passed; Shelter Phase Did Not Start

- Episode: `m4_episode_20260712_061341_1b7218cd`
- Session: `79e7ed21-129`
- Preflight: passed
- G2: failed; pre-dusk inventory gained only `oak_sapling:2`, while the first oak log arrived after dusk
- BM-011 eligible: false; eligible successes remain 0/3
- Planner controls: 26/26 real calls schema-valid; one final deadline-bound call timed out, zero reasoning bytes, maximum successful-call latency 9.641 seconds
- Craft-grounding retest: one canonical craft succeeded and produced `oak_planks:16`; no recipe-alias rejection recurred
- Actions: 27 attempted, 19 successful, one successful craft, zero place actions
- First unrecovered transition: after observing 16 planks, Planner call `llm-05670ca498a34ebf` expanded into unrelated tool/furnace work and returned to gathering rather than starting the already-unblocked shelter build
- Interrupt audit: one dusk shelter trigger preserved the frontier and escalated under the same trigger at night, with no competing root
- Deadline: ineligible; the final Planner call timed out at 281785.500, 0.016 seconds after the absolute deadline, and no later action executed
- Evidence: `logs/benchmarks/m4/m4_episode_20260712_061341_1b7218cd/`

### Probe 8: Task Reconciliation Passed; Craft Parameters Rejected

- Episode: `m4_episode_20260712_060223_239f1dde`
- Session: `dd883cea-eb9`
- Preflight: passed
- G2: report returned false because terminal evidence was deadline-ineligible; pre-dusk machine progress was present (`oak_log:3`, `oak_sapling:1` at world time 9943)
- BM-011 eligible: false; eligible successes remain 0/3
- Planner controls: passed for 30/30 real schema-valid calls, zero reasoning bytes, maximum latency 10.295 seconds
- Task-reconciliation retest: one event completed seven fulfilled gather tasks at `oak_log:6`, and the next behavior advanced to craft
- Actions: 30 attempted, 17 successful; 11 craft attempts, zero successful crafts, zero shelter placements
- First unrecovered transition: event index 207 attempted `craft` with `recipe=oak_planks` instead of canonical `item=oak_planks`; ActionVerifier rejected it at monotonic 280930.390
- Interrupt audit: one dusk shelter trigger preserved the frontier and escalated under the same trigger at night, with no competing root
- Deadline: ineligible; Agent reached the absolute deadline and manifest evidence ended 0.015 seconds later; the deadline-bound final move was not replayed or reconnected
- Evidence: `logs/benchmarks/m4/m4_episode_20260712_060223_239f1dde/`

### Probe 7: Action Grounding Passed; Task Readiness Did Not Converge

- Episode: `m4_episode_20260712_054638_ac6ac8de`
- Session: `b2f136c9-aa7`
- Preflight: passed
- G2: report returned false because terminal evidence was deadline-ineligible; pre-dusk machine progress itself was present (`oak_log:2`, `dark_oak_sapling:1` at world time 9889)
- BM-011 eligible: false; eligible successes remain 0/3
- Planner controls: passed for 22/22 real schema-valid calls, zero reasoning bytes, maximum latency 6.280 seconds
- Action-grounding retest: 9/9 canonical `dig` actions passed ActionVerifier and succeeded; inventory reached `oak_log:11`
- Actions: 21 attempted, 15 successful, zero craft actions, zero place actions
- First unrecovered transition: with `oak_log:9` already observed at event index 366, Planner call `llm-1ef73e3cdfab47e3` at event index 376 continued the fulfilled `Gather 6 oak logs` task instead of advancing to craft/build
- Interrupt audit: one dusk shelter trigger suspended the resource goal and preserved its frontier; the same trigger escalated at night with no duplicate root, but no recovery occurred before termination
- Deadline: ineligible; the final deadline-bound `move_to` returned at 280160.234, 0.016 seconds after the absolute deadline, with no replay or reconnect
- Evidence: `logs/benchmarks/m4/m4_episode_20260712_054638_ac6ac8de/`

### Probe 6: M4 Plan Envelope Recovery and G2 Passed

- Episode: `m4_episode_20260711_231148_fb3a1544`
- Session: `e79d7321-799`
- Preflight: passed
- G2: passed; G3 shelter-verifier work is unlocked
- BM-011 eligible: false; eligible successes remain 0/3
- Planner controls: passed for 32/32 real schema-valid Planner calls, zero reasoning bytes, maximum latency 10.546 seconds
- Plan-envelope retest: all 32 plans passed, zero `empty_plan` events, and zero `m4_planner_output_recovery` events; the prior failure did not recur
- Autonomous goals: 4; resource progression switched to dusk and night shelter priority
- Actions: 22 attempted and 2 successful; pre-dusk inventory gained `oak_log:1` and `dark_oak_sapling:1` by world time 9952
- First unrecovered transition: event index 138 rejected an alias-style `dig` using `block_name` plus nested `position`; canonical `dig` requires top-level coordinates and optional `block`
- Grounding audit: 17 alias-style `dig` rejections in total; an earlier rejection recovered, but the 16 rejections from event 138 onward did not, and no later action succeeded
- Reflection audit: 20 `failure_reflection_suppressed` events and zero legacy `failure_reflection` writes
- Interrupt audit: 11 unique deadline triggers, 11 matching recoveries, 96 unique expired tasks terminalized, no repeated trigger task, and 11 actions followed the first recovery
- Deadline: eligible; Agent ended at 256451.531 and manifest evidence ended at 256451.578, leaving 7.281 seconds before the absolute deadline with no post-deadline execution
- Evidence: `logs/benchmarks/m4/m4_episode_20260711_231148_fb3a1544/`

### Probe 5: M4 Failure Reflection Suppressed

- Episode: `m4_episode_20260711_220626_c1555273`
- Session: `df0ff546-6c2`
- Preflight: passed
- G2: failed
- BM-011 eligible: false; eligible successes remain 0/3
- Planner controls: passed for 22/22 real schema-valid Planner calls out of 23 total calls, zero reasoning bytes, maximum latency 24.625 seconds
- Autonomous goals: 4; resource progression switched to dusk and night shelter priority
- Actions: 28 attempted and 22 successful; pre-dusk inventory gained `dark_oak_log:3`, terminal inventory reached `dark_oak_log:10`, and all required G2 recording fields were present
- Reflection retest: 6 `failure_reflection_suppressed` events and zero legacy `failure_reflection` writes; immediate replanning remained active
- First unrecovered transition: event index 160 emitted `empty_plan` for the explicit oak-log goal while `status=planning`; Planner prose treated six dark-oak logs as completion, but no actions or machine goal verification followed and the goal was abandoned
- Interrupt audit: 7 unique deadline triggers, 7 matching recoveries, 29 unique expired tasks terminalized, no repeated trigger task, and 5 action events followed the first recovery
- Deadline: ineligible; Agent ended at the absolute deadline and manifest evidence ended 0.094 seconds later, with one Planner call and error plan recorded at the boundary but no subsequent action
- Evidence: `logs/benchmarks/m4/m4_episode_20260711_220626_c1555273/`

### Probe 4: Expired Task Lifecycle Recovery

- Episode: `m4_episode_20260711_213951_5e37c97d`
- Session: `c3e63af5-76d`
- Preflight: passed
- G2: failed
- BM-011 eligible: false; eligible successes remain 0/3
- Planner controls: passed for 17/17 real schema-valid Planner calls, zero reasoning bytes, maximum latency 10.608 seconds
- Autonomous goals: 4; resource progression switched to emergency shelter priority at night
- Actions: 19 attempted and 15 successful; terminal inventory gained `oak_log:4` and `dark_oak_log:4`, but pre-dusk inventory delta remained empty
- Interrupt retest: 7 unique deadline triggers, 7 recoveries, 28 expired tasks terminalized, no repeated trigger task, and actions resumed after the first recovery
- First unrecovered transition: a failed move at world time 9494 entered an unbounded, unlogged failure-reflection LLM call for 29.985 seconds; the next observation was after dusk at world time 10094
- Deadline: ineligible; Agent ended 0.016 seconds and manifest evidence ended 0.078 seconds after the absolute deadline, with one late Planner call and plan but no post-deadline action
- Evidence: `logs/benchmarks/m4/m4_episode_20260711_213951_5e37c97d/`

### Probe 3: Bridge Action Budget Bound

- Episode: `m4_episode_20260711_183833_d5ef78a8`
- Session: `15173437-4b6`
- Preflight: passed
- G2: failed
- BM-011 eligible: false; eligible successes remain 0/3
- Planner controls: passed; 26/26 real schema-valid calls, zero reasoning bytes, maximum latency 12.781 seconds
- Autonomous goals: 4; priority moved from resource progression to dusk/night shelter preparation
- Actions: 6 attempted and 6 successful; pre-dusk inventory gained `oak_log:1` and `oak_sapling:1`
- Bridge retest: oak-log `dig` completed in 4.046 seconds with a 60-second transport bound; the bridge stayed connected
- First unrecovered transition: expired active task `af7fad99` interrupted action execution at monotonic 239869.781, then repeated 21 times without a task state transition
- Deadline: ineligible; manifest evidence ended 0.094 seconds after the absolute deadline, with no post-deadline action, plan, or Planner call
- Evidence: `logs/benchmarks/m4/m4_episode_20260711_183833_d5ef78a8/`

### Probe 2: Provider Controls Pinned

- Episode: `m4_episode_20260711_180909_9129569c`
- Session: `e2c566f5-1b7`
- Preflight: passed
- G2: failed
- BM-011 eligible: false; eligible successes remain 0/3
- Planner controls: passed; 32/32 real schema-valid calls, zero reasoning bytes, maximum latency 10.391 seconds
- Autonomous goals: 4, all generated from `wood_reserve_below_target`
- Actions: 12 attempted, 4 successful; no qualifying pre-dusk inventory or block delta
- First unrecovered transition: `dig(103,140,-30)` timed out after 15.015 seconds and disconnected the Python bridge
- Deadline: eligible; Agent ended 10.234 seconds before the absolute deadline with no post-deadline execution
- Evidence: `logs/benchmarks/m4/m4_episode_20260711_180909_9129569c/`

### Probe 1: Unpinned Provider Thinking

- Episode: `m4_episode_20260711_170144_4ce51e64`
- Session: `441d17a2-bde`
- Preflight: passed
- G2: failed
- BM-011 eligible: false; eligible successes remain 0/3
- Autonomous goals: 2, both generated from `wood_reserve_below_target`
- Actions: 1 attempted, 0 successful
- Machine-visible inventory/block progress: none
- First unrecovered transition: `pre_dusk_planning_window_exhausted`
- Evidence: `logs/benchmarks/m4/m4_episode_20260711_170144_4ce51e64/`

## Evidence Discipline

- One live episode per round.
- One root-cause hypothesis per round.
- At most one principal subsystem change per round.
- Every live result records unique episode, session, and level identities plus result/session hashes.
- Reset, time set, teleport, give, and gamemode operations are allowed only before `autonomous_start` and are forbidden in the active episode.
- Offline fixtures never count as live capability evidence.
- M4 completion requires BM-011 through BM-014 at 3/3 each. Work stops after M4 and does not enter M5.
