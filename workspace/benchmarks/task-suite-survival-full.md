# Task Suite: M1 Survival Benchmarks

The machine-readable source of truth is `src/singularity/data/m1_protocol.json`. Offline fixtures never count toward the live totals below.

## Fixed Runtime

- Minecraft: `1.20.4`
- Server: Paper `1.20.4` build `499`, SHA-256 `cabed3ae77cf55deba7c7d8722bc9cfd5e991201c211665f9265616d9fe5c77b`
- Dependencies: Mineflayer `4.37.1`, mineflayer-pathfinder `2.4.5`, minecraft-data `3.111.0`
- World: seed `12345`, a new level name for every task attempt, world spawn as the reset origin
- Player: survival, peaceful, full health/food
- Time/weather: tick `1000`, clear
- Runtime identities: `singularity-agent-v1`, `rule-based-v1`, `mineflayer-bridge-v1`, `goal-action-verifier-v1`
- Action timeout: 30 seconds

## BM-001: Chop 3 Oak Logs

- Limit: 50 cycles / 120 seconds
- Start: empty inventory
- Success: `oak_log >= 3`
- Required evidence: grounded oak-log coordinates, successful dig, source block removed in pre/post observations, and oak-log inventory increase

## BM-002: Craft a Workbench

- Limit: 30 cycles / 60 seconds
- Start: `oak_planks = 4`
- Success: `crafting_table >= 1`
- Required evidence: successful craft plus crafting-table inventory increase in pre/post observations

## BM-003: Craft a Wooden Pickaxe

- Limit: 60 cycles / 120 seconds
- Start: `oak_planks = 3`, `stick = 2`, and one crafting table at `(spawn + 1, 0, 0)`
- Success: `wooden_pickaxe >= 1`
- Required evidence: the observed nearby crafting table is passed to Mineflayer and the wooden-pickaxe inventory increases

## BM-004: Mine 5 Cobblestone

- Limit: 40 cycles / 180 seconds
- Start: `wooden_pickaxe = 1`
- Success: `cobblestone >= 5`
- Required evidence: every counted dig uses observed stone coordinates; pre/post observations prove block removal and cobblestone pickup

## BM-005: Craft a Stone Pickaxe

- Limit: 80 cycles / 180 seconds
- Start: `cobblestone = 3`, `stick = 2`, and one crafting table at `(spawn + 1, 0, 0)`
- Success: `stone_pickaxe >= 1`
- Required evidence: the observed nearby crafting table is passed to Mineflayer and the stone-pickaxe inventory increases

## Evaluation Protocol

1. Provision `mc-server/server.jar`, accept the EULA manually, configure seed `12345` and offline mode, and operator-enable the `Singularity` bot.
2. Run exactly one task in one fresh episode:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/m1-runtime.ps1 -RunBenchmark -TaskId BM-001
   ```

3. Require the protocol-aware preflight, verified reset event, isolated deterministic runtime profile, action pre/post observations, Goal Verifier success, terminal inventory criteria, and a complete immutable session JSONL.
4. Reject any successful movement without `reached=true` or with final distance outside its declared tolerance.
5. Reject any dependent dig/place/craft after an unreached movement in the same plan cycle.
6. Reject copied sessions, repeated episode IDs, repeated session hashes, mixed Paper jar hashes, mock evidence, and synthetic evidence.
7. Repeat each task in three distinct fresh episodes. M1 requires 15 eligible live successes and a `repeat_verified` capability report.
