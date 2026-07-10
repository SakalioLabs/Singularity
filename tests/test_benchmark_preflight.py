"""Unit tests for benchmark preflight checks."""
import os
import sys
import json
import tempfile
from dataclasses import asdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from singularity.core.config import BotConfig, Config
from singularity.core.goal_verifier import GoalVerificationCritic
from singularity.core.memory import MemorySystem
from singularity.core.memory_policy import MemoryLifecyclePolicy
from singularity.core.skill_extractor import (
    SkillCandidate,
    SkillCandidateQueue,
    SkillExtractor,
    SkillPromotionCritic,
    build_discovery_skill_gate,
)
from singularity.core.skill_library import SkillLibrary
from singularity.evaluation import benchmark_runner as benchmark_module
from singularity.evaluation.benchmark_runner import BenchmarkResult, BenchmarkRunner, BenchmarkTask, PreflightCheck


class FakePromotionCriticLLM:
    def __init__(self, response):
        self.response = response

    def chat(self, messages, response_format=None):
        return json.dumps(self.response)


class VisualAwarePromotionCriticLLM:
    def __init__(self):
        self.prompts = []

    def chat(self, messages, response_format=None):
        prompt = messages[-1]["content"]
        self.prompts.append(prompt)
        if "session_visual.png" in prompt and "visual_evidence" in prompt:
            return json.dumps({
                "decision": "approve",
                "confidence": 0.88,
                "reason": "visual evidence confirms the environment claim",
                "evidence": ["screenshot and VLM summary show a completed shelter frame"],
                "matched_rules": ["visual_environment_evidence"],
                "postconditions": {"flags": ["shelter_frame_seen"]},
            })
        return json.dumps({
            "decision": "unknown",
            "confidence": 0.8,
            "reason": "missing visual evidence for environment-state claim",
            "missing": ["no screenshot or VLM summary"],
            "matched_rules": ["visual_environment_evidence"],
        })


class VisualAwareGoalCriticLLM:
    def __init__(self):
        self.prompts = []

    def chat(self, messages, response_format=None):
        prompt = messages[-1]["content"]
        self.prompts.append(prompt)
        if "session_goal_visual.png" in prompt:
            return json.dumps({
                "decision": "achieved",
                "confidence": 0.91,
                "reason": "screenshot confirms the base entrance is sealed",
                "evidence": ["screenshot reference and VLM summary show a sealed entrance"],
                "matched_rules": ["visual_goal_state"],
            })
        return json.dumps({
            "decision": "unknown",
            "confidence": 0.75,
            "reason": "missing screenshot evidence for the sealed entrance",
            "missing": ["no screenshot reference"],
            "matched_rules": ["visual_goal_state"],
        })


class StateGroundedTransitionEvaluatorLLM:
    def __init__(self):
        self.prompts = []
        self.response_formats = []

    def chat(self, messages, response_format=None):
        prompt = messages[-1]["content"]
        self.prompts.append(prompt)
        self.response_formats.append(response_format)
        if '"type": "dig"' in prompt and '"coal"' in prompt:
            return json.dumps({
                "label": "positive",
                "score": 0.82,
                "confidence": 0.9,
                "reason": "inventory gained coal after digging coal ore",
            })
        return json.dumps({
            "label": "no_progress",
            "score": 0.5,
            "confidence": 0.86,
            "reason": "before and after summaries are unchanged",
        })


class ReadyBridge:
    def __init__(self, config):
        self.config = config
        self.closed = False

    def connect(self):
        return True

    def health(self):
        return {
            "success": True,
            "bridge": True,
            "bot_ready": True,
            "username": self.config.username,
            "version": self.config.version,
            "mc_port": self.config.port,
        }

    def disconnect(self):
        self.closed = True


class NotReadyBridge(ReadyBridge):
    def health(self):
        return {
            "success": True,
            "bridge": True,
            "bot_ready": False,
            "mc_host": self.config.host,
            "mc_port": self.config.port,
            "last_error": "connect ECONNREFUSED",
        }


class UnrelatedTcpServiceBridge(ReadyBridge):
    def health(self):
        return {"success": False, "error": "Empty response from bot bridge for command 'health'"}


class WrongVersionBridge(ReadyBridge):
    def health(self):
        health = super().health()
        health["version"] = "1.21.1"
        return health


