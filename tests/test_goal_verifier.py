"""Unit tests for deterministic Minecraft goal self-verification."""
import json
import os
import sys
import tempfile

sys.path.insert(0, "src")

from singularity.core.agent import Agent
from singularity.core.config import Config
from singularity.core.goal_verifier import GoalVerificationCritic, GoalVerifier, VerifierAnchor
from singularity.core.skill_library import SkillLibrary
from singularity.logging.session_logger import SessionLogger


class FakeMemory:
    def __init__(self):
        self.events = []

    def write_episode(self, event_type, data):
        self.events.append({"type": event_type, "data": data})


class FakeSessionLogger:
    def __init__(self):
        self.events = []

    def log(self, event_type, data, level="INFO"):
        self.events.append({"type": event_type, "data": data, "level": level})


class FakeCriticLLM:
    def __init__(self, response: dict):
        self.response = response
        self.messages = []

    def chat(self, messages, response_format=None):
        self.messages.append({"messages": messages, "response_format": response_format})
        return json.dumps(self.response)


def make_agent():
    agent = object.__new__(Agent)
    agent.config = Config()
    agent.goal_verifier = GoalVerifier()
    agent.memory = FakeMemory()
    agent.session_logger = FakeSessionLogger()
    return agent


def test_goal_verifier_rejects_incomplete_inventory_goal():
    verifier = GoalVerifier()

    result = verifier.verify("Gather 6 oak logs", {"inventory": {"oak_log": 3}})

    assert not result.achieved
    assert result.status == "failed"
    assert "need 6 oak_log, have 3" in result.missing
    print("PASS: GoalVerifier rejects incomplete inventory target")


def test_goal_verifier_accepts_completed_crafting_goal():
    verifier = GoalVerifier()

    result = verifier.verify("Craft crafting table", {"inventory": {"crafting_table": 1}})

    assert result.achieved
    assert result.status == "achieved"
    assert "inventory:crafting_table" in result.matched_rules
    print("PASS: GoalVerifier accepts completed crafting target")


def test_goal_verifier_uses_recipe_generated_anchor():
    verifier = GoalVerifier()

    result = verifier.verify("Craft shield", {"inventory": {"shield": 1}})
    missing = verifier.verify("Craft shield", {"inventory": {"oak_planks": 6, "iron_ingot": 1}})

    assert result.achieved
    assert "anchor:recipe" in result.matched_rules
    assert not missing.achieved
    assert "need 1 shield, have 0" in missing.missing
    print("PASS: GoalVerifier uses recipe-generated verifier anchor")


def test_goal_verifier_uses_resource_drop_generated_anchor():
    verifier = GoalVerifier()

    result = verifier.verify("Mine diamond ore", {"inventory": {"diamond": 1}})

    assert result.achieved
    assert "anchor:resource_drop" in result.matched_rules
    assert result.target_inventory["diamond"] == 1
    print("PASS: GoalVerifier uses resource-drop verifier anchor")


def test_goal_verifier_anchor_verbs_prevent_resource_false_match():
    verifier = GoalVerifier()

    result = verifier.verify("Craft stone pickaxe", {"inventory": {"stone_pickaxe": 1}})

    assert result.achieved
    assert "inventory:stone_pickaxe" in result.matched_rules
    assert all("cobblestone" not in missing for missing in result.missing)
    print("PASS: GoalVerifier anchor verbs prevent resource false match")


def test_goal_verifier_uses_world_safety_evidence():
    verifier = GoalVerifier()

    result = verifier.verify(
        "Attack nearest hostile mob",
        {"nearby_entities": [{"type": "zombie", "hostile": True, "distance": 12}]},
    )

    assert result.achieved
    assert "no hostile mob within 8 blocks" in result.evidence
    print("PASS: GoalVerifier uses hostile-distance evidence")


