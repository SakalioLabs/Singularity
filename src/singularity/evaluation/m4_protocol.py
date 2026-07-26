"""Fixed M4 protocol and machine-checkable episode eligibility gates."""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from pathlib import Path


PROTOCOL_PATH = Path(__file__).resolve().parent.parent / "data" / "m4_protocol.json"
PROTOCOL_BYTES = PROTOCOL_PATH.read_bytes()
PROTOCOL = json.loads(PROTOCOL_BYTES.decode("utf-8"))
PROTOCOL_SHA256 = hashlib.sha256(PROTOCOL_BYTES).hexdigest()
TASKS_BY_ID = {str(task["id"]): task for task in PROTOCOL["tasks"]}
BM012_CONTRACT_PATH = Path(__file__).resolve().parent.parent / "data" / "m4_bm012_protocol.json"
BM012_CONTRACT_BYTES = BM012_CONTRACT_PATH.read_bytes()
BM012_CONTRACT = json.loads(BM012_CONTRACT_BYTES.decode("utf-8"))
BM012_CONTRACT_SHA256 = hashlib.sha256(BM012_CONTRACT_BYTES).hexdigest()
TASK_CONTRACTS_BY_ID = {"BM-012": BM012_CONTRACT}
TASK_CONTRACT_SHA256_BY_ID = {"BM-012": BM012_CONTRACT_SHA256}
M4_PLAYER_LIFECYCLE_VERIFIER_ID = str(
    PROTOCOL.get("identities", {}).get("player_lifecycle_verifier") or ""
)
_PROTOCOL_REPLAY_LOCK = threading.RLock()
_SUPERSEDED_LLM = {
    "provider": "openai",
    "base_url": "https://opencode.ai/zen/go/v1",
    "model": "deepseek-v4-flash",
    "temperature": 0.0,
    "max_tokens": 4096,
    "extra_body": {"thinking": {"type": "disabled"}},
}
_SUPERSEDED_BM012_CONTRACT_SHA256 = (
    "389bafa8651cd6d46b259a708e1f82144615d1a8ae90aa840b00c3751404b45d"
)


