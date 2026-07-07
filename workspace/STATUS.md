# STATUS.md | Last updated: 2026-07-07

## Current Phase: M1 (Minimum Viable Bot) ！ Environment Ready, Benchmarking Pending

## Phase Progress

| Phase | Status | Progress | Notes |
|-------|--------|----------|-------|
| M0: Research Baseline | **Complete** | 100% | 70+ workspace docs, 17 papers, 4 repos, 8 modules |
| M1: Minimum Viable Bot | **In Progress** | 80% | Bot connects, source complete, benchmarks pending |
| M2: LLM Task Planning | Source Complete | 60% | Planner/TaskSystem/Reflector written, need API wiring |
| M3: Skill Library & Memory | Source Complete | 60% | 17 skills, L0-L6 memory, need extraction logic |
| M4: Autonomous Survival | Planned | 10% | Architecture drafted |
| M5: Open-World Exploration | Planned | 10% | Architecture drafted |
| M6: Vision & Multimodal | Planned | 5% | Research only |
| M7: Multi-Agent Collab | Planned | 5% | Research only |

## M0 Complete ！ Research Baseline

- **17 papers** analyzed with detailed cards (Voyager, MineDojo, JARVIS-1, GITM, DEPS, STEVE-1, OmniJARVIS, Mindcraft, Optimus-1, Genie, ReAct, Reflexion, Code-as-Policies, ToT, Toolformer, SkillForge, Multi-Agent MC)
- **4 repos** evaluated (Mindcraft, Mineflayer, Baritone, MineDojo)
- **8 architecture module** docs (Planner, TaskSystem, Memory, SkillLibrary, Perception, ActionController, Evaluator, Safety)
- **5 benchmark suites** with 14 tasks (survival, crafting, exploration, building, collaboration)
- **15+ implementation notes** (tech-stack, mineflayer, baritone, model-provider, api-notes, cost-analysis, etc.)
- **Research analysis** RQ1-RQ10 answered
- **5 architecture decisions** DEC-001 through DEC-005
- **10 risks** RISK-001 through RISK-010

## M1 Progress ！ Minimum Viable Bot

### Environment (Complete)
- [x] Python 3.12.10 with pip deps (openai, anthropic, pydantic)
- [x] Node.js 24.14.1 with npm deps (mineflayer, pathfinder, minecraft-data)
- [x] JDK 17.0.19 installed
- [x] MC 1.20.4 vanilla server downloaded and configured
- [x] Server EULA accepted

### Source Code (Complete)
- [x] `src/singularity/core/agent.py` ！ Main observe-think-act loop (140 lines)
- [x] `src/singularity/core/config.py` ！ BotConfig, LLMConfig, Config dataclasses
- [x] `src/singularity/core/planner.py` ！ LLM-powered goal decomposition
- [x] `src/singularity/core/reflector.py` ！ Failure analysis and re-planning
- [x] `src/singularity/core/skill_library.py` ！ 17 builtin skills, version tracking
- [x] `src/singularity/core/task_system.py` ！ Hierarchical task state machine
- [x] `src/singularity/core/memory.py` ！ L0-L6 multi-layer memory system
- [x] `src/singularity/llm/provider.py` ！ Swappable LLM (OpenAI/Anthropic/Ollama)
- [x] `src/singularity/observation/observer.py` ！ Game state collection
- [x] `src/singularity/action/controller.py` ！ Action execution with safety
- [x] `src/singularity/bot/bridge.py` ！ Python-Node.js TCP socket bridge
- [x] `src/singularity/main.py` ！ CLI entry point
- [x] `src/bot/bot_server.js` ！ Node.js Mineflayer server with Vec3 fix

### Experiments
- [x] **EXP-0001**: Bot "Singularity" connected to MC server at (-9.5, 66.0, 2.5) ！ PASS

### Remaining for M1
- [ ] Session logger with structured JSON output
- [ ] Error handling and retry logic
- [ ] BM-001: Chop 3 oak logs
- [ ] BM-002: Craft workbench
- [ ] BM-003: Craft wooden pickaxe
- [ ] BM-004: Mine cobblestone
- [ ] BM-005: Craft stone tools

## Next Steps

1. Add session logger to Agent (structured JSON per session)
2. Add retry logic with exponential backoff to BotBridge
3. Start MC server and run BM-001 through BM-005
4. Wire Planner to actual LLM API calls for M2
5. Test end-to-end goal: "Gather wood and craft a workbench"

## Repository Status

- **Remotes**: Sakalio-Ling/Singularity (origin), SakalioLabs/Singularity (sakaliolabs)
- **Branch**: master (pushed to both remotes)
- **Commits**: 20+ commits covering M0 research and M1 implementation
- **Working tree**: Clean
