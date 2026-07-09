# Singularity - Minecraft LLM Agent

> An evolving modular agent system that drives a Minecraft Java Edition player through natural-language goals, progressing from basic connectivity to autonomous multi-agent collaboration.

[![M0: Research](https://img.shields.io/badge/M0-Complete-brightgreen)]()
[![M1: MVB](https://img.shields.io/badge/M1-Live%20Failing-critical)]()
[![M2: LLM](https://img.shields.io/badge/M2-Evidence%20Pending-yellow)]()
[![M3: Memory](https://img.shields.io/badge/M3-Evidence%20Pending-yellow)]()
[![M4: Survival](https://img.shields.io/badge/M4-Evidence%20Pending-yellow)]()
[![M5: Explore](https://img.shields.io/badge/M5-Evidence%20Pending-yellow)]()
[![M6: Vision](https://img.shields.io/badge/M6-Evidence%20Pending-yellow)]()
[![M7: Multi--Agent](https://img.shields.io/badge/M7-Evidence%20Pending-yellow)]()
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

### Running the Agent

```bash
# 1. Start Minecraft server
cd mc-server
java -Xmx1G -Xms512M -jar server.jar nogui

# 2. Start bot bridge (in new terminal)
node src/bot/bot_server.js

# 3. Run agent (in new terminal)

# Goal-directed mode
python -m singularity.main run --goal "Gather 3 oak logs"

# Autonomous survival mode (M4 + M5)
python -m singularity.main autonomous --max-goals 10

# Run benchmarks
python -m singularity.main preflight --skip-network
python -m singularity.main preflight
python -m singularity.main capability-evidence-report --check-runtime --output workspace/evals/capability_evidence_current.json
python -m singularity.main benchmark --suite m1 --preflight
python -m singularity.main benchmark --suite m1 --ingest
python -m singularity.main benchmark --suite m1 --ingest --promotion-critic --llm-provider openai --llm-model MODEL_NAME --llm-base-url PROVIDER_URL
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
python tests/test_bot_bridge.py
python tests/test_collaboration_benchmark.py
python tests/test_collaboration_executor.py
python tests/test_memory_task_system.py
python tests/test_benchmark_preflight.py
```

Coverage includes config, goal generation, exploration, interruptible runtime supervision, action safety helpers, memory and experience records, skill extraction/review, task scheduling, rule planning, knowledge loading, session logging, benchmark preflight, bridge health, collaboration benchmark feasibility/execution, Agent-backed collaboration task adapters, and benchmark trace ingestion.

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

- **75+ papers** analyzed across Minecraft, game agents, memory, skills, world models, evaluation, safety, and multi-agent execution
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
