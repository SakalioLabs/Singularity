"""Unit tests for benchmark preflight checks."""
import os
import sys
import json
import tempfile

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


class ReadyBridge:
    def __init__(self, config):
        self.config = config
        self.closed = False

    def connect(self):
        return True

    def health(self):
        return {"success": True, "bot_ready": True, "username": self.config.username}

    def disconnect(self):
        self.closed = True


class NotReadyBridge(ReadyBridge):
    def health(self):
        return {
            "success": True,
            "bot_ready": False,
            "mc_host": self.config.host,
            "mc_port": self.config.port,
            "last_error": "connect ECONNREFUSED",
        }


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
    assert "node" in names
    assert "npm" in names
    assert "node_dependencies" in names
    assert all(check.status in {"pass", "warn", "fail"} for check in report.checks)
    actionable = [check for check in report.checks if check.status in {"warn", "fail"}]
    assert all(check.remedy for check in actionable)
    print("PASS: Benchmark preflight report includes local readiness checks")


def test_bot_session_preflight_check():
    ready_runner = BenchmarkRunner(Config(), bridge_factory=ReadyBridge)
    ready = ready_runner._check_bot_session()
    assert ready.status == "pass"

    not_ready_runner = BenchmarkRunner(Config(), bridge_factory=NotReadyBridge)
    not_ready = not_ready_runner._check_bot_session()
    assert not_ready.status == "fail"
    assert "Minecraft server" in not_ready.remedy
    print("PASS: Bot session preflight distinguishes TCP bridge from spawned bot")


def test_preflight_uses_configured_bridge_endpoint():
    class CapturingRunner(BenchmarkRunner):
        def __init__(self, config):
            super().__init__(config)
            self.tcp_checks = []

        def _check_tcp(self, name, host, port, required):
            self.tcp_checks.append((name, host, port, required))
            return PreflightCheck(name, "pass", f"{host}:{port}")

        def _check_bot_session(self):
            return PreflightCheck("bot_session", "pass", "fake")

    config = Config(bot=BotConfig(host="mc.local", port=25570, bridge_host="127.0.0.9", bridge_port=3012))
    runner = CapturingRunner(config)
    report = runner.preflight(check_network=True)

    assert report.ok
    assert ("bot_bridge", "127.0.0.9", 3012, True) in runner.tcp_checks
    assert ("minecraft_server", "mc.local", 25570, True) in runner.tcp_checks
    print("PASS: Benchmark preflight uses configured bridge endpoint")


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
    assert report.promotion_readiness["approved"] == 1
    assert report.promotion_readiness["rejected"] == 1
    assert report.promotion_readiness["unknown"] == 0
    assert report.promotion_decisions["approve"] == 1
    assert report.promotion_decisions["reject"] == 1
    assert report.promotion_statuses["achieved"] == 1
    assert report.promotion_statuses["failed"] == 1

    pending = queue.pending()
    verified_candidate = next(candidate for candidate in pending if candidate.goal == "Craft torches")
    rejected_candidate = next(candidate for candidate in pending if candidate.goal == "Gather 6 oak logs")
    verified_report = verified_candidate.signals["promotion_report"]
    rejected_report = rejected_candidate.signals["promotion_report"]

    assert verified_report["benchmark_task_id"] == "BM-V"
    assert verified_report["reason"] == "verified_postconditions_satisfied"
    assert verified_report["postconditions"]["inventory"]["torch"] == 4
    assert rejected_report["benchmark_task_id"] == "BM-X"
    assert rejected_report["decision"] == "reject"
    assert rejected_report["missing"] == ["need 6 oak_log, have 3"]
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
    assert report.promotion_readiness["approved"] == 1
    assert report.promotion_readiness["unknown"] == 0
    assert report.promotion_statuses["critic_approved"] == 1
    candidate = queue.pending()[0]
    promotion_report = candidate.signals["promotion_report"]
    assert promotion_report["status"] == "critic_approved"
    assert promotion_report["postconditions"]["inventory"]["torch"] == 4
    print("PASS: Benchmark ingestion uses promotion critic for unknown reports")


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
    assert "screenshots" in case.visual_evidence_keys
    assert case.raw_screenshot_count == 1
    assert case.screenshot_count == 1
    assert case.missing_screenshot_count == 0
    assert case.invalid_screenshot_count == 0
    assert case.manual_readiness == "approved"
    assert case.manual_label_source == "manual_fixture"
    assert case.deterministic_readiness == "unknown"
    assert case.api_visual_readiness == "unknown"
    assert case.screenshot_vlm_readiness == "approved"
    assert case.without_visual_readiness == "unknown"
    assert case.with_visual_readiness == "approved"
    assert case.with_visual_status == "critic_approved"
    assert case.visual_helped
    assert not case.api_visual_helped
    assert case.screenshot_vlm_helped
    assert case.screenshot_vlm_added_value
    assert case.deterministic_matches_manual is False
    assert case.api_visual_matches_manual is False
    assert case.screenshot_vlm_matches_manual is True
    assert len(critic_llm.prompts) == 2
    assert "session_visual.png" not in critic_llm.prompts[0]
    assert "session_visual.png" in critic_llm.prompts[1]
    print("PASS: Promotion review ablation compares visual evidence")


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
    assert case.screenshot_vlm_readiness == "unknown"
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
    assert report.promotion_ablation.screenshot_vlm_added_value_count == 1
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
    assert payload["summary"]["promotion_screenshot_vlm_added_value_count"] == 1
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

    assert ready_skill is not None
    assert ready_candidate.review_status == "approved"
    assert ready_candidate.signals["promotion_report"]["discovery_gate"]["readiness"] == "approved"
    assert blocked_skill is None
    assert blocked_candidate.review_status == "rejected"
    blocked_report = blocked_candidate.signals["promotion_report"]
    assert blocked_report["decision"] == "reject"
    assert blocked_report["discovery_gate"]["readiness"] == "review"
    assert blocked_report["reason"] == "discovery_skill_gate_requires_review"
    assert "write_causal_rule_with_provenance_before_skill_promotion" in blocked_report["warnings"]
    print("PASS: Discovery skill gate controls experiment-derived skill promotion")


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

    assert ready_skill is not None
    assert ready_candidate.review_status == "approved"
    ready_report = ready_candidate.signals["promotion_report"]
    assert ready_report["transfer_gate"]["readiness"] == "approved"
    assert ready_skill.gate["transfer"]["readiness"] == "approved"
    governance = skill_library.skill_graph_report()
    ready_node = next(node for node in governance["nodes"] if node["name"] == ready_skill.name)
    assert ready_node["governance"]["transfer_readiness"] == "approved"
    memory_report = skill_library.skill_memory_report("Craft a stone pickaxe", task_family="crafting", limit=0)
    memory_summary = next(summary for summary in memory_report["skills"] if summary["name"] == ready_skill.name)
    assert memory_report["approved_transfer_memory_count"] == 1
    assert memory_summary["memories"][0]["type"] == "promotion_transfer"
    assert memory_summary["memories"][0]["transfer_readiness"] == "approved"
    assert memory_summary["memories"][0]["evidence"]["candidate_id"] == ready_candidate.id

    assert blocked_skill is None
    assert blocked_candidate.review_status == "rejected"
    blocked_report = blocked_candidate.signals["promotion_report"]
    assert blocked_report["decision"] == "reject"
    assert blocked_report["transfer_gate"]["readiness"] == "review"
    assert blocked_report["reason"] == "task_stream_transfer_gate_requires_review"
    assert "held-out generalization gain evidence is missing" in blocked_report["warnings"]
    print("PASS: Task stream transfer gate controls skill promotion path")


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


