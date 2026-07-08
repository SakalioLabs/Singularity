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
from singularity.core.skill_extractor import SkillCandidateQueue, SkillPromotionCritic
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
        {"type": "memory_read", "data": {"query": "craft torches"}},
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
    test_action_abstraction_report_counts_backend_mapping_and_low_level_candidates()
    test_memory_policy_report_counts_write_read_manage_gaps_and_feedback()
    test_ingest_queues_repeated_causal_summary_candidate()
    test_ingest_queues_failure_correction_candidate()
    test_benchmark_results_persist_intervention_metrics()
    test_visual_action_ablation_compares_enabled_and_disabled_modes()
    test_visual_action_ablation_replays_session_log_interventions()
    test_policy_skill_ablation_compares_enabled_and_disabled_modes()
    test_policy_skill_ablation_loads_cases_from_skill_library()
    test_policy_skill_benchmark_ablation_compares_live_suite_modes()
    test_visual_action_benchmark_ablation_compares_live_suite_modes()
    test_scheduling_ablation_report_compares_causal_switch()
    test_scheduling_ablation_replays_session_logs()
    print("\nBenchmark preflight tests PASSED")
