"""Unit tests for memory transfer records, task scheduling, and knowledge loading."""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, "src")

from singularity.core.memory import MemorySystem
from singularity.core.config import Config
from singularity.core.planner import Planner
from singularity.core.agent import Agent
from singularity.core.skill_extractor import SkillCandidateQueue, SkillExtractor, SkillPromotionCritic
from singularity.core.skill_library import SkillLibrary
from singularity.core.task_system import TaskStatus, TaskSystem
from singularity.data.knowledge_base import KnowledgeBase
from singularity.vision.action_advisor import VisualActionAdvisor


class MockPlannerLLM:
    def chat(self, messages, response_format=None):
        return json.dumps({
            "status": "planning",
            "reasoning": "Use memory and opportunities to craft tools",
            "subtasks": [
                {
                    "title": "Gather wood",
                    "type": "gathering",
                    "priority": 1,
                    "success_criteria": {"inventory": {"oak_log": 3}},
                    "opportunity_triggers": ["oak_log"],
                    "tags": ["wood", "resource"],
                },
                {
                    "title": "Craft wooden pickaxe",
                    "type": "crafting",
                    "priority": 2,
                    "preconditions": {"inventory": {"oak_planks": 3, "stick": 2}},
                    "depends_on": ["Gather wood"],
                    "opportunity_triggers": ["crafting_table"],
                    "assigned_skill": "craft_tools",
                    "rationale": "Mining stone requires at least a wooden pickaxe",
                },
            ],
            "actions": [{"type": "craft", "parameters": {"item": "oak_planks", "count": 4}}],
        })


class FakePromotionCriticLLM:
    def __init__(self, response: dict):
        self.response = response
        self.messages = []

    def chat(self, messages, response_format=None):
        self.messages.append({"messages": messages, "response_format": response_format})
        return json.dumps(self.response)


class FakeCausalMemory:
    def __init__(self):
        self.queries = []

    def get_causal_opportunity_context(self, query: str = "", current_state: dict = None, limit: int = 5) -> dict:
        self.queries.append(query)
        return {
            "causal_tags": ["coal", "torch"],
            "causal_events": [{
                "id": "evt1",
                "subject": "coal",
                "action_type": "craft",
                "outcome": "success",
                "tags": ["coal", "torch"],
                "why": "coal enabled torch crafting",
            }],
        }


class FakeActionController:
    def __init__(self):
        self.actions = []

    def execute(self, action: dict, observation: dict) -> dict:
        self.actions.append(action)
        result = {"success": True, "action_type": action.get("type")}
        params = action.get("parameters", {})
        if params.get("block"):
            result["block"] = params["block"]
        if params.get("item"):
            result["item"] = params["item"]
        return result


class FakeSessionLogger:
    def __init__(self):
        self.actions = []
        self.observations = []
        self.events = []

    def log(self, event_type: str, data: dict, level: str = "INFO"):
        self.events.append({"type": event_type, "data": data, "level": level})

    def log_action(self, action: dict, result: dict):
        self.actions.append((action, result))

    def log_observation(self, observation: dict):
        self.observations.append(observation)


class FakeMemoryWriter:
    def __init__(self):
        self.episodes = []

    def write_episode(self, event_type: str, data: dict):
        self.episodes.append({"type": event_type, "data": data})


class FakeObserver:
    def __init__(self, observation: dict):
        self.observation = observation

    def observe(self) -> dict:
        return dict(self.observation)


class FakeScreenshotBot:
    def __init__(self):
        self.paths = []

    def capture_screenshot(self, output_path: str = "") -> dict:
        self.paths.append(output_path)
        return {
            "success": True,
            "supported": True,
            "source": "test_renderer",
            "screenshot_path": output_path,
        }


class FakeExplorer:
    def record_position(self, position: dict):
        pass


class FakeRuntime:
    class Decision:
        should_interrupt = False

    def evaluate_interrupt(self, observation: dict, goal: str = "", active_task=None):
        return self.Decision()


def test_knowledge_base_loads_recipes():
    kb = KnowledgeBase()
    assert kb.get_recipe("crafting_table")
    assert kb.can_craft("crafting_table", {"oak_planks": 4})
    print("PASS: KnowledgeBase loads crafting recipes")


def test_knowledge_graph_plans_resources_and_tools():
    kb = KnowledgeBase()
    plan = kb.get_resource_plan("stone_pickaxe", {"oak_log": 1})

    assert kb.graph
    assert kb.graph.neighbors("stone_pickaxe", "requires")
    assert plan["raw_requirements"]["cobblestone"] == 3
    assert plan["missing_raw"]["cobblestone"] == 3
    assert plan["source_blocks"]["cobblestone"] == ["stone"]
    assert kb.required_tool_tier("iron_ore") == 2
    assert kb.recommended_tool_for("iron_ore") == "stone_pickaxe"
    assert not kb.can_mine("iron_ore", {"wooden_pickaxe": 1})
    assert kb.can_mine("iron_ore", {"stone_pickaxe": 1})
    print("PASS: Knowledge graph plans resource gaps and tool requirements")


