"""Tests for CausalGame-style causal evidence audits."""

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, "src")

from singularity.evaluation.causal_evidence import build_causal_evidence_report


def _write_jsonl(path: str, events: list[dict]):
    with open(path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")


def _controlled_causal_events():
    return [
        {"type": "goal_start", "data": {"goal": "Discover whether lever power reaches lamps, then build a lamp circuit"}},
        {
            "type": "discovery_hypothesis",
            "data": {
                "knowledge_gap": "Need to know whether a lever powers adjacent dust into a lamp.",
                "hypothesis": "If lever power reaches redstone dust, a connected lamp should turn on.",
            },
        },
        {
            "type": "discovery_experiment",
            "data": {
                "experiment": "Place lever, dust, and lamp in a line.",
                "intervention": "Toggle the lever on.",
                "control": "Repeat the same lamp setup without redstone dust as a negative control.",
                "outcome": "Lamp turns on only when redstone dust connects lever and lamp.",
                "success": True,
                "bias_risks": ["hidden_confounder", "measurement_error"],
                "bias_mitigation": "Hold tool tier, location, and time of day constant; repeat and verify lamp state twice.",
            },
        },
        {
            "type": "memory_write",
            "data": {
                "layer": "causal",
                "memory_type": "causal_rule",
                "content": "If lever power reaches connected redstone dust, adjacent lamps receive power.",
                "source": "discovery_experiment",
            },
        },
        {
            "type": "discovery_consolidation",
            "data": {
                "rule": "Lever power propagates through connected dust into lamps.",
                "control": "Negative control without dust did not light the lamp.",
            },
        },
        {
            "type": "discovery_application",
            "data": {
                "goal": "Build a two-lamp circuit using the lever rule.",
                "success": True,
                "evidence": "Both lamps turned on after lever toggle.",
            },
        },
        {"type": "goal_verification", "data": {"achieved": True, "status": "achieved", "context": {"accepted": True}}},
        {"type": "goal_end", "data": {"goal": "Build a two-lamp circuit", "result": {"completed": True}}},
    ]


def _unsupported_causal_events():
    return [
        {"type": "goal_start", "data": {"goal": "Discover whether lever power reaches lamps"}},
        {
            "type": "discovery_hypothesis",
            "data": {
                "hypothesis": "If I place a lever near a lamp, the lamp will turn on.",
            },
        },
        {
            "type": "discovery_experiment",
            "data": {
                "experiment": "Place a lever next to a lamp.",
                "intervention": "Toggle the lever.",
                "outcome": "I think the lamp turned on.",
                "success": True,
            },
        },
        {
            "type": "memory_write",
            "data": {
                "layer": "causal",
                "memory_type": "causal_rule",
                "content": "Levers always power nearby lamps.",
                "source": "discovery_experiment",
            },
        },
        {
            "type": "discovery_application",
            "data": {
                "goal": "Build a two-lamp circuit from the rule.",
                "success": False,
                "error": "Second lamp did not turn on.",
            },
        },
        {"type": "goal_verification", "data": {"achieved": False, "status": "failed", "context": {"accepted": False}}},
        {"type": "goal_end", "data": {"goal": "Build a two-lamp circuit", "result": {"completed": False}}},
    ]


def test_causal_evidence_report_approves_controlled_claims():
    tmpdir = tempfile.mkdtemp()
    log_path = os.path.join(tmpdir, "controlled.jsonl")
    _write_jsonl(log_path, _controlled_causal_events())

    report = build_causal_evidence_report([log_path])
    case = report["cases"][0]

    assert report["readiness"] == "approved"
    assert report["contrast_control_count"] >= 1
    assert report["unresolved_counterexample_count"] == 0
    assert report["causal_memory_write_count"] == 1
    assert case["causal_evidence_score"] >= 0.9
    assert case["issues"] == []
    assert "causal_evidence_ready_for_discovery_gate" in report["policy_hints"]
    print("PASS: Causal evidence report approves controlled claims")


def test_causal_evidence_report_rejects_uncontrolled_counterexamples():
    tmpdir = tempfile.mkdtemp()
    log_path = os.path.join(tmpdir, "unsupported.jsonl")
    _write_jsonl(log_path, _unsupported_causal_events())

    report = build_causal_evidence_report([log_path])
    case = report["cases"][0]

    assert report["readiness"] == "rejected"
    assert "missing_contrast_control" in case["issues"]
    assert "causal_memory_without_contrast" in case["issues"]
    assert "unresolved_counterexamples" in case["issues"]
    assert report["unresolved_counterexample_count"] >= 2
    assert "resolve_counterexamples_before_causal_promotion" in report["policy_hints"]
    print("PASS: Causal evidence report rejects uncontrolled counterexamples")


def test_causal_evidence_cli_writes_report():
    tmpdir = tempfile.mkdtemp()
    log_path = os.path.join(tmpdir, "controlled.jsonl")
    output_path = os.path.join(tmpdir, "causal_evidence.json")
    _write_jsonl(log_path, _controlled_causal_events())
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "singularity.main",
            "causal-evidence-report",
            "--session-log",
            log_path,
            "--output",
            output_path,
        ],
        cwd=os.getcwd(),
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    with open(output_path, "r", encoding="utf-8") as f:
        report = json.load(f)
    assert report["type"] == "causal_evidence_report"
    assert report["readiness"] == "approved"
    assert "Causal Evidence Audit" in result.stdout
    print("PASS: Causal evidence CLI writes report")


if __name__ == "__main__":
    test_causal_evidence_report_approves_controlled_claims()
    test_causal_evidence_report_rejects_uncontrolled_counterexamples()
    test_causal_evidence_cli_writes_report()
