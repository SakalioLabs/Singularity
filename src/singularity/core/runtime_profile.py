"""Runtime profile loading and validation for gated Agent startup."""
import hashlib
import json
import os
from typing import Any

from singularity.core.memory_policy import promptware_threat_flags


LIST_FIELDS = {
    "goal_critic_gate_paths": ("gates", ("goal_critic", "goal_critic_gate", "goal_critic_gate_paths")),
    "mixed_policy_patch_paths": ("artifacts", ("mixed_policy_patch", "mixed_policy_patches", "mixed_policy_patch_paths")),
    "mixed_policy_gate_paths": ("gates", ("mixed_policy", "mixed_policy_gate", "mixed_policy_gate_paths")),
    "self_evolution_feedback_paths": ("artifacts", ("self_evolution_feedback", "self_evolution_feedback_paths")),
    "world_model_feedback_paths": ("artifacts", ("world_model_feedback", "world_model_feedback_paths")),
    "world_model_gate_paths": ("gates", ("world_model", "world_model_gate", "world_model_gate_paths")),
    "knowledge_correction_feedback_paths": ("artifacts", ("knowledge_correction_feedback", "knowledge_correction_feedback_paths")),
    "knowledge_correction_gate_paths": ("gates", ("knowledge_correction", "knowledge_correction_gate", "knowledge_correction_gate_paths")),
    "task_precondition_feedback_paths": ("artifacts", ("task_precondition_feedback", "task_precondition_feedback_paths")),
    "task_precondition_gate_paths": ("gates", ("task_precondition", "task_precondition_gate", "task_precondition_gate_paths")),
    "plan_cache_paths": ("artifacts", ("plan_cache", "plan_transition_cache", "plan_cache_paths")),
    "plan_cache_gate_paths": ("gates", ("plan_cache", "plan_cache_gate", "plan_cache_gate_paths")),
    "memory_attribution_gate_paths": ("gates", ("memory_attribution", "memory_attribution_gate", "memory_attribution_gate_paths")),
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
    "memory_promptware_gate_paths": ("gates", ("memory_promptware", "memory_promptware_gate", "memory_promptware_gate_paths")),
    "coach_style_ablation_paths": ("artifacts", ("coach_style_ablation", "coach_style_ablation_paths")),
    "coach_style_gate_paths": ("gates", ("coach_style", "coach_style_gate", "coach_style_gate_paths")),
}


REQUIRED_GATES = {
    "goal_critic_gate_paths": ("enable_goal_critic",),
    "mixed_policy_gate_paths": ("mixed_policy_patch_paths",),
    "world_model_gate_paths": ("world_model_feedback_paths",),
    "knowledge_correction_gate_paths": ("knowledge_correction_feedback_paths",),
    "task_precondition_gate_paths": ("task_precondition_feedback_paths",),
    "skill_memory_quality_gate_paths": ("skill_memory_quality_feedback_paths",),
    "coach_style_gate_paths": ("coach_style", "coach_style_ablation_paths"),
    "memory_promptware_gate_paths": ("enforce_memory_write_gate",),
    "plan_cache_gate_paths": ("enable_plan_cache", "plan_cache_paths"),
    "memory_attribution_gate_paths": ("enable_weighted_memory_retrieval", "weighted_memory_retrieval"),
}


GATE_FIELDS = {
    "goal_critic_gate_paths",
    "mixed_policy_gate_paths",
    "world_model_gate_paths",
    "knowledge_correction_gate_paths",
    "task_precondition_gate_paths",
    "action_value_transition_gate_paths",
    "action_value_transition_evaluator_report_paths",
    "skill_memory_quality_gate_paths",
    "skill_runtime_default_gate_paths",
    "memory_promptware_gate_paths",
    "memory_attribution_gate_paths",
    "plan_cache_gate_paths",
    "coach_style_gate_paths",
}


ARTIFACT_FIELDS = set(LIST_FIELDS) - GATE_FIELDS


DEFAULT_SECURITY_SCAN_BYTES = 2_000_000
DEFAULT_SECURITY_MAX_FINDINGS = 50


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


