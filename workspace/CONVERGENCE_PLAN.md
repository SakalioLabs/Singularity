# M1 Convergence Plan

## Objective

Move the Minimum Viable Bot from `live_failing` to `repeat_verified`. Until then, work is limited to:

`Paper server -> Mineflayer -> TCP bridge -> observation -> deterministic planner -> action verification/execution -> post-observation -> goal verification -> evidence`

M2-M7, vision, learned skills, weighted memory, plan cache, self-evolution, frontier budgets, episode abort, policy mutation, and LLM critics are isolated from M1 acceptance runs.

## Current Gate

`G5_CAPABILITY_REPORT`: **complete**

- The user authorized EULA acceptance; the controlled Paper `1.20.4` build `499` runtime then passed live preflight in every counted episode.
- BM-001..005 each have three distinct protocol-eligible live successes: `15/15` total.
- All 15 successes use distinct session IDs, episode IDs, level names, session hashes, and result hashes under one pinned Paper jar hash and one protocol hash.
- The authoritative capability report reads M1 as `repeat_verified`; offline, mock, synthetic, setup, and failed evidence contribute zero successes.
- Paper and the Bridge are stopped after collection; ports `25565` and `30000` are not left listening.

## Ordered Gates

| Gate | Exit condition | Current state |
|---|---|---|
| G0 Runtime available | Controlled Paper 1.20.4 server; fixed seed; accepted EULA; valid bridge/session/harness | Complete |
| G1 Harness valid | Fresh level per task; verified reset; exact task inventory/fixture; deterministic isolated runtime; immutable session | Complete |
| G2 BM-001 live observed | Three oak logs plus Goal Verifier; truthful navigation and dig/pickup deltas | Complete: 3/3 |
| G3 BM-002..005 live observed | One eligible live success per task with craft/dig state deltas | Complete: 4/4 tasks observed |
| G4 Repeat verified | Three distinct eligible successes for each BM-001..005 under one server-jar hash | Complete: 15/15 |
| G5 Capability report | M1 reads `repeat_verified`; offline/mock/synthetic contribute zero | Complete |

Only the earliest failing gate changes in a convergence loop. A downstream result cannot upgrade an upstream gate.

## Canonical Protocol

The source of truth is `src/singularity/data/m1_protocol.json`.

| Task | Start inventory / fixture | Limit | Success |
|---|---|---|---|
| BM-001 | empty | 50 cycles / 120s | `oak_log >= 3` |
| BM-002 | `oak_planks = 4` | 30 / 60s | `crafting_table >= 1` |
| BM-003 | `oak_planks = 3`, `stick = 2`; nearby table | 60 / 120s | `wooden_pickaxe >= 1` |
| BM-004 | `wooden_pickaxe = 1` | 40 / 180s | `cobblestone >= 5` |
| BM-005 | `cobblestone = 3`, `stick = 2`; nearby table | 80 / 180s | `stone_pickaxe >= 1` |

Fixed identities and environment:

- Minecraft `1.20.4`; Paper build `499`; jar SHA-256 `cabed3ae77cf55deba7c7d8722bc9cfd5e991201c211665f9265616d9fe5c77b`
- Mineflayer `4.37.1`; pathfinder `2.4.5`; minecraft-data `3.111.0`
- Seed `12345`; fresh level per task; world spawn; peaceful; survival; tick `1000`; clear weather
- Agent `singularity-agent-v1`; planner `rule-based-v1`; backend `mineflayer-bridge-v1`; verifier `goal-action-verifier-v1`
- Maximum action timeout 30 seconds

## Evidence Rules

- New session, benchmark, preflight, and runtime files are timestamped; historical evidence is never overwritten.
- Success requires a real Minecraft connection, verified reset, complete session boundary, terminal inventory criteria, and an achieved Goal Verifier event.
- Successful navigation requires `success=true`, `reached=true`, and final distance no greater than tolerance.
- Dig requires grounded coordinates, an observed source block before the action, its removal after the action, and target-item pickup in inventory.
- Craft requires the requested target item to increase in pre/post inventory observations; 3x3 recipes require an observed nearby workbench.
- An unreached movement terminates its dependent plan suffix before dig/place/craft.
- Session ID, episode ID, session hash, and pinned server-jar hash are independently checked. Copies and any other Paper build are ineligible.
- Offline, mock, synthetic, planner text, and backend success text contribute zero live successes.

## Eliminated Hypotheses

- An open TCP port proves Bridge readiness: false; protocol identity and bot session are now required.
- Historical BM-002..005 failures prove recipe logic is primary: unsupported; their canonical starting inventories were absent.
- BM-004 needs only three cobblestone: false; the canonical threshold is five.
- Environment API credentials can silently select the LLM planner: prevented by the forced RuleBasedPlanner profile.
- Nonempty pre/post payloads prove action success: false; target inventory and source-block deltas are now checked.
- Reusing a session under another result path can satisfy repeats: false; session, episode, log hash, and Paper jar hash are deduplicated.

## Resolved Failure Chain

Live traces localized and resolved the M1 blockers in order: exact oak targeting, horizontal interaction reach, per-species tree visibility, measured navigation completion, active item pickup, stone search, source-to-drop mapping, three-dimensional pickup approach, target-specific inventory waiting, and non-replayed dig commands. The failure ledger retains every rejected run and its superseding evidence.

## One-Command Run

The runtime is provisioned and EULA acceptance is recorded in the ignored local server directory. Reproduce one fresh task with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/m1-runtime.ps1 -RunBenchmark -TaskId BM-001
```

The script creates a fresh level, uses bridge port `30000`, records the exact server jar hash, runs M1 preflight, executes only BM-001, writes immutable evidence, restores `server.properties`, and stops only processes it owns. It never edits or accepts `eula.txt`.

## Acceptance Progress

| Task | Eligible live successes | Required |
|---|---:|---:|
| BM-001 | 3 | 3 |
| BM-002 | 3 | 3 |
| BM-003 | 3 | 3 |
| BM-004 | 3 | 3 |
| BM-005 | 3 | 3 |

No M1 acceptance work remains. Later milestone work may resume only under its own evidence gates; M1 evidence remains immutable.