def test_memory_curates_and_retrieves_transfer_experience():
    memory = MemorySystem(memory_dir=tempfile.mkdtemp(), curated_char_limit=120)
    memory.add_memory(
        "Oak logs near spawn are reliable early-game fuel and planks.",
        tags=["oak_log", "spawn"],
        importance=0.9,
    )
    memory.add_memory(
        "Long low-value note that should fit only if there is enough room.",
        tags=["noise"],
        importance=0.1,
    )
    curated = memory.curate_entries()
    assert curated[0].tags == ["oak_log", "spawn"]

    memory.record_experience(
        goal="Craft a wooden pickaxe",
        task="Convert logs into planks and sticks",
        outcome="wooden_pickaxe crafted",
        actions=[{"type": "craft", "parameters": {"item": "oak_planks"}}],
        dimensions={
            "structure": "log -> planks -> sticks -> tool",
            "process": "craft intermediate materials before tool",
        },
        causal={"which": "craft planks first", "why": "sticks require planks"},
        tags=["wooden_pickaxe", "crafting"],
        success=True,
    )
    matches = memory.retrieve_relevant_experiences("Need wooden pickaxe from logs")
    assert matches
    assert matches[0].task == "Convert logs into planks and sticks"
    print("PASS: Memory retrieves transferable experience")


def test_memory_tracks_recall_diversity_for_consolidation():
    tmpdir = tempfile.mkdtemp()
    memory = MemorySystem(memory_dir=tmpdir)
    entry = memory.add_memory(
        "Coal near cave mouths is a high-value torch opportunity before night.",
        tags=["coal", "torch", "night"],
        importance=0.9,
        confidence=0.9,
    )

    assert memory.get_relevant_memory("coal torch before night")
    assert memory.get_relevant_memory("safe light from cave coal")
    assert entry.uses == 2
    assert len(entry.recall_queries) == 2

    record = memory.record_experience(
        goal="Prepare for night",
        task="Craft torches from found coal",
        outcome="torches crafted before hostile spawn",
        tags=["coal", "torch", "night"],
        success=True,
        causal={"which": "craft torches", "why": "coal plus sticks creates safe light"},
    )
    memory.retrieve_relevant_experiences("craft torches before night")
    memory.retrieve_relevant_experiences("safe light with coal and sticks")
    assert record.uses == 2
    assert len(record.recall_queries) == 2

    candidates = memory.memory_consolidation_candidates(
        min_score=0.45,
        min_recall_count=2,
        min_unique_queries=2,
    )
    kinds = {candidate["kind"] for candidate in candidates}
    assert "memory_entry" in kinds
    assert "experience_record" in kinds

    reloaded = MemorySystem(memory_dir=tmpdir)
    reloaded_entry = next(iter(reloaded.entries.values()))
    reloaded_record = next(iter(reloaded.experiences.values()))
    assert reloaded_entry.uses == 2
    assert len(reloaded_entry.recall_queries) == 2
    assert reloaded_record.uses == 2
    assert len(reloaded_record.recall_queries) == 2
    print("PASS: Memory tracks recall diversity for consolidation")


def test_memory_persists_entries_and_experiences():
    tmpdir = tempfile.mkdtemp()
    memory = MemorySystem(memory_dir=tmpdir)
    memory.add_memory("A crafting table enables wooden pickaxe crafting.", tags=["crafting_table"], importance=0.8)
    memory.record_experience(
        goal="Craft wooden pickaxe",
        task="Craft wooden pickaxe",
        outcome="completed",
        tags=["wooden_pickaxe"],
        success=True,
        causal={"which": "craft", "why": "recipe chain satisfied"},
    )

    reloaded = MemorySystem(memory_dir=tmpdir)
    assert reloaded.get_relevant_memory("crafting table")
    assert reloaded.retrieve_relevant_experiences("wooden pickaxe")
    print("PASS: Memory persists entries and experiences")


def test_memory_records_and_retrieves_causal_events():
    tmpdir = tempfile.mkdtemp()
    memory = MemorySystem(memory_dir=tmpdir)
    move = memory.record_causal_transition(
        {"inventory": {"oak_log": 1}, "position": {"x": 0, "y": 66, "z": 0}},
        {"type": "move_to", "parameters": {"x": 4, "z": 4}},
        {"success": True, "action_type": "move_to"},
        {"inventory": {"oak_log": 1}, "position": {"x": 4, "y": 66, "z": 4}},
        goal="Craft a wooden pickaxe",
    )
    event = memory.record_causal_transition(
        {
            "inventory": {"oak_log": 1},
            "nearby_blocks": [{"name": "oak_log"}],
            "position": {"x": 0, "y": 66, "z": 0},
        },
        {"type": "craft", "parameters": {"item": "oak_planks", "count": 4}},
        {"success": True, "item": "oak_planks", "action_type": "craft"},
        {
            "inventory": {"oak_log": 0, "oak_planks": 4},
            "nearby_blocks": [{"name": "crafting_table"}],
            "position": {"x": 0, "y": 66, "z": 0},
        },
        goal="Craft a wooden pickaxe",
        task="Convert logs to planks",
    )
    duplicate = memory.record_causal_transition(
        {
            "inventory": {"oak_log": 2, "oak_planks": 4},
            "nearby_blocks": [{"name": "oak_log"}],
            "position": {"x": 1, "y": 66, "z": 0},
        },
        {"type": "craft", "parameters": {"item": "oak_planks", "count": 4}},
        {"success": True, "item": "oak_planks", "action_type": "craft"},
        {
            "inventory": {"oak_log": 1, "oak_planks": 8},
            "nearby_blocks": [{"name": "crafting_table"}],
            "position": {"x": 1, "y": 66, "z": 0},
        },
        goal="Craft a wooden pickaxe",
        task="Convert logs to planks",
    )

    assert event.outcome == "success"
    assert duplicate.summary_key() == event.summary_key()
    assert move.value_score < 0.55
    assert event.value_score >= 0.55
    assert event.evidence["effects"]["inventory_delta"]["oak_planks"] == 4
    assert memory.retrieve_causal_events("Need oak planks for crafting")
    assert "Causal:" in memory.get_relevant_memory("oak planks")
    context = memory.get_causal_opportunity_context("move oak planks", {}, limit=10)
    assert "oak_planks" in context["causal_tags"]
    assert all(item["action_type"] != "move_to" for item in context["causal_events"])
    craft_summaries = [item for item in context["causal_events"] if item["action_type"] == "craft"]
    assert len(craft_summaries) == 1
    assert craft_summaries[0]["repeat_count"] == 2
    assert len(craft_summaries[0]["event_ids"]) == 2
    assert craft_summaries[0]["avg_value_score"] >= 0.55

    reloaded = MemorySystem(memory_dir=tmpdir)
    matches = reloaded.retrieve_causal_events("oak_planks")
    assert matches
    assert matches[0].subject == "oak_planks"
    print("PASS: Memory records and retrieves causal events")


