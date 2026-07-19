from __future__ import annotations

import hashlib
import json
from pathlib import Path

from singularity.evaluation.stone_pickaxe_sp003_runtime import (
    verify_sp003_policy_identity,
)


REPO = Path(__file__).resolve().parents[1]
AUDIT_PATH = (
    REPO
    / "workspace/evals/stone_pickaxe_sp003_first_table_tool_craft_readiness_repair.json"
)
PHASE123_RUN = (
    REPO
    / "workspace/evals/sp003_runs/sp003_baseline_20260720_040104_4676408a"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_phase124_preload_is_bound_by_the_sp003_policy():
    policy = json.loads(
        (
            REPO / "workspace/evals/stone_pickaxe_sp003_harness_policy.json"
        ).read_text(encoding="utf-8")
    )
    preload = REPO / policy["implementation_contract"]["runtime_preload_module"]
    source = preload.read_text(encoding="utf-8")

    assert policy["implementation_contract"]["runtime_preload_sha256"] == _sha256(
        preload
    )
    assert "sp003-first-table-tool-craft-readiness-v1" in source
    assert "preflightFirstTableToolCraft" in source
    assert "firstTableToolCraftReadinessStatus" in source
    assert verify_sp003_policy_identity()["passed"] is True


def test_phase124_keeps_phase123_and_shared_boundaries_immutable():
    assert _sha256(PHASE123_RUN / "manifest.json") == (
        "6420a734dd42c74a7c866f7cb3a23e5d2bb2f2b774a037e0f853d0a9b12a6133"
    )
    assert _sha256(PHASE123_RUN / "session.json") == (
        "aae89c099fb3ef43d0af68f9bceb69ae56880f37d1b2a2b1649773888ea01f97"
    )
    assert _sha256(PHASE123_RUN / "episode.json") == (
        "c2a18b85600c84d00c54e153d1fee77618c8d808becf458145c4064256b3362a"
    )
    assert _sha256(REPO / "src/bot/bot_server.js") == (
        "f1677b32fc726d6d983d4646d47cda80d57f49949f0759d8e735e59e18765f60"
    )
    assert _sha256(REPO / "workspace/evals/stone_pickaxe_protocol.json") == (
        "e0722422b62da73d9c1c1c449ae6a3392913125e85c72adad8fa2c9bd0970006"
    )


def test_phase124_audit_binds_the_one_shot_non_mutating_repair():
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    assert audit["phase"] == 124
    assert audit["base_commit"] == (
        "33441a1877f43c5292f83ca61c29b2cdcdf112c0"
    )
    assert audit["policy_id"] == "sp003-first-table-tool-craft-readiness-v1"
    assert audit["status"] == "offline_verified"
    contract = audit["repair_contract"]
    assert contract["preflight_attempt_limit"] == 1
    assert contract["original_craft_call_count_per_action"] == 1
    assert contract["backend_retry_added"] is False
    assert contract["preflight_inventory_must_remain_unchanged"] is True
    assert contract["preflight_world_mutation"] is False
    assert contract["failed_preflight_is_terminal"] is True

    for record in [
        *audit["implementation"],
        *audit["protected_identities"],
        *audit["retained_phase_123_identities"],
    ]:
        assert _sha256(REPO / record["path"]) == record["sha256"]

    assert audit["live_episode_run"] is False
    assert audit["live_authorization"] is False
    assert audit["automatic_retry_allowed"] is False
    assert audit["counts_toward_baseline_success"] is False
    assert audit["counts_toward_skill_gate"] is False
    assert audit["counts_toward_capability"] is False
    assert audit["counts_toward_m4"] is False
