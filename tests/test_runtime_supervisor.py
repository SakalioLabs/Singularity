"""Unit tests for runtime interrupt supervision."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from singularity.core.agent import Agent
from singularity.core.config import Config
from singularity.core.runtime import RuntimeSupervisor
from singularity.core.task_system import TaskStatus, TaskSystem


class FakeExplorer:
    def should_return(self, position, inventory_count):
        return inventory_count >= 36, "Inventory full"

    def get_return_direction(self, position):
        return {"x": 0, "z": 0}

    def record_position(self, position):
        pass


class FakeLogger:
    def __init__(self):
        self.events = []
        self.actions = []
        self.observations = []

    def log(self, event_type, data, level="INFO"):
        self.events.append({"type": event_type, "data": data, "level": level})

    def log_action(self, action, result):
        self.actions.append({"action": action, "result": result})

    def log_observation(self, observation):
        self.observations.append(observation)


class FakeMemory:
    def __init__(self):
        self.episodes = []
        self.contexts = []

    def write_episode(self, event_type, data):
        self.episodes.append({"type": event_type, "data": data})

    def write_context(self, data):
        self.contexts.append(data)


class FakeActionController:
    def __init__(self):
        self.actions = []

    def execute(self, action, observation):
        self.actions.append(action)
        return {"success": True, "action_type": action.get("type")}


class FakeObserver:
    def observe(self):
        return {"health": 20, "inventory": {}, "inventory_count": 0, "nearby_entities": [], "position": {}}


def test_runtime_interrupts_on_health_and_hostiles():
    supervisor = RuntimeSupervisor(Config())

    health = supervisor.evaluate_interrupt({"health": 1, "inventory": {"bread": 1}, "nearby_entities": []})
    assert health.should_interrupt
    assert health.reason == "health_critical"
    assert health.emergency_action["type"] == "use_item"

    hostile = supervisor.evaluate_interrupt({
        "health": 20,
        "inventory": {"stone_sword": 1},
        "nearby_entities": [{"type": "zombie", "hostile": True, "distance": 4}],
    })
    assert hostile.should_interrupt
    assert hostile.reason == "hostile_nearby"
    assert hostile.emergency_action["parameters"]["item"] == "stone_sword"
    print("PASS: RuntimeSupervisor interrupts health and hostile threats")


def test_runtime_interrupts_deadlines_and_return_to_base():
    tasks = TaskSystem()
    task = tasks.create_task(
        "Reach shelter before night",
        status=TaskStatus.ACCEPTED,
        deadline=time.time() - 1,
    )
    supervisor = RuntimeSupervisor(Config(), FakeExplorer())

    deadline = supervisor.evaluate_interrupt({"health": 20, "inventory": {}, "nearby_entities": []}, active_task=task)
    assert deadline.should_interrupt
    assert deadline.reason == "task_deadline_elapsed"

    returning = supervisor.evaluate_interrupt({
        "health": 20,
        "inventory": {},
        "inventory_count": 36,
        "nearby_entities": [],
        "position": {"x": 40, "z": 40},
    })
    assert returning.should_interrupt
    assert returning.reason == "return_to_base"
    assert returning.emergency_action["type"] == "move_to"
    print("PASS: RuntimeSupervisor interrupts deadlines and return-to-base")


def test_agent_handles_runtime_interrupt_with_emergency_action():
    agent = object.__new__(Agent)
    agent.task_system = TaskSystem()
    agent.runtime = RuntimeSupervisor(Config())
    agent.session_logger = FakeLogger()
    agent.memory = FakeMemory()
    agent.action_controller = FakeActionController()
    agent.observer = FakeObserver()
    agent.explorer = FakeExplorer()

    interrupted, observation = agent._handle_runtime_interrupt(
        {"health": 1, "inventory": {"bread": 1}, "inventory_count": 1, "nearby_entities": [], "position": {}},
        "Gather wood",
        {"cycle": 1},
    )

    assert interrupted
    assert observation["health"] == 20
    assert agent.session_logger.events[0]["type"] == "runtime_interrupt"
    assert agent.action_controller.actions[0]["type"] == "use_item"
    assert any(event["type"] == "runtime_emergency_action" for event in agent.memory.episodes)
    print("PASS: Agent handles runtime interrupt and emergency action")


if __name__ == "__main__":
    test_runtime_interrupts_on_health_and_hostiles()
    test_runtime_interrupts_deadlines_and_return_to_base()
    test_agent_handles_runtime_interrupt_with_emergency_action()
    print("\nRuntime supervisor tests PASSED")