def discover_runtime_profile_paths(runtime_dir: str) -> list[str]:
    """Return stable JSON runtime profile paths from a runtime profile directory."""
    runtime_dir = str(runtime_dir or "").strip()
    if not runtime_dir or not os.path.isdir(runtime_dir):
        return []
    paths = []
    for name in sorted(os.listdir(runtime_dir)):
        if name.startswith(".") or not name.lower().endswith(".json"):
            continue
        path = os.path.join(runtime_dir, name)
        if os.path.isfile(path):
            paths.append(path)
    return paths


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
        "enable_plan_cache": _truthy(profile_setting(profiles, "enable_plan_cache", "plan_cache")),
        "enable_weighted_memory_retrieval": _truthy(profile_setting(profiles, "enable_weighted_memory_retrieval", "weighted_memory_retrieval")),
        "enforce_memory_write_gate": _truthy(profile_setting(profiles, "enforce_memory_write_gate", "memory_write_gate")),
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
    if _truthy(profile_setting(profiles, "enable_plan_cache", "plan_cache")) and not collect_profile_list(profiles, "plan_cache_paths"):
        report["missing"].append("plan_cache_paths")
    report["missing"] = dedupe(report["missing"])


def build_runtime_profile_security_audit(
    profile_paths: list[str],
    include_gates: bool = False,
    max_scan_bytes: int = DEFAULT_SECURITY_SCAN_BYTES,
    max_findings: int = DEFAULT_SECURITY_MAX_FINDINGS,
) -> dict:
    """Audit profile-referenced artifacts for promptware-like payloads."""
    profiles, errors = load_runtime_profiles(profile_paths)
    return build_runtime_profile_security_audit_from_profiles(
        profiles,
        profile_paths=profile_paths,
        load_errors=errors,
        include_gates=include_gates,
        max_scan_bytes=max_scan_bytes,
        max_findings=max_findings,
    )


def build_runtime_profile_security_audit_from_profiles(
    profiles: list[dict],
    profile_paths: list[str] = None,
    load_errors: list[str] = None,
    include_gates: bool = False,
    max_scan_bytes: int = DEFAULT_SECURITY_SCAN_BYTES,
    max_findings: int = DEFAULT_SECURITY_MAX_FINDINGS,
) -> dict:
    """Scan artifacts referenced by runtime profiles before live startup.

    Findings intentionally avoid raw content snippets. Reports may be saved to
    disk, so they expose only path metadata, JSON location, threat flags, and a
    hash of the scanned unit.
    """
    max_scan_bytes = max(1, int(max_scan_bytes or DEFAULT_SECURITY_SCAN_BYTES))
    max_findings = max(1, int(max_findings or DEFAULT_SECURITY_MAX_FINDINGS))
    scan_fields = set(ARTIFACT_FIELDS)
    if include_gates:
        scan_fields.update(GATE_FIELDS)
    report = {
        "type": "runtime_profile_security_audit",
        "readiness": "review",
        "decision": "hold_runtime_profile_security",
        "reason": "runtime profile artifacts need promptware audit",
        "profile_paths": list(profile_paths or []),
        "profile_count": len(profiles or []),
        "include_gates": bool(include_gates),
        "max_scan_bytes": max_scan_bytes,
        "scanned_path_count": 0,
        "scanned_record_count": 0,
        "finding_count": 0,
        "included_finding_count": 0,
        "high_risk_count": 0,
        "truncated_finding_count": 0,
        "references": [],
        "findings": [],
        "missing": [],
        "errors": list(load_errors or []),
    }
    if not profile_paths:
        report["missing"].append("runtime_profile")

    for field in sorted(scan_fields):
        for path in collect_profile_list(profiles, field):
            reference = _scan_runtime_profile_reference(
                field,
                path,
                max_scan_bytes=max_scan_bytes,
                remaining_findings=max_findings - len(report["findings"]),
            )
            report["references"].append(reference)
            if reference.get("scanned"):
                report["scanned_path_count"] += 1
                report["scanned_record_count"] += int(reference.get("scanned_record_count") or 0)
            for error in reference.get("errors", []):
                report["errors"].append(f"{field}: {path}: {error}")
            for finding in reference.get("findings", []):
                if len(report["findings"]) >= max_findings:
                    report["truncated_finding_count"] += 1
                    continue
                report["findings"].append(finding)
            report["high_risk_count"] += int(reference.get("high_risk_count") or 0)

    total_reference_findings = sum(int(reference.get("finding_count") or 0) for reference in report["references"])
    report["finding_count"] = total_reference_findings
    report["included_finding_count"] = len(report["findings"])
    if any(reference.get("finding_count", 0) for reference in report["references"]):
        report["truncated_finding_count"] += max(0, total_reference_findings - report["included_finding_count"])

    if report["errors"]:
        report["readiness"] = "error"
        report["decision"] = "reject_runtime_profile_security"
        report["reason"] = "runtime profile security audit could not scan every referenced input"
    elif report["high_risk_count"]:
        report["readiness"] = "rejected"
        report["decision"] = "reject_runtime_profile_security"
        report["reason"] = "runtime profile references promptware-like artifact content"
    elif report["finding_count"]:
        report["readiness"] = "review"
        report["decision"] = "hold_runtime_profile_security"
        report["reason"] = "runtime profile references artifacts that need security review"
    elif profiles:
        report["readiness"] = "approved"
        report["decision"] = "allow_runtime_profile_security"
        report["reason"] = "runtime profile artifacts passed promptware audit"
    return report


