"""Vision Analyzer - VLM-powered visual analysis for the Minecraft agent."""
import json
import base64
import logging
from typing import Optional

logger = logging.getLogger("singularity.vision")


class VisionAnalyzer:
    """Analyzes game observations and optionally screenshots using a VLM."""

    def __init__(self, api_key: str = "", provider: str = "openai", model: str = ""):
        self.api_key = api_key
        self.provider = provider
        self.model = model or ("gpt-4o-mini" if provider == "openai" else "claude-3-haiku-20240307")
        self._client = None
        self._available = False
        self._init_from_env()

    def _init_from_env(self):
        import os
        if not self.api_key:
            for k, p in [("OPENAI_API_KEY", "openai"), ("ANTHROPIC_API_KEY", "anthropic")]:
                v = os.environ.get(k, "")
                if v:
                    self.api_key = v
                    self.provider = p
                    break
        if not self.api_key:
            return
        self._available = True
        try:
            if self.provider == "openai":
                from openai import OpenAI
                self._client = OpenAI(api_key=self.api_key)
            elif self.provider == "anthropic":
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
        except Exception as e:
            logger.warning(f"Failed to init VLM client: {e}")
            self._available = False

    def analyze(self, observations: dict, screenshot_path: str = "") -> dict:
        blocks = observations.get("nearby_blocks", [])
        entities = observations.get("nearby_entities", [])
        trees = observations.get("trees_found", [])
        result = {
            "position": observations.get("position", {}),
            "health": observations.get("health", 20),
            "resources": self._find_resources(blocks, trees),
            "dangers": self._detect_dangers(entities),
            "nearby_entities": entities[:5],
            "visual_analysis": "",
        }
        if self._available and screenshot_path:
            try:
                result["visual_analysis"] = self._analyze_vlm(screenshot_path, observations)
            except Exception as e:
                logger.warning(f"VLM analysis failed: {e}")
        return result

    def _find_resources(self, blocks: list, trees: list) -> list:
        seen = set()
        resources = []
        for b in blocks:
            n = b.get("name", "")
            if "ore" in n or "log" in n:
                if n not in seen:
                    seen.add(n)
                    resources.append({"type": "block", "name": n, "dist": b.get("distance")})
        for t in trees:
            n = t.get("name", "")
            if n not in seen:
                seen.add(n)
                resources.append({"type": "tree", "name": n, "dist": t.get("distance")})
        return resources

    def _detect_dangers(self, entities: list) -> list:
        hostile = {"zombie", "skeleton", "creeper", "spider", "enderman", "witch", "phantom"}
        dangers = []
        for e in entities:
            if e.get("hostile") or e.get("type", "").lower() in hostile:
                dangers.append({"type": e.get("type", "?"), "dist": e.get("distance")})
        return dangers

    def _analyze_vlm(self, image_path: str, obs: dict) -> str:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        prompt = f"Analyze this Minecraft screenshot. Player health: {obs.get('health',20)}. Describe visible blocks, threats, and resources. Be concise."
        if self.provider == "openai":
            resp = self._client.chat.completions.create(
                model=self.model,
                max_tokens=300,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                ]}],
            )
            return resp.choices[0].message.content or ""
        return ""

    def is_available(self) -> bool:
        return self._available
