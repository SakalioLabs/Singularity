# Module: Evaluator

> Status: Design (M0)
> Owner: Core Agent

## Purpose

Continuously assess agent performance through structured benchmarks, track metrics over time, and identify areas for improvement.

## Evaluation Dimensions

| Dimension | Metric | How |
|-----------|--------|-----|
| Task Success | Binary pass/fail per task | Check success_criteria |
| Completion Time | Seconds to task completion | Timestamp diff |
| Resource Efficiency | Items consumed vs produced | Inventory tracking |
| LLM Cost | Tokens used per task | API usage logs |
| Failure Rate | Failures per task type | Task log aggregation |
| Recovery Rate | % of failures that recover | Task state transitions |
| Death Rate | Deaths per session | Event log |
| Human Intervention | Manual overrides per session | Override log |
| Skill Reuse | % of tasks using existing skills | Skill execution logs |
| Memory Pollution | False facts detected in memory | Periodic memory audit |

## Benchmark Execution

```python
def run_benchmark(benchmark: Benchmark, seed: str, model: str):
    setup_world(seed, benchmark.version)
    agent = create_agent(model)
    start_time = time.now()
    result = agent.execute(benchmark.task_description, timeout=benchmark.max_time)
    return {
        "benchmark_id": benchmark.id,
        "seed": seed,
        "model": model,
        "success": check_criteria(result, benchmark.success_criteria),
        "duration": time.now() - start_time,
        "tokens_used": agent.token_usage,
        "deaths": agent.death_count,
        "human_overrides": agent.override_count,
        "log": agent.session_log
    }
```

## Reporting

After each benchmark run, generate:
1. Per-task result card
2. Aggregate statistics (success rate, avg time, avg cost)
3. Failure type distribution
4. Comparison with previous runs
5. Recommendations for next iteration

## Implemented Offline Reports

- `agent-module-comparison-report` compares baseline and candidate session JSONL logs as Orak-style module experiments.
- It summarizes completion rate, action failure rate, empty/blocked plans, and module activity for plan cache, visual action grounding, action verification, action candidate selection, skill memory, policy skills, memory policy, goal verification, and control-policy/backend decisions.
- The report marks a candidate `approved`, `review`, or `rejected` using configurable regression thresholds, then recommends the dedicated gate/report family to run next before packaging a runtime profile.

## Dependencies

- Task system (task state and results)
- Memory system (session logs)
- LLM provider (token usage tracking)