class ScreenshotReadyBridge(ReadyBridge):
    def capture_screenshot(self, output_path: str = "") -> dict:
        with open(output_path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
        return {
            "success": True,
            "supported": True,
            "source": "fake_renderer",
            "screenshot_path": output_path,
            "file_exists": True,
            "file_size": 24,
        }


class ContainerOnlyScreenshotBridge(ReadyBridge):
    def capture_screenshot(self, output_path: str = "") -> dict:
        return {
            "success": True,
            "supported": True,
            "source": "container_renderer",
            "screenshot_path": output_path,
            "file_exists": True,
            "file_size": 24,
        }


def test_preflight_report_without_network():
    runner = BenchmarkRunner(Config())
    report = runner.preflight(check_network=False)
    names = {check.name for check in report.checks}

    assert "python:pydantic" in names
    assert "java" in names
    assert "node" in names
    assert "npm" in names
    assert "node_dependencies" in names
    assert all(check.status in {"pass", "warn", "fail"} for check in report.checks)
    actionable = [check for check in report.checks if check.status in {"warn", "fail"}]
    assert all(check.remedy for check in actionable)
    print("PASS: Benchmark preflight report includes local readiness checks")


def test_bot_session_preflight_check():
    ready_runner = BenchmarkRunner(Config(), bridge_factory=ReadyBridge)
    ready_bridge, ready_session = ready_runner._check_bot_bridge_and_session()
    assert ready_bridge.status == "pass"
    assert ready_session.status == "pass"

    not_ready_runner = BenchmarkRunner(Config(), bridge_factory=NotReadyBridge)
    not_ready_bridge, not_ready_session = not_ready_runner._check_bot_bridge_and_session()
    assert not_ready_bridge.status == "pass"
    assert not_ready_session.status == "fail"
    assert "Minecraft server" in not_ready_session.remedy

    unrelated_runner = BenchmarkRunner(Config(), bridge_factory=UnrelatedTcpServiceBridge)
    unrelated_bridge, unrelated_session = unrelated_runner._check_bot_bridge_and_session()
    assert unrelated_bridge.status == "fail"
    assert "not a healthy Singularity bridge" in unrelated_bridge.detail
    assert unrelated_session.status == "fail"
    assert "protocol check failed" in unrelated_session.detail

    wrong_version_runner = BenchmarkRunner(Config(), bridge_factory=WrongVersionBridge)
    wrong_version_bridge, wrong_version_session = wrong_version_runner._check_bot_bridge_and_session()
    assert wrong_version_bridge.status == "pass"
    assert wrong_version_session.status == "fail"
    assert "version='1.21.1'" in wrong_version_session.detail
    print("PASS: Benchmark preflight distinguishes unrelated TCP, bridge health, and bot spawn")


def test_preflight_uses_configured_bridge_endpoint():
    class CapturingRunner(BenchmarkRunner):
        def __init__(self, config):
            super().__init__(config)
            self.tcp_checks = []
            self.bridge_checks = []

        def _check_tcp(self, name, host, port, required):
            self.tcp_checks.append((name, host, port, required))
            return PreflightCheck(name, "pass", f"{host}:{port}")

        def _check_bot_bridge_and_session(self):
            self.bridge_checks.append((self.config.bot.bridge_host, self.config.bot.bridge_port))
            return (
                PreflightCheck("bot_bridge", "pass", "fake"),
                PreflightCheck("bot_session", "pass", "fake"),
            )

    config = Config(bot=BotConfig(host="mc.local", port=25570, bridge_host="127.0.0.9", bridge_port=3012))
    runner = CapturingRunner(config)
    report = runner.preflight(check_network=True)

    assert report.ok
    assert ("127.0.0.9", 3012) in runner.bridge_checks
    assert ("minecraft_server", "mc.local", 25570, True) in runner.tcp_checks
    print("PASS: Benchmark preflight uses configured bridge endpoint")


def test_preflight_report_save_is_explicitly_non_capability_evidence():
    runner = BenchmarkRunner(Config())
    report = runner.preflight(check_network=False)
    with tempfile.TemporaryDirectory() as tmp:
        path = runner.save_preflight(report, os.path.join(tmp, "preflight.json"))
        with open(path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        try:
            runner.save_preflight(report, path)
            overwrite_blocked = False
        except FileExistsError:
            overwrite_blocked = True

    assert saved["type"] == "benchmark_preflight"
    assert saved["evidence_kind"] == "runtime_preflight"
    assert saved["counts_toward_live_observed"] is False
    assert saved["counts_toward_repeat_verified"] is False
    assert saved["ok"] == report.ok
    assert len(saved["checks"]) == len(report.checks)
    assert overwrite_blocked
    print("PASS: Saved preflight reports cannot count as Minecraft capability evidence")


def test_preflight_checks_screenshot_renderer_dependencies():
    class FakeProcess:
        def __init__(self, returncode, stdout):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    original_which = benchmark_module.shutil.which
    original_run = benchmark_module.subprocess.run
    try:
        benchmark_module.shutil.which = lambda name: "node"
        missing_payload = json.dumps({
            "ok": False,
            "install_command": "npm install prismarine-viewer three PrismarineJS/node-canvas-webgl",
            "windows_hint": "On Windows, prefer WSL or Docker for node-canvas-webgl.",
            "checks": [
                {"name": "prismarine-viewer", "status": "pass"},
                {"name": "node-canvas-webgl/lib", "status": "missing", "detail": "not installed"},
            ],
        })
        benchmark_module.subprocess.run = lambda *args, **kwargs: FakeProcess(1, missing_payload)
        runner = BenchmarkRunner(Config())
        missing = runner._check_screenshot_renderer()

        assert missing.name == "screenshot_renderer"
        assert missing.status == "fail"
        assert "node-canvas-webgl/lib" in missing.detail
        assert "npm install prismarine-viewer" in missing.remedy
        assert "WSL or Docker" in missing.remedy

        ok_payload = json.dumps({
            "ok": True,
            "checks": [
                {"name": "prismarine-viewer", "status": "pass"},
                {"name": "node-canvas-webgl/lib", "status": "pass"},
            ],
        })
        benchmark_module.subprocess.run = lambda *args, **kwargs: FakeProcess(0, ok_payload)
        ok = runner._check_screenshot_renderer()
        assert ok.status == "pass"

        report = runner.preflight(check_network=False, check_screenshot_renderer=True)
        assert any(check.name == "screenshot_renderer" for check in report.checks)
    finally:
        benchmark_module.shutil.which = original_which
        benchmark_module.subprocess.run = original_run
    print("PASS: Benchmark preflight checks screenshot renderer dependencies")


def test_screenshot_smoke_test_verifies_local_image_file():
    tmpdir = tempfile.mkdtemp()
    screenshot_path = os.path.join(tmpdir, "smoke.png")
    config = Config(
        bot=BotConfig(bridge_host="127.0.0.1", bridge_port=3033),
        screenshot_dir=tmpdir,
    )
    runner = BenchmarkRunner(config, bridge_factory=ScreenshotReadyBridge)
    report = runner.run_screenshot_smoke_test(screenshot_path)

    assert report.ok
    assert report.connected
    assert report.capture_success
    assert report.supported
    assert report.file_exists
    assert report.file_valid
    assert report.file_size >= 8
    assert report.screenshot_path == screenshot_path
    assert report.source == "fake_renderer"
    print("PASS: Screenshot smoke test verifies local image file")


def test_screenshot_smoke_test_explains_container_file_visibility():
    tmpdir = tempfile.mkdtemp()
    screenshot_path = os.path.join(tmpdir, "container_only.png")
    config = Config(
        bot=BotConfig(bridge_host="127.0.0.1", bridge_port=3034),
        screenshot_dir=tmpdir,
    )
    runner = BenchmarkRunner(config, bridge_factory=ContainerOnlyScreenshotBridge)
    report = runner.run_screenshot_smoke_test(screenshot_path)

    assert not report.ok
    assert report.connected
    assert report.capture_success
    assert report.supported
    assert not report.file_valid
    assert "Docker" in report.remedy
    assert "logs/screenshots" in report.remedy
    print("PASS: Screenshot smoke test explains container file visibility")


def test_ingest_successful_benchmark_results():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Craft torches"}},
        {"type": "observation", "data": {"inventory": {"stick": 1, "coal": 1}, "nearby_blocks": [], "nearby_entities": []}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "stick"}}, "result": {"success": True}}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "torch"}}, "result": {"success": True}}},
        {"type": "goal_end", "data": {"goal": "Craft torches", "result": {"completed": True}}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    config = Config(memory_dir=os.path.join(tmpdir, "memory"))
    runner = BenchmarkRunner(config)
    memory = MemorySystem(memory_dir=config.memory_dir)
    skills = SkillLibrary(storage_path=os.path.join(tmpdir, "skills"))
    queue = SkillCandidateQueue(os.path.join(tmpdir, "skill_candidates.jsonl"))

    report = runner.ingest_results(
        [
            BenchmarkResult("BM-T", "Craft torches", "pass", session_log_path=session_path),
            BenchmarkResult("BM-F", "Failed task", "fail", session_log_path=session_path),
        ],
        memory_system=memory,
        skill_library=skills,
        candidate_queue=queue,
    )

    assert report.processed_results == 1
    assert report.skipped_results == 1
    assert report.experience_atoms == 1
    assert report.skill_candidates == 1
    assert queue.pending()
    assert memory.retrieve_relevant_experiences("craft torches")
    print("PASS: Benchmark ingestion writes experience atoms and skill candidates")


def test_ingest_aggregates_promotion_validation_reports():
    tmpdir = tempfile.mkdtemp()
    verified_path = os.path.join(tmpdir, "session_verified.jsonl")
    failed_path = os.path.join(tmpdir, "session_failed_verification.jsonl")
    verified_events = [
        {"type": "goal_start", "data": {"goal": "Craft torches"}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "torch"}}, "result": {"success": True}}},
        {
            "type": "goal_verification",
            "data": {
                "goal": "Craft torches",
                "achieved": True,
                "status": "achieved",
                "target_inventory": {"torch": 1},
                "inventory_delta": {"torch": 4},
                "evidence": ["inventory delta gained 4 torch"],
                "context": {"accepted": True, "acceptance_reason": "deterministic_evidence_satisfied"},
            },
        },
        {"type": "goal_end", "data": {"goal": "Craft torches", "result": {"completed": True}}},
    ]
    failed_events = [
        {"type": "goal_start", "data": {"goal": "Gather 6 oak logs"}},
        {"type": "action", "data": {"action": {"type": "dig", "parameters": {"block": "oak_log"}}, "result": {"success": True}}},
        {
            "type": "goal_verification",
            "data": {
                "goal": "Gather 6 oak logs",
                "achieved": False,
                "status": "failed",
                "target_inventory": {"oak_log": 6},
                "missing": ["need 6 oak_log, have 3"],
                "context": {"accepted": False, "acceptance_reason": "deterministic_evidence_missing"},
            },
        },
        {"type": "goal_end", "data": {"goal": "Gather 6 oak logs", "result": {"completed": True}}},
    ]
    for path, events in ((verified_path, verified_events), (failed_path, failed_events)):
        with open(path, "w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

    config = Config(memory_dir=os.path.join(tmpdir, "memory"))
    runner = BenchmarkRunner(config)
    queue = SkillCandidateQueue(os.path.join(tmpdir, "skill_candidates.jsonl"))
    report = runner.ingest_results(
        [
            BenchmarkResult("BM-V", "Verified torch crafting", "pass", session_log_path=verified_path),
            BenchmarkResult("BM-X", "False complete wood gathering", "pass", session_log_path=failed_path),
        ],
        candidate_queue=queue,
    )

    assert report.processed_results == 2
    assert report.skill_candidates == 2
    assert len(report.promotion_reports) == 2
    assert report.promotion_readiness["approved"] == 0
    assert report.promotion_readiness["retained"] == 1
    assert report.promotion_readiness["rejected"] == 1
    assert report.promotion_readiness["unknown"] == 0
    assert report.promotion_decisions["retain_candidate"] == 1
    assert report.promotion_decisions["reject"] == 1
    assert report.promotion_statuses["candidate"] == 1
    assert report.promotion_statuses["failed"] == 1

    pending = queue.pending()
    verified_candidate = next(candidate for candidate in pending if candidate.goal == "Craft torches")
    rejected_candidate = next(candidate for candidate in pending if candidate.goal == "Gather 6 oak logs")
    verified_report = verified_candidate.signals["promotion_report"]
    rejected_report = rejected_candidate.signals["promotion_report"]

    assert verified_report["benchmark_task_id"] == "BM-V"
    assert verified_report["reason"] == "candidate_needs_more_independent_live_evidence"
    assert "three_distinct_live_source_sessions_required" in verified_report["missing"]
    assert verified_report["postconditions"]["inventory"]["torch"] == 4
    assert rejected_report["benchmark_task_id"] == "BM-X"
    assert rejected_report["decision"] == "reject"
    assert "need 6 oak_log, have 3" in rejected_report["missing"]
    print("PASS: Benchmark ingestion aggregates promotion validation reports")


def test_ingest_uses_promotion_critic_for_unknown_reports():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_unknown_critic.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Organize mining inventory"}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "stick"}}, "result": {"success": True}}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "torch"}}, "result": {"success": True}}},
        {"type": "goal_end", "data": {"goal": "Organize mining inventory", "result": {"completed": True}}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    config = Config(memory_dir=os.path.join(tmpdir, "memory"))
    runner = BenchmarkRunner(config)
    queue = SkillCandidateQueue(os.path.join(tmpdir, "skill_candidates.jsonl"))
    critic = SkillPromotionCritic(FakePromotionCriticLLM({
        "decision": "approve",
        "confidence": 0.9,
        "reason": "successful sequence is reusable",
        "evidence": ["all actions succeeded"],
        "matched_rules": ["trace_success_sequence"],
        "postconditions": {"inventory": {"torch": 4}},
    }))
    report = runner.ingest_results(
        [BenchmarkResult("BM-U", "Unknown verifier critic", "pass", session_log_path=session_path)],
        candidate_queue=queue,
        promotion_critic=critic,
    )

    assert report.processed_results == 1
    assert report.promotion_readiness["approved"] == 0
    assert report.promotion_readiness["retained"] == 1
    assert report.promotion_readiness["unknown"] == 0
    assert report.promotion_statuses["candidate"] == 1
    candidate = queue.pending()[0]
    promotion_report = candidate.signals["promotion_report"]
    assert promotion_report["status"] == "candidate"
    assert promotion_report["decision"] == "retain_candidate"
    assert promotion_report["postconditions"]["inventory"]["torch"] == 4
    print("PASS: Promotion critic cannot bypass distinct live-source requirements")


def test_promotion_review_ablation_compares_visual_evidence():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_visual_review.jsonl")
    label_path = os.path.join(tmpdir, "promotion_labels.jsonl")
    screenshot_path = os.path.join(tmpdir, "session_visual.png")
    with open(screenshot_path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    events = [
        {"type": "goal_start", "data": {"goal": "Inspect completed shelter frame"}},
        {
            "type": "observation",
            "data": {
                "inventory": {"oak_planks": 6},
                "screenshot_path": screenshot_path,
                "visual_analysis": "Screenshot shows a completed shelter frame with placed planks.",
                "structures": {"shelter": {"frame_complete": True}},
                "flags": ["shelter_frame_complete"],
                "nearby_blocks": [{"name": "oak_planks", "distance": 2}],
            },
        },
        {"type": "action", "data": {"action": {"type": "look_at", "parameters": {"x": 1, "y": 65, "z": 1}}, "result": {"success": True}}},
        {"type": "action", "data": {"action": {"type": "place", "parameters": {"item": "oak_planks"}}, "result": {"success": True}}},
        {"type": "goal_end", "data": {"goal": "Inspect completed shelter frame", "result": {"completed": True}}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")
    with open(label_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "source_log": session_path,
            "goal": "Inspect completed shelter frame",
            "readiness": "approved",
            "reviewer": "manual_fixture",
            "notes": "visual review confirms a reusable completed shelter-frame skill",
        }) + "\n")

    critic_llm = VisualAwarePromotionCriticLLM()
    critic = SkillPromotionCritic(critic_llm)
    runner = BenchmarkRunner(Config(memory_dir=os.path.join(tmpdir, "memory")))
    manual_labels = runner.load_promotion_review_labels(label_path)
    report = runner.run_promotion_review_ablation_from_logs(
        [session_path],
        promotion_critic=critic,
        manual_labels=manual_labels,
    )

    assert report.candidate_count == 1
    assert report.changed_count == 1
    assert report.visual_helped_count == 0
    assert report.api_visual_helped_count == 0
    assert report.screenshot_vlm_helped_count == 0
    assert report.screenshot_vlm_added_value_count == 0
    assert report.manual_labeled_count == 1
    assert report.deterministic_manual_match_count == 0
    assert report.api_visual_manual_match_count == 0
    assert report.screenshot_vlm_manual_match_count == 0
    assert report.screenshot_vlm_manual_improvement_count == 0
    case = report.cases[0]
    assert case.has_visual_evidence
    assert "screenshots" in case.visual_evidence_keys
    assert case.raw_screenshot_count == 1
    assert case.screenshot_count == 1
    assert case.missing_screenshot_count == 0
    assert case.invalid_screenshot_count == 0
    assert case.manual_readiness == "approved"
    assert case.manual_label_source == "manual_fixture"
    assert case.deterministic_readiness == "rejected"
    assert case.api_visual_readiness == "rejected"
    assert case.screenshot_vlm_readiness == "rejected"
    assert case.without_visual_readiness == "rejected"
    assert case.with_visual_readiness == "rejected"
    assert case.with_visual_status == "critic_approved"
    assert not case.visual_helped
    assert not case.api_visual_helped
    assert not case.screenshot_vlm_helped
    assert not case.screenshot_vlm_added_value
    assert case.deterministic_matches_manual is False
    assert case.api_visual_matches_manual is False
    assert case.screenshot_vlm_matches_manual is False
    assert len(critic_llm.prompts) == 2
    assert "session_visual.png" not in critic_llm.prompts[0]
    assert "session_visual.png" in critic_llm.prompts[1]
    print("PASS: Visual review cannot bypass typed skill-contract requirements")


def test_goal_verification_ablation_compares_visual_evidence():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_goal_visual_review.jsonl")
    label_path = os.path.join(tmpdir, "goal_labels.jsonl")
    screenshot_path = os.path.join(tmpdir, "session_goal_visual.png")
    with open(screenshot_path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    events = [
        {"type": "goal_start", "data": {"goal": "Confirm base entrance is sealed"}},
        {
            "type": "observation",
            "data": {
                "inventory": {"oak_planks": 2},
                "screenshot_path": screenshot_path,
                "visual_analysis": "Screenshot shows the base entrance sealed with oak planks and no visible gap.",
                "structures": {"base_entrance": {"sealed": True}},
                "flags": ["base_entrance_sealed"],
                "nearby_blocks": [{"name": "oak_planks", "distance": 1}],
            },
        },
        {"type": "action", "data": {"action": {"type": "look_at", "parameters": {"x": 2, "y": 65, "z": 2}}, "result": {"success": True}}},
        {"type": "goal_end", "data": {"goal": "Confirm base entrance is sealed", "result": {"completed": True}}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")
    with open(label_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "source_log": session_path,
            "goal": "Confirm base entrance is sealed",
            "readiness": "approved",
            "reviewer": "manual_fixture",
            "notes": "visual inspection confirms the entrance is sealed",
        }) + "\n")

    critic_llm = VisualAwareGoalCriticLLM()
    critic = GoalVerificationCritic(critic_llm)
    runner = BenchmarkRunner(Config(memory_dir=os.path.join(tmpdir, "memory")))
    manual_labels = runner.load_goal_verification_labels(label_path)
    report = runner.run_goal_verification_ablation_from_logs(
        [session_path],
        goal_critic=critic,
        manual_labels=manual_labels,
    )

    assert report.goal_count == 1
    assert report.changed_count == 1
    assert report.visual_helped_count == 1
    assert report.api_visual_helped_count == 0
    assert report.screenshot_vlm_helped_count == 1
    assert report.screenshot_vlm_added_value_count == 1
    assert report.manual_labeled_count == 1
    assert report.deterministic_manual_match_count == 0
    assert report.api_visual_manual_match_count == 0
    assert report.screenshot_vlm_manual_match_count == 1
    assert report.screenshot_vlm_manual_improvement_count == 1
    case = report.cases[0]
    assert case.has_visual_evidence
    assert "screenshot_path" in case.visual_evidence_keys
    assert case.raw_screenshot_count == 1
    assert case.screenshot_count == 1
    assert case.missing_screenshot_count == 0
    assert case.invalid_screenshot_count == 0
    assert case.manual_readiness == "approved"
    assert case.manual_label_source == "manual_fixture"
    assert case.deterministic_readiness == "unknown"
    assert case.api_visual_readiness == "unknown"
    assert case.screenshot_vlm_readiness == "approved"
    assert case.screenshot_vlm_status == "achieved"
    assert case.screenshot_vlm_reason == "screenshot confirms the base entrance is sealed"
    assert case.deterministic_matches_manual is False
    assert case.api_visual_matches_manual is False
    assert case.screenshot_vlm_matches_manual is True
    assert case.visual_helped
    assert not case.api_visual_helped
    assert case.screenshot_vlm_helped
    assert case.screenshot_vlm_added_value
    assert len(critic_llm.prompts) == 2
    assert "session_goal_visual.png" not in critic_llm.prompts[0]
    assert "session_goal_visual.png" in critic_llm.prompts[1]
    print("PASS: Goal verification ablation compares visual evidence")


def test_goal_verification_critic_gate_controls_runtime_use():
    runner = BenchmarkRunner(Config())
    ablation_report = {
        "goal_count": 1,
        "manual_labeled_count": 1,
        "screenshot_vlm_added_value_count": 1,
        "errors": [],
        "cases": [{
            "source_log": "logs/session_goal_visual_review.jsonl",
            "goal": "Confirm base entrance is sealed",
            "goal_index": 1,
            "screenshot_count": 1,
            "manual_readiness": "approved",
            "deterministic_readiness": "unknown",
            "api_visual_readiness": "unknown",
            "screenshot_vlm_readiness": "approved",
            "screenshot_vlm_added_value": True,
        }],
    }
    label_validation = {
        "ok": True,
        "label_count": 1,
        "ok_count": 1,
        "error_count": 0,
        "errors": [],
        "cases": [{
            "label_type": "goal_verification",
            "readiness": "approved",
            "ok": True,
        }],
    }

    report = runner.build_goal_verification_critic_gate(
        goal_ablation_reports=[ablation_report],
        label_validation_reports=[label_validation],
    )

    assert report["readiness"] == "approved"
    assert report["decision"] == "allow_goal_critic_runtime_use"
    assert report["approved_count"] == 1
    assert report["screenshot_vlm_manual_match_count"] == 1
    assert report["screenshot_vlm_manual_mismatch_count"] == 0
    assert "enable_goal_verification_critic" in report["policy_hints"]

    false_approve = dict(ablation_report)
    false_approve["cases"] = [dict(ablation_report["cases"][0], manual_readiness="rejected")]
    rejected = runner.build_goal_verification_critic_gate(
        goal_ablation_reports=[false_approve],
        label_validation_reports=[dict(label_validation, cases=[dict(label_validation["cases"][0], readiness="rejected")])],
    )

    assert rejected["readiness"] == "rejected"
    assert rejected["decision"] == "reject_goal_critic_runtime_use"
    assert rejected["dangerous_false_approve_count"] == 1
    assert rejected["dangerous_cases"][0]["goal"] == "Confirm base entrance is sealed"
    print("PASS: Goal verification critic gate controls runtime use")


def test_promotion_review_ablation_ignores_unverified_screenshot_paths():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_visual_review_missing.jsonl")
    missing_screenshot = os.path.join(tmpdir, "session_visual.png")
    events = [
        {"type": "goal_start", "data": {"goal": "Inspect completed shelter frame"}},
        {
            "type": "observation",
            "data": {
                "inventory": {"oak_planks": 6},
                "screenshot_path": missing_screenshot,
                "visual_analysis": "Screenshot supposedly shows a completed shelter frame.",
                "structures": {"shelter": {"frame_complete": True}},
                "flags": ["shelter_frame_complete"],
            },
        },
        {"type": "action", "data": {"action": {"type": "place", "parameters": {"item": "oak_planks"}}, "result": {"success": True}}},
        {"type": "goal_end", "data": {"goal": "Inspect completed shelter frame", "result": {"completed": True}}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    critic_llm = VisualAwarePromotionCriticLLM()
    runner = BenchmarkRunner(Config(memory_dir=os.path.join(tmpdir, "memory")))
    report = runner.run_promotion_review_ablation_from_logs(
        [session_path],
        promotion_critic=SkillPromotionCritic(critic_llm),
    )
    case = report.cases[0]

    assert case.raw_screenshot_count == 1
    assert case.screenshot_count == 0
    assert case.missing_screenshot_count == 1
    assert case.screenshot_vlm_readiness == "rejected"
    assert not case.screenshot_vlm_helped
    assert "session_visual.png" not in critic_llm.prompts[1]
    print("PASS: Promotion review ablation ignores unverified screenshot paths")


def test_goal_verification_ablation_ignores_unverified_screenshot_paths():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_goal_visual_review_missing.jsonl")
    missing_screenshot = os.path.join(tmpdir, "session_goal_visual.png")
    events = [
        {"type": "goal_start", "data": {"goal": "Confirm base entrance is sealed"}},
        {
            "type": "observation",
            "data": {
                "inventory": {"oak_planks": 2},
                "screenshot_path": missing_screenshot,
                "visual_analysis": "Screenshot supposedly shows the base entrance sealed.",
                "structures": {"base_entrance": {"sealed": True}},
                "flags": ["base_entrance_sealed"],
            },
        },
        {"type": "action", "data": {"action": {"type": "look_at", "parameters": {"x": 2, "y": 65, "z": 2}}, "result": {"success": True}}},
        {"type": "goal_end", "data": {"goal": "Confirm base entrance is sealed", "result": {"completed": True}}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    critic_llm = VisualAwareGoalCriticLLM()
    runner = BenchmarkRunner(Config(memory_dir=os.path.join(tmpdir, "memory")))
    report = runner.run_goal_verification_ablation_from_logs(
        [session_path],
        goal_critic=GoalVerificationCritic(critic_llm),
    )
    case = report.cases[0]

    assert case.raw_screenshot_count == 1
    assert case.screenshot_count == 0
    assert case.missing_screenshot_count == 1
    assert case.screenshot_vlm_readiness == "unknown"
    assert not case.screenshot_vlm_helped
    assert "session_goal_visual.png" not in critic_llm.prompts[1]
    print("PASS: Goal verification ablation ignores unverified screenshot paths")


def test_review_label_template_generates_promotion_and_goal_records():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_review_template.jsonl")
    screenshot_path = os.path.join(tmpdir, "review_template.png")
    with open(screenshot_path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    events = [
        {"type": "goal_start", "data": {"goal": "Inspect completed shelter frame"}},
        {
            "type": "observation",
            "data": {
                "inventory": {"oak_planks": 6},
                "screenshot_path": screenshot_path,
                "visual_analysis": "Screenshot shows a completed shelter frame with placed planks.",
                "structures": {"shelter": {"frame_complete": True}},
                "flags": ["shelter_frame_complete"],
                "nearby_blocks": [{"name": "oak_planks", "distance": 2}],
            },
        },
        {"type": "action", "data": {"action": {"type": "look_at", "parameters": {"x": 1, "y": 65, "z": 1}}, "result": {"success": True}}},
        {"type": "goal_end", "data": {"goal": "Inspect completed shelter frame", "result": {"completed": True}}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config(memory_dir=os.path.join(tmpdir, "memory")))
    templates = runner.build_review_label_templates_from_logs([session_path], mode="both")
    promotion_records = [record for record in templates if record.get("type") == "promotion_review"]
    goal_records = [record for record in templates if record.get("type") == "goal_verification"]

    assert len(promotion_records) == 1
    assert len(goal_records) == 1
    promotion = promotion_records[0]
    goal = goal_records[0]
    assert promotion["source_log"] == session_path
    assert promotion["goal"] == "Inspect completed shelter frame"
    assert promotion["readiness"] == "unknown"
    assert promotion["candidate_id"]
    assert promotion["candidate_name"]
    assert promotion["has_visual_evidence"]
    assert promotion["has_screenshot_evidence"]
    assert promotion["raw_screenshot_count"] == 1
    assert promotion["screenshot_count"] == 1
    assert promotion["missing_screenshot_count"] == 0
    assert promotion["invalid_screenshot_count"] == 0
    assert "screenshots" in promotion["visual_evidence_keys"]
    assert promotion["screenshots"] == [screenshot_path]
    assert "::" in promotion["key"]
    assert goal["source_log"] == session_path
    assert goal["goal_index"] == 1
    assert goal["goal"] == "Inspect completed shelter frame"
    assert goal["readiness"] == "unknown"
    assert goal["has_visual_evidence"]
    assert goal["has_screenshot_evidence"]
    assert goal["raw_screenshot_count"] == 1
    assert goal["screenshot_count"] == 1
    assert goal["missing_screenshot_count"] == 0
    assert goal["invalid_screenshot_count"] == 0
    assert "screenshot_path" in goal["visual_evidence_keys"]
    assert goal["screenshots"] == [screenshot_path]
    assert "::1::" in goal["key"]
    print("PASS: Review label template generates promotion and goal records")


def test_review_label_validate_checks_readiness_and_screenshots():
    tmpdir = tempfile.mkdtemp()
    label_path = os.path.join(tmpdir, "labels.jsonl")
    screenshot_path = os.path.join(tmpdir, "valid_label.png")
    missing_path = os.path.join(tmpdir, "missing_label.png")
    with open(screenshot_path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    records = [
        {
            "type": "promotion_review",
            "key": "session.jsonl::candidate_a",
            "source_log": os.path.join(tmpdir, "session.jsonl"),
            "candidate_id": "candidate_a",
            "readiness": "approved",
            "has_screenshot_evidence": True,
            "screenshots": [screenshot_path],
        },
        {
            "type": "goal_verification",
            "source_log": os.path.join(tmpdir, "session.jsonl"),
            "goal": "Confirm base entrance is sealed",
            "readiness": "approved",
            "has_screenshot_evidence": True,
            "screenshots": [missing_path],
        },
        {
            "type": "goal_verification",
            "source_log": os.path.join(tmpdir, "session.jsonl"),
            "goal": "Inspect unknown state",
            "readiness": "maybe",
        },
    ]
    with open(label_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")

    runner = BenchmarkRunner(Config(memory_dir=os.path.join(tmpdir, "memory")))
    report = runner.validate_review_labels(label_path)

    assert not report.ok
    assert report.label_count == 3
    assert report.ok_count == 1
    assert report.invalid_readiness_count == 1
    assert report.screenshot_unverified_count == 1
    assert report.error_count == 2
    good, missing, invalid = report.cases
    assert good.ok
    assert good.screenshot_count == 1
    assert not missing.ok
    assert "screenshot_evidence_not_verified" in missing.errors
    assert missing.missing_screenshots == [missing_path]
    assert not invalid.ok
    assert "invalid_readiness" in invalid.errors
    print("PASS: Review label validation checks readiness and screenshots")


def test_visual_review_pipeline_runs_trace_validation_and_ablations():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_visual_pipeline.jsonl")
    label_path = os.path.join(tmpdir, "pipeline_labels.jsonl")
    promotion_screenshot = os.path.join(tmpdir, "session_visual.png")
    goal_screenshot = os.path.join(tmpdir, "session_goal_visual.png")
    for screenshot_path in (promotion_screenshot, goal_screenshot):
        with open(screenshot_path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    visual_move = {"type": "move_to", "parameters": {"x": 8.0, "z": 0.0, "y": 64}}
    visual_dig = {"type": "dig", "parameters": {"x": 10, "y": 64, "z": 0}}
    events = [
        {"type": "goal_start", "data": {"goal": "Confirm base entrance is sealed"}},
        {
            "type": "observation",
            "data": {
                "inventory": {"oak_planks": 6},
                "position": {"x": 0, "y": 64, "z": 0},
                "screenshot_path": promotion_screenshot,
                "frame_path": goal_screenshot,
                "visual_analysis": "Screenshots show a completed shelter frame and a sealed base entrance.",
                "structures": {
                    "shelter": {"frame_complete": True},
                    "base_entrance": {"sealed": True},
                },
                "flags": ["shelter_frame_complete", "base_entrance_sealed"],
                "nearby_blocks": [{"name": "oak_planks", "distance": 2}],
                "grounded_resources": [{
                    "name": "iron_ore",
                    "can_harvest": True,
                    "best_available_tool": "stone_pickaxe",
                    "required_tool_tier": 2,
                    "position": {"x": 10, "y": 64, "z": 0},
                }],
            },
        },
        {"type": "visual_action_intervention", "data": {
            "goal": "mine iron ore",
            "phase": "prepend_approach",
            "suggestion": {
                "kind": "resource_approach",
                "action": visual_move,
                "reason": "move within reach of visible iron_ore",
            },
        }},
        {"type": "plan", "data": {
            "status": "in_progress",
            "actions": [visual_move, visual_dig],
        }},
        {"type": "action", "data": {"action": {"type": "look_at", "parameters": {"x": 1, "y": 65, "z": 1}}, "result": {"success": True}}},
        {"type": "action", "data": {"action": {"type": "place", "parameters": {"item": "oak_planks"}}, "result": {"success": True}}},
        {"type": "goal_end", "data": {"goal": "Confirm base entrance is sealed", "result": {"completed": True}}},
    ]
    with open(session_path, "w", encoding="utf-8-sig") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")
    label_records = [
        {
            "type": "promotion_review",
            "source_log": session_path,
            "goal": "Confirm base entrance is sealed",
            "readiness": "approved",
            "reviewer": "manual_fixture",
            "notes": "visual review confirms a reusable shelter inspection skill",
            "has_screenshot_evidence": True,
            "screenshots": [promotion_screenshot],
        },
        {
            "type": "goal_verification",
            "source_log": session_path,
            "goal": "Confirm base entrance is sealed",
            "readiness": "approved",
            "reviewer": "manual_fixture",
            "notes": "visual inspection confirms the entrance is sealed",
            "has_screenshot_evidence": True,
            "screenshots": [goal_screenshot],
        },
    ]
    with open(label_path, "w", encoding="utf-8") as f:
        for record in label_records:
            f.write(json.dumps(record) + "\n")

    runner = BenchmarkRunner(Config(memory_dir=os.path.join(tmpdir, "memory")))
    report = runner.run_visual_review_pipeline(
        [session_path],
        mode="both",
        label_file=label_path,
        promotion_critic=SkillPromotionCritic(VisualAwarePromotionCriticLLM()),
        goal_critic=GoalVerificationCritic(VisualAwareGoalCriticLLM()),
        run_ablations=True,
    )

    assert report.ready
    assert report.ready_for_manual_review
    assert report.ready_for_agreement_ablation
    assert report.visual_trace.log_count == 1
    assert report.visual_trace.ready_log_count == 1
    assert report.visual_trace.screenshot_log_count == 1
    assert report.template_count == 2
    assert report.promotion_template_count == 1
    assert report.goal_template_count == 1
    assert report.error_template_count == 0
    assert report.label_validation is not None
    assert report.label_validation.ok
    assert report.label_validation.label_count == 2
    assert report.promotion_ablation is not None
    assert report.promotion_ablation.candidate_count == 1
    assert report.promotion_ablation.manual_labeled_count == 1
    assert report.promotion_ablation.screenshot_vlm_added_value_count == 0
    assert report.goal_ablation is not None
    assert report.goal_ablation.goal_count == 1
    assert report.goal_ablation.manual_labeled_count == 1
    assert report.goal_ablation.screenshot_vlm_added_value_count == 1
    assert report.visual_action_ablation is not None
    assert len(report.visual_action_ablation.cases) == 1
    assert report.visual_action_ablation.helped_count == 1
    payload = runner.visual_review_pipeline_report_to_dict(report)
    assert payload["summary"]["ready"]
    assert payload["summary"]["template_count"] == 2
    assert payload["summary"]["promotion_screenshot_vlm_added_value_count"] == 0
    assert payload["summary"]["goal_screenshot_vlm_added_value_count"] == 1
    assert payload["summary"]["visual_action_case_count"] == 1
    assert payload["summary"]["visual_action_helped_count"] == 1
    print("PASS: Visual review pipeline runs trace validation and ablations")


def test_visual_trace_report_counts_visual_coverage():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_visual_trace.jsonl")
    screenshot_path = os.path.join(tmpdir, "visual_trace.png")
    with open(screenshot_path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    events = [
        {"type": "goal_start", "data": {"goal": "Inspect completed shelter frame"}},
        {
            "type": "observation",
            "data": {
                "inventory": {"oak_planks": 6},
                "screenshot_path": screenshot_path,
                "visual_analysis": "Screenshot shows a completed shelter frame with placed planks.",
                "structures": {"shelter": {"frame_complete": True}},
                "flags": ["shelter_frame_complete"],
                "nearby_blocks": [{"name": "oak_planks", "distance": 2}],
            },
        },
        {"type": "action", "data": {"action": {"type": "look_at", "parameters": {"x": 1, "y": 65, "z": 1}}, "result": {"success": True}}},
        {"type": "goal_end", "data": {"goal": "Inspect completed shelter frame", "result": {"completed": True}}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config(memory_dir=os.path.join(tmpdir, "memory")))
    report = runner.run_visual_trace_report_from_logs([session_path])

    assert report.log_count == 1
    assert report.ready_log_count == 1
    assert report.screenshot_log_count == 1
    assert report.goal_count == 1
    assert report.goals_with_visual_evidence_count == 1
    assert report.promotion_candidate_count == 1
    assert report.promotion_candidates_with_visual_evidence_count == 1
    case = report.cases[0]
    assert case.ready_for_visual_ablation
    assert case.observation_count == 1
    assert case.visual_observation_count == 1
    assert case.raw_screenshot_count == 1
    assert case.screenshot_count == 1
    assert case.missing_screenshot_count == 0
    assert case.invalid_screenshot_count == 0
    assert case.visual_analysis_count == 1
    assert case.goals_with_visual_evidence == 1
    assert case.promotion_candidates_with_visual_evidence == 1
    assert "screenshot_path" in case.visual_evidence_keys
    assert "screenshots" in case.visual_evidence_keys
    assert case.raw_screenshot_paths == [screenshot_path]
    assert case.screenshot_paths == [screenshot_path]
    assert not case.missing_visual_goals
    print("PASS: Visual trace report counts visual coverage")


def test_visual_trace_report_validates_screenshot_files():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_visual_trace_invalid.jsonl")
    invalid_path = os.path.join(tmpdir, "not_image.png")
    missing_path = os.path.join(tmpdir, "missing.png")
    with open(invalid_path, "w", encoding="utf-8") as f:
        f.write("not actually an image")
    events = [
        {"type": "goal_start", "data": {"goal": "Inspect screenshot evidence"}},
        {
            "type": "observation",
            "data": {
                "screenshot_path": missing_path,
                "screenshots": [invalid_path],
                "nearby_blocks": [{"name": "oak_planks", "distance": 2}],
            },
        },
        {"type": "goal_end", "data": {"goal": "Inspect screenshot evidence", "result": {"completed": False}}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config(memory_dir=os.path.join(tmpdir, "memory")))
    report = runner.run_visual_trace_report_from_logs([session_path])
    case = report.cases[0]

    assert report.raw_screenshot_log_count == 1
    assert report.screenshot_log_count == 0
    assert report.missing_screenshot_count == 1
    assert report.invalid_screenshot_count == 1
    assert case.raw_screenshot_count == 2
    assert case.screenshot_count == 0
    assert case.missing_screenshot_paths == [missing_path]
    assert case.invalid_screenshot_paths == [invalid_path]
    print("PASS: Visual trace report validates screenshot files")


def test_exploration_trace_report_counts_open_world_coverage():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_exploration_trace.jsonl")
    screenshot_path = os.path.join(tmpdir, "explore.png")
    with open(screenshot_path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    events = [
        {"type": "goal_start", "data": {"goal": "Explore cave and craft torches before night"}},
        {"type": "auto_goal", "data": {"goal": "Explore nearby cave"}},
        {"type": "curriculum_goal", "data": {"selected": "Explore nearby cave"}},
        {
            "type": "observation",
            "data": {
                "position": {"x": 0, "y": 64, "z": 0},
                "nearby_blocks": [{"name": "oak_log"}, {"name": "stone"}],
                "nearby_entities": [{"type": "sheep", "hostile": False}],
                "screenshot_path": screenshot_path,
                "visual_analysis": "Open field with trees and a cave mouth.",
            },
        },
        {
            "type": "plan",
            "data": {
                "actions": [
                    {"type": "move_to", "parameters": {"x": 3, "y": 64, "z": 4}},
                    {"type": "dig", "parameters": {"block": "coal_ore"}},
                ],
            },
        },
        {"type": "action", "data": {"action": {"type": "move_to"}, "result": {"success": True}}},
        {
            "type": "observation",
            "data": {
                "position": {"x": 3, "y": 64, "z": 4},
                "nearby_blocks": [{"name": "coal_ore"}, {"name": "stone"}],
                "grounded_resources": [{"name": "coal_ore", "drop": "coal", "can_harvest": True}],
                "nearby_entities": [{"type": "zombie", "hostile": True, "distance": 5}],
            },
        },
        {
            "type": "action",
            "data": {
                "action": {"type": "dig", "parameters": {"block": "coal_ore"}},
                "result": {"success": False, "error": "no target visible"},
            },
        },
        {
            "type": "observation",
            "data": {
                "position": {"x": 8, "y": 64, "z": 5},
                "nearby_blocks": [{"name": "torch"}],
                "dangers": [{"type": "creeper", "distance": 6}],
                "visual_resources": [{"name": "cave_entrance"}],
            },
        },
        {"type": "goal_end", "data": {"goal": "Explore cave and craft torches before night", "result": {"completed": False}}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config(memory_dir=os.path.join(tmpdir, "memory")))
    report = runner.run_exploration_trace_report_from_logs([session_path])
    case = report.cases[0]

    assert report.log_count == 1
    assert report.ready_log_count == 1
    assert report.logs_with_movement_count == 1
    assert report.failed_action_count == 1
    assert report.hostile_encounter_count == 2
    assert report.unique_block_type_count == 4
    assert report.unique_resource_type_count == 2
    assert case.ready_for_exploration_review
    assert case.observation_count == 3
    assert case.unique_position_count == 3
    assert case.x_span == 8
    assert case.z_span == 5
    assert case.path_distance > 10
    assert case.visual_observation_count == 3
    assert case.screenshot_count == 1
    assert case.danger_event_count == 2
    assert case.multi_hop_goal_count == 1
    assert case.multi_step_plan_count == 1
    assert case.auto_goal_count == 1
    assert case.curriculum_goal_count == 1
    assert case.failed_goal_count == 1
    assert case.action_failure_categories["perception"] == 1
    assert "coal_ore" in case.unique_block_types
    assert "zombie" in case.unique_entity_types
    assert "cave_entrance" in case.unique_resource_types
    feedback = runner.exploration_curriculum_feedback(report)
    assert feedback["discovered_blocks"] == ["coal_ore", "oak_log", "stone", "torch"]
    assert feedback["discovered_resources"] == ["cave_entrance", "coal_ore"]
    assert feedback["discovered_entities"] == ["creeper", "sheep", "zombie"]
    assert feedback["action_failure_categories"]["perception"] == 1
    assert feedback["low_movement_log_count"] == 0
    assert feedback["hostile_encounter_count"] == 2
    from singularity.core.curriculum import CurriculumManager
    curriculum = CurriculumManager()
    applied = runner.apply_exploration_feedback_to_curriculum(report, curriculum)
    assert applied == feedback
    assert curriculum.summary()["exploration_feedback"]["action_failure_categories"]["perception"] == 1
    print("PASS: Exploration trace report counts open-world coverage")


def test_world_model_report_builds_cells_frontiers_and_hotspots():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_world_model.jsonl")
    events = [
        {
            "type": "observation",
            "data": {
                "position": {"x": 0, "y": 64, "z": 0},
                "nearby_blocks": [{"name": "oak_log"}, {"name": "stone"}],
                "grounded_resources": [{"name": "oak_log", "position": {"x": 1, "y": 64, "z": 0}}],
                "nearby_entities": [{"type": "sheep", "hostile": False}],
            },
        },
        {
            "type": "observation",
            "data": {
                "position": {"x": 9, "y": 64, "z": 0},
                "nearby_blocks": [{"name": "coal_ore", "position": {"x": 9, "y": 63, "z": 1}}],
                "grounded_resources": [{"name": "coal_ore", "position": {"x": 9, "y": 63, "z": 1}}],
                "nearby_entities": [{"type": "zombie", "hostile": True, "position": {"x": 10, "y": 64, "z": 1}}],
            },
        },
        {
            "type": "observation",
            "data": {
                "position": {"x": 9, "y": 64, "z": 8},
                "visual_resources": [{"name": "cave_entrance"}],
                "dangers": [{"type": "creeper", "position": {"x": 9, "y": 64, "z": 8}}],
            },
        },
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config(memory_dir=os.path.join(tmpdir, "memory")))
    report = runner.run_world_model_report_from_logs([session_path], cell_size=8, limit=10)
    case = report.cases[0]

    assert report.log_count == 1
    assert report.ready_log_count == 1
    assert report.unique_cell_count == 3
    assert report.frontier_count >= 6
    assert report.resource_hotspot_count == 3
    assert report.danger_cell_count == 2
    assert case.ready_for_world_model_review
    assert case.position_count == 3
    assert case.transition_count == 2
    assert any(item["resource"] == "coal_ore" for item in case.resource_hotspots)
    assert any(item["resource"] == "cave_entrance" for item in case.resource_hotspots)
    assert any(frontier["direction"] in {"east", "west", "north", "south"} for frontier in case.frontiers)
    assert any(goal.startswith("Explore ") for goal in case.suggested_exploration_goals)
    coal_cell = next(cell for cell in case.cells if "coal_ore" in cell["resources"])
    assert coal_cell["cell"] == {"x": 1, "z": 0}
    assert coal_cell["danger_count"] == 1

    feedback = runner.world_model_curriculum_feedback(report)
    assert feedback["frontier_count"] == report.frontier_count
    assert feedback["resource_hotspot_count"] == 3
    assert feedback["danger_cell_count"] == 2
    assert feedback["suggested_goals"]
    assert feedback["frontiers"][0]["cell"]
    assert any(item["resource"] == "coal_ore" for item in feedback["resource_hotspots"])

    from singularity.core.curriculum import CurriculumManager
    curriculum = CurriculumManager()
    applied = runner.apply_world_model_feedback_to_curriculum(report, curriculum)
    assert applied == feedback
    summary = curriculum.summary()
    assert summary["world_model_feedback"]["frontier_count"] >= report.frontier_count

    candidates = curriculum.propose_goals(
        {
            "health": 20,
            "time_of_day": 6000,
            "inventory": {"crafting_table": 1, "stone_pickaxe": 1, "oak_log": 6, "cobblestone": 12, "torch": 8},
            "nearby_entities": [],
            "nearby_blocks": [],
        },
        "Explore surroundings",
    )
    categories = {candidate.category for candidate in candidates}
    assert "world_model_frontier" in categories
    assert "world_model_resource" in categories
    assert "world_model_safety" in categories
    assert any("world_model_frontier_feedback" in candidate.reasons for candidate in candidates)
    print("PASS: World model report builds cells, frontiers, and hotspots")


def test_world_model_feedback_gate_requires_structured_map_evidence():
    runner = BenchmarkRunner(Config())
    approved_report = {
        "log_count": 1,
        "ready_log_count": 1,
        "observation_count": 3,
        "unique_cell_count": 3,
        "frontier_count": 2,
        "resource_hotspot_count": 1,
        "danger_cell_count": 1,
        "world_model_feedback": {
            "frontier_count": 2,
            "resource_hotspot_count": 1,
            "danger_cell_count": 1,
            "suggested_goals": ["Explore east frontier cell (1,0) near x=12, z=4"],
            "frontiers": [{
                "cell": {"x": 1, "z": 0},
                "center": {"x": 12.0, "z": 4.0},
                "from_cell": {"x": 0, "z": 0},
                "direction": "east",
                "nearby_resources": ["coal_ore"],
                "score": 2.5,
            }],
            "resource_hotspots": [{
                "resource": "coal_ore",
                "cell": {"x": 1, "z": 0},
                "center": {"x": 12.0, "z": 4.0},
                "danger_count": 0,
                "visit_count": 1,
            }],
            "danger_cells": [{
                "cell": {"x": 1, "z": 1},
                "center": {"x": 12.0, "z": 12.0},
                "danger_count": 1,
            }],
        },
        "errors": [],
        "cases": [{"ready_for_world_model_review": True}],
    }
    thin_report = {
        "log_count": 1,
        "ready_log_count": 0,
        "frontier_count": 0,
        "resource_hotspot_count": 0,
        "world_model_feedback": {"frontiers": [], "resource_hotspots": [], "suggested_goals": []},
        "errors": [],
        "cases": [{"ready_for_world_model_review": False}],
    }

    approved = runner.build_world_model_feedback_gate(world_model_reports=[approved_report])
    review = runner.build_world_model_feedback_gate(world_model_reports=[thin_report])

    assert approved["type"] == "world_model_feedback_gate"
    assert approved["schema_version"] == 1
    assert approved["readiness"] == "approved"
    assert approved["decision"] == "allow_world_model_feedback"
    assert approved["ready_log_count"] == 1
    assert approved["structured_frontier_count"] == 1
    assert approved["structured_hotspot_count"] == 1
    assert "use_frontier_feedback_for_autonomous_curriculum" in approved["policy_hints"]
    assert "use_resource_hotspots_with_danger_aware_routes" in approved["policy_hints"]
    assert review["readiness"] == "review"
    assert "ready_world_model_logs" in review["missing"]
    assert "structured_cell_feedback" in review["missing"]
    assert "keep_world_model_feedback_review_only" in review["policy_hints"]
    print("PASS: World model feedback gate requires structured map evidence")


def test_self_evolution_report_tracks_progress_and_stagnation():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_self_evolution.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Craft torches after finding coal"}},
        {
            "type": "observation",
            "data": {
                "position": {"x": 0, "y": 64, "z": 0},
                "inventory": {"stick": 1},
                "health": 20,
            },
        },
        {"type": "action", "data": {"action": {"type": "move_to"}, "result": {"success": True}}},
        {
            "type": "observation",
            "data": {
                "position": {"x": 4, "y": 64, "z": 0},
                "inventory": {"stick": 1, "coal": 2},
                "health": 20,
            },
        },
        {
            "type": "action",
            "data": {
                "action": {"type": "dig", "parameters": {"block": "coal_ore"}},
                "result": {"success": False, "error": "no target visible"},
            },
        },
        {
            "type": "action",
            "data": {
                "action": {"type": "dig", "parameters": {"block": "coal_ore"}},
                "result": {"success": False, "error": "no target visible"},
            },
        },
        {
            "type": "observation",
            "data": {
                "position": {"x": 4, "y": 64, "z": 0},
                "inventory": {"stick": 1, "coal": 2},
                "health": 18,
            },
        },
        {
            "type": "observation",
            "data": {
                "position": {"x": 4, "y": 64, "z": 0},
                "inventory": {"stick": 1, "coal": 2},
                "health": 18,
            },
        },
        {
            "type": "action",
            "data": {
                "action": {"type": "wait", "parameters": {"ms": 200}},
                "result": {"success": True, "action_type": "wait"},
            },
        },
        {
            "type": "observation",
            "data": {
                "position": {"x": 4, "y": 64, "z": 0},
                "inventory": {"stick": 1, "coal": 2},
                "health": 18,
            },
        },
        {
            "type": "action",
            "data": {
                "action": {"type": "wait", "parameters": {"ms": 200}},
                "result": {"success": True, "action_type": "wait"},
            },
        },
        {
            "type": "observation",
            "data": {
                "position": {"x": 4, "y": 64, "z": 0},
                "inventory": {"stick": 1, "coal": 2},
                "health": 18,
            },
        },
        {"type": "goal_verification", "data": {"goal": "Craft torches", "achieved": False, "status": "failed"}},
        {"type": "goal_end", "data": {"goal": "Craft torches after finding coal", "result": {"completed": False}}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config(memory_dir=os.path.join(tmpdir, "memory")))
    report = runner.run_self_evolution_report_from_logs([session_path])
    case = report.cases[0]
    feedback = runner.self_evolution_feedback(report)

    assert report.log_count == 1
    assert report.ready_log_count == 1
    assert case.progress_signal_count >= 3
    assert case.regression_signal_count >= 4
    assert case.stagnation_signal_count >= 2
    assert case.inventory_gain_count == 1
    assert case.failed_action_count == 2
    assert case.repeated_failure_count == 1
    assert case.no_progress_success_count == 2
    assert case.repeated_success_loop_count == 1
    assert case.action_failure_categories["perception"] == 2
    assert case.typed_feedback_counts["monitor_inventory_gain"] == 1
    assert case.typed_feedback_counts["monitor_no_progress_success"] == 2
    assert case.typed_feedback_counts["monitor_repeated_success_loop"] == 1
    assert case.typed_feedback_counts["monitor_verification_failure"] == 1
    assert any("scan/look_at" in recommendation for recommendation in case.adaptor_recommendations)
    assert any("state, inventory, or verifier delta" in recommendation for recommendation in case.adaptor_recommendations)
    assert any("coal_ore" in remedy for remedy in case.remedy_candidates)
    assert feedback["action_failure_categories"]["perception"] == 2
    policies = {hint["self_evolution_policy"] for hint in feedback["policy_hints"]}
    assert "repair_stagnant_plan_suffix" in policies
    assert "verify_successful_actions_with_state_delta" in policies
    assert "induce_failure_remedies" in policies

    class CapturePolicy:
        def __init__(self):
            self.feedback = None

        def record_self_evolution_feedback(self, payload):
            self.feedback = payload

    policy = CapturePolicy()
    applied = runner.apply_self_evolution_feedback(report, policy)
    assert applied == feedback
    assert policy.feedback["stagnation_signal_count"] == case.stagnation_signal_count
    assert policy.feedback["no_progress_success_count"] == 2
    print("PASS: Self-evolution report tracks progress and stagnation")


def test_self_evolution_report_flags_zero_action_blocked_plan_failure():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_zero_action_blocked.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Mine cobblestone"}},
        {
            "type": "observation",
            "data": {
                "position": {"x": 0, "y": 64, "z": 0},
                "inventory": {},
                "health": 20,
            },
        },
        {"type": "plan", "data": {"status": "blocked", "reasoning": "Need pickaxe", "actions": []}},
        {
            "type": "observation",
            "data": {
                "position": {"x": 0, "y": 64, "z": 0},
                "inventory": {},
                "health": 20,
            },
        },
        {"type": "plan", "data": {"status": "blocked", "reasoning": "Need materials", "actions": []}},
        {"type": "blocked_plan", "data": {"goal": "Mine cobblestone", "cycle": 2, "reasoning": "Need materials"}},
        {"type": "goal_end", "data": {"goal": "Mine cobblestone", "result": {"completed": False}}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config(memory_dir=os.path.join(tmpdir, "memory")))
    report = runner.run_self_evolution_report_from_logs([session_path])
    case = report.cases[0]
    feedback = runner.self_evolution_feedback(report)

    assert report.ready_log_count == 1
    assert case.action_count == 0
    assert case.blocked_plan_count == 2
    assert case.empty_plan_count == 2
    assert case.zero_action_failure_count == 1
    assert case.typed_feedback_counts["monitor_blocked_plan_loop"] == 2
    assert any("prerequisite fallback" in recommendation for recommendation in case.adaptor_recommendations)
    assert feedback["blocked_plan_count"] == 2
    assert feedback["empty_plan_count"] == 2
    assert feedback["zero_action_failure_count"] == 1
    policies = {hint["self_evolution_policy"] for hint in feedback["policy_hints"]}
    assert "repair_blocked_plan_or_prerequisite_fallback" in policies
    print("PASS: Self-evolution report flags zero-action blocked plan failures")


def test_plan_action_compliance_report_tracks_plan_following_gaps():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_plan_action_compliance.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Craft a table and collect logs"}},
        {
            "type": "plan",
            "data": {
                "status": "in_progress",
                "reasoning": "Craft materials in order",
                "actions": [
                    {"type": "craft", "parameters": {"item": "oak_planks"}},
                    {"type": "craft", "parameters": {"item": "crafting_table"}},
                ],
            },
        },
        {
            "type": "action",
            "data": {
                "action": {"type": "craft", "parameters": {"item": "crafting_table"}},
                "result": {"success": True},
            },
        },
        {
            "type": "action",
            "data": {
                "action": {"type": "craft", "parameters": {"item": "oak_planks"}},
                "result": {"success": True},
            },
        },
        {
            "type": "plan",
            "data": {
                "status": "in_progress",
                "reasoning": "Gather logs and then make sticks",
                "actions": [
                    {"type": "dig", "parameters": {"block": "oak_log"}},
                    {"type": "craft", "parameters": {"item": "stick"}},
                ],
            },
        },
        {
            "type": "action",
            "data": {
                "action": {"type": "dig", "parameters": {"block": "oak_log"}},
                "result": {"success": True},
            },
        },
        {
            "type": "action",
            "data": {
                "action": {"type": "wait", "parameters": {"ms": 200}},
                "result": {"success": True},
            },
        },
        {"type": "plan", "data": {"status": "blocked", "reasoning": "Need materials", "actions": []}},
        {"type": "goal_end", "data": {"goal": "Craft a table and collect logs", "result": {"completed": False}}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config(memory_dir=os.path.join(tmpdir, "memory")))
    report = runner.run_plan_action_compliance_report_from_logs([session_path])
    case = report.cases[0]
    feedback = runner.plan_action_compliance_feedback(report)

    assert report.ready_log_count == 1
    assert case.plan_count == 3
    assert case.action_count == 4
    assert case.planned_action_count == 4
    assert case.unordered_match_count == 3
    assert case.ordered_match_count == 2
    assert case.order_violation_count == 1
    assert case.missing_planned_action_count == 1
    assert case.unplanned_action_count == 1
    assert case.empty_plan_count == 1
    assert case.blocked_plan_count == 1
    assert case.plan_follow_score == 0.5
    assert case.action_precision == 0.75
    assert case.compliance_score == 0.286
    assert case.mismatch_examples
    policies = {hint["plan_action_policy"] for hint in feedback["policy_hints"]}
    assert "repair_or_remind_unexecuted_plan_steps" in policies
    assert "preserve_plan_order_or_replan_explicitly" in policies
    assert "explain_unplanned_runtime_actions" in policies
    assert "avoid_empty_executable_plans" in policies
    print("PASS: Plan-action compliance report tracks plan-following gaps")


def test_plan_act_latency_report_counts_interrupt_opportunities():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "plan_act.jsonl")
    events = [
        {"ts": 100.0, "type": "goal_start", "data": {"goal": "Gather wood"}},
        {"ts": 101.0, "type": "observation", "data": {"inventory": {}}},
        {
            "ts": 102.0,
            "type": "plan",
            "data": {
                "status": "in_progress",
                "actions": [
                    {"type": "move_to", "parameters": {"target": "oak_tree"}},
                    {"type": "dig", "parameters": {"block": "oak_log"}},
                ],
            },
        },
        {
            "ts": 110.0,
            "type": "action",
            "data": {
                "action": {"type": "move_to", "parameters": {"target": "oak_tree"}},
                "result": {"success": True, "duration_ms": 6000},
            },
        },
        {"ts": 111.0, "type": "observation", "data": {"nearby_blocks": [{"name": "oak_log"}]}},
        {
            "ts": 112.0,
            "type": "plan",
            "data": {
                "status": "in_progress",
                "actions": [{"type": "dig", "parameters": {"block": "oak_log"}}],
            },
        },
        {
            "ts": 113.0,
            "type": "action",
            "data": {
                "action": {"type": "dig", "parameters": {"block": "oak_log"}},
                "result": {"success": True, "duration_ms": 500},
            },
        },
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config())
    report = runner.build_plan_act_latency_report(
        session_log_paths=[session_path],
        stale_plan_s=1.0,
        long_action_s=2.0,
    )

    assert report["type"] == "plan_act_latency_report"
    assert report["readiness"] == "review"
    assert report["session_log_count"] == 1
    assert report["plan_count"] == 2
    assert report["action_count"] == 2
    assert report["long_action_count"] == 1
    assert report["stale_plan_action_count"] == 1
    assert report["unfinished_plan_suffix_count"] == 1
    assert report["interrupt_opportunity_count"] >= 3
    assert "allow_interrupts_for_long_running_actions" in report["policy_hints"]
    assert "replace_unfinished_plan_suffix_on_replan" in report["policy_hints"]
    case = report["cases"][0]
    assert case["planner_wait_avg_s"] == 1.0
    assert case["plan_to_action_delay_avg_s"] > 0
    print("PASS: Plan-act latency report counts interrupt opportunities")


def test_plan_act_latency_report_extracts_collab_role_logs_and_overlap():
    tmpdir = tempfile.mkdtemp()
    left_log = os.path.join(tmpdir, "role_left.jsonl")
    right_log = os.path.join(tmpdir, "role_right.jsonl")

    def write_log(path, action_type, end_ts):
        events = [
            {"ts": end_ts - 4.5, "type": "observation", "data": {}},
            {"ts": end_ts - 4.0, "type": "plan", "data": {"actions": [{"type": action_type}]}},
            {
                "ts": end_ts,
                "type": "action",
                "data": {
                    "action": {"type": action_type},
                    "result": {"success": True, "duration_ms": 3000},
                },
            },
        ]
        with open(path, "w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

    write_log(left_log, "gather", 205.0)
    write_log(right_log, "build", 206.0)
    collab_report = os.path.join(tmpdir, "collab.json")
    with open(collab_report, "w", encoding="utf-8") as f:
        json.dump({
            "type": "collaboration_benchmark",
            "execution": {
                "task_results": [
                    {"result": {"agent_result": {"summary": {"log_path": left_log}}}},
                    {"result": {"session_log_path": right_log}},
                ]
            },
        }, f)

    runner = BenchmarkRunner(Config())
    report = runner.build_plan_act_latency_report(
        collab_report_paths=[collab_report],
        long_action_s=2.0,
    )

    assert report["collab_report_count"] == 1
    assert report["session_log_count"] == 2
    assert report["action_count"] == 2
    assert report["actual_peak_parallel_actions"] == 2
    assert report["cross_log_overlapping_action_pairs"] == 1
    assert report["cross_log_overlap_total_s"] == 2.0
    assert "preserve_role_parallel_dispatch" in report["policy_hints"]
    print("PASS: Plan-act latency report extracts collab role logs and overlap")


def test_plan_act_latency_gate_requires_candidate_and_verifier_evidence():
    tmpdir = tempfile.mkdtemp()
    baseline_path = os.path.join(tmpdir, "baseline_plan_act.json")
    with open(baseline_path, "w", encoding="utf-8") as f:
        json.dump({
            "type": "plan_act_latency_report",
            "session_log_count": 1,
            "stale_plan_action_count": 4,
            "interrupt_opportunity_count": 6,
            "errors": [],
        }, f)

    runner = BenchmarkRunner(Config())
    gate = runner.build_plan_act_latency_gate(baseline_report_paths=[baseline_path])

    assert gate["readiness"] == "review"
    assert gate["decision"] == "collect_plan_act_candidate_evidence"
    assert "candidate_plan_act_report" in gate["missing"]
    assert "baseline_verifier_report" in gate["missing"]
    assert "candidate_verifier_report" in gate["missing"]
    print("PASS: Plan-act latency gate requires candidate and verifier evidence")


def test_plan_act_latency_gate_approves_reduced_stale_without_verifier_regression():
    tmpdir = tempfile.mkdtemp()
    baseline_path = os.path.join(tmpdir, "baseline_plan_act.json")
    candidate_path = os.path.join(tmpdir, "candidate_plan_act.json")
    baseline_verifier_path = os.path.join(tmpdir, "baseline_verifier.json")
    candidate_verifier_path = os.path.join(tmpdir, "candidate_verifier.json")
    with open(baseline_path, "w", encoding="utf-8") as f:
        json.dump({
            "type": "plan_act_latency_report",
            "session_log_count": 2,
            "stale_plan_action_count": 8,
            "interrupt_opportunity_count": 14,
            "errors": [],
        }, f)
    with open(candidate_path, "w", encoding="utf-8") as f:
        json.dump({
            "type": "plan_act_latency_report",
            "session_log_count": 2,
            "stale_plan_action_count": 3,
            "interrupt_opportunity_count": 7,
            "errors": [],
        }, f)
    with open(baseline_verifier_path, "w", encoding="utf-8") as f:
        json.dump({"type": "action_verification_report", "failure_count": 1}, f)
    with open(candidate_verifier_path, "w", encoding="utf-8") as f:
        json.dump({"type": "action_verification_report", "failure_count": 1}, f)

    runner = BenchmarkRunner(Config())
    gate = runner.build_plan_act_latency_gate(
        baseline_report_paths=[baseline_path],
        candidate_report_paths=[candidate_path],
        baseline_verifier_report_paths=[baseline_verifier_path],
        candidate_verifier_report_paths=[candidate_verifier_path],
        min_stale_reduction=2,
    )

    assert gate["readiness"] == "approved"
    assert gate["decision"] == "allow_gated_interruptible_plan_act"
    assert gate["stale_action_delta"] == -5
    assert gate["verifier_reject_delta"] == 0
    assert "enable_interruptible_plan_act_behind_runtime_gate" in gate["policy_hints"]
    print("PASS: Plan-act latency gate approves reduced stale actions without verifier regression")


def test_plan_act_latency_gate_rejects_verifier_regression():
    tmpdir = tempfile.mkdtemp()
    baseline_path = os.path.join(tmpdir, "baseline_plan_act.json")
    candidate_path = os.path.join(tmpdir, "candidate_plan_act.json")
    baseline_verifier_path = os.path.join(tmpdir, "baseline_verifier.json")
    candidate_verifier_path = os.path.join(tmpdir, "candidate_verifier.json")
    payloads = {
        baseline_path: {
            "type": "plan_act_latency_report",
            "session_log_count": 2,
            "stale_plan_action_count": 8,
            "interrupt_opportunity_count": 14,
            "errors": [],
        },
        candidate_path: {
            "type": "plan_act_latency_report",
            "session_log_count": 2,
            "stale_plan_action_count": 3,
            "interrupt_opportunity_count": 7,
            "errors": [],
        },
        baseline_verifier_path: {"type": "action_verification_report", "failure_count": 1},
        candidate_verifier_path: {"type": "action_verification_report", "failure_count": 3},
    }
    for path, payload in payloads.items():
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

    runner = BenchmarkRunner(Config())
    gate = runner.build_plan_act_latency_gate(
        baseline_report_paths=[baseline_path],
        candidate_report_paths=[candidate_path],
        baseline_verifier_report_paths=[baseline_verifier_path],
        candidate_verifier_report_paths=[candidate_verifier_path],
    )

    assert gate["readiness"] == "rejected"
    assert gate["decision"] == "keep_interruptible_plan_act_disabled"
    assert gate["verifier_reject_delta"] == 2
    assert "reduce_verifier_rejections_before_interrupts" in gate["policy_hints"]
    print("PASS: Plan-act latency gate rejects verifier regression")


def test_terminal_commitment_report_separates_world_completion_from_reporting():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_terminal_commitment.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Craft torches"}},
        {"type": "observation", "data": {"inventory": {"torch": 4}}},
        {
            "type": "goal_verification",
            "data": {
                "goal": "Craft torches",
                "achieved": True,
                "status": "achieved",
                "evidence": ["torch inventory satisfied"],
            },
        },
        {"type": "goal_end", "data": {"goal": "Craft torches", "result": {"completed": True}}},
        {"type": "goal_start", "data": {"goal": "Gather 6 oak logs"}},
        {"type": "observation", "data": {"inventory": {"oak_log": 2}}},
        {
            "type": "goal_verification",
            "data": {
                "goal": "Gather 6 oak logs",
                "achieved": False,
                "status": "failed",
                "missing": ["need 6 oak_log, have 2"],
            },
        },
        {"type": "goal_end", "data": {"goal": "Gather 6 oak logs", "result": {"completed": True}}},
        {"type": "goal_start", "data": {"goal": "Craft a crafting table"}},
        {"type": "observation", "data": {"inventory": {"crafting_table": 1}}},
        {
            "type": "goal_verification",
            "data": {
                "goal": "Craft a crafting table",
                "achieved": True,
                "status": "achieved",
                "evidence": ["crafting_table present"],
            },
        },
        {"type": "goal_end", "data": {"goal": "Craft a crafting table", "result": {"completed": False}}},
        {"type": "goal_start", "data": {"goal": "Mine cobblestone"}},
        {"type": "observation", "data": {"inventory": {}}},
        {
            "type": "goal_verification",
            "data": {
                "goal": "Mine cobblestone",
                "achieved": False,
                "status": "failed",
                "missing": ["need cobblestone"],
            },
        },
        {"type": "goal_end", "data": {"goal": "Mine cobblestone", "result": {"completed": False}}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config(memory_dir=os.path.join(tmpdir, "memory")))
    report = runner.run_terminal_commitment_report_from_logs([session_path])
    feedback = runner.terminal_commitment_feedback(report)
    outcomes = {case.goal: case.outcome for case in report.cases}

    assert report.goal_count == 4
    assert report.ready_goal_count == 4
    assert report.world_complete_count == 2
    assert report.terminal_complete_count == 2
    assert report.verified_success_count == 1
    assert report.unsupported_commitment_count == 1
    assert report.post_attainment_drift_count == 1
    assert report.missed_execution_count == 1
    assert report.world_completion_score == 0.5
    assert report.terminal_commitment_score == 0.25
    assert outcomes["Craft torches"] == "verified_success"
    assert outcomes["Gather 6 oak logs"] == "unsupported_commitment"
    assert outcomes["Craft a crafting table"] == "post_attainment_drift"
    assert outcomes["Mine cobblestone"] == "missed_execution"
    policies = {hint["terminal_commitment_policy"] for hint in feedback["policy_hints"]}
    assert "reject_unsupported_completion_claims" in policies
    assert "commit_when_world_state_is_verified" in policies
    assert "repair_execution_before_completion_retry" in policies
    print("PASS: Terminal commitment report separates world completion from reporting")


def test_action_verification_report_replays_logged_actions():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "action_verification_session.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Craft torches and gather stone"}},
        {
            "type": "observation",
            "data": {
                "inventory": {"stick": 1},
                "nearby_blocks": [{"name": "stone"}],
                "nearby_entities": [],
            },
        },
        {
            "type": "action",
            "data": {
                "action": {"type": "craft", "parameters": {"item": "torch", "count": 4}},
                "result": {"success": False, "error": "Missing coal"},
            },
        },
        {
            "type": "action",
            "data": {
                "action": {"type": "dig", "parameters": {"block": "stone"}},
                "result": {"success": False, "error": "Missing pickaxe"},
            },
        },
        {
            "type": "observation",
            "data": {
                "inventory": {"oak_log": 1},
                "nearby_blocks": [{"name": "oak_log"}],
                "nearby_entities": [],
            },
        },
        {
            "type": "action",
            "data": {
                "action": {"type": "craft", "parameters": {"item": "oak_planks", "count": 4}},
                "result": {"success": True, "item": "oak_planks"},
            },
        },
        {
            "type": "action",
            "data": {
                "action": {"type": "dig", "parameters": {"x": 1, "y": 64, "z": 1}},
                "result": {"success": True, "block": "oak_log"},
            },
        },
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config())
    report = runner.run_action_verification_report_from_logs([session_path])
    case = report.cases[0]
    feedback = runner.action_verification_feedback(report)
    policies = {hint["action_verification_policy"] for hint in feedback["policy_hints"]}

    assert report.ready_log_count == 1
    assert case.action_count == 4
    assert case.rejected_action_count == 2
    assert case.accepted_action_count == 1
    assert case.review_action_count == 1
    assert case.failed_without_reject_count == 0
    assert "block_rejected_actions_before_execution" in policies
    print("PASS: Action verification report replays logged action feasibility gaps")


def test_action_candidate_report_replays_repairable_rejected_actions():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "action_candidate_session.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Craft torches"}},
        {
            "type": "observation",
            "data": {
                "inventory": {"stick": 1, "wooden_pickaxe": 1},
                "nearby_blocks": [{"name": "coal_ore"}],
                "nearby_entities": [],
            },
        },
        {
            "type": "action",
            "data": {
                "action": {"type": "craft", "parameters": {"item": "torch", "count": 4}},
                "result": {"success": False, "error": "Missing coal"},
            },
        },
        {
            "type": "observation",
            "data": {
                "inventory": {"oak_log": 1},
                "nearby_blocks": [{"name": "oak_log"}],
                "nearby_entities": [],
            },
        },
        {
            "type": "action",
            "data": {
                "action": {"type": "craft", "parameters": {"item": "oak_planks", "count": 4}},
                "result": {"success": True, "item": "oak_planks"},
            },
        },
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config())
    report = runner.run_action_candidate_report_from_logs([session_path])
    case = report.cases[0]
    feedback = runner.action_candidate_feedback(report)
    policies = {hint["action_candidate_policy"] for hint in feedback["policy_hints"]}

    assert report.ready_log_count == 1
    assert case.action_count == 2
    assert case.original_reject_count == 1
    assert case.changed_selection_count == 1
    assert case.repaired_reject_count == 1
    assert case.unchanged_reject_count == 0
    assert case.examples[0]["selected_action"]["type"] == "dig"
    assert "enable_repair_candidate_selection_for_rejected_actions" in policies
    print("PASS: Action candidate report replays repairable rejected actions")


def test_action_value_report_aggregates_outcome_profiles():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "action_value_session.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Craft torches"}},
        {"type": "observation", "data": {"position": {"x": 0, "y": 64, "z": 0}, "health": 20, "inventory": {}, "nearby_blocks": [{"name": "coal_ore"}]}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "torch"}}, "result": {"success": False, "error": "Missing coal"}}},
        {"type": "observation", "data": {"position": {"x": 0, "y": 64, "z": 0}, "health": 20, "inventory": {}, "nearby_blocks": [{"name": "coal_ore"}]}},
        {"type": "action", "data": {"action": {"type": "dig", "parameters": {"block": "coal_ore"}}, "result": {"success": True}}},
        {"type": "observation", "data": {"position": {"x": 0, "y": 64, "z": 0}, "health": 20, "inventory": {"coal": 1}, "nearby_blocks": [{"name": "coal_ore"}]}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "torch"}}, "result": {"success": False, "error": "Missing coal"}}},
        {"type": "observation", "data": {"position": {"x": 0, "y": 64, "z": 0}, "health": 20, "inventory": {"coal": 1}, "nearby_blocks": [{"name": "coal_ore"}]}},
        {"type": "action", "data": {"action": {"type": "dig", "parameters": {"block": "coal_ore"}}, "result": {"success": True}}},
        {"type": "observation", "data": {"position": {"x": 0, "y": 64, "z": 0}, "health": 20, "inventory": {"coal": 2}, "nearby_blocks": [{"name": "coal_ore"}]}},
        {"type": "action", "data": {"action": {"type": "dig", "parameters": {"block": "coal_ore"}}, "result": {"success": True}}},
        {"type": "observation", "data": {"position": {"x": 0, "y": 64, "z": 0}, "health": 20, "inventory": {"coal": 3}, "nearby_blocks": [{"name": "coal_ore"}]}},
        {"type": "action", "data": {"action": {"type": "dig", "parameters": {"block": "coal_ore"}}, "result": {"success": True}}},
        {"type": "observation", "data": {"position": {"x": 0, "y": 64, "z": 0}, "health": 20, "inventory": {"coal": 4}, "nearby_blocks": [{"name": "coal_ore"}]}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config())
    report = runner.run_action_value_report_from_logs([session_path])
    feedback = runner.action_value_feedback(report)
    items = {item["signature"]: item for item in feedback["action_value_items"]}
    transition_items = {item["signature"]: item for item in feedback["state_transition_value_items"]}
    policies = {hint["action_value_policy"] for hint in feedback["policy_hints"]}

    assert report.ready_log_count == 1
    assert report.action_count == 6
    assert report.success_count == 4
    assert report.failure_count == 2
    assert report.failure_correction_pair_count == 2
    assert report.state_transition_count == 6
    assert report.positive_transition_count == 4
    assert report.negative_transition_count == 2
    assert report.low_confidence_transition_count == 0
    assert report.action_local_transition_count == 0
    assert report.next_observation_transition_count == 6
    assert report.shared_observation_transition_count == 0
    assert feedback["failure_correction_pairs"][0]["source_log"] == session_path
    assert feedback["state_transition_count"] == 6
    assert feedback["low_confidence_transition_count"] == 0
    assert feedback["transition_window_diagnostics"]["transition_coverage_rate"] == 1.0
    assert feedback["transition_window_diagnostics"]["next_observation_transition_count"] == 6
    assert items["dig:coal_ore"]["attempts"] == 4
    assert items["dig:coal_ore"]["value_score"] >= 0.7
    assert items["craft:torch"]["failures"] == 2
    assert transition_items["dig:coal_ore"]["positive_transitions"] == 4
    assert transition_items["dig:coal_ore"]["avg_state_value_delta"] > 0
    assert transition_items["craft:torch"]["negative_transitions"] == 2
    assert "prefer_high_value_action_signatures" in policies
    assert "mine_failure_correction_pairs_for_repair_candidates" in policies
    assert "score_actions_by_state_transition_value" in policies
    print("PASS: Action value report aggregates outcome profiles and repair pairs")


def test_knowledge_correction_report_mines_failed_actions_and_dependencies():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "knowledge_correction_session.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Craft torches"}},
        {"type": "observation", "data": {"position": {"x": 0, "y": 64, "z": 0}, "health": 20, "inventory": {}, "nearby_blocks": [{"name": "coal_ore"}]}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "torch"}}, "result": {"success": False, "error": "Missing coal"}}},
        {"type": "observation", "data": {"position": {"x": 0, "y": 64, "z": 0}, "health": 20, "inventory": {}, "nearby_blocks": [{"name": "coal_ore"}]}},
        {"type": "action", "data": {"action": {"type": "dig", "parameters": {"block": "coal_ore"}}, "result": {"success": True}}},
        {"type": "observation", "data": {"position": {"x": 0, "y": 64, "z": 0}, "health": 20, "inventory": {"coal": 1}, "nearby_blocks": [{"name": "coal_ore"}]}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "torch"}}, "result": {"success": False, "error": "Missing coal"}}},
        {"type": "observation", "data": {"position": {"x": 0, "y": 64, "z": 0}, "health": 20, "inventory": {"coal": 1}, "nearby_blocks": [{"name": "coal_ore"}]}},
        {"type": "action", "data": {"action": {"type": "dig", "parameters": {"block": "coal_ore"}}, "result": {"success": True}}},
        {"type": "observation", "data": {"position": {"x": 0, "y": 64, "z": 0}, "health": 20, "inventory": {"coal": 2}, "nearby_blocks": [{"name": "coal_ore"}]}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config())
    report = runner.run_knowledge_correction_report_from_logs([session_path])
    feedback = runner.knowledge_correction_feedback(report)
    dependencies = {
        (item["failed_signature"], item["recovery_signature"]): item
        for item in feedback["dependency_corrections"]
    }
    failed_memories = {item["signature"]: item for item in feedback["failure_action_memories"]}
    policies = {hint["knowledge_correction_policy"] for hint in feedback["policy_hints"]}

    assert report.ready_log_count == 1
    assert report.dependency_correction_count == 1
    assert report.failure_action_memory_count == 1
    assert ("craft:torch", "dig:coal_ore") in dependencies
    assert dependencies[("craft:torch", "dig:coal_ore")]["evidence_count"] == 2
    assert "torch" in dependencies[("craft:torch", "dig:coal_ore")]["target_items"]
    assert dependencies[("craft:torch", "dig:coal_ore")]["knowledge_dimensions"]["interaction"] == ["dig_before_craft"]
    assert failed_memories["craft:torch"]["failures"] == 2
    assert failed_memories["craft:torch"]["recommendation"] == "avoid_or_replan_until_preconditions_change"
    assert "review_dependency_graph_corrections" in policies
    assert "review_failed_action_memories" in policies

    gate = runner.build_knowledge_correction_gate(
        knowledge_correction_reports=[feedback],
        min_ready_logs=1,
        min_corrections=2,
    )
    assert gate["readiness"] == "approved"
    assert gate["decision"] == "allow_reviewed_knowledge_correction_feedback"
    assert gate["correction_count"] == 2
    print("PASS: Knowledge correction report mines failed actions and dependencies")


