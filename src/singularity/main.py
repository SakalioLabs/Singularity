"""Singularity - Minecraft LLM Agent entry point."""
import sys
import json
import logging
import argparse
import os

from singularity.core.config import Config, BotConfig, LLMConfig


def _llm_config_from_args(args) -> LLMConfig:
    return LLMConfig(
        provider=getattr(args, "llm_provider", "openai") or "openai",
        model=getattr(args, "llm_model", "gpt-4o-mini") or "gpt-4o-mini",
        api_key=(
            getattr(args, "api_key", "")
            or os.environ.get("SINGULARITY_LLM_API_KEY", "")
            or os.environ.get("OPENAI_API_KEY", "")
        ),
        base_url=getattr(args, "llm_base_url", "") or os.environ.get("SINGULARITY_LLM_BASE_URL", ""),
    )


def _promotion_critic_from_args(args):
    if not getattr(args, "promotion_critic", False):
        return None
    from singularity.core.skill_extractor import SkillPromotionCritic
    from singularity.llm.provider import LLMProvider

    return SkillPromotionCritic(LLMProvider(_llm_config_from_args(args)))


def _goal_critic_from_args(args):
    if not getattr(args, "goal_critic", False):
        return None
    from singularity.core.goal_verifier import GoalVerificationCritic
    from singularity.llm.provider import LLMProvider

    return GoalVerificationCritic(LLMProvider(_llm_config_from_args(args)))


def _add_coaching_args(parser):
    parser.add_argument(
        "--coach-style",
        type=str,
        default="",
        help="Advisory runtime coaching style for planner/curriculum bias: safe, explorer, efficient, resourceful, builder",
    )
    parser.add_argument(
        "--no-coaching-policy",
        action="store_true",
        help="Disable advisory runtime coaching even when --coach-style is supplied",
    )


def _merge_skill_memory_quality_feedback_paths(paths: list[str]) -> dict:
    feedback = {
        "quality_label_counts": {},
        "hint_type_counts": {},
        "task_family_counts": {},
        "hint_quality_items": [],
        "policy_hints": [],
    }
    for path in paths or []:
        with open(path, "r", encoding="utf-8-sig") as f:
            payload = json.load(f)
        current = payload.get("skill_memory_quality_feedback", payload) if isinstance(payload, dict) else {}
        if not isinstance(current, dict):
            continue
        for key in ("quality_label_counts", "hint_type_counts", "task_family_counts"):
            for name, count in (current.get(key, {}) or {}).items():
                try:
                    amount = int(float(count or 0))
                except (TypeError, ValueError):
                    amount = 0
                feedback[key][str(name)] = feedback[key].get(str(name), 0) + amount
        for key in ("hint_quality_items", "policy_hints"):
            values = current.get(key, [])
            if isinstance(values, list):
                feedback[key].extend(item for item in values if isinstance(item, dict))
    return feedback


def _load_skill_memory_quality_ablation_cases(args) -> list[dict]:
    case_file = getattr(args, "case_file", "") or ""
    if case_file:
        with open(case_file, "r", encoding="utf-8-sig") as f:
            if case_file.lower().endswith(".jsonl"):
                return [json.loads(line) for line in f if line.strip()]
            payload = json.load(f)
        if isinstance(payload, dict) and isinstance(payload.get("cases"), list):
            return payload["cases"]
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            return [payload]
    goals = getattr(args, "goal", []) or []
    task_family = getattr(args, "task_family", "") or ""
    return [
        {"id": f"goal_{index}", "goal": goal, "task_family": task_family}
        for index, goal in enumerate(goals, start=1)
    ]