def test_goal_verifier_treats_resource_shelter_purpose_as_nonbinding():
    verifier = GoalVerifier()

    completed = verifier.verify(
        "Gather 6 oak logs for tools and shelter",
        {"inventory": {"oak_log": 6}},
    )
    incomplete = verifier.verify(
        "Gather 6 oak logs to prepare shelter",
        {"inventory": {"oak_log": 5}},
    )

    assert completed.achieved
    assert completed.matched_rules == [
        "inventory:oak_log",
        "anchor:manual",
        "intent:shelter_purpose_phrase",
    ]
    assert "shelter mention is a non-binding purpose phrase" in completed.evidence
    assert "world:shelter" not in completed.matched_rules
    assert not incomplete.achieved
    assert incomplete.missing == ["need 6 oak_log, have 5"]
    assert "intent:shelter_purpose_phrase" in incomplete.matched_rules
    print("PASS: GoalVerifier keeps shelter purpose phrases non-binding for resource goals")


def test_goal_verifier_preserves_explicit_shelter_requirements():
    verifier = GoalVerifier()
    observation = {"inventory": {"oak_log": 6}}

    conjunctive = verifier.verify("Gather 6 oak logs and build shelter", observation)
    followup = verifier.verify("Gather 6 oak logs for tools; then build shelter", observation)
    shelter = verifier.verify("Build verified shelter before nightfall", observation)

    for result in (conjunctive, followup, shelter):
        assert not result.achieved
        assert "world:shelter" in result.matched_rules
        assert "no shelter flag, structure, or sufficient placed-block evidence" in result.missing
        assert "intent:shelter_purpose_phrase" not in result.matched_rules
    print("PASS: GoalVerifier preserves explicit shelter and compound-goal requirements")


def test_agent_accepts_probe_1_resource_goal_after_machine_inventory_target():
    agent = make_agent()

    accepted, verification = agent._accept_plan_completion(
        "Gather 6 oak logs for tools and shelter",
        {"inventory": {"oak_log": 6}},
        {"status": "complete", "reasoning": "Machine inventory reached the requested count"},
        {"phase": "probe_1_reproduction"},
    )

    assert accepted
    assert verification.achieved
    assert agent.memory.events[-1]["data"]["context"]["acceptance_reason"] == "deterministic_evidence_satisfied"
    assert "intent:shelter_purpose_phrase" in verification.matched_rules
    print("PASS: Agent accepts the Probe 1 resource root once machine inventory reaches six logs")


def test_goal_verifier_accepts_custom_anchor():
    verifier = GoalVerifier(
        anchors=[
            VerifierAnchor(
                canonical="campfire",
                phrases=["campfire"],
                inventory_items=["campfire"],
                verbs=["craft", "obtain"],
                source="test_anchor",
            )
        ],
        use_knowledge_base=False,
    )

    result = verifier.verify("Craft campfire", {"inventory": {"campfire": 1}})

    assert result.achieved
    assert "anchor:test_anchor" in result.matched_rules
    print("PASS: GoalVerifier accepts caller-provided verifier anchor")


def test_goal_verifier_mines_skill_postcondition_anchor():
    skills = SkillLibrary(persist=False)
    skills.create_skill(
        "build_campfire",
        "Build campfire for a safe base",
        "place campfire",
        postconditions={"inventory": {"campfire": 1}},
    )
    verifier = GoalVerifier(skill_library=skills, use_knowledge_base=False)

    result = verifier.verify("Build campfire", {"inventory": {"campfire": 1}})

    assert result.achieved
    assert "anchor:skill_postcondition" in result.matched_rules
    assert result.target_inventory["campfire"] == 1
    print("PASS: GoalVerifier mines skill postcondition verifier anchor")


def test_skill_description_cannot_add_unrelated_inventory_targets():
    skills = SkillLibrary(persist=False)
    skills.create_skill(
        "learned_craft_wooden_pickaxe",
        "Craft one wooden pickaxe at an observed, placed crafting table.",
        "{}",
        skill_id="learned:craft_wooden_pickaxe",
        status="advisory",
        postconditions={"inventory": {"wooden_pickaxe": 1}},
    )
    verifier = GoalVerifier(skill_library=skills, use_knowledge_base=False)

    result = verifier.verify("Craft a crafting table", {"inventory": {"crafting_table": 1}})

    assert result.achieved
    assert result.target_inventory == {"crafting_table": 1}
    assert "inventory:wooden_pickaxe" not in result.matched_rules
    print("PASS: skill descriptions cannot contaminate unrelated inventory verification targets")


