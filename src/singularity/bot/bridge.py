"""Bot bridge -- communicates with the Node.js Mineflayer bot via persistent TCP socket."""
import json
import socket
import logging
import time
from typing import Optional

from singularity.core.config import BotConfig

logger = logging.getLogger("singularity.bot")

MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds, exponential backoff


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
        self._bridge_host = "127.0.0.1"
        self._bridge_port = 3000
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
                    response += chunk
                    if b"\n" in response:
                        break
                return json.loads(response.decode("utf-8").strip())
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

    # Action commands
    def move_to(self, x: float, z: float, y: float = None) -> dict:
        return self._send_command("move_to", {"x": x, "z": z, "y": y})

    def look_at(self, x: float, y: float, z: float) -> dict:
        return self._send_command("look_at", {"x": x, "y": y, "z": z})

    def dig(self, x: int = None, y: int = None, z: int = None) -> dict:
        return self._send_command("dig", {"x": x, "y": y, "z": z})

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
