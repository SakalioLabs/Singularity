"""M7 Multi-Agent tests."""
import sys, os, json, tempfile, time, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import unittest
from singularity.multiagent.protocol import (
    SharedState, AgentRole, MessageType, AgentMessage
)
from singularity.multiagent.coordinator import (
    AgentCoordinator, LeaderAgent, AgentWorker
)


class TestSharedState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state = SharedState(os.path.join(self.tmp, "state.json"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_register_agent(self):
        info = self.state.register_agent("agent1", AgentRole.WORKER)
        self.assertEqual(info["role"], "worker")
        self.assertEqual(info["status"], "idle")

    def test_register_leader(self):
        self.state.register_agent("lead", AgentRole.LEADER)
        self.assertEqual(self.state.get_leader(), "lead")

    def test_update_agent_state(self):
        self.state.register_agent("a1", AgentRole.WORKER)
        self.state.update_agent_state("a1", status="working", health=18)
        info = self.state.get_agent("a1")
        self.assertEqual(info["status"], "working")
        self.assertEqual(info["health"], 18)

    def test_list_agents(self):
        self.state.register_agent("a1", AgentRole.WORKER)
        self.state.register_agent("a2", AgentRole.WORKER)
        self.assertEqual(len(self.state.list_agents()), 2)

    def test_assign_task(self):
        self.state.register_agent("w1", AgentRole.WORKER)
        ok = self.state.assign_task("w1", {"title": "Gather wood", "priority": 1})
        self.assertTrue(ok)
        tasks = self.state.get_agent_tasks("w1")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["title"], "Gather wood")

    def test_complete_task(self):
        self.state.register_agent("w1", AgentRole.WORKER)
        self.state.assign_task("w1", {"title": "Test"})
        tasks = self.state.get_agent_tasks("w1")
        self.state.complete_task(tasks[0]["task_id"], {"items": 5})
        tasks2 = self.state.get_agent_tasks("w1")
        self.assertEqual(tasks2[0]["status"], "completed")

    def test_start_task(self):
        self.state.register_agent("w1", AgentRole.WORKER)
        self.state.assign_task("w1", {"title": "Test"})
        tasks = self.state.get_agent_tasks("w1")
        ok = self.state.start_task(tasks[0]["task_id"])
        tasks2 = self.state.get_agent_tasks("w1")
        self.assertTrue(ok)
        self.assertEqual(tasks2[0]["status"], "in_progress")

    def test_fail_task(self):
        self.state.register_agent("w1", AgentRole.WORKER)
        self.state.assign_task("w1", {"title": "Test"})
        tasks = self.state.get_agent_tasks("w1")
        self.state.fail_task(tasks[0]["task_id"], "No resources")
        tasks2 = self.state.get_agent_tasks("w1")
        self.assertEqual(tasks2[0]["status"], "failed")

    def test_clear_old_agents(self):
        self.state.register_agent("old", AgentRole.WORKER)
        self.state.clear_old_agents(max_age=0)
        self.assertEqual(len(self.state.list_agents()), 0)


class TestLeaderAgent(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state = SharedState(os.path.join(self.tmp, "state.json"))
        self.leader = LeaderAgent("leader1", self.state)
        self.worker = AgentWorker("worker1", self.state)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_leader_assigned(self):
        self.assertEqual(self.state.get_leader(), "leader1")

    def test_assign_task_to_worker(self):
        ok = self.leader.assign_task("worker1", {"title": "Mine stone", "priority": 2})
        self.assertTrue(ok)
        tasks = self.worker.get_next_task()
        self.assertIsNotNone(tasks)
        self.assertEqual(tasks["title"], "Mine stone")

    def test_worker_completes_task(self):
        self.leader.assign_task("worker1", {"title": "Gather"})
        task = self.worker.get_next_task()
        self.worker.complete_current_task(task["task_id"], {"oak": 3})
        self.assertTrue(self.leader.check_all_complete())

    def test_worker_fails_task(self):
        self.leader.assign_task("worker1", {"title": "Mine"})
        task = self.worker.get_next_task()
        self.worker.fail_current_task(task["task_id"], "No pickaxe")
        failed = self.leader.get_failed_tasks()
        self.assertEqual(len(failed), 1)

    def test_worker_no_next_task(self):
        task = self.worker.get_next_task()
        self.assertIsNone(task)

    def test_leader_worker_status(self):
        self.leader.update_status("planning")
        self.worker.update_status("mining")
        agents = self.leader.get_all_agents()
        statuses = [a.get("status") for a in agents]
        self.assertIn("planning", statuses)
        self.assertIn("mining", statuses)

    def test_double_worker(self):
        w2 = AgentWorker("worker2", self.state)
        self.leader.assign_task("worker1", {"title": "Task A"})
        self.leader.assign_task("worker2", {"title": "Task B"})
        self.assertEqual(len(self.state.get_pending_tasks()), 2)

    def test_leader_update_then_check(self):
        self.leader.update_status("planning", {"x": 10, "y": 66, "z": 20})
        info = self.leader.get_agent_info("leader1")
        self.assertEqual(info["position"]["x"], 10)


class TestCoordinatorEdgeCases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state = SharedState(os.path.join(self.tmp, "state.json"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_task_for_nonexistent_agent(self):
        ok = self.state.assign_task("ghost", {"title": "Task"})
        self.assertFalse(ok)

    def test_complete_nonexistent_task(self):
        ok = self.state.complete_task("no_such_task")
        self.assertFalse(ok)

    def test_fail_nonexistent_task(self):
        ok = self.state.fail_task("no_such_task")
        self.assertFalse(ok)

    def test_get_agent_nonexistent(self):
        info = self.state.get_agent("nobody")
        self.assertEqual(info, {})

    def test_leader_without_workers(self):
        leader = LeaderAgent("only_leader", self.state)
        workers = leader.get_available_workers()
        self.assertEqual(len(workers), 0)


if __name__ == "__main__":
    unittest.main()