def test_goal_verifier_records_inventory_delta_evidence():
    verifier = GoalVerifier()

    result = verifier.verify(
        "Craft shield",
        {"inventory": {"shield": 1}},
        recent_actions=[{
            "action": {"type": "craft", "parameters": {"item": "shield"}},
            "result": {"success": True},
            "before_observation": {"inventory": {"shield": 0}},
            "after_observation": {"inventory": {"shield": 1}},
        }],
    )

    assert result.achieved
    assert result.inventory_delta["shield"] == 1
    assert any("inventory delta gained 1 shield" in item for item in result.evidence)
    print("PASS: GoalVerifier records before/after inventory delta evidence")


def test_goal_verifier_unknown_goal_uses_critic_visual_evidence():
    critic_llm = FakeCriticLLM({
        "decision": "achieved",
        "confidence": 0.84,
        "reason": "visual evidence confirms the sealed base entrance",
        "evidence": ["screenshot summary shows the entrance is sealed"],
        "matched_rules": ["visual_state_claim"],
    })
    verifier = GoalVerifier(
        use_knowledge_base=False,
        goal_critic=GoalVerificationCritic(critic_llm),
    )

    result = verifier.verify(
        "Confirm base entrance is sealed",
        {
            "screenshot_path": "logs/screens/base_sealed.png",
            "visual_analysis": "The base entrance is sealed with planks and no gap is visible.",
            "nearby_blocks": [{"name": "oak_planks", "distance": 1}],
        },
    )

    assert result.achieved
    assert result.status == "achieved"
    assert result.confidence == 0.84
    assert "goal_critic" in result.matched_rules
    assert result.critic["decision"] == "achieved"
    prompt = critic_llm.messages[0]["messages"][1]["content"]
    assert "base_sealed.png" in prompt
    assert critic_llm.messages[0]["response_format"] == {"type": "json_object"}
    print("PASS: GoalVerifier unknown goals can use visual critic evidence")


def test_agent_completion_gate_rejects_false_complete():
    agent = make_agent()

    accepted, verification = agent._accept_plan_completion(
        "Gather 6 oak logs",
        {"inventory": {"oak_log": 3}},
        {"status": "complete", "reasoning": "Rule planner thinks enough logs"},
        {"phase": "planner_complete"},
    )

    assert not accepted
    assert verification.status == "failed"
    assert agent.memory.events[-1]["type"] == "goal_verification"
    assert agent.memory.events[-1]["data"]["context"]["acceptance_reason"] == "deterministic_evidence_missing"
    print("PASS: Agent completion gate rejects false complete")


def test_agent_completion_gate_accepts_unknown_goal_with_audit_trail():
    agent = make_agent()

    accepted, verification = agent._accept_plan_completion(
        "Organize inventory for later mining",
        {"inventory": {"cobblestone": 3}},
        {"status": "complete", "reasoning": "No deterministic postcondition exists"},
        {"phase": "planner_complete"},
    )

    assert accepted
    assert verification.status == "unknown"
    assert agent.session_logger.events[-1]["data"]["context"]["acceptance_reason"] == "no_deterministic_rule_matched"
    print("PASS: Agent completion gate preserves unknown goals with audit trail")


def test_agent_completion_gate_rejects_unknown_goal_when_critic_rejects():
    agent = make_agent()
    critic_llm = FakeCriticLLM({
        "decision": "failed",
        "confidence": 0.9,
        "reason": "visual evidence does not show a sealed entrance",
        "missing": ["base entrance is still open"],
        "matched_rules": ["visual_state_claim"],
    })
    agent.goal_verifier = GoalVerifier(
        use_knowledge_base=False,
        goal_critic=GoalVerificationCritic(critic_llm),
    )

    accepted, verification = agent._accept_plan_completion(
        "Confirm base entrance is sealed",
        {
            "screenshot_path": "logs/screens/base_open.png",
            "visual_analysis": "The base entrance is open.",
        },
        {"status": "complete", "reasoning": "Planner thinks the entrance is sealed"},
        {"phase": "planner_complete"},
    )

    assert not accepted
    assert verification.status == "failed"
    assert "goal_critic" in verification.matched_rules
    assert agent.session_logger.events[-1]["data"]["context"]["acceptance_reason"] == "critic_evidence_missing"
    print("PASS: Agent completion gate rejects unknown goals when critic rejects")