def test_task_system_dependency_and_opportunity_scheduler():
    tasks = TaskSystem()
    gather = tasks.create_task(
        "Gather wood",
        status=TaskStatus.COMPLETED,
        priority=2,
        success_criteria={"inventory": {"oak_log": 3}},
    )
    craft = tasks.create_task(
        "Craft wooden pickaxe",
        status=TaskStatus.ACCEPTED,
        priority=3,
        depends_on=[gather.id],
        preconditions={"inventory": {"oak_planks": 3, "stick": 2}},
        opportunity_triggers=["crafting_table"],
    )
    urgent = tasks.create_task(
        "Build shelter before night",
        status=TaskStatus.ACCEPTED,
        priority=2,
        deadline=time.time() + 60,
    )

    world = {
        "inventory": {"oak_planks": 3, "stick": 2},
        "nearby_blocks": [{"name": "crafting_table"}],
    }
    next_task = tasks.get_next_task(world)
    assert next_task.id in {craft.id, urgent.id}
    assert craft in tasks.get_ready_tasks(world)
    print(f"PASS: Task scheduler selected {next_task.title}")


def test_task_system_uses_causal_opportunity_tags():
    tasks = TaskSystem()
    tasks.create_task(
        "Explore for resources",
        status=TaskStatus.ACCEPTED,
        priority=3,
    )
    torch_task = tasks.create_task(
        "Craft torches from remembered coal opportunity",
        status=TaskStatus.ACCEPTED,
        priority=3,
        preconditions={"inventory": {"stick": 1}},
        opportunity_triggers=["coal"],
    )

    next_task = tasks.get_next_task({
        "inventory": {"stick": 1},
        "nearby_blocks": [],
        "causal_tags": ["coal", "torch"],
    })

    assert next_task.id == torch_task.id
    print("PASS: TaskSystem uses causal opportunity tags")


def test_task_system_can_disable_causal_opportunity_scoring():
    tasks = TaskSystem(use_causal_opportunities=False)
    explore = tasks.create_task(
        "Explore for resources",
        status=TaskStatus.ACCEPTED,
        priority=3,
    )
    tasks.create_task(
        "Craft torches from remembered coal opportunity",
        status=TaskStatus.ACCEPTED,
        priority=3,
        preconditions={"inventory": {"stick": 1}},
        opportunity_triggers=["coal"],
    )

    next_task = tasks.get_next_task({
        "inventory": {"stick": 1},
        "nearby_blocks": [],
        "causal_tags": ["coal", "torch"],
    })

    assert next_task.id == explore.id
    print("PASS: TaskSystem can disable causal opportunity scoring")


def test_task_system_updates_state_from_action_success():
    tasks = TaskSystem()
    task = tasks.create_task(
        "Craft torches",
        status=TaskStatus.ACCEPTED,
        success_criteria={"inventory": {"torch": 4}},
    )

    updated = tasks.apply_action_result(
        {"type": "craft", "parameters": {"item": "torch", "count": 4}},
        {"success": True, "item": "torch"},
        {"inventory": {"torch": 4}, "health": 20},
    )

    assert updated.id == task.id
    assert task.status == TaskStatus.COMPLETED
    assert task.result["completed_by"] == "action_result"
    print("PASS: TaskSystem completes tasks from action result evidence")


def test_task_system_updates_state_from_action_failure():
    tasks = TaskSystem()
    task = tasks.create_task(
        "Craft pickaxe",
        status=TaskStatus.ACCEPTED,
        failure_criteria={"max_failures": 2},
    )

    tasks.apply_action_result(
        {"type": "craft", "parameters": {"item": "wooden_pickaxe"}},
        {"success": False, "error": "Missing materials"},
        {"inventory": {}},
    )
    assert task.status == TaskStatus.ACTIVE
    assert task.attempts == 1

    tasks.apply_action_result(
        {"type": "craft", "parameters": {"item": "wooden_pickaxe"}},
        {"success": False, "error": "Still missing materials"},
        {"inventory": {}},
    )
    assert task.status == TaskStatus.FAILED
    assert task.attempts == 2
    print("PASS: TaskSystem fails tasks from repeated action failures")


def test_agent_autonomous_goal_selects_ready_opportunity_task():
    agent = object.__new__(Agent)
    agent.task_system = TaskSystem()
    agent.task_system.create_task(
        "Craft torches while coal is nearby",
        status=TaskStatus.PROPOSED,
        priority=3,
        preconditions={"inventory": {"coal": 1, "stick": 1}},
        opportunity_triggers=["coal"],
    )
    agent._accept_planned_tasks()
    goal = agent._select_autonomous_goal(
        {"inventory": {"coal": 1, "stick": 2}, "nearby_blocks": [{"name": "coal_ore"}]},
        "Explore surroundings",
    )
    assert goal == "Craft torches while coal is nearby"
    print("PASS: Agent autonomous selector chooses ready opportunity task")