if __name__ == "__main__":
    test_preflight_report_without_network()
    test_bot_session_preflight_check()
    test_preflight_uses_configured_bridge_endpoint()
    test_preflight_checks_screenshot_renderer_dependencies()
    test_screenshot_smoke_test_verifies_local_image_file()
    test_screenshot_smoke_test_explains_container_file_visibility()
    test_ingest_successful_benchmark_results()
    test_ingest_aggregates_promotion_validation_reports()
    test_ingest_uses_promotion_critic_for_unknown_reports()
    test_promotion_review_ablation_compares_visual_evidence()
    test_goal_verification_ablation_compares_visual_evidence()
    test_promotion_review_ablation_ignores_unverified_screenshot_paths()
    test_goal_verification_ablation_ignores_unverified_screenshot_paths()
    test_review_label_template_generates_promotion_and_goal_records()
    test_review_label_validate_checks_readiness_and_screenshots()
    test_visual_review_pipeline_runs_trace_validation_and_ablations()
    test_visual_trace_report_counts_visual_coverage()
    test_visual_trace_report_validates_screenshot_files()
    test_exploration_trace_report_counts_open_world_coverage()
    test_world_model_report_builds_cells_frontiers_and_hotspots()
    test_self_evolution_report_tracks_progress_and_stagnation()
    test_self_evolution_report_flags_zero_action_blocked_plan_failure()
    test_plan_action_compliance_report_tracks_plan_following_gaps()
    test_terminal_commitment_report_separates_world_completion_from_reporting()
    test_action_verification_report_replays_logged_actions()
    test_action_candidate_report_replays_repairable_rejected_actions()
    test_self_evolution_gate_requires_verifier_and_counterexamples()
    test_discovery_application_report_tracks_hypothesis_to_application_loop()
    test_discovery_skill_gate_controls_experiment_derived_skill_promotion()
    test_task_stream_transfer_gate_controls_skill_promotion_path()
    test_action_abstraction_report_counts_backend_mapping_and_low_level_candidates()
    test_memory_policy_report_counts_write_read_manage_gaps_and_feedback()
    test_memory_lifecycle_policy_uses_task_stream_transfer_gate()
    test_bounded_context_report_audits_typed_planner_context()
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
    test_policy_skill_ablation_loads_cases_from_skill_library()
    test_policy_skill_benchmark_ablation_compares_live_suite_modes()
    test_skill_memory_benchmark_ablation_compares_policy_only_baseline()
    test_skill_memory_quality_report_labels_typed_hint_outcomes()
    test_skill_memory_quality_gate_controls_reuse_promotion()
    test_skill_memory_quality_preflight_requires_gate_and_ranking_effect()
    test_visual_action_benchmark_ablation_compares_live_suite_modes()
    test_mixed_policy_benchmark_ablation_compares_live_patch_modes()
    test_scheduling_ablation_report_compares_causal_switch()
    test_scheduling_ablation_replays_session_logs()
    print("\nBenchmark preflight tests PASSED")
