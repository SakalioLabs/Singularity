# Collaboration Benchmark Suite
> Last updated: 2026-07-08

## Purpose

M7 evaluates whether multiple Minecraft agents can coordinate under role heterogeneity, shared state, dynamic risk, and real-time deadlines.

## Schema

The canonical machine-readable format is JSON and is implemented in `singularity.evaluation.collaboration_benchmark`.

Required top-level fields:
- `id`, `name`, `phase`, `max_duration_s`
- `roles`: heterogeneous agents with capabilities and optional starting inventory
- `tasks`: assigned role, capabilities, dependencies, deadlines, estimates, success criteria
- `shared_state`: required keys, initial values, success keys
- `dynamic_events`: timed risks or environment changes
- `success_criteria`: global benchmark success gate

Static feasibility checks:
- at least two unique roles
- every task assigned to an existing role
- dependencies resolve
- assigned roles cover required task capabilities
- task deadlines and dynamic events fit within `max_duration_s`
- at least two required roles have assigned tasks
- shared-state success keys are initialized or updated by tasks

Static schedule analysis:
- estimates each task's start/finish time from dependencies, role resource locks, priority, deadline, and `estimated_duration_s`
- reports role busy/idle time, task deadline misses, benchmark deadline misses, and makespan
- can transform the same spec into a single-agent baseline, making the predicted collaboration speedup visible before live Mineflayer execution
- aligns completed execution traces back to the schedule, reporting actual start/finish/duration, elapsed delta, deadline deltas, missing scheduled tasks, and unexpected execution tasks
- computes actual overlap metrics from measured task intervals: peak parallel task count, overlap seconds, task-seconds, busy window, parallel efficiency, and overlapping task pairs

Execution dispatch:
- each dispatch wave selects at most one runnable task per role
- different roles run concurrently through the selected executor, allowing separate live bot bridges to progress in parallel
- shared-state writes and task status transitions are committed serially by the runner after each role task finishes, keeping the file-backed shared state deterministic
- the live `AgentCollaborationExecutor` protects its agent and connection caches with locks: different roles can run concurrently, while duplicate same-role calls reuse one agent and serialize that role's `run_goal()` calls
- `--executor agent` prints and saves bridge launch plans with exact role usernames, bridge ports, launch commands, and duplicate-port conflicts before preflight or execution
- Agent bridge preflight fails fast when multiple roles share one bridge port; pass `--bridge-port-base` or unique `--role-bridge-port ROLE=PORT` values for live collaboration

## Included Benchmarks

### BM-701: Time-sensitive shared shelter

File: `m7_time_sensitive_shelter.json`

Two agents must finish a lit shelter before hostile nightfall:
- `resource_runner` gathers logs, delivers wood, and prepares lighting.
- `leader_builder` builds and verifies the shelter.
- Shared keys: `wood_delivered`, `shelter_frame_done`, `torch_ready`.
- Dynamic event: `hostile_nightfall` at 360 seconds.
- Deadline: 420 seconds.

## Runner Plan

1. Load JSON spec with `CollaborationBenchmarkSpec.load_json()`.
2. Run `CollaborationFeasibilityChecker().check(spec)` before live execution.
3. Run `CollaborationBenchmarkRunner.analyze_schedule(spec)` to compute theoretical parallel makespan and deadline risk.
4. Use `spec.assignment_plan()` to assign tasks through `LeaderAgent.assign_task()`.
5. Execute assigned tasks through `CollaborationBenchmarkRunner.execute_prepared()` with role-parallel dispatch and a pluggable task executor.
6. During live runs, log per-agent latency, task duration, handoff failures, and deadline misses.
7. Compare live execution against the static schedule to measure bridge/runtime overhead, missing task execution, and actual task overlap.
8. Compare against a single-agent baseline for completion time and failure mode distribution.

Dry-run command:

```powershell
python -m singularity.main collab-benchmark --spec workspace/benchmarks/m7_time_sensitive_shelter.json
```

State-transition execution command:

```powershell
python -m singularity.main collab-benchmark --spec workspace/benchmarks/m7_time_sensitive_shelter.json --execute
```

Live Agent executor command:

```powershell
python -m singularity.main collab-benchmark --spec workspace/benchmarks/m7_time_sensitive_shelter.json --execute --executor agent
```

Multi-bot live command:

```powershell
node src/bot/bot_server.js --username Singularity_resource_runner --bridge-port 3000
node src/bot/bot_server.js --username Singularity_leader_builder --bridge-port 3001
node src/bot/bot_server.js --username Singularity_single_agent --bridge-port 3002
python -m singularity.main collab-benchmark --spec workspace/benchmarks/m7_time_sensitive_shelter.json --preflight --executor agent --role-bridge-port resource_runner=3000 --role-bridge-port leader_builder=3001 --role-bridge-port single_agent=3002 --single-agent-baseline
python -m singularity.main collab-benchmark --spec workspace/benchmarks/m7_time_sensitive_shelter.json --execute --executor agent --role-bridge-port resource_runner=3000 --role-bridge-port leader_builder=3001 --role-bridge-port single_agent=3002 --single-agent-baseline --output logs/benchmarks/bm701_collab_report.json
```

The saved JSON report includes static schedule analysis, Agent bridge launch plans, dispatch mode/batches/max parallel task counts, schedule-vs-execution comparison with actual overlap metrics, optional single-agent schedule comparison, collaboration execution, optional single-agent baseline execution, and compact comparisons over predicted makespan, measured elapsed time, success, completed tasks, failures, skipped tasks, and deadline misses.