def test_agent_goal_critic_requires_approved_runtime_gate():
    blocked = object.__new__(Agent)
    blocked.config = Config(enable_goal_critic=True)
    blocked_report = blocked._evaluate_goal_critic_runtime_gate()

    assert blocked_report["gate_required"]
    assert not blocked_report["gate_approved"]
    assert blocked_report["gate_readiness"] == "review"
    assert "goal_critic_gate" in blocked_report["missing"]

    tmpdir = tempfile.mkdtemp()
    gate_path = os.path.join(tmpdir, "goal_critic_gate.json")
    with open(gate_path, "w", encoding="utf-8") as f:
        json.dump({
            "type": "goal_verification_critic_gate",
            "readiness": "approved",
            "decision": "allow_goal_critic_runtime_use",
            "reason": "fixture",
            "approved_count": 1,
        }, f)

    approved = object.__new__(Agent)
    approved.config = Config(enable_goal_critic=True, goal_critic_gate_paths=[gate_path])
    approved_report = approved._evaluate_goal_critic_runtime_gate()

    assert approved_report["gate_required"]
    assert approved_report["gate_approved"]
    assert approved_report["gate_readiness"] == "approved"
    assert approved_report["gate_reports"][0]["approved_count"] == 1
    print("PASS: Agent goal critic requires approved runtime gate")


def test_session_summary_counts_goal_verification_metrics():
    logger = SessionLogger(log_dir=tempfile.mkdtemp(), session_id="verify-test")
    logger.log("goal_verification", {
        "goal": "Gather 6 oak logs",
        "achieved": False,
        "status": "failed",
        "context": {"accepted": False, "acceptance_reason": "deterministic_evidence_missing"},
    })
    logger.log("goal_verification", {
        "goal": "Organize inventory",
        "achieved": False,
        "status": "unknown",
        "context": {"accepted": True, "acceptance_reason": "no_deterministic_rule_matched"},
    })

    metrics = logger.get_summary()["goal_verification_metrics"]

    assert metrics["count"] == 2
    assert metrics["failed"] == 1
    assert metrics["unknown"] == 1
    assert metrics["accepted"] == 1
    assert metrics["rejected"] == 1
    print("PASS: Session summary counts goal verification metrics")


if __name__ == "__main__":
    test_goal_verifier_rejects_incomplete_inventory_goal()
    test_goal_verifier_accepts_completed_crafting_goal()
    test_goal_verifier_uses_recipe_generated_anchor()
    test_goal_verifier_uses_resource_drop_generated_anchor()
    test_goal_verifier_anchor_verbs_prevent_resource_false_match()
    test_goal_verifier_uses_world_safety_evidence()
    test_goal_verifier_treats_resource_shelter_purpose_as_nonbinding()
    test_goal_verifier_preserves_explicit_shelter_requirements()
    test_agent_accepts_probe_1_resource_goal_after_machine_inventory_target()
    test_goal_verifier_accepts_custom_anchor()
    test_goal_verifier_mines_skill_postcondition_anchor()
    test_skill_description_cannot_add_unrelated_inventory_targets()
    test_goal_verifier_records_inventory_delta_evidence()
    test_goal_verifier_unknown_goal_uses_critic_visual_evidence()
    test_agent_completion_gate_rejects_false_complete()
    test_agent_completion_gate_accepts_unknown_goal_with_audit_trail()
    test_agent_completion_gate_rejects_unknown_goal_when_critic_rejects()
    test_agent_goal_critic_requires_approved_runtime_gate()
    test_session_summary_counts_goal_verification_metrics()
    print("\nGoal verifier tests PASSED")