def test_task_precondition_report_mines_hidden_prerequisites_from_failures():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "task_preconditions_session.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Craft torches then mine iron ore"}},
        {"type": "observation", "data": {"inventory": {}, "nearby_blocks": [{"name": "coal_ore"}, {"name": "iron_ore"}]}},
        {
            "type": "action",
            "data": {
                "action": {"type": "craft", "parameters": {"item": "torch"}},
                "result": {"success": False, "error": "Missing coal and stick"},
            },
        },
        {"type": "observation", "data": {"inventory": {"wooden_pickaxe": 1}, "nearby_blocks": [{"name": "iron_ore"}]}},
        {
            "type": "action",
            "data": {
                "action": {"type": "dig", "parameters": {"block": "iron_ore"}},
                "result": {"success": False, "error": "requires stone pickaxe tool"},
            },
        },
        {
            "type": "blocked_plan",
            "data": {
                "goal": "Craft stone pickaxe before mining iron ore",
                "reasoning": "Need cobblestone and sticks before retrying iron ore",
            },
        },
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config())
    report = runner.run_task_precondition_report_from_logs([session_path])
    feedback = runner.task_precondition_feedback(report)
    candidate_by_type = {}
    for candidate in report["candidates"]:
        candidate_by_type.setdefault(candidate["candidate_type"], []).append(candidate)
    policies = {hint["task_precondition_policy"] for hint in feedback["policy_hints"]}

    assert report["ready_log_count"] == 1
    assert report["failed_action_count"] == 2
    assert report["blocked_plan_count"] == 1
    assert report["candidate_count"] >= 3
    assert report["candidate_type_counts"]["inventory_precondition"] >= 1
    assert report["candidate_type_counts"]["tool_precondition"] == 1
    assert report["candidate_type_counts"]["blocked_plan_prerequisite"] == 1
    craft_candidate = next(item for item in candidate_by_type["inventory_precondition"] if item["action_signature"] == "craft:torch")
    assert craft_candidate["inferred_preconditions"]["inventory"]["coal"] == 1
    assert craft_candidate["inferred_preconditions"]["inventory"]["stick"] == 1
    tool_candidate = candidate_by_type["tool_precondition"][0]
    assert tool_candidate["action_signature"] == "dig:iron_ore"
    assert tool_candidate["inferred_preconditions"]["inventory"]["stone_pickaxe"] == 1
    assert tool_candidate["inferred_preconditions"]["tool_for"]["iron_ore"] == "stone_pickaxe"
    assert "review_task_precondition_candidates" in policies
    assert "add_inventory_preconditions_before_crafting" in policies
    assert "add_tool_preconditions_before_mining" in policies
    print("PASS: Task precondition report mines hidden prerequisites from failures")


def test_task_precondition_gate_requires_ready_candidates():
    runner = BenchmarkRunner(Config())
    ready_report = {
        "type": "task_precondition_report",
        "log_count": 1,
        "ready_log_count": 1,
        "failed_action_count": 2,
        "blocked_plan_count": 1,
        "empty_plan_count": 0,
        "candidate_count": 2,
        "candidate_type_counts": {
            "inventory_precondition": 1,
            "tool_precondition": 1,
        },
        "candidates": [
            {
                "candidate_type": "inventory_precondition",
                "action_signature": "craft:torch",
                "confidence": 0.82,
            },
            {
                "candidate_type": "tool_precondition",
                "action_signature": "dig:iron_ore",
                "confidence": 0.71,
            },
        ],
    }

    approved = runner.build_task_precondition_gate(
        task_precondition_reports=[ready_report],
        min_ready_logs=1,
        min_candidates=2,
        min_high_confidence_candidates=2,
        min_confidence=0.7,
    )
    assert approved["readiness"] == "approved"
    assert approved["decision"] == "allow_reviewed_task_precondition_feedback"
    assert approved["candidate_count"] == 2
    assert approved["high_confidence_candidate_count"] == 2
    assert approved["candidate_type_counts"]["tool_precondition"] == 1
    assert "load_task_precondition_feedback_with_gate" in approved["policy_hints"]

    review = runner.build_task_precondition_gate(
        task_precondition_reports=[{
            "type": "task_precondition_report",
            "log_count": 1,
            "ready_log_count": 0,
            "candidate_count": 0,
            "candidates": [],
        }],
        min_ready_logs=1,
        min_candidates=1,
    )
    assert review["readiness"] == "review"
    assert "ready_task_precondition_logs" in review["missing"]
    assert "task_precondition_candidates" in review["missing"]
    print("PASS: Task precondition gate requires ready candidates")


