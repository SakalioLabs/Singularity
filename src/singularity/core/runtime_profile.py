"""Runtime profile loading and validation for gated Agent startup."""
import json
import os
from typing import Any


LIST_FIELDS = {
    "goal_critic_gate_paths": ("gates", ("goal_critic", "goal_critic_gate", "goal_critic_gate_paths")),
    "mixed_policy_patch_paths": ("artifacts", ("mixed_policy_patch", "mixed_policy_patches", "mixed_policy_patch_paths")),
    "mixed_policy_gate_paths": ("gates", ("mixed_policy", "mixed_policy_gate", "mixed_policy_gate_paths")),
    "self_evolution_feedback_paths": ("artifacts", ("self_evolution_feedback", "self_evolution_feedback_paths")),
    "world_model_feedback_paths": ("artifacts", ("world_model_feedback", "world_model_feedback_paths")),
    "world_model_gate_paths": ("gates", ("world_model", "world_model_gate", "world_model_gate_paths")),
    "knowledge_correction_feedback_paths": ("artifacts", ("knowledge_correction_feedback", "knowledge_correction_feedback_paths")),
    "knowledge_correction_gate_paths": ("gates", ("knowledge_correction", "knowledge_correction_gate", "knowledge_correction_gate_paths")),
    "action_value_feedback_paths": ("artifacts", ("action_value_feedback", "action_value_feedback_paths")),
    "action_value_transition_gate_paths": ("gates", ("action_value_transition", "action_value_transition_gate", "action_value_transition_gate_paths")),
    "action_value_transition_evaluator_report_paths": (
        "gates",
        (
            "action_value_transition_evaluator",
            "action_value_transition_evaluator_report",
            "action_value_transition_evaluator_report_paths",
        ),
    ),
    "skill_memory_quality_feedback_paths": ("artifacts", ("skill_memory_quality_feedback", "skill_memory_quality_feedback_paths")),
    "skill_memory_quality_gate_paths": ("gates", ("skill_memory_quality", "skill_memory_quality_gate", "skill_memory_quality_gate_paths")),
    "skill_runtime_default_gate_paths": ("gates", ("skill_runtime_default", "skill_runtime_default_gate", "skill_runtime_default_gate_paths")),
    "coach_style_ablation_paths": ("artifacts", ("coach_style_ablation", "coach_style_ablation_paths")),
    "coach_style_gate_paths": ("gates", ("coach_style", "coach_style_gate", "coach_style_gate_paths")),
}


REQUIRED_GATES = {
    "goal_critic_gate_paths": ("enable_goal_critic",),
    "mixed_policy_gate_paths": ("mixed_policy_patch_paths",),
    "world_model_gate_paths": ("world_model_feedback_paths",),
    "knowledge_correction_gate_paths": ("knowledge_correction_feedback_paths",),
    "skill_memory_quality_gate_paths": ("skill_memory_quality_feedback_paths",),
    "coach_style_gate_paths": ("coach_style", "coach_style_ablation_paths"),
}


GATE_FIELDS = {
    "goal_critic_gate_paths",
    "mixed_policy_gate_paths",
    "world_model_gate_paths",
    "knowledge_correction_gate_paths",
    "action_value_transition_gate_paths",
    "action_value_transition_evaluator_report_paths",
    "skill_memory_quality_gate_paths",
    "skill_runtime_default_gate_paths",
    "coach_style_gate_paths",
}


ARTIFACT_FIELDS = set(LIST_FIELDS) - GATE_FIELDS


def _canonical_profile_key(field: str) -> tuple[str, str]:
    section, keys = LIST_FIELDS[field]
    return section, keys[0]


def dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _as_list(value: Any) -> list[str]:
    if value in (None, "", [], {}):
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item]
    return [str(value)]


def _profile_values(profile: dict, section: str, keys: tuple[str, ...]) -> list[str]:
    values = []
    section_payload = profile.get(section, {}) if isinstance(profile.get(section, {}), dict) else {}
    for key in keys:
        values.extend(_as_list(section_payload.get(key)))
        values.extend(_as_list(profile.get(key)))
    return values


def load_runtime_profiles(paths: list[str]) -> tuple[list[dict], list[str]]:
    profiles = []
    errors = []
    for path in paths or []:
        if not path:
            continue
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                raise ValueError("runtime profile JSON must be an object")
            profile = dict(payload)
            profile["_profile_path"] = path
            profiles.append(profile)
        except Exception as e:
            errors.append(f"{path}: {e}")
    return profiles, errors


def collect_profile_list(profiles: list[dict], field: str) -> list[str]:
    section, keys = LIST_FIELDS.get(field, ("", (field,)))
    values = []
    for profile in profiles or []:
        if not isinstance(profile, dict):
            continue
        values.extend(_profile_values(profile, section, keys))
    return dedupe(values)


def merge_arg_profile_list(args, attr: str, profiles: list[dict], field: str) -> list[str]:
    return dedupe(_as_list(getattr(args, attr, [])) + collect_profile_list(profiles, field))


def profile_setting(profiles: list[dict], *keys: str):
    for profile in reversed(profiles or []):
        if not isinstance(profile, dict):
            continue
        settings = profile.get("settings", {}) if isinstance(profile.get("settings", {}), dict) else {}
        for key in keys:
            if key in settings:
                return settings[key]
            if key in profile:
                return profile[key]
    return None


def profile_bool_arg(args, attr: str, profiles: list[dict], *keys: str) -> bool:
    if bool(getattr(args, attr, False)):
        return True
    return _truthy(profile_setting(profiles, *keys))


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _setting_required(value) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"", "0", "false", "no", "off", "disabled", "none"}:
        return False
    return bool(value)