def main():
    parser = argparse.ArgumentParser(description="Singularity Minecraft LLM Agent")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Run goal command
    run_parser = subparsers.add_parser("run", help="Run a single goal")
    run_parser.add_argument("--goal", type=str, default="Gather 3 oak logs", help="Goal in natural language")
    run_parser.add_argument("--host", type=str, default="localhost")
    run_parser.add_argument("--port", type=int, default=25565)
    run_parser.add_argument("--username", type=str, default="Singularity")
    run_parser.add_argument("--bridge-host", type=str, default="127.0.0.1")
    run_parser.add_argument("--bridge-port", type=int, default=3000)
    run_parser.add_argument("--llm-provider", type=str, default="openai")
    run_parser.add_argument("--llm-model", type=str, default="gpt-4o-mini")
    run_parser.add_argument("--llm-base-url", type=str, default="")
    run_parser.add_argument("--api-key", type=str, default="")
    run_parser.add_argument("--goal-critic", action="store_true", help="Use configured LLM as fallback critic for unknown goal verification")
    run_parser.add_argument("--no-skill-memory-context", action="store_true", help="Disable skill-level memory hints in planner context")
    run_parser.add_argument("--no-vision-analysis", action="store_true", help="Disable structured vision grounding on observations")
    run_parser.add_argument("--no-visual-action-grounding", action="store_true", help="Disable visual suggestions from modifying planned actions")
    run_parser.add_argument("--capture-screenshots", action="store_true", help="Ask the bridge renderer to capture screenshots for visual analysis")
    run_parser.add_argument("--screenshot-dir", type=str, default="logs/screenshots", help="Directory for captured screenshot files")
    run_parser.add_argument("--screenshot-min-interval", type=float, default=2.0, help="Minimum seconds between screenshot capture attempts")
    run_parser.add_argument("--mixed-policy-patch", action="append", default=[], help="Approved mixed-initiative policy patch JSON to load at runtime")
    run_parser.add_argument("--mixed-policy-gate", action="append", default=[], help="Approved mixed-policy gate JSON required before loading runtime policy patches")
    run_parser.add_argument("--self-evolution-feedback", action="append", default=[], help="self-evolution-report JSON to load as advisory planner feedback")
    run_parser.add_argument("--world-model-feedback", action="append", default=[], help="world-model-report JSON to load into autonomous curriculum after approved gate")
    run_parser.add_argument("--world-model-gate", action="append", default=[], help="Approved world-model-feedback-gate JSON required before loading world-model feedback")
    run_parser.add_argument("--action-value-feedback", action="append", default=[], help="action-value-report JSON to load for advisory action candidate scoring")
    run_parser.add_argument("--action-value-transition-gate", action="append", default=[], help="Approved action-value-transition-gate JSON required before loading ASV transition scores")
    run_parser.add_argument("--action-value-transition-evaluator-report", action="append", default=[], help="Approved action-value-transition-evaluator-report JSON required before loading ASV transition scores")
    run_parser.add_argument("--skill-memory-quality-feedback", action="append", default=[], help="skill-memory-quality-report JSON to load for advisory skill-memory retrieval ranking")
    run_parser.add_argument("--skill-memory-quality-gate", action="append", default=[], help="Approved skill-memory-quality-gate JSON required before loading quality feedback")
    _add_coaching_args(run_parser)
    run_parser.add_argument("--log-level", type=str, default="INFO")

    # Autonomous mode (M4 + M5)
    auto_parser = subparsers.add_parser("autonomous", help="Run autonomous survival (M4 + M5)")
    auto_parser.add_argument("--max-goals", type=int, default=10, help="Maximum goals to pursue")
    auto_parser.add_argument("--max-cycles", type=int, default=80, help="Max cycles per goal")
    auto_parser.add_argument("--host", type=str, default="localhost")
    auto_parser.add_argument("--port", type=int, default=25565)
    auto_parser.add_argument("--username", type=str, default="Singularity")
    auto_parser.add_argument("--bridge-host", type=str, default="127.0.0.1")
    auto_parser.add_argument("--bridge-port", type=int, default=3000)
    auto_parser.add_argument("--llm-provider", type=str, default="openai")
    auto_parser.add_argument("--llm-model", type=str, default="gpt-4o-mini")
    auto_parser.add_argument("--llm-base-url", type=str, default="")
    auto_parser.add_argument("--api-key", type=str, default="")
    auto_parser.add_argument("--goal-critic", action="store_true", help="Use configured LLM as fallback critic for unknown goal verification")
    auto_parser.add_argument("--no-skill-memory-context", action="store_true", help="Disable skill-level memory hints in planner context")
    auto_parser.add_argument("--no-vision-analysis", action="store_true", help="Disable structured vision grounding on observations")
    auto_parser.add_argument("--no-visual-action-grounding", action="store_true", help="Disable visual suggestions from modifying planned actions")
    auto_parser.add_argument("--capture-screenshots", action="store_true", help="Ask the bridge renderer to capture screenshots for visual analysis")
    auto_parser.add_argument("--screenshot-dir", type=str, default="logs/screenshots", help="Directory for captured screenshot files")
    auto_parser.add_argument("--screenshot-min-interval", type=float, default=2.0, help="Minimum seconds between screenshot capture attempts")
    auto_parser.add_argument("--mixed-policy-patch", action="append", default=[], help="Approved mixed-initiative policy patch JSON to load at runtime")
    auto_parser.add_argument("--mixed-policy-gate", action="append", default=[], help="Approved mixed-policy gate JSON required before loading runtime policy patches")
    auto_parser.add_argument("--self-evolution-feedback", action="append", default=[], help="self-evolution-report JSON to load as advisory planner feedback")
    auto_parser.add_argument("--world-model-feedback", action="append", default=[], help="world-model-report JSON to load into autonomous curriculum after approved gate")
    auto_parser.add_argument("--world-model-gate", action="append", default=[], help="Approved world-model-feedback-gate JSON required before loading world-model feedback")
    auto_parser.add_argument("--action-value-feedback", action="append", default=[], help="action-value-report JSON to load for advisory action candidate scoring")
    auto_parser.add_argument("--action-value-transition-gate", action="append", default=[], help="Approved action-value-transition-gate JSON required before loading ASV transition scores")
    auto_parser.add_argument("--action-value-transition-evaluator-report", action="append", default=[], help="Approved action-value-transition-evaluator-report JSON required before loading ASV transition scores")
    auto_parser.add_argument("--skill-memory-quality-feedback", action="append", default=[], help="skill-memory-quality-report JSON to load for advisory skill-memory retrieval ranking")
    auto_parser.add_argument("--skill-memory-quality-gate", action="append", default=[], help="Approved skill-memory-quality-gate JSON required before loading quality feedback")
    _add_coaching_args(auto_parser)
    auto_parser.add_argument("--log-level", type=str, default="INFO")

    # Benchmark command
    bench_parser = subparsers.add_parser("benchmark", help="Run benchmarks")
    bench_parser.add_argument("--suite", type=str, default="m1", choices=["m1", "m2", "all"])
    bench_parser.add_argument("--host", type=str, default="localhost")
    bench_parser.add_argument("--port", type=int, default=25565)
    bench_parser.add_argument("--username", type=str, default="Singularity")
    bench_parser.add_argument("--bridge-host", type=str, default="127.0.0.1")
    bench_parser.add_argument("--bridge-port", type=int, default=3000)
    bench_parser.add_argument("--llm-provider", type=str, default="openai")
    bench_parser.add_argument("--llm-model", type=str, default="gpt-4o-mini")
    bench_parser.add_argument("--llm-base-url", type=str, default="")
    bench_parser.add_argument("--api-key", type=str, default="")
    bench_parser.add_argument("--goal-critic", action="store_true", help="Use configured LLM as fallback critic for unknown goal verification")
    bench_parser.add_argument("--no-skill-memory-context", action="store_true", help="Disable skill-level memory hints in planner context")
    bench_parser.add_argument("--no-vision-analysis", action="store_true", help="Disable structured vision grounding on observations")
    bench_parser.add_argument("--no-visual-action-grounding", action="store_true", help="Disable visual suggestions from modifying planned actions")
    bench_parser.add_argument("--capture-screenshots", action="store_true", help="Ask the bridge renderer to capture screenshots for visual analysis")
    bench_parser.add_argument("--screenshot-dir", type=str, default="logs/screenshots", help="Directory for captured screenshot files")
    bench_parser.add_argument("--screenshot-min-interval", type=float, default=2.0, help="Minimum seconds between screenshot capture attempts")
    bench_parser.add_argument("--mixed-policy-patch", action="append", default=[], help="Approved mixed-initiative policy patch JSON to load in benchmark agents")
    bench_parser.add_argument("--mixed-policy-gate", action="append", default=[], help="Approved mixed-policy gate JSON required before loading benchmark policy patches")
    bench_parser.add_argument("--self-evolution-feedback", action="append", default=[], help="self-evolution-report JSON to load as advisory planner feedback")
    bench_parser.add_argument("--world-model-feedback", action="append", default=[], help="world-model-report JSON to load into autonomous curriculum after approved gate")
    bench_parser.add_argument("--world-model-gate", action="append", default=[], help="Approved world-model-feedback-gate JSON required before loading world-model feedback")
    bench_parser.add_argument("--action-value-feedback", action="append", default=[], help="action-value-report JSON to load for advisory action candidate scoring")
    bench_parser.add_argument("--action-value-transition-gate", action="append", default=[], help="Approved action-value-transition-gate JSON required before loading ASV transition scores")
    bench_parser.add_argument("--action-value-transition-evaluator-report", action="append", default=[], help="Approved action-value-transition-evaluator-report JSON required before loading ASV transition scores")
    bench_parser.add_argument("--action-value-transition-preflight", action="store_true", help="Run saved action-value transition gate/evaluator preflight before transition-scored benchmarks")
    bench_parser.add_argument("--action-value-transition-preflight-output", type=str, default="", help="Optional JSON path for the action-value transition benchmark preflight report")
    bench_parser.add_argument("--require-action-value-transition-evaluator-report", action="store_true", help="Require approved state-grounded evaluator reports in action-value transition preflight")
    bench_parser.add_argument("--skill-memory-quality-feedback", action="append", default=[], help="skill-memory-quality-report JSON to load for advisory skill-memory retrieval ranking")
    bench_parser.add_argument("--skill-memory-quality-gate", action="append", default=[], help="Approved skill-memory-quality-gate JSON required before loading quality feedback")
    bench_parser.add_argument("--skill-memory-quality-preflight", action="store_true", help="Run gate and offline ranking preflight before quality-feedback-assisted benchmarks")
    bench_parser.add_argument("--skill-memory-quality-preflight-output", type=str, default="", help="Optional JSON path for the skill-memory quality benchmark preflight report")
    _add_coaching_args(bench_parser)
    bench_parser.add_argument("--log-level", type=str, default="INFO")
    bench_parser.add_argument("--output", type=str, default="benchmark_results.json")
    bench_parser.add_argument("--preflight", action="store_true", help="Run readiness checks before benchmarks")
    bench_parser.add_argument("--ingest", action="store_true", help="Ingest passing benchmark traces into memory and skill candidate queue")
    bench_parser.add_argument("--promotion-critic", action="store_true", help="Use configured LLM as fallback critic for unknown skill-candidate verifier gates during ingestion")
    bench_parser.add_argument("--policy-skill-ablation", action="store_true", help="Run suite twice with reviewed policy skills disabled and enabled")
    bench_parser.add_argument("--skill-memory-ablation", action="store_true", help="Run suite twice with policy skills enabled but skill-memory context disabled vs enabled")
    bench_parser.add_argument("--visual-action-ablation", action="store_true", help="Run suite twice with visual action grounding disabled and enabled")
    bench_parser.add_argument("--mixed-policy-ablation", action="store_true", help="Run suite twice without and with approved mixed-policy patches")

    # Benchmark preflight command
    preflight_parser = subparsers.add_parser("preflight", help="Check benchmark readiness without running tasks")
    preflight_parser.add_argument("--host", type=str, default="localhost")
    preflight_parser.add_argument("--port", type=int, default=25565)
    preflight_parser.add_argument("--username", type=str, default="Singularity")
    preflight_parser.add_argument("--bridge-host", type=str, default="127.0.0.1")
    preflight_parser.add_argument("--bridge-port", type=int, default=3000)
    preflight_parser.add_argument("--skip-network", action="store_true", help="Skip bot bridge and MC server TCP checks")
    preflight_parser.add_argument("--screenshot-renderer", action="store_true", help="Check optional prismarine-viewer screenshot renderer dependencies")
    preflight_parser.add_argument("--log-level", type=str, default="INFO")

    # Screenshot bridge runtime smoke test
    screenshot_smoke_parser = subparsers.add_parser("screenshot-smoke-test", help="Capture one screenshot through the live bridge and verify the local image file")
    screenshot_smoke_parser.add_argument("--host", type=str, default="localhost")
    screenshot_smoke_parser.add_argument("--port", type=int, default=25565)
    screenshot_smoke_parser.add_argument("--username", type=str, default="Singularity")
    screenshot_smoke_parser.add_argument("--bridge-host", type=str, default="127.0.0.1")
    screenshot_smoke_parser.add_argument("--bridge-port", type=int, default=3000)
    screenshot_smoke_parser.add_argument("--screenshot-dir", type=str, default="logs/screenshots", help="Directory for default smoke-test screenshot")
    screenshot_smoke_parser.add_argument("--screenshot-path", type=str, default="", help="Exact screenshot path to request from the bridge")
    screenshot_smoke_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    screenshot_smoke_parser.add_argument("--log-level", type=str, default="INFO")

    # Skills info command
    skills_parser = subparsers.add_parser("skills", help="List available skills")

    # Skill graph governance report
    skill_graph_parser = subparsers.add_parser("skill-graph-report", help="Report skill dependencies, provenance, and promotion gates")
    skill_graph_parser.add_argument("--skill-storage-path", type=str, default="workspace/skills", help="Skill storage path containing custom_skills.jsonl")
    skill_graph_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    skill_graph_parser.add_argument("--log-level", type=str, default="INFO")

    # Skill contract retrieval report
    skill_contract_parser = subparsers.add_parser("skill-contract-report", help="Report skill contract readiness for a goal and world state")
    skill_contract_parser.add_argument("--skill-storage-path", type=str, default="workspace/skills", help="Skill storage path containing custom_skills.jsonl")
    skill_contract_parser.add_argument("--goal", type=str, required=True, help="Goal or task query to score against skill contracts")
    skill_contract_parser.add_argument("--world-state-json", type=str, default="", help="Optional world state JSON object")
    skill_contract_parser.add_argument("--world-state-file", type=str, default="", help="Optional world state JSON file")
    skill_contract_parser.add_argument("--limit", type=int, default=20)
    skill_contract_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    skill_contract_parser.add_argument("--log-level", type=str, default="INFO")

    # Skill-local memory report
    skill_memory_parser = subparsers.add_parser("skill-memory-report", help="Report per-skill replay, failure, and transfer memories")
    skill_memory_parser.add_argument("--skill-storage-path", type=str, default="workspace/skills", help="Skill storage path containing custom_skills.jsonl")
    skill_memory_parser.add_argument("--goal", type=str, default="", help="Optional goal query to score skill contracts alongside memory")
    skill_memory_parser.add_argument("--task-family", type=str, default="", help="Optional task-family zone such as crafting, mining, shelter, or navigation")
    skill_memory_parser.add_argument("--include-builtins", action="store_true", help="Include built-in skills even when they have no skill memory")
    skill_memory_parser.add_argument("--limit", type=int, default=20)
    skill_memory_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    skill_memory_parser.add_argument("--log-level", type=str, default="INFO")

    # MUSE-style skill lifecycle report
    skill_lifecycle_parser = subparsers.add_parser(
        "skill-lifecycle-report",
        help="Audit skill creation, memory, management, evaluation, and refinement readiness",
    )
    skill_lifecycle_parser.add_argument("--skill-storage-path", type=str, default="workspace/skills", help="Skill storage path containing custom_skills.jsonl")
    skill_lifecycle_parser.add_argument("--goal", type=str, default="", help="Optional goal query to score skill contracts alongside lifecycle readiness")
    skill_lifecycle_parser.add_argument("--task-family", type=str, default="", help="Optional task-family zone such as crafting, mining, shelter, or navigation")
    skill_lifecycle_parser.add_argument("--include-builtins", action="store_true", help="Include built-in skills in the lifecycle audit")
    skill_lifecycle_parser.add_argument("--limit", type=int, default=20)
    skill_lifecycle_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    skill_lifecycle_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline skill-memory quality report
    skill_memory_quality_parser = subparsers.add_parser(
        "skill-memory-quality-report",
        help="Audit typed skill-memory hints against later session outcomes",
    )
    skill_memory_quality_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    skill_memory_quality_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    skill_memory_quality_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline skill-memory quality ranking ablation
    skill_memory_quality_ablation_parser = subparsers.add_parser(
        "skill-memory-quality-ablation",
        help="Compare skill-memory hint ranking before and after quality feedback",
    )
    skill_memory_quality_ablation_parser.add_argument("--skill-storage-path", type=str, default="workspace/skills", help="Skill storage path containing custom_skills.jsonl")
    skill_memory_quality_ablation_parser.add_argument("--quality-feedback", action="append", default=[], help="skill-memory-quality-report JSON to apply for the adjusted ranking")
    skill_memory_quality_ablation_parser.add_argument("--goal", action="append", default=[], help="Goal/query to compare; repeat for multiple cases")
    skill_memory_quality_ablation_parser.add_argument("--task-family", type=str, default="", help="Optional task-family zone for all --goal cases")
    skill_memory_quality_ablation_parser.add_argument("--case-file", type=str, default="", help="Optional JSON/JSONL case file with goal and task_family fields")
    skill_memory_quality_ablation_parser.add_argument("--limit", type=int, default=5)
    skill_memory_quality_ablation_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    skill_memory_quality_ablation_parser.add_argument("--log-level", type=str, default="INFO")

    skill_memory_quality_gate_parser = subparsers.add_parser(
        "skill-memory-quality-gate",
        help="Gate REUSE skill-memory promotion with localized quality evidence",
    )
    skill_memory_quality_gate_parser.add_argument("--skill-memory-report", action="append", default=[], help="Saved skill-memory-report JSON")
    skill_memory_quality_gate_parser.add_argument("--quality-feedback", action="append", default=[], help="Saved skill-memory-quality-report JSON or feedback JSON")
    skill_memory_quality_gate_parser.add_argument("--target", type=str, default="skill_memory_reuse_promotion", help="Promotion target label for the gate report")
    skill_memory_quality_gate_parser.add_argument("--min-supported-reuse", type=int, default=2, help="Minimum localized supported REUSE count required")
    skill_memory_quality_gate_parser.add_argument("--max-conflicting-reuse", type=int, default=0, help="Maximum localized conflicting REUSE count allowed")
    skill_memory_quality_gate_parser.add_argument("--output", type=str, default="", help="Optional JSON gate report path")
    skill_memory_quality_gate_parser.add_argument("--log-level", type=str, default="INFO")

    # Memory consolidation report
    memory_report_parser = subparsers.add_parser("memory-consolidation-report", help="Report repeatedly recalled memories worth consolidation")
    memory_report_parser.add_argument("--memory-dir", type=str, default="workspace/memory")
    memory_report_parser.add_argument("--min-score", type=float, default=0.65)
    memory_report_parser.add_argument("--min-recall-count", type=int, default=2)
    memory_report_parser.add_argument("--min-unique-queries", type=int, default=2)
    memory_report_parser.add_argument("--limit", type=int, default=20)
    memory_report_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    memory_report_parser.add_argument("--log-level", type=str, default="INFO")

    # Echo-style transfer memory report
    transfer_memory_parser = subparsers.add_parser("transfer-memory-report", help="Report transfer-axis experience matches for a query")
    transfer_memory_parser.add_argument("--memory-dir", type=str, default="workspace/memory")
    transfer_memory_parser.add_argument("--query", type=str, required=True, help="Goal or task query to retrieve transferable experiences for")
    transfer_memory_parser.add_argument("--current-state-json", type=str, default="", help="Optional current state JSON object")
    transfer_memory_parser.add_argument("--current-state-file", type=str, default="", help="Optional current state JSON file")
    transfer_memory_parser.add_argument("--min-score", type=float, default=0.1)
    transfer_memory_parser.add_argument("--limit", type=int, default=10)
    transfer_memory_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    transfer_memory_parser.add_argument("--log-level", type=str, default="INFO")

    task_memory_parser = subparsers.add_parser("task-memory-report", help="Report task-centric memory context for a goal and task")
    task_memory_parser.add_argument("--memory-dir", type=str, default="workspace/memory")
    task_memory_parser.add_argument("--goal", type=str, required=True, help="Goal query to scope task memory")
    task_memory_parser.add_argument("--task-json", type=str, default="", help="Optional task JSON object")
    task_memory_parser.add_argument("--task-file", type=str, default="", help="Optional task JSON file")
    task_memory_parser.add_argument("--current-state-json", type=str, default="", help="Optional current state JSON object")
    task_memory_parser.add_argument("--current-state-file", type=str, default="", help="Optional current state JSON file")
    task_memory_parser.add_argument("--min-score", type=float, default=0.1)
    task_memory_parser.add_argument("--limit", type=int, default=5)
    task_memory_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    task_memory_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline memory policy trace report
    memory_policy_parser = subparsers.add_parser("memory-policy-report", help="Report memory write/read/manage policy gaps in session logs")
    memory_policy_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    memory_policy_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    memory_policy_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline bounded planner context report
    bounded_context_parser = subparsers.add_parser("bounded-context-report", help="Audit bounded typed retrieval context before planner calls")
    bounded_context_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    bounded_context_parser.add_argument("--max-read-chars", type=int, default=1200, help="Maximum characters allowed from any single memory read")
    bounded_context_parser.add_argument("--max-cycle-chars", type=int, default=2400, help="Maximum total memory-read characters allowed before each plan")
    bounded_context_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    bounded_context_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline continual-learning trace report
    continual_parser = subparsers.add_parser("continual-learning-report", help="Report open-ended continual-learning diagnostics in session logs")
    continual_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    continual_parser.add_argument("--cell-size", type=float, default=8.0, help="XZ block span per world-model cell")
    continual_parser.add_argument("--max-read-chars", type=int, default=1200, help="Maximum characters allowed from any single memory read")
    continual_parser.add_argument("--max-cycle-chars", type=int, default=2400, help="Maximum total memory-read characters allowed before each plan")
    continual_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    continual_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline controlled task-stream transfer report
    task_stream_parser = subparsers.add_parser(
        "task-stream-transfer-report",
        help="Report AgentCL-style transfer gains, stability, and interference in controlled task streams",
    )
    task_stream_parser.add_argument("--stream-file", action="append", default=[], help="JSON/JSONL controlled task stream spec")
    task_stream_parser.add_argument("--cell-size", type=float, default=8.0, help="XZ block span per world-model cell when deriving scores from session logs")
    task_stream_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    task_stream_parser.add_argument("--log-level", type=str, default="INFO")

    task_stream_gate_parser = subparsers.add_parser(
        "task-stream-transfer-gate",
        help="Gate memory or skill promotion using AgentCL-style task-stream transfer reports",
    )
    task_stream_gate_parser.add_argument("--transfer-report", action="append", default=[], help="Saved task-stream-transfer-report JSON")
    task_stream_gate_parser.add_argument("--target", type=str, default="memory_or_skill_promotion", help="Promotion target label for the gate report")
    task_stream_gate_parser.add_argument("--min-plasticity-gain", type=float, default=0.01, help="Minimum baseline-to-first-pass gain required")
    task_stream_gate_parser.add_argument("--min-stability-gain", type=float, default=0.0, help="Minimum second-pass minus first-pass gain required")
    task_stream_gate_parser.add_argument("--min-generalization-gain", type=float, default=0.0, help="Minimum held-out minus baseline gain required")
    task_stream_gate_parser.add_argument("--min-reuse-coverage", type=float, default=0.5, help="Minimum expected reuse-tag coverage required")
    task_stream_gate_parser.add_argument("--max-interference-count", type=int, default=0, help="Maximum allowed transfer/interference regressions")
    task_stream_gate_parser.add_argument("--no-require-heldout", action="store_true", help="Allow approval without held-out generalization evidence")
    task_stream_gate_parser.add_argument("--output", type=str, default="", help="Optional JSON gate report path")
    task_stream_gate_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline memory read filter report
    memory_read_parser = subparsers.add_parser("memory-read-filter-report", help="Report stale or condition-mismatched durable memories for a query")
    memory_read_parser.add_argument("--memory-dir", type=str, default="workspace/memory")
    memory_read_parser.add_argument("--query", type=str, default="", help="Optional retrieval query to filter relevant entries")
    memory_read_parser.add_argument("--current-state-json", type=str, default="", help="Optional current state JSON object for conditional applicability checks")
    memory_read_parser.add_argument("--current-state-file", type=str, default="", help="Optional JSON file with current state for conditional applicability checks")
    memory_read_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    memory_read_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline promptware memory audit
    memory_promptware_parser = subparsers.add_parser("memory-promptware-report", help="Report promptware or memory-injection threats in durable memory")
    memory_promptware_parser.add_argument("--memory-dir", type=str, default="workspace/memory")
    memory_promptware_parser.add_argument("--query", type=str, default="", help="Optional retrieval query to scope the audit")
    memory_promptware_parser.add_argument("--current-state-json", type=str, default="", help="Optional current state JSON object for conditional applicability checks")
    memory_promptware_parser.add_argument("--current-state-file", type=str, default="", help="Optional JSON file with current state for conditional applicability checks")
    memory_promptware_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    memory_promptware_parser.add_argument("--log-level", type=str, default="INFO")

    # Skill candidate review queue
    candidates_parser = subparsers.add_parser("skill-candidates", help="Review extracted skill candidates")
    candidates_parser.add_argument("--queue", type=str, default="workspace/skills/skill_candidates.jsonl")
    candidates_parser.add_argument("--storage-path", type=str, default="workspace/skills")
    candidates_parser.add_argument("--session", type=str, default="", help="Extract candidates from a session JSONL log")
    candidates_parser.add_argument("--promotion-critic", action="store_true", help="Use configured LLM as fallback critic for unknown verifier gates")
    candidates_parser.add_argument("--discovery-skill-gate", action="append", default=[], help="Saved discovery-application-report JSON required before approving experiment-derived skills")
    candidates_parser.add_argument("--task-stream-transfer-gate", action="append", default=[], help="Saved task-stream-transfer-gate JSON required before promoting transfer-tested skills")
    candidates_parser.add_argument("--llm-provider", type=str, default="openai")
    candidates_parser.add_argument("--llm-model", type=str, default="gpt-4o-mini")
    candidates_parser.add_argument("--llm-base-url", type=str, default="")
    candidates_parser.add_argument("--api-key", type=str, default="")
    candidates_parser.add_argument("--causal-summaries", action="store_true", help="Extract repeated causal-summary candidates from the session log")
    candidates_parser.add_argument("--min-causal-repeats", type=int, default=3, help="Minimum repeated causal events before queueing a summary candidate")
    candidates_parser.add_argument("--min-causal-value", type=float, default=0.65, help="Minimum causal value score before queueing a summary candidate")
    candidates_parser.add_argument("--failure-corrections", action="store_true", help="Extract repeated failure-to-correction candidates from the session log")
    candidates_parser.add_argument("--min-failure-repeats", type=int, default=2, help="Minimum repeated failures before queueing a correction candidate")
    candidates_parser.add_argument("--min-failure-value", type=float, default=0.55, help="Minimum failure value score before queueing a correction candidate")
    candidates_parser.add_argument("--approve", type=str, default="", help="Approve a candidate id")
    candidates_parser.add_argument("--reject", type=str, default="", help="Reject a candidate id")
    candidates_parser.add_argument("--reason", type=str, default="", help="Reason for rejection")
    candidates_parser.add_argument("--all", action="store_true", help="List all candidates, not just pending")

    skill_edit_parser = subparsers.add_parser(
        "skill-edit-proposal-report",
        help="Review queued skill candidates as create/update/retain/reject proposals",
    )
    skill_edit_parser.add_argument("--queue", type=str, default="workspace/skills/skill_candidates.jsonl")
    skill_edit_parser.add_argument("--skill-storage-path", type=str, default="workspace/skills")
    skill_edit_parser.add_argument("--discovery-skill-gate", action="append", default=[], help="Saved discovery-application-report JSON to include in candidate validation")
    skill_edit_parser.add_argument("--task-stream-transfer-gate", action="append", default=[], help="Saved task-stream-transfer-gate JSON used as counterfactual probe evidence")
    skill_edit_parser.add_argument("--include-all", action="store_true", help="Include approved/rejected candidates as retain/review records")
    skill_edit_parser.add_argument("--no-require-transfer-gate", action="store_true", help="Allow create/update proposals without approved transfer probe evidence")
    skill_edit_parser.add_argument("--min-score", type=float, default=0.55, help="Minimum candidate score for create/update proposals")
    skill_edit_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    skill_edit_parser.add_argument("--log-level", type=str, default="INFO")

    # M7 collaboration benchmark dry-run/assignment
    collab_parser = subparsers.add_parser("collab-benchmark", help="Prepare an M7 collaboration benchmark")
    collab_parser.add_argument("--spec", type=str, default="workspace/benchmarks/m7_time_sensitive_shelter.json")
    collab_parser.add_argument("--state-path", type=str, default="workspace/multiagent/collab_benchmark_state.json")
    collab_parser.add_argument("--no-reset", action="store_true", help="Keep existing shared-state file")
    collab_parser.add_argument("--preflight", action="store_true", help="Check Agent executor role bridges before execution")
    collab_parser.add_argument("--execute", action="store_true", help="Run the synchronous state-transition executor after assignment")
    collab_parser.add_argument("--executor", type=str, default="simulated", choices=["simulated", "agent"], help="Task executor for --execute")
    collab_parser.add_argument("--max-steps", type=int, default=0, help="Maximum dispatch steps for --execute")
    collab_parser.add_argument("--mixed-policy-ablation", action="store_true", help="Run Agent-backed collaboration once without and once with approved mixed-policy patches")
    collab_parser.add_argument("--host", type=str, default="localhost")
    collab_parser.add_argument("--port", type=int, default=25565)
    collab_parser.add_argument("--username", type=str, default="Singularity")
    collab_parser.add_argument("--bridge-host", type=str, default="127.0.0.1")
    collab_parser.add_argument("--bridge-port", type=int, default=3000)
    collab_parser.add_argument("--bridge-port-base", type=int, default=0, help="Use sequential bridge ports from this base for Agent executor roles")
    collab_parser.add_argument("--role-bridge-port", action="append", default=[], metavar="ROLE=PORT", help="Explicit Agent executor bridge port for a role; repeat for multiple roles")
    collab_parser.add_argument("--single-agent-baseline", action="store_true", help="Run a single-agent baseline after collaboration execution")
    collab_parser.add_argument("--baseline-role-id", type=str, default="single_agent", help="Role id for --single-agent-baseline")
    collab_parser.add_argument("--baseline-state-path", type=str, default="", help="Optional shared-state path for the single-agent baseline")
    collab_parser.add_argument("--llm-provider", type=str, default="openai")
    collab_parser.add_argument("--llm-model", type=str, default="gpt-4o-mini")
    collab_parser.add_argument("--llm-base-url", type=str, default="")
    collab_parser.add_argument("--api-key", type=str, default="")
    collab_parser.add_argument("--goal-critic", action="store_true", help="Use configured LLM as fallback critic for unknown goal verification")
    collab_parser.add_argument("--no-skill-memory-context", action="store_true", help="Disable skill-level memory hints in planner context")
    collab_parser.add_argument("--no-vision-analysis", action="store_true", help="Disable structured vision grounding on observations")
    collab_parser.add_argument("--no-visual-action-grounding", action="store_true", help="Disable visual suggestions from modifying planned actions")
    collab_parser.add_argument("--capture-screenshots", action="store_true", help="Ask each Agent bridge renderer to capture screenshots for visual analysis")
    collab_parser.add_argument("--screenshot-dir", type=str, default="logs/screenshots", help="Directory for captured screenshot files")
    collab_parser.add_argument("--screenshot-min-interval", type=float, default=2.0, help="Minimum seconds between screenshot capture attempts")
    collab_parser.add_argument("--mixed-policy-patch", action="append", default=[], help="Approved mixed-initiative policy patch JSON to load in Agent executor roles")
    collab_parser.add_argument("--mixed-policy-gate", action="append", default=[], help="Approved mixed-policy gate JSON required before loading Agent executor policy patches")
    collab_parser.add_argument("--self-evolution-feedback", action="append", default=[], help="self-evolution-report JSON to load as advisory planner feedback")
    collab_parser.add_argument("--world-model-feedback", action="append", default=[], help="world-model-report JSON to load into Agent executor curriculum after approved gate")
    collab_parser.add_argument("--world-model-gate", action="append", default=[], help="Approved world-model-feedback-gate JSON required before loading world-model feedback")
    collab_parser.add_argument("--action-value-feedback", action="append", default=[], help="action-value-report JSON to load for advisory action candidate scoring")
    collab_parser.add_argument("--action-value-transition-gate", action="append", default=[], help="Approved action-value-transition-gate JSON required before loading ASV transition scores")
    collab_parser.add_argument("--action-value-transition-evaluator-report", action="append", default=[], help="Approved action-value-transition-evaluator-report JSON required before loading ASV transition scores")
    collab_parser.add_argument("--skill-memory-quality-feedback", action="append", default=[], help="skill-memory-quality-report JSON to load for advisory skill-memory retrieval ranking")
    collab_parser.add_argument("--skill-memory-quality-gate", action="append", default=[], help="Approved skill-memory-quality-gate JSON required before loading quality feedback")
    _add_coaching_args(collab_parser)
    collab_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    collab_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline scheduling ablation
    scheduling_parser = subparsers.add_parser("scheduling-ablation", help="Compare direct-only vs causal-opportunity task scheduling")
    scheduling_parser.add_argument("--session-log", action="append", default=[], help="Replay a session JSONL log into scheduling ablation cases")
    scheduling_parser.add_argument("--max-cases-per-log", type=int, default=20)
    scheduling_parser.add_argument("--min-value-score", type=float, default=0.55, help="Minimum causal event value for session-log replay")
    scheduling_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    scheduling_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline promotion review visual ablation
    review_parser = subparsers.add_parser("promotion-review-ablation", help="Compare skill promotion review with and without visual evidence")
    review_parser.add_argument("--session-log", action="append", default=[], help="Replay a session JSONL log into promotion review ablation")
    review_parser.add_argument("--promotion-critic", action="store_true", help="Use configured LLM critic for unknown verifier gates")
    review_parser.add_argument("--llm-provider", type=str, default="openai")
    review_parser.add_argument("--llm-model", type=str, default="gpt-4o-mini")
    review_parser.add_argument("--llm-base-url", type=str, default="")
    review_parser.add_argument("--api-key", type=str, default="")
    review_parser.add_argument("--causal-summaries", action="store_true", help="Include repeated causal-summary candidates")
    review_parser.add_argument("--failure-corrections", action="store_true", help="Include repeated failure-correction candidates")
    review_parser.add_argument("--label-file", type=str, default="", help="Optional manual labels JSON/JSONL for agreement metrics")
    review_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    review_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline goal verification visual ablation
    goal_review_parser = subparsers.add_parser("goal-verification-ablation", help="Compare goal verification with deterministic, API visual, and screenshot/VLM evidence")
    goal_review_parser.add_argument("--session-log", action="append", default=[], help="Replay a session JSONL log into goal verification ablation")
    goal_review_parser.add_argument("--goal-critic", action="store_true", help="Use configured LLM critic for unknown goal verifier coverage")
    goal_review_parser.add_argument("--llm-provider", type=str, default="openai")
    goal_review_parser.add_argument("--llm-model", type=str, default="gpt-4o-mini")
    goal_review_parser.add_argument("--llm-base-url", type=str, default="")
    goal_review_parser.add_argument("--api-key", type=str, default="")
    goal_review_parser.add_argument("--label-file", type=str, default="", help="Optional manual labels JSON/JSONL for agreement metrics")
    goal_review_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    goal_review_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline manual review label templates
    label_template_parser = subparsers.add_parser("review-label-template", help="Generate JSONL manual review label templates from session logs")
    label_template_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to convert into review label templates")
    label_template_parser.add_argument("--mode", type=str, default="both", choices=["promotion", "goal", "both"], help="Template type to generate")
    label_template_parser.add_argument("--causal-summaries", action="store_true", help="Include repeated causal-summary promotion candidates")
    label_template_parser.add_argument("--failure-corrections", action="store_true", help="Include repeated failure-correction promotion candidates")
    label_template_parser.add_argument("--output", type=str, default="", help="Optional JSONL output path")
    label_template_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline manual review label validation
    label_validate_parser = subparsers.add_parser("review-label-validate", help="Validate manual review labels before visual ablations")
    label_validate_parser.add_argument("--label-file", type=str, required=True, help="Manual labels JSON/JSONL file to validate")
    label_validate_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    label_validate_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline visual trace coverage report
    visual_trace_parser = subparsers.add_parser("visual-trace-report", help="Report screenshot/VLM/API visual evidence coverage in session logs")
    visual_trace_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    visual_trace_parser.add_argument("--causal-summaries", action="store_true", help="Include repeated causal-summary promotion candidates")
    visual_trace_parser.add_argument("--failure-corrections", action="store_true", help="Include repeated failure-correction promotion candidates")
    visual_trace_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    visual_trace_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline open-world exploration trace report
    exploration_trace_parser = subparsers.add_parser("exploration-trace-report", help="Report autonomous/open-world exploration coverage in session logs")
    exploration_trace_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    exploration_trace_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    exploration_trace_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline world-model trace report
    world_model_parser = subparsers.add_parser("world-model-report", help="Build AGI-Maze-style world-state cells and exploration frontiers from session logs")
    world_model_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    world_model_parser.add_argument("--cell-size", type=float, default=8.0, help="XZ block span per world-model cell")
    world_model_parser.add_argument("--limit", type=int, default=12, help="Maximum cells/frontiers/hotspots to include per case")
    world_model_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    world_model_parser.add_argument("--log-level", type=str, default="INFO")

    world_model_gate_parser = subparsers.add_parser(
        "world-model-feedback-gate",
        help="Gate world-model frontier/resource feedback before runtime curriculum loading",
    )
    world_model_gate_parser.add_argument("--world-model-report", action="append", default=[], help="Saved world-model-report JSON")
    world_model_gate_parser.add_argument("--target", type=str, default="world_model_curriculum_feedback", help="Gate target label")
    world_model_gate_parser.add_argument("--min-ready-logs", type=int, default=1, help="Minimum ready world-model logs required")
    world_model_gate_parser.add_argument("--min-frontiers", type=int, default=1, help="Minimum frontier count required")
    world_model_gate_parser.add_argument("--min-actionable-items", type=int, default=1, help="Minimum structured frontiers, hotspots, or suggested goals required")
    world_model_gate_parser.add_argument("--output", type=str, default="", help="Optional JSON gate report path")
    world_model_gate_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline self-evolution trace report
    self_evolution_parser = subparsers.add_parser("self-evolution-report", help="Report execution progress, stagnation, and adaptor hints in session logs")
    self_evolution_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    self_evolution_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    self_evolution_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline plan-action compliance trace report
    plan_action_parser = subparsers.add_parser("plan-action-compliance-report", help="Report whether executed actions follow preceding plan windows")
    plan_action_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    plan_action_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    plan_action_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline terminal commitment trace report
    terminal_commitment_parser = subparsers.add_parser("terminal-commitment-report", help="Report VIGIL-style world completion versus terminal completion claims")
    terminal_commitment_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    terminal_commitment_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    terminal_commitment_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline action verification replay report
    action_verification_parser = subparsers.add_parser("action-verification-report", help="Replay logged actions through deterministic action verification")
    action_verification_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    action_verification_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    action_verification_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline verifier-guided candidate action selection report
    action_candidate_parser = subparsers.add_parser("action-candidate-report", help="Replay logged actions through verifier-guided candidate selection")
    action_candidate_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    action_candidate_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    action_candidate_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline action outcome value profile report
    action_value_parser = subparsers.add_parser("action-value-report", help="Aggregate action outcome values from session logs")
    action_value_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    action_value_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    action_value_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline action transition value runtime-readiness gate
    action_value_gate_parser = subparsers.add_parser("action-value-transition-gate", help="Gate ASV-style transition-value feedback before runtime use")
    action_value_gate_parser.add_argument("--action-value-report", action="append", default=[], help="Saved action-value-report JSON")
    action_value_gate_parser.add_argument("--target", type=str, default="action_value_transition_feedback", help="Gate target label")
    action_value_gate_parser.add_argument("--min-trusted-items", type=int, default=1, help="Minimum trusted transition signatures required")
    action_value_gate_parser.add_argument("--min-trusted-transitions", type=int, default=1, help="Minimum trusted transition attempts required")
    action_value_gate_parser.add_argument("--min-transition-confidence", type=float, default=0.75, help="Minimum average transition confidence")
    action_value_gate_parser.add_argument("--max-low-confidence-rate", type=float, default=0.25, help="Maximum overall low-confidence transition rate")
    action_value_gate_parser.add_argument("--max-item-low-confidence-rate", type=float, default=0.25, help="Maximum per-item low-confidence transition rate")
    action_value_gate_parser.add_argument("--output", type=str, default="", help="Optional JSON gate report path")
    action_value_gate_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline state-grounded evaluator comparison for action transition values
    action_value_eval_parser = subparsers.add_parser("action-value-transition-evaluator-report", help="Compare deterministic ASV transition labels against a state-grounded LLM evaluator")
    action_value_eval_parser.add_argument("--action-value-report", action="append", default=[], help="Saved action-value-report JSON")
    action_value_eval_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect directly")
    action_value_eval_parser.add_argument("--limit", type=int, default=40, help="Maximum transition windows to evaluate")
    action_value_eval_parser.add_argument("--min-transition-confidence", type=float, default=0.75, help="Minimum deterministic transition confidence")
    action_value_eval_parser.add_argument("--min-evaluator-confidence", type=float, default=0.65, help="Minimum LLM evaluator confidence")
    action_value_eval_parser.add_argument("--min-evaluated-transitions", type=int, default=1, help="Minimum evaluated transition windows required")
    action_value_eval_parser.add_argument("--min-label-agreement-rate", type=float, default=0.75, help="Minimum deterministic-vs-evaluator label agreement")
    action_value_eval_parser.add_argument("--max-avg-score-delta", type=float, default=0.25, help="Maximum average absolute score delta")
    action_value_eval_parser.add_argument("--max-large-score-delta-rate", type=float, default=0.25, help="Maximum rate of large score deltas")
    action_value_eval_parser.add_argument("--llm-evaluator", action="store_true", help="Call the configured LLM as the state-grounded evaluator")
    action_value_eval_parser.add_argument("--llm-provider", type=str, default="openai")
    action_value_eval_parser.add_argument("--llm-model", type=str, default="gpt-4o-mini")
    action_value_eval_parser.add_argument("--llm-base-url", type=str, default="")
    action_value_eval_parser.add_argument("--api-key", type=str, default="")
    action_value_eval_parser.add_argument("--output", type=str, default="", help="Optional JSON evaluator report path")
    action_value_eval_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline self-evolution automatic repair gate
    self_evolution_gate_parser = subparsers.add_parser("self-evolution-gate", help="Gate automatic self-evolution plan repair with verifier and counterexample evidence")
    self_evolution_gate_parser.add_argument("--self-evolution-report", action="append", default=[], help="Saved self-evolution-report JSON")
    self_evolution_gate_parser.add_argument("--verifier-report", action="append", default=[], help="Saved goal verifier or goal-verification-ablation JSON")
    self_evolution_gate_parser.add_argument("--counterexample-report", action="append", default=[], help="Saved counterexample JSON proving unresolved counterexamples are absent or reviewed")
    self_evolution_gate_parser.add_argument("--output", type=str, default="", help="Optional JSON gate report path")
    self_evolution_gate_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline discovery-to-application trace report
    discovery_parser = subparsers.add_parser("discovery-application-report", help="Report SciCrafter-style discovery-to-application evidence in session logs")
    discovery_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    discovery_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    discovery_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline action abstraction report
    action_abstraction_parser = subparsers.add_parser("action-abstraction-report", help="Report canonical actions and backend mapping coverage in session logs")
    action_abstraction_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    action_abstraction_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    action_abstraction_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline mixed-initiative task template report
    mixed_parser = subparsers.add_parser("mixed-initiative-report", help="Compile MineNPC-style task templates and optionally validate bounded evidence")
    mixed_parser.add_argument("--goal", type=str, default="Collect 20 oak logs", help="Natural-language Minecraft request")
    mixed_template_choices = [
        "auto",
        "collect_oak_logs",
        "fetch_named_tool",
        "craft_or_process_item",
        "collect_or_mine_resource",
        "build_or_place_structure",
        "unsupported_request",
    ]
    mixed_parser.add_argument("--template", type=str, default="auto", choices=mixed_template_choices, help="Template to use")
    mixed_parser.add_argument("--context-json", type=str, default="", help="Optional JSON object with slots, memory_preferences, or clarification_answers")
    mixed_parser.add_argument("--context-file", type=str, default="", help="Optional JSON file with context")
    mixed_parser.add_argument("--evidence-json", type=str, default="", help="Optional bounded evidence JSON object")
    mixed_parser.add_argument("--evidence-file", type=str, default="", help="Optional bounded evidence JSON file")
    mixed_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    mixed_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline mixed-initiative trace report
    mixed_trace_parser = subparsers.add_parser("mixed-initiative-trace-report", help="Replay session logs through MineNPC-style task validators")
    mixed_trace_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    mixed_trace_parser.add_argument("--template", type=str, default="auto", choices=mixed_template_choices, help="Template to use for all goals")
    mixed_trace_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    mixed_trace_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline mixed-initiative recommendation queue
    mixed_queue_parser = subparsers.add_parser(
        "mixed-initiative-review-queue",
        help="Aggregate mixed-initiative trace recommendations into review queue items",
    )
    mixed_queue_parser.add_argument("--trace-report", action="append", default=[], help="Saved mixed-initiative trace JSON report")
    mixed_queue_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect directly")
    mixed_queue_parser.add_argument("--template", type=str, default="auto", choices=mixed_template_choices, help="Template to force for session-log inputs")
    mixed_queue_parser.add_argument("--output", type=str, default="", help="Optional JSON queue path")
    mixed_queue_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline mixed-initiative review experiment routing
    mixed_review_plan_parser = subparsers.add_parser(
        "mixed-initiative-review-plan",
        help="Route mixed-initiative review queue items into follow-up experiment cases",
    )
    mixed_review_plan_parser.add_argument("--review-queue", action="append", default=[], help="Saved mixed-initiative review queue JSON")
    mixed_review_plan_parser.add_argument("--trace-report", action="append", default=[], help="Saved mixed-initiative trace JSON report")
    mixed_review_plan_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect directly")
    mixed_review_plan_parser.add_argument("--template", type=str, default="auto", choices=mixed_template_choices, help="Template to force for session-log inputs")
    mixed_review_plan_parser.add_argument("--output", type=str, default="", help="Optional JSON experiment plan path")
    mixed_review_plan_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline mixed-initiative review approval labels
    mixed_review_label_parser = subparsers.add_parser(
        "mixed-initiative-review-label-template",
        help="Generate JSONL operator approval labels from mixed-initiative review plans",
    )
    mixed_review_label_parser.add_argument("--review-plan", action="append", default=[], help="Saved mixed-initiative review plan JSON")
    mixed_review_label_parser.add_argument("--review-queue", action="append", default=[], help="Saved mixed-initiative review queue JSON")
    mixed_review_label_parser.add_argument("--trace-report", action="append", default=[], help="Saved mixed-initiative trace JSON report")
    mixed_review_label_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect directly")
    mixed_review_label_parser.add_argument("--template", type=str, default="auto", choices=mixed_template_choices, help="Template to force for session-log inputs")
    mixed_review_label_parser.add_argument("--output", type=str, default="", help="Optional JSONL label template path")
    mixed_review_label_parser.add_argument("--log-level", type=str, default="INFO")

    mixed_review_label_validate_parser = subparsers.add_parser(
        "mixed-initiative-review-label-validate",
        help="Validate filled mixed-initiative review approval labels",
    )
    mixed_review_label_validate_parser.add_argument("--label-file", type=str, default="", help="Filled mixed-initiative review labels JSON/JSONL")
    mixed_review_label_validate_parser.add_argument("--review-plan", action="append", default=[], help="Saved mixed-initiative review plan JSON for case matching")
    mixed_review_label_validate_parser.add_argument("--output", type=str, default="", help="Optional JSON validation report path")
    mixed_review_label_validate_parser.add_argument("--log-level", type=str, default="INFO")

    mixed_review_execute_parser = subparsers.add_parser(
        "mixed-initiative-review-execute",
        help="Execute approved mixed-initiative review labels through whitelisted report builders",
    )
    mixed_review_execute_parser.add_argument("--label-file", type=str, default="", help="Filled approved mixed-initiative review labels JSON/JSONL")
    mixed_review_execute_parser.add_argument("--review-plan", action="append", default=[], help="Saved mixed-initiative review plan JSON for case matching")
    mixed_review_execute_parser.add_argument("--output-dir", type=str, default="", help="Optional directory for per-case artifact JSON")
    mixed_review_execute_parser.add_argument("--dry-run", action="store_true", help="Validate approvals and show executable cases without running reports")
    mixed_review_execute_parser.add_argument("--output", type=str, default="", help="Optional JSON execution report path")
    mixed_review_execute_parser.add_argument("--log-level", type=str, default="INFO")

    mixed_policy_patch_parser = subparsers.add_parser(
        "mixed-initiative-policy-patch",
        help="Build reusable action/template policy feedback from approved review execution artifacts",
    )
    mixed_policy_patch_parser.add_argument("--execution-report", action="append", default=[], help="Saved mixed-initiative review execution JSON")
    mixed_policy_patch_parser.add_argument("--artifact", action="append", default=[], help="Per-case artifact JSON emitted by mixed-initiative-review-execute")
    mixed_policy_patch_parser.add_argument("--output", type=str, default="", help="Optional JSON policy patch path")
    mixed_policy_patch_parser.add_argument("--log-level", type=str, default="INFO")

    mixed_policy_ablation_parser = subparsers.add_parser(
        "mixed-initiative-policy-ablation",
        help="Compare baseline vs approved mixed-initiative policy patch decisions",
    )
    mixed_policy_ablation_parser.add_argument("--policy-patch", action="append", default=[], help="Approved mixed-initiative policy patch JSON")
    mixed_policy_ablation_parser.add_argument("--action", action="append", default=[], help="Canonical action type or JSON object to compare")
    mixed_policy_ablation_parser.add_argument("--template-id", action="append", default=[], help="Template id to compare review decisions")
    mixed_policy_ablation_parser.add_argument("--candidate-id", action="append", default=[], help="Template-candidate id to compare review decisions")
    mixed_policy_ablation_parser.add_argument("--allow-planned-backend", action="store_true", help="Allow planned desktop backend decisions in the comparison")
    mixed_policy_ablation_parser.add_argument("--output", type=str, default="", help="Optional JSON ablation report path")
    mixed_policy_ablation_parser.add_argument("--log-level", type=str, default="INFO")

    mixed_policy_gate_parser = subparsers.add_parser(
        "mixed-initiative-policy-gate",
        help="Gate mixed-policy patch promotion using offline/live ablation reports",
    )
    mixed_policy_gate_parser.add_argument("--policy-ablation", action="append", default=[], help="Saved mixed-initiative-policy-ablation JSON")
    mixed_policy_gate_parser.add_argument("--benchmark-ablation", action="append", default=[], help="Saved benchmark --mixed-policy-ablation JSON")
    mixed_policy_gate_parser.add_argument("--collab-ablation", action="append", default=[], help="Saved collab-benchmark --mixed-policy-ablation JSON")
    mixed_policy_gate_parser.add_argument("--output", type=str, default="", help="Optional JSON gate report path")
    mixed_policy_gate_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline mixed-initiative held-out variant report
    mixed_variant_parser = subparsers.add_parser(
        "mixed-initiative-variant-report",
        help="Replay held-out natural-language variants through mixed-initiative templates",
    )
    mixed_variant_parser.add_argument("--case-file", action="append", default=[], help="JSON/JSONL variant case file")
    mixed_variant_parser.add_argument("--no-builtins", action="store_true", help="Skip built-in held-out variant cases")
    mixed_variant_parser.add_argument(
        "--template",
        type=str,
        default="auto",
        choices=mixed_template_choices,
        help="Template to force for all variants",
    )
    mixed_variant_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    mixed_variant_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline visual review pipeline
    visual_pipeline_parser = subparsers.add_parser("visual-review-pipeline", help="Run visual trace audit, review templates, label validation, and optional ablations")
    visual_pipeline_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    visual_pipeline_parser.add_argument("--mode", type=str, default="both", choices=["promotion", "goal", "both"], help="Review mode to include")
    visual_pipeline_parser.add_argument("--label-file", type=str, default="", help="Optional filled manual labels JSON/JSONL file to validate and use")
    visual_pipeline_parser.add_argument("--run-ablations", action="store_true", help="Also run promotion/goal visual ablations after trace and label checks")
    visual_pipeline_parser.add_argument("--promotion-critic", action="store_true", help="Use configured LLM critic for promotion ablation")
    visual_pipeline_parser.add_argument("--goal-critic", action="store_true", help="Use configured LLM critic for goal-verification ablation")
    visual_pipeline_parser.add_argument("--llm-provider", type=str, default="openai")
    visual_pipeline_parser.add_argument("--llm-model", type=str, default="gpt-4o-mini")
    visual_pipeline_parser.add_argument("--llm-base-url", type=str, default="")
    visual_pipeline_parser.add_argument("--api-key", type=str, default="")
    visual_pipeline_parser.add_argument("--causal-summaries", action="store_true", help="Include repeated causal-summary promotion candidates")
    visual_pipeline_parser.add_argument("--failure-corrections", action="store_true", help="Include repeated failure-correction promotion candidates")
    visual_pipeline_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    visual_pipeline_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline reviewed policy-skill ablation
    policy_parser = subparsers.add_parser("policy-skill-ablation", help="Compare reviewed policy skills disabled vs enabled")
    policy_parser.add_argument("--skill-storage-path", type=str, default="", help="Load approved custom skills from this storage path and generate ablation cases")
    policy_parser.add_argument("--no-builtin", action="store_true", help="Skip built-in policy-skill ablation cases")
    policy_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    policy_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline visual action grounding ablation
    visual_action_parser = subparsers.add_parser("visual-action-ablation", help="Compare visual action grounding disabled vs enabled")
    visual_action_parser.add_argument("--session-log", action="append", default=[], help="Replay visual action interventions from session JSONL logs")
    visual_action_parser.add_argument("--max-cases-per-log", type=int, default=20, help="Maximum mined visual-action cases per session log; 0 means unlimited")
    visual_action_parser.add_argument("--include-builtin", action="store_true", help="Include built-in visual action cases when replaying session logs")
    visual_action_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    visual_action_parser.add_argument("--log-level", type=str, default="INFO")

    # Legacy: direct goal without subcommand
    parser.add_argument("--goal", type=str, default=None)

    args = parser.parse_args()

    log_level = getattr(args, "log_level", "INFO") or "INFO"
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    # Handle skills command (no server needed)
    if args.command == "skills":
        from singularity.core.skill_library import SkillLibrary
        lib = SkillLibrary(persist=True)
        print(f"\nSingularity Skill Library ({len(lib.skills)} skills)\n")
        for layer in ("primitive", "composite", "strategic"):
            skills = lib.list_skills(layer)
            if skills:
                print(f"  [{layer.upper()}]")
                for s in skills:
                    uses = f" ({s.total_uses} uses, {s.success_rate:.0%} success)" if s.total_uses > 0 else ""
                    print(f"    - {s.name}: {s.description}{uses}")
        return

    if args.command == "skill-graph-report":
        from singularity.core.skill_library import SkillLibrary

        lib = SkillLibrary(storage_path=getattr(args, "skill_storage_path", "workspace/skills"), persist=True)
        report = lib.skill_graph_report()
        print("\nSkill Graph Governance")
        print(f"  skills: {report['skill_count']} ({report['custom_skill_count']} custom)")
        print(f"  edges: {report['edge_count']}")
        print(f"  missing dependencies: {report['missing_dependency_count']}")
        print(f"  ungoverned custom skills: {report['ungoverned_custom_skill_count']}")
        print(f"  missing postconditions: {report['missing_postcondition_count']}")
        print(f"  cycles: {report['cycle_count']}")
        if report["issue_counts"]:
            parts = [f"{key}={value}" for key, value in sorted(report["issue_counts"].items())]
            print(f"  issues: {', '.join(parts)}")
        for node in report["nodes"]:
            if node["built_in"] and not node["issues"]:
                continue
            marker = "!" if node["issues"] else "+"
            governance = node["governance"]
            print(
                f"  [{marker}] {node['name']} layer={node['layer']} "
                f"gate={governance['gate_readiness']} deps={len(node['dependencies'])}"
            )
            if node["issues"]:
                print(f"      issues: {', '.join(node['issues'])}")
            if node["missing_dependencies"]:
                print(f"      missing deps: {', '.join(node['missing_dependencies'])}")
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "skill-contract-report":
        from singularity.core.skill_library import SkillLibrary

        world_state = {}
        if getattr(args, "world_state_file", ""):
            with open(args.world_state_file, "r", encoding="utf-8-sig") as f:
                world_state = json.load(f)
        elif getattr(args, "world_state_json", ""):
            try:
                world_state = json.loads(args.world_state_json)
            except json.JSONDecodeError as exc:
                print(f"skill-contract-report could not parse --world-state-json: {exc}")
                sys.exit(1)
        if not isinstance(world_state, dict):
            print("skill-contract-report world state must be a JSON object")
            sys.exit(1)

        lib = SkillLibrary(storage_path=getattr(args, "skill_storage_path", "workspace/skills"), persist=True)
        report = lib.skill_contract_report(
            goal=getattr(args, "goal", ""),
            world_state=world_state,
            limit=getattr(args, "limit", 20),
        )
        print("\nSkill Contract Report")
        print(f"  goal: {report['goal']}")
        print(
            f"  skills: {report['skill_count']}, matched: {report['matched_count']}, "
            f"ready/review/blocked: {report['ready_count']}/{report['review_count']}/{report['blocked_count']}"
        )
        if report["issue_counts"]:
            parts = [f"{key}={value}" for key, value in sorted(report["issue_counts"].items())]
            print(f"  issues: {', '.join(parts)}")
        for match in report["matches"][:getattr(args, "limit", 20)]:
            if match["score"] <= 0 and match["readiness"] == "ready":
                continue
            issues = f" issues={','.join(match['issues'])}" if match["issues"] else ""
            print(
                f"  - {match['name']} score={match['score']:.2f} "
                f"readiness={match['readiness']}{issues}"
            )
            if match["goal_matches"] or match["postcondition_matches"]:
                terms = sorted(set(match["goal_matches"] + match["postcondition_matches"]))
                print(f"      matches: {', '.join(terms[:8])}")
            if match["missing_preconditions"] or match["missing_required_items"] or match["missing_dependencies"]:
                missing = match["missing_preconditions"] + match["missing_required_items"] + match["missing_dependencies"]
                print(f"      missing: {', '.join(str(item) for item in missing[:8])}")
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "skill-memory-report":
        from singularity.core.skill_library import SkillLibrary

        lib = SkillLibrary(storage_path=getattr(args, "skill_storage_path", "workspace/skills"), persist=True)
        report = lib.skill_memory_report(
            goal=getattr(args, "goal", ""),
            task_family=getattr(args, "task_family", ""),
            include_builtins=getattr(args, "include_builtins", False),
            limit=getattr(args, "limit", 20),
        )
        print("\nSkill Memory Report")
        if report["goal"]:
            print(f"  goal: {report['goal']}")
        if report["task_family"]:
            print(f"  task family: {report['task_family']}")
        print(
            f"  skills: {report['skill_count']}, with memory: {report['skills_with_memory_count']}, "
            f"memories: {report['memory_count']}"
        )
        print(
            f"  success/failure memories: {report['success_memory_count']}/{report['failure_memory_count']}, "
            f"approved/review transfer memories: "
            f"{report['approved_transfer_memory_count']}/{report['review_transfer_memory_count']}"
        )
        if report["issue_counts"]:
            parts = [f"{key}={value}" for key, value in sorted(report["issue_counts"].items())]
            print(f"  issues: {', '.join(parts)}")
        if report["task_family_counts"]:
            parts = [f"{key}={value}" for key, value in sorted(report["task_family_counts"].items())]
            print(f"  task families: {', '.join(parts)}")
        for skill in report["skills"][:getattr(args, "limit", 20)]:
            if skill["built_in"] and not skill["memory_count"] and not getattr(args, "include_builtins", False):
                continue
            issues = f" issues={','.join(skill['issues'])}" if skill["issues"] else ""
            print(
                f"  - {skill['name']} memories={skill['memory_count']} "
                f"success/failure={skill['success_memory_count']}/{skill['failure_memory_count']} "
                f"gate={skill['gate_readiness']} contract={skill['contract_readiness']}{issues}"
            )
            for memory in skill["memories"][-2:]:
                label = memory.get("task_family") or memory.get("type") or "memory"
                note = memory.get("note", "")
                if note:
                    print(f"      {label}: {note[:120]}")
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "skill-lifecycle-report":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        runner = BenchmarkRunner(Config(skill_dir=getattr(args, "skill_storage_path", "workspace/skills")))
        report = runner.run_skill_lifecycle_report(
            skill_storage_path=getattr(args, "skill_storage_path", "workspace/skills"),
            goal=getattr(args, "goal", ""),
            task_family=getattr(args, "task_family", ""),
            include_builtins=getattr(args, "include_builtins", False),
            limit=getattr(args, "limit", 20),
        )
        runner.print_skill_lifecycle_report(report)
        if getattr(args, "output", ""):
            runner.save_skill_lifecycle_report(report, getattr(args, "output", ""))
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "skill-memory-quality-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("skill-memory-quality-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_skill_memory_quality_report_from_logs(session_logs)
        runner.print_skill_memory_quality_report(report)
        quality_feedback = runner.skill_memory_quality_feedback(report)
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "log_count": report.log_count,
                    "ready_log_count": report.ready_log_count,
                    "hint_event_count": report.hint_event_count,
                    "hint_count": report.hint_count,
                    "hint_type_counts": report.hint_type_counts,
                    "task_family_counts": report.task_family_counts,
                    "post_hint_failed_action_count": report.post_hint_failed_action_count,
                    "post_hint_goal_success_count": report.post_hint_goal_success_count,
                    "post_hint_goal_failure_count": report.post_hint_goal_failure_count,
                    "repeated_post_hint_failure_count": report.repeated_post_hint_failure_count,
                    "quality_label_counts": report.quality_label_counts,
                    "hint_quality_items": report.hint_quality_items,
                    "skill_memory_quality_feedback": quality_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "skill-memory-quality-ablation":
        from singularity.core.skill_library import SkillLibrary

        feedback_paths = getattr(args, "quality_feedback", []) or []
        if not feedback_paths:
            print("skill-memory-quality-ablation requires at least one --quality-feedback")
            sys.exit(1)
        cases = _load_skill_memory_quality_ablation_cases(args)
        if not cases:
            print("skill-memory-quality-ablation requires --goal or --case-file")
            sys.exit(1)
        feedback = _merge_skill_memory_quality_feedback_paths(feedback_paths)
        lib = SkillLibrary(storage_path=getattr(args, "skill_storage_path", "workspace/skills"), persist=True)
        report = lib.skill_memory_quality_ablation(
            feedback,
            cases=cases,
            limit=getattr(args, "limit", 5),
        )
        report["quality_feedback_paths"] = list(feedback_paths)

        print("\nSkill Memory Quality Ablation")
        print(
            f"  cases: {report['case_count']}, changed: {report['changed_count']}, "
            f"promoted: {report['promoted_count']}, demoted: {report['demoted_count']}, "
            f"quality applications: {report['quality_policy_application_count']}"
        )
        for case in report["cases"]:
            marker = "+" if case["changed"] else "~"
            print(f"  [{marker}] {case['id']}: {case['goal']} ({case['task_family'] or 'any'})")
            if case["promoted"]:
                print("      promoted: " + ", ".join(f"{item['skill']}#{item['adjusted_rank']}" for item in case["promoted"][:4]))
            if case["demoted"]:
                print("      demoted: " + ", ".join(f"{item['skill']}#{item['baseline_rank']}->{item['adjusted_rank']}" for item in case["demoted"][:4]))
            for item in case["adjusted_hints"][:min(3, getattr(args, "limit", 5))]:
                quality = ",".join(item.get("quality_policies", [])) or "none"
                print(f"      adjusted {item['rank']}: {item['hint_type']} {item['skill']} quality={quality}")
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "skill-memory-quality-gate":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        memory_reports = getattr(args, "skill_memory_report", []) or []
        feedback_paths = getattr(args, "quality_feedback", []) or []
        if not memory_reports:
            print("skill-memory-quality-gate requires at least one --skill-memory-report")
            sys.exit(1)
        if not feedback_paths:
            print("skill-memory-quality-gate requires at least one --quality-feedback")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.build_skill_memory_quality_gate(
            memory_report_paths=memory_reports,
            quality_feedback_paths=feedback_paths,
            target=getattr(args, "target", "skill_memory_reuse_promotion"),
            min_supported_reuse=getattr(args, "min_supported_reuse", 2),
            max_conflicting_reuse=getattr(args, "max_conflicting_reuse", 0),
        )
        runner.print_skill_memory_quality_gate_report(report)
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "memory-consolidation-report":
        from singularity.core.memory import MemorySystem

        memory = MemorySystem(memory_dir=getattr(args, "memory_dir", "workspace/memory"))
        candidates = memory.memory_consolidation_candidates(
            min_score=getattr(args, "min_score", 0.65),
            min_recall_count=getattr(args, "min_recall_count", 2),
            min_unique_queries=getattr(args, "min_unique_queries", 2),
            limit=getattr(args, "limit", 20),
        )
        report = {
            "memory_dir": getattr(args, "memory_dir", "workspace/memory"),
            "candidate_count": len(candidates),
            "min_score": getattr(args, "min_score", 0.65),
            "min_recall_count": getattr(args, "min_recall_count", 2),
            "min_unique_queries": getattr(args, "min_unique_queries", 2),
            "candidates": candidates,
        }
        print("\nMemory Consolidation Report")
        print(f"  candidates: {len(candidates)}")
        for candidate in candidates:
            label = candidate.get("content") or f"{candidate.get('task')} -> {candidate.get('outcome')}"
            print(
                f"  - {candidate['kind']} {candidate['id']} "
                f"score={candidate['score']:.2f} "
                f"recalls={candidate['recall_count']} "
                f"queries={candidate['unique_query_count']}: {label[:120]}"
            )
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"  saved: {args.output}")
        return

    if args.command == "transfer-memory-report":
        from singularity.core.memory import MemorySystem

        current_state = {}
        if getattr(args, "current_state_file", ""):
            with open(args.current_state_file, "r", encoding="utf-8-sig") as f:
                current_state = json.load(f)
        elif getattr(args, "current_state_json", ""):
            current_state = json.loads(args.current_state_json)
        if not isinstance(current_state, dict):
            print("transfer-memory-report current state must be a JSON object")
            sys.exit(1)

        memory = MemorySystem(memory_dir=getattr(args, "memory_dir", "workspace/memory"))
        report = memory.transfer_memory_report(
            getattr(args, "query", ""),
            current_state=current_state,
            limit=getattr(args, "limit", 10),
            min_score=getattr(args, "min_score", 0.1),
        )
        print("\nTransfer Memory Report")
        print(f"  query: {report['query']}")
        print(f"  experiences: {report['experience_count']}, matches: {report['match_count']}")
        if report["axis_counts"]:
            parts = [f"{axis}={count}" for axis, count in sorted(report["axis_counts"].items())]
            print(f"  axes: {', '.join(parts)}")
        for match in report["matches"]:
            axes = ",".join(match.get("matched_axes", [])) or "text"
            print(
                f"  - {match['id']} score={match['score']:.2f} "
                f"axes={axes}: {match['task']} -> {match['outcome']}"
            )
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"  saved: {args.output}")
        return

    if args.command == "task-memory-report":
        from singularity.core.memory import MemorySystem

        current_state = {}
        if getattr(args, "current_state_file", ""):
            with open(args.current_state_file, "r", encoding="utf-8-sig") as f:
                current_state = json.load(f)
        elif getattr(args, "current_state_json", ""):
            current_state = json.loads(args.current_state_json)
        if not isinstance(current_state, dict):
            print("task-memory-report current state must be a JSON object")
            sys.exit(1)

        task = {}
        if getattr(args, "task_file", ""):
            with open(args.task_file, "r", encoding="utf-8-sig") as f:
                task = json.load(f)
        elif getattr(args, "task_json", ""):
            task = json.loads(args.task_json)
        if task and not isinstance(task, dict):
            print("task-memory-report task must be a JSON object")
            sys.exit(1)

        memory = MemorySystem(memory_dir=getattr(args, "memory_dir", "workspace/memory"))
        report = memory.task_memory_profile(
            getattr(args, "goal", ""),
            task=task,
            current_state=current_state,
            limit=getattr(args, "limit", 5),
            min_score=getattr(args, "min_score", 0.1),
        )
        print("\nTask Memory Report")
        print(f"  goal: {report['goal']}")
        if report["task"].get("title"):
            print(f"  task: {report['task'].get('title')}")
        print(f"  scoped memories: {report['memory_match_count']}, transfer matches: {report['transfer_match_count']}")
        if report["axis_counts"]:
            parts = [f"{axis}={count}" for axis, count in sorted(report["axis_counts"].items())]
            print(f"  transfer axes: {', '.join(parts)}")
        for memory_match in report["memory_matches"][:getattr(args, "limit", 5)]:
            print(f"  - memory {memory_match['id']} score={memory_match['score']:.2f}: {memory_match['content'][:120]}")
        for transfer in report["transfer_matches"][:getattr(args, "limit", 5)]:
            axes = ",".join(transfer.get("matched_axes", [])) or "text"
            print(
                f"  - transfer {transfer['id']} score={transfer['score']:.2f} "
                f"axes={axes}: {transfer['task']} -> {transfer['outcome']}"
            )
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"  saved: {args.output}")
        return

    if args.command == "memory-policy-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("memory-policy-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_memory_policy_report_from_logs(session_logs)
        runner.print_memory_policy_report(report)
        memory_policy_feedback = runner.memory_policy_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "log_count": report.log_count,
                    "ready_log_count": report.ready_log_count,
                    "event_count": report.event_count,
                    "explicit_memory_write_count": report.explicit_memory_write_count,
                    "explicit_memory_read_count": report.explicit_memory_read_count,
                    "explicit_memory_manage_count": report.explicit_memory_manage_count,
                    "semantic_write_candidate_count": report.semantic_write_candidate_count,
                    "missed_semantic_write_count": report.missed_semantic_write_count,
                    "failure_learning_candidate_count": report.failure_learning_candidate_count,
                    "consolidation_signal_count": report.consolidation_signal_count,
                    "noisy_write_candidate_count": report.noisy_write_candidate_count,
                    "missing_read_trace_count": report.missing_read_trace_count,
                    "read_filter_event_count": report.read_filter_event_count,
                    "read_filtered_entry_count": report.read_filtered_entry_count,
                    "read_filter_reasons": report.read_filter_reasons,
                    "memory_policy_feedback": memory_policy_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "bounded-context-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("bounded-context-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_bounded_context_report_from_logs(
            session_logs,
            max_read_chars=getattr(args, "max_read_chars", 1200),
            max_cycle_chars=getattr(args, "max_cycle_chars", 2400),
        )
        runner.print_bounded_context_report(report)
        bounded_context_feedback = runner.bounded_context_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "log_count": report.log_count,
                    "ready_log_count": report.ready_log_count,
                    "planning_cycle_count": report.planning_cycle_count,
                    "bounded_cycle_count": report.bounded_cycle_count,
                    "unbounded_cycle_count": report.unbounded_cycle_count,
                    "missing_read_cycle_count": report.missing_read_cycle_count,
                    "oversized_read_cycle_count": report.oversized_read_cycle_count,
                    "oversized_cycle_count": report.oversized_cycle_count,
                    "raw_context_cycle_count": report.raw_context_cycle_count,
                    "low_diversity_cycle_count": report.low_diversity_cycle_count,
                    "max_read_chars": report.max_read_chars,
                    "max_cycle_chars": report.max_cycle_chars,
                    "read_layers": report.read_layers,
                    "read_types": report.read_types,
                    "bounded_context_feedback": bounded_context_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "continual-learning-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("continual-learning-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_continual_learning_report_from_logs(
            session_logs,
            cell_size=getattr(args, "cell_size", 8.0),
            max_read_chars=getattr(args, "max_read_chars", 1200),
            max_cycle_chars=getattr(args, "max_cycle_chars", 2400),
        )
        runner.print_continual_learning_report(report)
        continual_learning_feedback = runner.continual_learning_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "log_count": report.log_count,
                    "ready_log_count": report.ready_log_count,
                    "event_count": report.event_count,
                    "observation_count": report.observation_count,
                    "action_count": report.action_count,
                    "failed_action_count": report.failed_action_count,
                    "completed_goal_count": report.completed_goal_count,
                    "failed_goal_count": report.failed_goal_count,
                    "progress_event_count": report.progress_event_count,
                    "object_exploration_count": report.object_exploration_count,
                    "memory_read_count": report.memory_read_count,
                    "memory_write_count": report.memory_write_count,
                    "unbounded_context_cycle_count": report.unbounded_context_cycle_count,
                    "average_axis_scores": report.average_axis_scores,
                    "continual_learning_feedback": continual_learning_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "task-stream-transfer-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        stream_files = getattr(args, "stream_file", []) or []
        if not stream_files:
            print("task-stream-transfer-report requires at least one --stream-file")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_task_stream_transfer_report_from_files(
            stream_files,
            cell_size=getattr(args, "cell_size", 8.0),
        )
        runner.print_task_stream_transfer_report(report)
        task_stream_feedback = runner.task_stream_transfer_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "stream_count": report.stream_count,
                    "ready_stream_count": report.ready_stream_count,
                    "task_count": report.task_count,
                    "reusable_relation_count": report.reusable_relation_count,
                    "reuse_expected_tag_count": report.reuse_expected_tag_count,
                    "reuse_hit_tag_count": report.reuse_hit_tag_count,
                    "reuse_coverage": report.reuse_coverage,
                    "interference_count": report.interference_count,
                    "average_plasticity_gain": report.average_plasticity_gain,
                    "average_stability_gain": report.average_stability_gain,
                    "average_generalization_gain": report.average_generalization_gain,
                    "task_stream_feedback": task_stream_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "task-stream-transfer-gate":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        transfer_reports = getattr(args, "transfer_report", []) or []
        if not transfer_reports:
            print("task-stream-transfer-gate requires at least one --transfer-report")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.build_task_stream_transfer_gate(
            transfer_report_paths=transfer_reports,
            target=getattr(args, "target", "memory_or_skill_promotion"),
            min_plasticity_gain=getattr(args, "min_plasticity_gain", 0.01),
            min_stability_gain=getattr(args, "min_stability_gain", 0.0),
            min_generalization_gain=getattr(args, "min_generalization_gain", 0.0),
            min_reuse_coverage=getattr(args, "min_reuse_coverage", 0.5),
            max_interference_count=getattr(args, "max_interference_count", 0),
            require_heldout=not getattr(args, "no_require_heldout", False),
        )
        runner.print_task_stream_transfer_gate_report(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "memory-read-filter-report":
        from singularity.core.memory import MemorySystem

        current_state = {}
        if getattr(args, "current_state_file", ""):
            with open(args.current_state_file, "r", encoding="utf-8-sig") as f:
                current_state = json.load(f)
        elif getattr(args, "current_state_json", ""):
            current_state = json.loads(args.current_state_json)
        memory = MemorySystem(memory_dir=getattr(args, "memory_dir", "workspace/memory"))
        report = memory.memory_read_filter_report(
            query=getattr(args, "query", ""),
            current_state=current_state or None,
        )
        print("\nMemory Read Filter Report")
        print(f"  memory dir: {getattr(args, 'memory_dir', 'workspace/memory')}")
        print(f"  query: {report['query'] or '-'}")
        print(f"  total entries: {report['total_entries']}")
        print(f"  usable entries: {report['usable_entries']}")
        print(f"  filtered entries: {report['filtered_entries']}")
        for reason, count in sorted(report["filter_reasons"].items()):
            print(f"    - {reason}: {count}")
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "memory-promptware-report":
        from singularity.core.memory import MemorySystem

        current_state = {}
        if getattr(args, "current_state_file", ""):
            with open(args.current_state_file, "r", encoding="utf-8-sig") as f:
                current_state = json.load(f)
        elif getattr(args, "current_state_json", ""):
            current_state = json.loads(args.current_state_json)
        if current_state and not isinstance(current_state, dict):
            print("memory-promptware-report current state must be a JSON object")
            sys.exit(1)

        memory = MemorySystem(memory_dir=getattr(args, "memory_dir", "workspace/memory"))
        report = memory.memory_promptware_report(
            query=getattr(args, "query", ""),
            current_state=current_state or None,
        )
        print("\nMemory Promptware Report")
        print(f"  memory dir: {getattr(args, 'memory_dir', 'workspace/memory')}")
        print(f"  query: {report['query'] or '-'}")
        print(
            f"  flagged entries: {report['flagged_entry_count']}, "
            f"flagged experiences: {report['flagged_experience_count']}"
        )
        for reason, count in sorted(report["reason_counts"].items()):
            print(f"    - {reason}: {count}")
        for entry in report["flagged_entries"]:
            print(f"  - memory {entry['id']} flags={','.join(entry['flags'])} tags={','.join(entry['tags'])}")
        for experience in report["flagged_experiences"]:
            print(f"  - experience {experience['id']} flags={','.join(experience['flags'])} tags={','.join(experience['tags'])}")
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "skill-edit-proposal-report":
        from singularity.core.skill_extractor import build_skill_edit_proposal_report

        report = build_skill_edit_proposal_report(
            queue_path=getattr(args, "queue", "workspace/skills/skill_candidates.jsonl"),
            skill_storage_path=getattr(args, "skill_storage_path", "workspace/skills"),
            discovery_gate_paths=getattr(args, "discovery_skill_gate", []) or [],
            transfer_gate_paths=getattr(args, "task_stream_transfer_gate", []) or [],
            include_all=getattr(args, "include_all", False),
            require_transfer_gate=not getattr(args, "no_require_transfer_gate", False),
            min_score=getattr(args, "min_score", 0.55),
        )
        print("\nSkill Edit Proposal Report")
        print(f"  candidates: {report['candidate_count']}")
        print(
            "  proposals: "
            + ", ".join(f"{key}={value}" for key, value in sorted(report["proposal_counts"].items()))
            if report["proposal_counts"]
            else "  proposals: none"
        )
        print(
            f"  readiness: approved={report['ready_count']}, "
            f"review={report['review_count']}, rejected={report['reject_count']}"
        )
        print(f"  transfer probe required: {report['require_transfer_gate']}")
        for proposal in report["proposals"][:12]:
            marker = "+" if proposal["readiness"] == "approved" else "x" if proposal["readiness"] == "rejected" else "!"
            target = f" -> {proposal['target_skill']}" if proposal.get("target_skill") else ""
            print(
                f"  [{marker}] {proposal['candidate_id']} {proposal['proposal']}{target}: "
                f"{proposal['candidate_name']} score={proposal['score']:.2f}"
            )
            print(f"      {proposal['reason']}")
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "skill-candidates":
        from singularity.core.skill_extractor import SkillCandidateQueue, SkillExtractor
        from singularity.core.skill_library import SkillLibrary

        queue = SkillCandidateQueue(getattr(args, "queue", "workspace/skills/skill_candidates.jsonl"))
        promotion_critic = _promotion_critic_from_args(args)
        if getattr(args, "session", ""):
            lib = SkillLibrary(storage_path=getattr(args, "storage_path", "workspace/skills"))
            extractor = SkillExtractor(
                lib,
                auto_promote=False,
                promotion_critic=promotion_critic,
                discovery_gate_paths=getattr(args, "discovery_skill_gate", []) or [],
                transfer_gate_paths=getattr(args, "task_stream_transfer_gate", []) or [],
            )
            candidates = extractor.extract_skill_candidates(args.session)
            if getattr(args, "causal_summaries", False):
                candidates.extend(extractor.extract_causal_skill_candidates(
                    args.session,
                    min_repeats=getattr(args, "min_causal_repeats", 3),
                    min_value_score=getattr(args, "min_causal_value", 0.65),
                ))
            if getattr(args, "failure_corrections", False):
                candidates.extend(extractor.extract_failure_correction_candidates(
                    args.session,
                    min_failures=getattr(args, "min_failure_repeats", 2),
                    min_value_score=getattr(args, "min_failure_value", 0.55),
                ))
            for candidate in candidates:
                if promotion_critic:
                    report = extractor.validate_candidate_for_promotion(candidate)
                    candidate.signals = {
                        **candidate.signals,
                        "verification_gate": report.gate,
                        "promotion_report": report.to_dict(),
                    }
                queue.enqueue(candidate)
                print(f"queued {candidate.id}: {candidate.name} score={candidate.score}")
            if not candidates:
                print("no promotable candidates found")
            return
        if getattr(args, "approve", ""):
            lib = SkillLibrary(storage_path=getattr(args, "storage_path", "workspace/skills"), persist=True)
            candidate = queue.approve(
                args.approve,
                lib,
                promotion_critic=promotion_critic,
                discovery_gate_paths=getattr(args, "discovery_skill_gate", []) or [],
                transfer_gate_paths=getattr(args, "task_stream_transfer_gate", []) or [],
            )
            if not candidate:
                print(f"candidate not found: {args.approve}")
                sys.exit(1)
            if candidate.review_status != "approved":
                print(f"{candidate.review_status} {candidate.id}: {candidate.name}; reason={candidate.reason}")
                sys.exit(2)
            print(f"approved {candidate.id}: {candidate.name}")
            return
        if getattr(args, "reject", ""):
            candidate = queue.reject(args.reject, getattr(args, "reason", ""))
            if not candidate:
                print(f"candidate not found: {args.reject}")
                sys.exit(1)
            print(f"rejected {candidate.id}: {candidate.name}")
            return

        candidates = queue.all() if getattr(args, "all", False) else queue.pending()
        print(f"\nSkill Candidates ({len(candidates)})\n")
        for candidate in candidates:
            report = candidate.signals.get("promotion_report", {}) if isinstance(candidate.signals, dict) else {}
            gate = report.get("gate", {}) if isinstance(report, dict) else {}
            if not gate and isinstance(candidate.signals, dict):
                gate = candidate.signals.get("verification_gate", {})
            gate_text = ""
            if isinstance(gate, dict) and gate:
                gate_text = f" gate={gate.get('decision', 'allow')}/{gate.get('status', 'unknown')}:{gate.get('reason', '')}"
            discovery_gate = report.get("discovery_gate", {}) if isinstance(report, dict) else {}
            if not discovery_gate and isinstance(candidate.signals, dict):
                discovery_gate = candidate.signals.get("discovery_skill_gate", {})
            discovery_text = ""
            if isinstance(discovery_gate, dict) and discovery_gate.get("required"):
                discovery_text = f" discovery={discovery_gate.get('readiness', 'unknown')}:{discovery_gate.get('reason', '')}"
            transfer_gate = report.get("transfer_gate", {}) if isinstance(report, dict) else {}
            if not transfer_gate and isinstance(candidate.signals, dict):
                transfer_gate = candidate.signals.get("task_stream_transfer_gate", {})
            transfer_text = ""
            if isinstance(transfer_gate, dict) and transfer_gate.get("required"):
                transfer_text = f" transfer={transfer_gate.get('readiness', 'unknown')}:{transfer_gate.get('reason', '')}"
            print(f"- {candidate.id} [{candidate.review_status}] {candidate.name} score={candidate.score}{gate_text}{discovery_text}{transfer_text}: {candidate.description}")
        return

    if args.command == "collab-benchmark":
        from singularity.evaluation.collaboration_benchmark import CollaborationBenchmarkSpec
        from singularity.evaluation.collaboration_runner import CollaborationBenchmarkRunner

        runner = CollaborationBenchmarkRunner(getattr(args, "state_path", "workspace/multiagent/collab_benchmark_state.json"))
        executor_mode = getattr(args, "executor", "simulated")
        spec_path = getattr(args, "spec", "workspace/benchmarks/m7_time_sensitive_shelter.json")
        task_executor = None
        output_path = getattr(args, "output", "")
        run_baseline = getattr(args, "single_agent_baseline", False)
        run_mixed_policy_ablation = getattr(args, "mixed_policy_ablation", False)
        baseline_role_id = getattr(args, "baseline_role_id", "single_agent") or "single_agent"
        baseline_state_path = getattr(args, "baseline_state_path", "") or ""
        if run_mixed_policy_ablation:
            if executor_mode != "agent":
                print("collab-benchmark --mixed-policy-ablation requires --executor agent")
                sys.exit(1)
            if not getattr(args, "execute", False):
                print("collab-benchmark --mixed-policy-ablation requires --execute")
                sys.exit(1)
            if run_baseline:
                print("collab-benchmark --mixed-policy-ablation cannot be combined with --single-agent-baseline")
                sys.exit(1)
            if not (getattr(args, "mixed_policy_patch", []) or []):
                print("collab-benchmark --mixed-policy-ablation requires at least one --mixed-policy-patch")
                sys.exit(1)
        if run_baseline and not (getattr(args, "preflight", False) or getattr(args, "execute", False)):
            print("collab-benchmark --single-agent-baseline requires --preflight or --execute")
            sys.exit(1)
        if run_baseline and not baseline_state_path:
            root, ext = os.path.splitext(runner.state_path)
            baseline_state_path = f"{root}_single_agent_baseline{ext or '.json'}"
        spec = CollaborationBenchmarkSpec.load_json(spec_path)
        schedule_report = runner.analyze_schedule(spec)
        baseline_schedule_report = None
        if run_baseline:
            baseline_schedule_report = runner.analyze_single_agent_baseline_schedule(
                spec,
                baseline_role_id=baseline_role_id,
            )
        output_payload = {
            "type": "collaboration_benchmark",
            "spec_path": spec_path,
            "state_path": runner.state_path,
            "executor": executor_mode,
            "schedule_analysis": runner.schedule_report_to_dict(schedule_report),
            "single_agent_baseline_schedule": runner.schedule_report_to_dict(baseline_schedule_report) if baseline_schedule_report else None,
            "schedule_comparison": runner.compare_schedule_reports(schedule_report, baseline_schedule_report) if baseline_schedule_report else None,
            "execution_schedule_comparison": None,
            "single_agent_baseline_schedule_execution_comparison": None,
            "agent_bridge_launch_plan": None,
            "single_agent_baseline_bridge_launch_plan": None,
            "preflight": None,
            "single_agent_baseline_preflight": None,
            "dry_run": None,
            "execution": None,
            "single_agent_baseline": None,
            "baseline_comparison": None,
        }
        runner.print_schedule_report(schedule_report)
        if baseline_schedule_report:
            runner.print_schedule_report(baseline_schedule_report, title="Single-Agent Baseline Schedule Analysis")
            comparison = runner.compare_schedule_reports(schedule_report, baseline_schedule_report)
            print(f"\nSchedule Comparison")
            print(f"  makespan delta: {comparison['makespan_s_delta']}s")
            print(f"  speedup: {comparison['speedup']}x")
        if executor_mode == "agent":
            from singularity.evaluation.collaboration_executor import AgentCollaborationExecutor

            role_bridge_ports = {}
            for item in getattr(args, "role_bridge_port", []) or []:
                if "=" not in item:
                    print(f"invalid --role-bridge-port value: {item}; expected ROLE=PORT")
                    sys.exit(1)
                role_id, raw_port = (part.strip() for part in item.split("=", 1))
                if not role_id:
                    print(f"invalid --role-bridge-port value: {item}; role cannot be empty")
                    sys.exit(1)
                try:
                    port = int(raw_port)
                except ValueError:
                    print(f"invalid port in --role-bridge-port value: {item}")
                    sys.exit(1)
                if port <= 0:
                    print(f"invalid port in --role-bridge-port value: {item}")
                    sys.exit(1)
                role_bridge_ports[role_id] = port

            def make_agent_executor(mixed_policy_patch_paths):
                return AgentCollaborationExecutor(Config(
                    bot=BotConfig(
                        host=getattr(args, "host", "localhost"),
                        port=getattr(args, "port", 25565),
                        username=getattr(args, "username", "Singularity"),
                        bridge_host=getattr(args, "bridge_host", "127.0.0.1"),
                        bridge_port=getattr(args, "bridge_port", 3000),
                    ),
                    llm=LLMConfig(
                        provider=getattr(args, "llm_provider", "openai"),
                        model=getattr(args, "llm_model", "gpt-4o-mini"),
                        api_key=(
                            getattr(args, "api_key", "")
                            or os.environ.get("SINGULARITY_LLM_API_KEY", "")
                            or os.environ.get("OPENAI_API_KEY", "")
                        ),
                        base_url=getattr(args, "llm_base_url", "") or os.environ.get("SINGULARITY_LLM_BASE_URL", ""),
                    ),
                    enable_goal_critic=getattr(args, "goal_critic", False),
                    enable_skill_memory_context=not getattr(args, "no_skill_memory_context", False),
                    enable_coaching_policy=not getattr(args, "no_coaching_policy", False),
                    coach_style=getattr(args, "coach_style", "") or "",
                    enable_vision_analysis=not getattr(args, "no_vision_analysis", False),
                    enable_visual_action_grounding=not getattr(args, "no_visual_action_grounding", False),
                    enable_screenshot_capture=getattr(args, "capture_screenshots", False),
                    mixed_policy_patch_paths=list(mixed_policy_patch_paths or []),
                    mixed_policy_gate_paths=getattr(args, "mixed_policy_gate", []) or [],
                    self_evolution_feedback_paths=getattr(args, "self_evolution_feedback", []) or [],
                    world_model_feedback_paths=getattr(args, "world_model_feedback", []) or [],
                    world_model_gate_paths=getattr(args, "world_model_gate", []) or [],
                    action_value_feedback_paths=getattr(args, "action_value_feedback", []) or [],
                    action_value_transition_gate_paths=getattr(args, "action_value_transition_gate", []) or [],
                    action_value_transition_evaluator_report_paths=getattr(args, "action_value_transition_evaluator_report", []) or [],
                    skill_memory_quality_feedback_paths=getattr(args, "skill_memory_quality_feedback", []) or [],
                    skill_memory_quality_gate_paths=getattr(args, "skill_memory_quality_gate", []) or [],
                    screenshot_dir=getattr(args, "screenshot_dir", "logs/screenshots"),
                    screenshot_min_interval_s=getattr(args, "screenshot_min_interval", 2.0),
                ), bridge_port_base=getattr(args, "bridge_port_base", 0) or None, role_bridge_ports=role_bridge_ports)

            if run_mixed_policy_ablation:
                from singularity.evaluation.mixed_initiative import build_mixed_initiative_policy_ablation

                patch_paths = getattr(args, "mixed_policy_patch", []) or []
                baseline_executor = make_agent_executor([])
                patched_executor = make_agent_executor(patch_paths)
                bridge_launch_plan = patched_executor.bridge_launch_plan(spec)
                patched_executor.print_bridge_launch_plan(bridge_launch_plan)
                output_payload["type"] = "collaboration_mixed_policy_ablation"
                output_payload["mixed_policy_patch_paths"] = list(patch_paths)
                output_payload["policy_decision_report"] = build_mixed_initiative_policy_ablation(
                    patch_paths=patch_paths
                ).to_dict()
                output_payload["agent_bridge_launch_plan"] = patched_executor.bridge_launch_plan_to_dict(bridge_launch_plan)
                if getattr(args, "preflight", False):
                    bridge_report = patched_executor.preflight_bridges(spec)
                    patched_executor.print_bridge_preflight_report(bridge_report)
                    output_payload["preflight"] = patched_executor.bridge_preflight_report_to_dict(bridge_report)
                    if not bridge_report.ok:
                        runner.save_json_report(output_payload, output_path)
                        sys.exit(1)

                root, ext = os.path.splitext(runner.state_path)
                baseline_mixed_state_path = f"{root}_mixed_policy_baseline{ext or '.json'}"
                patched_mixed_state_path = f"{root}_mixed_policy_patched{ext or '.json'}"
                baseline_mixed_runner = CollaborationBenchmarkRunner(baseline_mixed_state_path)
                patched_mixed_runner = CollaborationBenchmarkRunner(patched_mixed_state_path)
                try:
                    baseline_result = baseline_mixed_runner.execute(
                        spec,
                        executor=baseline_executor,
                        reset=not getattr(args, "no_reset", False),
                        max_steps=getattr(args, "max_steps", 0) or None,
                    )
                    patched_result = patched_mixed_runner.execute(
                        spec,
                        executor=patched_executor,
                        reset=not getattr(args, "no_reset", False),
                        max_steps=getattr(args, "max_steps", 0) or None,
                    )
                finally:
                    baseline_executor.close()
                    patched_executor.close()

                print("\nMixed Policy Baseline")
                baseline_mixed_runner.print_execution_report(baseline_result)
                baseline_schedule_comparison = baseline_mixed_runner.compare_schedule_to_execution(
                    schedule_report,
                    baseline_result,
                )
                baseline_mixed_runner.print_schedule_execution_comparison(
                    baseline_schedule_comparison,
                    title="Baseline Schedule vs Execution",
                )
                print("\nMixed Policy Patched")
                patched_mixed_runner.print_execution_report(patched_result)
                patched_schedule_comparison = patched_mixed_runner.compare_schedule_to_execution(
                    schedule_report,
                    patched_result,
                )
                patched_mixed_runner.print_schedule_execution_comparison(
                    patched_schedule_comparison,
                    title="Patched Schedule vs Execution",
                )
                mixed_policy_comparison = runner.compare_mixed_policy_execution_reports(
                    baseline_result,
                    patched_result,
                )
                print("\nMixed Policy Execution Comparison")
                print(f"  ok delta: {mixed_policy_comparison['ok_delta']}")
                print(f"  completed delta: {mixed_policy_comparison['completed_tasks_delta']}")
                print(f"  failed delta: {mixed_policy_comparison['failed_tasks_delta']}")
                print(f"  elapsed delta: {mixed_policy_comparison['total_elapsed_s_delta']}s")
                baseline_control = mixed_policy_comparison.get("baseline_control_policy", {})
                patched_control = mixed_policy_comparison.get("patched_control_policy", {})
                print(f"  control changed: {mixed_policy_comparison.get('control_policy_changed', False)}")
                print(f"  baseline control: {baseline_control.get('preferred_control_counts', {})}")
                print(f"  patched control: {patched_control.get('preferred_control_counts', {})}, fallbacks={patched_control.get('fallback_count', 0)}")
                output_payload["baseline_execution"] = baseline_mixed_runner.execution_report_to_dict(baseline_result)
                output_payload["patched_execution"] = patched_mixed_runner.execution_report_to_dict(patched_result)
                output_payload["baseline_schedule_execution_comparison"] = baseline_mixed_runner.schedule_execution_comparison_to_dict(
                    baseline_schedule_comparison
                )
                output_payload["patched_schedule_execution_comparison"] = patched_mixed_runner.schedule_execution_comparison_to_dict(
                    patched_schedule_comparison
                )
                output_payload["mixed_policy_comparison"] = mixed_policy_comparison
                runner.save_json_report(output_payload, output_path)
                if not baseline_result.ok or not patched_result.ok:
                    sys.exit(1)
                return

            task_executor = make_agent_executor(getattr(args, "mixed_policy_patch", []) or [])
            bridge_launch_plan = task_executor.bridge_launch_plan(spec)
            task_executor.print_bridge_launch_plan(bridge_launch_plan)
            output_payload["agent_bridge_launch_plan"] = task_executor.bridge_launch_plan_to_dict(bridge_launch_plan)
            if run_baseline:
                baseline_spec = runner.single_agent_baseline_spec(spec, baseline_role_id=baseline_role_id)
                baseline_bridge_launch_plan = task_executor.bridge_launch_plan(baseline_spec)
                task_executor.print_bridge_launch_plan(
                    baseline_bridge_launch_plan,
                    title="Single-Agent Baseline Bridge Launch Plan",
                )
                output_payload["single_agent_baseline_bridge_launch_plan"] = task_executor.bridge_launch_plan_to_dict(
                    baseline_bridge_launch_plan
                )

        if getattr(args, "preflight", False):
            if not task_executor:
                print("collab-benchmark --preflight currently checks Agent executor bridges; use --executor agent")
                sys.exit(1)
            bridge_report = task_executor.preflight_bridges(spec)
            task_executor.print_bridge_preflight_report(bridge_report)
            output_payload["preflight"] = task_executor.bridge_preflight_report_to_dict(bridge_report)
            if not bridge_report.ok:
                runner.save_json_report(output_payload, output_path)
                sys.exit(1)
            if run_baseline:
                baseline_spec = runner.single_agent_baseline_spec(spec, baseline_role_id=baseline_role_id)
                baseline_bridge_report = task_executor.preflight_bridges(baseline_spec)
                print("\nSingle-Agent Baseline")
                task_executor.print_bridge_preflight_report(baseline_bridge_report)
                output_payload["single_agent_baseline_preflight"] = task_executor.bridge_preflight_report_to_dict(baseline_bridge_report)
                if not baseline_bridge_report.ok:
                    runner.save_json_report(output_payload, output_path)
                    sys.exit(1)
            if not getattr(args, "execute", False):
                runner.save_json_report(output_payload, output_path)
                return

        if getattr(args, "execute", False) or executor_mode != "simulated":
            try:
                result = runner.execute(
                    spec,
                    executor=task_executor,
                    reset=not getattr(args, "no_reset", False),
                    max_steps=getattr(args, "max_steps", 0) or None,
                )
                baseline_report = None
                if run_baseline:
                    baseline_runner = CollaborationBenchmarkRunner(baseline_state_path)
                    baseline_report = baseline_runner.run_single_agent_baseline(
                        spec,
                        executor=task_executor,
                        baseline_role_id=baseline_role_id,
                        reset=True,
                        max_steps=getattr(args, "max_steps", 0) or None,
                    )
            finally:
                if task_executor and hasattr(task_executor, "close"):
                    task_executor.close()
            runner.print_execution_report(result)
            output_payload["execution"] = runner.execution_report_to_dict(result)
            execution_schedule_comparison = runner.compare_schedule_to_execution(schedule_report, result)
            runner.print_schedule_execution_comparison(execution_schedule_comparison)
            output_payload["execution_schedule_comparison"] = runner.schedule_execution_comparison_to_dict(execution_schedule_comparison)
            if run_baseline and baseline_report is not None:
                print("\nSingle-Agent Baseline")
                baseline_runner.print_execution_report(baseline_report)
                output_payload["single_agent_baseline"] = baseline_runner.execution_report_to_dict(baseline_report)
                output_payload["baseline_comparison"] = runner.compare_execution_reports(result, baseline_report)
                baseline_schedule_execution_comparison = runner.compare_schedule_to_execution(
                    baseline_schedule_report,
                    baseline_report,
                )
                runner.print_schedule_execution_comparison(
                    baseline_schedule_execution_comparison,
                    title="Single-Agent Schedule vs Execution",
                )
                output_payload["single_agent_baseline_schedule_execution_comparison"] = runner.schedule_execution_comparison_to_dict(
                    baseline_schedule_execution_comparison
                )
            runner.save_json_report(output_payload, output_path)
            if not result.ok:
                sys.exit(1)
            if run_baseline and baseline_report is not None and not baseline_report.ok:
                sys.exit(1)
            return
        result = runner.prepare(spec, reset=not getattr(args, "no_reset", False))
        runner.print_result(result)
        output_payload["dry_run"] = runner.run_result_to_dict(result)
        runner.save_json_report(output_payload, output_path)
        if not result.ok:
            sys.exit(1)
        return

    if args.command == "scheduling-ablation":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        runner = BenchmarkRunner(Config())
        session_logs = getattr(args, "session_log", []) or []
        if session_logs:
            report = runner.run_scheduling_ablation_from_logs(
                session_logs,
                max_cases_per_log=getattr(args, "max_cases_per_log", 20),
                min_value_score=getattr(args, "min_value_score", 0.55),
            )
        else:
            report = runner.run_scheduling_ablation()
        runner.print_scheduling_ablation_report(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "changed_count": report.changed_count,
                    "helped_count": report.helped_count,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "promotion-review-ablation":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("promotion-review-ablation requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config(llm=_llm_config_from_args(args)))
        manual_labels = runner.load_promotion_review_labels(getattr(args, "label_file", "")) if getattr(args, "label_file", "") else {}
        report = runner.run_promotion_review_ablation_from_logs(
            session_logs,
            promotion_critic=_promotion_critic_from_args(args),
            include_causal_summaries=getattr(args, "causal_summaries", False),
            include_failure_corrections=getattr(args, "failure_corrections", False),
            manual_labels=manual_labels,
        )
        runner.print_promotion_review_ablation_report(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "candidate_count": report.candidate_count,
                    "changed_count": report.changed_count,
                    "visual_helped_count": report.visual_helped_count,
                    "api_visual_helped_count": report.api_visual_helped_count,
                    "screenshot_vlm_helped_count": report.screenshot_vlm_helped_count,
                    "screenshot_vlm_added_value_count": report.screenshot_vlm_added_value_count,
                    "manual_labeled_count": report.manual_labeled_count,
                    "deterministic_manual_match_count": report.deterministic_manual_match_count,
                    "api_visual_manual_match_count": report.api_visual_manual_match_count,
                    "screenshot_vlm_manual_match_count": report.screenshot_vlm_manual_match_count,
                    "screenshot_vlm_manual_improvement_count": report.screenshot_vlm_manual_improvement_count,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "goal-verification-ablation":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("goal-verification-ablation requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config(llm=_llm_config_from_args(args)))
        manual_labels = runner.load_goal_verification_labels(getattr(args, "label_file", "")) if getattr(args, "label_file", "") else {}
        report = runner.run_goal_verification_ablation_from_logs(
            session_logs,
            goal_critic=_goal_critic_from_args(args),
            manual_labels=manual_labels,
        )
        runner.print_goal_verification_ablation_report(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "goal_count": report.goal_count,
                    "changed_count": report.changed_count,
                    "visual_helped_count": report.visual_helped_count,
                    "api_visual_helped_count": report.api_visual_helped_count,
                    "screenshot_vlm_helped_count": report.screenshot_vlm_helped_count,
                    "screenshot_vlm_added_value_count": report.screenshot_vlm_added_value_count,
                    "manual_labeled_count": report.manual_labeled_count,
                    "deterministic_manual_match_count": report.deterministic_manual_match_count,
                    "api_visual_manual_match_count": report.api_visual_manual_match_count,
                    "screenshot_vlm_manual_match_count": report.screenshot_vlm_manual_match_count,
                    "screenshot_vlm_manual_improvement_count": report.screenshot_vlm_manual_improvement_count,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "review-label-template":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("review-label-template requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        templates = runner.build_review_label_templates_from_logs(
            session_logs,
            mode=getattr(args, "mode", "both"),
            include_causal_summaries=getattr(args, "causal_summaries", False),
            include_failure_corrections=getattr(args, "failure_corrections", False),
        )
        lines = [json.dumps(template, ensure_ascii=False, default=str) for template in templates]
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                for line in lines:
                    f.write(line + "\n")
            print(f"Review label template saved to {args.output} ({len(lines)} records)")
        else:
            for line in lines:
                print(line)
        return

    if args.command == "review-label-validate":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        runner = BenchmarkRunner(Config())
        report = runner.validate_review_labels(getattr(args, "label_file", ""))
        runner.print_review_label_validation_report(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "label_path": report.label_path,
                    "ok": report.ok,
                    "label_count": report.label_count,
                    "ok_count": report.ok_count,
                    "error_count": report.error_count,
                    "invalid_readiness_count": report.invalid_readiness_count,
                    "unknown_readiness_count": report.unknown_readiness_count,
                    "screenshot_unverified_count": report.screenshot_unverified_count,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if not report.ok:
            sys.exit(1)
        return

    if args.command == "visual-trace-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("visual-trace-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_visual_trace_report_from_logs(
            session_logs,
            include_causal_summaries=getattr(args, "causal_summaries", False),
            include_failure_corrections=getattr(args, "failure_corrections", False),
        )
        runner.print_visual_trace_report(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "log_count": report.log_count,
                    "ready_log_count": report.ready_log_count,
                    "screenshot_log_count": report.screenshot_log_count,
                    "raw_screenshot_log_count": report.raw_screenshot_log_count,
                    "missing_screenshot_count": report.missing_screenshot_count,
                    "invalid_screenshot_count": report.invalid_screenshot_count,
                    "goal_count": report.goal_count,
                    "goals_with_visual_evidence_count": report.goals_with_visual_evidence_count,
                    "promotion_candidate_count": report.promotion_candidate_count,
                    "promotion_candidates_with_visual_evidence_count": report.promotion_candidates_with_visual_evidence_count,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "exploration-trace-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("exploration-trace-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_exploration_trace_report_from_logs(session_logs)
        runner.print_exploration_trace_report(report)
        curriculum_feedback = runner.exploration_curriculum_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "log_count": report.log_count,
                    "ready_log_count": report.ready_log_count,
                    "observation_count": report.observation_count,
                    "goal_count": report.goal_count,
                    "completed_goal_count": report.completed_goal_count,
                    "failed_goal_count": report.failed_goal_count,
                    "failed_action_count": report.failed_action_count,
                    "logs_with_movement_count": report.logs_with_movement_count,
                    "visual_observation_count": report.visual_observation_count,
                    "hostile_encounter_count": report.hostile_encounter_count,
                    "unique_block_type_count": report.unique_block_type_count,
                    "unique_entity_type_count": report.unique_entity_type_count,
                    "unique_resource_type_count": report.unique_resource_type_count,
                    "curriculum_feedback": curriculum_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "world-model-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("world-model-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_world_model_report_from_logs(
            session_logs,
            cell_size=getattr(args, "cell_size", 8.0),
            limit=getattr(args, "limit", 12),
        )
        runner.print_world_model_report(report)
        world_model_feedback = runner.world_model_curriculum_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "log_count": report.log_count,
                    "ready_log_count": report.ready_log_count,
                    "observation_count": report.observation_count,
                    "unique_cell_count": report.unique_cell_count,
                    "frontier_count": report.frontier_count,
                    "resource_hotspot_count": report.resource_hotspot_count,
                    "danger_cell_count": report.danger_cell_count,
                    "world_model_feedback": world_model_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "world-model-feedback-gate":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        report_paths = getattr(args, "world_model_report", []) or []
        if not report_paths:
            print("world-model-feedback-gate requires at least one --world-model-report")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.build_world_model_feedback_gate(
            world_model_report_paths=report_paths,
            target=getattr(args, "target", "world_model_curriculum_feedback"),
            min_ready_logs=getattr(args, "min_ready_logs", 1),
            min_frontiers=getattr(args, "min_frontiers", 1),
            min_actionable_items=getattr(args, "min_actionable_items", 1),
        )
        runner.print_world_model_feedback_gate_report(report)
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "self-evolution-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("self-evolution-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_self_evolution_report_from_logs(session_logs)
        runner.print_self_evolution_report(report)
        self_evolution_feedback = runner.self_evolution_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "log_count": report.log_count,
                    "ready_log_count": report.ready_log_count,
                    "observation_count": report.observation_count,
                    "action_count": report.action_count,
                    "failed_action_count": report.failed_action_count,
                    "progress_signal_count": report.progress_signal_count,
                    "regression_signal_count": report.regression_signal_count,
                    "stagnation_signal_count": report.stagnation_signal_count,
                    "repeated_failure_count": report.repeated_failure_count,
                    "no_progress_success_count": report.no_progress_success_count,
                    "repeated_success_loop_count": report.repeated_success_loop_count,
                    "blocked_plan_count": report.blocked_plan_count,
                    "empty_plan_count": report.empty_plan_count,
                    "zero_action_failure_count": report.zero_action_failure_count,
                    "relative_reward_delta": report.relative_reward_delta,
                    "self_evolution_feedback": self_evolution_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "plan-action-compliance-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("plan-action-compliance-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_plan_action_compliance_report_from_logs(session_logs)
        runner.print_plan_action_compliance_report(report)
        plan_action_feedback = runner.plan_action_compliance_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "log_count": report.log_count,
                    "ready_log_count": report.ready_log_count,
                    "plan_count": report.plan_count,
                    "action_count": report.action_count,
                    "planned_action_count": report.planned_action_count,
                    "ordered_match_count": report.ordered_match_count,
                    "unordered_match_count": report.unordered_match_count,
                    "missing_planned_action_count": report.missing_planned_action_count,
                    "unplanned_action_count": report.unplanned_action_count,
                    "order_violation_count": report.order_violation_count,
                    "empty_plan_count": report.empty_plan_count,
                    "blocked_plan_count": report.blocked_plan_count,
                    "plan_follow_score": report.plan_follow_score,
                    "action_precision": report.action_precision,
                    "compliance_score": report.compliance_score,
                    "plan_action_feedback": plan_action_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "terminal-commitment-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("terminal-commitment-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_terminal_commitment_report_from_logs(session_logs)
        runner.print_terminal_commitment_report(report)
        terminal_commitment_feedback = runner.terminal_commitment_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "goal_count": report.goal_count,
                    "ready_goal_count": report.ready_goal_count,
                    "world_complete_count": report.world_complete_count,
                    "terminal_complete_count": report.terminal_complete_count,
                    "verified_success_count": report.verified_success_count,
                    "unsupported_commitment_count": report.unsupported_commitment_count,
                    "post_attainment_drift_count": report.post_attainment_drift_count,
                    "missed_execution_count": report.missed_execution_count,
                    "unknown_world_count": report.unknown_world_count,
                    "world_completion_score": report.world_completion_score,
                    "terminal_commitment_score": report.terminal_commitment_score,
                    "unsupported_commitment_rate": report.unsupported_commitment_rate,
                    "post_attainment_drift_rate": report.post_attainment_drift_rate,
                    "terminal_commitment_feedback": terminal_commitment_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "action-verification-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("action-verification-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_action_verification_report_from_logs(session_logs)
        runner.print_action_verification_report(report)
        action_verification_feedback = runner.action_verification_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "log_count": report.log_count,
                    "ready_log_count": report.ready_log_count,
                    "action_count": report.action_count,
                    "verified_action_count": report.verified_action_count,
                    "accepted_action_count": report.accepted_action_count,
                    "review_action_count": report.review_action_count,
                    "rejected_action_count": report.rejected_action_count,
                    "rejected_success_count": report.rejected_success_count,
                    "failed_without_reject_count": report.failed_without_reject_count,
                    "reject_rate": report.reject_rate,
                    "review_rate": report.review_rate,
                    "action_verification_feedback": action_verification_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "action-candidate-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("action-candidate-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_action_candidate_report_from_logs(session_logs)
        runner.print_action_candidate_report(report)
        action_candidate_feedback = runner.action_candidate_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "log_count": report.log_count,
                    "ready_log_count": report.ready_log_count,
                    "action_count": report.action_count,
                    "original_reject_count": report.original_reject_count,
                    "changed_selection_count": report.changed_selection_count,
                    "repaired_reject_count": report.repaired_reject_count,
                    "unchanged_reject_count": report.unchanged_reject_count,
                    "selection_change_rate": report.selection_change_rate,
                    "repaired_reject_rate": report.repaired_reject_rate,
                    "action_candidate_feedback": action_candidate_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "action-value-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("action-value-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_action_value_report_from_logs(session_logs)
        runner.print_action_value_report(report)
        action_value_feedback = runner.action_value_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "log_count": report.log_count,
                    "ready_log_count": report.ready_log_count,
                    "action_count": report.action_count,
                    "success_count": report.success_count,
                    "failure_count": report.failure_count,
                    "unknown_outcome_count": report.unknown_outcome_count,
                    "signature_count": report.signature_count,
                    "success_rate": report.success_rate,
                    "failure_rate": report.failure_rate,
                    "failure_correction_pair_count": report.failure_correction_pair_count,
                    "action_value_feedback": action_value_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "action-value-transition-gate":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        action_value_reports = getattr(args, "action_value_report", []) or []
        if not action_value_reports:
            print("action-value-transition-gate requires at least one --action-value-report")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.build_action_value_transition_gate(
            action_value_report_paths=action_value_reports,
            target=getattr(args, "target", "action_value_transition_feedback"),
            min_trusted_items=getattr(args, "min_trusted_items", 1),
            min_trusted_transitions=getattr(args, "min_trusted_transitions", 1),
            min_transition_confidence=getattr(args, "min_transition_confidence", 0.75),
            max_low_confidence_rate=getattr(args, "max_low_confidence_rate", 0.25),
            max_item_low_confidence_rate=getattr(args, "max_item_low_confidence_rate", 0.25),
        )
        runner.print_action_value_transition_gate_report(report)
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if report.get("readiness") in {"rejected", "error"}:
            sys.exit(1)
        return

    if args.command == "action-value-transition-evaluator-report":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        action_value_reports = getattr(args, "action_value_report", []) or []
        session_logs = getattr(args, "session_log", []) or []
        if not action_value_reports and not session_logs:
            print("action-value-transition-evaluator-report requires at least one --action-value-report or --session-log")
            sys.exit(1)
        evaluator = None
        if getattr(args, "llm_evaluator", False):
            from singularity.llm.provider import LLMProvider
            evaluator = LLMProvider(_llm_config_from_args(args))
        runner = BenchmarkRunner(Config(llm=_llm_config_from_args(args)))
        report = runner.build_action_value_transition_evaluator_report(
            action_value_report_paths=action_value_reports,
            session_log_paths=session_logs,
            evaluator=evaluator,
            limit=getattr(args, "limit", 40),
            min_transition_confidence=getattr(args, "min_transition_confidence", 0.75),
            min_evaluator_confidence=getattr(args, "min_evaluator_confidence", 0.65),
            min_evaluated_transitions=getattr(args, "min_evaluated_transitions", 1),
            min_label_agreement_rate=getattr(args, "min_label_agreement_rate", 0.75),
            max_avg_score_delta=getattr(args, "max_avg_score_delta", 0.25),
            max_large_score_delta_rate=getattr(args, "max_large_score_delta_rate", 0.25),
        )
        runner.print_action_value_transition_evaluator_report(report)
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if report.get("readiness") in {"rejected", "error"}:
            sys.exit(1)
        return

    if args.command == "self-evolution-gate":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        self_evolution_reports = getattr(args, "self_evolution_report", []) or []
        verifier_reports = getattr(args, "verifier_report", []) or []
        counterexample_reports = getattr(args, "counterexample_report", []) or []
        if not self_evolution_reports and not verifier_reports and not counterexample_reports:
            print("self-evolution-gate requires at least one evidence report")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.build_self_evolution_plan_repair_gate(
            self_evolution_report_paths=self_evolution_reports,
            verifier_report_paths=verifier_reports,
            counterexample_report_paths=counterexample_reports,
        )
        runner.print_self_evolution_gate_report(report)
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if report.get("readiness") in {"rejected", "error"}:
            sys.exit(1)
        return

    if args.command == "discovery-application-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("discovery-application-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_discovery_application_report_from_logs(session_logs)
        runner.print_discovery_application_report(report)
        discovery_feedback = runner.discovery_application_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "log_count": report.log_count,
                    "ready_log_count": report.ready_log_count,
                    "goal_count": report.goal_count,
                    "completed_goal_count": report.completed_goal_count,
                    "hypothesis_count": report.hypothesis_count,
                    "experiment_count": report.experiment_count,
                    "consolidation_count": report.consolidation_count,
                    "application_count": report.application_count,
                    "successful_application_count": report.successful_application_count,
                    "failed_application_count": report.failed_application_count,
                    "experiment_action_count": report.experiment_action_count,
                    "failed_experiment_action_count": report.failed_experiment_action_count,
                    "causal_memory_write_count": report.causal_memory_write_count,
                    "complete_loop_count": report.complete_loop_count,
                    "discovery_feedback": discovery_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "action-abstraction-report":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("action-abstraction-report requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config())
        report = runner.run_action_abstraction_report_from_logs(session_logs)
        runner.print_action_abstraction_report(report)
        action_abstraction_feedback = runner.action_abstraction_feedback(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "log_count": report.log_count,
                    "action_count": report.action_count,
                    "failed_action_count": report.failed_action_count,
                    "unknown_canonical_count": report.unknown_canonical_count,
                    "failed_mapping_count": report.failed_mapping_count,
                    "desktop_planned_count": report.desktop_planned_count,
                    "low_level_candidate_count": report.low_level_candidate_count,
                    "action_abstraction_feedback": action_abstraction_feedback,
                    "errors": report.errors,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "mixed-initiative-report":
        from singularity.evaluation.mixed_initiative import build_mixed_initiative_report

        def load_json_arg(json_text: str = "", json_path: str = "") -> dict:
            if json_path:
                with open(json_path, "r", encoding="utf-8-sig") as f:
                    return json.load(f)
            if json_text:
                return json.loads(json_text)
            return {}

        context = load_json_arg(
            getattr(args, "context_json", ""),
            getattr(args, "context_file", ""),
        )
        evidence = None
        if getattr(args, "evidence_json", "") or getattr(args, "evidence_file", ""):
            evidence = load_json_arg(
                getattr(args, "evidence_json", ""),
                getattr(args, "evidence_file", ""),
            )
        report = build_mixed_initiative_report(
            getattr(args, "goal", "Collect 20 oak logs"),
            template_id=getattr(args, "template", "auto"),
            context=context,
            evidence=evidence,
        )
        plan = report["plan"]
        print("\nMixed-Initiative Task Report")
        print(f"  template: {plan['template_id']} ({plan['category']})")
        print(f"  goal: {plan['goal']}")
        print(f"  preview: {plan['plan_preview']}")
        if plan["clarifying_questions"]:
            print(f"  clarification: {plan['clarifying_questions'][0]}")
        print(f"  unbound slots: {plan['unbound_slot_count']}")
        for subtask in plan["subtasks"]:
            marker = "?" if subtask["missing_parameters"] else "+"
            print(f"  [{marker}] {subtask['id']}: {subtask['name']}")
            if subtask["bound_parameters"]:
                params = ", ".join(f"{key}={value}" for key, value in subtask["bound_parameters"].items())
                print(f"      params: {params}")
            if subtask["missing_parameters"]:
                print(f"      missing: {', '.join(subtask['missing_parameters'])}")
            if subtask["clarifying_question"]:
                print(f"      question: {subtask['clarifying_question']}")
        if report["validation"]:
            summary = report["validation_summary"]
            print(
                "  validation: "
                f"passed={summary['passed']}, failed={summary['failed']}, "
                f"invalid={summary['invalid']}, unknown={summary['unknown']}"
            )
            for result in report["validation"]:
                marker = "+" if result["success"] else "x" if result["status"] == "invalid" else "-"
                print(f"  [{marker}] {result['subtask_id']}: {result['status']}")
                if result["evidence"]:
                    print(f"      evidence: {'; '.join(result['evidence'][:3])}")
                if result["missing"]:
                    print(f"      missing: {'; '.join(result['missing'][:3])}")
                if result["policy_violations"]:
                    details = [violation["detail"] for violation in result["policy_violations"][:3]]
                    print(f"      policy: {'; '.join(details)}")
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "mixed-initiative-variant-report":
        from singularity.evaluation.mixed_initiative import build_mixed_initiative_variant_report

        report = build_mixed_initiative_variant_report(
            case_paths=getattr(args, "case_file", []) or [],
            include_builtin=not getattr(args, "no_builtins", False),
            template_id=getattr(args, "template", "auto"),
        )
        print("\nMixed-Initiative Variant Report")
        print(f"  cases: {report.case_count}")
        print(f"  fully passed: {report.fully_passed_count}/{report.case_count}")
        print(f"  template matches: {report.template_match_count}/{report.case_count}")
        print(f"  slot matches: {report.slot_match_count}/{report.case_count}")
        print(f"  validation success: {report.validation_success_count}/{report.validation_checked_count}")
        print(f"  clarifications: {report.clarification_count}")
        for case in report.cases:
            marker = "+" if case.fully_passed else "x"
            expected = case.expected_template_id or "<none>"
            print(f"  [{marker}] {case.id}: {case.goal}")
            print(f"      template: expected={expected}, actual={case.actual_template_id}")
            if case.slot_mismatches:
                print(f"      slot mismatches: {'; '.join(case.slot_mismatches[:3])}")
            if case.needs_clarification:
                print(f"      clarification needed, unbound_slots={case.unbound_slot_count}")
            if case.validation_checked:
                status = "passed" if case.validation_success else "failed"
                print(
                    f"      validation: {status}, passed={case.validation_passed_count}, "
                    f"failed={case.validation_failed_count}, invalid={case.validation_invalid_count}, "
                    f"unknown={case.validation_unknown_count}"
                )
        for error in report.errors:
            print(f"  error: {error}")
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "mixed-initiative-review-queue":
        from singularity.evaluation.mixed_initiative import build_mixed_initiative_review_queue

        trace_reports = getattr(args, "trace_report", []) or []
        session_logs = getattr(args, "session_log", []) or []
        if not trace_reports and not session_logs:
            print("mixed-initiative-review-queue requires --trace-report or --session-log")
            sys.exit(1)
        report = build_mixed_initiative_review_queue(
            trace_report_paths=trace_reports,
            session_log_paths=session_logs,
            template_id=getattr(args, "template", "auto"),
        )
        print("\nMixed-Initiative Review Queue")
        print(f"  items: {report.item_count}")
        print(f"  high priority: {report.high_priority_count}")
        if report.decision_counts:
            parts = [f"{key}={value}" for key, value in sorted(report.decision_counts.items())]
            print(f"  decisions: {', '.join(parts)}")
        for item in report.items:
            print(f"  [{item.priority}] {item.id}")
            print(f"      {item.target_type}:{item.target_id} -> {item.decision}")
            if item.source_goals:
                print(f"      examples: {', '.join(item.source_goals[:3])}")
            if item.action_items:
                print(f"      next: {item.action_items[0]}")
        for error in report.errors:
            print(f"  error: {error}")
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
            print(f"\nQueue saved to {args.output}")
        return

    if args.command == "mixed-initiative-review-plan":
        from singularity.evaluation.mixed_initiative import build_mixed_initiative_review_experiment_plan

        review_queues = getattr(args, "review_queue", []) or []
        trace_reports = getattr(args, "trace_report", []) or []
        session_logs = getattr(args, "session_log", []) or []
        if not review_queues and not trace_reports and not session_logs:
            print("mixed-initiative-review-plan requires --review-queue, --trace-report, or --session-log")
            sys.exit(1)
        report = build_mixed_initiative_review_experiment_plan(
            review_queue_paths=review_queues,
            trace_report_paths=trace_reports,
            session_log_paths=session_logs,
            template_id=getattr(args, "template", "auto"),
        )
        print("\nMixed-Initiative Review Experiment Plan")
        print(f"  cases: {report.case_count}")
        print(f"  ready: {report.ready_count}")
        print(f"  high priority: {report.high_priority_count}")
        if report.route_counts:
            parts = [f"{key}={value}" for key, value in sorted(report.route_counts.items())]
            print(f"  routes: {', '.join(parts)}")
        for case in report.cases:
            marker = "+" if case.ready else "!"
            print(f"  {marker} [{case.priority}] {case.id}")
            print(f"      {case.route}: {case.target_type}:{case.target_id} -> {case.decision}")
            if case.source_goals:
                print(f"      examples: {', '.join(case.source_goals[:3])}")
            if case.missing_inputs:
                print(f"      missing: {', '.join(case.missing_inputs)}")
            if case.recommended_commands:
                print(f"      command: {case.recommended_commands[0]}")
        for error in report.errors:
            print(f"  error: {error}")
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
            print(f"\nExperiment plan saved to {args.output}")
        return

    if args.command == "mixed-initiative-review-label-template":
        from singularity.evaluation.mixed_initiative import build_mixed_initiative_review_label_templates

        review_plans = getattr(args, "review_plan", []) or []
        review_queues = getattr(args, "review_queue", []) or []
        trace_reports = getattr(args, "trace_report", []) or []
        session_logs = getattr(args, "session_log", []) or []
        if not review_plans and not review_queues and not trace_reports and not session_logs:
            print("mixed-initiative-review-label-template requires --review-plan, --review-queue, --trace-report, or --session-log")
            sys.exit(1)
        templates = build_mixed_initiative_review_label_templates(
            review_plan_paths=review_plans,
            review_queue_paths=review_queues,
            trace_report_paths=trace_reports,
            session_log_paths=session_logs,
            template_id=getattr(args, "template", "auto"),
        )
        lines = [json.dumps(template, ensure_ascii=False, default=str) for template in templates]
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                for line in lines:
                    f.write(line + "\n")
            print(f"Mixed-initiative review label template saved to {args.output} ({len(lines)} records)")
        else:
            for line in lines:
                print(line)
        return

    if args.command == "mixed-initiative-review-label-validate":
        from singularity.evaluation.mixed_initiative import validate_mixed_initiative_review_labels

        label_file = getattr(args, "label_file", "")
        if not label_file:
            print("mixed-initiative-review-label-validate requires --label-file")
            sys.exit(1)
        report = validate_mixed_initiative_review_labels(
            label_file,
            review_plan_paths=getattr(args, "review_plan", []) or [],
        )
        print("\nMixed-Initiative Review Label Validation")
        print(f"  labels: {report.ok_count}/{report.label_count} ok")
        print(f"  approved: {report.approved_count}")
        print(f"  rejected: {report.rejected_count}")
        print(f"  unknown: {report.unknown_count}")
        print(f"  executable approved cases: {report.executable_count}")
        if report.approved_route_counts:
            parts = [f"{key}={value}" for key, value in sorted(report.approved_route_counts.items())]
            print(f"  approved routes: {', '.join(parts)}")
        for case in report.cases:
            marker = "+" if case.ok else "x"
            label = case.case_id or case.queue_item_id or case.target_id or f"record-{case.index}"
            print(f"  [{marker}] {case.index} {case.route or 'unknown_route'}: {label}")
            print(f"      readiness={case.readiness or 'invalid'}, commands={len(case.recommended_commands)}")
            if case.errors:
                print(f"      errors: {', '.join(case.errors)}")
            if case.warnings:
                print(f"      warnings: {', '.join(case.warnings)}")
        for error in report.errors:
            print(f"  error: {error}")
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if not report.ok:
            sys.exit(1)
        return

    if args.command == "mixed-initiative-review-execute":
        from singularity.evaluation.mixed_initiative import execute_mixed_initiative_review_labels

        label_file = getattr(args, "label_file", "")
        if not label_file:
            print("mixed-initiative-review-execute requires --label-file")
            sys.exit(1)
        report = execute_mixed_initiative_review_labels(
            label_file,
            review_plan_paths=getattr(args, "review_plan", []) or [],
            output_dir=getattr(args, "output_dir", "") or "",
            dry_run=getattr(args, "dry_run", False),
        )
        print("\nMixed-Initiative Review Execution")
        print(f"  dry run: {report.dry_run}")
        print(f"  cases: {report.case_count}")
        print(f"  executed: {report.executed_count}")
        print(f"  dry-run cases: {report.dry_run_count}")
        print(f"  skipped: {report.skipped_count}")
        print(f"  failed: {report.failed_count}")
        if report.route_counts:
            parts = [f"{key}={value}" for key, value in sorted(report.route_counts.items())]
            print(f"  routes: {', '.join(parts)}")
        for case in report.cases:
            marker = "+" if case.status in {"executed", "dry_run"} else ("-" if case.status == "skipped" else "x")
            print(f"  [{marker}] {case.status} {case.route}: {case.case_id or case.target_id}")
            if case.artifact_summaries:
                summary = ", ".join(f"{key}={value}" for key, value in sorted(case.artifact_summaries.items())[:6])
                print(f"      summary: {summary}")
            for artifact_path in case.artifact_paths:
                print(f"      artifact: {artifact_path}")
            if case.errors:
                print(f"      errors: {', '.join(case.errors)}")
        for error in report.errors:
            print(f"  error: {error}")
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if not report.ok:
            sys.exit(1)
        return

    if args.command == "mixed-initiative-policy-patch":
        from singularity.evaluation.mixed_initiative import build_mixed_initiative_policy_patch

        execution_reports = getattr(args, "execution_report", []) or []
        artifacts = getattr(args, "artifact", []) or []
        if not execution_reports and not artifacts:
            print("mixed-initiative-policy-patch requires --execution-report or --artifact")
            sys.exit(1)
        patch = build_mixed_initiative_policy_patch(
            execution_report_paths=execution_reports,
            artifact_paths=artifacts,
        )
        print("\nMixed-Initiative Policy Patch")
        print(f"  ok: {patch.ok}")
        print(f"  artifacts: {patch.artifact_count}")
        print(f"  action policy hints: {patch.action_policy_hint_count}")
        print(f"  mixed policy hints: {patch.mixed_policy_hint_count}")
        print(f"  template updates: {patch.template_update_count}")
        action_hints = patch.action_policy_feedback.get("policy_hints", [])
        if action_hints:
            hints = [
                f"{item.get('action_type')}->{item.get('preferred_control')}"
                for item in action_hints[:6]
                if isinstance(item, dict)
            ]
            print(f"  action hint sample: {', '.join(hints)}")
        mixed_hints = patch.mixed_initiative_feedback.get("policy_hints", [])
        if mixed_hints:
            hints = [
                f"{item.get('policy')}:{item.get('template_id') or item.get('candidate_id') or 'trace'}"
                for item in mixed_hints[:6]
                if isinstance(item, dict)
            ]
            print(f"  mixed hint sample: {', '.join(hints)}")
        for error in patch.errors:
            print(f"  error: {error}")
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(patch.to_dict(), f, indent=2, ensure_ascii=False)
            print(f"\nPolicy patch saved to {args.output}")
        if not patch.ok:
            sys.exit(1)
        return

    if args.command == "mixed-initiative-policy-ablation":
        from singularity.evaluation.mixed_initiative import build_mixed_initiative_policy_ablation

        patch_paths = getattr(args, "policy_patch", []) or []
        if not patch_paths:
            print("mixed-initiative-policy-ablation requires at least one --policy-patch")
            sys.exit(1)
        actions = []
        for raw_action in getattr(args, "action", []) or []:
            raw_action = str(raw_action or "").strip()
            if not raw_action:
                continue
            if raw_action.startswith("{"):
                actions.append(json.loads(raw_action))
            else:
                actions.append({"id": raw_action, "type": raw_action, "parameters": {}})
        report = build_mixed_initiative_policy_ablation(
            patch_paths=patch_paths,
            actions=actions,
            template_ids=getattr(args, "template_id", []) or [],
            candidate_ids=getattr(args, "candidate_id", []) or [],
            allow_planned_backend=getattr(args, "allow_planned_backend", False),
        )
        print("\nMixed-Initiative Policy Ablation")
        print(f"  ok: {report.ok}")
        print(f"  patches: {report.patch_count}")
        print(f"  action decisions changed: {report.action_changed_count}/{len(report.action_cases)}")
        print(f"  template decisions changed: {report.template_changed_count}/{len(report.template_cases)}")
        print(f"  candidate decisions changed: {report.candidate_changed_count}/{len(report.candidate_cases)}")
        if report.action_cases:
            print("  action cases:")
            for case in report.action_cases[:8]:
                base = case.baseline
                patched = case.patched
                marker = "*" if case.changed else "-"
                print(
                    f"    {marker} {case.id}: "
                    f"{base.get('backend')}/{base.get('preferred_control')} -> "
                    f"{patched.get('backend')}/{patched.get('preferred_control')}"
                )
                if patched.get("fallback_reason"):
                    print(f"      fallback: {patched.get('fallback_reason')}")
        review_cases = list(report.template_cases) + list(report.candidate_cases)
        if review_cases:
            print("  review cases:")
            for case in review_cases[:8]:
                marker = "*" if case.changed else "-"
                print(
                    f"    {marker} {case.target_type}:{case.target_id}: "
                    f"{case.baseline.get('decision')} -> {case.patched.get('decision')}"
                )
        if report.patched_recommendations:
            print("  patched recommendations:")
            for item in report.patched_recommendations[:8]:
                print(
                    f"    - {item.get('decision')}[{item.get('priority', 'normal')}] "
                    f"{item.get('target_type')}:{item.get('target_id')}"
                )
        for error in report.errors:
            print(f"  error: {error}")
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if not report.ok:
            sys.exit(1)
        return

    if args.command == "mixed-initiative-policy-gate":
        from singularity.evaluation.mixed_initiative import build_mixed_initiative_policy_gate

        policy_ablation_paths = getattr(args, "policy_ablation", []) or []
        benchmark_ablation_paths = getattr(args, "benchmark_ablation", []) or []
        collab_ablation_paths = getattr(args, "collab_ablation", []) or []
        if not policy_ablation_paths and not benchmark_ablation_paths and not collab_ablation_paths:
            print("mixed-initiative-policy-gate requires at least one ablation report")
            sys.exit(1)
        report = build_mixed_initiative_policy_gate(
            policy_ablation_paths=policy_ablation_paths,
            benchmark_ablation_paths=benchmark_ablation_paths,
            collaboration_ablation_paths=collab_ablation_paths,
        )
        print("\nMixed-Initiative Policy Gate")
        print(f"  readiness: {report.readiness}")
        print(f"  decision: {report.decision}")
        print(f"  reason: {report.reason}")
        print(f"  evidence: {report.evidence_count}, warnings: {report.warning_count}, regressions: {report.regression_count}")
        for check in report.checks:
            marker = "+" if check.get("status") == "pass" else "!" if check.get("status") == "warn" else "x"
            print(f"  [{marker}] {check.get('source')}: {check.get('detail')}")
        for error in report.errors:
            print(f"  error: {error}")
        if getattr(args, "output", ""):
            output_dir = os.path.dirname(args.output)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if report.readiness == "rejected":
            sys.exit(1)
        return

    if args.command == "mixed-initiative-trace-report":
        from singularity.evaluation.mixed_initiative import build_mixed_initiative_trace_report

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("mixed-initiative-trace-report requires at least one --session-log")
            sys.exit(1)
        report = build_mixed_initiative_trace_report(
            session_logs,
            template_id=getattr(args, "template", "auto"),
        )
        print("\nMixed-Initiative Trace Report")
        print(f"  logs: {report.log_count}")
        print(f"  goals: {report.goal_count}")
        print(f"  goals needing clarification: {report.needs_clarification_count}")
        print(f"  unbound slots: {report.unbound_slot_count}")
        print(f"  unsupported template goals: {report.unsupported_goal_count}")
        print(f"  validator success: {report.validator_success_count}/{report.goal_count}")
        print(
            "  actions: "
            f"total={report.action_count}, valid={report.valid_action_count}, "
            f"invalid={report.invalid_action_count}, successful={report.successful_action_count}, "
            f"failed={report.failed_action_count}"
        )
        print(
            "  action success rates: "
            f"raw={report.action_success_rate:.2f}, valid_only={report.valid_action_success_rate:.2f}"
        )
        print(f"  policy violations: {report.policy_violation_count}")
        if report.agreement_counts:
            parts = [f"{key}={value}" for key, value in sorted(report.agreement_counts.items())]
            print(f"  agreement: {', '.join(parts)}")
        if report.template_action_metrics:
            print("  template action metrics:")
            for item in report.template_action_metrics:
                print(
                    f"    - {item['template_id']}: actions={item['action_count']}, "
                    f"valid={item['valid_action_count']}, invalid={item['invalid_action_count']}, "
                    f"valid_success_rate={item['valid_action_success_rate']:.2f}"
                )
        feedback = report.mixed_initiative_feedback
        if feedback.get("policy_hints"):
            print("  feedback hints:")
            for hint in feedback["policy_hints"][:6]:
                target = hint.get("template_id") or hint.get("candidate_id") or "trace"
                print(
                    f"    - {hint['policy']}[{hint.get('priority', 'low')}] "
                    f"{target}: {hint.get('reason', '')}"
                )
        if report.mixed_initiative_recommendations:
            print("  recommendations:")
            for item in report.mixed_initiative_recommendations[:6]:
                print(
                    f"    - {item['decision']}[{item.get('priority', 'normal')}] "
                    f"{item['target_type']}:{item['target_id']}"
                )
        if report.template_candidates:
            print("  template candidates:")
            for candidate in report.template_candidates[:6]:
                examples = ", ".join(candidate["example_goals"][:2])
                print(
                    f"    - {candidate['candidate_id']} x{candidate['count']} "
                    f"({candidate['category']}): {examples}"
                )
        for case in report.cases:
            marker = "+" if case.validator_success else "x" if case.policy_violation_count else "~"
            print(f"  [{marker}] {case.goal}")
            print(f"      template={case.template_id}, preview={case.plan_preview}")
            print(
                f"      subtasks={case.validation_passed_count}/{case.subtask_count} passed, "
                f"failed={case.validation_failed_count}, invalid={case.validation_invalid_count}, "
                f"unknown={case.validation_unknown_count}"
            )
            if case.action_count:
                print(
                    f"      actions: total={case.action_count}, valid={case.valid_action_count}, "
                    f"invalid={case.invalid_action_count}, successful={case.successful_action_count}, "
                    f"failed={case.failed_action_count}"
                )
            if case.needs_clarification and case.clarifying_questions:
                print(f"      clarification: {case.clarifying_questions[0]}")
            if case.goal_verification_status:
                print(
                    f"      goal verifier: status={case.goal_verification_status}, "
                    f"accepted={case.goal_verification_accepted}"
                )
            if case.template_candidate:
                print(f"      template candidate: {case.template_candidate.get('candidate_id')}")
            print(f"      agreement: {case.agreement}")
        for error in report.errors:
            print(f"  error: {error}")
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "visual-review-pipeline":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        session_logs = getattr(args, "session_log", []) or []
        if not session_logs:
            print("visual-review-pipeline requires at least one --session-log")
            sys.exit(1)
        runner = BenchmarkRunner(Config(llm=_llm_config_from_args(args)))
        report = runner.run_visual_review_pipeline(
            session_logs,
            mode=getattr(args, "mode", "both"),
            label_file=getattr(args, "label_file", ""),
            promotion_critic=_promotion_critic_from_args(args),
            goal_critic=_goal_critic_from_args(args),
            include_causal_summaries=getattr(args, "causal_summaries", False),
            include_failure_corrections=getattr(args, "failure_corrections", False),
            run_ablations=getattr(args, "run_ablations", False),
        )
        runner.print_visual_review_pipeline_report(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(runner.visual_review_pipeline_report_to_dict(report), f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if report.label_validation is not None and not report.label_validation.ok:
            sys.exit(1)
        return

    if args.command == "policy-skill-ablation":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        runner = BenchmarkRunner(Config())
        report = runner.run_policy_skill_ablation(
            skill_storage_path=getattr(args, "skill_storage_path", ""),
            include_builtin=not getattr(args, "no_builtin", False),
        )
        runner.print_policy_skill_ablation_report(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "helped_count": report.helped_count,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    if args.command == "visual-action-ablation":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        runner = BenchmarkRunner(Config())
        session_logs = getattr(args, "session_log", []) or []
        if session_logs:
            report = runner.run_visual_action_ablation_from_logs(
                session_logs,
                max_cases_per_log=getattr(args, "max_cases_per_log", 20),
                include_builtin=getattr(args, "include_builtin", False),
            )
        else:
            report = runner.run_visual_action_ablation()
        runner.print_visual_action_ablation_report(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "passed_count": report.passed_count,
                    "changed_count": report.changed_count,
                    "helped_count": report.helped_count,
                    "cases": [asdict(case) for case in report.cases],
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        return

    # Build config from args
    host = getattr(args, "host", "localhost") or "localhost"
    port = getattr(args, "port", 25565) or 25565
    username = getattr(args, "username", "Singularity") or "Singularity"
    bridge_host = getattr(args, "bridge_host", "127.0.0.1") or "127.0.0.1"
    bridge_port = getattr(args, "bridge_port", 3000) or 3000
    config = Config(
        bot=BotConfig(host=host, port=port, username=username, bridge_host=bridge_host, bridge_port=bridge_port),
        llm=_llm_config_from_args(args),
        enable_goal_critic=getattr(args, "goal_critic", False),
        enable_skill_memory_context=not getattr(args, "no_skill_memory_context", False),
        enable_coaching_policy=not getattr(args, "no_coaching_policy", False),
        coach_style=getattr(args, "coach_style", "") or "",
        enable_vision_analysis=not getattr(args, "no_vision_analysis", False),
        enable_visual_action_grounding=not getattr(args, "no_visual_action_grounding", False),
        mixed_policy_patch_paths=getattr(args, "mixed_policy_patch", []) or [],
        mixed_policy_gate_paths=getattr(args, "mixed_policy_gate", []) or [],
        self_evolution_feedback_paths=getattr(args, "self_evolution_feedback", []) or [],
        world_model_feedback_paths=getattr(args, "world_model_feedback", []) or [],
        world_model_gate_paths=getattr(args, "world_model_gate", []) or [],
        action_value_feedback_paths=getattr(args, "action_value_feedback", []) or [],
        action_value_transition_gate_paths=getattr(args, "action_value_transition_gate", []) or [],
        action_value_transition_evaluator_report_paths=getattr(args, "action_value_transition_evaluator_report", []) or [],
        skill_memory_quality_feedback_paths=getattr(args, "skill_memory_quality_feedback", []) or [],
        skill_memory_quality_gate_paths=getattr(args, "skill_memory_quality_gate", []) or [],
        enable_screenshot_capture=getattr(args, "capture_screenshots", False),
        screenshot_dir=getattr(args, "screenshot_dir", "logs/screenshots"),
        screenshot_min_interval_s=getattr(args, "screenshot_min_interval", 2.0),
    )

    if args.command == "preflight":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner
        runner = BenchmarkRunner(config)
        report = runner.preflight(
            check_network=not getattr(args, "skip_network", False),
            check_screenshot_renderer=getattr(args, "screenshot_renderer", False),
        )
        runner.print_preflight(report)
        if not report.ok:
            sys.exit(1)

    elif args.command == "screenshot-smoke-test":
        from dataclasses import asdict
        from singularity.evaluation.benchmark_runner import BenchmarkRunner

        runner = BenchmarkRunner(config)
        report = runner.run_screenshot_smoke_test(getattr(args, "screenshot_path", ""))
        runner.print_screenshot_smoke_report(report)
        if getattr(args, "output", ""):
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    **asdict(report),
                    "ok": report.ok,
                }, f, indent=2, ensure_ascii=False)
            print(f"\nReport saved to {args.output}")
        if not report.ok:
            sys.exit(1)

    elif args.command == "benchmark":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner
        runner = BenchmarkRunner(config)
        if getattr(args, "preflight", False):
            report = runner.preflight(
                check_screenshot_renderer=getattr(args, "capture_screenshots", False),
            )
            runner.print_preflight(report)
            if not report.ok:
                sys.exit(1)
        quality_feedback_paths = getattr(args, "skill_memory_quality_feedback", []) or []
        if getattr(args, "skill_memory_quality_preflight", False) or quality_feedback_paths:
            report = runner.run_skill_memory_quality_preflight(suite=args.suite)
            runner.print_skill_memory_quality_preflight_report(report)
            quality_preflight_output = getattr(args, "skill_memory_quality_preflight_output", "") or ""
            if quality_preflight_output:
                runner.save_skill_memory_quality_preflight_report(report, quality_preflight_output)
            if not report.get("ready"):
                sys.exit(1)
        transition_gate_paths = getattr(args, "action_value_transition_gate", []) or []
        transition_evaluator_paths = getattr(args, "action_value_transition_evaluator_report", []) or []
        if (
            getattr(args, "action_value_transition_preflight", False)
            or transition_gate_paths
            or transition_evaluator_paths
        ):
            report = runner.run_action_value_transition_preflight(
                suite=args.suite,
                require_evaluator_report=getattr(args, "require_action_value_transition_evaluator_report", False),
            )
            runner.print_action_value_transition_preflight_report(report)
            transition_preflight_output = getattr(args, "action_value_transition_preflight_output", "") or ""
            if transition_preflight_output:
                runner.save_action_value_transition_preflight_report(report, transition_preflight_output)
            if not report.get("ready"):
                sys.exit(1)
        if getattr(args, "policy_skill_ablation", False):
            report = runner.run_policy_skill_benchmark_ablation(suite=args.suite)
            runner.print_policy_skill_benchmark_ablation_report(report)
            runner.save_policy_skill_benchmark_ablation_report(report, args.output)
            return
        if getattr(args, "skill_memory_ablation", False):
            report = runner.run_skill_memory_benchmark_ablation(suite=args.suite)
            runner.print_skill_memory_benchmark_ablation_report(report)
            runner.save_skill_memory_benchmark_ablation_report(report, args.output)
            return
        if getattr(args, "visual_action_ablation", False):
            report = runner.run_visual_action_benchmark_ablation(suite=args.suite)
            runner.print_visual_action_benchmark_ablation_report(report)
            runner.save_visual_action_benchmark_ablation_report(report, args.output)
            return
        if getattr(args, "mixed_policy_ablation", False):
            patch_paths = getattr(args, "mixed_policy_patch", []) or []
            if not patch_paths:
                print("benchmark --mixed-policy-ablation requires at least one --mixed-policy-patch")
                sys.exit(1)
            report = runner.run_mixed_policy_benchmark_ablation(
                patch_paths=patch_paths,
                suite=args.suite,
            )
            runner.print_mixed_policy_benchmark_ablation_report(report)
            runner.save_mixed_policy_benchmark_ablation_report(report, args.output)
            return
        if args.suite == "m1":
            runner.run_m1_suite()
        elif args.suite == "m2":
            runner.run_m2_suite()
        else:
            runner.run_m1_suite()
            runner.run_m2_suite()
        runner.print_summary()
        runner.save_results(args.output)
        if getattr(args, "ingest", False):
            report = runner.ingest_results(promotion_critic=_promotion_critic_from_args(args))
            runner.print_ingestion_report(report)

    elif args.command == "autonomous":
        from singularity.core.agent import Agent
        agent = Agent(config)
        if not agent.connect():
            print("Failed to connect to Minecraft server")
            sys.exit(1)
        try:
            result = agent.run_autonomous(
                max_goals=getattr(args, "max_goals", 10),
                max_cycles_per_goal=getattr(args, "max_cycles", 80),
            )
            print(json.dumps(result, indent=2, default=str))
        finally:
            agent.disconnect()

    else:
        from singularity.core.agent import Agent
        goal = args.goal if args.goal else "Gather 3 oak logs"
        agent = Agent(config)
        if not agent.connect():
            print("Failed to connect to Minecraft server")
            sys.exit(1)
        try:
            result = agent.run_goal(goal)
            print(json.dumps(result, indent=2, default=str))
        finally:
            agent.disconnect()


if __name__ == "__main__":
    main()