def test_agent_autonomous_goal_uses_causal_memory_context():
    agent = object.__new__(Agent)
    agent.task_system = TaskSystem()
    memory = FakeCausalMemory()
    agent.memory = memory
    agent.task_system.create_task(
        "Craft torches from causal memory",
        status=TaskStatus.PROPOSED,
        priority=3,
        preconditions={"inventory": {"stick": 1}},
        opportunity_triggers=["coal"],
    )
    agent._accept_planned_tasks()
    goal = agent._select_autonomous_goal(
        {"inventory": {"stick": 1}, "nearby_blocks": [], "nearby_entities": []},
        "Explore surroundings",
    )
    assert goal == "Craft torches from causal memory"
    assert "coal" in memory.queries[-1]
    print("PASS: Agent autonomous selector uses causal memory context")


def test_planner_preserves_task_scheduling_hints():
    tasks = TaskSystem()
    planner = Planner(MockPlannerLLM(), tasks)
    plan = planner.plan_from_goal("Craft a wooden pickaxe", {"inventory": {"oak_log": 3}})

    assert plan["status"] == "planning"
    created = list(tasks.tasks.values())
    assert len(created) == 2
    pickaxe = next(t for t in created if t.title == "Craft wooden pickaxe")
    gather = next(t for t in created if t.title == "Gather wood")
    assert pickaxe.depends_on == [gather.id]
    assert pickaxe.preconditions["inventory"]["stick"] == 2
    assert pickaxe.opportunity_triggers == ["crafting_table"]
    assert pickaxe.assigned_skill == "craft_tools"
    print("PASS: Planner preserves dependency and opportunity hints")


def test_planner_prompt_includes_knowledge_graph_summary():
    planner = Planner(MockPlannerLLM(), TaskSystem())
    prompt = planner._planner_system_prompt()
    assert "Knowledge Graph:" in prompt
    assert "iron_ore drops raw_iron" in prompt
    assert "stone_pickaxe raw needs" in prompt
    print("PASS: Planner prompt includes knowledge graph summary")