def build_runtime_profile_suite_report(
    profile_paths: list[str] = None,
    runtime_dir: str = "",
    required_profiles: list[str] = None,
    include_gates: bool = False,
    max_scan_bytes: int = DEFAULT_SECURITY_SCAN_BYTES,
    max_findings: int = DEFAULT_SECURITY_MAX_FINDINGS,
) -> dict:
    """Aggregate validation and promptware security checks across runtime profiles."""
    explicit_paths = dedupe(profile_paths or [])
    discovered_paths = discover_runtime_profile_paths(runtime_dir)
    paths = dedupe(explicit_paths + discovered_paths)
    required = dedupe([str(value or "").strip().lower() for value in (required_profiles or [])])
    report = {
        "type": "runtime_profile_suite_report",
        "readiness": "review",
        "decision": "hold_runtime_profile_suite",
        "reason": "runtime profile suite needs approved validation and security evidence",
        "runtime_dir": str(runtime_dir or ""),
        "explicit_profile_count": len(explicit_paths),
        "discovered_profile_count": len(discovered_paths),
        "profile_paths": paths,
        "profile_count": len(paths),
        "approved_profile_count": 0,
        "review_profile_count": 0,
        "rejected_profile_count": 0,
        "error_profile_count": 0,
        "required_profiles": required,
        "missing_required_profiles": [],
        "profiles": [],
        "errors": [],
    }
    if not paths:
        report["missing_required_profiles"] = list(required)
        report["errors"].append("no runtime profiles found")
        return report

    for path in paths:
        validation = build_runtime_profile_report([path])
        security = build_runtime_profile_security_audit(
            [path],
            include_gates=include_gates,
            max_scan_bytes=max_scan_bytes,
            max_findings=max_findings,
        )
        profiles, load_errors = load_runtime_profiles([path])
        name = ""
        description = ""
        if profiles:
            name = str(profiles[0].get("name", "") or "")
            description = str(profiles[0].get("description", "") or "")
        profile_item = {
            "path": path,
            "name": name,
            "description": description,
            "validation_readiness": validation.get("readiness", "unknown"),
            "validation_decision": validation.get("decision", ""),
            "validation_reason": validation.get("reason", ""),
            "security_readiness": security.get("readiness", "unknown"),
            "security_decision": security.get("decision", ""),
            "security_reason": security.get("reason", ""),
            "gate_count": validation.get("gate_count", 0),
            "approved_gate_count": validation.get("approved_gate_count", 0),
            "artifact_count": validation.get("artifact_count", 0),
            "scanned_path_count": security.get("scanned_path_count", 0),
            "finding_count": security.get("finding_count", 0),
            "high_risk_count": security.get("high_risk_count", 0),
            "missing": dedupe((validation.get("missing") or []) + (security.get("missing") or [])),
            "errors": dedupe((validation.get("errors") or []) + (security.get("errors") or []) + load_errors),
        }
        profile_item["readiness"] = _runtime_profile_suite_item_readiness(profile_item)
        profile_item["decision"] = _runtime_profile_suite_item_decision(profile_item)
        report["profiles"].append(profile_item)
        if profile_item["readiness"] == "approved":
            report["approved_profile_count"] += 1
        elif profile_item["readiness"] == "rejected":
            report["rejected_profile_count"] += 1
        elif profile_item["readiness"] == "error":
            report["error_profile_count"] += 1
        else:
            report["review_profile_count"] += 1
        for error in profile_item["errors"]:
            report["errors"].append(f"{path}: {error}")

    labels = {_runtime_profile_suite_label(path, item.get("name", "")) for path, item in zip(paths, report["profiles"])}
    missing_required = []
    for required_label in required:
        if not any(required_label in label for label in labels):
            missing_required.append(required_label)
    report["missing_required_profiles"] = missing_required

    if report["error_profile_count"]:
        report["readiness"] = "error"
        report["decision"] = "reject_runtime_profile_suite"
        report["reason"] = "one or more runtime profiles could not be loaded or scanned"
    elif report["rejected_profile_count"]:
        report["readiness"] = "rejected"
        report["decision"] = "reject_runtime_profile_suite"
        report["reason"] = "one or more runtime profiles failed validation or promptware security audit"
    elif missing_required:
        report["readiness"] = "review"
        report["decision"] = "hold_runtime_profile_suite"
        report["reason"] = "runtime profile suite is missing required profile coverage"
    elif report["review_profile_count"]:
        report["readiness"] = "review"
        report["decision"] = "hold_runtime_profile_suite"
        report["reason"] = "one or more runtime profiles still need gate or artifact review"
    elif report["approved_profile_count"] == report["profile_count"]:
        report["readiness"] = "approved"
        report["decision"] = "allow_runtime_profile_suite"
        report["reason"] = "all runtime profiles passed validation and promptware security audit"
    return report


