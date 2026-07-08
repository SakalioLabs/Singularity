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
    run_parser.add_argument("--no-vision-analysis", action="store_true", help="Disable structured vision grounding on observations")
    run_parser.add_argument("--no-visual-action-grounding", action="store_true", help="Disable visual suggestions from modifying planned actions")
    run_parser.add_argument("--capture-screenshots", action="store_true", help="Ask the bridge renderer to capture screenshots for visual analysis")
    run_parser.add_argument("--screenshot-dir", type=str, default="logs/screenshots", help="Directory for captured screenshot files")
    run_parser.add_argument("--screenshot-min-interval", type=float, default=2.0, help="Minimum seconds between screenshot capture attempts")
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
    auto_parser.add_argument("--no-vision-analysis", action="store_true", help="Disable structured vision grounding on observations")
    auto_parser.add_argument("--no-visual-action-grounding", action="store_true", help="Disable visual suggestions from modifying planned actions")
    auto_parser.add_argument("--capture-screenshots", action="store_true", help="Ask the bridge renderer to capture screenshots for visual analysis")
    auto_parser.add_argument("--screenshot-dir", type=str, default="logs/screenshots", help="Directory for captured screenshot files")
    auto_parser.add_argument("--screenshot-min-interval", type=float, default=2.0, help="Minimum seconds between screenshot capture attempts")
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
    bench_parser.add_argument("--no-vision-analysis", action="store_true", help="Disable structured vision grounding on observations")
    bench_parser.add_argument("--no-visual-action-grounding", action="store_true", help="Disable visual suggestions from modifying planned actions")
    bench_parser.add_argument("--capture-screenshots", action="store_true", help="Ask the bridge renderer to capture screenshots for visual analysis")
    bench_parser.add_argument("--screenshot-dir", type=str, default="logs/screenshots", help="Directory for captured screenshot files")
    bench_parser.add_argument("--screenshot-min-interval", type=float, default=2.0, help="Minimum seconds between screenshot capture attempts")
    bench_parser.add_argument("--log-level", type=str, default="INFO")
    bench_parser.add_argument("--output", type=str, default="benchmark_results.json")
    bench_parser.add_argument("--preflight", action="store_true", help="Run readiness checks before benchmarks")
    bench_parser.add_argument("--ingest", action="store_true", help="Ingest passing benchmark traces into memory and skill candidate queue")
    bench_parser.add_argument("--promotion-critic", action="store_true", help="Use configured LLM as fallback critic for unknown skill-candidate verifier gates during ingestion")
    bench_parser.add_argument("--policy-skill-ablation", action="store_true", help="Run suite twice with reviewed policy skills disabled and enabled")
    bench_parser.add_argument("--visual-action-ablation", action="store_true", help="Run suite twice with visual action grounding disabled and enabled")

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

    # Memory consolidation report
    memory_report_parser = subparsers.add_parser("memory-consolidation-report", help="Report repeatedly recalled memories worth consolidation")
    memory_report_parser.add_argument("--memory-dir", type=str, default="workspace/memory")
    memory_report_parser.add_argument("--min-score", type=float, default=0.65)
    memory_report_parser.add_argument("--min-recall-count", type=int, default=2)
    memory_report_parser.add_argument("--min-unique-queries", type=int, default=2)
    memory_report_parser.add_argument("--limit", type=int, default=20)
    memory_report_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    memory_report_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline memory policy trace report
    memory_policy_parser = subparsers.add_parser("memory-policy-report", help="Report memory write/read/manage policy gaps in session logs")
    memory_policy_parser.add_argument("--session-log", action="append", default=[], help="Session JSONL log to inspect")
    memory_policy_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    memory_policy_parser.add_argument("--log-level", type=str, default="INFO")

    # Offline memory read filter report
    memory_read_parser = subparsers.add_parser("memory-read-filter-report", help="Report stale or condition-mismatched durable memories for a query")
    memory_read_parser.add_argument("--memory-dir", type=str, default="workspace/memory")
    memory_read_parser.add_argument("--query", type=str, default="", help="Optional retrieval query to filter relevant entries")
    memory_read_parser.add_argument("--current-state-json", type=str, default="", help="Optional current state JSON object for conditional applicability checks")
    memory_read_parser.add_argument("--current-state-file", type=str, default="", help="Optional JSON file with current state for conditional applicability checks")
    memory_read_parser.add_argument("--output", type=str, default="", help="Optional JSON report path")
    memory_read_parser.add_argument("--log-level", type=str, default="INFO")

    # Skill candidate review queue
    candidates_parser = subparsers.add_parser("skill-candidates", help="Review extracted skill candidates")
    candidates_parser.add_argument("--queue", type=str, default="workspace/skills/skill_candidates.jsonl")
    candidates_parser.add_argument("--storage-path", type=str, default="workspace/skills")
    candidates_parser.add_argument("--session", type=str, default="", help="Extract candidates from a session JSONL log")
    candidates_parser.add_argument("--promotion-critic", action="store_true", help="Use configured LLM as fallback critic for unknown verifier gates")
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

    # M7 collaboration benchmark dry-run/assignment
    collab_parser = subparsers.add_parser("collab-benchmark", help="Prepare an M7 collaboration benchmark")
    collab_parser.add_argument("--spec", type=str, default="workspace/benchmarks/m7_time_sensitive_shelter.json")
    collab_parser.add_argument("--state-path", type=str, default="workspace/multiagent/collab_benchmark_state.json")
    collab_parser.add_argument("--no-reset", action="store_true", help="Keep existing shared-state file")
    collab_parser.add_argument("--preflight", action="store_true", help="Check Agent executor role bridges before execution")
    collab_parser.add_argument("--execute", action="store_true", help="Run the synchronous state-transition executor after assignment")
    collab_parser.add_argument("--executor", type=str, default="simulated", choices=["simulated", "agent"], help="Task executor for --execute")
    collab_parser.add_argument("--max-steps", type=int, default=0, help="Maximum dispatch steps for --execute")
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
    collab_parser.add_argument("--no-vision-analysis", action="store_true", help="Disable structured vision grounding on observations")
    collab_parser.add_argument("--no-visual-action-grounding", action="store_true", help="Disable visual suggestions from modifying planned actions")
    collab_parser.add_argument("--capture-screenshots", action="store_true", help="Ask each Agent bridge renderer to capture screenshots for visual analysis")
    collab_parser.add_argument("--screenshot-dir", type=str, default="logs/screenshots", help="Directory for captured screenshot files")
    collab_parser.add_argument("--screenshot-min-interval", type=float, default=2.0, help="Minimum seconds between screenshot capture attempts")
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

    if args.command == "skill-candidates":
        from singularity.core.skill_extractor import SkillCandidateQueue, SkillExtractor
        from singularity.core.skill_library import SkillLibrary

        queue = SkillCandidateQueue(getattr(args, "queue", "workspace/skills/skill_candidates.jsonl"))
        promotion_critic = _promotion_critic_from_args(args)
        if getattr(args, "session", ""):
            lib = SkillLibrary(storage_path=getattr(args, "storage_path", "workspace/skills"))
            extractor = SkillExtractor(lib, auto_promote=False, promotion_critic=promotion_critic)
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
            candidate = queue.approve(args.approve, lib, promotion_critic=promotion_critic)
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
            print(f"- {candidate.id} [{candidate.review_status}] {candidate.name} score={candidate.score}{gate_text}: {candidate.description}")
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
        baseline_role_id = getattr(args, "baseline_role_id", "single_agent") or "single_agent"
        baseline_state_path = getattr(args, "baseline_state_path", "") or ""
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

            task_executor = AgentCollaborationExecutor(Config(
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
                enable_vision_analysis=not getattr(args, "no_vision_analysis", False),
                enable_visual_action_grounding=not getattr(args, "no_visual_action_grounding", False),
                enable_screenshot_capture=getattr(args, "capture_screenshots", False),
                screenshot_dir=getattr(args, "screenshot_dir", "logs/screenshots"),
                screenshot_min_interval_s=getattr(args, "screenshot_min_interval", 2.0),
            ), bridge_port_base=getattr(args, "bridge_port_base", 0) or None, role_bridge_ports=role_bridge_ports)
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
        enable_vision_analysis=not getattr(args, "no_vision_analysis", False),
        enable_visual_action_grounding=not getattr(args, "no_visual_action_grounding", False),
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
        if getattr(args, "policy_skill_ablation", False):
            report = runner.run_policy_skill_benchmark_ablation(suite=args.suite)
            runner.print_policy_skill_benchmark_ablation_report(report)
            runner.save_policy_skill_benchmark_ablation_report(report, args.output)
            return
        if getattr(args, "visual_action_ablation", False):
            report = runner.run_visual_action_benchmark_ablation(suite=args.suite)
            runner.print_visual_action_benchmark_ablation_report(report)
            runner.save_visual_action_benchmark_ablation_report(report, args.output)
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
