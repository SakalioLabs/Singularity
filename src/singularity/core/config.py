"""Configuration for Singularity agent."""
from dataclasses import dataclass, field


@dataclass
class BotConfig:
    host: str = "localhost"
    port: int = 25565
    username: str = "Singularity"
    version: str = "1.20.4"
    auth: str = "offline"
    bridge_host: str = "127.0.0.1"
    bridge_port: int = 3000


@dataclass
class LLMConfig:
    provider: str = "openai"  # openai, anthropic, deepseek, ollama
    model: str = "gpt-4o-mini"
    api_key: str = ""
    base_url: str = ""
    max_tokens: int = 4096
    temperature: float = 0.7


@dataclass
class Config:
    bot: BotConfig = field(default_factory=BotConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    log_dir: str = "logs"
    memory_dir: str = "workspace/memory"
    skill_dir: str = "workspace/skills"
    enable_policy_skills: bool = True
    enable_autocurriculum: bool = True
    enable_memory_policy: bool = True
    enable_task_memory_context: bool = True
    enable_skill_memory_context: bool = True
    enforce_memory_write_gate: bool = False
    enable_vision_analysis: bool = True
    enable_visual_action_grounding: bool = True
    mixed_policy_patch_paths: list[str] = field(default_factory=list)
    mixed_policy_gate_paths: list[str] = field(default_factory=list)
    self_evolution_feedback_paths: list[str] = field(default_factory=list)
    skill_memory_quality_feedback_paths: list[str] = field(default_factory=list)
    enable_self_evolution_policy: bool = True
    enable_screenshot_capture: bool = False
    screenshot_dir: str = "logs/screenshots"
    screenshot_min_interval_s: float = 2.0
    enable_goal_verification: bool = True
    enable_goal_critic: bool = False
    max_action_timeout: int = 30000  # ms
    health_critical_threshold: float = 4.0  # hearts
