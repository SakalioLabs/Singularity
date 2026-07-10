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
    enable_skill_candidate_extraction: bool = False
    skill_candidate_queue_path: str = "workspace/skills/skill_candidates.jsonl"
    skill_learning_ledger_path: str = "workspace/evals/skill_learning_ledger.json"
    skill_regressions_path: str = "workspace/evals/skill_regressions.json"
    skill_execution_mode: str = "off"  # off, shadow, advisory, evaluation, runtime
    target_skill_id: str = ""
    skill_experiment_id: str = ""
    skill_evaluation_authorization: dict = field(default_factory=dict)
    skill_fault_profile: str = ""
    enable_policy_skills: bool = True
    enable_skill_frontier_routing: bool = True
    enable_autocurriculum: bool = True
    enable_memory_policy: bool = True
    enable_memory_persistence: bool = True
    enable_planning_memory_context: bool = True
    enable_task_memory_context: bool = True
    enable_task_continuity_context: bool = True
    enable_task_readiness_context: bool = True
    enable_task_readiness_recovery: bool = True
    enable_bounded_planning_context: bool = True
    planning_memory_read_limit_chars: int = 600
    planning_memory_cycle_limit_chars: int = 2400
    enable_skill_memory_context: bool = True
    enable_curriculum_planner_context: bool = True
    enable_knowledge_correction_context: bool = True
    enable_plan_cache: bool = False
    plan_cache_paths: list[str] = field(default_factory=list)
    plan_cache_gate_paths: list[str] = field(default_factory=list)
    plan_cache_min_confidence: float = 0.75
    episode_abort_mode: str = "off"
    episode_abort_gate_paths: list[str] = field(default_factory=list)
    episode_abort_task_stream_id: str = ""
    episode_abort_seed_id: str = ""
    frontier_budget_mode: str = "off"
    frontier_budget_policy: str = "information"
    frontier_budget_gate_paths: list[str] = field(default_factory=list)
    frontier_budget_total_rounds: int = 8
    frontier_budget_temperature: float = 2.0
    frontier_budget_exploration_floor: int = 1
    frontier_budget_task_stream_id: str = ""
    frontier_budget_seed_id: str = ""
    enable_weighted_memory_retrieval: bool = False
    memory_attribution_gate_paths: list[str] = field(default_factory=list)
    enforce_memory_write_gate: bool = False
    memory_promptware_gate_paths: list[str] = field(default_factory=list)
    enable_coaching_policy: bool = True
    coach_style: str = ""
    coach_style_ablation_paths: list[str] = field(default_factory=list)
    coach_style_gate_paths: list[str] = field(default_factory=list)
    enable_vision_analysis: bool = True
    enable_visual_action_grounding: bool = True
    mixed_policy_patch_paths: list[str] = field(default_factory=list)
    mixed_policy_gate_paths: list[str] = field(default_factory=list)
    self_evolution_feedback_paths: list[str] = field(default_factory=list)
    world_model_feedback_paths: list[str] = field(default_factory=list)
    world_model_gate_paths: list[str] = field(default_factory=list)
    knowledge_correction_feedback_paths: list[str] = field(default_factory=list)
    knowledge_correction_gate_paths: list[str] = field(default_factory=list)
    enable_task_precondition_context: bool = True
    task_precondition_feedback_paths: list[str] = field(default_factory=list)
    task_precondition_gate_paths: list[str] = field(default_factory=list)
    action_value_feedback_paths: list[str] = field(default_factory=list)
    action_value_transition_gate_paths: list[str] = field(default_factory=list)
    action_value_transition_evaluator_report_paths: list[str] = field(default_factory=list)
    skill_memory_quality_feedback_paths: list[str] = field(default_factory=list)
    skill_memory_quality_gate_paths: list[str] = field(default_factory=list)
    skill_runtime_default_gate_paths: list[str] = field(default_factory=list)
    skill_retirement_gate_paths: list[str] = field(default_factory=list)
    enable_self_evolution_policy: bool = True
    enable_screenshot_capture: bool = False
    screenshot_dir: str = "logs/screenshots"
    screenshot_min_interval_s: float = 2.0
    enable_goal_verification: bool = True
    enable_goal_critic: bool = False
    force_rule_planner: bool = False
    goal_critic_gate_paths: list[str] = field(default_factory=list)
    enable_world_model_curriculum_feedback: bool = True
    enable_blocked_plan_rule_fallback: bool = True
    enable_action_verification: bool = True
    enforce_action_verification: bool = True
    enable_action_candidate_selection: bool = True
    max_action_timeout: int = 30000  # ms
    health_critical_threshold: float = 4.0  # hearts