def canonical_sha256(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def supported_protocol_sha256s() -> set[str]:
    """Return the active protocol and its explicitly declared provider predecessor."""
    values = {PROTOCOL_SHA256}
    predecessor = str(PROTOCOL.get("supersedes_protocol_sha256") or "").strip().lower()
    if predecessor:
        values.add(predecessor)
    return values


def validate_m4_player_lifecycle(
    value,
    episode_id: str = "",
    require_uninterrupted: bool = True,
) -> dict:
    """Validate one bridge-owned M4 death/respawn continuity snapshot."""
    lifecycle = value if isinstance(value, dict) else {}
    issues = []

    def require(name: str, passed: bool):
        if not passed:
            issues.append(name)

    expected_source = str(PROTOCOL["validation_contract"]["survival"]["player_lifecycle_source"])
    require("type", lifecycle.get("type") == "m4_player_lifecycle")
    require("schema_version", lifecycle.get("schema_version") == 1)
    require("verifier_id", lifecycle.get("verifier_id") == M4_PLAYER_LIFECYCLE_VERIFIER_ID)
    require("source", lifecycle.get("source") == expected_source)
    require("profile", lifecycle.get("profile") == PROTOCOL["profile"])
    require("protocol_sha256", lifecycle.get("protocol_sha256") == PROTOCOL_SHA256)
    require("tracker_id", bool(str(lifecycle.get("tracker_id") or "").strip()))
    require("episode_id", bool(str(lifecycle.get("episode_id") or "").strip()))
    if episode_id:
        require("episode_id_match", str(lifecycle.get("episode_id") or "") == str(episode_id))
    require("level_name", bool(str(lifecycle.get("level_name") or "").strip()))
    baseline_id = str(lifecycle.get("baseline_id") or "")
    require(
        "baseline_id",
        len(baseline_id) == 64 and all(character in "0123456789abcdef" for character in baseline_id),
    )
    require("baseline_established", lifecycle.get("baseline_established") is True)
    require("initial_spawn_observed", lifecycle.get("initial_spawn_observed") is True)

    integer_fields = (
        "baseline_death_count_total",
        "baseline_respawn_count_total",
        "baseline_spawn_count_total",
        "death_count_total",
        "respawn_count_total",
        "spawn_count_total",
        "death_count",
        "respawn_count",
        "spawn_count",
        "pending_respawn_count",
    )
    integers = {}
    for name in integer_fields:
        raw = lifecycle.get(name)
        passed = isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0
        require(name, passed)
        if passed:
            integers[name] = raw
    for name in ("baseline_observed_at_ms", "baseline_bridge_monotonic_ms"):
        raw = lifecycle.get(name)
        require(
            name,
            isinstance(raw, (int, float))
            and not isinstance(raw, bool)
            and math.isfinite(float(raw))
            and float(raw) >= 0,
        )

    if len(integers) == len(integer_fields):
        death_delta = integers["death_count_total"] - integers["baseline_death_count_total"]
        respawn_delta = integers["respawn_count_total"] - integers["baseline_respawn_count_total"]
        spawn_delta = integers["spawn_count_total"] - integers["baseline_spawn_count_total"]
        require("death_count_delta", death_delta == integers["death_count"] and death_delta >= 0)
        require("respawn_count_delta", respawn_delta == integers["respawn_count"] and respawn_delta >= 0)
        require("spawn_count_delta", spawn_delta == integers["spawn_count"] and spawn_delta >= 0)
        require("baseline_spawn_observed", integers["baseline_spawn_count_total"] >= 1)
        require(
            "baseline_respawn_not_ahead_of_death",
            integers["baseline_respawn_count_total"] <= integers["baseline_death_count_total"],
        )
        require("respawn_not_ahead_of_death", integers["respawn_count"] <= integers["death_count"])
        require("respawn_has_spawn", integers["spawn_count"] >= integers["respawn_count"])
        require(
            "pending_respawn_count_match",
            integers["pending_respawn_count"] == integers["death_count"] - integers["respawn_count"],
        )
        require(
            "uninterrupted_consistency",
            lifecycle.get("uninterrupted") is (
                integers["death_count"] == 0 and integers["respawn_count"] == 0
            ),
        )
        require(
            "last_death_consistency",
            (integers["death_count"] == 0 and lifecycle.get("last_death") is None)
            or (
                integers["death_count"] > 0
                and _valid_lifecycle_event(lifecycle.get("last_death"), "death")
                and lifecycle["last_death"].get("death_count_total") == integers["death_count_total"]
            ),
        )
        require(
            "last_respawn_consistency",
            (integers["respawn_count"] == 0 and lifecycle.get("last_respawn") is None)
            or (
                integers["respawn_count"] > 0
                and _valid_lifecycle_event(lifecycle.get("last_respawn"), "respawn")
                and lifecycle["last_respawn"].get("respawn_count_total") == integers["respawn_count_total"]
                and lifecycle["last_respawn"].get("spawn_count_total") == integers["spawn_count_total"]
            ),
        )
        if require_uninterrupted:
            expected_deaths = int(PROTOCOL["validation_contract"]["survival"]["active_episode_death_count"])
            expected_respawns = int(PROTOCOL["validation_contract"]["survival"]["active_episode_respawn_count"])
            require("active_episode_death_count", integers["death_count"] == expected_deaths)
            require("active_episode_respawn_count", integers["respawn_count"] == expected_respawns)
            require("uninterrupted_survival", lifecycle.get("uninterrupted") is True)

    return {
        "passed": not issues,
        "issues": issues,
        "death_count": lifecycle.get("death_count"),
        "respawn_count": lifecycle.get("respawn_count"),
        "baseline_id": baseline_id,
        "episode_id": str(lifecycle.get("episode_id") or ""),
    }


def _valid_lifecycle_event(value, kind: str) -> bool:
    if not isinstance(value, dict) or value.get("kind") != kind:
        return False
    return bool(
        isinstance(value.get("event_sequence"), int)
        and not isinstance(value.get("event_sequence"), bool)
        and value["event_sequence"] > 0
        and isinstance(value.get("observed_at_ms"), (int, float))
        and not isinstance(value.get("observed_at_ms"), bool)
        and math.isfinite(float(value["observed_at_ms"]))
        and isinstance(value.get("bridge_monotonic_ms"), (int, float))
        and not isinstance(value.get("bridge_monotonic_ms"), bool)
        and math.isfinite(float(value["bridge_monotonic_ms"]))
    )


def protocol_integrity_report() -> dict:
    expected = {
        "reset_protocol_sha256": canonical_sha256(PROTOCOL.get("reset_contract", {})),
        "validation_protocol_sha256": canonical_sha256(PROTOCOL.get("validation_contract", {})),
    }
    issues = [name for name, value in expected.items() if str(PROTOCOL.get(name) or "") != value]
    if PROTOCOL.get("profile") != "m4-fixed-v1":
        issues.append("profile_mismatch")
    predecessor = str(PROTOCOL.get("supersedes_protocol_sha256") or "").strip().lower()
    replaying_predecessor = bool(predecessor and PROTOCOL_SHA256 == predecessor)
    llm = PROTOCOL.get("llm", {})
    if llm.get("provider") != "openai":
        issues.append("planner_provider_must_be_openai_compatible")
    if replaying_predecessor:
        if llm != _SUPERSEDED_LLM:
            issues.append("predecessor_planner_mismatch")
    else:
        if PROTOCOL.get("provider_revision") != "m4-grok-4.5-openai-compatible-v1":
            issues.append("provider_revision_mismatch")
        if llm.get("model") != "grok-4.5":
            issues.append("planner_model_mismatch")
        if llm.get("provider_modalities") != ["text", "image"]:
            issues.append("provider_modalities_mismatch")
        if llm.get("runtime_modalities") != ["text"]:
            issues.append("runtime_modalities_mismatch")
    if PROTOCOL.get("game_mode") != "survival":
        issues.append("survival_mode_required")
    if PROTOCOL.get("difficulty") == "peaceful":
        issues.append("peaceful_difficulty_forbidden")
    gamerules = PROTOCOL.get("gamerules", {})
    if gamerules.get("doDaylightCycle") is not True:
        issues.append("natural_time_progression_required")
    if gamerules.get("doMobSpawning") is not True:
        issues.append("mob_spawning_required")
    if PROTOCOL.get("initial_inventory") != {}:
        issues.append("initial_inventory_must_be_empty")
    controls = PROTOCOL.get("baseline_runtime_controls", {})
    if controls.get("skill_execution_mode") != "off":
        issues.append("learned_skill_execution_must_be_off")
    for name in (
        "learned_executable_skills_enabled",
        "quarantined_skills_enabled",
        "vision_enabled",
        "multi_agent_enabled",
    ):
        if controls.get(name) is not False:
            issues.append(f"baseline_control_mismatch:{name}")
    planner_contract = PROTOCOL.get("validation_contract", {}).get("planner_evidence", {})
    required_extra_body = {"thinking": {"type": "disabled"}}
    if PROTOCOL.get("llm", {}).get("extra_body") != required_extra_body:
        issues.append("planner_thinking_must_be_disabled")
    if planner_contract.get("required_extra_body") != required_extra_body:
        issues.append("planner_extra_body_contract_mismatch")
    if planner_contract.get("real_llm_call_required") is not True:
        issues.append("planner_real_llm_call_must_be_required")
    if planner_contract.get("schema_valid_call_required") is not True:
        issues.append("planner_schema_valid_call_must_be_required")
    if planner_contract.get("finish_reason") != "stop":
        issues.append("planner_finish_reason_must_be_stop")
    if planner_contract.get("reasoning_content_max_bytes") != 0:
        issues.append("planner_reasoning_content_must_be_disabled")
    survival_contract = PROTOCOL.get("validation_contract", {}).get("survival", {})
    reset_contract = PROTOCOL.get("reset_contract", {})
    if not M4_PLAYER_LIFECYCLE_VERIFIER_ID:
        issues.append("player_lifecycle_verifier_id_missing")
    if survival_contract.get("player_lifecycle_source") != "mineflayer_events":
        issues.append("player_lifecycle_source_mismatch")
    if survival_contract.get("player_lifecycle_observation_required") is not True:
        issues.append("player_lifecycle_observation_must_be_required")
    if survival_contract.get("player_lifecycle_event_required") is not True:
        issues.append("player_lifecycle_event_must_be_required")
    if survival_contract.get("active_episode_death_count") != 0:
        issues.append("active_episode_deaths_must_be_zero")
    if survival_contract.get("active_episode_respawn_count") != 0:
        issues.append("active_episode_respawns_must_be_zero")
    if survival_contract.get("uninterrupted_survival_required") is not True:
        issues.append("uninterrupted_survival_must_be_required")
    if reset_contract.get("establish_player_lifecycle_baseline") is not True:
        issues.append("player_lifecycle_baseline_must_be_reset")
    if reset_contract.get("player_lifecycle_source") != "mineflayer_events":
        issues.append("reset_player_lifecycle_source_mismatch")
    return {
        "passed": not issues,
        "issues": issues,
        "protocol_sha256": PROTOCOL_SHA256,
        **expected,
    }


def task_spec(task_id: str) -> dict:
    return TASKS_BY_ID.get(str(task_id or "").upper().strip(), {})


def task_contract(task_id: str) -> dict:
    return TASK_CONTRACTS_BY_ID.get(str(task_id or "").upper().strip(), {})


def task_contract_sha256(task_id: str) -> str:
    return TASK_CONTRACT_SHA256_BY_ID.get(str(task_id or "").upper().strip(), "")


def task_contract_integrity_report(task_id: str) -> dict:
    normalized = str(task_id or "").upper().strip()
    if normalized == "BM-011":
        return {"passed": True, "issues": [], "task_id": normalized, "contract_sha256": ""}
    contract = task_contract(normalized)
    task = task_spec(normalized)
    issues = []

    def require(name: str, passed: bool):
        if not passed:
            issues.append(name)

    require("contract_present", bool(contract))
    require("contract_type", contract.get("type") == "m4_task_contract")
    require("contract_schema", contract.get("schema_version") == 1)
    require("contract_profile", contract.get("profile") == PROTOCOL["profile"])
    require("contract_base_protocol", contract.get("base_protocol_sha256") == PROTOCOL_SHA256)
    require("contract_task", contract.get("task_id") == normalized)
    require("task_present", bool(task))
    require("task_name", contract.get("name") == task.get("name"))
    require("task_terminal_goal", contract.get("terminal_goal") == task.get("terminal_goal"))
    require("task_duration", contract.get("max_duration_s") == task.get("max_duration_s"))
    require("task_success_criteria", contract.get("success_criteria") == task.get("success_criteria"))
    require(
        "task_goal_limit",
        contract.get("max_autonomous_goals") == PROTOCOL["limits"]["max_autonomous_goals"],
    )
    require(
        "task_cycle_limit",
÷n4¶‰žËkºwµçM•ÍÌ‰t€ô…±Í”(€€€€€€€É•ÑÕÉ¸É•Á½ÉÐ(€€€¥˜É•ÅÕ•ÍÑ•€ôôAI=Q==1}M!ÈÔØè(€€€€€€€É•ÑÕÉ¸•Ù…±Õ…Ñ•}´Ñ}•Á¥Í½‘”¡•Ù•¹ÑÌ°É•ÍÕ±Ð°ÁÉ•™±¥¡Ð°µ…¹¥™•ÍÐ°Ñ…Í­}¥¤((€€€Ý¥Ñ }AI=Q==1}IA1e}1=,è(€€€€€€€…Ñ¥Ù•}Í¡„ÈÔØ€ôAI=Q==1}M!ÈÔØ(€€€€€€€…Ñ¥Ù•}±±´€ôAI=Q==0¹•Ð ‰±±´ˆ¤(€€€€€€€½¹ÑÉ…Ð€ôQM-}=9QIQM}	e}%¹•Ð¡Ñ…Í­}¥¤(€€€€€€€…Ñ¥Ù•}½¹ÑÉ…Ñ}‰…Í”€ô½¹ÑÉ…Ð¹•Ð ‰‰…Í•}ÁÉ½Ñ½½±}Í¡„ÈÔØˆ¤¥˜½¹ÑÉ…Ð•±Í”9½¹”(€€€€€€€…Ñ¥Ù•}½¹ÑÉ…Ñ}Í¡„ÈÔØ€ôQM-}=9QIQ}M!ÈÔÙ}	e}%¹•Ð¡Ñ…Í­}¥¤(€€€€€€€ÑÉäè(€€€€€€€€€€€AI=Q==1}M!ÈÔØ€ôÉ•ÅÕ•ÍÑ•(€€€€€€€€€€€AI=Q==1l‰±±´‰t€ô‘¥Ð¡}MUAIM}114¤(€€€€€€€€€€€¥˜½¹ÑÉ…Ð¥Ì¹½Ð9½¹”è(€€€€€€€€€€€€€€€½¹ÑÉ…Ñl‰‰…Í•}ÁÉ½Ñ½½±}Í¡„ÈÔØ‰t€ôÉ•ÅÕ•ÍÑ•(€€€€€€€€€€€€€€€QM-}=9QIQ}M!ÈÔÙ}	e}%mÑ…Í­}¥‘t€ô}MUAIM}	4ÀÄÉ}=9QIQ}M!ÈÔØ(€€€€€€€€€€€É•ÑÕÉ¸•Ù…±Õ…Ñ•}´Ñ}•Á¥Í½‘”¡•Ù•¹ÑÌ°É•ÍÕ±Ð°ÁÉ•™±¥¡Ð°µ…¹¥™•ÍÐ°Ñ…Í­}¥¤(€€€€€€€™¥¹…±±äè(€€€€€€€€€€€AI=Q==1}M!ÈÔØ€ô…Ñ¥Ù•}Í¡„ÈÔØ(€€€€€€€€€€€AI=Q==1l‰±±´‰t€ô…Ñ¥Ù•}±±´(€€€€€€€€€€€¥˜½¹ÑÉ…Ð¥Ì¹½Ð9½¹”è(€€€€€€€€€€€€€€€½¹ÑÉ…Ñl‰‰…Í•}ÁÉ½Ñ½½±}Í¡„ÈÔØ‰t€ô…Ñ¥Ù•}½¹ÑÉ…Ñ}‰…Í”(€€€€€€€€€€€€€€€QM-}=9QIQ}M!ÈÔÙ}	e}%mÑ…Í­}¥‘t€ô…Ñ¥Ù•}½¹ÑÉ…Ñ}Í¡„ÈÔØ(()‘•˜}…Ñ¥Ù•}•Á¥Í½‘•}•Ù•¹ÑÌ¡•Ù•¹ÑÌè±¥ÍÑm‘¥Ñt¤€´ø±¥ÍÑm‘¥Ñtè(€€€ÍÑ…ÉÐ€ô¹•áÐ ¡¥¹‘•à™½È¥¹‘•à°•Ù•¹Ð¥¸•¹Õµ•É…Ñ”¡•Ù•¹ÑÌ¤¥˜•Ù•¹Ð¹•Ð ‰ÑåÁ”ˆ¤€ôô€‰…ÕÑ½¹½µ½ÕÍ}ÍÑ…ÉÐˆ¤°9½¹”¤(€€€¥˜ÍÑ…ÉÐ¥Ì9½¹”è(€€€€€€€É•ÑÕÉ¸mt(€€€•¹€ô¹•áÐ (€€€€€€€€¡¥¹‘•à™½È¥¹‘•à¥¸É…¹”¡ÍÑ…ÉÐ°±•¸¡•Ù•¹ÑÌ¤¤¥˜•Ù•¹ÑÍm¥¹‘•át¹•Ð ‰ÑåÁ”ˆ¤€ôô€‰…ÕÑ½¹½µ½ÕÍ}•¹ˆ¤°(€€€€€€€±•¸¡•Ù•¹ÑÌ¤€´€Ä°(€€€€¤(€€€É•ÑÕÉ¸m•Ù•¹Ð™½È•Ù•¹Ð¥¸•Ù•¹ÑÍmÍÑ…ÉÐé•¹€¬€Åt¥˜¥Í¥¹ÍÑ…¹”¡•Ù•¹Ð°‘¥Ð¥t(()‘•˜}™½É‰¥‘‘•¹}…Ñ¥Ù•}•Ù•¹ÑÌ¡•Ù•¹ÑÌè±¥ÍÑm‘¥Ñt¤€´ø±¥ÍÑmÍÑÉtè(€€€™½É‰¥‘‘•¸€ôÍ•Ð¡AI=Q==1l‰É•Í•Ñ}½¹ÑÉ…Ð‰ul‰…Ñ¥Ù•}•Á¥Í½‘•}™½É‰¥‘‘•¹}½µµ…¹‘Ì‰t¤(€€€™½Õ¹€ômt(€€€™½È•Ù•¹Ð¥¸•Ù•¹ÑÌè(€€€€€€€•Ù•¹Ñ}ÑåÁ”€ôÍÑÈ¡•Ù•¹Ð¹•Ð ‰ÑåÁ”ˆ¤½È€ˆˆ¤(€€€€€€€‘…Ñ„€ô•Ù•¹Ð¹•Ð ‰‘…Ñ„ˆ°íô¤¥˜¥Í¥¹ÍÑ…¹”¡•Ù•¹Ð¹•Ð ‰‘…Ñ„ˆ¤°‘¥Ð¤•±Í”íô(€€€€€€€½µµ…¹€ôÍÑÈ¡‘…Ñ„¹•Ð ‰½µµ…¹ˆ¤½È‘…Ñ„¹•Ð ‰‰…­•¹‘}½µµ…¹ˆ¤½È€ˆˆ¤¹±½Ý•È ¤(€€€€€€€¥˜•Ù•¹Ñ}ÑåÁ”¥¸ì‰‰•¹¡µ…É­}É•Í•Ðˆ°€‰É•Í•Ñ}‰•¹¡µ…É¬‰ôè(€€€€€€€€€€€™½Õ¹¹…ÁÁ•¹¡•Ù•¹Ñ}ÑåÁ”¤(€€€€€€€¥˜½µµ…¹¥¸™½É‰¥‘‘•¸½È…¹ä¡Ñ½­•¸¥¸½µµ…¹™½ÈÑ½­•¸¥¸€ ‰Ñ¥µ”Í•Ðˆ°€‰…µ•µ½‘”ˆ°€‰Ñ•±•Á½ÉÐˆ°€‰¥Ù”ˆ¤¤è(€€€€€€€€€€€™½Õ¹¹…ÁÁ•¹¡½µµ…¹½È•Ù•¹Ñ}ÑåÁ”¤(€€€€€€€…Ñ¥½¸€ô‘…Ñ„¹•Ð ‰…Ñ¥½¸ˆ°íô¤¥˜¥Í¥¹ÍÑ…¹”¡‘…Ñ„¹•Ð ‰…Ñ¥½¸ˆ¤°‘¥Ð¤•±Í”íô(€€€€€€€Á…É…µÌ€ô…Ñ¥½¸¹•Ð ‰Á…É…µ•Ñ•ÉÌˆ°íô¤¥˜¥Í¥¹ÍÑ…¹”¡…Ñ¥½¸¹•Ð ‰Á…É…µ•Ñ•ÉÌˆ¤°‘¥Ð¤•±Í”íô(€€€€€€€µ•ÍÍ…”€ôÍÑÈ¡Á…É…µÌ¹•Ð ‰µ•ÍÍ…”ˆ¤½È€ˆˆ¤¹±½Ý•È ¤(€€€€€€€¥˜…Ñ¥½¸¹•Ð ‰ÑåÁ”ˆ¤€ôô€‰¡…Ðˆ…¹…¹ä¡Ñ½­•¸¥¸µ•ÍÍ…”™½ÈÑ½­•¸¥¸€ ˆ½Ñ¥µ”ˆ°€ˆ½…µ•µ½‘”ˆ°€ˆ½ÑÀˆ°€ˆ½Ñ•±•Á½ÉÐˆ°€ˆ½¥Ù”ˆ¤¤è(€€€€€€€€€€€™½Õ¹¹…ÁÁ•¹¡µ•ÍÍ…”¹ÍÁ±¥Ð ¥lÁt¤(€€€É•ÑÕÉ¸Í½ÉÑ•¡Í•Ð¡™½Õ¹¤¤(()‘•˜}ÅÕ…É…¹Ñ¥¹•‘}Í­¥±±}ÕÍ•¡•Ù•¹ÑÌè±¥ÍÑm‘¥Ñt¤€´ø‰½½°è(€€€É•ÑÕÉ¸…¹ä (€€€€€€€•Ù•¹Ð¹•Ð ‰ÑåÁ”ˆ¤¥¸ì‰Í­¥±±}Í•±•Ñ•ˆ°€‰Í­¥±±}•á•ÕÑ¥½¹}ÍÑ…ÉÐ‰ô(€€€€€€€…¹ÍÑÈ ¡•Ù•¹Ð¹•Ð ‰‘…Ñ„ˆ¤½Èíô¤¹•Ð ‰ÍÑ…ÑÕÌˆ¤½È€ˆˆ¤¹±½Ý•È ¤€ôô€‰ÅÕ…É…¹Ñ¥¹•ˆ(€€€€€€€™½È•Ù•¹Ð¥¸•Ù•¹ÑÌ(€€€€¤(()‘•˜}ÍÑÉ…Ñ•¥}É½½Ñ}Í­¥±±}ÕÍ•¡•Ù•¹ÑÌè±¥ÍÑm‘¥Ñt¤€´ø‰½½°è(€€€ÁÉ½¡¥‰¥Ñ•€ôÍ•Ð¡AI=Q==1l‰Ù…±¥‘…Ñ¥½¹}½¹ÑÉ…Ð‰ul‰Í­¥±±Ì‰ul‰ÁÉ½¡¥‰¥Ñ•‘}É½½Ñ}Í­¥±±Ì‰t¤(€€€É•ÑÕÉ¸…¹ä (€€€€€€€•Ù•¹Ð¹•Ð ‰ÑåÁ”ˆ¤¥¸ì‰Í­¥±±}Í•±•Ñ•ˆ°€‰Í­¥±±}•á•ÕÑ¥½¹}ÍÑ…ÉÐ‰ô(€€€€€€€…¹ÍÑÈ ¡•Ù•¹Ð¹•Ð ‰‘…Ñ„ˆ¤½Èíô¤¹•Ð ‰Í­¥±±}¹…µ”ˆ¤½È€¡•Ù•¹Ð¹•Ð ‰‘…Ñ„ˆ¤½Èíô¤¹•Ð ‰Í­¥±°ˆ¤½È€ˆˆ¤¥¸ÁÉ½¡¥‰¥Ñ•(€€€€€€€…¹€¡•Ù•¹Ð¹•Ð ‰‘…Ñ„ˆ¤½Èíô¤¹•Ð ‰É½½Ñ}½…°ˆ¤¥ÌQÉÕ”(€€€€€€€™½È•Ù•¹Ð¥¸•Ù•¹ÑÌ(€€€€¤(()‘•˜}…Ñ¥½¹}½‰Í•ÉÙ…Ñ¥½¸¡•Ù•¹Ðè‘¥Ð°­•äèÍÑÈ¤€´ø‰½½°è(€€€‘…Ñ„€ô•Ù•¹Ð¹•Ð ‰‘…Ñ„ˆ°íô¤¥˜¥Í¥¹ÍÑ…¹”¡•Ù•¹Ð¹•Ð ‰‘…Ñ„ˆ¤°‘¥Ð¤•±Í”íô(€€€É•ÑÕÉ¸¥Í¥¹ÍÑ…¹”¡‘…Ñ„¹•Ð¡­•ä¤°‘¥Ð¤…¹‰½½°¡‘…Ñ„¹•Ð¡­•ä¤¤(()‘•˜}…Ñ¥½¹}Ù•É¥™¥•É}ÁÉ•Í•¹Ð¡•Ù•¹Ðè‘¥Ð¤€´ø‰½½°è(€€€‘…Ñ„€ô•Ù•¹Ð¹•Ð ‰‘…Ñ„ˆ°íô¤¥˜¥Í¥¹ÍÑ…¹”¡•Ù•¹Ð¹•Ð ‰‘…Ñ„ˆ¤°‘¥Ð¤•±Í”íô(€€€É•ÍÕ±Ð€ô‘…Ñ„¹•Ð ‰É•ÍÕ±Ðˆ°íô¤¥˜¥Í¥¹ÍÑ…¹”¡‘…Ñ„¹•Ð ‰É•ÍÕ±Ðˆ¤°‘¥Ð¤•±Í”íô(€€€É•ÑÕÉ¸¥Í¥¹ÍÑ…¹”¡É•ÍÕ±Ð¹•Ð ‰…Ñ¥½¹}Ù•É¥™¥…Ñ¥½¸ˆ¤°‘¥Ð¤…¹‰½½°¡É•ÍÕ±Ð¹•Ð ‰…Ñ¥½¹}Ù•É¥™¥…Ñ¥½¸ˆ¤¤(()‘•˜}±¥™•å±•}‰…Í•±¥¹•}Í¥¹…ÑÕÉ”¡Ù…±Õ”¤€´øÑÕÁ±”è(€€€±¥™•å±”€ôÙ…±Õ”¥˜¥Í¥¹ÍÑ…¹”¡Ù…±Õ”°‘¥Ð¤•±Í”íô(€€€™¥•±‘Ì€ô€ (€€€€€€€€‰Ù•É¥™¥•É}¥ˆ°(€€€€€€€€‰Í½ÕÉ”ˆ°(€€€€€€€€‰ÁÉ½™¥±”ˆ°(€€€€€€€€‰ÁÉ½Ñ½½±}Í¡„ÈÔØˆ°(€€€€€€€€‰ÑÉ…­•É}¥ˆ°(€€€€€€€€‰•Á¥Í½‘•}¥ˆ°(€€€€€€€€‰±•Ù•±}¹…µ”ˆ°(€€€€€€€€‰‰…Í•±¥¹•}¥ˆ°(€€€€€€€€‰‰…Í•±¥¹•}‘•…Ñ¡}½Õ¹Ñ}Ñ½Ñ…°ˆ°(€€€€€€€€‰‰…Í•±¥¹•}É•ÍÁ…Ý¹}½Õ¹Ñ}Ñ½Ñ…°ˆ°(€€€€€€€€‰‰…Í•±¥¹•}ÍÁ…Ý¹}½Õ¹Ñ}Ñ½Ñ…°ˆ°(€€€€€€€€‰‰…Í•±¥¹•}½‰Í•ÉÙ•‘}…Ñ}µÌˆ°(€€€€€€€€‰‰…Í•±¥¹•}‰É¥‘•}µ½¹½Ñ½¹¥}µÌˆ°(€€€€¤(€€€Í¥¹…ÑÕÉ”€ôÑÕÁ±”¡±¥™•å±”¹•Ð¡¹…µ”¤™½È¹…µ”¥¸™¥•±‘Ì¤(€€€É•ÑÕÉ¸Í¥¹…ÑÕÉ”¥˜…±°¡Ù…±Õ”¥Ì¹½Ð9½¹”…¹Ù…±Õ”€„ô€ˆˆ™½ÈÙ…±Õ”¥¸Í¥¹…ÑÕÉ”¤•±Í”€ ¤(()‘•˜}±¥™•å±•}Ñ•Éµ¥¹…±}Í¥¹…ÑÕÉ”¡Ù…±Õ”¤€´øÑÕÁ±”è(€€€±¥™•å±”€ôÙ…±Õ”¥˜¥Í¥¹ÍÑ…¹”¡Ù…±Õ”°‘¥Ð¤•±Í”íô(€€€‰…Í•±¥¹”€ô}±¥™•å±•}‰…Í•±¥¹•}Í¥¹…ÑÕÉ”¡±¥™•å±”¤(€€€¥˜¹½Ð‰…Í•±¥¹”è(€€€€€€€É•ÑÕÉ¸€ ¤(€€€É•ÑÕÉ¸‰…Í•±¥¹”€¬ÑÕÁ±” (€€€€€€€±¥™•å±”¹•Ð¡¹…µ”¤(€€€€€€€™½È¹…µ”¥¸€ (€€€€€€€€€€€€‰‘•…Ñ¡}½Õ¹Ñ}Ñ½Ñ…°ˆ°(€€€€€€€€€€€€‰É•ÍÁ…Ý¹}½Õ¹Ñ}Ñ½Ñ…°ˆ°(€€€€€€€€€€€€‰ÍÁ…Ý¹}½Õ¹Ñ}Ñ½Ñ…°ˆ°(€€€€€€€€€€€€‰‘•…Ñ¡}½Õ¹Ðˆ°(€€€€€€€€€€€€‰É•ÍÁ…Ý¹}½Õ¹Ðˆ°(€€€€€€€€€€€€‰ÍÁ…Ý¹}½Õ¹Ðˆ°(€€€€€€€€€€€€‰Á•¹‘¥¹}É•ÍÁ…Ý¹}½Õ¹Ðˆ°(€€€€€€€€€€€€‰Õ¹¥¹Ñ•ÉÉÕÁÑ•ˆ°(€€€€€€€€¤(€€€€¤(()‘•˜}Ñ•Éµ¥¹…±}Ù•É¥™¥…Ñ¥½¹}µ…Ñ¡•Ì¡•Ù•¹ÑÌè±¥ÍÑm‘¥Ñt°½‰Í•ÉÙ…Ñ¥½¸è‘¥Ð°Ñ•Éµ¥¹…±}ÍÑ…Ñ”è‘¥Ð¤€´ø‰½½°è(€€€Ù•É¥™¥…Ñ¥½¸€ô¹•áÐ (€€€€€€€€ (€€€€€€€€€€€•Ù•¹Ð¹•Ð ‰‘…Ñ„ˆ°íô¤™½È•Ù•¹Ð¥¸É•Ù•ÉÍ•¡•Ù•¹ÑÌ¤(€€€€€€€€€€€¥˜•Ù•¹Ð¹•Ð ‰ÑåÁ”ˆ¤€ôô€‰Ñ•Éµ¥¹…±}ÍÕÉÙ¥Ù…±}Ù•É¥™¥…Ñ¥½¸ˆ…¹¥Í¥¹ÍÑ…¹”¡•Ù•¹Ð¹•Ð ‰‘…Ñ„ˆ¤°‘¥Ð¤(€€€€€€€€¤°(€€€€€€€íô°(€€€€¤(€€€¥˜Ù•É¥™¥…Ñ¥½¸¹•Ð ‰Á…ÍÍ•ˆ¤¥Ì¹½ÐQÉÕ”½ÈÙ•É¥™¥…Ñ¥½¸¹•Ð ‰Í½ÕÉ”ˆ¤€„ô€‰µ…¡¥¹•}ÍÑ…Ñ”ˆè(€€€€€€€É•ÑÕÉ¸…±Í”(€€€½‰Í•ÉÙ•‘}Ñ¥µ”€ô}¹½Éµ…±¥é•‘}Ñ¥µ”¡½‰Í•ÉÙ…Ñ¥½¸¹•Ð ‰Ñ¥µ•}½™}‘…äˆ¤¤(€€€Ù•É¥™¥•‘}Ñ¥µ”€ô}¹½Éµ…±¥é•‘}Ñ¥µ”¡Ù•É¥™¥…Ñ¥½¸¹•Ð ‰Ñ¥µ•}½™}‘…äˆ¤¤(€€€½‰Í•ÉÙ•‘}±¥™•å±”€ô½‰Í•ÉÙ…Ñ¥½¸¹•Ð ‰Á±…å•É}±¥™•å±”ˆ¤(€€€Ñ•Éµ¥¹…±}±¥™•å±”€ôÑ•Éµ¥¹…±}ÍÑ…Ñ”¹•Ð ‰Á±…å•É}±¥™•å±”ˆ¤(€€€Ù•É¥™¥•‘}±¥™•å±”€ôÙ•É¥™¥…Ñ¥½¸¹•Ð ‰Á±…å•É}±¥™•å±”ˆ¤(€€€±¥™•å±•}É•Á½ÉÐ€ôÙ…±¥‘…Ñ•}´Ñ}Á±…å•É}±¥™•å±” (€€€€€€€Ù•É¥™¥•‘}±¥™•å±”°(€€€€€€€•Á¥Í½‘•}¥õÍÑÈ ¡½‰Í•ÉÙ•‘}±¥™•å±”½Èíô¤¹•Ð ‰•Á¥Í½‘•}¥ˆ¤½È€ˆˆ¤°(€€€€€€€É•ÅÕ¥É•}Õ¹¥¹Ñ•ÉÉÕÁÑ•õQÉÕ”°(€€€€¤(€€€É•ÑÕÉ¸‰½½° (€€€€€€€½‰Í•ÉÙ•‘}Ñ¥µ”¥Ì¹½Ð9½¹”(€€€€€€€…¹Ù•É¥™¥•‘}Ñ¥µ”€ôô½‰Í•ÉÙ•‘}Ñ¥µ”(€€€€€€€…¹Ù•É¥™¥…Ñ¥½¸¹•Ð ‰¡•…±Ñ ˆ¤€ôô½‰Í•ÉÙ…Ñ¥½¸¹•Ð ‰¡•…±Ñ ˆ°Ñ•Éµ¥¹…±}ÍÑ…Ñ”¹•Ð ‰¡•…±Ñ ˆ¤¤(€€€€€€€…¹Ù•É¥™¥…Ñ¥½¸¹•Ð ‰‰½Ñ}½¹¹•Ñ•ˆ¤¥ÌQÉÕ”(€€€€€€€…¹±¥™•å±•}É•Á½ÉÑl‰Á…ÍÍ•‰t(€€€€€€€…¹}±¥™•å±•}Ñ•Éµ¥¹…±}Í¥¹…ÑÕÉ”¡Ù•É¥™¥•‘}±¥™•å±”¤(€€€€€€€€ôô}±¥™•å±•}Ñ•Éµ¥¹…±}Í¥¹…ÑÕÉ”¡½‰Í•ÉÙ•‘}±¥™•å±”¤(€€€€€€€€ôô}±¥™•å±•}Ñ•Éµ¥¹…±}Í¥¹…ÑÕÉ”¡Ñ•Éµ¥¹…±}±¥™•å±”¤(€€€€¤(()‘•˜}Ñ•Éµ¥¹…±}É•Í½ÕÉ•}Ù•É¥™¥…Ñ¥½¹}µ…Ñ¡•Ì (€€€•Ù•¹ÑÌè±¥ÍÑm‘¥Ñt°(€€€½‰Í•ÉÙ…Ñ¥½¸è‘¥Ð°(€€€Ñ•Éµ¥¹…±}ÍÑ…Ñ”è‘¥Ð°(€€€½¹ÑÉ…Ðè‘¥Ð°(¤€´ø‰½½°è(€€€Ù•É¥™¥•È€ô½¹ÑÉ…Ð¹•Ð ‰Ñ•Éµ¥¹…±}Ù•É¥™¥•Èˆ°íô¤¥˜¥Í¥¹ÍÑ…¹”¡½¹ÑÉ…Ð°‘¥Ð¤•±Í”íô(€€€•Ù•¹Ñ}ÑåÁ”€ôÍÑÈ¡Ù•É¥™¥•È¹•Ð ‰•Ù•¹Ñ}ÑåÁ”ˆ¤½È€ˆˆ¤(€€€Ù•É¥™¥…Ñ¥½¸€ô¹•áÐ (€€€€€€€€ (€€€€€€€€€€€•Ù•¹Ð¹•Ð ‰‘…Ñ„ˆ°íô¤(€€€€€€€€€€€™½È•Ù•¹Ð¥¸É•Ù•ÉÍ•¡•Ù•¹ÑÌ¤(€€€€€€€€€€€¥˜•Ù•¹Ð¹•Ð ‰ÑåÁ”ˆ¤€ôô•Ù•¹Ñ}ÑåÁ”…¹¥Í¥¹ÍÑ…¹”¡•Ù•¹Ð¹•Ð ‰‘…Ñ„ˆ¤°‘¥Ð¤(€€€€€€€€¤°(€€€€€€€íô°(€€€€¤(€€€½‰Í•ÉÙ•‘}¥¹Ù•¹Ñ½Éä€ô}¥¹Ù•¹Ñ½Éå}½Õ¹ÑÌ¡½‰Í•ÉÙ…Ñ¥½¸¹•Ð ‰¥¹Ù•¹Ñ½Éäˆ¤¤(€€€Ñ•Éµ¥¹…±}¥¹Ù•¹Ñ½Éä€ô}¥¹Ù•¹Ñ½Éå}½Õ¹ÑÌ¡Ñ•Éµ¥¹…±}ÍÑ…Ñ”¹•Ð ‰¥¹Ù•¹Ñ½Éäˆ¤¤(€€€Ù•É¥™¥•‘}¥¹Ù•¹Ñ½Éä€ô}¥¹Ù•¹Ñ½Éå}½Õ¹ÑÌ¡Ù•É¥™¥…Ñ¥½¸¹•Ð ‰¥¹Ù•¹Ñ½Éäˆ¤¤(€€€ÅÕ…±¥™å¥¹}¥Ñ•´€ôÍÑÈ¡Ù•É¥™¥…Ñ¥½¸¹•Ð ‰ÅÕ…±¥™å¥¹}¥Ñ•´ˆ¤½È€ˆˆ¤(€€€É¥Ñ•É¥„€ô½¹ÑÉ…Ð¹•Ð ‰ÍÕ•ÍÍ}É¥Ñ•É¥„ˆ°íô¤¹•Ð ‰¥¹Ù•¹Ñ½Éå}…¹äˆ°íô¤(€€€É•ÅÕ¥É•‘}½Õ¹Ð€ôÉ¥Ñ•É¥„¹•Ð¡ÅÕ…±¥™å¥¹}¥Ñ•´¤(€€€½‰Í•ÉÙ•‘}±¥™•å±”€ô½‰Í•ÉÙ…Ñ¥½¸¹•Ð ‰Á±…å•É}±¥™•å±”ˆ¤(€€€Ñ•Éµ¥¹…±}±¥™•å±”€ôÑ•Éµ¥¹…±}ÍÑ…Ñ”¹•Ð ‰Á±…å•É}±¥™•å±”ˆ¤(€€€Ù•É¥™¥•‘}±¥™•å±”€ôÙ•É¥™¥…Ñ¥½¸¹•Ð ‰Á±…å•É}±¥™•å±”ˆ¤(€€€±¥™•å±•}É•Á½ÉÐ€ôÙ…±¥‘…Ñ•}´Ñ}Á±…å•É}±¥™•å±” (€€€€€€€Ù•É¥™¥•‘}±¥™•å±”°(€€€€€€€•Á¥Í½‘•}¥õÍÑÈ ¡½‰Í•ÉÙ•‘}±¥™•å±”½Èíô¤¹•Ð ‰•Á¥Í½‘•}¥ˆ¤½È€ˆˆ¤°(€€€€€€€É•ÅÕ¥É•}Õ¹¥¹Ñ•ÉÉÕÁÑ•õQÉÕ”°(€€€€¤(€€€É•ÑÕÉ¸‰½½° (€€€€€€€Ù•É¥™¥…Ñ¥½¸¹•Ð ‰ÑåÁ”ˆ¤€ôôÙ•É¥™¥•È¹•Ð ‰Á…å±½…‘}ÑåÁ”ˆ¤(€€€€€€€…¹Ù•É¥™¥…Ñ¥½¸¹•Ð ‰Á…ÍÍ•ˆ¤¥ÌQÉÕ”(€€€€€€€…¹Ù•É¥™¥…Ñ¥½¸¹•Ð ‰Í½ÕÉ”ˆ¤€ôôÙ•É¥™¥•È¹•Ð ‰Í½ÕÉ”ˆ¤(€€€€€€€…¹Ù•É¥™¥…Ñ¥½¸¹•Ð ‰Ñ…Í­}¥ˆ¤€ôô½¹ÑÉ…Ð¹•Ð ‰Ñ…Í­}¥ˆ¤(€€€€€€€…¹Ù•É¥™¥…Ñ¥½¸¹•Ð ‰Ù•É¥™¥•É}¥ˆ¤€ôôÙ•É¥™¥•È¹•Ð ‰¥ˆ¤(€€€€€€€…¹Ù•É¥™¥…Ñ¥½¸¹•Ð ‰Ñ…Í­}½¹ÑÉ…Ñ}¥ˆ¤€ôô½¹ÑÉ…Ð¹•Ð ‰¥ˆ¤(€€€€€€€…¹Ù•É¥™¥…Ñ¥½¸¹•Ð ‰Ñ…Í­}½¹ÑÉ…Ñ}Í¡„ÈÔØˆ¤€ôôÑ…Í­}½¹ÑÉ…Ñ}Í¡„ÈÔØ¡½¹ÑÉ…Ð¹•Ð ‰Ñ…Í­}¥ˆ¤¤(€€€€€€€…¹ÅÕ…±¥™å¥¹}¥Ñ•´¥¸É¥Ñ•É¥„(€€€€€€€…¹¥Í¥¹ÍÑ…¹”¡É•ÅÕ¥É•‘}½Õ¹Ð°¥¹Ð¤(€€€€€€€…¹¹½Ð¥Í¥¹ÍÑ…¹”¡É•ÅÕ¥É•‘}½Õ¹Ð°‰½½°¤(€€€€€€€…¹Ù•É¥™¥…Ñ¥½¸¹•Ð ‰É•ÅÕ¥É•‘}½Õ¹Ðˆ¤€ôôÉ•ÅÕ¥É•‘}½Õ¹Ð(€€€€€€€…¹Ù•É¥™¥…Ñ¥½¸¹•Ð ‰½‰Í•ÉÙ•‘}½Õ¹Ðˆ¤€ôô½‰Í•ÉÙ•‘}¥¹Ù•¹Ñ½Éä¹•Ð¡ÅÕ…±¥™å¥¹}¥Ñ•´¤(€€€€€€€…¹½‰Í•ÉÙ•‘}¥¹Ù•¹Ñ½Éä¹•Ð¡ÅÕ…±¥™å¥¹}¥Ñ•´°€À¤€øôÉ•ÅÕ¥É•‘}½Õ¹Ð(€€€€€€€…¹½‰Í•ÉÙ•‘}¥¹Ù•¹Ñ½Éä€ôôÑ•Éµ¥¹…±}¥¹Ù•¹Ñ½Éä€ôôÙ•É¥™¥•‘}¥¹Ù•¹Ñ½Éä(€€€€€€€…¹Ù•É¥™¥…Ñ¥½¸¹•Ð ‰¡•…±Ñ ˆ¤€ôô½‰Í•ÉÙ…Ñ¥½¸¹•Ð ‰¡•…±Ñ ˆ°Ñ•Éµ¥¹…±}ÍÑ…Ñ”¹•Ð ‰¡•…±Ñ ˆ¤¤(€€€€€€€…¹Ù•É¥™¥…Ñ¥½¸¹•Ð ‰‰½Ñ}½¹¹•Ñ•ˆ¤¥ÌQÉÕ”(€€€€€€€…¹±¥™•å±•}É•Á½ÉÑl‰Á…ÍÍ•‰t(€€€€€€€…¹}±¥™•å±•}Ñ•Éµ¥¹…±}Í¥¹…ÑÕÉ”¡Ù•É¥™¥•‘}±¥™•å±”¤(€€€€€€€€ôô}±¥™•å±•}Ñ•Éµ¥¹…±}Í¥¹…ÑÕÉ”¡½‰Í•ÉÙ•‘}±¥™•å±”¤(€€€€€€€€ôô}±¥™•å±•}Ñ•Éµ¥¹…±}Í¥¹…ÑÕÉ”¡Ñ•Éµ¥¹…±}±¥™•å±”¤(€€€€¤(()‘•˜}É•Í½ÕÉ•}…ÅÕ¥Í¥Ñ¥½¹}É•Á½ÉÐ (€€€•Ù•¹ÑÌè±¥ÍÑm‘¥Ñt°(€€€½‰Í•ÉÙ…Ñ¥½¹Ìè±¥ÍÑm‘¥Ñt°(€€€Ñ•Éµ¥¹…±}ÍÑ…Ñ”è‘¥Ð°(€€€½¹ÑÉ…Ðè‘¥Ð°(¤€´ø‘¥Ðè(€€€É¥Ñ•É¥„€ô½¹ÑÉ…Ð¹•Ð ‰ÍÕ•ÍÍ}É¥Ñ•É¥„ˆ°íô¤¹•Ð ‰¥¹Ù•¹Ñ½Éå}…¹äˆ°íô¤(€€€Ñ…É•Ñ}¥Ñ•µÌ€ôÑÕÁ±”¡ÍÑÈ¡¥Ñ•´¤™½È¥Ñ•´¥¸É¥Ñ•É¥„¤(€€€Í½ÕÉ•}‰±½­Ì€ôÍ•Ð¡½¹ÑÉ…Ð¹•Ð ‰Ñ•Éµ¥¹…±}Ù•É¥™¥•Èˆ°íô¤¹•Ð ‰Í½ÕÉ•}‰±½­Ìˆ°mt¤¤(€€€¥¹¥Ñ¥…±}¥¹Ù•¹Ñ½Éä€ô}¥¹Ù•¹Ñ½Éå}½Õ¹ÑÌ ¡½‰Í•ÉÙ…Ñ¥½¹ÍlÁt¥˜½‰Í•ÉÙ…Ñ¥½¹Ì•±Í”íô¤¹•Ð ‰¥¹Ù•¹Ñ½Éäˆ¤¤(€€€Ñ•Éµ¥¹…±}½‰Í•ÉÙ…Ñ¥½¸€ô½‰Í•ÉÙ…Ñ¥½¹Íl´Åt¥˜½‰Í•ÉÙ…Ñ¥½¹Ì•±Í”íô(€€€Ñ•Éµ¥¹…±}¥¹Ù•¹Ñ½Éä€ô}¥¹Ù•¹Ñ½Éå}½Õ¹ÑÌ (€€€€€€€Ñ•Éµ¥¹…±}½‰Í•ÉÙ…Ñ¥½¸¹•Ð ‰¥¹Ù•¹Ñ½Éäˆ°Ñ•Éµ¥¹…±}ÍÑ…Ñ”¹•Ð ‰¥¹Ù•¹Ñ½Éäˆ¤¤(€€€€¤(€€€Í½ÕÉ•}…Ñ¥½¹Ì€ômt(€€€™½È¥¹‘•à°•Ù•¹Ð¥¸•¹Õµ•É…Ñ”¡•Ù•¹ÑÌ¤è(€€€€€€€¥˜•Ù•¹Ð¹•Ð ‰ÑåÁ”ˆ¤€„ô€‰…Ñ¥½¸ˆ½È¹½Ð¥Í¥¹ÍÑ…¹”¡•Ù•¹Ð¹•Ð ‰‘…Ñ„ˆ¤°‘¥Ð¤è(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€‘…Ñ„€ô•Ù•¹Ñl‰‘…Ñ„‰t(€€€€€€€…Ñ¥½¸€ô‘…Ñ„¹•Ð ‰…Ñ¥½¸ˆ°íô¤¥˜¥Í¥¹ÍÑ…¹”¡‘…Ñ„¹•Ð ‰…Ñ¥½¸ˆ¤°‘¥Ð¤•±Í”íô(€€€€€€€É•ÍÕ±Ð€ô‘…Ñ„¹•Ð ‰É•ÍÕ±Ðˆ°íô¤¥˜¥Í¥¹ÍÑ…¹”¡‘…Ñ„¹•Ð ‰É•ÍÕ±Ðˆ¤°‘¥Ð¤•±Í”íô(€€€€€€€‰•™½É•}‰±½¬€ôÉ•ÍÕ±Ð¹•Ð ‰Ñ…É•Ñ}‰±½­}‰•™½É”ˆ°íô¤(€€€€€€€‰•™½É•}‰±½¬€ô‰•™½É•}‰±½¬¥˜¥Í¥¹ÍÑ…¹”¡‰•™½É•}‰±½¬°‘¥Ð¤•±Í”íô(€€€€€€€¥˜€ (€€€€€€€€€€€…Ñ¥½¸¹•Ð ‰ÑåÁ”ˆ¤€„ô½¹ÑÉ…Ð¹•Ð ‰Ñ•Éµ¥¹…±}Ù•É¥™¥•Èˆ°íô¤¹•Ð ‰É•ÅÕ¥É•‘}…Ñ¥½¹}ÑåÁ”ˆ¤(€€€€€€€€€€€½ÈÉ•ÍÕ±Ð¹•Ð ‰ÍÕ•ÍÌˆ¤¥Ì¹½ÐQÉÕ”(€€€€€€€€€€€½ÈÉ•ÍÕ±Ð¹•Ð ‰‰±½­}É•µ½Ù•ˆ¤¥Ì¹½ÐQÉÕ”(€€€€€€€€€€€½ÈÍÑÈ¡‰•™½É•}‰±½¬¹•Ð ‰¹…µ”ˆ¤½È€ˆˆ¤¹½Ð¥¸Í½ÕÉ•}‰±½­Ì(€€€€€€€€¤è(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€Í½ÕÉ•}…Ñ¥½¹Ì¹…ÁÁ•¹¡ì(€€€€€€€€€€€€‰•Ù•¹Ñ}¥¹‘•àˆè¥¹‘•à€¬€Ä°(€€€€€€€€€€€€‰‰±½¬ˆèÍÑÈ¡‰•™½É•}‰±½¬¹•Ð ‰¹…µ”ˆ¤½È€ˆˆ¤°(€€€€€€€€€€€€‰Á½Í¥Ñ¥½¸ˆè‰•™½É•}‰±½¬¹•Ð ‰Á½Í¥Ñ¥½¸ˆ°íô¤°(€€€€€€€ô¤(€€€ÅÕ…±¥™å¥¹}¥Ñ•µÌ€ôl(€€€€€€€¥Ñ•´(€€€€€€€™½È¥Ñ•´°É•ÅÕ¥É•¥¸É¥Ñ•É¥„¹¥Ñ•µÌ ¤(€€€€€€€¥˜Ñ•Éµ¥¹…±}¥¹Ù•¹Ñ½Éä¹•Ð¡¥Ñ•´°€À¤€øô¥¹Ð¡É•ÅÕ¥É•¤(€€€t(€€€Á½Í¥Ñ¥Ù•}‘•±Ñ„€ôì(€€€€€€€¥Ñ•´èÑ•Éµ¥¹…±}¥¹Ù•¹Ñ½Éä¹•Ð¡¥Ñ•´°€À¤€´¥¹¥Ñ¥…±}¥¹Ù•¹Ñ½Éä¹•Ð¡¥Ñ•´°€À¤(€€€€€€€™½È¥Ñ•´¥¸Ñ…É•Ñ}¥Ñ•µÌ(€€€ô(€€€É•ÑÕÉ¸ì(€€€€€€€€‰Ñ…É•Ñ}¥Ñ•µÌˆè±¥ÍÐ¡Ñ…É•Ñ}¥Ñ•µÌ¤°(€€€€€€€€‰¥¹¥Ñ¥…±}¥¹Ù•¹Ñ½Éäˆèí¥Ñ•´è¥¹¥Ñ¥…±}¥¹Ù•¹Ñ½Éä¹•Ð¡¥Ñ•´°€À¤™½È¥Ñ•´¥¸Ñ…É•Ñ}¥Ñ•µÍô°(€€€€€€€€‰Ñ•Éµ¥¹…±}¥¹Ù•¹Ñ½Éäˆèí¥Ñ•´èÑ•Éµ¥¹…±}¥¹Ù•¹Ñ½Éä¹•Ð¡¥Ñ•´°€À¤™½È¥Ñ•´¥¸Ñ…É•Ñ}¥Ñ•µÍô°(€€€€€€€€‰¥¹¥Ñ¥…±}Ñ…É•Ñ}½Õ¹ÐˆèÍÕ´¡¥¹¥Ñ¥…±}¥¹Ù•¹Ñ½Éä¹•Ð¡¥Ñ•´°€À¤™½È¥Ñ•´¥¸Ñ…É•Ñ}¥Ñ•µÌ¤°(€€€€€€€€‰ÅÕ…±¥™å¥¹}¥Ñ•µÌˆèÅÕ…±¥™å¥¹}¥Ñ•µÌ°(€€€€€€€€‰Ñ•Éµ¥¹…±}Ñ…É•Ñ}Á…ÍÍ•ˆè‰½½°¡ÅÕ…±¥™å¥¹}¥Ñ•µÌ¤°(€€€€€€€€‰Á½Í¥Ñ¥Ù•}¥¹Ù•¹Ñ½Éå}‘•±Ñ„ˆèÁ½Í¥Ñ¥Ù•}‘•±Ñ„°(€€€€€€€€‰Á½Í¥Ñ¥Ù•}¥¹Ù•¹Ñ½Éå}‘•±Ñ…}Á…ÍÍ•ˆè…¹ä (€€€€€€€€€€€Á½Í¥Ñ¥Ù•}‘•±Ñ„¹•Ð¡¥Ñ•´°€À¤€øô¥¹Ð¡É¥Ñ•É¥…m¥Ñ•µt¤™½È¥Ñ•´¥¸ÅÕ…±¥™å¥¹}¥Ñ•µÌ(€€€€€€€€¤°(€€€€€€€€‰ÍÕ•ÍÍ™Õ±}Í½ÕÉ•}…Ñ¥½¹}½Õ¹Ðˆè±•¸¡Í½ÕÉ•}…Ñ¥½¹Ì¤°(€€€€€€€€‰ÍÕ•ÍÍ™Õ±}Í½ÕÉ•}…Ñ¥½¹ÌˆèÍ½ÕÉ•}…Ñ¥½¹Ì°(€€€ô(()‘•˜}¹…ÑÕÉ…±}Ñ¥µ•}ÁÉ½É•ÍÍ¥½¸¡Ñ¥µ•Ìè±¥ÍÑm¥¹Ñt¤€´ø‰½½°è(€€€¥˜±•¸¡Ñ¥µ•Ì¤€ð€Èè(€€€€€€€É•ÑÕÉ¸…±Í”(€€€µ…á¥µÕµ}…À€ô¥¹Ð¡AI=Q==1l‰Ù…±¥‘…Ñ¥½¹}½¹ÑÉ…Ð‰ul‰ÍÕÉÙ¥Ù…°‰ul‰µ…á¥µÕµ}½‰Í•ÉÙ…Ñ¥½¹}Ñ¥­}…À‰t¤(€€€‘•±Ñ…Ì€ôm¥¹Ð ¡ÕÉÉ•¹Ð€´ÁÉ•Ù¥½ÕÌ¤€”€ÈÐÀÀÀ¤™½ÈÁÉ•Ù¥½ÕÌ°ÕÉÉ•¹Ð¥¸é¥À¡Ñ¥µ•Ì°Ñ¥µ•ÍlÄét¥t(€€€É•ÑÕÉ¸…¹ä¡‘•±Ñ„€ø€À™½È‘•±Ñ„¥¸‘•±Ñ…Ì¤…¹…±° À€ðô‘•±Ñ„€ðôµ…á¥µÕµ}…À™½È‘•±Ñ„¥¸‘•±Ñ…Ì¤(()‘•˜}Á½ÍÑ}‘•…‘±¥¹•}•á•ÕÑ¥½¸¡•Ù•¹ÑÌè±¥ÍÑm‘¥Ñt°‘•…‘±¥¹”è™±½…Ðð9½¹”¤€´ø‰½½°è(€€€¥˜‘•…‘±¥¹”¥Ì9½¹”è(€€€€€€€É•ÑÕÉ¸QÉÕ”(€€€•á•ÕÑ…‰±•}ÑåÁ•Ì€ôì‰…ÕÑ½}½…°ˆ°€‰Á±…¸ˆ°€‰…Ñ¥½¸ˆ°€‰Í­¥±±}•á•ÕÑ¥½¹}ÍÑ…ÉÐ‰ô(€€€™½È•Ù•¹Ð¥¸•Ù•¹ÑÌè(€€€€€€€¥˜•Ù•¹Ð¹•Ð ‰ÑåÁ”ˆ¤¹½Ð¥¸•á•ÕÑ…‰±•}ÑåÁ•Ìè(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€Ù…±Õ”€ô}•Ù•¹Ñ}µ½¹½Ñ½¹¥Œ¡•Ù•¹Ð¤(€€€€€€€¥˜Ù…±Õ”¥Ì9½¹”½ÈÙ…±Õ”€øô‘•…‘±¥¹”è(€€€€€€€€€€€É•ÑÕÉ¸QÉÕ”(€€€É•ÑÕÉ¸…±Í”(()‘•˜}•Ù•¹Ñ}µ½¹½Ñ½¹¥Œ¡•Ù•¹Ðè‘¥Ð¤€´ø™±½…Ðð9½¹”è(€€€‘…Ñ„€ô•Ù•¹Ð¹•Ð ‰‘…Ñ„ˆ°íô¤¥˜¥Í¥¹ÍÑ…¹”¡•Ù•¹Ð¹•Ð ‰‘…Ñ„ˆ¤°‘¥Ð¤•±Í”íô(€€€É•ÑÕÉ¸}™¥¹¥Ñ•}½É}¹½¹”¡•Ù•¹Ð¹•Ð ‰µ½¹½Ñ½¹¥}Ìˆ°‘…Ñ„¹•Ð ‰µ½¹½Ñ½¹¥}Ìˆ¤¤¤(()‘•˜}É•ÍÕ±Ñ}‘ÕÉ…Ñ¥½¹}•±¥¥‰±”¡É•ÍÕ±Ðè‘¥Ð°Ñ…Í¬è‘¥Ð°Ñ…Í­}¥èÍÑÈ€ô€‰	4´ÀÄÄˆ¤€´ø‰½½°è(€€€‘ÕÉ…Ñ¥½¸€ô}™¥¹¥Ñ•}½É}¹½¹”¡É•ÍÕ±Ð¹•Ð ‰•±…ÁÍ•‘}Ìˆ¤¤(€€€½¹ÑÉ…Ð€ôÑ…Í­}½¹ÑÉ…Ð¡Ñ…Í­}¥¤(€€€•áÁ•Ñ•‘}É•…Í½¸€ô€ (€€€€€€€½¹ÑÉ…Ð¹•Ð ‰Ñ•Éµ¥¹…±}Ù•É¥™¥•Èˆ°íô¤¹•Ð ‰Ñ•Éµ¥¹…Ñ¥½¹}É•…Í½¸ˆ¤(€€€€€€€¥˜½¹ÑÉ…Ð(€€€€€€€•±Í”€‰Ñ•Éµ¥¹…±}ÍÕÉÙ¥Ù…±}Ù•É¥™¥•ˆ(€€€€¤(€€€É•ÑÕÉ¸‰½½° (€€€€€€€É•ÍÕ±Ð¹•Ð ‰½µÁ±•Ñ•ˆ¤¥ÌQÉÕ”(€€€€€€€…¹É•ÍÕ±Ð¹•Ð ‰Ñ•Éµ¥¹…Ñ¥½¹}É•…Í½¸ˆ¤€ôô•áÁ•Ñ•‘}É•…Í½¸(€€€€€€€…¹‘ÕÉ…Ñ¥½¸¥Ì¹½Ð9½¹”(€€€€€€€…¹‘ÕÉ…Ñ¥½¸€ðô™±½…Ð¡Ñ…Í­l‰µ…á}‘ÕÉ…Ñ¥½¹}Ì‰t¤(€€€€¤(()‘•˜}µ…ÁÁ¥¹}½¹Ñ…¥¹Ì¡…ÑÕ…°°•áÁ•Ñ•¤€´ø‰½½°è(€€€É•ÑÕÉ¸¥Í¥¹ÍÑ…¹”¡…ÑÕ…°°‘¥Ð¤…¹…±°¡…ÑÕ…°¹•Ð¡­•ä¤€ôôÙ…±Õ”™½È­•ä°Ù…±Õ”¥¸•áÁ•Ñ•¹¥Ñ•µÌ ¤¤(()‘•˜}¥¹Ù•¹Ñ½Éå}½Õ¹ÑÌ¡Ù…±Õ”¤€´ø‘¥ÑmÍÑÈ°¥¹Ñtè(€€€¥˜¹½Ð¥Í¥¹ÍÑ…¹”¡Ù…±Õ”°‘¥Ð¤è(€€€€€€€É•ÑÕÉ¸íô(€€€½Õ¹ÑÌ€ôíô(€€€™½È¹…µ”°É…Ý}½Õ¹Ð¥¸Ù…±Õ”¹¥Ñ•µÌ ¤è(€€€€€€€ÑÉäè(€€€€€€€€€€€½Õ¹Ð€ô¥¹Ð¡É…Ý}½Õ¹Ð½È€À¤(€€€€€€€•á•ÁÐ€¡QåÁ•ÉÉ½È°Y…±Õ•ÉÉ½È¤è(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¥˜¹…µ”…¹½Õ¹Ð€ø€Àè(€€€€€€€€€€€½Õ¹ÑÍmÍÑÈ¡¹…µ”¥t€ô½Õ¹Ð(€€€É•ÑÕÉ¸½Õ¹ÑÌ(()‘•˜}Á±…å•É}ÍÑ…Ñ•}µ…Ñ¡•Ì¡…ÑÕ…°è‘¥Ð¤€´ø‰½½°è(€€€•áÁ•Ñ•€ôAI=Q==1l‰¥¹¥Ñ¥…±}Á±…å•É}ÍÑ…Ñ”‰t(€€€É•ÑÕÉ¸¥Í¥¹ÍÑ…¹”¡…ÑÕ…°°‘¥Ð¤…¹…±°¡}¹Õµ‰•É}¹•…È¡…ÑÕ…°¹•Ð¡­•ä¤°Ù…±Õ”°€À¸ÈÔ¤™½È­•ä°Ù…±Õ”¥¸•áÁ•Ñ•¹¥Ñ•µÌ ¤¤(()‘•˜}¹Õµ‰•É}¹•…È¡Ù…±Õ”°•áÁ•Ñ•°Ñ½±•É…¹”è™±½…Ð¤€´ø‰½½°è(€€€É•ÑÕÉ¸}™¥¹¥Ñ•}¹Õµ‰•È¡Ù…±Õ”¤…¹…‰Ì¡™±½…Ð¡Ù…±Õ”¤€´™±½…Ð¡•áÁ•Ñ•¤¤€ðô™±½…Ð¡Ñ½±•É…¹”¤(()‘•˜}¹½Éµ…±¥é•‘}Ñ¥µ”¡Ù…±Õ”¤€´ø¥¹Ðð9½¹”è(€€€¹Õµ‰•È€ô}™¥¹¥Ñ•}½É}¹½¹”¡Ù…±Õ”¤(€€€É•ÑÕÉ¸¥¹Ð¡¹Õµ‰•È¤€”€ÈÐÀÀÀ¥˜¹Õµ‰•È¥Ì¹½Ð9½¹”•±Í”9½¹”(()‘•˜}™¥¹¥Ñ•}¹Õµ‰•È¡Ù…±Õ”¤€´ø‰½½°è(€€€É•ÑÕÉ¸}™¥¹¥Ñ•}½É}¹½¹”¡Ù…±Õ”¤¥Ì¹½Ð9½¹”(()‘•˜}™¥¹¥Ñ•}½É}¹½¹”¡Ù…±Õ”¤€´ø™±½…Ðð9½¹”è(€€€ÑÉäè(€€€€€€€¹Õµ‰•È€ô™±½…Ð¡Ù…±Õ”¤(€€€•á•ÁÐ€¡QåÁ•ÉÉ½È°Y…±Õ•ÉÉ½È¤è(€€€€€€€É•ÑÕÉ¸9½¹”(€€€É•ÑÕÉ¸¹Õµ‰•È¥˜µ…Ñ ¹¥Í™¥¹¥Ñ”¡¹Õµ‰•È¤•±Í”9½¹”(