"""Singularity - Minecraft LLM Agent entry point."""
import sys
import json
import logging
import argparse

from singularity.core.config import Config, BotConfig, LLMConfig


def main():
    parser = argparse.ArgumentParser(description="Singularity Minecraft LLM Agent")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Run goal command
    run_parser = subparsers.add_parser("run", help="Run a single goal")
    run_parser.add_argument("--goal", type=str, default="Gather 3 oak logs", help="Goal in natural language")
    run_parser.add_argument("--host", type=str, default="localhost")
    run_parser.add_argument("--port", type=int, default=25565)
    run_parser.add_argument("--username", type=str, default="Singularity")
    run_parser.add_argument("--llm-provider", type=str, default="openai")
    run_parser.add_argument("--llm-model", type=str, default="gpt-4o-mini")
    run_parser.add_argument("--api-key", type=str, default="")
    run_parser.add_argument("--log-level", type=str, default="INFO")

    # Autonomous mode (M4 + M5)
    auto_parser = subparsers.add_parser("autonomous", help="Run autonomous survival (M4 + M5)")
    auto_parser.add_argument("--max-goals", type=int, default=10, help="Maximum goals to pursue")
    auto_parser.add_argument("--max-cycles", type=int, default=80, help="Max cycles per goal")
    auto_parser.add_argument("--host", type=str, default="localhost")
    auto_parser.add_argument("--port", type=int, default=25565)
    auto_parser.add_argument("--username", type=str, default="Singularity")
    auto_parser.add_argument("--llm-provider", type=str, default="openai")
    auto_parser.add_argument("--llm-model", type=str, default="gpt-4o-mini")
    auto_parser.add_argument("--api-key", type=str, default="")
    auto_parser.add_argument("--log-level", type=str, default="INFO")

    # Benchmark command
    bench_parser = subparsers.add_parser("benchmark", help="Run benchmarks")
    bench_parser.add_argument("--suite", type=str, default="m1", choices=["m1", "m2", "all"])
    bench_parser.add_argument("--host", type=str, default="localhost")
    bench_parser.add_argument("--port", type=int, default=25565)
    bench_parser.add_argument("--username", type=str, default="Singularity")
    bench_parser.add_argument("--llm-provider", type=str, default="openai")
    bench_parser.add_argument("--llm-model", type=str, default="gpt-4o-mini")
    bench_parser.add_argument("--api-key", type=str, default="")
    bench_parser.add_argument("--log-level", type=str, default="INFO")
    bench_parser.add_argument("--output", type=str, default="benchmark_results.json")

    # Skills info command
    skills_parser = subparsers.add_parser("skills", help="List available skills")

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
        lib = SkillLibrary()
        print(f"\nSingularity Skill Library ({len(lib.skills)} skills)\n")
        for layer in ("primitive", "composite", "strategic"):
            skills = lib.list_skills(layer)
            if skills:
                print(f"  [{layer.upper()}]")
                for s in skills:
                    uses = f" ({s.total_uses} uses, {s.success_rate:.0%} success)" if s.total_uses > 0 else ""
                    print(f"    - {s.name}: {s.description}{uses}")
        return

    # Build config from args
    host = getattr(args, "host", "localhost") or "localhost"
    port = getattr(args, "port", 25565) or 25565
    username = getattr(args, "username", "Singularity") or "Singularity"
    provider = getattr(args, "llm_provider", "openai") or "openai"
    model = getattr(args, "llm_model", "gpt-4o-mini") or "gpt-4o-mini"
    api_key = getattr(args, "api_key", "") or ""

    config = Config(
        bot=BotConfig(host=host, port=port, username=username),
        llm=LLMConfig(provider=provider, model=model, api_key=api_key),
    )

    if args.command == "benchmark":
        from singularity.evaluation.benchmark_runner import BenchmarkRunner
        runner = BenchmarkRunner(config)
        if args.suite == "m1":
            runner.run_m1_suite()
        elif args.suite == "m2":
            runner.run_m2_suite()
        else:
            runner.run_m1_suite()
            runner.run_m2_suite()
        runner.print_summary()
        runner.save_results(args.output)

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
