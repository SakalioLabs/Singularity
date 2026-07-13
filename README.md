# Singularity - Minecraft LLM Agent

> An evolving modular agent system that drives a Minecraft Java Edition player through natural-language goals, progressing from basic connectivity to autonomous multi-agent collaboration.

[![M0: Research](https://img.shields.io/badge/M0-Source%20Verified-brightgreen)]()
[![M1: MVB](https://img.shields.io/badge/M1-Repeat%20Verified-brightgreen)]()
[![M2: LLM](https://img.shields.io/badge/M2-Repeat%20Verified-brightgreen)]()
[![M3: Memory](https://img.shields.io/badge/M3-Repeat%20Verified-brightgreen)]()
[![M4: Survival](https://img.shields.io/badge/M4-Live%20Failing-critical)]()
[![M5: Explore](https://img.shields.io/badge/M5-Live%20Failing-critical)]()
[![M6: Vision](https://img.shields.io/badge/M6-Live%20Failing-critical)]()
[![M7: Multi--Agent](https://img.shields.io/badge/M7-Not%20Run-yellow)]()
[![Minecraft](https://img.shields.io/badge/Minecraft-1.20.4-green)]()
[![Python](https://img.shields.io/badge/Python-3.12-blue)]()
[![Tests](https://img.shields.io/badge/Tests-core%20passing-brightgreen)]()

## Architecture

```
User Goal / Autonomous GoalGenerator
        |
        v
  +-----------+     +-------------+
  |  Planner  |<--->|   Memory    |  L0-L6 layered memory, context injection
  +-----------+     +-------------+
        |
        v
  +-----------+     +-------------+
  | TaskSystem|<--->| SkillLibrary|  17 builtin skills, versioning, success tracking
  +-----------+     +-------------+
        |
        v
  +---------------+     +-----------+
  | Action Ctrl   |     |  Explorer |  Landmarks, base return, spiral search
  +---------------+     +-----------+
        |
        v
  +------------------+
  | Minecraft Server |  Via Mineflayer / Pathfinder
  +------------------+
        |
        v
  +---------------+
  |  Observation  |  Position, health, inventory, entities, blocks, time
  +---------------+
        |
        v
  +-----------+     +---------------+
  | Reflector |---->| GoalGenerator |  6-level survival priority
  +-----------+     +---------------+
```

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Agent Core | Python 3.12 | Main observe-think-act loop with full module integration |
| Bot Interface | Mineflayer (Node.js) | Minecraft protocol interaction |
| Pathfinding | mineflayer-pathfinder | Navigation with obstacle avoidance |
| LLM Backend | OpenAI / Anthropic / DeepSeek / Ollama | Planning, reflection, skill generation |
| Memory | L0-L6 Multi-layer (Markdown + JSON) | Context, working, episodic, semantic, skill, decision, research |
| Task System | Python state machine | Hierarchical task management |
| Skill Library | Python dataclass + file storage | 17 builtin skills with versioning |
| Evaluation | Python benchmark suite | M1/M2 structured task evaluation |

## Quick Start

### Prerequisites
- Python 3.12+
- Node.js 18+
- JDK 17+ (for Minecraft server)

### Installation
```bash
git clone https://github.com/SakalioLabs/Singularity.git
cd Singularity
python -m pip install -e .
npm install
```

### Running M1

Provision Paper and manually accept the EULA as described in `docs/SERVER_SETUP.md`, then run exactly one task in a fresh episode:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/m1-runtime.ps1 -RunBenchmark -TaskId BM-001
```

The M1 protocol pins Paper 1.20.4 build 499 and its SHA-256. The script uses the deterministic RuleBasedPlanner profile, Bridge port `30000`, a fresh level, verified reset state, and timestamped evidence. BM-001..005 each require three distinct live successes; offline tests do not count.

Current status: M1, M2, and M3 are `repeat_verified`. M1 has BM-001..005 at 3/3 (`15/15` distinct eligible live successes). M2 has BM-006 and BM-007 at three eligible baseline/candidate pairs each, BM-008..010 at 3/3 independent successes each, and two eligible recovery sessions. M3 has three later-session skill retrieval/outcome cases plus approved held-out transfer evidence. M4 is `failing`: BM-011 has three independently eligible fresh survival-to-dawn episodes, BM-012 has five failed attempts and remains 0/3, and BM-013..014 remain unverified. Probe 5 live-validated strict-M4 log-family task reconciliation and advanced through crafting-table creation, then exposed inventory-as-placement-proof in Planner subtask criteria. The bounded Planner gate now maps only goal/subtask/action-aligned placement criteria to machine `nearby_block_present` evidence, preserves fail-closed controls, and authorizes exactly one fresh Probe 6 after the gate commit is pushed. The sole authoritative audit is `workspace/evals/capability_evidence_current.json`.

### Running M2

M2 uses `m2-fixed-v1`, the OpenAI-compatible `https://opencode.ai/zen/go/v1` endpoint, `deepseek-v4-flash`, a fresh Paper world per run, a real structured LLM Root Plan, machine-verifiable subtasks, independent terminal world evidence, and a hard total deadline with zero SDK retries plus one bounded transport-only retry. Configure either `SINGULARITY_LLM_API_KEY` or `OPENAI_API_KEY` outside the repository, then run one fixed experiment arm:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/m2-runtime.ps1 -TaskId BM-006 -Arm baseline -PairId bm006-pair-01 -ReplicateId 1
```

The BM-010 harness and deterministic construction template can be checked without an LLM call:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/m2-runtime.ps1 -TaskId BM-010 -HarnessSmoke
powershell -ExecutionPolicy Bypass -File scripts/m2-runtime.ps1 -TaskId BM-010 -TemplateSmoke
```

Harness/template smoke artifacts never count toward `live_observed` or `repeat_verified`. M2 now satisfies that contract: BM-006..010 are all `repeat_verified`, both composite-task pairing gates are 3/3, and the failure/replan recovery gate is approved.

### Development Commands

```bash
python -m singularity.main preflight --skip-network
python -m singularity.main capability-evidence-report --output workspace/evals/capability_evidence_current.json
python -m singularity.main capability-evidence-report --m3-evidence workspace/evals/skill_continual_learning_report.json --m3-evidence workspace/evals/skill_transfer/gather_wood/transfer_gate.json --m5-evidence logs/benchmarks/exploration_trace_current.json --m5-evidence logs/benchmarks/world_model_gate_current.json --m6-evidence logs/benchmarks/visual_trace_current.json --m6-evidence logs/benchmarks/visual_action_ablation_current.json --output workspace/evals/capability_evidence_current.json
python -m singularity.main task-continuity-report --goal "Build a safe shelter" --output logs/benchmarks/task_continuity.json
python -m singularity.main task-continuity-revision --failed-checkpoint CHECKPOINT_ID --reason "Review nearest verified boundary" --output workspace/reviews/task_revision.json
# Built-in lineage/restoration fixtures are smoke tests and cannot approve the default live-evidence gate.
python -m singularity.main task-continuity-lineage-ablation --include-builtins --capsule-char-budget 600 --output logs/benchmarks/task_continuity_lineage_ablation.json
python -m singularity.main task-continuity-restoration-report --include-builtins --output logs/benchmarks/task_continuity_restoration_report.json
python -m singularity.main task-continuity-restoration-gate --lineage-ablation logs/benchmarks/task_continuity_lineage_ablation.json --restoration-report logs/benchmarks/task_continuity_restoration_report.json --output logs/benchmarks/task_continuity_restoration_gate.json
# Synthetic router fixtures compare legacy goal/success ranking with task-frontier transition routing.
python -m singularity.main skill-frontier-routing-ablation --include-builtins --output logs/benchmarks/skill_frontier_routing.json
# Synthetic retirement fixtures exercise report schemas only and can never approve runtime quarantine.
python -m singularity.main skill-verifier-calibration-report --include-builtins --output logs/benchmarks/skill_verifier_calibration_builtin.json
python -m singularity.main skill-contribution-report --include-builtins --output logs/benchmarks/skill_contribution_builtin.json
# Offline plan-cache entries are hybrid-only; direct reuse requires three matched live sessions by default.
python -m singularity.main plan-cache-report --session-log logs/session_xxx.jsonl --output logs/benchmarks/plan_cache.json
python -m singularity.main plan-cache-gate --plan-cache-report logs/benchmarks/plan_cache.json --output logs/benchmarks/plan_cache_hybrid_gate.json
# Calibrate a behavior-only episode viability cascade on three disjoint live splits.
# Active termination remains unavailable unless the saved gate carries held-out global-recall certificates.
python -m singularity.main episode-early-abort-gate --calibration-log logs/calibration_1.jsonl --validation-log logs/validation_1.jsonl --test-log logs/test_1.jsonl --evidence-kind live_trace --planner-id rule-based-v1 --action-backend mineflayer-bridge-v1 --verifier-id goal-action-verifier-v1 --task-stream-id m1-fixed-v1 --seed WORLD_SEED --output logs/benchmarks/episode_early_abort_gate.json
python -m singularity.main run --goal "Gather 3 oak logs" --episode-abort-mode shadow --episode-abort-gate logs/benchmarks/episode_early_abort_gate.json --episode-abort-task-stream-id m1-fixed-v1 --episode-abort-seed-id WORLD_SEED
# Compare an eight-round task-frontier ledger. Built-ins are synthetic and shadow-only.
python -m singularity.main frontier-rollout-budget-report --include-builtins --evidence-kind synthetic_control --total-rounds 8 --planner-id builtin-fixed-planner-v1 --action-backend synthetic-no-execution --verifier-id builtin-milestone-verifier-v1 --task-stream-id builtin-frontier-budget --seed builtin-20260710 --output logs/benchmarks/frontier_budget_builtin.json
# Collect fixed-control runtime traces; shadow mode never changes planner context.
python -m singularity.main autonomous --max-goals 10 --frontier-budget-mode shadow --frontier-budget-policy uniform --frontier-budget-rounds 8 --frontier-budget-task-stream-id m1-fixed-v1 --frontier-budget-seed-id WORLD_SEED
python -m singularity.main autonomous --max-goals 10 --frontier-budget-mode shadow --frontier-budget-policy information --frontier-budget-rounds 8 --frontier-budget-task-stream-id m1-fixed-v1 --frontier-budget-seed-id WORLD_SEED
# Advisory mode additionally requires exact-control paired live logs. Repeat baseline/candidate flags in order;
# defaults require at least 12 successful candidate interval observations for the coverage certificate.
python -m singularity.main frontier-rollout-budget-report --help
# Normalize Observation-Plan-Action-Feedback cycles and localize the first unrecovered failure.
# Built-ins are synthetic controls; typed repair candidates remain review-only in every report.
python -m singularity.main critical-transition-report --include-builtins --evidence-kind synthetic_control --output logs/benchmarks/critical_transition_builtin.json
python -m singularity.main critical-transition-report --session-log logs/session_xxx.jsonl --label-file workspace/reviews/critical_transition_labels.jsonl --evidence-kind live_trace --output logs/benchmarks/critical_transition_live.json
# M1 acceptance runs must use exactly one task and one fresh episode.
powershell -ExecutionPolicy Bypass -File scripts/m1-runtime.ps1 -RunBenchmark -TaskId BM-001
python -m singularity.main visual-trace-report --session-log logs/session_xxx.jsonl --output logs/benchmarks/visual_trace_report.json
python -m singularity.main review-label-template --session-log logs/session_xxx.jsonl --mode both --output workspace/reviews/session_xxx_labels.jsonl
python -m singularity.main promotion-review-ablation --session-log logs/session_xxx.jsonl --promotion-critic --llm-provider openai --llm-model MODEL_NAME --llm-base-url PROVIDER_URL
python -m singularity.main goal-verification-ablation --session-log logs/session_xxx.jsonl --goal-critic --llm-provider openai --llm-model MODEL_NAME --llm-base-url PROVIDER_URL

# Multi-bot collaboration uses one bridge port per role
node src/bot/bot_server.js --username Singularity_resource_runner --bridge-port 3000
node src/bot/bot_server.js --username Singularity_leader_builder --bridge-port 3001
node src/bot/bot_server.js --username Singularity_single_agent --bridge-port 3002
python -m singularity.main collab-benchmark --preflight --executor agent --role-bridge-port resource_runner=3000 --role-bridge-port leader_builder=3001 --role-bridge-port single_agent=3002 --single-agent-baseline
python -m singularity.main collab-benchmark --execute --executor agent --role-bridge-port resource_runner=3000 --role-bridge-port leader_builder=3001 --role-bridge-port single_agent=3002 --single-agent-baseline --output logs/benchmarks/bm701_collab_report.json

# List available skills
python -m singularity.main skills

# Review extracted skill candidates
python -m singularity.main skill-candidates

# With LLM
python -m singularity.main run --goal "Craft a wooden pickaxe" \
  --llm-provider openai --llm-model gpt-4o-mini
```

## Modes of Operation

### Goal-Directed Mode
Pursues a specific natural-language goal through observe-think-act cycles. Uses LLM planner when API key is available, falls back to rule-based planner.

```bash
python -m singularity.main run --goal "Gather oak wood and craft a crafting table"
```

### Autonomous Survival Mode (M4 + M5)
Self-directs survival: generates goals by priority, explores, and returns to base when needed.

```bash
python -m singularity.main autonomous --max-goals 20 --max-cycles 100
```

Priority levels:
1. Critical threat response (hostiles nearby)
2. Critical health (eat or find food)
3. Night preparation (shelter before dusk)
4. Night survival (smelt, craft, organize)
5. Tool progression (wooden -> stone -> iron)
6. Resource gathering (logs, crafting table)

## Test Suite

```bash
# Core script tests (no MC server needed)
python tests/test_comprehensive.py
python tests/test_m2_comprehensive.py
python tests/test_action_controller.py
python tests/test_runtime_supervisor.py
python tests/test_episode_abort.py
python tests/test_frontier_budget.py
python tests/test_critical_transition.py
python tests/test_bot_bridge.py
python tests/test_collaboration_benchmark.py
python tests/test_collaboration_executor.py
python tests/test_memory_task_system.py
python tests/test_benchmark_preflight.py
node tests/test_bot_server_navigation.js
```

Coverage includes config, goal generation, exploration, interruptible runtime supervision, recall-controlled episode viability, fixed-budget frontier allocation, dependency-aware failure localization, truthful navigation completion, action safety helpers, memory and experience records, skill extraction/review, task scheduling, rule planning, knowledge loading, session logging, benchmark preflight, bridge health, collaboration benchmark feasibility/execution, Agent-backed collaboration task adapters, and benchmark trace ingestion.

## Project Structure

```
Singularity/
├── README.md
├── requirements.txt              # openai, anthropic, pydantic
├── package.json                  # mineflayer, pathfinder, minecraft-data
├── setup.ps1                     # Automated environment setup
├── src/
│   ├── singularity/
│   │   ├── core/
│   │   │   ├── agent.py          # Main agent: goal-directed + autonomous modes
│   │   │   ├── config.py         # BotConfig, LLMConfig, Config
│   │   │   ├── episode_abort.py  # Recall-controlled behavioral viability cascade
│   │   │   ├── frontier_budget.py # Fixed planner-round frontier allocation and gate
│   │   │   ├── planner.py        # LLM planner with knowledge injection
│   │   │   ├── reflector.py      # Failure analysis and re-planning
│   │   │   ├── rule_planner.py   # Rule-based fallback planner
│   │   │   ├── task_system.py    # Hierarchical task state machine
│   │   │   ├── memory.py         # L0-L6 multi-layer memory
│   │   │   ├── skill_library.py  # 17 builtin skills with versioning
│   │   │   ├── skill_extractor.py # Extract skills from session traces
│   │   │   ├── goal_generator.py # M4 survival goal prioritization
│   │   │   └── explorer.py       # M5 exploration with landmarks
│   │   ├── llm/provider.py       # Swappable LLM (OpenAI/Anthropic/Ollama)
│   │   ├── evaluation/critical_transition.py # Auditable execution dependency diagnosis
│   │   ├── observation/observer.py # Game state collection
│   │   ├── action/controller.py  # Action execution with safety
│   │   ├── bot/bridge.py         # Python-Node.js TCP bridge
│   │   ├── data/
│   │   │   ├── knowledge_base.py # Crafting recipes, recipe chains
│   │   │   └── crafting_recipes.json
│   │   ├── logging/session_logger.py # JSONL structured logging
│   │   ├── evaluation/benchmark_runner.py # M1/M2 benchmark suites
│   │   └── main.py               # CLI entry point
│   └── bot/bot_server.js         # Node.js Mineflayer server
├── tests/
│   ├── test_comprehensive.py     # 89 unit tests (all modules)
│   ├── test_goal_generator.py    # 6 goal generator tests
│   └── test_m2_integration.py    # M2 planner integration test
├── workspace/                    # Research knowledge base (70+ docs)
│   ├── STATUS.md                 # Current phase status
│   ├── PROGRESS.md               # Detailed progress tracking
│   ├── ROADMAP.md                # M0-M7 phase roadmap
│   ├── papers/                   # 75+ paper cards
│   ├── architecture/             # Module designs and deep analyses
│   ├── benchmarks/               # 5 benchmark suites
│   ├── implementation/           # 15+ technical notes
│   └── skills/                   # Skill documentation
└── docs/SERVER_SETUP.md          # MC server setup guide
```

## Research Foundation

- **94 papers** analyzed across Minecraft, game agents, memory, skills, world models, evaluation, safety, and multi-agent execution
- **4 key repos** evaluated: Mindcraft, Mineflayer, Baritone, MineDojo
- **10 research questions** identified and tracked (RQ1-RQ10)

## Design Constraints

1. **Safety First**: LLM never directly executes dangerous code. All actions go through safety layer.
2. **Model Agnostic**: Swappable LLM providers. No single-provider lock-in.
3. **Memory Integrity**: Memory resists pollution. Only verified information enters long-term memory.
4. **Measurable**: Every task has measurable success criteria.
5. **Evidence Based**: No capability claims without 3+ repeated experiment results.

## Contact

- **Repository**: [SakalioLabs/Singularity](https://github.com/SakalioLabs/Singularity)
- **Issues**: [GitHub Issues](https://github.com/SakalioLabs/Singularity/issues)