def test_skill_extractor_creates_experience_atom_and_skill():
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "session.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Craft a crafting table"}},
        {"type": "observation", "data": {"inventory": {"oak_log": 1}, "nearby_blocks": [], "nearby_entities": []}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "oak_planks", "count": 4}}, "result": {"success": True}}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "crafting_table"}}, "result": {"success": True}}},
        {"type": "goal_end", "data": {"goal": "Craft a crafting table", "result": {"completed": True}}},
    ]
    with open(path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    memory = MemorySystem(memory_dir=tmpdir)
    skills = SkillLibrary()
    extractor = SkillExtractor(skills, memory)

    score = extractor.consolidation_score(path)
    assert score["should_promote"]
    created = extractor.extract_from_session(path)
    atoms = extractor.extract_experience_atoms(path)

    assert created
    assert atoms
    assert atoms[0].goal == "Craft a crafting table"
    assert memory.retrieve_relevant_experiences("crafting table")
    assert memory.retrieve_causal_events("crafting_table")
    print("PASS: SkillExtractor creates promoted skill and experience atom")


def test_skill_extractor_review_gate():
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "session.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Craft sticks"}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "oak_planks"}}, "result": {"success": True}}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "stick"}}, "result": {"success": True}}},
        {"type": "goal_end", "data": {"result": {"completed": True}}},
    ]
    with open(path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    skills = SkillLibrary()
    extractor = SkillExtractor(skills, auto_promote=False)
    candidates = extractor.extract_skill_candidates(path)
    created = extractor.extract_from_session(path)

    assert candidates
    assert not created
    assert skills.get_skill(candidates[0].name) is None
    approved = extractor.approve_candidate(candidates[0])
    assert approved.name == candidates[0].name
    print("PASS: SkillExtractor review gate holds candidates until approval")


def test_skill_candidate_queue_persists_and_approves_custom_skill():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session.jsonl")
    queue_path = os.path.join(tmpdir, "skill_candidates.jsonl")
    skill_dir = os.path.join(tmpdir, "skills")
    events = [
        {"type": "goal_start", "data": {"goal": "Craft torches"}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "stick"}}, "result": {"success": True}}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "torch"}}, "result": {"success": True}}},
        {"type": "goal_end", "data": {"result": {"completed": True}}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    extractor = SkillExtractor(SkillLibrary(storage_path=skill_dir), auto_promote=False)
    candidate = extractor.extract_skill_candidates(session_path)[0]
    queue = SkillCandidateQueue(queue_path)
    queue.enqueue(candidate)

    reloaded_queue = SkillCandidateQueue(queue_path)
    assert reloaded_queue.pending()[0].id == candidate.id

    durable_skills = SkillLibrary(storage_path=skill_dir, persist=True)
    approved = reloaded_queue.approve(candidate.id, durable_skills)
    assert approved and approved.review_status == "approved"

    reloaded_skills = SkillLibrary(storage_path=skill_dir, persist=True)
    assert reloaded_skills.get_skill(candidate.name)
    print("PASS: Skill candidate queue persists and approves custom skill")


def test_skill_candidate_approval_writes_verified_postconditions():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "verified_session.jsonl")
    events = [
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
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    skills = SkillLibrary(storage_path=os.path.join(tmpdir, "skills"))
    extractor = SkillExtractor(skills, auto_promote=False)
    candidate = extractor.extract_skill_candidates(session_path)[0]
    skill = extractor.approve_candidate(candidate)

    assert skill
    assert skill.postconditions["inventory"]["torch"] == 4
    assert candidate.review_status == "approved"
    assert candidate.signals["verification_gate"]["status"] == "achieved"
    report = candidate.signals["promotion_report"]
    assert report["decision"] == "approve"
    assert report["reason"] == "verified_postconditions_satisfied"
    assert report["postconditions"]["inventory"]["torch"] == 4
    print("PASS: Skill candidate approval writes verifier-backed postconditions")


def test_skill_candidate_approval_rejects_failed_verification():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "failed_verified_session.jsonl")
    events = [
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
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    skill_dir = os.path.join(tmpdir, "skills")
    queue_path = os.path.join(tmpdir, "skill_candidates.jsonl")
    skills = SkillLibrary(storage_path=skill_dir)
    extractor = SkillExtractor(skills, auto_promote=False)
    candidate = extractor.extract_skill_candidates(session_path)[0]
    queue = SkillCandidateQueue(queue_path)
    queue.enqueue(candidate)
    durable_skills = SkillLibrary(storage_path=skill_dir, persist=True)
    rejected = queue.approve(candidate.id, durable_skills)

    assert rejected and rejected.review_status == "rejected"
    assert "deterministic_evidence_missing" in rejected.reason
    assert rejected.signals["promotion_report"]["decision"] == "reject"
    assert rejected.signals["promotion_report"]["missing"] == ["need 6 oak_log, have 3"]
    assert durable_skills.get_skill(candidate.name) is None
    reloaded_queue = SkillCandidateQueue(queue_path)
    assert reloaded_queue.candidates[candidate.id].review_status == "rejected"
    print("PASS: Skill candidate approval rejects failed verifier evidence")


def test_skill_candidate_validation_report_explains_unknown_gate():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "unknown_verified_session.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Organize mining inventory"}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "stick"}}, "result": {"success": True}}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "torch"}}, "result": {"success": True}}},
        {"type": "goal_end", "data": {"goal": "Organize mining inventory", "result": {"completed": True}}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    skills = SkillLibrary(storage_path=os.path.join(tmpdir, "skills"))
    extractor = SkillExtractor(skills, auto_promote=False)
    candidate = extractor.extract_skill_candidates(session_path)[0]
    report = extractor.validate_candidate_for_promotion(candidate)

    assert report.decision == "approve"
    assert report.status == "unknown"
    assert report.reason == "no_goal_verification_event"
    assert report.warnings
    print("PASS: Skill candidate validation report explains unknown gate")


def test_skill_candidate_unknown_gate_uses_promotion_critic():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "critic_unknown_session.jsonl")
    events = [
        {"type": "goal_start", "data": {"goal": "Organize mining inventory"}},
        {
            "type": "observation",
            "data": {
                "inventory": {"stick": 1, "coal": 1},
                "screenshot_path": "logs/screens/critic_unknown.png",
                "visual_analysis": "Screenshot shows a safe inventory/crafting context with coal and sticks visible.",
                "grounded_resources": [{"name": "coal_ore", "drop": "coal", "can_harvest": True, "distance": 5}],
                "nearby_entities": [{"type": "sheep", "distance": 8, "hostile": False}],
            },
        },
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "stick"}}, "result": {"success": True}}},
        {"type": "action", "data": {"action": {"type": "craft", "parameters": {"item": "torch"}}, "result": {"success": True}}},
        {"type": "goal_end", "data": {"goal": "Organize mining inventory", "result": {"completed": True}}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    critic_llm = FakePromotionCriticLLM({
        "decision": "approve",
        "confidence": 0.82,
        "reason": "trace contains a reusable craft sequence with no failures",
        "evidence": ["two successful crafting actions"],
        "missing": [],
        "matched_rules": ["trace_success_sequence"],
        "postconditions": {"inventory": {"torch": 4}},
        "warnings": [],
    })
    skills = SkillLibrary(storage_path=os.path.join(tmpdir, "skills"))
    extractor = SkillExtractor(
        skills,
        auto_promote=False,
        promotion_critic=SkillPromotionCritic(critic_llm),
    )
    candidate = extractor.extract_skill_candidates(session_path)[0]
    visual = candidate.signals["visual_evidence"]
    assert visual["screenshots"] == ["logs/screens/critic_unknown.png"]
    assert visual["grounded_resources"][0]["name"] == "coal_ore"
    assert "safe inventory" in visual["visual_analysis"][0]
    skill = extractor.approve_candidate(candidate)

    assert skill
    assert skill.postconditions["inventory"]["torch"] == 4
    assert candidate.review_status == "approved"
    report = candidate.signals["promotion_report"]
    assert report["decision"] == "approve"
    assert report["status"] == "critic_approved"
    assert report["reason"] == "critic_approved"
    assert report["critic"]["confidence"] == 0.82
    assert "promotion_critic" in report["matched_rules"]
    assert critic_llm.messages[0]["response_format"] == {"type": "json_object"}
    prompt = critic_llm.messages[0]["messages"][1]["content"]
    assert "visual_evidence" in prompt
    assert "critic_unknown.png" in prompt
    print("PASS: Skill candidate unknown gate uses promotion critic")


def test_skill_extractor_promotes_repeated_causal_summary_candidate():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "session.jsonl")
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

    skills = SkillLibrary(storage_path=os.path.join(tmpdir, "skills"))
    extractor = SkillExtractor(skills, auto_promote=False)
    candidates = extractor.extract_causal_skill_candidates(session_path, min_repeats=3, min_value_score=0.65)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.name == "causal_dig_oak_log"
    assert candidate.signals["source"] == "causal_summary"
    assert candidate.signals["repeat_count"] == 3
    assert candidate.signals["value_score"] >= 0.65
    implementation = json.loads(candidate.implementation)
    assert implementation["action_template"]["type"] == "dig"
    assert implementation["action_template"]["parameters"]["block"] == "oak_log"
    print("PASS: SkillExtractor promotes repeated causal summary candidate")