def _runtime_profile_suite_item_readiness(profile_item: dict) -> str:
    readinesses = {
        str(profile_item.get("validation_readiness", "") or "unknown"),
        str(profile_item.get("security_readiness", "") or "unknown"),
    }
    if "error" in readinesses:
        return "error"
    if "rejected" in readinesses:
        return "rejected"
    if readinesses == {"approved"}:
        return "approved"
    return "review"


def _runtime_profile_suite_item_decision(profile_item: dict) -> str:
    readiness = profile_item.get("readiness", "review")
    if readiness == "approved":
        return "allow_runtime_profile"
    if readiness in {"error", "rejected"}:
        return "reject_runtime_profile"
    return "hold_runtime_profile"


def _runtime_profile_suite_label(path: str, name: str = "") -> str:
    parts = [
        str(path or "").replace("\\", "/").lower(),
        os.path.basename(str(path or "")).lower(),
        os.path.splitext(os.path.basename(str(path or "")))[0].lower(),
        str(name or "").lower(),
    ]
    return " ".join(part for part in parts if part)


def _scan_runtime_profile_reference(
    field: str,
    path: str,
    max_scan_bytes: int,
    remaining_findings: int,
) -> dict:
    reference = {
        "field": field,
        "path": path,
        "scanned": False,
        "bytes_scanned": 0,
        "is_json": False,
        "scanned_record_count": 0,
        "finding_count": 0,
        "high_risk_count": 0,
        "findings": [],
        "errors": [],
    }
    if not os.path.exists(path):
        reference["errors"].append("missing referenced path")
        return reference
    if os.path.isdir(path):
        reference["errors"].append("referenced path is a directory")
        return reference

    try:
        with open(path, "rb") as f:
            data = f.read(max_scan_bytes + 1)
    except Exception as e:
        reference["errors"].append(str(e))
        return reference

    if len(data) > max_scan_bytes:
        reference["errors"].append(f"referenced file exceeds max_scan_bytes={max_scan_bytes}")
        data = data[:max_scan_bytes]
    reference["bytes_scanned"] = len(data)
    reference["scanned"] = True
    text = data.decode("utf-8-sig", errors="replace")

    payload = None
    try:
        payload = json.loads(text)
        reference["is_json"] = True
    except Exception:
        payload = None

    units = list(_iter_runtime_profile_scan_units(payload if reference["is_json"] else text))
    if not units:
        units = [("$", text)]
    found = []
    for record_path, content in units:
        reference["scanned_record_count"] += 1
        flags = promptware_threat_flags(content)
        if not flags:
            continue
        finding = _runtime_profile_security_finding(field, path, record_path, content, flags)
        found.append(finding)
        if finding.get("severity") == "high":
            reference["high_risk_count"] += 1
        if len(reference["findings"]) < max(0, remaining_findings):
            reference["findings"].append(finding)

    if not found and reference["is_json"]:
        reference["scanned_record_count"] += 1
        flags = promptware_threat_flags(payload)
        if flags:
            finding = _runtime_profile_security_finding(field, path, "$", payload, flags)
            found.append(finding)
            if finding.get("severity") == "high":
                reference["high_risk_count"] += 1
            if len(reference["findings"]) < max(0, remaining_findings):
                reference["findings"].append(finding)

    reference["finding_count"] = len(found)
    return reference


def _iter_runtime_profile_scan_units(value, path: str = "$"):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            yield f"{path}.{_safe_record_path_part(key_text)}.__key__", key_text
            yield from _iter_runtime_profile_scan_units(
                child,
                f"{path}.{_safe_record_path_part(key_text)}",
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _iter_runtime_profile_scan_units(child, f"{path}[{index}]")


def _runtime_profile_security_finding(field: str, path: str, record_path: str, content, flags: list[str]) -> dict:
    content_hash = hashlib.sha256(content_text_for_hash(content).encode("utf-8", errors="replace")).hexdigest()
    return {
        "field": field,
        "path": path,
        "record_path": record_path,
        "severity": "high" if "promptware_threat" in flags else "review",
        "flags": sorted(set(flags)),
        "content_sha256": content_hash,
    }


def content_text_for_hash(content) -> str:
    try:
        return json.dumps(content, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        return str(content or "")


def _safe_record_path_part(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(value or ""))
    return cleaned[:80] or "field"
