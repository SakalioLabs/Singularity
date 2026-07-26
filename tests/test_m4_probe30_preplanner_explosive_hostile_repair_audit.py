import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = (
    ROOT
    / "workspace"
    / "evals"
    / "m4_probe30_preplanner_explosive_hostile_repair_audit.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_probe30_audit_binds_immutable_evidence_and_earliest_transition():
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    paths = {
        key: ROOT / value
        for key, value in audit["evidence_paths"].items()
    }
    assert {
        key: _sha256(path)
        for key, path in paths.items()
    } == audit["evidence_sha256"]

    events = [
        json.loads(line)
        for line in paths["raw_session_jsonl"].read_text(encoding="utf-8").splitlines()
    ]
    transition = audit["first_unrecovered_transition"]
    before = events[transition["preplanner_observation_line_index"]]
    planner = events[transition["planner_call_line_index"]]
    after = events[transition["postplanner_observation_line_index"]]

    creeper = before["data"]["nearby_entities"][0]
    assert before["type"] == "observation"
    assert before["data"]["health"] == transition["health_before"] == 20
    assert creeper["type"] == transition["hostile_type"] == "creeper"
    assert creeper["distance"] == transition["hostile_distance"] == 12.7
    assert planner["data"]["call_id"] == transition["planner_call_id"]
    assert planner["data"]["provider_metadata"]["duration_ms"] == 14938
    assert after["data"]["health"] == transition["health_after"]
    assert after["data"]["health"] < 2


def test_probe30_repair_is_bounded_and_grants_no_credit():
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    repair = audit["offline_repair"]
    assert repair["policy_id"] == "m4-preplanner-explosive-hostile-horizon-v1"
    assert repair["scope"] == "strict_m4_only"
    assert repair["explosive_hostile_types"] == ["creeper"]
    assert repair["explosive_interrupt_distance"] == 16.0
    assert repair["legacy_interrupt_distance_preserved"] == 8.0
    assert repair["non_m4_unchanged"] is True
    assert audit["counts_toward_bm012_success"] is False
    assert audit["counts_toward_capability"] is False
    assert audit["decision"]["probe_31_authorized"] is False
