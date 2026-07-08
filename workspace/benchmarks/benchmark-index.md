# Benchmark Index
> Last updated: 2026-07-08

## M1 Benchmarks (5 tasks)

| ID | Task | Success Criteria | Max Time | Phase |
|----|------|-----------------|----------|-------|
| BM-001 | Chop 3 oak logs | 3 oak_log in inventory | 120s | M1 |
| BM-002 | Craft a workbench | 1 crafting_table in inventory | 60s | M1 |
| BM-003 | Craft a wooden pickaxe | 1 wooden_pickaxe in inventory | 120s | M1 |
| BM-004 | Mine 5 cobblestone | 5 cobblestone in inventory | 180s | M1 |
| BM-005 | Craft a stone pickaxe | 1 stone_pickaxe in inventory | 180s | M1 |

## M2 Benchmarks (5 tasks)

| ID | Task | Success Criteria | Max Time | Phase |
|----|------|-----------------|----------|-------|
| BM-006 | Gather wood and craft workbench | workbench in inventory | 180s | M2 |
| BM-007 | Craft wooden pickaxe and get cobblestone | cobblestone in inventory | 300s | M2 |
| BM-008 | Find coal or make charcoal | coal/charcoal in inventory | 300s | M2 |
| BM-009 | Craft a torch | torch in inventory | 180s | M2 |
| BM-010 | Build a simple 5x5 shelter | shelter structure exists | 600s | M2 |

## M3+ Benchmarks

| ID | Task | Success Criteria | Max Time | Phase |
|----|------|-----------------|----------|-------|
| BM-011 | Survive the first night | alive at dawn | 1200s | M3 |
| BM-012 | Get 8 iron ore | 8 iron_ore in inventory | 600s | M3 |
| BM-013 | Smelt iron ingot | iron_ingot in inventory | 300s | M3 |
| BM-014 | Craft iron pickaxe | iron_pickaxe in inventory | 300s | M3 |

## M7 Collaboration Benchmarks

| ID | Task | Success Criteria | Max Time | Phase |
|----|------|-----------------|----------|-------|
| BM-701 | Time-sensitive shared shelter | wood delivered, shelter frame done, torch ready before hostile nightfall | 420s | M7 |

## Benchmark Format
Each benchmark records: seed, MC version, bot version, model, task description, success criteria, max time, max tokens, human intervention allowed, result, log, failure reason, and reviewed policy-skill intervention metrics.

## M7 Collaboration Format
M7 benchmark specs are JSON documents with roles, tasks, deadlines, dynamic events, shared state, success criteria, and static feasibility checks. See `m7_time_sensitive_shelter.json`.
