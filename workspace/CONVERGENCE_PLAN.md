# M1 Convergence Plan

## Objective

Move the Minimum Viable Bot from `live_failing` to `repeat_verified`. Until then, work is limited to:

`Paper server -> Mineflayer -> TCP bridge -> observation -> deterministic planner -> action verification/execution -> post-observation -> goal verification -> evidence`

M2-M7, vision, learned skills, weighted memory, plan cache, self-evolution, frontier budgets, episode abort, policy mutation, and LLM critics are isolated from M1 acceptance runs.

## Current Gate

`G0_RUNTIME_AVAILABLE`: **failing**

- `mc-server/server.jar`, `mc-server/server.properties`, and manually accepted `mc-server/eula.txt` are absent.
- No Minecraft server is listening on `localhost:25565`.
- `127.0.0.1:3000` is an unrelated Windows service and fails the Singularity health protocol.
- Latest raw evidence: `logs/benchmarks/m1_preflight_20260710_142227.json` (`sha256=e542670efd191db84298690e252eb9561688fcaea35bca10c70b7ddaf7cd2c41`).
- The preflight is explicitly non-capability evidence. No live task ran in this loop.

`G1_HARNESS_VALID` is implemented and offline-tested, but it remains live-unverified behind G0.

## Ordered Gates

| Gate | Exit condition | Current state |
|---|---|---|
| G0 Runtime available | Controlled Paper 1.20.4 server; fixed seed; manually accepted EULA; valid bridge/session/harness | Failing |
| G1 Harness valid | Fresh level per task; verified reset; exact task inventory/fixture; deterministic isolated runtime; immutable session | Offline ready, live unverified |
| G2 BM-001 live observed | Three oak logs plus Goal Verifier; truthful navigation and dig/pickup deltas | 0 successes |
| G3 BM-002..005 live observed | One eligible live success per task with craft/dig state deltas | 0/4 tasks |
| G4 Repeat verified | Three distinct eligible successes for each BM-001..005 under one server-jar hash | 0/15 successes |
| G5 Capability report | M1 reads `repeat_verified`; offline/mock/synthetic contribute zero | Failing |

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

- Minecraft `1.20.4`; Paper; a single server-jar SHA-256 across all eligible sessions
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
- Session ID, episode ID, session hash, and server-jar hash are independently checked. Copies and mixed-server campaigns are ineligible.
- Offline, mock, synthetic, planner text, and backend success text contribute zero live successes.

## Eliminated Hypotheses

- An open TCP port proves Bridge readiness: false; protocol identity and bot session are now required.
- Historical BM-002..005 failures prove recipe logic is primary: unsupported; their canonical starting inventories were absent.
- BM-004 needs only three cobblestone: false; the canonical threshold is five.
- Environment API credentials can silently select the LLM planner: prevented by the forced RuleBasedPlanner profile.
- Nonempty pre/post payloads prove action success: false; target inventory and source-block deltas are now checked.
- Reusing a session under another result path can satisfy repeats: false; session, episode, log hash, and Paper jar hash are deduplicated.

## Current Repair Hypothesis

The earliest causal blocker is external runtime provisioning, not another planner feature. Once a controlled Paper runtime is available, the highest-information experiment is one fresh BM-001 attempt. Its first unrecovered transition will determine the next code change.

## One-Command Run

After placing Paper 1.20.4 at `mc-server/server.jar`, manually accepting the EULA, setting `level-seed=12345`, `online-mode=false`, `server-port=25565`, and adding `Singularity` to `ops.json`, run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/m1-runtime.ps1 -RunBenchmark -TaskId BM-001
```

The script creates a fresh level, uses bridge port `30000`, records the exact server jar hash, runs M1 preflight, executes only BM-001, writes immutable evidence, restores `server.properties`, and stops only processes it owns. It never edits or accepts `eula.txt`.

## Acceptance Progress

| Task | Eligible live successes | Required |
|---|---:|---:|
| BM-001 | 0 | 3 |
| BM-002 | 0 | 3 |
| BM-003 | 0 | 3 |
| BM-004 | 0 | 3 |
| BM-005 | 0 | 3 |

Next experiment: provision the external server prerequisites and run the exact BM-001 command above. Do not start another feature branch while G0 is failing.
