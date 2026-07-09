"""Tests for evidence-backed project capability status."""

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, "src")

from singularity.evaluation.capability_evidence import build_capability_evidence_report


def _write_status(path: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            "| Phase | Name | Status | Progress |\n"
            "|---|---|---|---|\n"
            "| M0 | Research | Complete | 100% |\n"
            "| M1 | Bot | Complete | 100% |\n"
            "| M2 | Planner | In Progress | 60% |\n"
        )


def _write_results(path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump([
            {
                "task_id": "BM-001",
                "status": "success",
                "cycles": 5,
                "log": "logs/session-success.jsonl",
            },
            {
                "task_id": "BM-002",
                "status": "fail",
                "cycles": 20,
                "log": "logs/session-fail.jsonl",
            },
            {
                "task_id": "BM-003",
                "status": "planned",
                "task_name": "not an execution record",
            },
        ], f)


def test_capability_evidence_rejects_unsupported_completion_claims():
    tmpdir = tempfile.mkdtemp()
    status_path = os.path.join(tmpdir, "STATUS.md")
    results_path = os.path.join(tmpdir, "results.json")
    _write_status(status_path)
    _write_results(results_path)

    report = build_capability_evidence_report(
        [results_path],
        status_path=status_path,
        source_root=tmpdir,
        min_repeats=3,
        runtime_evidence={"ok": False, "checks": []},
    )
    phases = {phase["id"]: phase for phase in report["phases"]}

    assert report["readiness"] == "rejected"
    assert report["claim_readiness"] == "rejected"
    assert report["system_status"] == "incomplete"
    assert phases["M0"]["status"] == "source_incomplete"
    assert phases["M0"]["claim_assessment"] == "contradicted"
    assert phases["M1"]["status"] == "failing"
    assert phases["M1"]["claim_assessment"] == "contradicted"
    assert phases["M1"]["benchmarks"][0]["status"] == "live_observed"
    assert phases["M1"]["benchmarks"][1]["status"] == "failing"
    assert phases["M1"]["benchmarks"][2]["attempts"] == 0
    assert phases["M2"]["claim_assessment"] == "not_claimed_complete"
    assert "restore_live_minecraft_preflight_before_new_capability_claims" in report["recommendations"]
    print("PASS: Capability evidence rejects unsupported completion claims")


def test_capability_evidence_requires_distinct_repeated_runs():
    tmpdir = tempfile.mkdtemp()
    status_path = os.path.join(tmpdir, "STATUS.md")
    results_path = os.path.join(tmpdir, "results.json")
    _write_status(status_path)
    results = []
    for task_number in range(1, 6):
        for run_number in range(1, 4):
            results.append({
                "task_id": f"BM-{task_number:03d}",
                "status": "pass",
                "duration_s": 1,
                "log": f"logs/bm{task_number}-run{run_number}.jsonl",
            })
    results.append(dict(results[0]))
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump({"results": results}, f)

    report = build_capability_evidence_report(
        [results_path],
        status_path=status_path,
        source_root=tmpdir,
        min_repeats=3,
    )
    m1 = next(phase for phase in report["phases"] if phase["id"] == "M1")

    assert m1["status"] == "repeat_verified"
    assert m1["claim_assessment"] == "supported"
    assert all(task["attempts"] == 3 for task in m1["benchmarks"])
    assert report["system_complete"] is False
    print("PASS: Capability evidence requires distinct repeated runs")


def test_capability_evidence_cli_writes_report():
    tmpdir = tempfile.mkdtemp()
    status_path = os.path.join(tmpdir, "STATUS.md")
    results_path = os.path.join(tmpdir, "results.json")
    output_path = os.path.join(tmpdir, "capability.json")
    _write_status(status_path)
    _write_results(results_path)
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "singularity.main",
            "capability-evidence-report",
            "--benchmark-results",
            results_path,
            "--status-file",
            status_path,
            "--source-root",
            tmpdir,
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
    assert report["type"] == "capability_evidence_report"
    assert report["readiness"] == "rejected"
    assert "Capability Evidence Report" in result.stdout

    strict_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "singularity.main",
            "capability-evidence-report",
            "--benchmark-results",
            results_path,
            "--status-file",
            status_path,
            "--source-root",
            tmpdir,
            "--strict",
        ],
        cwd=os.getcwd(),
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert strict_result.returncode == 1
    print("PASS: Capability evidence CLI writes report")


if __name__ == "__main__":
    test_capability_evidence_rejects_unsupported_completion_claims()
    test_capability_evidence_requires_distinct_repeated_runs()
    test_capability_evidence_cli_writes_report()
