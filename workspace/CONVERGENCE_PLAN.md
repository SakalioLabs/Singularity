# M1 Convergence Plan

## Objective

Move the Minimum Viable Bot from `live_failing` to `repeat_verified`. Until that gate passes, work is limited to the Minecraft 1.20.4 execution path:

`Paper server -> Mineflayer -> TCP bridge -> observation -> deterministic planner -> action verification/execution -> post-observation -> goal verification -> evidence`

M2-M7 work, research-driven feature additions, vision, learned skills, weighted memory, plan cache, self-evolution, frontier budgets, episode abort, policy mutation, and LLM critics are frozen for M1 acceptance runs.

## Current Gate

`G0_RUNTIME_AVAILABLE`: **failing**

- No Minecraft server is listening on `localhost:25565`.
- No server jar, `server.properties`, or manually accepted `eula.txt` exists under `mc-server/`.
- `127.0.0.1:3000` belongs to an unrelated Windows service. It accepts TCP but does not implement the Singularity health protocol.
- Raw evidence: `logs/benchmarks/m1_preflight_20260710_131157.json`.

The preflight now requires a valid `health` response with `success=true` and `bridge=true`; an arbitrary TCP listener cannot satisfy the bridge gate.

## Ordered Gates

| Gate | Exit condition | Evidence |
|---|---|---|
| G0 Runtime available | Controlled Paper 1.20.4 server on seed `12345`; EULA accepted manually; Singularity bridge on an unused port; expected username/version/MC port; bot spawned | Timestamped `m1_preflight_*.json` plus server/bridge logs |
| G1 Harness valid | Every task starts at spawn/daytime with its canonical inventory, reset postconditions are observed, BM-004 requires five cobblestone, advanced modules are disabled, and each task has its own session log | Reset event, effective M1 runtime profile, pre/post state, and verifier result in every session |
| G2 BM-001 live observed | Three oak logs in post-observation and goal verifier; all movement has `reached=true` plus final tolerance proof | One passing live session |
| G3 BM-002..005 live observed | Craft/dig outcomes proven by pre/post inventory or world state; no dependent action follows unreached navigation | One passing live session per task |
| G4 Repeat verified | BM-001..005 each pass in three distinct complete sessions under the same fixed protocol | Fifteen distinct passing session manifests |
| G5 Capability report | Capability evidence reports M1 as `repeat_verified`; offline/mock/synthetic records contribute zero live counts | `workspace/evals/capability_evidence_current.json` |

Only the earliest failing gate is changed in each loop. A downstream result cannot upgrade an upstream gate.

## Canonical M1 Protocol

| Task | Start inventory | Success |
|---|---|---|
| BM-001 | empty | `oak_log >= 3` |
| BM-002 | `oak_planks = 4` | `crafting_table >= 1` |
| BM-003 | `oak_planks = 3`, `stick = 2` | `wooden_pickaxe >= 1` |
| BM-004 | `wooden_pickaxe = 1` | `cobblestone >= 5` |
| BM-005 | `cobblestone = 3`, `stick = 2` | `stone_pickaxe >= 1` |

Every attempt uses Minecraft `1.20.4`, seed `12345`, spawn position, daytime, survival mode, and a distinct session ID. Initial state and final success are observed, not inferred from planner text or backend return text.

## Evidence Rules

- Never overwrite historical session logs or benchmark reports. New runtime evidence uses timestamped filenames under `logs/benchmarks/`.
- A preflight report is `runtime_preflight`; it explicitly cannot count as `live_observed` or `repeat_verified`.
- An attempt counts only when the bridge is connected to a real Minecraft world, the terminal boundary is complete, and the goal verifier is grounded in post-observation state.
- A movement success requires `success=true`, `reached=true`, final position, target, tolerance, and final distance within tolerance.
- Dig, pickup, and craft success require relevant pre/post state deltas. Backend success text alone is insufficient.
- Any unreached movement defers the dependent plan suffix. A later dig/place/craft from that suffix is a regression.
- Secrets and credentials are excluded from all logs and artifacts.

## One-Command Runtime Preparation

After placing a Paper 1.20.4 jar at `mc-server/server.jar`, manually accepting the EULA, and setting `level-seed=12345` plus `online-mode=false`, run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/m1-runtime.ps1
```

The script uses bridge port `30000`, owns and cleans up only the processes it starts, writes timestamped runtime logs, and runs protocol-aware preflight. It never edits `eula.txt`, never stops an existing listener, and currently stops at G1 rather than collecting invalid benchmark evidence.

## Next Action

Provision the controlled server prerequisites, pass G0 with `scripts/m1-runtime.ps1`, then implement and offline-test the canonical per-task reset contract before any new BM-001..005 acceptance attempt.