def test_knowledge_correction_preflight_requires_gate_and_suite_overlap():
    tmpdir = tempfile.mkdtemp()
    feedback_path = os.path.join(tmpdir, "knowledge_correction.json")
    gate_path = os.path.join(tmpdir, "knowledge_correction_gate.json")
    feedback = {
        "log_count": 1,
        "ready_log_count": 1,
        "dependency_correction_count": 1,
        "failure_action_memory_count": 1,
        "dependency_corrections": [
            {
                "type": "dependency_correction",
                "goal": "Craft torches",
                "failed_signature": "craft:torch",
                "recovery_signature": "dig:coal_ore",
                "target_items": ["torch"],
                "evidence_count": 2,
                "confidence": 0.85,
                "correction": "Before retrying craft:torch, collect or expose coal_ore with dig when the goal is Craft torches.",
                "knowledge_dimensions": {
                    "attribute": ["crafting", "torch"],
                    "interaction": ["dig_before_craft"],
                },
            },
        ],
        "failure_action_memories": [
            {
                "type": "failed_action_memory",
                "signature": "craft:torch",
                "action_type": "craft",
                "attempts": 3,
                "failures": 3,
                "task_families": {"crafting": 3},
                "recommendation": "avoid_or_replan_until_preconditions_change",
                "reason": "repeated_failed_action",
            },
        ],
        "policy_hints": [
            {
                "knowledge_correction_policy": "review_dependency_graph_corrections",
                "priority": "high",
                "count": 1,
            },
        ],
    }
    with open(feedback_path, "w", encoding="utf-8") as f:
        json.dump({"knowledge_correction_feedback": feedback}, f)
    with open(gate_path, "w", encoding="utf-8") as f:
        json.dump({
            "type": "knowledge_correction_gate",
            "readiness": "approved",
            "decision": "allow_reviewed_knowledge_correction_feedback",
            "reason": "reviewable correction evidence is present",
            "source_count": 1,
            "ready_log_count": 1,
            "correction_count": 2,
            "dependency_correction_count": 1,
            "failure_action_memory_count": 1,
        }, f)

    task = BenchmarkTask("BM-KC", "Craft torches", "Craft torches", "M1")
    approved_runner = BenchmarkRunner(Config(
        knowledge_correction_feedback_paths=[feedback_path],
        knowledge_correction_gate_paths=[gate_path],
    ))
    approved = approved_runner.run_knowledge_correction_preflight(tasks=[task], suite="m1")

    assert approved["ready"] is True
    assert approved["readiness"] == "approved"
    assert approved["decision"] == "allow_knowledge_correction_benchmark"
    assert approved["gate_approved"] is True
    assert approved["dependency_correction_count"] == 1
    assert approved["failure_action_memory_count"] == 1
    assert approved["matched_case_count"] == 1
    assert approved["coverage_rate"] == 1.0
    assert approved["cases"][0]["matched"] is True
    assert "craft:torch->dig:coal_ore" in approved["cases"][0]["matched_signatures"]

    ungated_runner = BenchmarkRunner(Config(knowledge_correction_feedback_paths=[feedback_path]))
    ungated = ungated_runner.run_knowledge_correction_preflight(tasks=[task], suite="m1")

    assert ungated["ready"] is False
    assert ungated["gate_approved"] is False
    assert ungated["gate_readiness"] == "missing"
    assert "knowledge_correction_gate" in ungated["missing"]

    no_overlap_task = BenchmarkTask("BM-NAV", "Navigate away", "Travel to a desert village", "M1")
    no_overlap = approved_runner.run_knowledge_correction_preflight(tasks=[no_overlap_task], suite="m1")

    assert no_overlap["ready"] is False
    assert no_overlap["matched_case_count"] == 0
    assert "benchmark_suite_knowledge_correction_overlap" in no_overlap["missing"]
    print("PASS: Knowledge correction preflight requires gate and suite overlap")


def test_knowledge_correction_ablation_reports_context_changes():
    tmpdir = tempfile.mkdtemp()
    feedback_path = os.path.join(tmpdir, "knowledge_correction.json")
    gate_path = os.path.join(tmpdir, "knowledge_correction_gate.json")
    feedback = {
        "ready_log_count": 1,
        "dependency_correction_count": 1,
        "failure_action_memory_count": 1,
        "dependency_corrections": [
            {
                "type": "dependency_correction",
                "goal": "Craft torches",
                "failed_signature": "craft:torch",
                "recovery_signature": "dig:coal_ore",
                "target_items": ["torch"],
                "evidence_count": 2,
                "confidence": 0.85,
                "correction": "Before retrying craft:torch, collect or expose coal_ore with dig when the goal is Craft torches.",
                "knowledge_dimensions": {
                    "attribute": ["crafting", "torch"],
                    "interaction": ["dig_before_craft"],
                },
            },
        ],
        "failure_action_memories": [
            {
                "type": "failed_action_memory",
                "signature": "craft:torch",
                "action_type": "craft",
                "attempts": 3,
                "failures": 3,
                "task_families": {"crafting": 3},
                "recommendation": "avoid_or_replan_until_preconditions_change",
                "reason": "repeated_failed_action",
            },
        ],
    }
    with open(feedback_path, "w", encoding="utf-8") as f:
        json.dump({"knowledge_correction_feedback": feedback}, f)
    with open(gate_path, "w", encoding="utf-8") as f:
        json.dump({
            "type": "knowledge_correction_gate",
            "readiness": "approved",
            "decision": "allow_reviewed_knowledge_correction_feedback",
            "reason": "reviewable correction evidence is present",
            "source_count": 1,
            "ready_log_count": 1,
            "correction_count": 2,
            "dependency_correction_count": 1,
            "failure_action_memory_count": 1,
        }, f)

    cases = [
        {
            "id": "torch",
            "goal": "Craft torches",
            "current_state": {"inventory": {"stick": 1}},
        },
        {
            "id": "travel",
            "goal": "Travel to a desert village",
            "current_state": {},
        },
    ]
    approved_runner = BenchmarkRunner(Config(
        log_dir=os.path.join(tmpdir, "logs"),
        memory_dir=os.path.join(tmpdir, "memory"),
        skill_dir=os.path.join(tmpdir, "skills"),
        knowledge_correction_feedback_paths=[feedback_path],
        knowledge_correction_gate_paths=[gate_path],
    ))
    approved = approved_runner.run_knowledge_correction_ablation(cases=cases, suite="m1")

    assert approved["ready"] is True
    assert approved["readiness"] == "approved"
    assert approved["changed_count"] == 1
    assert approved["enabled_context_count"] == 1
    assert approved["dependency_context_count"] == 1
    assert approved["failure_memory_context_count"] == 1
    torch_case = next(case for case in approved["cases"] if case["id"] == "torch")
    travel_case = next(case for case in approved["cases"] if case["id"] == "travel")
    assert torch_case["changed"] is True
    assert "craft:torch" in torch_case["enabled_context_preview"]
    assert "dig:coal_ore" in torch_case["enabled_context_preview"]
    assert travel_case["changed"] is False

    ungated_runner = BenchmarkRunner(Config(
        log_dir=os.path.join(tmpdir, "logs_ungated"),
        memory_dir=os.path.join(tmpdir, "memory_ungated"),
        skill_dir=os.path.join(tmpdir, "skills_ungated"),
        knowledge_correction_feedback_paths=[feedback_path],
    ))
    ungated = ungated_runner.run_knowledge_correction_ablation(cases=cases, suite="m1")

    assert ungated["ready"] is False
    assert ungated["gate_approved"] is False
    assert ungated["changed_count"] == 0
    assert all(not case["enabled_context_preview"] for case in ungated["cases"])
    print("PASS: Knowledge correction ablation reports context changes")


def test_knowledge_correction_review_labels_emit_approved_feedback():
    tmpdir = tempfile.mkdtemp()
    report_path = os.path.join(tmpdir, "knowledge_correction.json")
    label_path = os.path.join(tmpdir, "knowledge_correction_labels.jsonl")
    feedback = {
        "log_count": 1,
        "ready_log_count": 1,
        "dependency_correction_count": 1,
        "failure_action_memory_count": 1,
        "dependency_corrections": [
            {
                "type": "dependency_correction",
                "goal": "Craft torches",
                "failed_signature": "craft:torch",
                "recovery_signature": "dig:coal_ore",
                "target_items": ["torch"],
                "evidence_count": 2,
                "confidence": 0.85,
                "correction": "Before retrying craft:torch, collect or expose coal_ore with dig when the goal is Craft torches.",
                "knowledge_dimensions": {"attribute": ["crafting", "torch"]},
            },
        ],
        "failure_action_memories": [
            {
                "type": "failed_action_memory",
                "signature": "craft:torch",
                "action_type": "craft",
                "attempts": 3,
                "failures": 3,
                "task_families": {"crafting": 3},
                "recommendation": "avoid_or_replan_until_preconditions_change",
                "reason": "repeated_failed_action",
            },
        ],
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({"knowledge_correction_feedback": feedback}, f)

    runner = BenchmarkRunner(Config())
    templates = runner.build_knowledge_correction_review_templates(
        knowledge_correction_report_paths=[report_path],
    )
    assert len(templates) == 2
    assert {template["correction_type"] for template in templates} == {
        "dependency_correction",
        "failed_action_memory",
    }
    assert all(template["readiness"] == "unknown" for template in templates)
    assert all(template["item"] for template in templates)

    filled = []
    for template in templates:
        record = dict(template)
        record["readiness"] = "approved" if template["correction_type"] == "dependency_correction" else "review"
        record["notes"] = "manual check"
        filled.append(record)
    with open(label_path, "w", encoding="utf-8") as f:
        for record in filled:
            f.write(json.dumps(record) + "\n")

    validation = runner.validate_knowledge_correction_review_labels(
        label_path=label_path,
        knowledge_correction_report_paths=[report_path],
    )
    approved_feedback = validation["knowledge_correction_feedback"]

    assert validation["ok"] is True
    assert validation["label_count"] == 2
    assert validation["approved_count"] == 1
    assert validation["review_count"] == 1
    assert validation["approved_dependency_correction_count"] == 1
    assert validation["approved_failure_action_memory_count"] == 0
    assert approved_feedback["dependency_correction_count"] == 1
    assert approved_feedback["failure_action_memory_count"] == 0
    assert approved_feedback["ready_log_count"] == 1
    assert approved_feedback["dependency_corrections"][0]["review_readiness"] == "approved"
    assert approved_feedback["dependency_corrections"][0]["review_notes"] == "manual check"
    policies = {hint["knowledge_correction_policy"] for hint in approved_feedback["policy_hints"]}
    assert "review_dependency_graph_corrections" in policies
    assert "keep_unreviewed_knowledge_corrections_gated" in policies

    invalid_path = os.path.join(tmpdir, "invalid_knowledge_correction_labels.jsonl")
    bad = dict(filled[0])
    bad["readiness"] = "maybe"
    with open(invalid_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(bad) + "\n")
    invalid = runner.validate_knowledge_correction_review_labels(
        label_path=invalid_path,
        knowledge_correction_report_paths=[report_path],
    )
    assert invalid["ok"] is False
    assert invalid["invalid_readiness_count"] == 1

    missing_path = os.path.join(tmpdir, "missing_knowledge_correction_labels.jsonl")
    missing = dict(filled[0])
    missing["key"] = "knowledge_correction::dependency_correction::missing"
    with open(missing_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(missing) + "\n")
    missing_validation = runner.validate_knowledge_correction_review_labels(
        label_path=missing_path,
        knowledge_correction_report_paths=[report_path],
    )
    assert missing_validation["ok"] is False
    assert missing_validation["missing_match_count"] == 1
    print("PASS: Knowledge correction review labels emit approved feedback")


def test_action_value_report_uses_embedded_action_observation_windows():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "action_value_embedded_observation_session.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Collect coal"}},
        {
            "type": "action",
            "data": {
                "action": {"type": "dig", "parameters": {"block": "coal_ore"}},
                "result": {"success": True},
                "pre_observation": {
                    "position": {"x": 0, "y": 64, "z": 0},
                    "health": 20,
                    "inventory": {},
                    "nearby_blocks": [{"name": "coal_ore"}],
                },
                "post_observation": {
                    "position": {"x": 0, "y": 64, "z": 0},
                    "health": 20,
                    "inventory": {"coal": 1},
                    "nearby_blocks": [{"name": "coal_ore"}],
                },
            },
        },
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config())
    report = runner.run_action_value_report_from_logs([session_path])
    feedback = runner.action_value_feedback(report)
    transition = feedback["state_transition_value_items"][0]

    assert report.state_transition_count == 1
    assert report.positive_transition_count == 1
    assert report.low_confidence_transition_count == 0
    assert report.action_local_transition_count == 1
    assert transition["signature"] == "dig:coal_ore"
    assert transition["avg_transition_confidence"] == 1.0
    assert transition["action_local_transitions"] == 1
    assert transition["inventory_gain_count"] == 1
    assert transition["examples"][0]["transition_confidence"] == 1.0
    assert transition["examples"][0]["transition_window"] == "action_local"
    assert transition["examples"][0]["before_state_summary"]["inventory"] == {}
    assert transition["examples"][0]["after_state_summary"]["inventory"]["coal"] == 1.0
    print("PASS: Action value report uses embedded action observation windows")


def test_action_value_report_flags_shared_transition_windows():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "action_value_shared_windows.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Gather oak logs"}},
        {"type": "observation", "data": {"position": {"x": 0, "y": 64, "z": 0}, "health": 20, "inventory": {}, "nearby_blocks": [{"name": "oak_log"}]}},
        {"type": "action", "data": {"action": {"type": "move_to", "parameters": {"x": 3, "z": 0}}, "result": {"success": True}}},
        {"type": "action", "data": {"action": {"type": "dig", "parameters": {"block": "oak_log"}}, "result": {"success": True}}},
        {"type": "observation", "data": {"position": {"x": 3, "y": 64, "z": 0}, "health": 20, "inventory": {"oak_log": 1}, "nearby_blocks": [{"name": "oak_log"}]}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config())
    report = runner.run_action_value_report_from_logs([session_path])
    feedback = runner.action_value_feedback(report)
    diagnostics = feedback["transition_window_diagnostics"]
    gate = runner.build_action_value_transition_gate(action_value_reports=[{"action_value_feedback": feedback}])

    assert report.action_count == 2
    assert report.state_transition_count == 2
    assert report.low_confidence_transition_count == 2
    assert report.shared_observation_transition_count == 2
    assert diagnostics["readiness"] == "review"
    assert diagnostics["shared_observation_transition_count"] == 2
    assert diagnostics["action_local_transition_count"] == 0
    assert "avoid_shared_transition_credit_assignment" in {
        hint["action_value_policy"] for hint in diagnostics["policy_hints"]
    }
    assert gate["readiness"] == "review"
    assert gate["transition_window_diagnostics"]["shared_observation_transition_count"] == 2
    assert gate["review_items"][0]["reason"] == "missing_action_local_transition_windows"
    print("PASS: Action value report flags shared transition windows")


def test_action_value_transition_gate_controls_runtime_feedback():
    runner = BenchmarkRunner(Config())
    trusted_payload = {
        "action_value_feedback": {
            "state_transition_count": 4,
            "low_confidence_transition_count": 0,
            "state_transition_value_items": [
                {
                    "signature": "dig:coal_ore",
                    "action_type": "dig",
                    "attempts": 4,
                    "avg_transition_value_score": 0.82,
                    "avg_transition_confidence": 1.0,
                    "low_confidence_transitions": 0,
                    "action_local_transitions": 4,
                }
            ],
        },
        "errors": [],
    }
    low_confidence_payload = {
        "action_value_feedback": {
            "state_transition_count": 4,
            "low_confidence_transition_count": 4,
            "state_transition_value_items": [
                {
                    "signature": "dig:coal_ore",
                    "action_type": "dig",
                    "attempts": 4,
                    "avg_transition_value_score": 0.2,
                    "avg_transition_confidence": 0.5,
                    "low_confidence_transitions": 4,
                    "action_local_transitions": 4,
                }
            ],
        },
        "errors": [],
    }

    approved = runner.build_action_value_transition_gate(action_value_reports=[trusted_payload])
    review = runner.build_action_value_transition_gate(action_value_reports=[low_confidence_payload])

    assert approved["readiness"] == "approved"
    assert approved["decision"] == "approve"
    assert approved["trusted_item_count"] == 1
    assert approved["trusted_transition_count"] == 4
    assert "load_trusted_transition_values" in approved["policy_hints"]
    assert review["readiness"] == "review"
    assert review["decision"] == "hold_for_review"
    assert review["trusted_item_count"] == 0
    assert review["low_confidence_rate"] == 1.0
    assert "collect_action_local_transition_windows" in review["policy_hints"]
    assert review["review_items"][0]["reason"] == "low_transition_confidence"
    print("PASS: Action value transition gate controls runtime feedback")


def test_action_value_transition_evaluator_compares_state_grounded_labels():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "transition_evaluator_session.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Collect coal"}},
        {
            "type": "action",
            "data": {
                "action": {"type": "dig", "parameters": {"block": "coal_ore"}},
                "result": {"success": True},
                "pre_observation": {
                    "position": {"x": 0, "y": 64, "z": 0},
                    "health": 20,
                    "inventory": {},
                    "nearby_blocks": [{"name": "coal_ore"}],
                },
                "post_observation": {
                    "position": {"x": 0, "y": 64, "z": 0},
                    "health": 20,
                    "inventory": {"coal": 1},
                    "nearby_blocks": [{"name": "coal_ore"}],
                },
            },
        },
        {
            "type": "action",
            "data": {
                "action": {"type": "wait", "parameters": {"ticks": 1}},
                "result": {"success": True},
                "pre_observation": {
                    "position": {"x": 0, "y": 64, "z": 0},
                    "health": 20,
                    "inventory": {"coal": 1},
                    "nearby_blocks": [{"name": "coal_ore"}],
                },
                "post_observation": {
                    "position": {"x": 0, "y": 64, "z": 0},
                    "health": 20,
                    "inventory": {"coal": 1},
                    "nearby_blocks": [{"name": "coal_ore"}],
                },
            },
        },
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config())
    action_report = runner.run_action_value_report_from_logs([session_path])
    payload = {
        "cases": [asdict(case) for case in action_report.cases],
        "action_value_feedback": runner.action_value_feedback(action_report),
        "errors": action_report.errors,
    }
    evaluator = StateGroundedTransitionEvaluatorLLM()
    report = runner.build_action_value_transition_evaluator_report(
        action_value_reports=[payload],
        evaluator=evaluator,
        limit=5,
        min_evaluated_transitions=2,
    )

    assert report["readiness"] == "approved"
    assert report["decision"] == "approve_comparison"
    assert report["evaluated_count"] == 2
    assert report["agreement_count"] == 2
    assert report["agreement_rate"] == 1.0
    assert report["conflict_count"] == 0
    assert "allow_llm_checked_transition_value_review" in report["policy_hints"]
    assert evaluator.response_formats[0] == {"type": "json_object"}
    assert "before_state" in evaluator.prompts[0]
    print("PASS: Action value transition evaluator compares state-grounded labels")


def test_self_evolution_gate_requires_verifier_and_counterexamples():
    runner = BenchmarkRunner(Config())
    self_evolution_report = {
        "ready_log_count": 1,
        "self_evolution_feedback": {
            "ready_log_count": 1,
            "failed_action_count": 2,
            "stagnation_signal_count": 1,
            "remedy_candidates": ["dig coal_ore: add scan/look_at before retry"],
            "adaptor_recommendations": ["Rewrite only the unfinished suffix."],
            "policy_hints": [
                {
                    "self_evolution_policy": "repair_stagnant_plan_suffix",
                    "priority": "high",
                }
            ],
        },
        "errors": [],
    }
    verifier_report = {
        "goal_count": 1,
        "errors": [],
        "cases": [
            {
                "goal": "Craft torches",
                "screenshot_vlm_readiness": "approved",
                "screenshot_vlm_status": "achieved",
            }
        ],
    }
    clear_counterexamples = {
        "counterexample_count": 0,
        "unresolved_counterexample_count": 0,
        "counterexamples": [],
        "errors": [],
    }

    review_report = runner.build_self_evolution_plan_repair_gate(
        self_evolution_reports=[self_evolution_report],
    )
    assert review_report["readiness"] == "review"
    assert review_report["decision"] == "keep_self_evolution_feedback_advisory"
    assert "verifier_report" in review_report["missing"]
    assert "counterexample_report" in review_report["missing"]

    approved_report = runner.build_self_evolution_plan_repair_gate(
        self_evolution_reports=[self_evolution_report],
        verifier_reports=[verifier_report],
        counterexample_reports=[clear_counterexamples],
    )
    assert approved_report["readiness"] == "approved"
    assert approved_report["decision"] == "allow_verified_plan_suffix_repair"
    assert approved_report["actionable_feedback_count"] == 1
    assert approved_report["verifier_success_count"] == 1
    assert approved_report["unresolved_counterexample_count"] == 0

    rejected_report = runner.build_self_evolution_plan_repair_gate(
        self_evolution_reports=[self_evolution_report],
        verifier_reports=[verifier_report],
        counterexample_reports=[{
            "counterexamples": [
                {"id": "ce-1", "status": "open", "detail": "retry still digs invisible target"}
            ],
            "errors": [],
        }],
    )
    assert rejected_report["readiness"] == "rejected"
    assert rejected_report["decision"] == "do_not_mutate_plan"
    assert rejected_report["unresolved_counterexample_count"] == 1
    print("PASS: Self-evolution gate requires verifier and counterexamples")


def test_self_evolution_counterexample_report_blocks_plan_repair_gate():
    runner = BenchmarkRunner(Config())
    self_evolution_report = {
        "ready_log_count": 1,
        "self_evolution_feedback": {
            "ready_log_count": 1,
            "stagnation_signal_count": 4,
            "remedy_candidates": ["retry with prerequisite fallback"],
            "adaptor_recommendations": ["rewrite unfinished suffix only"],
            "policy_hints": [
                {
                    "self_evolution_policy": "repair_stagnant_plan_suffix",
                    "priority": "high",
                    "count": 4,
                }
            ],
        },
        "cases": [
            {
                "source_log": "logs/session_stalled.jsonl",
                "goal": "Craft a crafting table",
                "failed_goal_count": 1,
                "blocked_plan_count": 3,
                "empty_plan_count": 3,
                "zero_action_failure_count": 1,
                "no_progress_success_count": 0,
                "repeated_success_loop_count": 0,
                "regression_signal_count": 1,
            }
        ],
    }
    terminal_report = {
        "cases": [
            {
                "source_log": "logs/session_stalled.jsonl",
                "goal": "Craft a crafting table",
                "outcome": "missed_execution",
                "world_complete": False,
                "world_status": "failed",
                "terminal_status": "not_reported_complete",
                "missing": ["need 1 crafting_table, have 0"],
            }
        ],
        "errors": [],
    }
    plan_action_report = {
        "cases": [
            {
                "source_log": "logs/session_stalled.jsonl",
                "blocked_plan_count": 3,
                "empty_plan_count": 3,
                "missing_planned_action_count": 0,
                "unplanned_action_count": 0,
                "order_violation_count": 0,
                "compliance_score": 0.0,
                "mismatch_examples": [],
            }
        ],
        "errors": [],
    }
    action_verification_report = {
        "cases": [
            {
                "source_log": "logs/session_stalled.jsonl",
                "verified_action_count": 1,
                "rejected_action_count": 0,
                "failed_without_reject_count": 0,
                "rejected_success_count": 0,
                "review_action_count": 1,
                "review_reasons": {"dig coordinates present but target block is unknown": 1},
            }
        ],
        "errors": [],
    }
    action_value_report = {
        "action_value_feedback": {
            "state_transition_count": 4,
            "no_progress_transition_count": 3,
            "low_confidence_transition_count": 4,
            "transition_window_diagnostics": {
                "state_transition_count": 4,
                "low_confidence_transition_count": 4,
                "shared_observation_transition_count": 4,
                "missing_transition_window_count": 0,
                "action_local_transition_rate": 0.0,
            },
        },
        "errors": [],
    }

    counterexamples = runner.build_self_evolution_counterexample_report(
        self_evolution_reports=[self_evolution_report],
        terminal_commitment_reports=[terminal_report],
        plan_action_reports=[plan_action_report],
        action_verification_reports=[action_verification_report],
        action_value_reports=[action_value_report],
    )
    categories = set(counterexamples["category_counts"])

    assert counterexamples["readiness"] == "rejected"
    assert counterexamples["unresolved_counterexample_count"] >= 5
    assert "missed_execution" in categories
    assert "blocked_plan_loop" in categories
    assert "transition_window_quality" in categories
    assert "resolve_self_evolution_counterexamples_before_plan_repair" in counterexamples["policy_hints"]

    gate = runner.build_self_evolution_plan_repair_gate(
        self_evolution_reports=[self_evolution_report],
        verifier_reports=[terminal_report],
        counterexample_reports=[counterexamples],
    )
    assert gate["readiness"] == "rejected"
    assert gate["decision"] == "do_not_mutate_plan"
    assert gate["verifier_failure_count"] == 1
    assert gate["unresolved_counterexample_count"] == counterexamples["unresolved_counterexample_count"]
    print("PASS: Self-evolution counterexample report blocks plan repair gate")


def test_discovery_application_report_tracks_hypothesis_to_application_loop():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_discovery_application.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Discover whether a lever powers redstone dust, then build a two-lamp circuit"}},
        {
            "type": "discovery_hypothesis",
            "data": {
                "knowledge_gap": "Need to know whether one lever powers adjacent dust.",
                "hypothesis": "If a lever powers redstone dust, both connected lamps should turn on.",
            },
        },
        {
            "type": "discovery_experiment",
            "data": {
                "experiment": "Place lever, redstone dust, and lamp in a short line.",
                "success": True,
                "observation": "The lamp turns on when the lever is used.",
            },
        },
        {
            "type": "action",
            "data": {
                "action": {"type": "place", "parameters": {"item": "redstone_dust", "x": 1, "y": 64, "z": 1}},
                "result": {"success": True, "backend": "mineflayer", "message": "redstone experiment trial succeeded"},
            },
        },
        {
            "type": "memory_write",
            "data": {
                "layer": "causal",
                "memory_type": "causal_rule",
                "content": "If a lever powers redstone dust, connected lamps receive power.",
                "source": "discovery_experiment",
            },
        },
        {
            "type": "discovery_consolidation",
            "data": {
                "rule": "Lever power propagates through adjacent redstone dust into lamps.",
            },
        },
        {
            "type": "discovery_application",
            "data": {
                "goal": "Build a two-lamp circuit using the discovered lever rule.",
                "success": True,
            },
        },
        {"type": "goal_end", "data": {"goal": "Build a two-lamp circuit", "result": {"completed": True}}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config(memory_dir=os.path.join(tmpdir, "memory")))
    report = runner.run_discovery_application_report_from_logs([session_path])
    case = report.cases[0]

    assert report.log_count == 1
    assert report.ready_log_count == 1
    assert report.hypothesis_count == 1
    assert report.experiment_count == 1
    assert report.experiment_action_count == 1
    assert report.causal_memory_write_count == 1
    assert report.application_count == 2
    assert report.successful_application_count == 2
    assert report.complete_loop_count >= 1
    assert case.phase_counts["knowledge_gap_identification"] == 1
    assert case.phase_counts["experimental_discovery"] == 2
    assert case.phase_counts["knowledge_consolidation"] >= 2
    assert case.phase_counts["knowledge_application"] == 2
    assert "Need to know whether one lever powers adjacent dust." in case.knowledge_gap_candidates
    assert any("connected lamps receive power" in rule for rule in case.causal_rule_candidates)
    feedback = runner.discovery_application_feedback(report)
    assert feedback["ready_for_skill_gate"] is True
    assert feedback["complete_loop_count"] >= 1
    assert not feedback["recommendations"]

    ordinary_path = os.path.join(tmpdir, "session_ordinary_goal.jsonl")
    ordinary_events = [
        {"type": "goal_start", "data": {"goal": "Gather 3 oak logs"}},
        {"type": "observation", "data": {"inventory": {"oak_log": 3}}},
        {"type": "goal_end", "data": {"goal": "Gather 3 oak logs", "result": {"completed": True}}},
    ]
    with open(ordinary_path, "w", encoding="utf-8") as f:
        for event in ordinary_events:
            f.write(json.dumps(event) + "\n")
    ordinary_report = runner.run_discovery_application_report_from_logs([ordinary_path])
    assert ordinary_report.ready_log_count == 0
    assert ordinary_report.complete_loop_count == 0
    assert runner.discovery_application_feedback(ordinary_report)["ready_for_skill_gate"] is False
    print("PASS: Discovery application report tracks hypothesis-to-application loop")


def test_discovery_skill_gate_controls_experiment_derived_skill_promotion():
    tmpdir = tempfile.mkdtemp()
    skill_library = SkillLibrary(storage_path=os.path.join(tmpdir, "skills"), persist=True)
    ready_feedback = {
        "ready_for_skill_gate": True,
        "complete_loop_count": 1,
        "successful_application_count": 1,
        "failed_application_count": 0,
        "causal_memory_write_count": 1,
        "failed_experiment_action_count": 0,
        "recommendations": [],
    }
    blocked_feedback = {
        "ready_for_skill_gate": False,
        "complete_loop_count": 0,
        "successful_application_count": 0,
        "failed_application_count": 0,
        "causal_memory_write_count": 0,
        "failed_experiment_action_count": 0,
        "recommendations": [
            "write_causal_rule_with_provenance_before_skill_promotion",
            "test_discovered_rule_on_held_out_application_goal",
        ],
    }
    verification_gate = {
        "decision": "allow",
        "status": "achieved",
        "reason": "deterministic_verification_achieved",
        "target_inventory": {},
        "inventory_delta": {},
        "evidence": ["goal verifier accepted application output"],
        "matched_rules": ["goal_verifier"],
    }
    ready_candidate = SkillCandidate(
        name="redstone_lamp_rule_ready",
        goal="Build a two-lamp redstone circuit",
        description="Experiment-derived redstone circuit skill",
        implementation=json.dumps([{"type": "place", "parameters": {"item": "redstone_dust"}}]),
        score=0.92,
        signals={
            "verification_gate": verification_gate,
            "discovery_feedback": ready_feedback,
            "discovery_skill_gate": build_discovery_skill_gate(feedback=ready_feedback, source="ready_report"),
        },
    )
    blocked_candidate = SkillCandidate(
        name="redstone_lamp_rule_blocked",
        goal="Build a two-lamp redstone circuit",
        description="Incomplete experiment-derived redstone circuit skill",
        implementation=json.dumps([{"type": "place", "parameters": {"item": "redstone_dust"}}]),
        score=0.92,
        signals={
            "verification_gate": verification_gate,
            "discovery_feedback": blocked_feedback,
            "discovery_skill_gate": build_discovery_skill_gate(feedback=blocked_feedback, source="blocked_report"),
        },
    )

    extractor = SkillExtractor(skill_library, auto_promote=False)
    ready_skill = extractor.approve_candidate(ready_candidate)
    blocked_skill = extractor.approve_candidate(blocked_candidate)

    assert ready_skill is None
    assert ready_candidate.review_status == "rejected"
    assert ready_candidate.signals["promotion_report"]["discovery_gate"]["readiness"] == "approved"
    assert "typed_bounded_skill_contract" in ready_candidate.signals["promotion_report"]["matched_rules"]
    assert blocked_skill is None
    assert blocked_candidate.review_status == "rejected"
    blocked_report = blocked_candidate.signals["promotion_report"]
    assert blocked_report["decision"] == "reject"
    assert blocked_report["discovery_gate"]["readiness"] == "review"
    assert blocked_report["reason"] == "discovery_skill_gate_requires_review"
    assert "write_causal_rule_with_provenance_before_skill_promotion" in blocked_report["warnings"]
    print("PASS: Discovery evidence cannot bypass bounded contract and live-source gates")


