"""Unit tests for BotBridge response decoding."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from singularity.bot.bridge import BotBridge
from singularity.core.config import BotConfig


class RecordingBridge(BotBridge):
    def __init__(self):
        self.calls = []

    def _send_command(self, command: str, params: dict = None) -> dict:
        payload = params or {}
        self.calls.append((command, payload))
        return {"success": True, "screenshot_path": payload.get("path", "")}

    def _send_command_single(self, command: str, params: dict = None) -> dict:
        self.calls.append((command, params or {}))
        return {"success": True}


class ScriptedSocket:
    def __init__(self, response=b'{"success": true}\n', timeout=10.0):
        self.response = response
        self.timeout = timeout
        self.timeout_history = []
        self.sent = b""

    def gettimeout(self):
        return self.timeout

    def settimeout(self, value):
        self.timeout = value
        self.timeout_history.append(value)

    def sendall(self, payload):
        self.sent += payload

    def recv(self, _):
        response, self.response = self.response, b""
        return response


def test_bridge_uses_configured_endpoint():
    bridge = BotBridge(BotConfig(bridge_host="127.0.0.2", bridge_port=3007))

    assert bridge._bridge_host == "127.0.0.2"
    assert bridge._bridge_port == 3007
    print("PASS: BotBridge uses configured endpoint")


def test_decode_response_handles_valid_json_and_extra_lines():
    bridge = object.__new__(BotBridge)
    result = bridge._decode_response("health", b'{"success": true, "bot_ready": true}\n{"ignored": true}\n')
    assert result["success"] is True
    assert result["bot_ready"] is True
    print("PASS: BotBridge decodes first JSON line")


def test_decode_response_handles_empty_or_invalid_payloads():
    bridge = object.__new__(BotBridge)
    empty = bridge._decode_response("health", b"")
    invalid = bridge._decode_response("health", b"not-json\n")

    assert empty["success"] is False
    assert "Empty response" in empty["error"]
    assert invalid["success"] is False
    assert "Invalid JSON" in invalid["error"]
    print("PASS: BotBridge reports malformed bridge responses")


def test_capture_screenshot_sends_renderer_command():
    bridge = RecordingBridge()
    result = bridge.capture_screenshot("logs/screenshots/test.png")

    assert result["success"] is True
    assert result["screenshot_path"] == "logs/screenshots/test.png"
    assert bridge.calls == [("capture_screenshot", {"path": "logs/screenshots/test.png"})]
    print("PASS: BotBridge capture_screenshot sends renderer command")


def test_navigation_commands_omit_null_y_and_forward_pathfinder_controls():
    bridge = RecordingBridge()

    bridge.walk_to(3, 4, ms=750)
    bridge.move_to(8, 9, tolerance=3, timeout_ms=7000)
    bridge.move_to(8, 9, y=64)
    bridge.dig(8, 63, 9, timeout_ms=30000)

    assert bridge.calls == [
        ("walk_to", {"x": 3, "z": 4, "ms": 750}),
        ("move_to", {"x": 8, "z": 9, "tolerance": 3, "timeout_ms": 7000}),
        ("move_to", {"x": 8, "z": 9, "y": 64}),
        ("dig", {"x": 8, "y": 63, "z": 9, "timeout_ms": 30000}),
    ]
    print("PASS: BotBridge preserves horizontal navigation and pathfinder controls")


def test_m4_dig_forwards_explicit_pickup_and_tool_equip_postconditions():
    bridge = RecordingBridge()

    bridge.dig(
        93,
        139,
        -36,
        timeout_ms=60000,
        require_pickup=True,
        require_tool_equip=True,
    )
    bridge.dig(93, 139, -36, timeout_ms=60000, require_pickup=True)
    bridge.dig(93, 139, -36, timeout_ms=60000)

    assert bridge.calls == [
        (
            "dig",
            {
                "x": 93,
                "y": 139,
                "z": -36,
                "timeout_ms": 60000,
                "require_pickup": True,
                "require_tool_equip": True,
            },
        ),
        (
            "dig",
            {
                "x": 93,
                "y": 139,
                "z": -36,
                "timeout_ms": 60000,
                "require_pickup": True,
            },
        ),
        ("dig", {"x": 93, "y": 139, "z": -36, "timeout_ms": 60000}),
    ]
    print("PASS: BotBridge scopes strict dig postconditions to explicit M4 requests")


def test_m4_place_forwards_explicit_player_clearance_postcondition():
    bridge = RecordingBridge()

    bridge.place(103, 135, -31, "crafting_table", require_player_clearance=True)
    bridge.place(103, 135, -31, "crafting_table")

    assert bridge.calls == [
        (
            "place",
            {
                "x": 103,
                "y": 135,
                "z": -31,
                "item": "crafting_table",
                "require_player_clearance": True,
            },
        ),
        (
            "place",
            {"x": 103, "y": 135, "z": -31, "item": "crafting_table"},
        ),
    ]
    print("PASS: BotBridge scopes player-clearance evidence to explicit M4 place requests")


def test_benchmark_protocol_commands_are_fixed_and_typed():
    bridge = RecordingBridge()
    bridge.benchmark_protocol()
    bridge.reset_benchmark("BM-001")
    bridge.get_player_lifecycle()

    assert bridge.calls == [
        ("benchmark_protocol", {}),
        ("benchmark_reset", {"task_id": "BM-001"}),
        ("get_player_lifecycle", {}),
    ]
    print("PASS: BotBridge exposes fixed M1 protocol and allowlisted task reset commands")


def test_single_shot_navigation_extends_and_restores_socket_timeout():
    bridge = object.__new__(BotBridge)
    bridge._connected = True
    bridge._socket = ScriptedSocket()

    result = bridge._send_command_single("move_to", {"x": 8, "z": 9, "timeout_ms": 30000})

    assert result["success"] is True
    assert bridge._socket.timeout_history == [35.0, 10.0]
    assert b'"timeout_ms": 30000' in bridge._socket.sent
    assert BotBridge._single_response_timeout("move_to", {}, 10.0) == 65.0
    assert BotBridge._single_response_timeout("walk_to", {"ms": 10000}, 10.0) == 15.0
    assert BotBridge._single_response_timeout("dig", {}, 10.0) == 15.0
    assert BotBridge._single_response_timeout("dig", {"timeout_ms": 30000}, 10.0) == 35.0
    print("PASS: Single-shot navigation aligns socket and action timeout budgets")


if __name__ == "__main__":
    test_bridge_uses_configured_endpoint()
    test_decode_response_handles_valid_json_and_extra_lines()
    test_decode_response_handles_empty_or_invalid_payloads()
    test_capture_screenshot_sends_renderer_command()
    test_navigation_commands_omit_null_y_and_forward_pathfinder_controls()
    test_m4_place_forwards_explicit_player_clearance_postcondition()
    test_benchmark_protocol_commands_are_fixed_and_typed()
    test_single_shot_navigation_extends_and_restores_socket_timeout()
    print("\nBot bridge tests PASSED")
