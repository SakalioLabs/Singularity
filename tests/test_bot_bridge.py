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
        self.calls.append((command, params or {}))
        return {"success": True, "screenshot_path": params.get("path", "")}


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


if __name__ == "__main__":
    test_bridge_uses_configured_endpoint()
    test_decode_response_handles_valid_json_and_extra_lines()
    test_decode_response_handles_empty_or_invalid_payloads()
    test_capture_screenshot_sends_renderer_command()
    print("\nBot bridge tests PASSED")