def test_task_stream_transfer_gate_controls_skill_promotion_path():
    tmpdir = tempfile.mkdtemp()
    skill_library = SkillLibrary(storage_path=os.path.join(tmpdir, "skills"), persist=True)
    verification_gate = {
        "decision": "allow",
        "status": "achieved",
        "reason": "deterministic_verification_achieved",
        "target_inventory": {},
        "inventory_delta": {},
        "evidence": ["goal verifier accepted pickaxe crafting"],
        "matched_rules": ["goal_verifier"],
    }
    approved_transfer_gate = {
        "required": True,
        "readiness": "approved",
        "decision": "allow_candidate_promotion",
        "reason": "controlled task streams show positive transfer",
        "stream_count": 1,
        "ready_stream_count": 1,
        "task_count": 3,
        "interference_count": 0,
        "evidence_count": 1,
        "evidence": ["wood_to_pickaxe: transfer gate approved"],
        "missing": [],
        "warnings": [],
        "errors": [],
        "average_plasticity_gain": 0.42,
        "average_stability_gain": 0.03,
        "average_generalization_gain": 0.37,
    }
    review_transfer_gate = {
        **approved_transfer_gate,
        "readiness": "review",
        "decision": "keep_candidate_review_only",
        "reason": "held-out transfer evidence is missing",
        "evidence_count": 0,
        "warning_count": 1,
        "evidence": [],
        "missing": ["wood_to_pickaxe: transfer gate review"],
        "warnings": ["held-out generalization gain evidence is missing"],
        "average_generalization_gain": None,
    }
    ready_candidate = SkillCandidate(
        name="craft_stone_pickaxe_transfer_ready",
        goal="Craft a stone pickaxe",
        description="Transfer-tested stone pickaxe skill",
        implementation=json.dumps([{"type": "craft", "parameters": {"item": "stone_pickaxe"}}]),
        score=0.91,
        signals={
            "verification_gate": verification_gate,
            "task_stream_transfer_gate": approved_transfer_gate,
        },
    )
    blocked_candidate = SkillCandidate(
        name="craft_stone_pickaxe_transfer_blocked",
        goal="Craft a stone pickaxe",
        description="Transfer-untested stone pickaxe skill",
        implementation=json.dumps([{"type": "craft", "parameters": {"item": "stone_pickaxe"}}]),
        score=0.91,
        signals={
            "verification_gate": verification_gate,
            "task_stream_transfer_gate": review_transfer_gate,
        },
    )

    extractor = SkillExtractor(skill_library, auto_promote=False)
    ready_skill = extractor.approve_candidate(ready_candidate)
    blocked_skill = extractor.approve_candidate(blocked_candidate)

    assert ready_skill is None
    assert ready_candidate.review_status == "rejected"
    ready_report = ready_candidate.signals["promotion_report"]
    assert ready_report["transfer_gate"]["readiness"] == "approved"
    assert "typed_bounded_skill_contract" in ready_report["matched_rules"]
    assert not skill_library.skill_versions(ready_candidate.skill_id)

    assert blocked_skill is None
    assert blocked_candidate.review_status == "rejected"
    blocked_report = blocked_candidate.signals["promotion_report"]
    assert blocked_report["decision"] == "reject"
    assert blocked_report["transfer_gate"]["readiness"] == "review"
    assert blocked_report["reason"] == "task_stream_transfer_gate_requires_review"
    assert "held-out generalization gain evidence is missing" in blocked_report["warnings"]
    print("PASS: Transfer evidence cannot bypass bounded contract and source provenance")


def test_action_abstraction_report_counts_backend_mapping_and_low_level_candidates():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_action_abstraction.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Mine visible coal and place torch"}},
        {
            "type": "action",
            "data": {
                "action": {"type": "move_to", "parameters": {"x": 3, "z": 4}},
                "result": {"success": True, "backend": "mineflayer", "backend_command": "move_to"},
            },
        },
        {
            "type": "action",
            "data": {
                "action": {"type": "dig", "parameters": {"block": "coal_ore"}},
                "result": {"success": False, "error": "no target visible"},
            },
        },
        {
            "type": "action",
            "data": {
                "action": {"type": "place", "parameters": {"x": 3, "y": 64, "z": 4, "item": "torch"}},
                "result": {"success": True},
            },
        },
        {
            "type": "action",
            "data": {
                "action": {"type": "teleport", "parameters": {"x": 100, "z": 100}},
                "result": {"success": False, "error": "unknown canonical action"},
            },
        },
        {"type": "goal_end", "data": {"goal": "Mine visible coal and place torch", "result": {"completed": False}}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config(memory_dir=os.path.join(tmpdir, "memory")))
    report = runner.run_action_abstraction_report_from_logs([session_path])
    case = report.cases[0]

    assert report.log_count == 1
    assert report.action_count == 4
    assert report.failed_action_count == 2
    assert report.unknown_canonical_count == 1
    assert report.failed_mapping_count == 1
    assert report.low_level_candidate_count == 2
    assert case.canonical_action_types["dig"] == 1
    assert case.canonical_action_types["teleport"] == 1
    assert case.mineflayer_command_counts["teleport"] == 1
    assert case.desktop_command_counts["mouse_hold_attack"] == 1
    assert case.desktop_command_counts["mouse_place_block"] == 1
    assert case.lower_level_reasons["missing_precise_target"] == 1
    assert case.lower_level_reasons["visual_precision_action"] == 1
    assert any("lower-level control" in recommendation for recommendation in case.task_recommendations)

    feedback = runner.action_abstraction_feedback(report)
    assert feedback["lower_level_action_types"]["dig"] == 1
    assert feedback["lower_level_action_types"]["place"] == 1
    assert feedback["unknown_action_types"]["teleport"] == 1
    hints = {hint["action_type"]: hint for hint in feedback["policy_hints"]}
    assert hints["dig"]["preferred_control"] == "consider_low_level_visual_control"
    assert hints["place"]["preferred_control"] == "consider_low_level_visual_control"
    assert hints["move_to"]["preferred_control"] == "mineflayer_api_ok"
    assert hints["teleport"]["preferred_control"] == "define_canonical_mapping"

    class RecordingPolicy:
        def __init__(self):
            self.feedback = None

        def record_action_abstraction_feedback(self, recorded_feedback):
            self.feedback = recorded_feedback

    policy = RecordingPolicy()
    applied = runner.apply_action_abstraction_feedback(report, policy)
    assert applied == feedback
    assert policy.feedback == feedback
    print("PASS: Action abstraction report counts backend mapping and low-level candidates")


def test_memory_policy_report_counts_write_read_manage_gaps_and_feedback():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_memory_policy.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Craft torches"}},
        {
            "type": "memory_read",
            "data": {
                "query": "craft torches",
                "read_filter_report": {
                    "filtered_entries": 2,
                    "filter_reasons": {"superseded": 1, "conditional_mismatch": 1},
                },
            },
        },
        {"type": "observation", "data": {"inventory": {"stick": 1}, "nearby_blocks": [{"name": "coal_ore"}]}},
        {"type": "plan", "data": {"status": "in_progress", "actions": [{"type": "craft", "parameters": {"item": "torch"}}]}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "torch"}}, "result": {"success": False, "error": "Missing coal"}}},
        {"type": "reflection", "data": {"lesson": "Need coal before crafting torches"}},
        {"type": "failure_correction_completed", "data": {"skill": "collect_coal_before_torch", "success": True}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "torch"}}, "result": {"success": True, "item": "torch"}}},
        {"type": "goal_verification", "data": {"achieved": True, "context": {"accepted": True}}},
        {
            "type": "memory_write",
            "data": {
                "layer": "semantic",
                "memory_type": "fact",
                "content": "Torch crafting verified after collecting coal.",
                "confidence": 0.95,
            },
        },
        {
            "type": "memory_write",
            "data": {
                "layer": "context",
                "memory_type": "raw_observation",
                "content": "raw observation " * 80,
                "source": "observation",
                "confidence": 0.3,
            },
        },
        {"type": "goal_end", "data": {"goal": "Craft torches", "result": {"completed": True}}},
        {"type": "memory_consolidation", "data": {"operation": "consolidate", "count": 1}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config(memory_dir=os.path.join(tmpdir, "memory")))
    report = runner.run_memory_policy_report_from_logs([session_path])
    case = report.cases[0]

    assert report.log_count == 1
    assert report.ready_log_count == 1
    assert case.explicit_memory_write_count == 2
    assert case.explicit_memory_read_count == 1
    assert case.explicit_memory_manage_count == 1
    assert case.semantic_write_candidate_count == 2
    assert case.missed_semantic_write_count == 1
    assert case.failure_learning_candidate_count == 3
    assert case.noisy_write_candidate_count == 1
    assert case.missing_read_trace_count == 0
    assert case.read_filter_event_count == 1
    assert case.read_filtered_entry_count == 2
    assert case.read_filter_reasons["superseded"] == 1
    assert report.read_filter_event_count == 1
    assert report.read_filtered_entry_count == 2
    assert case.write_operations["memory_write:semantic:fact"] == 1
    assert case.write_operations["memory_write:context:raw_observation"] == 1
    assert "craft torches" in case.read_queries

    feedback = runner.memory_policy_feedback(report)
    policies = {hint["memory_policy"]: hint for hint in feedback["policy_hints"]}
    assert "instrument_memory_retrieval" not in policies
    assert policies["promote_verified_outcomes"]["priority"] == "high"
    assert policies["record_failure_corrections"]["count"] == 3
    assert policies["tighten_memory_write_gate"]["count"] == 1
    assert policies["queue_consolidation_review"]["count"] == 2
    assert policies["review_filtered_memory_reads"]["count"] == 2
    assert feedback["read_filter_reasons"]["conditional_mismatch"] == 1

    class RecordingMemoryPolicy:
        def __init__(self):
            self.feedback = None

        def record_memory_policy_feedback(self, recorded_feedback):
            self.feedback = recorded_feedback

    policy = RecordingMemoryPolicy()
    applied = runner.apply_memory_policy_feedback(report, policy)
    assert applied == feedback
    assert policy.feedback == feedback

    lifecycle_policy = MemoryLifecyclePolicy()
    runner.apply_memory_policy_feedback(report, lifecycle_policy)
    profile = lifecycle_policy.feedback_profile()
    assert profile["promote_verified_outcomes"]["priority"] == "high"
    assert profile["tighten_memory_write_gate"]["count"] == 1
    promoted = lifecycle_policy.decide_write(
        "episodic",
        "goal_end",
        "write_episode",
        {"goal": "Craft torches", "success": True},
        source="test",
    )
    noisy = lifecycle_policy.decide_write(
        "context",
        "raw_observation",
        "write_context",
        {"raw": "x" * 600},
        source="observation",
        confidence=0.3,
    )
    failure = lifecycle_policy.decide_write(
        "episodic",
        "failure_correction_completed",
        "write_episode",
        {"skill": "collect_coal_before_torch"},
        source="test",
    )
    assert promoted.decision == "semantic_promotion_candidate"
    assert "missed semantic writes" in promoted.reason
    assert noisy.decision == "write_review_needed"
    assert noisy.priority == "medium"
    assert "tighten_memory_write_gate" in noisy.feedback_hints
    assert failure.decision == "failure_learning_candidate"
    assert "record_failure_corrections" in failure.feedback_hints
    print("PASS: Memory policy report counts write/read/manage gaps and feedback")


def test_memory_attribution_report_labels_retrieval_outcomes_without_raw_queries():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_memory_attribution.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Craft torches"}},
        {
            "type": "memory_read",
            "data": {
                "layer": "semantic",
                "memory_type": "relevant_memory",
                "source": "planner_memory",
                "query": "craft torch route",
                "memory_id": "memory-supported-1",
                "result_chars": 200,
                "has_result": True,
                "retrieval_trace": {
                    "weighted_retrieval_enabled": True,
                    "weighted_memory_match_count": 1,
                    "weighted_transfer_match_count": 0,
                    "top_memory_ids": ["memory-supported-1", "memory-supported-extra"],
                    "top_weighted_memory_ids": ["memory-supported-1"],
                    "attribution_policy_counts": {"boost_supported_memory": 1},
                },
            },
        },
        {
            "type": "memory_read",
            "data": {
                "layer": "task",
                "memory_type": "task_memory",
                "source": "planner_task_memory",
                "query": "torch task setup",
                "memory_id": "memory-supported-2",
                "result_chars": 80,
                "has_result": True,
            },
        },
        {"type": "plan", "data": {"status": "in_progress", "actions": [{"type": "craft", "parameters": {"item": "torch"}}]}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "torch"}}, "result": {"success": True}}},
        {"type": "goal_verification", "data": {"achieved": True, "context": {"accepted": True}}},
        {
            "type": "memory_read",
            "data": {
                "layer": "semantic",
                "memory_type": "relevant_memory",
                "source": "planner_memory",
                "query": "mine coal route",
                "memory_id": "memory-conflict-1",
                "result_chars": 180,
                "has_result": True,
            },
        },
        {"type": "plan", "data": {"status": "in_progress", "actions": [{"type": "dig", "parameters": {"block": "coal_ore"}}]}},
        {"type": "action", "data": {"action": {"type": "dig", "parameters": {"block": "coal_ore"}}, "result": {"success": False, "error": "wooden pickaxe"}}},
        {"type": "goal_verification", "data": {"achieved": False, "context": {"accepted": False}}},
        {
            "type": "memory_read",
            "data": {
                "layer": "semantic",
                "memory_type": "relevant_memory",
                "source": "planner_memory",
                "query": "empty recall",
                "result_chars": 0,
                "has_result": False,
            },
        },
        {"type": "plan", "data": {"status": "in_progress", "actions": []}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config(memory_dir=os.path.join(tmpdir, "memory")))
    report = runner.run_memory_attribution_report_from_logs([session_path])
    case = report["cases"][0]
    items = case["items"]

    assert report["log_count"] == 1
    assert report["ready_log_count"] == 1
    assert report["planning_cycle_count"] == 3
    assert report["memory_read_count"] == 4
    assert report["attributed_read_count"] == 3
    assert report["supported_read_count"] == 2
    assert report["conflicting_read_count"] == 1
    assert report["no_result_read_count"] == 1
    assert report["memory_id_traced_read_count"] == 3
    assert report["weighted_retrieval_read_count"] == 1
    assert report["weighted_memory_match_count"] == 1
    assert report["attribution_policy_counts"]["boost_supported_memory"] == 1
    assert report["quality_label_counts"]["supported"] == 2
    assert report["read_type_counts"]["relevant_memory"] == 3
    assert report["read_layer_counts"]["semantic"] == 3
    assert {item["quality_label"] for item in items} == {"supported", "conflicting", "no_result"}
    assert items[0]["query_signature"]
    assert "query" not in items[0]
    assert items[0]["memory_ids"] == ["memory-supported-1", "memory-supported-extra"]
    assert items[0]["weighted_memory_ids"] == ["memory-supported-1"]
    assert "craft torch route" not in json.dumps(items)
    assert "mine coal route" not in json.dumps(items)

    policies = {hint["memory_attribution_policy"]: hint for hint in report["policy_hints"]}
    assert policies["promote_outcome_supported_retrieval"]["count"] == 2
    assert policies["demote_conflicting_retrieval"]["count"] == 1
    assert policies["include_retrieval_result_metadata"]["count"] == 1
    assert "use_supported_memory_reads_as_candidates_for_weighted_retrieval_boost" in report["recommendations"]
    assert "route_conflicting_memory_reads_to_review_before_reuse" in report["recommendations"]
    print("PASS: Memory attribution report labels retrieval outcomes without raw queries")


