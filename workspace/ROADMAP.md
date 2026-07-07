# ROADMAP.md - Phase Roadmap

> Last updated: 2026-07-07
> Current phase: M1 (Minimum Viable Bot)

## Overview

The project evolves a Minecraft LLM Agent through 8 phases (M0-M7), each building on the previous. Every phase has clear goals, acceptance criteria, key tasks, dependencies, and risks.

---

## M0: Research Baseline

**Status**: **Complete**
**Goal**: Establish paper library, repo library, architecture draft, first benchmark suite, and technical stack decision.
**Acceptance Criteria**:
- [x] At least 20 paper/project cards completed (17 papers + 4 repos = 21)
- [x] current-architecture.md v1 drafted (8 module docs)
- [x] ROADMAP.md finalized
- [x] First benchmark draft with 10+ tasks (14 tasks across 5 suites)
- [x] OPEN_QUESTIONS.md populated (10 questions)
- [x] Tech stack decision documented in DECISIONS.md (5 decisions)

**Completed Deliverables**:
- 70+ workspace documents
- 17 paper cards with scoring (P-001 through P-017)
- 4 repo cards (Mindcraft, Mineflayer, Baritone, MineDojo)
- 8 architecture module docs
- 5 benchmark suites (14 tasks)
- 15+ implementation notes
- Research analysis RQ1-RQ10
- 5 architecture decisions DEC-001 through DEC-005
- 10 risks RISK-001 through RISK-010

**Completion Date**: 2026-07-07

---

## M1: Minimum Viable Bot

**Status**: **In Progress (80%)**
**Goal**: Connect to a local Minecraft server, read basic state, execute simple actions.
**Acceptance Criteria**:
- [x] Bot connects to local Minecraft 1.20.x server via Mineflayer
- [x] Bot reads: position, health, hunger, inventory, nearby blocks, nearby entities, time of day
- [x] Bot executes: move, look, dig, place, craft, attack, open container
- [ ] 5 basic benchmark tasks pass (see benchmarks/)
- [x] Decision/action logs are generated per session

**Completed**:
- [x] Set up local Minecraft server (vanilla 1.20.4)
- [x] Implement Mineflayer bot bridge in Python (via TCP socket)
- [x] Implement observation module (read game state into structured dict)
- [x] Implement primitive action API (move, look, dig, place, craft, attack)
- [x] Session logger (structured JSON log of observations, actions, outcomes)
- [x] EXP-0001: Bot connected to MC server at (-9.5, 66.0, 2.5)
- [x] Retry logic with exponential backoff

**Remaining**:
- [ ] Run BM-001 through BM-005 benchmarks and record results
- [ ] Error handling refinement based on benchmark failures

**Dependencies**: M0 (tech stack decision, architecture draft)
**Risks**: Mineflayer version compatibility, Python-Node.js bridge complexity

---

## M2: LLM Task Planning

**Status**: Source Complete (60%)
**Goal**: Accept natural-language goals, decompose into structured plans, execute subtasks.
**Acceptance Criteria**:
- [ ] "Gather wood and craft a workbench" completes end-to-end
- [ ] "Craft a wooden pickaxe and obtain cobblestone" completes end-to-end
- [ ] At least 1 re-planning event triggered and logged on failure
- [ ] Task system tracks subtask states (proposed/active/completed/failed)

**Completed (Source)**:
- [x] Planner module (LLM-powered, outputs structured JSON plans)
- [x] TaskSystem (hierarchical tasks with states, dependencies, priorities)
- [x] Reflection module (failure analysis, re-plan trigger)
- [x] Integration in Agent.run_goal() loop

**Remaining**:
- [ ] Wire Planner to actual LLM API calls
- [ ] Run M2 acceptance benchmarks
- [ ] Validate JSON parsing reliability

**Dependencies**: M1 (working bot with primitive actions)
**Risks**: LLM hallucination in plans, JSON parsing failures, cost overruns

---

## M3: Skill Library and Long-Term Memory

**Status**: Source Complete (60%)
**Goal**: Successful tasks auto-sink into reusable skills; failures become experience; long-term goals persist across sessions.
**Acceptance Criteria**:
- [ ] At least 10 reusable skills stored with success rate statistics
- [ ] Skill library supports versioning and rollback
- [ ] MEMORY.md auto-updated with validated facts
- [ ] Cross-session goal recovery works
- [ ] Experiment logs and failure cases are searchable

**Completed (Source)**:
- [x] Skill Library (code-based + NL-based skills, versioning, metadata)
- [x] Memory System (L0-L6 layers)
- [x] 17 builtin skills with success rate tracking

**Remaining**:
- [ ] Skill extraction from successful task traces
- [ ] Failure case library
- [ ] Session persistence and recovery
- [ ] Run M3 acceptance benchmarks

**Dependencies**: M2 (LLM planning and task execution)
**Risks**: Skill overfitting, memory pollution, storage growth

---

## M4: Autonomous Survival Loop

**Status**: Planned (10%)
**Goal**: Agent self-directs survival goals: first-night shelter, resource gathering, tool progression, threat response.
**Acceptance Criteria**:
- [ ] Survives first night on a fixed seed (3+ repeated experiments)
- [ ] Self-proposes next survival goals without human input
- [ ] Handles nighttime threats (shelter, combat, retreat)
- [ ] Logs success rate and failure types

**Key Tasks**:
1. Implement strategic goal generation (bootstrapping -> resource chain -> tech tree)
2. Implement night cycle awareness and shelter strategy
3. Implement combat/threat response skills
4. Implement resource inventory management
5. Run 3+ repeated survival experiments on fixed seeds

**Dependencies**: M3 (skill library, memory, task system)
**Risks**: Long task chains accumulate errors, combat is hard to test

---

## M5: Open-World Exploration

**Status**: Planned (10%)
**Goal**: Agent explores unknown terrain, gathers resources, and returns to base.
**Acceptance Criteria**:
- [ ] Explore-gather-return loop completes successfully
- [ ] Handles getting lost (pathfinding recovery, compass use)
- [ ] Handles full inventory (prioritization, caching, return trip)
- [ ] Generates reusable exploration strategies

**Dependencies**: M4 (autonomous survival)
**Risks**: Infinite exploration loops, pathfinding failures in complex terrain

---

## M6: Vision and Multimodal Enhancement

**Status**: Planned (5%)
**Goal**: Research and integrate visual input, screenshot understanding, or VLA approaches.
**Acceptance Criteria**:
- [ ] At least one vision-augmented task completed
- [ ] Decision report on whether to continue investing in VLA vs structured API
- [ ] Comparison of visual vs API-only performance on same tasks

**Dependencies**: M5 (reliable autonomous exploration)
**Risks**: High latency, high cost, low accuracy of visual approaches

---

## M7: Multi-Agent Collaboration

**Status**: Planned (5%)
**Goal**: Multiple bots cooperate on shared tasks with role assignment and communication.
**Acceptance Criteria**:
- [ ] Two agents complete a resource gathering or building task together
- [ ] Communication protocol documented
- [ ] Sync failures and conflict resolution logged
- [ ] Efficiency improvement over single-agent measured

**Dependencies**: M6 (mature single-agent system)
**Risks**: Communication overhead, coordination deadlocks, shared memory corruption
