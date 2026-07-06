# Task Suite: Survival — Full Benchmark Definitions

## BM-001: Chop 3 Oak Logs
- Seed: 12345 | Version: 1.20.4 | Max time: 120s | Max tokens: 5000
- Start: Player at spawn, empty inventory, daytime
- Success: 3+ oak_log in inventory
- Failure: Death, timeout, wrong item collected
- Metrics: time, tokens, blocks_broken, distance_traveled

## BM-002: Craft a Workbench
- Seed: 12345 | Version: 1.20.4 | Max time: 60s | Max tokens: 3000
- Start: Player at spawn with 4 oak_planks
- Success: 1 crafting_table in inventory
- Failure: Death, timeout, material wasted
- Metrics: time, tokens, craft_attempts

## BM-003: Craft a Wooden Pickaxe
- Seed: 12345 | Version: 1.20.4 | Max time: 120s | Max tokens: 5000
- Start: Player at spawn with 3 oak_planks + 2 sticks
- Success: 1 wooden_pickaxe in inventory
- Failure: Death, timeout, wrong recipe
- Metrics: time, tokens, craft_attempts

## BM-004: Mine 5 Cobblestone
- Seed: 12345 | Version: 1.20.4 | Max time: 180s | Max tokens: 8000
- Start: Player at spawn with wooden_pickaxe
- Success: 5+ cobblestone in inventory
- Failure: Death, timeout, pickaxe broken without getting stone
- Metrics: time, tokens, blocks_mined, distance_traveled, tool_durability_used

## BM-005: Craft a Stone Pickaxe
- Seed: 12345 | Version: 1.20.4 | Max time: 180s | Max tokens: 8000
- Start: Player at spawn with 3 cobblestone + 2 sticks
- Success: 1 stone_pickaxe in inventory
- Failure: Death, timeout, wrong recipe
- Metrics: time, tokens, craft_attempts

## Evaluation Protocol
1. Start MC server with fixed seed
2. Connect bot, teleport to spawn
3. Set inventory to benchmark starting items
4. Issue natural language goal to agent
5. Log all observations, actions, LLM calls
6. Check success criteria at timeout or completion
7. Record all metrics to experiment log
8. Repeat 3x for statistical significance