def profile_str_arg(args, attr: str, profiles: list[dict], *keys: str, default: str = "") -> str:
    value = getattr(args, attr, default)
    if value not in (None, "", default):
        return str(value)
    setting = profile_setting(profiles, *keys)
    if setting in (None, ""):
        return default
    return str(setting)


def build_runtime_profile_payload(
    name: str = "",
    description: str = "",
    settings: dict = None,
    path_fields: dict = None,
) -> dict:
    """Build a reusable runtime profile from canonical gate/artifact fields."""
    payload = {"type": "runtime_profile"}
    if name:
        payload["name"] = str(name)
    if description:
        payload["description"] = str(description)
    cleaned_settings = {
        str(key): value
        for key, value in (settings or {}).items()
        if value not in (None, "", [], {})
    }
    if cleaned_settings:
        payload["settings"] = cleaned_settings
    sections = {"gates": {}, "artifacts": {}}
    for field, values in (path_fields or {}).items():
        if field not in LIST_FIELDS:
            continue
        cleaned = dedupe(_as_list(values))
        if not cleaned:
            continue
        section, key = _canonical_profile_key(field)
        sections[section][key] = cleaned
    for section, values in sections.items():
        if values:
            payload[section] = values
    return payload


def build_runtime_profile_report(profile_paths: list[str]) -> dict:
    profiles, errors = load_runtime_profiles(profile_paths)
    return build_runtime_profile_report_from_profiles(
        profiles,
        profile_paths=profile_paths,
        load_errors=errors,
    )


def build_runtime_profile_report_from_profiles(
    profiles: list[dict],
    profile_paths: list[str] = None,
    load_errors: list[str] = None,
) -> dict:
    report = {
        "type": "runtime_profile_validation",
        "readiness": "review",
        "decision": "hold_runtime_profile",
        "reason": "runtime profile needs approved gate evidence",
        "profile_paths": list(profile_paths or []),
        "profile_count": len(profiles or []),
        "gate_count": 0,
        "approved_gate_count": 0,
        "artifact_count": 0,
        "artifact_paths": {},
        "gate_reports": [],
        "settings": {},
        "missing": [],
        "errors": list(load_errors or []),
    }
    if not profile_paths:
        report["missing"].append("runtime_profile")
    for field in sorted(ARTIFACT_FIELDS):
        values = collect_profile_list(profiles, field)
        if values:
            report["artifact_paths"][field] = values
            report["artifact_count"] += len(values)
            for value in values:
                if not os.path.exists(value):
                    report["errors"].append(f"{field}: missing artifact path {value}")
    settings = {
        "enable_goal_critic": _truthy(profile_setting(profiles, "enable_goal_critic", "goal_critic")),
        "coach_style": str(profile_setting(profiles, "coach_style") or ""),
    }
    report["settings"] = {key: value for key, value in settings.items() if value not in ("", False, None)}

    for field in sorted(GATE_FIELDS):
        paths = collect_profile_list(profiles, field)
        if not paths:
            continue
        for path in paths:
            summary = _gate_summary(field, path)
            report["gate_reports"].append(summary)
            report["gate_count"] += 1
            if summary.get("readiness") == "approved":
                report["approved_gate_count"] += 1
            if summary.get("error"):
                report["errors"].append(f"{path}: {summary['error']}")

    _add_missing_runtime_profile_requirements(report, profiles)
    readinesses = [gate.get("readiness", "unknown") for gate in report["gate_reports"]]
    if report["errors"]:
        report["readiness"] = "error"
        report["decision"] = "reject_runtime_profile"
        report["reason"] = "runtime profile inputs could not be loaded"
    elif any(readiness == "rejected" for readiness in readinesses):
        report["readiness"] = "rejected"
        report["decision"] = "reject_runtime_profile"
        report["reason"] = "runtime profile includes rejected gate reports"
    elif any(readiness not in {"approved"} for readiness in readinesses):
        report["readiness"] = "review"
        report["decision"] = "hold_runtime_profile"
        report["reason"] = "runtime profile includes review or unknown gate reports"
    elif report["missing"]:
        report["readiness"] = "review"
        report["decision"] = "hold_runtime_profile"
        report["reason"] = "runtime profile is missing required gates"
    elif profiles:
        report["readiness"] = "approved"
        report["decision"] = "allow_runtime_profile"
        report["reason"] = "runtime profile gates and artifact paths are ready"
    return report


def _gate_summary(field: str, path: str) -> dict:
    summary = {
        "field": field,
        "path": path,
        "readiness": "error",
        "decision": "",
        "reason": "",
        "type": "",
    }
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            raise ValueError("gate JSON must be an object")
        summary.update({
            "readiness": str(payload.get("readiness", "") or "unknown").strip().lower(),
            "decision": str(payload.get("decision", "") or ""),
            "reason": str(payload.get("reason", "") or "")[:300],
            "type": str(payload.get("type", "") or ""),
        })
    except Exception as e:
        summary["error"] = str(e)
    return summary


def _add_missing_runtime_profile_requirements(report: dict, profiles: list[dict]):
    if not profiles:
        return
    for gate_field, requirements in REQUIRED_GATES.items():
        gate_paths = collect_profile_list(profiles, gate_field)
        required = False
        for requirement in requirements:
            if requirement in LIST_FIELDS:
                required = required or bool(collect_profile_list(profiles, requirement))
            else:
                required = required or _setting_required(profile_setting(profiles, requirement))
        if required and not gate_paths:
            report["missing"].append(gate_field)
    report["missing"] = dedupe(report["missing"])