def test_memory_attribution_gate_controls_weighted_retrieval_profile():
    tmpdir = tempfile.mkdtemp()
    ready_path = os.path.join(tmpdir, "session_memory_attribution_ready.jsonl")
    blocked_path = os.path.join(tmpdir, "session_memory_attribution_blocked.jsonl")
    ready_events = [
        {"type": "goal_start", "data": {"goal": "Craft torches"}},
        {
            "type": "memory_read",
            "data": {
                "layer": "semantic",
                "memory_type": "relevant_memory",
                "source": "planner_memory",
                "query": "craft torch route",
                "result_chars": 200,
                "has_result": True,
                "retrieval_trace": {
                    "top_memory_ids": ["torch_semantic_supported"],
                    "weighted_retrieval_enabled": False,
                    "weighted_memory_match_count": 0,
                    "weighted_transfer_match_count": 0,
                },
            },
        },
        {
            "type": "memory_read",
            "data": {
                "layer": "task",
                "memory_type": "task_memory",
                "source": "planner_task_memory",
                "query": "torch task setup",
                "memory_id": "torch_task_supported",
                "result_chars": 80,
                "has_result": True,
            },
        },
        {"type": "plan", "data": {"status": "in_progress", "actions": [{"type": "craft", "parameters": {"item": "torch"}}]}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "torch"}}, "result": {"success": True}}},
    ]
    blocked_events = [
        {"type": "goal_start", "data": {"goal": "Mine coal"}},
        {
            "type": "memory_read",
            "data": {
                "layer": "semantic",
                "memory_type": "relevant_memory",
                "source": "planner_memory",
                "query": "mine coal route",
                "result_chars": 160,
                "has_result": True,
            },
        },
        {"type": "plan", "data": {"status": "in_progress", "actions": [{"type": "dig", "parameters": {"block": "coal_ore"}}]}},
        {"type": "action", "data": {"action": {"type": "dig", "parameters": {"block": "coal_ore"}}, "result": {"success": False, "error": "need stone pickaxe"}}},
    ]
    for path, events in ((ready_path, ready_events), (blocked_path, blocked_events)):
        with open(path, "w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config(memory_dir=os.path.join(tmpdir, "memory")))
    ready_report = runner.run_memory_attribution_report_from_logs([ready_path])
    ready_report_path = os.path.join(tmpdir, "memory_attribution_ready.json")
    with open(ready_report_path, "w", encoding="utf-8") as f:
        json.dump(ready_report, f)
    ready_gate = runner.build_memory_attribution_gate(
        memory_attribution_report_paths=[ready_report_path],
    )

    blocked_report = runner.run_memory_attribution_report_from_logs([blocked_path])
    blocked_gate = runner.build_memory_attribution_gate(
        memory_attribution_reports=[blocked_report],
    )

    assert ready_gate["readiness"] == "approved"
    assert ready_gate["decision"] == "allow_weighted_memory_retrieval_profile"
    assert ready_gate["memory_attribution_report_count"] == 1
    assert ready_gate["supported_read_count"] == 2
    assert ready_gate["conflicting_read_count"] == 0
    assert ready_gate["attributed_read_rate"] == 1.0
    assert ready_gate["failure_count"] == 0
    assert ready_gate["retrieval_weight_hint_count"] == 2
    assert {hint["memory_id"] for hint in ready_gate["retrieval_weight_hints"]} == {
        "torch_semantic_supported",
        "torch_task_supported",
    }
    assert all(hint["policy"] == "boost_supported_memory" for hint in ready_gate["retrieval_weight_hints"])
    assert "promote_supported_memory_reads_only_after_gate" in ready_gate["policy_hints"]

    assert blocked_gate["readiness"] == "rejected"
    assert blocked_gate["decision"] == "do_not_enable_weighted_memory_retrieval"
    assert blocked_gate["conflicting_read_count"] == 1
    assert blocked_gate["conflicting_read_rate"] == 1.0
    assert blocked_gate["failure_count"] == 1
    assert "route_conflicting_memory_reads_to_review_before_weight_update" in blocked_gate["policy_hints"]
    print("PASS: Memory attribution gate controls weighted retrieval profile")


def test_memory_lifecycle_policy_uses_task_stream_transfer_gate():
    approved_gate = {
        "required": True,
        "readiness": "approved",
        "decision": "allow_candidate_promotion",
        "reason": "positive transfer without regressions",
    }
    rejected_gate = {
        "required": True,
        "readiness": "rejected",
        "decision": "do_not_promote_candidate",
        "reason": "held-out regression detected",
    }
    review_gate = {
        "required": True,
        "readiness": "review",
        "decision": "keep_candidate_review_only",
        "reason": "missing held-out stream",
    }

    approved_policy = MemoryLifecyclePolicy(transfer_gate=approved_gate)
    promoted = approved_policy.decide_write(
        "episodic",
        "goal_end",
        "write_episode",
        {"goal": "Craft torches", "success": True},
        source="test",
    )
    assert promoted.decision == "semantic_promotion_candidate"
    assert promoted.should_review is False
    assert "approved transfer evidence" in promoted.reason
    assert "task_stream_transfer_gate_approved" in promoted.feedback_hints

    rejected_policy = MemoryLifecyclePolicy(transfer_gate=rejected_gate)
    blocked = rejected_policy.decide_write(
        "semantic",
        "fact",
        "write_fact",
        {"content": "oak-to-planks transfers to crafting table"},
        source="test",
    )
    assert blocked.decision == "transfer_promotion_blocked"
    assert blocked.should_persist is False
    assert blocked.should_review is True
    assert "held-out regression detected" in blocked.reason

    review_policy = MemoryLifecyclePolicy(transfer_gate=review_gate)
    review = review_policy.decide_write(
        "episodic",
        "experience",
        "write_episode",
        {"content": "stone pickaxe workflow may transfer"},
        source="test",
    )
    assert review.decision == "transfer_promotion_review_needed"
    assert review.should_persist is True
    assert review.should_review is True
    assert "task_stream_transfer_gate_review" in review.feedback_hints
    print("PASS: Memory lifecycle policy uses task stream transfer gate")


def test_bounded_context_report_audits_typed_planner_context():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_bounded_context.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Craft torches"}},
        {
            "type": "memory_read",
            "data": {
                "layer": "mixed",
                "memory_type": "relevant_memory",
                "source": "planner_goal",
                "query": "Craft torches",
                "result_chars": 180,
                "has_result": True,
            },
        },
        {
            "type": "memory_read",
            "data": {
                "layer": "task",
                "memory_type": "task_memory",
                "source": "planner_task_memory",
                "query": "Craft torches",
                "result_chars": 120,
                "has_result": True,
            },
        },
        {
            "type": "memory_read",
            "data": {
                "layer": "task",
                "memory_type": "task_continuity",
                "source": "planner_task_continuity",
                "query": "Craft torches",
                "result_chars": 260,
                "has_result": True,
                "context_profile": "goal_frontier_capsule_v1",
                "context_budget_chars": 600,
                "context_within_budget": True,
                "context_trace": {
                    "schema_version": 1,
                    "profile": "goal_frontier_capsule_v1",
                    "char_budget": 600,
                    "result_chars": 260,
                    "full_context_chars": 260,
                    "truncated": False,
                    "required_lines_complete": True,
                    "frontier_available": True,
                    "frontier_injected": True,
                    "next_actions_available": True,
                    "next_actions_injected": True,
                    "active_branch_count": 1,
                    "mode": "active",
                    "path_checkpoint_count": 2,
                    "nonselected_branch_count": 1,
                },
            },
        },
        {
            "type": "memory_read",
            "data": {
                "layer": "context",
                "memory_type": "context_window",
                "source": "planner_context",
                "query": "context_window",
                "result_chars": 80,
                "has_result": True,
            },
        },
        {"type": "plan", "data": {"status": "in_progress", "actions": [{"type": "craft", "parameters": {"item": "torch"}}]}},
        {
            "type": "memory_read",
            "data": {
                "layer": "context",
                "memory_type": "raw_transcript",
                "source": "full_history",
                "query": "message_history",
                "result_chars": 2000,
                "has_result": True,
            },
        },
        {"type": "plan", "data": {"status": "in_progress", "actions": [{"type": "dig", "parameters": {"block": "coal_ore"}}]}},
        {"type": "plan", "data": {"status": "blocked", "actions": []}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config(memory_dir=os.path.join(tmpdir, "memory")))
    report = runner.run_bounded_context_report_from_logs(
        [session_path],
        max_read_chars=1000,
        max_cycle_chars=1500,
    )
    case = report.cases[0]

    assert report.log_count == 1
    assert report.ready_log_count == 1
    assert report.planning_cycle_count == 3
    assert report.bounded_cycle_count == 1
    assert report.unbounded_cycle_count == 2
    assert report.missing_read_cycle_count == 1
    assert report.oversized_read_cycle_count == 1
    assert report.oversized_cycle_count == 1
    assert report.raw_context_cycle_count == 1
    assert report.task_continuity_capsule_read_count == 1
    assert report.capsule_trace_missing_count == 0
    assert report.capsule_required_line_failure_count == 0
    assert report.capsule_frontier_omission_count == 0
    assert report.capsule_next_action_omission_count == 0
    assert case.cycles[0].bounded_ok is True
    assert case.cycles[0].has_relevant_memory is True
    assert case.cycles[0].has_task_memory is True
    assert "raw_context_risk" in case.cycles[1].issues
    assert "missing_memory_read_trace" in case.cycles[2].issues
    assert report.read_types["relevant_memory"] == 1
    assert report.read_types["raw_transcript"] == 1

    feedback = runner.bounded_context_feedback(report)
    policies = {hint["bounded_context_policy"]: hint for hint in feedback["policy_hints"]}
    assert policies["instrument_planning_context_reads"]["priority"] == "high"
    assert policies["tighten_planner_context_budget"]["count"] == 2
    assert policies["replace_raw_transcript_with_typed_retrieval"]["count"] == 1
    assert "increase_typed_retrieval_diversity" in policies
    print("PASS: Bounded context report audits typed planner context")


def test_bounded_context_report_rejects_incomplete_task_capsule():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_incomplete_capsule.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Craft torches"}},
        {
            "type": "memory_read",
            "data": {
                "layer": "mixed",
                "memory_type": "relevant_memory",
                "source": "planner_goal",
                "result_chars": 100,
            },
        },
        {
            "type": "memory_read",
            "data": {
                "layer": "task",
                "memory_type": "task_continuity",
                "source": "planner_task_continuity",
                "result_chars": 121,
                "context_profile": "goal_frontier_capsule_v1",
                "context_budget_chars": 120,
                "context_within_budget": True,
                "context_trace": {
                    "profile": "goal_frontier_capsule_v1",
                    "truncated": True,
                    "required_lines_complete": False,
                    "frontier_available": True,
                    "frontier_injected": False,
                    "next_actions_available": True,
                    "next_actions_injected": False,
                },
            },
        },
        {"type": "plan", "data": {"status": "in_progress", "actions": [{"type": "craft"}]}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config(memory_dir=os.path.join(tmpdir, "memory")))
    report = runner.run_bounded_context_report_from_logs([session_path])
    cycle = report.cases[0].cycles[0]
    feedback = runner.bounded_context_feedback(report)
    policies = {hint["bounded_context_policy"] for hint in feedback["policy_hints"]}

    assert cycle.bounded_ok is False
    assert report.task_continuity_capsule_read_count == 1
    assert report.capsule_truncated_count == 1
    assert report.capsule_trace_missing_count == 1
    assert report.capsule_budget_violation_count == 1
    assert report.capsule_required_line_failure_count == 1
    assert report.capsule_frontier_omission_count == 1
    assert report.capsule_next_action_omission_count == 1
    assert "task_capsule_trace_missing" in cycle.issues
    assert "task_capsule_budget_violation" in cycle.issues
    assert "task_capsule_required_fields_missing" in cycle.issues
    assert "task_capsule_frontier_missing" in cycle.issues
    assert "task_capsule_next_actions_missing" in cycle.issues
    assert "preserve_task_capsule_contract" in policies
    print("PASS: Bounded context report rejects incomplete task capsule")


def test_bounded_context_report_allows_empty_task_capsule():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_empty_capsule.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Explore spawn"}},
        {
            "type": "memory_read",
            "data": {
                "layer": "mixed",
                "memory_type": "relevant_memory",
                "source": "planner_goal",
                "result_chars": 80,
            },
        },
        {
            "type": "memory_read",
            "data": {
                "layer": "task",
                "memory_type": "task_continuity",
                "source": "planner_task_continuity",
                "result_chars": 0,
                "context_profile": "goal_frontier_capsule_v1",
                "context_budget_chars": 600,
                "context_within_budget": True,
                "context_trace": {
                    "schema_version": 1,
                    "profile": "goal_frontier_capsule_v1",
                    "char_budget": 600,
                    "result_chars": 0,
                    "full_context_chars": 0,
                    "truncated": False,
                    "required_lines_complete": False,
                    "frontier_available": False,
                    "frontier_injected": False,
                    "next_actions_available": False,
                    "next_actions_injected": False,
                    "active_branch_count": 0,
                    "mode": "empty",
                    "path_checkpoint_count": 0,
                    "nonselected_branch_count": 0,
                },
            },
        },
        {"type": "plan", "data": {"status": "in_progress", "actions": [{"type": "move"}]}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config(memory_dir=os.path.join(tmpdir, "memory")))
    report = runner.run_bounded_context_report_from_logs([session_path])
    cycle = report.cases[0].cycles[0]

    assert cycle.bounded_ok is True
    assert report.task_continuity_capsule_read_count == 1
    assert report.capsule_trace_missing_count == 0
    assert report.capsule_budget_violation_count == 0
    assert report.capsule_required_line_failure_count == 0
    print("PASS: Bounded context report allows empty task capsule")


def test_bounded_context_gate_controls_planner_contract():
    tmpdir = tempfile.mkdtemp()
    ready_path = os.path.join(tmpdir, "session_bounded_ready.jsonl")
    blocked_path = os.path.join(tmpdir, "session_bounded_blocked.jsonl")
    ready_events = [
        {"type": "goal_start", "data": {"goal": "Craft torches"}},
        {
            "type": "memory_read",
            "data": {
                "layer": "semantic",
                "memory_type": "relevant_memory",
                "source": "planner_memory",
                "query": "craft torches",
                "result_chars": 180,
            },
        },
        {
            "type": "memory_read",
            "data": {
                "layer": "task",
                "memory_type": "task_memory",
                "source": "planner_task_memory",
                "query": "craft torches",
                "result_chars": 90,
            },
        },
        {"type": "plan", "data": {"status": "in_progress", "actions": [{"type": "craft", "parameters": {"item": "torch"}}]}},
    ]
    blocked_events = [
        {"type": "goal_start", "data": {"goal": "Mine coal"}},
        {
            "type": "memory_read",
            "data": {
                "layer": "raw",
                "memory_type": "raw_transcript",
                "source": "full_history",
                "query": "message_history",
                "result_chars": 2200,
            },
        },
        {"type": "plan", "data": {"status": "in_progress", "actions": [{"type": "dig", "parameters": {"block": "coal_ore"}}]}},
        {"type": "plan", "data": {"status": "blocked", "actions": []}},
    ]
    for path, events in ((ready_path, ready_events), (blocked_path, blocked_events)):
        with open(path, "w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config(memory_dir=os.path.join(tmpdir, "memory")))
    ready_report = runner.run_bounded_context_report_from_logs([ready_path], max_read_chars=1000, max_cycle_chars=1500)
    ready_payload = {
        "log_count": ready_report.log_count,
        "ready_log_count": ready_report.ready_log_count,
        "planning_cycle_count": ready_report.planning_cycle_count,
        "bounded_cycle_count": ready_report.bounded_cycle_count,
        "unbounded_cycle_count": ready_report.unbounded_cycle_count,
        "missing_read_cycle_count": ready_report.missing_read_cycle_count,
        "oversized_read_cycle_count": ready_report.oversized_read_cycle_count,
        "oversized_cycle_count": ready_report.oversized_cycle_count,
        "raw_context_cycle_count": ready_report.raw_context_cycle_count,
        "low_diversity_cycle_count": ready_report.low_diversity_cycle_count,
        "bounded_context_feedback": runner.bounded_context_feedback(ready_report),
        "errors": ready_report.errors,
        "cases": [asdict(case) for case in ready_report.cases],
    }
    ready_gate = runner.build_bounded_context_gate(bounded_context_reports=[ready_payload])

    blocked_report = runner.run_bounded_context_report_from_logs([blocked_path], max_read_chars=1000, max_cycle_chars=1500)
    blocked_payload = {
        "log_count": blocked_report.log_count,
        "ready_log_count": blocked_report.ready_log_count,
        "planning_cycle_count": blocked_report.planning_cycle_count,
        "bounded_cycle_count": blocked_report.bounded_cycle_count,
        "unbounded_cycle_count": blocked_report.unbounded_cycle_count,
        "missing_read_cycle_count": blocked_report.missing_read_cycle_count,
        "oversized_read_cycle_count": blocked_report.oversized_read_cycle_count,
        "oversized_cycle_count": blocked_report.oversized_cycle_count,
        "raw_context_cycle_count": blocked_report.raw_context_cycle_count,
        "low_diversity_cycle_count": blocked_report.low_diversity_cycle_count,
        "bounded_context_feedback": runner.bounded_context_feedback(blocked_report),
        "errors": blocked_report.errors,
        "cases": [asdict(case) for case in blocked_report.cases],
    }
    blocked_gate = runner.build_bounded_context_gate(bounded_context_reports=[blocked_payload])

    assert ready_gate["readiness"] == "approved"
    assert ready_gate["decision"] == "allow_bounded_context_profile"
    assert ready_gate["bounded_cycle_rate"] == 1.0
    assert ready_gate["failure_count"] == 0
    assert blocked_gate["readiness"] == "rejected"
    assert blocked_gate["decision"] == "do_not_use_bounded_context_profile"
    assert blocked_gate["unbounded_cycle_count"] == 2
    assert "replace_raw_transcript_with_typed_retrieval" in blocked_gate["policy_hints"]
    print("PASS: Bounded context gate controls planner contract")


def test_task_continuity_lineage_ablation_isolates_failed_branches():
    runner = BenchmarkRunner(Config())
    report = runner.run_task_continuity_lineage_ablation()
    payload = runner.task_continuity_lineage_ablation_payload(report)
    by_id = {case.case_id: case for case in report.cases}

    assert payload["type"] == "task_continuity_lineage_ablation"
    assert payload["schema_version"] == 3
    assert payload["case_count"] == 3
    assert payload["ready_case_count"] == 2
    assert payload["non_builtin_ready_case_count"] == 0
    assert payload["helped_count"] == 2
    assert payload["regression_count"] == 0
    assert payload["baseline_failed_contamination_count"] == 2
    assert payload["candidate_failed_contamination_count"] == 0
    assert payload["average_precision_gain"] > 0
    assert payload["average_context_char_reduction"] > 0
    assert payload["capsule_probe_failure_count"] == 0
    assert payload["capsule_budget_violation_count"] == 0
    assert by_id["TC-LIN-001"].baseline_failed_contamination_count == 1
    assert by_id["TC-LIN-001"].candidate_failed_contamination_count == 0
    assert by_id["TC-LIN-001"].candidate_active_leaf_hit is True
    assert by_id["TC-LIN-001"].expected_active_checkpoint_consistent is True
    assert by_id["TC-LIN-001"].candidate_context_chars < by_id["TC-LIN-001"].baseline_context_chars
    assert by_id["TC-LIN-001"].candidate_context_chars < by_id["TC-LIN-001"].rich_candidate_context_chars
    assert by_id["TC-LIN-001"].capsule_all_probes_pass is True
    assert by_id["TC-LIN-001"].capsule_within_budget is True
    assert by_id["TC-LIN-001"].missing_required_context_terms == []
    assert by_id["TC-LIN-001"].present_forbidden_context_terms == []
    assert by_id["TC-LIN-003"].ready_for_lineage_review is False
    assert "ambiguous_active_branches" in by_id["TC-LIN-003"].issues

    stale_expected_payload = asdict(benchmark_module.TASK_CONTINUITY_LINEAGE_ABLATION_CASES[1])
    stale_expected_payload["id"] = "TC-LIN-STALE-EXPECTED"
    stale_expected_payload["expected_active_checkpoint_id"] = "mine-root"
    stale_expected = benchmark_module.TaskContinuityLineageAblationCase(**stale_expected_payload)
    stale_result = runner.run_task_continuity_lineage_ablation([stale_expected]).cases[0]
    assert stale_result.ready_for_lineage_review is False
    assert stale_result.expected_active_checkpoint_consistent is False
    assert stale_result.inferred_active_checkpoint_ids == ["mine-leaf"]
    assert "explicit_active_leaf_mismatch" in stale_result.issues

    tight_budget_payload = asdict(benchmark_module.TASK_CONTINUITY_LINEAGE_ABLATION_CASES[0])
    tight_budget_payload["id"] = "TC-LIN-TIGHT-BUDGET"
    tight_budget_payload["capsule_char_budget"] = 120
    tight_budget_case = benchmark_module.TaskContinuityLineageAblationCase(**tight_budget_payload)
    tight_budget = runner.run_task_continuity_lineage_ablation([tight_budget_case]).cases[0]
    assert tight_budget.candidate_context_chars <= 120
    assert tight_budget.capsule_within_budget is True
    assert tight_budget.capsule_all_probes_pass is False
    assert tight_budget.candidate_regressed is True
    assert tight_budget.ready_for_lineage_review is False
    assert "candidate_capsule_probe_failure" in tight_budget.issues
    print("PASS: Task continuity lineage ablation isolates failed branches")


def test_task_continuity_restoration_report_rejects_state_rollback():
    runner = BenchmarkRunner(Config())
    ready_report = runner.run_task_continuity_restoration_report()
    ready = ready_report.cases[0]
    assert ready.ready_for_shadow_review is True
    assert ready.proposal_is_review_only is True
    assert ready.failed_checkpoint_failed is True
    assert ready.target_verified is True
    assert ready.target_is_ancestor is True
    assert ready.target_evidence_consistent is True
    assert ready.branch_isolated is True
    assert ready.lineage_integrity is True
    assert ready.state_evidence_complete is True
    assert ready.state_preserved_before_action is True
    assert "hunger" in ready.critical_state_fields
    assert "xp_level" in ready.critical_state_fields
    assert ready.target_reachable is True
    assert ready.completion_non_regression is True

    bad_payload = asdict(benchmark_module.TASK_CONTINUITY_RESTORATION_CASES[0])
    bad_payload["id"] = "TC-RESTORE-BAD"
    bad_payload["candidate_pre_action_state"] = {
        "inventory": {},
        "position": {"x": 3, "y": 64, "z": 0},
        "dimension": "overworld",
        "health": 20,
    }
    bad_payload["route_verified"] = False
    bad_payload["baseline_completed"] = True
    bad_payload["candidate_completed"] = False
    bad_case = benchmark_module.TaskContinuityRestorationCase(**bad_payload)
    bad_report = runner.run_task_continuity_restoration_report([bad_case])
    bad = bad_report.cases[0]
    assert bad.ready_for_shadow_review is False
    assert bad.state_preserved_before_action is False
    assert bad.target_reachable is False
    assert bad.completion_non_regression is False
    assert "state_changed_before_shadow_action" in bad.issues
    assert "route_evidence_missing" in bad.issues
    assert "candidate_completion_regression_or_missing" in bad.issues

    integrity_payload = asdict(benchmark_module.TASK_CONTINUITY_RESTORATION_CASES[0])
    integrity_payload["id"] = "TC-RESTORE-INTEGRITY-BAD"
    for record in integrity_payload["records"]:
        if record["id"] == "restore-fail":
            record["validation_status"] = "verified"
            record["branch_status"] = "active"
        if record["id"] == "restore-proposal":
            record["validation_evidence"]["verified_target_checkpoint_id"] = "wrong-target"
    integrity_case = benchmark_module.TaskContinuityRestorationCase(**integrity_payload)
    integrity = runner.run_task_continuity_restoration_report([integrity_case]).cases[0]
    assert integrity.ready_for_shadow_review is False
    assert integrity.failed_checkpoint_failed is False
    assert integrity.target_evidence_consistent is False
    assert "failed_checkpoint_not_failed" in integrity.issues
    assert "revision_target_evidence_mismatch" in integrity.issues
    print("PASS: Task continuity restoration report rejects state rollback")


def test_task_continuity_restoration_gate_allows_shadow_only():
    runner = BenchmarkRunner(Config())
    builtin_lineage = runner.task_continuity_lineage_ablation_payload(
        runner.run_task_continuity_lineage_ablation()
    )
    builtin_restoration = runner.task_continuity_restoration_payload(
        runner.run_task_continuity_restoration_report()
    )
    builtin_gate = runner.build_task_continuity_restoration_gate(
        lineage_ablation_reports=[builtin_lineage],
        restoration_reports=[builtin_restoration],
    )
    assert builtin_gate["readiness"] == "review"
    assert builtin_gate["automatic_restore_allowed"] is False
    assert builtin_gate["shadow_revision_selection_allowed"] is False
    assert builtin_gate["eligible_lineage_case_count"] == 0

    lineage_template = asdict(runner.run_task_continuity_lineage_ablation().cases[0])
    lineage_cases = []
    for index in range(3):
        case = json.loads(json.dumps(lineage_template))
        case["case_id"] = f"LIVE-LINEAGE-{index + 1}"
        case["evidence_kind"] = "live_trace"
        case["source"] = f"session-lineage-{index + 1}.jsonl"
        case["task_stream_id"] = f"live-stream-{index + 1}"
        case["seed"] = str(index + 10)
        lineage_cases.append(case)
    live_lineage = {
        "type": "task_continuity_lineage_ablation",
        "schema_version": 3,
        "cases": lineage_cases,
        "errors": [],
    }

    restoration_template = asdict(runner.run_task_continuity_restoration_report().cases[0])
    restoration_cases = []
    for index in range(3):
        case = json.loads(json.dumps(restoration_template))
        case["case_id"] = f"LIVE-RESTORE-{index + 1}"
        case["evidence_kind"] = "live_trace"
        case["source"] = f"session-restore-{index + 1}.jsonl"
        case["baseline_session_id"] = f"baseline-{index + 1}"
        case["candidate_session_id"] = f"candidate-{index + 1}"
        case["route_evidence_id"] = f"route-{index + 1}"
        restoration_cases.append(case)
    live_restoration = {
        "type": "task_continuity_restoration_report",
        "schema_version": 2,
        "cases": restoration_cases,
        "errors": [],
    }
    approved = runner.build_task_continuity_restoration_gate(
        lineage_ablation_reports=[live_lineage],
        restoration_reports=[live_restoration],
    )
    assert approved["readiness"] == "approved"
    assert approved["decision"] == "allow_shadow_revision_selection"
    assert approved["shadow_revision_selection_allowed"] is True
    assert approved["automatic_restore_allowed"] is False
    assert approved["distinct_candidate_session_count"] == 3
    assert approved["average_context_char_reduction"] > 0

    regressed = json.loads(json.dumps(live_restoration))
    regressed["cases"][0]["state_preserved_before_action"] = False
    regressed["cases"][0]["ready_for_shadow_review"] = False
    rejected = runner.build_task_continuity_restoration_gate(
        lineage_ablation_reports=[live_lineage],
        restoration_reports=[regressed],
    )
    assert rejected["readiness"] == "rejected"
    assert rejected["decision"] == "reject_restoration_policy"
    assert rejected["automatic_restore_allowed"] is False

    invalid_integrity = json.loads(json.dumps(live_restoration))
    invalid_integrity["cases"][0]["failed_checkpoint_failed"] = False
    invalid_integrity_gate = runner.build_task_continuity_restoration_gate(
        lineage_ablation_reports=[live_lineage],
        restoration_reports=[invalid_integrity],
    )
    assert invalid_integrity_gate["readiness"] == "rejected"
    assert invalid_integrity_gate["restoration_integrity_failure_count"] == 1
    assert invalid_integrity_gate["automatic_restore_allowed"] is False

    invalid_lineage = json.loads(json.dumps(live_lineage))
    invalid_lineage["cases"][0]["expected_active_checkpoint_consistent"] = False
    invalid_lineage_gate = runner.build_task_continuity_restoration_gate(
        lineage_ablation_reports=[invalid_lineage],
        restoration_reports=[live_restoration],
    )
    assert invalid_lineage_gate["readiness"] == "rejected"
    assert invalid_lineage_gate["lineage_integrity_failure_count"] == 1
    assert invalid_lineage_gate["automatic_restore_allowed"] is False

    invalid_capsule = json.loads(json.dumps(live_lineage))
    invalid_capsule["cases"][0]["capsule_all_probes_pass"] = False
    invalid_capsule_gate = runner.build_task_continuity_restoration_gate(
        lineage_ablation_reports=[invalid_capsule],
        restoration_reports=[live_restoration],
    )
    assert invalid_capsule_gate["readiness"] == "rejected"
    assert invalid_capsule_gate["capsule_probe_failure_count"] == 1
    assert invalid_capsule_gate["automatic_restore_allowed"] is False

    no_context_savings = json.loads(json.dumps(live_lineage))
    for case in no_context_savings["cases"]:
        case["context_char_reduction"] = 0
    no_context_savings_gate = runner.build_task_continuity_restoration_gate(
        lineage_ablation_reports=[no_context_savings],
        restoration_reports=[live_restoration],
    )
    assert no_context_savings_gate["readiness"] == "review"
    assert no_context_savings_gate["shadow_revision_selection_allowed"] is False
    assert no_context_savings_gate["automatic_restore_allowed"] is False
    print("PASS: Task continuity restoration gate allows shadow only")


def test_continual_learning_report_aggregates_open_ended_axes():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_continual_learning.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Explore, collect coal, and craft torches"}},
        {
            "type": "memory_read",
            "data": {
                "layer": "mixed",
                "memory_type": "relevant_memory",
                "source": "planner_goal",
                "query": "craft torches",
                "result_chars": 180,
                "has_result": True,
            },
        },
        {
            "type": "memory_read",
            "data": {
                "layer": "task",
                "memory_type": "task_memory",
                "source": "planner_task_memory",
                "query": "craft torches",
                "result_chars": 100,
                "has_result": True,
            },
        },
        {"type": "plan", "data": {"status": "in_progress", "actions": [
            {"type": "move_to", "parameters": {"x": 8, "z": 0}},
            {"type": "dig", "parameters": {"block": "coal_ore"}},
            {"type": "craft", "parameters": {"item": "torch"}},
        ]}},
        {"type": "observation", "data": {
            "position": {"x": 0, "y": 64, "z": 0},
            "inventory": {"stick": 2},
            "nearby_blocks": [{"name": "oak_log"}],
            "nearby_entities": [],
        }},
        {"type": "action", "data": {"action": {"type": "move_to", "parameters": {"x": 8, "z": 0}}, "result": {"success": True}}},
        {"type": "observation", "data": {
            "position": {"x": 8, "y": 63, "z": 0},
            "inventory": {"stick": 2},
            "nearby_blocks": [{"name": "coal_ore"}],
            "grounded_resources": [{"name": "coal_ore"}],
            "nearby_entities": [{"type": "sheep", "hostile": False}],
        }},
        {"type": "action", "data": {"action": {"type": "dig", "parameters": {"block": "coal_ore"}}, "result": {"success": True, "block": "coal_ore"}}},
        {"type": "observation", "data": {
            "position": {"x": 8, "y": 63, "z": 0},
            "inventory": {"stick": 2, "coal": 1},
            "nearby_blocks": [{"name": "coal_ore"}],
            "grounded_resources": [{"name": "coal_ore"}],
        }},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "torch"}}, "result": {"success": True, "item": "torch"}}},
        {"type": "observation", "data": {
            "position": {"x": 8, "y": 63, "z": 0},
            "inventory": {"torch": 4},
            "nearby_blocks": [{"name": "coal_ore"}],
        }},
        {
            "type": "memory_write",
            "data": {
                "layer": "semantic",
                "memory_type": "fact",
                "source": "goal_verification",
                "content": "Coal plus sticks produced torches after moving to a coal_ore vein.",
                "confidence": 0.9,
            },
        },
        {
            "type": "memory_write",
            "data": {
                "layer": "episodic",
                "memory_type": "experience",
                "source": "goal_end",
                "content": "Moved to coal_ore, mined coal, then crafted torch.",
                "confidence": 0.85,
            },
        },
        {"type": "goal_verification", "data": {"achieved": True, "status": "achieved"}},
        {"type": "goal_end", "data": {"goal": "Explore, collect coal, and craft torches", "result": {"completed": True}}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config(memory_dir=os.path.join(tmpdir, "memory")))
    report = runner.run_continual_learning_report_from_logs([session_path], cell_size=8)
    case = report.cases[0]

    assert report.log_count == 1
    assert report.ready_log_count == 1
    assert report.completed_goal_count == 1
    assert report.failed_action_count == 0
    assert case.unique_action_type_count == 3
    assert case.action_entropy > 0.9
    assert case.memory_read_count == 2
    assert case.memory_write_count == 2
    assert case.semantic_write_count == 1
    assert case.episodic_write_count == 1
    assert case.bounded_cycle_count == 1
    assert case.unbounded_context_cycle_count == 0
    assert case.unique_cell_count >= 2
    assert case.object_exploration_count >= 5
    assert case.axis_scores["continual_learning"] > 0.45
    assert "weak_memory_learning_loop" not in case.issues

    feedback = runner.continual_learning_feedback(report)
    assert feedback["average_axis_scores"]["action_diversity"] > 0.9
    assert not any(hint["continual_learning_policy"] == "enforce_bounded_context_contract" for hint in feedback["policy_hints"])
    print("PASS: Continual learning report aggregates open-ended axes")


def test_continual_learning_report_accepts_flat_session_log_fields():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_continual_learning_flat.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "gather oak and craft planks"}},
        {"type": "memory_read", "data": {"memory_type": "semantic", "content": "oak trees provide logs for planks"}},
        {"type": "memory_read", "data": {"memory_type": "episodic", "content": "last run found oak near x=8 z=0"}},
        {"type": "plan", "data": {"goal": "gather oak and craft planks", "steps": ["move to oak", "dig oak", "craft planks"]}},
        {
            "type": "observation",
            "data": {
                "position": {"x": 0, "y": 64, "z": 0},
                "nearby_blocks": [{"type": "grass_block"}],
                "nearby_resources": [{"type": "oak_log"}],
                "nearby_entities": [{"type": "cow"}],
            },
        },
        {"type": "action", "data": {"action": "move_to", "result": {"success": True, "target": "oak_tree"}}},
        {
            "type": "observation",
            "data": {
                "position": {"x": 9, "y": 64, "z": 1},
                "inventory": {"oak_log": 1},
                "nearby_blocks": [{"type": "oak_log"}, {"type": "oak_leaves"}],
                "nearby_resources": [{"type": "oak_log"}],
            },
        },
        {"type": "action", "data": {"action": "dig", "result": {"success": True, "target": "oak_log"}}},
        {"type": "memory_write", "data": {"memory_type": "episodic", "content": "oak was reachable near x=9 z=1"}},
        {"type": "action", "data": {"action": "craft", "result": {"success": True, "target": "oak_planks"}}},
        {"type": "memory_write", "data": {"memory_type": "semantic", "content": "one oak log can be converted into planks after harvesting"}},
        {"type": "goal_verification", "data": {"achieved": True}},
        {"type": "goal_end", "data": {"status": "completed"}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config(memory_dir=os.path.join(tmpdir, "memory")))
    report = runner.run_continual_learning_report_from_logs([session_path], cell_size=8)
    case = report.cases[0]
    feedback = runner.continual_learning_feedback(report)

    assert report.completed_goal_count == 1
    assert case.goal_count == 1
    assert case.unique_action_type_count == 3
    assert case.action_entropy > 0.9
    assert case.semantic_write_count == 1
    assert case.episodic_write_count == 1
    assert "no_goal_progress" not in case.issues
    assert feedback["completed_goal_count"] == 1
    assert feedback["average_axis_scores"]["action_diversity"] > 0.9
    print("PASS: Continual learning report accepts flat session log fields")


def test_task_stream_transfer_report_scores_controlled_reuse():
    tmpdir = tempfile.mkdtemp()
    stream_path = os.path.join(tmpdir, "controlled_stream.json")
    stream = {
        "id": "wood_to_pickaxe_transfer",
        "description": "Reusable wood and crafting-table sub-solutions should help later tool goals.",
        "tasks": [
            {
                "id": "collect_oak",
                "goal": "Collect oak logs",
                "produced_tags": ["oak_log", "planks"],
                "baseline_score": 0.30,
                "first_pass_score": 0.80,
                "second_pass_score": 0.86,
                "heldout_score": 0.78,
                "reuse_evidence": "agent writes oak_log and planks lesson for later crafting",
            },
            {
                "id": "craft_table",
                "goal": "Craft a crafting table from planks",
                "depends_on": ["collect_oak"],
                "expected_reuse_tags": ["oak_log", "planks"],
                "produced_tags": ["crafting_table"],
                "baseline_score": 0.20,
                "first_pass_score": 0.76,
                "second_pass_score": 0.82,
                "heldout_score": 0.72,
                "reuse_evidence": "memory_read reused oak_log to planks workflow before crafting_table",
            },
            {
                "id": "craft_stone_pickaxe",
                "goal": "Craft a stone pickaxe after collecting cobblestone",
                "depends_on": ["craft_table"],
                "expected_reuse_tags": ["crafting_table", "planks"],
                "baseline_score": 0.18,
                "first_pass_score": 0.70,
                "second_pass_score": 0.76,
                "heldout_score": 0.68,
                "reuse_evidence": "skill match used crafting_table and planks prerequisites for pickaxe workflow",
            },
        ],
    }
    with open(stream_path, "w", encoding="utf-8") as f:
        json.dump(stream, f, indent=2)

    runner = BenchmarkRunner(Config(memory_dir=os.path.join(tmpdir, "memory")))
    report = runner.run_task_stream_transfer_report_from_files([stream_path])
    case = report.cases[0]
    feedback = runner.task_stream_transfer_feedback(report)

    assert report.stream_count == 1
    assert report.ready_stream_count == 1
    assert report.task_count == 3
    assert report.reusable_relation_count == 2
    assert report.reuse_coverage == 1.0
    assert report.average_plasticity_gain > 0.45
    assert report.average_stability_gain > 0.0
    assert report.average_generalization_gain > 0.4
    assert report.interference_count == 0
    assert case.ready_for_transfer_review
    assert case.plasticity_gain > 0.45
    assert not case.issues
    assert case.tasks[1].reuse_hit_tags
    assert "missing_reuse_evidence" not in case.tasks[1].issues
    assert not any(hint["task_stream_policy"] == "quarantine_interfering_memories_or_skills" for hint in feedback["policy_hints"])
    print("PASS: Task stream transfer report scores controlled reuse")


def test_seed_minecraft_task_stream_specs_are_gate_ready():
    stream_path = os.path.abspath(os.path.join(
        os.path.dirname(__file__),
        "..",
        "workspace",
        "evals",
        "minecraft_task_streams.json",
    ))
    runner = BenchmarkRunner(Config())
    report = runner.run_task_stream_transfer_report_from_files([stream_path])
    feedback = runner.task_stream_transfer_feedback(report)
    gate = runner.build_task_stream_transfer_gate(transfer_reports=[{
        "stream_count": report.stream_count,
        "ready_stream_count": report.ready_stream_count,
        "task_count": report.task_count,
        "reusable_relation_count": report.reusable_relation_count,
        "reuse_expected_tag_count": report.reuse_expected_tag_count,
        "reuse_hit_tag_count": report.reuse_hit_tag_count,
        "reuse_coverage": report.reuse_coverage,
        "interference_count": report.interference_count,
        "average_plasticity_gain": report.average_plasticity_gain,
        "average_stability_gain": report.average_stability_gain,
        "average_generalization_gain": report.average_generalization_gain,
        "task_stream_feedback": feedback,
        "errors": report.errors,
    }])
    stream_ids = {case.stream_id for case in report.cases}

    assert report.errors == []
    assert stream_ids == {
        "wood_to_tools",
        "shelter_escalation",
        "mining_progression",
        "navigation_return_loop",
        "redstone_variant",
    }
    assert report.stream_count == 5
    assert report.ready_stream_count == 5
    assert report.task_count == 15
    assert report.reuse_coverage == 1.0
    assert report.interference_count == 0
    assert report.average_plasticity_gain > 0.3
    assert report.average_stability_gain > 0.0
    assert report.average_generalization_gain > 0.25
    assert all(case.ready_for_transfer_review for case in report.cases)
    assert all(not case.issues for case in report.cases)
    assert gate["readiness"] == "approved"
    print("PASS: Seed Minecraft task streams are ready for transfer gates")


def test_task_stream_transfer_gate_controls_promotion():
    runner = BenchmarkRunner(Config())
    approved_payload = {
        "stream_count": 1,
        "ready_stream_count": 1,
        "task_count": 3,
        "reuse_expected_tag_count": 4,
        "reuse_hit_tag_count": 4,
        "reuse_coverage": 1.0,
        "average_plasticity_gain": 0.52,
        "average_stability_gain": 0.04,
        "average_generalization_gain": 0.44,
        "interference_count": 0,
        "task_stream_feedback": {"policy_hints": []},
        "errors": [],
    }
    approved = runner.build_task_stream_transfer_gate(
        transfer_reports=[approved_payload],
        target="skill:craft_stone_pickaxe",
    )
    assert approved["type"] == "task_stream_transfer_gate"
    assert approved["schema_version"] == 1
    assert approved["readiness"] == "approved"
    assert approved["decision"] == "allow_candidate_promotion"
    assert approved["evidence_count"] == 1
    assert approved["regression_count"] == 0
    assert approved["reuse_coverage"] == 1.0

    review_payload = {
        **approved_payload,
        "reuse_hit_tag_count": 1,
        "reuse_coverage": 0.25,
        "average_generalization_gain": None,
    }
    review = runner.build_task_stream_transfer_gate(transfer_reports=[review_payload])
    assert review["readiness"] == "review"
    assert review["decision"] == "keep_candidate_review_only"
    assert review["warning_count"] == 1
    assert review["regression_count"] == 0

    rejected_payload = {
        **approved_payload,
        "average_stability_gain": -0.12,
        "interference_count": 1,
    }
    rejected = runner.build_task_stream_transfer_gate(transfer_reports=[rejected_payload])
    assert rejected["readiness"] == "rejected"
    assert rejected["decision"] == "do_not_promote_candidate"
    assert rejected["regression_count"] == 1
    print("PASS: Task stream transfer gate controls promotion")


