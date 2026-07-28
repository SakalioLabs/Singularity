import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    ROOT / "workspace" / "evals" / "m4_gemini36_provider_migration_20260728.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_gemini36_migration_binds_protocol_probe_and_sources():
    migration = json.loads(MIGRATION_PATH.read_text(encoding="utf-8"))
    assert migration["type"] == "m4_provider_migration_gate"
    assert migration["model"] == "gemini-3.6-flash-high"
    assert migration["runtime_modalities"] == ["text"]
    assert migration["wsl_inspection_performed"] is False
    assert migration["protocol_sha256"] == _sha256(
        ROOT / "src" / "singularity" / "data" / "m4_protocol.json"
    )
    for task_id, name in {
        "BM-012": "m4_bm012_protocol.json",
        "BM-013": "m4_bm013_protocol.json",
        "BM-014": "m4_bm014_protocol.json",
    }.items():
        assert migration["task_contract_sha256"][task_id] == _sha256(
            ROOT / "src" / "singularity" / "data" / name
        )
    assert migration["provider_probe_sha256"] == _sha256(
        ROOT / migration["provider_probe_path"]
    )
    for key, path in {
        "provider": "src/singularity/llm/provider.py",
        "protocol_evaluator": "src/singularity/evaluation/m4_protocol.py",
        "live_observer": "scripts/m4_live_observer.js",
        "runtime": "scripts/m4-runtime.ps1",
    }.items():
        assert migration["source_sha256"][key] == _sha256(ROOT / path)
    assert migration["probe_56_authorized"] is False
