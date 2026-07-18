#!/usr/bin/env python3
"""Run the isolated SP-002 first-cycle skill-routing recovery window."""

from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import scripts.stone_pickaxe_sp002_skill_evaluation as _base
import singularity.evaluation.stone_pickaxe_sp002_skill_evaluation_v2 as _v2


_PATCHED_NAMES = (
    "POLICY",
    "POLICY_SHA256",
    "StonePickaxeSP002SkillEvaluationAgent",
    "build_baseline_index",
    "build_evaluation_authorization",
    "build_paired_evaluation_report",
    "build_skill_evaluation_episode",
    "build_skill_evaluation_run",
    "build_skill_evaluation_runtime_config",
    "discover_evaluation_run_paths",
    "policy_identity_report",
    "validate_evaluation_authorization",
)


def _patch_base_runner() -> None:
    for name in _PATCHED_NAMES:
        setattr(_base, name, getattr(_v2, name))


def _apply_v2_report_defaults(argv: list[str]) -> list[str]:
    values = list(argv)
    if len(values) < 2 or values[1] != "refresh-report":
        return values
    defaults = {
        "--baseline-output": (
            "workspace/evals/sp002_skill_evaluation_v2/"
            "craft_stone_pickaxe_baseline_index_v2.json"
        ),
        "--report-output": (
            "workspace/evals/sp002_skill_evaluation_v2/"
            "craft_stone_pickaxe_paired_evaluation_v2.json"
        ),
    }
    for option, value in defaults.items():
        if option not in values:
            values.extend((option, value))
    return values


def main() -> int:
    _patch_base_runner()
    sys.argv = _apply_v2_report_defaults(sys.argv)
    return _base.main()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print({"error": str(exc), "automatic_retry_allowed": False}, file=sys.stderr)
        raise