def test_ingest_queues_repeated_causal_summary_candidate():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_repeated.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Gather oak logs"}},
        {"type": "observation", "data": {"inventory": {}, "nearby_blocks": [{"name": "oak_log"}], "nearby_entities": []}},
        {"type": "action", "data": {"action": {"type": "dig", "parameters": {"block": "oak_log"}}, "result": {"success": True, "block": "oak_log"}}},
        {"type": "observation", "data": {"inventory": {"oak_log": 1}, "nearby_blocks": [{"name": "oak_log"}], "nearby_entities": []}},
        {"type": "action", "data": {"action": {"type": "dig", "parameters": {"block": "oak_log"}}, "result": {"success": True, "block": "oak_log"}}},
        {"type": "observation", "data": {"inventory": {"oak_log": 2}, "nearby_blocks": [{"name": "oak_log"}], "nearby_entities": []}},
        {"type": "action", "data": {"action": {"type": "dig", "parameters": {"block": "oak_log"}}, "result": {"success": True, "block": "oak_log"}}},
        {"type": "observation", "data": {"inventory": {"oak_log": 3}, "nearby_blocks": [], "nearby_entities": []}},
        {"type": "goal_end", "data": {"goal": "Gather oak logs", "result": {"completed": True}}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    config = Config(memory_dir=os.path.join(tmpdir, "memory"))
    runner = BenchmarkRunner(config)
    queue = SkillCandidateQueue(os.path.join(tmpdir, "skill_candidates.jsonl"))
    report = runner.ingest_results(
        [BenchmarkResult("BM-R", "Repeated wood gathering", "pass", session_log_path=session_path)],
        candidate_queue=queue,
    )

    pending = queue.pending()
    causal_candidates = [candidate for candidate in pending if candidate.signals.get("source") == "causal_summary"]
    assert report.processed_results == 1
    assert report.skill_candidates == 2
    assert causal_candidates
    assert causal_candidates[0].name == "causal_dig_oak_log"
    assert causal_candidates[0].signals["repeat_count"] == 3
    print("PASS: Benchmark ingestion queues repeated causal summary candidates")


def test_ingest_queues_failure_correction_candidate():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_failure_correction.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Craft torches"}},
        {"type": "observation", "data": {"inventory": {"stick": 1}, "nearby_blocks": [{"name": "coal_ore"}], "nearby_entities": []}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "torch"}}, "result": {"success": False, "error": "Missing coal"}}},
        {"type": "observation", "data": {"inventory": {"stick": 1}, "nearby_blocks": [{"name": "coal_ore"}], "nearby_entities": []}},
        {"type": "action", "data": {"action": {"type": "dig", "parameters": {"block": "coal_ore"}}, "result": {"success": True, "block": "coal_ore"}}},
        {"type": "observation", "data": {"inventory": {"stick": 1, "coal": 1}, "nearby_blocks": [], "nearby_entities": []}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "torch"}}, "result": {"success": True, "item": "torch"}}},
        {"type": "observation", "data": {"inventory": {"torch": 4}, "nearby_blocks": [{"name": "coal_ore"}], "nearby_entities": []}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "torch"}}, "result": {"success": False, "error": "Missing coal"}}},
        {"type": "observation", "data": {"inventory": {"stick": 1}, "nearby_blocks": [{"name": "coal_ore"}], "nearby_entities": []}},
        {"type": "action", "data": {"action": {"type": "dig", "parameters": {"block": "coal_ore"}}, "result": {"success": True, "block": "coal_ore"}}},
        {"type": "observation", "data": {"inventory": {"stick": 1, "coal": 1}, "nearby_blocks": [], "nearby_entities": []}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "torch"}}, "result": {"success": True, "item": "torch"}}},
        {"type": "goal_end", "data": {"goal": "Craft torches", "result": {"completed": True}}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    config = Config(memory_dir=os.path.join(tmpdir, "memory"))
    runner = BenchmarkRunner(config)
    queue = SkillCandidateQueue(os.path.join(tmpdir, "skill_candidates.jsonl"))
    report = runner.ingest_results(
        [BenchmarkResult("BM-C", "Failure correction", "pass", session_log_path=session_path)],
        candidate_queue=queue,
    )

    pending = queue.pending()
    correction_candidates = [
        candidate for candidate in pending
        if candidate.signals.get("source") == "failure_correction_summary"
    ]
    assert report.processed_results == 1
    assert correction_candidates
    assert correction_candidates[0].name == "correct_craft_torch_via_dig_coal_ore"
    assert correction_candidates[0].signals["failure_count"] == 2
    assert correction_candidates[0].signals["correction_count"] == 2
    print("PASS: Benchmark ingestion queues failure correction candidates")


def test_benchmark_results_persist_intervention_metrics():
    tmpdir = tempfile.mkdtemp()
    runner = BenchmarkRunner(Config(), output_dir=tmpdir)
    runner.results = [
        BenchmarkResult(
            "BM-I",
            "Intervention metric task",
            "pass",
            intervention_metrics={
                "policy_intervention_count": 1,
                "policy_intervention_successes": 1,
                "policy_intervention_success_rate": 1.0,
                "visual_action_intervention_count": 2,
                "visual_action_intervention_phases": {
                    "prepend_approach": 1,
                    "fill_coordinates": 1,
                },
            },
            memory_policy_metrics={
                "memory_read_count": 1,
                "memory_read_filtered_entries": 2,
                "memory_read_filter_reasons": {"superseded": 2},
            },
            session_log_path="logs/session_test.jsonl",
        )
    ]
    runner.save_results("results.json")

    with open(os.path.join(tmpdir, "results.json"), "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data[0]["intervention_metrics"]["policy_intervention_count"] == 1
    assert data[0]["intervention_metrics"]["policy_intervention_success_rate"] == 1.0
    assert data[0]["intervention_metrics"]["visual_action_intervention_count"] == 2
    assert data[0]["intervention_metrics"]["visual_action_intervention_phases"]["prepend_approach"] == 1
    assert data[0]["memory_policy_metrics"]["memory_read_filtered_entries"] == 2
    assert data[0]["memory_policy_metrics"]["memory_read_filter_reasons"]["superseded"] == 2
    print("PASS: Benchmark results persist intervention metrics")


def test_visual_action_ablation_compares_enabled_and_disabled_modes():
    runner = BenchmarkRunner(Config())
    report = runner.run_visual_action_ablation()

    assert len(report.cases) == 5
    assert report.passed_count == 5
    assert report.changed_count == 4
    assert report.helped_count == 4
    by_id = {case.case_id: case for case in report.cases}
    assert by_id["AB-VISACT-001"].enabled_phases["fill_coordinates"] == 1
    assert by_id["AB-VISACT-002"].enabled_actions[0]["type"] == "move_to"
    assert by_id["AB-VISACT-002"].enabled_phases["prepend_approach"] == 1
    assert by_id["AB-VISACT-003"].enabled_phases["prepend_danger"] == 1
    assert not by_id["AB-VISACT-004"].changed
    assert by_id["AB-VISACT-004"].passed
    assert by_id["AB-VISACT-005"].enabled_actions[0]["type"] == "look_at"
    assert by_id["AB-VISACT-005"].enabled_phases["prepend_focus"] == 1
    print("PASS: Visual action ablation compares enabled and disabled modes")


def test_visual_action_ablation_replays_session_log_interventions():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_visual_action.jsonl")
    move_action = {"type": "move_to", "parameters": {"x": 8.0, "z": 0.0, "y": 64}}
    dig_action = {"type": "dig", "parameters": {"x": 10, "y": 64, "z": 0}}
    events = [
        {"type": "goal_start", "data": {"goal": "mine iron ore"}},
        {"type": "observation", "data": {
            "position": {"x": 0, "y": 64, "z": 0},
            "grounded_resources": [{
                "name": "iron_ore",
                "can_harvest": True,
                "best_available_tool": "stone_pickaxe",
                "required_tool_tier": 2,
                "position": {"x": 10, "y": 64, "z": 0},
            }],
        }},
        {"type": "visual_action_intervention", "data": {
            "goal": "mine iron ore",
            "phase": "prepend_approach",
            "suggestion": {
                "kind": "resource_approach",
                "action": move_action,
                "reason": "move within reach of visible iron_ore",
            },
        }},
        {"type": "plan", "data": {
            "status": "in_progress",
            "actions": [move_action, dig_action],
        }},
    ]
    with open(session_path, "w", encoding="utf-8-sig") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config())
    cases = runner.visual_action_cases_from_logs([session_path])
    report = runner.run_visual_action_ablation_from_logs([session_path])

    assert len(cases) == 1
    assert cases[0].expected_phase == "prepend_approach"
    assert cases[0].plan["actions"] == [dig_action]
    assert report.passed_count == 1
    assert report.changed_count == 1
    assert report.cases[0].enabled_actions[0] == move_action
    print("PASS: Visual action ablation replays session log interventions")


def test_policy_skill_ablation_compares_enabled_and_disabled_modes():
    runner = BenchmarkRunner(Config())
    report = runner.run_policy_skill_ablation()

    assert report.helped_count == 1
    assert len(report.cases) == 1
    case = report.cases[0]
    assert not case.disabled_corrected
    assert case.enabled_corrected
    assert case.enabled_helped
    assert case.disabled_interventions == 0
    assert case.enabled_interventions == 1
    assert case.enabled_success_rate == 1.0
    assert case.enabled_actions == ["dig", "craft"]
    print("PASS: Policy skill ablation compares enabled and disabled modes")


def test_skill_frontier_routing_ablation_uses_fixed_task_intervals():
    runner = BenchmarkRunner(Config())
    report = runner.run_skill_frontier_routing_ablation()
    payload = runner.skill_frontier_routing_payload(report)
    cases = {case.case_id: case for case in report.cases}

    assert payload["type"] == "skill_frontier_routing_ablation"
    assert payload["schema_version"] == 1
    assert payload["case_count"] == 3
    assert payload["ready_case_count"] == 3
    assert payload["non_builtin_ready_case_count"] == 0
    assert payload["baseline_top1_hit_count"] == 0
    assert payload["candidate_top1_hit_count"] == 3
    assert payload["helped_count"] == 3
    assert payload["regression_count"] == 0
    assert payload["average_candidate_frontier_coverage"] == 1.0
    assert cases["SKILL-ROUTE-001"].candidate_skill_names[0] == "gather_wood"
    assert cases["SKILL-ROUTE-001"].blocked_candidate_count == 1
    assert cases["SKILL-ROUTE-001"].present_forbidden_skills == []
    assert cases["SKILL-ROUTE-002"].candidate_skill_names[0] == "mine_stone"
    assert cases["SKILL-ROUTE-003"].candidate_skill_names[0] == "defend_self"
    assert all(case.candidate_context_chars <= 600 for case in report.cases)
    assert all(case.fixed_controls for case in report.cases)
    assert report.errors == []
    print("PASS: Skill frontier routing ablation uses fixed task intervals")


def test_policy_skill_ablation_loads_cases_from_skill_library():
    tmpdir = tempfile.mkdtemp()
    skill_dir = os.path.join(tmpdir, "skills")
    skills = SkillLibrary(storage_path=skill_dir, persist=True)
    implementation = {
        "type": "failure_correction_skill",
        "avoid_action_template": {"type": "craft", "parameters": {"item": "torch"}},
        "primary_correction": {"type": "dig", "parameters": {"block": "coal_ore"}},
        "correction_sequence": [
            {"type": "dig", "parameters": {"block": "coal_ore"}},
            {"type": "craft", "parameters": {"item": "torch"}},
        ],
        "evidence": {"failure_why": "Missing coal"},
    }
    skills.create_skill(
        "correct_craft_torch_via_dig_coal_ore",
        "Correct missing coal before crafting torches",
        json.dumps(implementation),
    )

    runner = BenchmarkRunner(Config())
    cases = runner.policy_skill_cases_from_library(skill_dir)
    report = runner.run_policy_skill_ablation(skill_storage_path=skill_dir, include_builtin=False)

    assert len(cases) == 1
    assert cases[0].source == "skill_library"
    assert cases[0].skill_name == "correct_craft_torch_via_dig_coal_ore"
    assert len(report.cases) == 1
    assert report.helped_count == 1
    assert report.cases[0].source == "skill_library"
    assert report.cases[0].enabled_actions == ["dig", "craft"]
    print("PASS: Policy skill ablation loads cases from skill library")


def test_policy_skill_benchmark_ablation_compares_live_suite_modes():
    class FakePolicyBenchmarkRunner(BenchmarkRunner):
        def _run_task_with_config(self, task, config):
            if config.enable_policy_skills:
                return BenchmarkResult(
                    task.task_id if hasattr(task, "task_id") else task.id,
                    task.name,
                    "pass",
                    duration_s=3.0,
                    intervention_metrics={
                        "policy_intervention_count": 1,
                        "policy_intervention_success_rate": 1.0,
                    },
                    session_log_path="enabled.jsonl",
                )
            return BenchmarkResult(
                task.task_id if hasattr(task, "task_id") else task.id,
                task.name,
                "fail",
                duration_s=4.0,
                intervention_metrics={"policy_intervention_count": 0},
                session_log_path="disabled.jsonl",
            )

    tmpdir = tempfile.mkdtemp()
    runner = FakePolicyBenchmarkRunner(Config(), output_dir=tmpdir)
    task = BenchmarkTask("BM-P", "Policy skill task", "Craft torches", "M1")
    report = runner.run_policy_skill_benchmark_ablation(tasks=[task])
    runner.save_policy_skill_benchmark_ablation_report(report, "policy_report.json")

    with open(os.path.join(tmpdir, "policy_report.json"), "r", encoding="utf-8") as f:
        data = json.load(f)

    assert report.disabled_passed_count == 0
    assert report.enabled_passed_count == 1
    assert report.helped_count == 1
    assert report.cases[0].disabled_status == "fail"
    assert report.cases[0].enabled_status == "pass"
    assert report.cases[0].enabled_interventions == 1
    assert data["enabled_passed_count"] == 1
    assert data["cases"][0]["enabled_helped"]
    print("PASS: Policy skill benchmark ablation compares live suite modes")


def test_skill_memory_benchmark_ablation_compares_policy_only_baseline():
    class FakeSkillMemoryBenchmarkRunner(BenchmarkRunner):
        def _run_task_with_config(self, task, config):
            assert config.enable_policy_skills is True
            if config.enable_skill_memory_context:
                return BenchmarkResult(
                    task.task_id if hasattr(task, "task_id") else task.id,
                    task.name,
                    "pass",
                    duration_s=3.0,
                    intervention_metrics={
                        "policy_hint_count": 1,
                        "skill_memory_hint_count": 2,
                    },
                    session_log_path="skill_memory_enabled.jsonl",
                )
            return BenchmarkResult(
                task.task_id if hasattr(task, "task_id") else task.id,
                task.name,
                "fail",
                duration_s=4.0,
                intervention_metrics={
                    "policy_hint_count": 1,
                    "skill_memory_hint_count": 0,
                },
                session_log_path="policy_only_baseline.jsonl",
            )

    tmpdir = tempfile.mkdtemp()
    runner = FakeSkillMemoryBenchmarkRunner(Config(), output_dir=tmpdir)
    task = BenchmarkTask("BM-SM", "Skill memory task", "Craft torches", "M1")
    report = runner.run_skill_memory_benchmark_ablation(tasks=[task])
    runner.save_skill_memory_benchmark_ablation_report(report, "skill_memory_report.json")

    with open(os.path.join(tmpdir, "skill_memory_report.json"), "r", encoding="utf-8") as f:
        data = json.load(f)

    assert report.baseline_passed_count == 0
    assert report.enabled_passed_count == 1
    assert report.changed_count == 1
    assert report.helped_count == 1
    assert report.cases[0].baseline_skill_memory_hints == 0
    assert report.cases[0].enabled_skill_memory_hints == 2
    assert data["helped_count"] == 1
    print("PASS: Skill memory benchmark ablation compares policy-only baseline")


def test_skill_memory_quality_report_labels_typed_hint_outcomes():
    tmpdir = tempfile.mkdtemp()
    conflict_path = os.path.join(tmpdir, "session_skill_memory_conflict.jsonl")
    supported_path = os.path.join(tmpdir, "session_skill_memory_supported.jsonl")
    no_hint_path = os.path.join(tmpdir, "session_skill_memory_missing.jsonl")
    conflict_events = [
        {"type": "goal_start", "data": {"goal": "Craft torches"}},
        {
            "type": "skill_memory_hint",
            "data": {
                "goal": "Craft torches",
                "task_family": "crafting",
                "hints": [
                    "REUSE craft_torch_memory_skill: mine coal first",
                    "AVOID craft_torch_memory_skill: do not craft torches without coal",
                    "REVIEW_ONLY desert_torch_route: unverified exposed-spawn route",
                ],
            },
        },
        {
            "type": "action",
            "data": {
                "action": {"type": "craft", "parameters": {"item": "torch"}},
                "result": {"success": False, "error": "Missing coal"},
            },
        },
        {
            "type": "action",
            "data": {
                "action": {"type": "craft", "parameters": {"item": "torch"}},
                "result": {"success": False, "error": "Missing coal"},
            },
        },
        {"type": "goal_verification", "data": {"achieved": False, "reason": "No torch in inventory"}},
    ]
    supported_events = [
        {"type": "goal_start", "data": {"goal": "Mine coal for torches"}},
        {
            "type": "skill_memory_hint",
            "data": {
                "goal": "Mine coal for torches",
                "task_family": "mining",
                "hints": ["REUSE mine_coal_for_torch: coal_ore first, craft later"],
            },
        },
        {
            "type": "action",
            "data": {
                "action": {"type": "dig", "parameters": {"block": "coal_ore"}},
                "result": {"success": True, "item": "coal"},
            },
        },
        {"type": "goal_end", "data": {"goal": "Mine coal for torches", "result": {"completed": True}}},
    ]
    no_hint_events = [
        {"type": "goal_start", "data": {"goal": "Gather wood"}},
        {"type": "action", "data": {"action": {"type": "dig", "parameters": {"block": "oak_log"}}, "result": {"success": True}}},
        {"type": "goal_end", "data": {"goal": "Gather wood", "result": {"completed": True}}},
    ]
    for path, events in (
        (conflict_path, conflict_events),
        (supported_path, supported_events),
        (no_hint_path, no_hint_events),
    ):
        with open(path, "w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config())
    report = runner.run_skill_memory_quality_report_from_logs([conflict_path, supported_path, no_hint_path])
    conflict = report.cases[0]
    supported = report.cases[1]
    missing = report.cases[2]

    assert report.log_count == 3
    assert report.ready_log_count == 2
    assert report.hint_count == 4
    assert report.hint_type_counts["REUSE"] == 2
    assert report.hint_type_counts["AVOID"] == 1
    assert report.hint_type_counts["REVIEW_ONLY"] == 1
    assert report.post_hint_goal_success_count == 1
    assert report.post_hint_goal_failure_count == 1
    assert report.repeated_post_hint_failure_count == 1
    items = {
        (item["hint_type"], item["skill"], item["task_family"]): item
        for item in report.hint_quality_items
    }
    assert items[("REUSE", "craft_torch_memory_skill", "crafting")]["labels"]["reuse_conflicted_with_failures"] == 1
    assert items[("AVOID", "craft_torch_memory_skill", "crafting")]["labels"]["avoid_unheeded_post_hint_failures"] == 1
    assert items[("REVIEW_ONLY", "desert_torch_route", "crafting")]["labels"]["review_only_present_keep_gated"] == 1
    assert items[("REUSE", "mine_coal_for_torch", "mining")]["labels"]["reuse_supported_by_goal_success"] == 1
    assert "reuse_conflicted_with_failures" in conflict.quality_labels
    assert "avoid_unheeded_post_hint_failures" in conflict.quality_labels
    assert "review_only_present_keep_gated" in conflict.quality_labels
    assert "reuse_supported_by_goal_success" in supported.quality_labels
    assert "no_skill_memory_hints" in missing.quality_labels

    feedback = runner.skill_memory_quality_feedback(report)
    policies = {hint["skill_memory_policy"]: hint for hint in feedback["policy_hints"]}
    assert policies["demote_conflicting_reuse_hints"]["priority"] == "high"
    assert policies["tighten_avoid_hint_prompting"]["count"] == 1
    assert policies["keep_review_only_skill_memory_gated"]["count"] == 1
    assert policies["candidate_promote_reuse_hints"]["priority"] == "low"
    assert policies["instrument_skill_memory_hints"]["count"] == 1
    assert feedback["hint_quality_items"]
    skill_library = SkillLibrary(storage_path=os.path.join(tmpdir, "skills"), persist=False)
    applied = runner.apply_skill_memory_quality_feedback(report, skill_library)
    profile = skill_library.skill_memory_quality_profile()
    assert applied == feedback
    assert "demote_conflicting_reuse_hints" in profile["policy_hints"]
    print("PASS: Skill memory quality report labels typed hint outcomes")


def test_skill_memory_quality_gate_controls_reuse_promotion():
    tmpdir = tempfile.mkdtemp()
    skill_library = SkillLibrary(storage_path=os.path.join(tmpdir, "skills"), persist=False)
    for name in ("supported_torch_skill", "risky_torch_skill", "thin_torch_skill"):
        skill_library.create_skill(
            name,
            "Craft torches with skill-local memory evidence",
            json.dumps([{"type": "craft", "parameters": {"item": "torch", "count": 4}}]),
            postconditions={"inventory": {"torch": 4}},
            gate={"decision": "approve", "verification": {"status": "achieved"}},
        )
        skill_library.record_skill_memory(
            name,
            f"{name} replayed a torch crafting route.",
            memory_type="replay",
            outcome="success",
            task_family="crafting",
            confidence=0.9,
        )
    skill_library.record_skill_memory(
        "supported_torch_skill",
        "Second supported replay confirmed coal-before-craft ordering.",
        memory_type="replay",
        outcome="success",
        task_family="crafting",
        confidence=0.85,
        transfer_gate={"readiness": "approved", "target": "skill:supported_torch_skill"},
    )

    memory_report = skill_library.skill_memory_report("Craft torches", task_family="crafting", limit=0)
    quality_feedback = {
        "skill_memory_quality_feedback": {
            "hint_quality_items": [
                {
                    "hint_type": "REUSE",
                    "skill": "supported_torch_skill",
                    "task_family": "crafting",
                    "count": 2,
                    "labels": {"reuse_supported_by_goal_success": 2},
                },
                {
                    "hint_type": "REUSE",
                    "skill": "risky_torch_skill",
                    "task_family": "crafting",
                    "count": 2,
                    "labels": {
                        "reuse_supported_by_goal_success": 1,
                        "reuse_conflicted_with_failures": 1,
                    },
                },
                {
                    "hint_type": "REUSE",
                    "skill": "thin_torch_skill",
                    "task_family": "crafting",
                    "count": 1,
                    "labels": {"reuse_supported_by_goal_success": 1},
                },
            ]
        }
    }

    runner = BenchmarkRunner(Config())
    gate = runner.build_skill_memory_quality_gate(
        memory_reports=[memory_report],
        quality_feedbacks=[quality_feedback],
        min_supported_reuse=2,
        max_conflicting_reuse=0,
    )
    candidates = {item["skill"]: item for item in gate["candidates"]}

    assert gate["readiness"] == "rejected"
    assert gate["approved_count"] == 1
    assert gate["review_count"] == 1
    assert gate["rejected_count"] == 1
    assert candidates["supported_torch_skill"]["readiness"] == "approved"
    assert candidates["supported_torch_skill"]["decision"] == "allow_supported_reuse_skill_memory_promotion"
    assert candidates["risky_torch_skill"]["readiness"] == "rejected"
    assert candidates["thin_torch_skill"]["readiness"] == "review"
    assert "promote_supported_reuse_skill_memory" in gate["policy_hints"]
    assert "block_conflicting_reuse_skill_memory" in gate["policy_hints"]
    print("PASS: Skill memory quality gate controls REUSE promotion")


def test_skill_memory_quality_preflight_requires_gate_and_ranking_effect():
    tmpdir = tempfile.mkdtemp()
    skill_dir = os.path.join(tmpdir, "skills")
    skill_library = SkillLibrary(storage_path=skill_dir, persist=True)
    skill_library.create_skill(
        "supported_torch_skill",
        "Craft torches with skill-local memory evidence",
        json.dumps([{"type": "craft", "parameters": {"item": "torch", "count": 4}}]),
        postconditions={"inventory": {"torch": 4}},
        gate={"decision": "approve", "verification": {"status": "achieved"}},
        status="advisory",
        task_family="crafting",
    )
    skill_library.record_skill_memory(
        "supported_torch_skill",
        "Mine coal before crafting torches.",
        memory_type="replay",
        outcome="success",
        task_family="crafting",
        confidence=0.9,
    )

    feedback_path = os.path.join(tmpdir, "skill_memory_quality.json")
    gate_path = os.path.join(tmpdir, "skill_memory_quality_gate.json")
    with open(feedback_path, "w", encoding="utf-8") as f:
        json.dump({
            "skill_memory_quality_feedback": {
                "task_family_counts": {"crafting": 2},
                "hint_quality_items": [
                    {
                        "hint_type": "REUSE",
                        "skill": "supported_torch_skill",
                        "task_family": "crafting",
                        "count": 2,
                        "labels": {"reuse_supported_by_goal_success": 2},
                    }
                ],
                "policy_hints": [
                    {
                        "skill_memory_policy": "candidate_promote_reuse_hints",
                        "priority": "low",
                        "count": 2,
                    }
                ],
            }
        }, f)
    with open(gate_path, "w", encoding="utf-8") as f:
        json.dump({
            "readiness": "approved",
            "decision": "allow_supported_reuse_skill_memory_promotion",
            "reason": "localized REUSE hints are repeatedly supported",
            "approved_count": 1,
            "review_count": 0,
            "rejected_count": 0,
        }, f)

    task = BenchmarkTask("BM-Q", "Quality feedback task", "Craft torches", "M1")
    approved_runner = BenchmarkRunner(Config(
        skill_dir=skill_dir,
        skill_memory_quality_feedback_paths=[feedback_path],
        skill_memory_quality_gate_paths=[gate_path],
    ))
    approved = approved_runner.run_skill_memory_quality_preflight(tasks=[task])

    assert approved["ready"]
    assert approved["readiness"] == "approved"
    assert approved["gate_approved"]
    assert approved["case_count"] == 1
    assert approved["quality_policy_application_count"] == 1
    assert approved["quality_ablation"]["cases"][0]["task_family"] == "crafting"

    ungated_runner = BenchmarkRunner(Config(
        skill_dir=skill_dir,
        skill_memory_quality_feedback_paths=[feedback_path],
    ))
    ungated = ungated_runner.run_skill_memory_quality_preflight(tasks=[task])

    assert not ungated["ready"]
    assert ungated["readiness"] == "review"
    assert "skill_memory_quality_gate" in ungated["missing"]
    print("PASS: Skill memory quality preflight requires gate and ranking effect")


def test_skill_lifecycle_report_tracks_ready_and_refinement_paths():
    tmpdir = tempfile.mkdtemp()
    skill_dir = os.path.join(tmpdir, "skills")
    skill_library = SkillLibrary(storage_path=skill_dir, persist=True)
    skill_library.create_skill(
        "craft_torch_reliable",
        "Craft torches after confirming coal and sticks are available",
        json.dumps([{"type": "craft", "parameters": {"item": "torch", "count": 4}}]),
        parameters={"count": "int"},
        preconditions={"inventory": {"coal": 1, "stick": 1}},
        postconditions={"inventory": {"torch": 4}},
        required_items=["coal", "stick"],
        dependencies=["craft_item"],
        total_uses=3,
        successful_uses=3,
        success_rate=1.0,
        provenance={"source_log": "fixture", "goal": "Craft torches", "reviewer": "unit_test"},
        gate={
            "decision": "approve",
            "verification": {"status": "achieved"},
            "transfer": {"readiness": "approved"},
        },
    )
    skill_library.record_skill_memory(
        "craft_torch_reliable",
        "Coal plus sticks reliably crafts four torches before cave exploration.",
        memory_type="replay",
        outcome="success",
        task_family="crafting",
        confidence=0.95,
        transfer_gate={"readiness": "approved"},
        evidence={"successes": 3},
    )
    skill_library.create_skill(
        "craft_torch_risky",
        "Craft torches without checking material counts",
        json.dumps([{"type": "craft", "parameters": {"item": "torch"}}]),
        preconditions={},
        postconditions={},
        total_uses=1,
        successful_uses=0,
        success_rate=0.0,
        provenance={"source_log": "fixture", "goal": "Craft torches"},
        gate={"transfer": {"readiness": "review"}},
    )
    skill_library.record_skill_memory(
        "craft_torch_risky",
        "The skill failed when coal was missing; it needs a material check or fallback.",
        memory_type="failure",
        outcome="failure",
        task_family="crafting",
        confidence=0.9,
        transfer_gate={"readiness": "review"},
        evidence={"failures": 1},
    )

    runner = BenchmarkRunner(Config(skill_dir=skill_dir))
    report = runner.run_skill_lifecycle_report(
        skill_storage_path=skill_dir,
        goal="Craft torches before cave exploration",
        task_family="crafting",
        include_builtins=False,
        limit=10,
    )
    by_name = {skill["name"]: skill for skill in report["skills"]}

    assert report["skill_count"] == 2
    assert report["custom_skill_count"] == 2
    assert report["ready_count"] == 1
    assert report["review_count"] == 1
    assert report["blocked_count"] == 0
    assert report["runtime_default_candidate_count"] == 1
    assert report["stage_counts"]["creation_ready"] == 2
    assert report["stage_counts"]["memory_ready"] == 2
    assert report["stage_counts"]["management_ready"] == 2
    assert report["stage_counts"]["evaluation_ready"] == 2
    assert report["stage_counts"]["refinement_ready"] == 1
    assert by_name["craft_torch_reliable"]["readiness"] == "ready"
    assert by_name["craft_torch_reliable"]["runtime_default_candidate"]
    assert "candidate_runtime_default_for_matching_family" in by_name["craft_torch_reliable"]["recommendations"]
    assert by_name["craft_torch_risky"]["readiness"] == "review"
    assert "unresolved_failure_memory" in by_name["craft_torch_risky"]["issues"]
    assert "missing_postconditions" in by_name["craft_torch_risky"]["issues"]
    assert "refine_skill_or_add_failure_correction" in by_name["craft_torch_risky"]["recommendations"]
    assert "convert_failure_heavy_skills_into_refinement_or_failure_correction_candidates" in report["policy_hints"]
    assert "consider_task_family_runtime_default_candidates_after_gate_review" in report["policy_hints"]
    print("PASS: Skill lifecycle report tracks ready and refinement paths")


def test_skill_runtime_default_gate_requires_lifecycle_transfer_and_quality():
    tmpdir = tempfile.mkdtemp()
    skill_dir = os.path.join(tmpdir, "skills")
    skill_library = SkillLibrary(storage_path=skill_dir, persist=True)
    skill_library.create_skill(
        "craft_torch_reliable",
        "Craft torches after confirming coal and sticks are available",
        json.dumps([{"type": "craft", "parameters": {"item": "torch", "count": 4}}]),
        parameters={"count": "int"},
        preconditions={"inventory": {"coal": 1, "stick": 1}},
        postconditions={"inventory": {"torch": 4}},
        required_items=["coal", "stick"],
        dependencies=["craft_item"],
        total_uses=3,
        successful_uses=3,
        success_rate=1.0,
        provenance={"source_log": "fixture", "goal": "Craft torches", "reviewer": "unit_test"},
        gate={
            "decision": "approve",
            "verification": {"status": "achieved"},
            "transfer": {"readiness": "approved"},
        },
    )
    skill_library.record_skill_memory(
        "craft_torch_reliable",
        "Coal plus sticks reliably crafts four torches before cave exploration.",
        memory_type="replay",
        outcome="success",
        task_family="crafting",
        confidence=0.95,
        transfer_gate={"readiness": "approved"},
        evidence={"successes": 3},
    )

    runner = BenchmarkRunner(Config(skill_dir=skill_dir))
    lifecycle = runner.run_skill_lifecycle_report(
        skill_storage_path=skill_dir,
        goal="Craft torches before cave exploration",
        task_family="crafting",
        include_builtins=False,
        limit=10,
    )
    transfer_gate = runner.build_task_stream_transfer_gate(
        transfer_reports=[{
            "stream_count": 1,
            "ready_stream_count": 1,
            "task_count": 3,
            "reuse_expected_tag_count": 3,
            "reuse_hit_tag_count": 3,
            "reuse_coverage": 1.0,
            "average_plasticity_gain": 0.2,
            "average_stability_gain": 0.0,
            "average_generalization_gain": 0.1,
            "interference_count": 0,
            "errors": [],
        }],
        target="skill:craft_torch_reliable",
    )
    quality_gate = {
        "readiness": "approved",
        "decision": "allow_supported_reuse_skill_memory_promotion",
        "reason": "localized REUSE hints are supported",
        "approved_count": 1,
        "review_count": 0,
        "rejected_count": 0,
        "candidates": [{
            "skill": "craft_torch_reliable",
            "task_family": "crafting",
            "readiness": "approved",
            "supported_reuse_count": 3,
            "conflicting_reuse_count": 0,
        }],
    }
    approved = runner.build_skill_runtime_default_gate(
        lifecycle_reports=[lifecycle],
        transfer_gates=[transfer_gate],
        quality_gates=[quality_gate],
        target_task_family="crafting",
        require_quality_gate=True,
    )

    assert approved["readiness"] == "approved"
    assert approved["decision"] == "allow_task_family_runtime_default_skills"
    assert approved["approved_candidate_count"] == 1
    candidate = approved["candidates"][0]
    assert candidate["skill"] == "craft_torch_reliable"
    assert candidate["candidate_readiness"] == "approved"
    assert candidate["quality_readiness"] == "approved"
    assert "scope_runtime_default_skill_to_task_family" in approved["policy_hints"]

    missing_transfer = runner.build_skill_runtime_default_gate(
        lifecycle_reports=[lifecycle],
        target_task_family="crafting",
    )
    assert missing_transfer["readiness"] == "review"
    assert "task_stream_transfer_gate" in missing_transfer["missing"]

    rejected_quality = runner.build_skill_runtime_default_gate(
        lifecycle_reports=[lifecycle],
        transfer_gates=[transfer_gate],
        quality_gates=[{
            **quality_gate,
            "readiness": "rejected",
            "decision": "do_not_promote_skill_memory",
            "rejected_count": 1,
            "approved_count": 0,
            "candidates": [{
                "skill": "craft_torch_reliable",
                "task_family": "crafting",
                "readiness": "rejected",
                "supported_reuse_count": 1,
                "conflicting_reuse_count": 1,
            }],
        }],
        target_task_family="crafting",
        require_quality_gate=True,
    )
    assert rejected_quality["readiness"] == "rejected"
    assert rejected_quality["decision"] == "do_not_enable_runtime_default_skills"
    assert rejected_quality["rejected_candidate_count"] == 1
    print("PASS: Skill runtime default gate requires lifecycle, transfer, and quality evidence")


def test_skill_runtime_default_preflight_requires_approved_family_coverage():
    tmpdir = tempfile.mkdtemp()
    skill_dir = os.path.join(tmpdir, "skills")

    def write_gate(filename, task_family="crafting", readiness="approved", candidate_readiness="approved"):
        approved = 1 if candidate_readiness == "approved" else 0
        review = 1 if candidate_readiness == "review" else 0
        rejected = 1 if candidate_readiness == "rejected" else 0
        path = os.path.join(tmpdir, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "type": "skill_runtime_default_gate",
                "target_task_family": task_family,
                "readiness": readiness,
                "decision": (
                    "allow_task_family_runtime_default_skills"
                    if readiness == "approved"
                    else "do_not_enable_runtime_default_skills"
                ),
                "reason": f"{readiness} runtime-default fixture",
                "candidate_count": 1,
                "approved_candidate_count": approved,
                "review_candidate_count": review,
                "rejected_candidate_count": rejected,
                "candidates": [{
                    "skill": f"{task_family or 'general'}_fixture_skill",
                    "task_family": task_family,
                    "candidate_readiness": candidate_readiness,
                    "decision": (
                        "allow_task_family_runtime_default"
                        if candidate_readiness == "approved"
                        else "do_not_enable_runtime_default_skill"
                    ),
                    "reason": "",
                    "lifecycle_ready": candidate_readiness == "approved",
                    "runtime_default_candidate": candidate_readiness == "approved",
                    "quality_readiness": "approved",
                }],
            }, f, indent=2)
        return path

    no_gate = BenchmarkRunner(Config(skill_dir=skill_dir)).run_skill_runtime_default_preflight(
        suite="m1",
        gate_paths=[],
    )
    assert no_gate["ready"]
    assert no_gate["readiness"] == "not_required"
    assert no_gate["decision"] == "skip_skill_runtime_default_preflight"

    approved_path = write_gate("approved_crafting_gate.json", task_family="crafting")
    approved_runner = BenchmarkRunner(Config(
        skill_dir=skill_dir,
        skill_runtime_default_gate_paths=[approved_path],
    ))
    approved = approved_runner.run_skill_runtime_default_preflight(suite="m1")
    assert approved["ready"]
    assert approved["readiness"] == "approved"
    assert approved["decision"] == "allow_skill_runtime_default_benchmark"
    assert approved["gate_approved"]
    assert approved["approved_candidate_count"] == 1
    assert "crafting" in approved["benchmark_task_families"]
    assert "crafting" in approved["approved_task_families"]
    assert "crafting" in approved["covered_task_families"]
    assert approved["family_overlap_count"] >= 1

    no_overlap_path = write_gate("approved_redstone_gate.json", task_family="redstone")
    no_overlap_runner = BenchmarkRunner(Config(
        skill_dir=skill_dir,
        skill_runtime_default_gate_paths=[no_overlap_path],
    ))
    no_overlap = no_overlap_runner.run_skill_runtime_default_preflight(suite="m1")
    assert not no_overlap["ready"]
    assert no_overlap["readiness"] == "review"
    assert no_overlap["decision"] == "hold_skill_runtime_default_benchmark"
    assert "benchmark_task_family_overlap" in no_overlap["missing"]
    assert no_overlap["family_overlap_count"] == 0

    rejected_path = write_gate(
        "rejected_crafting_gate.json",
        task_family="crafting",
        readiness="rejected",
        candidate_readiness="rejected",
    )
    rejected_runner = BenchmarkRunner(Config(
        skill_dir=skill_dir,
        skill_runtime_default_gate_paths=[rejected_path],
    ))
    rejected = rejected_runner.run_skill_runtime_default_preflight(suite="m1")
    assert not rejected["ready"]
    assert rejected["readiness"] == "rejected"
    assert rejected["decision"] == "block_skill_runtime_default_benchmark"
    print("PASS: Skill runtime default preflight requires approved task-family coverage")


def test_runtime_profile_suite_preflight_requires_approved_suite_coverage():
    tmpdir = tempfile.mkdtemp()
    profile_path = os.path.join(tmpdir, "m1_profile.json")
    approved_suite_path = os.path.join(tmpdir, "runtime_profile_suite_approved.json")
    review_suite_path = os.path.join(tmpdir, "runtime_profile_suite_review.json")
    with open(profile_path, "w", encoding="utf-8") as f:
        json.dump({"type": "runtime_profile", "name": "m1_safe_profile"}, f)
    with open(approved_suite_path, "w", encoding="utf-8") as f:
        json.dump({
            "type": "runtime_profile_suite_report",
            "readiness": "approved",
            "decision": "allow_runtime_profile_suite",
            "reason": "fixture suite approved",
            "profile_count": 1,
            "approved_profile_count": 1,
            "required_profiles": ["m1"],
            "missing_required_profiles": [],
            "profiles": [{
                "path": profile_path,
                "name": "m1_safe_profile",
                "readiness": "approved",
            }],
        }, f)
    with open(review_suite_path, "w", encoding="utf-8") as f:
        json.dump({
            "type": "runtime_profile_suite_report",
            "readiness": "review",
            "decision": "hold_runtime_profile_suite",
            "reason": "m2 is missing",
            "profile_count": 1,
            "approved_profile_count": 1,
            "missing_required_profiles": ["m2"],
            "profiles": [{
                "path": profile_path,
                "name": "m1_safe_profile",
                "readiness": "approved",
            }],
        }, f)

    runner = BenchmarkRunner(Config())
    skipped = runner.run_runtime_profile_suite_preflight(suite="m1")
    assert skipped["ready"]
    assert skipped["readiness"] == "not_required"

    missing = runner.run_runtime_profile_suite_preflight(
        suite="m1",
        profile_paths=[profile_path],
        suite_report_paths=[],
    )
    assert not missing["ready"]
    assert missing["readiness"] == "review"
    assert "runtime_profile_suite_report" in missing["missing"]

    approved = runner.run_runtime_profile_suite_preflight(
        suite="m1",
        profile_paths=[profile_path],
        suite_report_paths=[approved_suite_path],
    )
    assert approved["ready"]
    assert approved["readiness"] == "approved"
    assert approved["decision"] == "allow_runtime_profile_benchmark"
    assert approved["covered_profile_paths"] == [profile_path]
    assert approved["covered_required_profiles"] == ["m1"]

    m7_missing = runner.run_runtime_profile_suite_preflight(
        suite="m7",
        profile_paths=[profile_path],
        suite_report_paths=[approved_suite_path],
    )
    assert not m7_missing["ready"]
    assert m7_missing["readiness"] == "review"
    assert m7_missing["required_profiles"] == ["m7"]
    assert m7_missing["missing_required_profiles"] == ["m7"]

    review = runner.run_runtime_profile_suite_preflight(
        suite="m1",
        profile_paths=[profile_path],
        suite_report_paths=[review_suite_path],
        required_profiles=["m1", "m2"],
    )
    assert not review["ready"]
    assert review["readiness"] == "review"
    assert review["decision"] == "hold_runtime_profile_benchmark"
    assert review["approved_suite_report_count"] == 0
    print("PASS: Runtime profile suite preflight requires approved suite coverage")


def test_action_value_transition_preflight_requires_approved_gate_and_evaluator():
    tmpdir = tempfile.mkdtemp()
    feedback_path = os.path.join(tmpdir, "action_value_feedback.json")
    gate_path = os.path.join(tmpdir, "action_value_transition_gate.json")
    evaluator_path = os.path.join(tmpdir, "action_value_transition_evaluator.json")
    with open(feedback_path, "w", encoding="utf-8") as f:
        json.dump({
            "action_value_feedback": {
                "action_value_items": [
                    {
                        "signature": "dig:coal_ore",
                        "action_type": "dig",
                        "attempts": 4,
                        "successes": 4,
                        "failures": 0,
                    }
                ],
                "state_transition_value_items": [
                    {
                        "signature": "dig:coal_ore",
                        "action_type": "dig",
                        "attempts": 4,
                        "avg_transition_value_score": 0.82,
                        "avg_transition_confidence": 1.0,
                        "low_confidence_transitions": 0,
                    }
                ],
            }
        }, f)
    with open(gate_path, "w", encoding="utf-8") as f:
        json.dump({
            "readiness": "approved",
            "decision": "approve",
            "reason": "trusted transition values are ready",
            "trusted_item_count": 1,
            "trusted_transition_count": 4,
            "low_confidence_rate": 0.0,
        }, f)
    with open(evaluator_path, "w", encoding="utf-8") as f:
        json.dump({
            "readiness": "approved",
            "decision": "approve_comparison",
            "reason": "state-grounded evaluator agrees",
            "evaluated_count": 2,
            "agreement_rate": 1.0,
            "avg_abs_score_delta": 0.02,
        }, f)

    approved_runner = BenchmarkRunner(Config(
        action_value_feedback_paths=[feedback_path],
        action_value_transition_gate_paths=[gate_path],
        action_value_transition_evaluator_report_paths=[evaluator_path],
    ))
    approved = approved_runner.run_action_value_transition_preflight(
        suite="m1",
        require_evaluator_report=True,
    )

    assert approved["ready"]
    assert approved["readiness"] == "approved"
    assert approved["transition_item_count"] == 1
    assert approved["trusted_transition_item_count"] == 1
    assert approved["transition_gate_approved"]
    assert approved["transition_evaluator_approved"]

    ungated_runner = BenchmarkRunner(Config(
        action_value_feedback_paths=[feedback_path],
    ))
    ungated = ungated_runner.run_action_value_transition_preflight(
        suite="m1",
        require_evaluator_report=True,
    )

    assert not ungated["ready"]
    assert ungated["readiness"] == "review"
    assert "action_value_transition_gate" in ungated["missing"]
    assert "action_value_transition_evaluator_report" in ungated["missing"]
    print("PASS: Action value transition preflight requires approved gate and evaluator")


def test_visual_action_benchmark_ablation_compares_live_suite_modes():
    class FakeVisualActionBenchmarkRunner(BenchmarkRunner):
        def _run_task_with_config(self, task, config):
            if config.enable_visual_action_grounding:
                return BenchmarkResult(
                    task.id,
                    task.name,
                    "pass",
                    duration_s=3.0,
                    inventory_snapshot={"raw_iron": 1},
                    intervention_metrics={
                        "visual_action_intervention_count": 2,
                        "visual_action_intervention_phases": {
                            "prepend_approach": 1,
                            "fill_coordinates": 1,
                        },
                    },
                    session_log_path="visual_enabled.jsonl",
                )
            return BenchmarkResult(
                task.id,
                task.name,
                "pass",
                duration_s=4.0,
                inventory_snapshot={},
                intervention_metrics={"visual_action_intervention_count": 0},
                session_log_path="visual_disabled.jsonl",
            )

    tmpdir = tempfile.mkdtemp()
    runner = FakeVisualActionBenchmarkRunner(Config(), output_dir=tmpdir)
    task = BenchmarkTask("BM-VIS", "Visual action task", "Mine iron ore", "M1")
    report = runner.run_visual_action_benchmark_ablation(tasks=[task])
    runner.save_visual_action_benchmark_ablation_report(report, "visual_report.json")

    with open(os.path.join(tmpdir, "visual_report.json"), "r", encoding="utf-8") as f:
        data = json.load(f)

    assert report.disabled_passed_count == 1
    assert report.enabled_passed_count == 1
    assert report.changed_count == 1
    assert report.helped_count == 1
    case = report.cases[0]
    assert case.enabled_visual_actions == 2
    assert case.enabled_phases["prepend_approach"] == 1
    assert case.enabled_changed
    assert data["cases"][0]["enabled_visual_actions"] == 2
    assert data["changed_count"] == 1
    print("PASS: Visual action benchmark ablation compares live suite modes")


def test_mixed_policy_benchmark_ablation_compares_live_patch_modes():
    tmpdir = tempfile.mkdtemp()
    patch_path = os.path.join(tmpdir, "mixed_policy_patch.json")
    with open(patch_path, "w", encoding="utf-8") as f:
        json.dump({
            "action_policy_feedback": {
                "policy_hints": [
                    {
                        "action_type": "place",
                        "preferred_control": "consider_low_level_visual_control",
                        "reason": "visual_or_precision_sensitive",
                    }
                ]
            },
            "mixed_initiative_feedback": {
                "policy_hints": [
                    {
                        "policy": "inspect_backend_execution",
                        "template_id": "craft_or_process_item",
                        "priority": "high",
                    }
                ]
            },
            "template_policy_updates": [
                {"target_id": "craft_or_process_item", "decision": "inspect_backend_execution"}
            ],
        }, f)

    def write_action_log(name, preferred_control, fallback_reason=""):
        path = os.path.join(tmpdir, name)
        control_policy = {
            "action_type": "place",
            "backend": "mineflayer",
            "preferred_backend": "desktop" if preferred_control == "consider_low_level_visual_control" else "mineflayer",
            "preferred_control": preferred_control,
            "reason": "visual_or_precision_sensitive" if preferred_control == "consider_low_level_visual_control" else "default_backend",
        }
        if fallback_reason:
            control_policy["fallback_reason"] = fallback_reason
        event = {
            "type": "action",
            "data": {
                "action": {"type": "place", "parameters": {"item": "torch"}},
                "result": {
                    "success": True,
                    "action_type": "place",
                    "backend": "mineflayer",
                    "control_policy": control_policy,
                },
            },
        }
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
        return path

    class FakeMixedPolicyBenchmarkRunner(BenchmarkRunner):
        def _run_task_with_config(self, task, config):
            patched = bool(config.mixed_policy_patch_paths)
            log_path = write_action_log(
                "patched.jsonl" if patched else "baseline.jsonl",
                "consider_low_level_visual_control" if patched else "mineflayer_api_ok",
                "preferred backend desktop is not enabled" if patched else "",
            )
            return BenchmarkResult(
                task.id,
                task.name,
                "pass",
                duration_s=3.0 if patched else 4.0,
                inventory_snapshot={"torch": 1},
                session_log_path=log_path,
            )

    runner = FakeMixedPolicyBenchmarkRunner(Config(), output_dir=tmpdir)
    task = BenchmarkTask("BM-MIX", "Mixed policy task", "Place a torch", "M1")
    report = runner.run_mixed_policy_benchmark_ablation(patch_paths=[patch_path], tasks=[task])
    runner.save_mixed_policy_benchmark_ablation_report(report, "mixed_policy_report.json")

    with open(os.path.join(tmpdir, "mixed_policy_report.json"), "r", encoding="utf-8") as f:
        data = json.load(f)

    assert report.baseline_passed_count == 1
    assert report.patched_passed_count == 1
    assert report.changed_count == 1
    assert report.control_changed_count == 1
    assert report.policy_decision_report["action_changed_count"] == 1
    assert report.policy_decision_report["template_changed_count"] == 1
    case = report.cases[0]
    assert case.patched_control_policy["preferred_control_counts"]["consider_low_level_visual_control"] == 1
    assert case.patched_control_policy["fallback_count"] == 1
    assert data["control_changed_count"] == 1
    assert data["cases"][0]["patched_control_policy"]["fallback_count"] == 1
    print("PASS: Mixed policy benchmark ablation compares live patch modes")


def test_scheduling_ablation_report_compares_causal_switch():
    runner = BenchmarkRunner(Config())
    report = runner.run_scheduling_ablation()
    first_case = next(case for case in report.cases if case.case_id == "AB-SCHED-001")

    assert report.changed_count >= 1
    assert report.helped_count >= 1
    assert first_case.direct_only_task == "Explore surroundings"
    assert first_case.causal_enabled_task == "Craft torches from remembered coal opportunity"
    assert first_case.causal_helped
    print("PASS: Scheduling ablation report compares causal scheduling switch")


def test_scheduling_ablation_replays_session_logs():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session_replay.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Craft torches"}},
        {"type": "observation", "data": {"inventory": {"stick": 1, "coal": 1}, "position": {"x": 0, "z": 0}, "nearby_blocks": [], "nearby_entities": []}},
        {"type": "action", "data": {"action": {"type": "move_to", "parameters": {"x": 4, "z": 4}}, "result": {"success": True}}},
        {"type": "observation", "data": {"inventory": {"stick": 1, "coal": 1}, "position": {"x": 4, "z": 4}, "nearby_blocks": [], "nearby_entities": []}},
        {"type": "observation", "data": {"inventory": {"stick": 1, "coal": 1}, "nearby_blocks": [], "nearby_entities": []}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "torch"}}, "result": {"success": True, "item": "torch"}}},
        {"type": "observation", "data": {"inventory": {"stick": 0, "coal": 0, "torch": 4}, "nearby_blocks": [], "nearby_entities": []}},
        {"type": "observation", "data": {"inventory": {"stick": 1, "coal": 1, "torch": 4}, "nearby_blocks": [], "nearby_entities": []}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "torch"}}, "result": {"success": True, "item": "torch"}}},
        {"type": "observation", "data": {"inventory": {"stick": 0, "coal": 0, "torch": 8}, "nearby_blocks": [], "nearby_entities": []}},
        {"type": "observation", "data": {"inventory": {"stick": 1}, "nearby_blocks": [], "nearby_entities": []}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "torch"}}, "result": {"success": False, "error": "Missing coal"}}},
        {"type": "observation", "data": {"inventory": {"stick": 1}, "nearby_blocks": [], "nearby_entities": []}},
        {"type": "goal_end", "data": {"goal": "Craft torches", "result": {"completed": False}}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    runner = BenchmarkRunner(Config())
    report = runner.run_scheduling_ablation_from_logs([session_path], max_cases_per_log=10)

    assert len(report.cases) == 2
    assert report.changed_count == 2
    assert report.helped_count == 2
    assert {case.outcome for case in report.cases} == {"success", "failure"}
    assert all(case.action_type == "craft" for case in report.cases)
    assert all(case.value_score >= 0.55 for case in report.cases)
    assert all(case.source == session_path for case in report.cases)
    success_case = next(case for case in report.cases if case.outcome == "success")
    failure_case = next(case for case in report.cases if case.outcome == "failure")
    assert success_case.repeat_count == 2
    assert failure_case.repeat_count == 1
    assert "(2x)" in success_case.case_name
    assert "(2x)" in success_case.causal_enabled_task
    assert success_case.avg_value_score >= 0.55
    print("PASS: Scheduling ablation replays successful and failed session logs")


def test_coach_style_ablation_compares_curriculum_styles():
    runner = BenchmarkRunner(Config())
    report = runner.run_coach_style_ablation(styles=["safe", "explorer"])

    explorer_case = next(
        case for case in report.cases
        if case.case_id == "AB-COACH-001" and case.style == "explorer"
    )

    assert report.changed_count >= 1
    assert report.score_changed_count >= 1
    assert explorer_case.changed
    assert explorer_case.baseline_goal != explorer_case.styled_goal
    assert explorer_case.styled_goal.startswith("Explore east frontier cell")
    assert any(reason.startswith("coach:explorer") for reason in explorer_case.styled_reasons)
    assert explorer_case.baseline_candidates
    assert explorer_case.styled_candidates

    tmpdir = tempfile.mkdtemp()
    case_path = os.path.join(tmpdir, "coach_cases.json")
    with open(case_path, "w", encoding="utf-8") as f:
        json.dump({
            "cases": [{
                "id": "FILE-COACH-001",
                "name": "case file frontier preference",
                "fallback_goal": "Explore surroundings",
                "styles": ["explorer"],
                "observation": {
                    "health": 20,
                    "time_of_day": 4000,
                    "inventory": {"crafting_table": 1, "wooden_pickaxe": 1, "oak_log": 4},
                    "nearby_entities": [],
                },
                "world_model_feedback": {
                    "suggested_goals": ["Explore north frontier cell (0,-1)"],
                    "frontiers": [{"cell": {"x": 0, "z": -1}, "direction": "north"}],
                },
            }]
        }, f)

    loaded = runner.load_coach_style_ablation_cases([case_path])
    file_report = runner.run_coach_style_ablation(cases=loaded)

    assert len(loaded) == 1
    assert file_report.cases[0].source == case_path
    assert file_report.cases[0].style == "explorer"
    assert file_report.cases[0].styled_goal.startswith("Explore north frontier cell")
    print("PASS: Coach style ablation compares curriculum styles and case files")


def test_coach_style_gate_controls_style_readiness():
    runner = BenchmarkRunner(Config())
    ablation = runner.run_coach_style_ablation(styles=["safe", "explorer"])
    payload = {
        "changed_count": ablation.changed_count,
        "score_changed_count": ablation.score_changed_count,
        "cases": [asdict(case) for case in ablation.cases],
    }

    approved = runner.build_coach_style_gate(
        coach_ablation_reports=[payload],
        styles=["explorer"],
        min_cases_per_style=1,
        min_score_changed_per_style=1,
    )
    review = runner.build_coach_style_gate(
        coach_ablation_reports=[payload],
        styles=["safe"],
        min_cases_per_style=1,
        min_score_changed_per_style=1,
        require_goal_change=True,
    )

    assert approved["readiness"] == "approved"
    assert approved["decision"] == "allow_coach_style"
    assert approved["approved_styles"] == ["explorer"]
    assert "styles_ready_for_benchmark_preflight" in approved["policy_hints"]
    assert review["readiness"] == "review"
    assert review["decision"] == "hold_coach_style"
    assert review["review_styles"][0]["style"] == "safe"
    assert "goal_change" in review["review_styles"][0]["missing"]
    assert "keep_coach_style_manual_or_review_only" in review["policy_hints"]
    print("PASS: Coach style gate controls style readiness")


def test_coach_style_preflight_requires_gate_and_ablation_effect():
    tmpdir = tempfile.mkdtemp()
    runner = BenchmarkRunner(Config())
    ablation = runner.run_coach_style_ablation(styles=["explorer"])
    ablation_payload = {
        "changed_count": ablation.changed_count,
        "score_changed_count": ablation.score_changed_count,
        "cases": [asdict(case) for case in ablation.cases],
    }
    gate_payload = runner.build_coach_style_gate(
        coach_ablation_reports=[ablation_payload],
        styles=["explorer"],
    )
    ablation_path = os.path.join(tmpdir, "coach_style_ablation.json")
    gate_path = os.path.join(tmpdir, "coach_style_gate.json")
    with open(ablation_path, "w", encoding="utf-8") as f:
        json.dump(ablation_payload, f)
    with open(gate_path, "w", encoding="utf-8") as f:
        json.dump(gate_payload, f)

    approved_runner = BenchmarkRunner(Config(
        coach_style="explorer",
        coach_style_ablation_paths=[ablation_path],
        coach_style_gate_paths=[gate_path],
    ))
    approved = approved_runner.run_coach_style_preflight(suite="m1")

    assert approved["ready"]
    assert approved["readiness"] == "approved"
    assert approved["decision"] == "allow_coach_style_benchmark"
    assert approved["gate_approved"]
    assert approved["approved_styles"] == ["explorer"]
    assert approved["case_count"] == len(ablation.cases)
    assert approved["score_changed_count"] >= 1

    ungated_runner = BenchmarkRunner(Config(
        coach_style="explorer",
        coach_style_ablation_paths=[ablation_path],
    ))
    ungated = ungated_runner.run_coach_style_preflight(suite="m1")

    assert not ungated["ready"]
    assert ungated["readiness"] == "review"
    assert "coach_style_gate" in ungated["missing"]
    assert "approved_coach_style_gate" in ungated["missing"]
    print("PASS: Coach style preflight requires gate and ablation effect")


if __name__ == "__main__":
    test_preflight_report_without_network()
    test_bot_session_preflight_check()
    test_preflight_uses_configured_bridge_endpoint()
    test_preflight_report_save_is_explicitly_non_capability_evidence()
    test_preflight_checks_screenshot_renderer_dependencies()
    test_screenshot_smoke_test_verifies_local_image_file()
    test_screenshot_smoke_test_explains_container_file_visibility()
    test_ingest_successful_benchmark_results()
    test_ingest_aggregates_promotion_validation_reports()
    test_ingest_uses_promotion_critic_for_unknown_reports()
    test_promotion_review_ablation_compares_visual_evidence()
    test_goal_verification_ablation_compares_visual_evidence()
    test_goal_verification_critic_gate_controls_runtime_use()
    test_promotion_review_ablation_ignores_unverified_screenshot_paths()
    test_goal_verification_ablation_ignores_unverified_screenshot_paths()
    test_review_label_template_generates_promotion_and_goal_records()
    test_review_label_validate_checks_readiness_and_screenshots()
    test_visual_review_pipeline_runs_trace_validation_and_ablations()
    test_visual_trace_report_counts_visual_coverage()
    test_visual_trace_report_validates_screenshot_files()
    test_exploration_trace_report_counts_open_world_coverage()
    test_world_model_report_builds_cells_frontiers_and_hotspots()
    test_world_model_feedback_gate_requires_structured_map_evidence()
    test_self_evolution_report_tracks_progress_and_stagnation()
    test_self_evolution_report_flags_zero_action_blocked_plan_failure()
    test_plan_action_compliance_report_tracks_plan_following_gaps()
    test_plan_act_latency_report_counts_interrupt_opportunities()
    test_plan_act_latency_report_extracts_collab_role_logs_and_overlap()
    test_plan_act_latency_gate_requires_candidate_and_verifier_evidence()
    test_plan_act_latency_gate_approves_reduced_stale_without_verifier_regression()
    test_plan_act_latency_gate_rejects_verifier_regression()
    test_terminal_commitment_report_separates_world_completion_from_reporting()
    test_action_verification_report_replays_logged_actions()
    test_action_candidate_report_replays_repairable_rejected_actions()
    test_action_value_report_aggregates_outcome_profiles()
    test_knowledge_correction_report_mines_failed_actions_and_dependencies()
    test_task_precondition_report_mines_hidden_prerequisites_from_failures()
    test_task_precondition_gate_requires_ready_candidates()
    test_knowledge_correction_preflight_requires_gate_and_suite_overlap()
    test_knowledge_correction_ablation_reports_context_changes()
    test_knowledge_correction_review_labels_emit_approved_feedback()
    test_action_value_report_uses_embedded_action_observation_windows()
    test_action_value_report_flags_shared_transition_windows()
    test_action_value_transition_gate_controls_runtime_feedback()
    test_action_value_transition_evaluator_compares_state_grounded_labels()
    test_self_evolution_gate_requires_verifier_and_counterexamples()
    test_self_evolution_counterexample_report_blocks_plan_repair_gate()
    test_discovery_application_report_tracks_hypothesis_to_application_loop()
    test_discovery_skill_gate_controls_experiment_derived_skill_promotion()
    test_task_stream_transfer_gate_controls_skill_promotion_path()
    test_action_abstraction_report_counts_backend_mapping_and_low_level_candidates()
    test_memory_policy_report_counts_write_read_manage_gaps_and_feedback()
    test_memory_attribution_report_labels_retrieval_outcomes_without_raw_queries()
    test_memory_attribution_gate_controls_weighted_retrieval_profile()
    test_memory_lifecycle_policy_uses_task_stream_transfer_gate()
    test_bounded_context_report_audits_typed_planner_context()
    test_bounded_context_report_rejects_incomplete_task_capsule()
    test_bounded_context_report_allows_empty_task_capsule()
    test_bounded_context_gate_controls_planner_contract()
    test_task_continuity_lineage_ablation_isolates_failed_branches()
    test_task_continuity_restoration_report_rejects_state_rollback()
    test_task_continuity_restoration_gate_allows_shadow_only()
    test_continual_learning_report_aggregates_open_ended_axes()
    test_continual_learning_report_accepts_flat_session_log_fields()
    test_task_stream_transfer_report_scores_controlled_reuse()
    test_seed_minecraft_task_stream_specs_are_gate_ready()
    test_task_stream_transfer_gate_controls_promotion()
    test_ingest_queues_repeated_causal_summary_candidate()
    test_ingest_queues_failure_correction_candidate()
    test_benchmark_results_persist_intervention_metrics()
    test_visual_action_ablation_compares_enabled_and_disabled_modes()
    test_visual_action_ablation_replays_session_log_interventions()
    test_policy_skill_ablation_compares_enabled_and_disabled_modes()
    test_skill_frontier_routing_ablation_uses_fixed_task_intervals()
    test_policy_skill_ablation_loads_cases_from_skill_library()
    test_policy_skill_benchmark_ablation_compares_live_suite_modes()
    test_skill_memory_benchmark_ablation_compares_policy_only_baseline()
    test_skill_memory_quality_report_labels_typed_hint_outcomes()
    test_skill_memory_quality_gate_controls_reuse_promotion()
    test_skill_memory_quality_preflight_requires_gate_and_ranking_effect()
    test_skill_lifecycle_report_tracks_ready_and_refinement_paths()
    test_skill_runtime_default_gate_requires_lifecycle_transfer_and_quality()
    test_skill_runtime_default_preflight_requires_approved_family_coverage()
    test_runtime_profile_suite_preflight_requires_approved_suite_coverage()
    test_action_value_transition_preflight_requires_approved_gate_and_evaluator()
    test_visual_action_benchmark_ablation_compares_live_suite_modes()
    test_mixed_policy_benchmark_ablation_compares_live_patch_modes()
    test_scheduling_ablation_report_compares_causal_switch()
    test_scheduling_ablation_replays_session_logs()
    test_coach_style_ablation_compares_curriculum_styles()
    test_coach_style_gate_controls_style_readiness()
    test_coach_style_preflight_requires_gate_and_ablation_effect()
    print("\nBenchmark preflight tests PASSED")
