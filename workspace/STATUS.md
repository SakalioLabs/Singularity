# STATUS.md | Last updated: 2026-07-07

## Current Phase: M1 Complete, M2/M3/M4/M5 Integration Complete

## Phase Progress
| Phase | Status | Progress |
|-------|--------|----------|
| M0: Research Baseline | **Complete** | 100% |
| M1: Minimum Viable Bot | **Complete** | 100% |
| M2: LLM Task Planning | **Integration Complete** | 85% |
| M3: Skill Library & Memory | **Integration Complete** | 80% |
| M4: Autonomous Survival | **Integration Complete** | 70% |
| M5: Open-World Exploration | **Integration Complete** | 60% |
| M6: Vision & Multimodal | Research Only | 10% |
| M7: Multi-Agent Collab | Research Only | 5% |

## Source Code (26 Python + 1 JS files)
- **core**: agent.py (full M1-M5 integration), config.py, planner.py, reflector.py, task_system.py, skill_library.py, memory.py, skill_extractor.py, goal_generator.py, explorer.py, rule_planner.py
- **llm**: provider.py (OpenAI/Anthropic/Ollama)
- **observation**: observer.py (32-block tree scanning)
- **action**: controller.py (10 action types with safety checks)
- **bot**: bridge.py (retry logic with exponential backoff)
- **logging**: session_logger.py (JSONL structured logging)
- **data**: knowledge_base.py (BOM-safe recipe loading), crafting_recipes.json
- **evaluation**: benchmark_runner.py (M1/M2 suites)
- **tests**: test_comprehensive.py (82 tests), test_goal_generator.py (6 tests), test_m2_integration.py (1 test)

## Key Milestones (Latest)
- **89/89 tests passing** (82 comprehensive + 7 existing)
- Agent fully integrated with MemorySystem, SkillLibrary, TaskSystem, GoalGenerator, Explorer
- Autonomous survival mode implemented (M4 GoalGenerator + M5 Explorer)
- Rule planner ordering fixed for stone pickaxe crafting
- Knowledge base BOM encoding fixed
- KnowledgeBase.list_recipes() and get_recipe_chain() return list
- CLI supports `run`, `autonomous`, `benchmark`, `skills` commands

## What This Means
- **M1 (100%)**: Bot connects, reads state, executes all 10 action types, session logging works
- **M2 (85%)**: LLM planner wired with memory context injection and skill recommendations; needs live API testing
- **M3 (80%)**: Memory (L0-L6) and skills (17 builtins) integrated into agent loop; needs extraction from real sessions
- **M4 (70%)**: GoalGenerator proposes survival goals by priority (threat > health > night > tools > resources); integrated into autonomous mode
- **M5 (60%)**: Explorer tracks landmarks, path history, base return logic; integrated into autonomous loop

## Next Priorities
1. Run BM-001 through BM-005 with live MC server + bot bridge
2. Run autonomous mode against live server to validate M4/M5 integration
3. M2 end-to-end testing with real LLM API
4. M3 skill extraction from real session logs
5. M6 vision research deep-dive
