"""Bot bridge -- communicates with the Node.js Mineflayer bot via persistent TCP socket."""
import json
import socket
import logging
import time
from json import JSONDecodeError
from typing import Optional

from singularity.core.config import BotConfig

logger = logging.getLogger("singularity.bot")

MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds, exponential backoff
ACTION_RESPONSE_GRACE_SECONDS = 5.0
MAX_ACTION_RESPONSE_TIMEOUT_SECONDS = 65.0


class BotBridge:
    """Python bridge to a Mineflayer bot running in Node.js.

    Uses a persistent TCP socket connection for low-latency communication.
    The Node.js bot process must be running separately.
    Includes retry logic with exponential backoff for transient failures.
    """

    def __init__(self, config: BotConfig):
        self.config = config
        self._socket: Optional[socket.socket] = None
        self._connected = False
        self._bridge_host = config.bridge_host
        self._bridge_port = config.bridge_port
        self._retry_count = 0

    def connect(self) -> bool:
        """Connect to the Node.js bot bridge with retry logic."""
        for attempt in range(MAX_RETRIES):
            try:
                self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._socket.settimeout(10)
                self._socket.connect((self._bridge_host, self._bridge_port))
                self._connected = True
                self._retry_count = 0
                logger.info(f"Connected to bot bridge at {self._bridge_host}:{self._bridge_port}")
                return True
            except Exception as e:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(f"Connection attempt {attempt+1}/{MAX_RETRIES} failed: {e}, retrying in {delay}s")
                time.sleep(delay)
        logger.error(f"Failed to connect after {MAX_RETRIES} attempts")
        self._connected = False
        return False

    def disconnect(self):
        """Disconnect from the bot bridge."""
        self._connected = False
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
        logger.info("Disconnected from bot bridge")

    def _send_command(self, command: str, params: dict = None) -> dict:
        """Send a command to the Node.js bot with retry logic."""
        if not self._connected or not self._socket:
            return {"success": False, "error": "Not connected to bot bridge"}

        msg = json.dumps({"command": command, "params": params or {}}) + "\n"
        for attempt in range(MAX_RETRIES):
            try:
                self._socket.sendall(msg.encode("utf-8"))
                response = b""
                while True:
                    chunk = self._socket.recv(4096)
                    if not chunk:
                        break
                    response += chunk
                    if b"\n" in response:
                        break
                return self._decode_response(command, response)
            except (socket.timeout, ConnectionError, BrokenPipeError) as e:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(f"Command '{command}' attempt {attempt+1}/{MAX_RETRIES} failed: {e}, retrying in {delay}s")
                time.sleep(delay)
                if attempt < MAX_RETRIES - 1:
                    self._reconnect()
            except Exception as e:
                logger.error(f"Command '{command}' failed: {e}")
                return {"success": False, "error": str(e)}
        return {"success": False, "error": f"Command '{command}' failed after {MAX_RETRIES} retries"}

    def _decode_response(self, command: str, response: bytes) -> dict:
        """Decode one newline-delimited JSON response from the bridge."""
        if not response:
            return {"success": False, "error": f"Empty response from bot bridge for command '{command}'"}
        first_line = response.split(b"\n", 1)[0].decode("utf-8").strip()
        if not first_line:
            return {"success": False, "error": f"Blank response from bot bridge for command '{command}'"}
        try:
            return json.loads(first_line)
        except JSONDecodeError as e:
            return {"success": False, "error": f"Invalid JSON from bot bridge for command '{command}': {e}"}

    def _reconnect(self):
        """Attempt to re-establish the connection."""
        logger.info("Attempting to reconnect...")
        try:
            self._socket.close()
        except Exception:
            pass
        self._connected = False
        self.connect()

    # Observation commands
    def get_player_state(self) -> dict:
        return self._send_command("get_player_state")

    def health(self) -> dict:
        return self._send_command("health")

    def benchmark_protocol(self) -> dict:
        return self._send_command("benchmark_protocol")

    def reset_benchmark(self, task_id: str) -> dict:
        return self._send_command("benchmark_reset", {"task_id": task_id})

    def get_inventory(self) -> list:
        result = self._send_command("get_inventory")
        return result.get("items", [])

    def get_nearby_entities(self, radius: int = 32) -> list:
        result = self._send_command("get_nearby_entities", {"radius": radius})
        return result.get("entities", [])

    def get_nearby_blocks(self, radius: int = 5) -> list:
        result = self._send_command("get_nearby_blocks", {"radius": radius})
        return result.get("blocks", [])

    def get_block_below(self) -> str:
        result = self._send_command("get_block_below")
        return result.get("block", "unknown")

    def get_time(self) -> int:
        result = self._send_command("get_time")
        return result.get("time", 0)

    def get_weather(self) -> str:
        result = self._send_command("get_weather")
        return result.get("weather", "clear")

    def get_biome(self) -> str:
        result = self._send_command("get_biome")
        return result.get("biome", "unknown")

    def get_light_level(self) -> int:
        result = self._send_command("get_light_level")
        return result.get("light_level", 0)

    def capture_screenshot(self, output_path: str = "") -> dict:
        """Ask the bridge renderer, if present, to capture the current view."""
        params = {"path": output_path} if output_path else {}
        return self._send_command("capture_screenshot", params)

    def get_nearby_trees(self, radius: int = 32) -> list:
        result = self._send_command("get_nearby_trees", {"radius": radius})
        return result.get("trees", [])

    def _send_command_single(self, command: str, params: dict = None) -> dict:
        if not self._connected or not self._socket:
            return {"success": False, "error": "Not connected to bot bridge"}
        params = params or {}
        msg = json.dumps({"command": command, "params": params}) + "\n"
        active_socket = self._socket
        previous_timeout = active_socket.gettimeout()
        response_timeout = self._single_response_timeout(command, params, previous_timeout)
        try:
            active_socket.settimeout(response_timeout)
            active_socket.sendall(msg.encode("utf-8"))
            response = b""
            while True:
                chunk = active_socket.recv(4096)
                if not chunk:
                    break
                response += chunk
                if b"\n" in response:
                    break
            return self._decode_response(command, response)
        except (socket.timeout, ConnectionError, BrokenPipeError) as e:
            logger.warning(f"Single-shot command '{command}' failed: {e}; reconnecting without replay")
            self._reconnect()
            return {
                "success": False,
                "error": str(e),
                "command_replayed": False,
                "bridge_reconnected": self._connected,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "command_replayed": False}
        finally:
            if self._connected and self._socket is active_socket:
                active_socket.settimeout(previous_timeout)

    @staticmethod
    def _single_response_timeout(command: str, params: dict, previous_timeout: float = None) -> float:
        baseline = float(previous_timeout) if previous_timeout is not None else 10.0
        if command == "move_to":
            requested = params.get("timeout_ms")
            try:
                action_seconds = float(requested) / 1000.0 if requested is not None else 60.0
            except (TypeError, ValueError):
                action_seconds = 60.0
            action_seconds = max(1.0, min(60.0, action_seconds))
        elif command == "walk_to":
            try:
                action_seconds = float(params.get("ms", 2000)) / 1000.0
            except (TypeError, ValueError):
                action_seconds = 2.0
            action_seconds = max(0.1, min(10.0, action_seconds))
        elif command == "dig":
            action_seconds = 10.0
        else:
            action_seconds = baseline
        return min(
            MAX_ACTION_RESPONSE_TIMEOUT_SECONDS,
            max(baseline, action_seconds + ACTION_RESPONSE_GRACE_SECONDS),
        )
    # Action commands
    def walk_to(self, x: float, z: float, y: float = None, ms: int = 2000) -> dict:
        params = {"x": x, "z": z, "ms": ms}
        if y is not None:
            params["y"] = y
        return self._send_command_single("walk_to", params)

    def move_to(
        self,
        x: float,
        z: float,
        y: float = None,
        tolerance: float = None,
        timeout_ms: int = None,
    ) -> dict:
        params = {"x": x, "z": z}
        if y is not None:
            params["y"] = y
        if tolerance is not None:
            params["tolerance"] = tolerance
        if timeout_ms is not None:
            params["timeout_ms"] = timeout_ms
        return self._send_command_single("move_to", params)

    def look_at(self, x: float, y: float, z: float) -> dict:
        return self._send_command("look_at", {"x": x, "y": y, "z": z})

    def dig(self, x: int = None, y: int = None, z: int = None) -> dict:
        return self._send_command_single("dig", {"x": x, "y": y, "z": z})

    def place(self, x: int, y: int, z: int, item_name: str = None) -> dict:
        return self._send_command("place", {"x": x, "y": y, "z": z, "item": item_name})

    def craft(self, item_name: str, count: int = 1) -> dict:
        return self._send_command("craft", {"item": item_name, "count": count})

    def attack(self, entity_id: int = None) -> dict:
        return self._send_command("attack", {"entity_id": entity_id})

    def equip(self, item_name: str, destination: str = "hand") -> dict:
        return self._send_command("equip", {"item": item_name, "destination": destination})

    def use_item(self) -> dict:
        return self._send_command("use_item")

    def chat(self, message: str) -> dict:
        return self._send_command("chat", {"message": message})