def test_skill_extractor_promotes_failure_correction_candidate():
    tmpdir = tempfile.mkdtemp()
    session_path = os.path.join(tmpdir, "failure_correction.jsonl")
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
        {"type": "observation", "data": {"inventory": {"torch": 4}, "nearby_blocks": [], "nearby_entities": []}},
        {"type": "goal_end", "data": {"goal": "Craft torches", "result": {"completed": True}}},
    ]
    with open(session_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    skills = SkillLibrary(storage_path=os.path.join(tmpdir, "skills"))
    extractor = SkillExtractor(skills, auto_promote=False)
    candidates = extractor.extract_failure_correction_candidates(session_path)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.name == "correct_craft_torch_via_dig_coal_ore"
    assert candidate.signals["source"] == "failure_correction_summary"
    assert candidate.signals["failure_count"] == 2
    assert candidate.signals["correction_count"] == 2
    assert candidate.signals["primary_correction_action_type"] == "dig"
    assert candidate.signals["primary_correction_subject"] == "coal_ore"
    implementation = json.loads(candidate.implementation)
    assert implementation["avoid_action_template"]["parameters"]["item"] == "torch"
    assert implementation["primary_correction"]["parameters"]["block"] == "coal_ore"
    assert implementation["correction_sequence"][0]["type"] == "dig"
    print("PASS: SkillExtractor promotes failure correction candidate")


def test_skill_library_recommends_policy_skills_and_corrections():
    skills = SkillLibrary()
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

    world_state = {
        "inventory": {"stick": 1},
        "nearby_blocks": [{"name": "coal_ore"}],
        "nearby_entities": [],
    }
    hints = skills.get_policy_skill_hints("Craft torches", world_state)
    match = skills.find_failure_correction(
        {"type": "craft", "parameters": {"item": "torch", "count": 4}},
        {"success": False, "error": "Missing coal"},
        world_state,
    )

    assert hints and "dig:coal_ore" in hints[0]
    assert match
    assert match[0].name == "correct_craft_torch_via_dig_coal_ore"
    print("PASS: SkillLibrary recommends policy skills and corrections")


def test_agent_runs_approved_failure_correction_sequence():
    tmpdir = tempfile.mkdtemp()
    agent = object.__new__(Agent)
    agent.skill_library = SkillLibrary(storage_path=os.path.join(tmpdir, "skills"))
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
    agent.skill_library.create_skill(
        "correct_craft_torch_via_dig_coal_ore",
        "Correct missing coal before crafting torches",
        json.dumps(implementation),
    )
    agent.memory = MemorySystem(memory_dir=os.path.join(tmpdir, "memory"))
    agent.task_system = TaskSystem()
    agent.action_controller = FakeActionController()
    agent.session_logger = FakeSessionLogger()
    agent.observer = FakeObserver({
        "inventory": {"stick": 1, "coal": 1},
        "nearby_blocks": [{"name": "coal_ore"}],
        "nearby_entities": [],
        "position": {},
    })
    agent.explorer = FakeExplorer()
    agent.runtime = FakeRuntime()

    corrected, observation = agent._attempt_failure_correction(
        {"type": "craft", "parameters": {"item": "torch"}},
        {"success": False, "error": "Missing coal"},
        {"inventory": {"stick": 1}, "nearby_blocks": [{"name": "coal_ore"}], "nearby_entities": []},
        "Craft torches",
        {"cycle": 1},
    )

    skill = agent.skill_library.get_skill("correct_craft_torch_via_dig_coal_ore")
    assert corrected
    assert [action["type"] for action in agent.action_controller.actions] == ["dig", "craft"]
    assert observation["inventory"]["coal"] == 1
    assert skill.total_uses == 1
    assert skill.success_rate == 1.0
    phases = [
        event["data"]["phase"] for event in agent.session_logger.events
        if event["type"] == "policy_intervention"
    ]
    assert phases == ["selected", "action", "action", "completed"]
    print("PASS: Agent runs approved failure correction sequence")


def test_agent_loads_reviewed_policy_skills_from_configured_storage():
    tmpdir = tempfile.mkdtemp()
    skill_dir = os.path.join(tmpdir, "skills")
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
    writer = SkillLibrary(storage_path=skill_dir, persist=True)
    writer.create_skill(
        "correct_craft_torch_via_dig_coal_ore",
        "Correct missing coal before crafting torches",
        json.dumps(implementation),
    )

    agent = Agent(Config(
        memory_dir=os.path.join(tmpdir, "memory"),
        log_dir=os.path.join(tmpdir, "logs"),
        skill_dir=skill_dir,
    ))
    match = agent.skill_library.find_failure_correction(
        {"type": "craft", "parameters": {"item": "torch"}},
        {"success": False, "error": "Missing coal"},
        {"nearby_blocks": [{"name": "coal_ore"}], "inventory": {"stick": 1}},
    )

    assert match
    assert match[0].name == "correct_craft_torch_via_dig_coal_ore"
    print("PASS: Agent loads reviewed policy skills from configured storage")


def test_agent_observe_enriches_and_logs_structured_vision():
    agent = object.__new__(Agent)
    agent.config = Config()
    agent.observer = FakeObserver({
        "inventory": {"stone_pickaxe": 1},
        "nearby_blocks": [{"name": "iron_ore", "distance": 8}],
        "nearby_entities": [{"type": "zombie", "hostile": True, "distance": 7}],
        "trees_found": [],
        "position": {"x": 1, "y": 64, "z": 2},
        "health": 20,
    })
    agent.session_logger = FakeSessionLogger()
    from singularity.vision.analyzer import VisionAnalyzer
    from singularity.vision.visual_memory import VisualMemory
    agent.vision_analyzer = VisionAnalyzer()
    agent.visual_memory = VisualMemory()

    observation = agent._observe()

    assert observation["grounded_resources"][0]["name"] == "iron_ore"
    assert observation["grounded_resources"][0]["can_harvest"]
    assert observation["dangers"][0]["type"] == "zombie"
    vision_events = [event for event in agent.session_logger.events if event["type"] == "vision"]
    assert vision_events
    assert vision_events[0]["data"]["grounded_resources"][0]["name"] == "iron_ore"
    assert agent.visual_memory.count() == 1
    print("PASS: Agent observe enriches and logs structured vision")


def test_agent_visual_memory_context_summarizes_recent_evidence():
    agent = object.__new__(Agent)
    from singularity.vision.visual_memory import VisualMemory
    agent.visual_memory = VisualMemory()
    agent.visual_memory.add({
        "grounded_resources": [{"name": "iron_ore", "can_harvest": True}],
        "dangers": [{"type": "zombie", "dist": 6}],
        "visual_analysis": "Iron ore is visible near a tunnel wall.",
    }, "observation")

    context = agent._visual_memory_context("mine iron")

    assert "Recent visual memory" in context
    assert "iron_ore" in context
    assert "zombie" in context
    assert "Iron ore is visible" in context
    print("PASS: Agent visual memory context summarizes recent evidence")


def test_agent_observe_captures_screenshot_for_visual_pipeline():
    tmpdir = tempfile.mkdtemp()
    agent = object.__new__(Agent)
    agent.config = Config(
        enable_screenshot_capture=True,
        screenshot_dir=tmpdir,
        screenshot_min_interval_s=0,
    )
    agent.observer = FakeObserver({
        "inventory": {"stone_pickaxe": 1},
        "nearby_blocks": [{"name": "iron_ore", "distance": 5}],
        "nearby_entities": [],
        "trees_found": [],
        "position": {"x": 0, "y": 64, "z": 0},
        "health": 20,
    })
    agent.bot = FakeScreenshotBot()
    agent.session_logger = FakeSessionLogger()
    from singularity.vision.analyzer import VisionAnalyzer
    from singularity.vision.visual_memory import VisualMemory
    agent.vision_analyzer = VisionAnalyzer()
    agent.visual_memory = VisualMemory()

    observation = agent._observe()

    assert agent.bot.paths
    assert observation["screenshot_path"].startswith(tmpdir)
    assert observation["screenshot_capture"]["source"] == "test_renderer"
    vision_events = [event for event in agent.session_logger.events if event["type"] == "vision"]
    assert vision_events[0]["data"]["screenshot_path"] == observation["screenshot_path"]
    assert agent.visual_memory.get_recent(1)[0]["data"]["screenshot_path"] == observation["screenshot_path"]
    print("PASS: Agent observe captures screenshot for visual pipeline")


def test_agent_visual_action_grounding_fills_missing_dig_coordinates():
    agent = object.__new__(Agent)
    agent.config = Config(enable_visual_action_grounding=True)
    agent.visual_action_advisor = VisualActionAdvisor()
    agent.session_logger = FakeSessionLogger()
    agent.memory = FakeMemoryWriter()

    plan = {
        "status": "in_progress",
        "reasoning": "dig visible ore",
        "actions": [{"type": "dig", "parameters": {}}],
    }
    observation = {
        "grounded_resources": [{
            "name": "iron_ore",
            "can_harvest": True,
            "best_available_tool": "stone_pickaxe",
            "position": {"x": 3, "y": 64, "z": 4},
        }],
    }

    grounded = agent._apply_visual_action_grounding(plan, observation, "mine iron ore")

    assert grounded["actions"][0]["type"] == "look_at"
    assert grounded["actions"][0]["parameters"] == {"x": 3, "y": 64, "z": 4}
    assert grounded["actions"][1]["type"] == "dig"
    assert grounded["actions"][1]["parameters"] == {"x": 3, "y": 64, "z": 4}
    assert "Visual grounding filled action coordinates" in grounded["reasoning"]
    assert "Visual grounding inserted focus action" in grounded["reasoning"]
    interventions = [event for event in agent.session_logger.events if event["type"] == "visual_action_intervention"]
    phases = [event["data"]["phase"] for event in interventions]
    assert "fill_coordinates" in phases
    assert "prepend_focus" in phases
    assert agent.memory.episodes[-1]["type"] == "visual_action_intervention"
    print("PASS: Agent visual action grounding fills missing dig coordinates")


def test_agent_visual_action_grounding_prepends_danger_retreat():
    agent = object.__new__(Agent)
    agent.config = Config(enable_visual_action_grounding=True)
    agent.visual_action_advisor = VisualActionAdvisor(retreat_distance=8)
    agent.session_logger = FakeSessionLogger()
    agent.memory = FakeMemoryWriter()

    plan = {
        "status": "in_progress",
        "reasoning": "keep mining",
        "actions": [{"type": "wait", "parameters": {"ticks": 20}}],
    }
    observation = {
        "position": {"x": 0, "y": 64, "z": 0},
        "nearby_entities": [{
            "type": "zombie",
            "hostile": True,
            "distance": 3,
            "position": {"x": 4, "y": 64, "z": 0},
        }],
    }

    grounded = agent._apply_visual_action_grounding(plan, observation, "mine iron ore")

    assert grounded["actions"][0]["type"] == "move_to"
    assert grounded["actions"][0]["parameters"]["x"] < 0
    assert grounded["actions"][1]["type"] == "wait"
    assert "Visual grounding inserted safety action" in grounded["reasoning"]
    interventions = [event for event in agent.session_logger.events if event["type"] == "visual_action_intervention"]
    assert interventions[-1]["data"]["phase"] == "prepend_danger"
    print("PASS: Agent visual action grounding prepends danger retreat")


def test_agent_visual_action_grounding_prepends_resource_approach():
    agent = object.__new__(Agent)
    agent.config = Config(enable_visual_action_grounding=True)
    agent.visual_action_advisor = VisualActionAdvisor(harvest_reach=4, stand_distance=2)
    agent.session_logger = FakeSessionLogger()
    agent.memory = FakeMemoryWriter()

    plan = {
        "status": "in_progress",
        "reasoning": "mine visible ore",
        "actions": [{"type": "dig", "parameters": {"x": 10, "y": 64, "z": 0}}],
    }
    observation = {
        "position": {"x": 0, "y": 64, "z": 0},
        "grounded_resources": [{
            "name": "iron_ore",
            "can_harvest": True,
            "best_available_tool": "stone_pickaxe",
            "required_tool_tier": 2,
            "position": {"x": 10, "y": 64, "z": 0},
        }],
    }

    grounded = agent._apply_visual_action_grounding(plan, observation, "mine iron ore")

    assert grounded["actions"][0]["type"] == "move_to"
    assert grounded["actions"][0]["parameters"] == {"x": 8.0, "z": 0.0, "y": 64}
    assert grounded["actions"][1]["type"] == "dig"
    assert "Visual grounding inserted approach action" in grounded["reasoning"]
    interventions = [event for event in agent.session_logger.events if event["type"] == "visual_action_intervention"]
    assert interventions[-1]["data"]["phase"] == "prepend_approach"
    print("PASS: Agent visual action grounding prepends resource approach")


def test_agent_visual_action_grounding_prepends_resource_focus():
    agent = object.__new__(Agent)
    agent.config = Config(enable_visual_action_grounding=True)
    agent.visual_action_advisor = VisualActionAdvisor(harvest_reach=4)
    agent.session_logger = FakeSessionLogger()
    agent.memory = FakeMemoryWriter()

    plan = {
        "status": "in_progress",
        "reasoning": "mine visible ore",
        "actions": [{"type": "dig", "parameters": {"x": 3, "y": 64, "z": 0}}],
    }
    observation = {
        "position": {"x": 2, "y": 64, "z": 0},
        "grounded_resources": [{
            "name": "iron_ore",
            "can_harvest": True,
            "best_available_tool": "stone_pickaxe",
            "required_tool_tier": 2,
            "position": {"x": 3, "y": 64, "z": 0},
        }],
    }

    grounded = agent._apply_visual_action_grounding(plan, observation, "mine iron ore")

    assert grounded["actions"][0]["type"] == "look_at"
    assert grounded["actions"][0]["parameters"] == {"x": 3, "y": 64, "z": 0}
    assert grounded["actions"][1]["type"] == "dig"
    assert "Visual grounding inserted focus action" in grounded["reasoning"]
    interventions = [event for event in agent.session_logger.events if event["type"] == "visual_action_intervention"]
    assert interventions[-1]["data"]["phase"] == "prepend_focus"
    print("PASS: Agent visual action grounding prepends resource focus")


if __name__ == "__main__":
    test_knowledge_base_loads_recipes()
    test_knowledge_graph_plans_resources_and_tools()
    test_memory_curates_and_retrieves_transfer_experience()
    test_memory_tracks_recall_diversity_for_consolidation()
    test_memory_persists_entries_and_experiences()
    test_memory_records_and_retrieves_causal_events()
    test_task_system_dependency_and_opportunity_scheduler()
    test_task_system_uses_causal_opportunity_tags()
    test_task_system_can_disable_causal_opportunity_scoring()
    test_task_system_updates_state_from_action_success()
    test_task_system_updates_state_from_action_failure()
    test_agent_autonomous_goal_selects_ready_opportunity_task()
    test_agent_autonomous_goal_uses_causal_memory_context()
    test_planner_preserves_task_scheduling_hints()
    test_planner_prompt_includes_knowledge_graph_summary()
    test_skill_extractor_creates_experience_atom_and_skill()
    test_skill_extractor_review_gate()
    test_skill_candidate_queue_persists_and_approves_custom_skill()
    test_skill_candidate_approval_writes_verified_postconditions()
    test_skill_candidate_approval_rejects_failed_verification()
    test_skill_candidate_validation_report_explains_unknown_gate()
    test_skill_candidate_unknown_gate_uses_promotion_critic()
    test_skill_extractor_promotes_repeated_causal_summary_candidate()
    test_skill_extractor_promotes_failure_correction_candidate()
    test_skill_library_recommends_policy_skills_and_corrections()
    test_agent_runs_approved_failure_correction_sequence()
    test_agent_loads_reviewed_policy_skills_from_configured_storage()
    test_agent_observe_enriches_and_logs_structured_vision()
    test_agent_visual_memory_context_summarizes_recent_evidence()
    test_agent_observe_captures_screenshot_for_visual_pipeline()
    test_agent_visual_action_grounding_fills_missing_dig_coordinates()
    test_agent_visual_action_grounding_prepends_danger_retreat()
    test_agent_visual_action_grounding_prepends_resource_approach()
    test_agent_visual_action_grounding_prepends_resource_focus()
    print("\nMemory/task system tests PASSED")
