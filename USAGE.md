# USAGE.md - Singularity Minecraft LLM Agent

## Quick Start

### Prerequisites
- Python 3.12+
- Node.js 18+
- JDK 17+ (for MC server)
- MC 1.20.4 server jar

### Setup
```powershell
# Clone and install
git clone https://github.com/SakalioLabs/Singularity.git
cd Singularity
.\setup.ps1
```

### Running the Agent

**Terminal 1: MC Server**
```powershell
cd mc-server
java -Xmx1G -Xms512M -jar server.jar nogui
```

**Terminal 2: Bot Bridge**
```powershell
node src/bot/bot_server.js
# Optional screenshot renderer/plugin for --capture-screenshots:
node src/bot/bot_server.js --screenshot-plugin src/bot/screenshot_plugin_prismarine_viewer.js
# or:
npm run start:screenshot
```

**Terminal 3: Agent**
```powershell
# With OpenAI
$env:OPENAI_API_KEY = "sk-..."
python -m singularity.main run --goal "Gather 3 oak logs" --llm-provider openai --llm-model gpt-4o-mini

# Optional fallback critic for goals that deterministic verification cannot cover.
# Runtime use requires an approved goal-verification-critic-gate report.
python -m singularity.main run --goal "Confirm base entrance is sealed" --goal-critic --goal-critic-gate logs/benchmarks/goal_critic_gate.json --llm-provider openai --llm-model MODEL_NAME --llm-base-url PROVIDER_URL

# Structured vision grounding is enabled by default and logs lightweight `vision` events.
# Disable it for debugging or baseline runs:
python -m singularity.main run --goal "Gather wood" --no-vision-analysis
# Visual action grounding is also enabled by default. It can use grounded
# resources/dangers to approach and look at visible resources, fill dig
# coordinates, or insert a retreat action:
python -m singularity.main run --goal "Mine nearby iron ore" --no-visual-action-grounding

# If the bridge has a renderer/plugin that implements capture_screenshot,
# capture screenshot paths into vision logs and VisualMemory:
python -m singularity.main run --goal "Inspect shelter entrance" --capture-screenshots --screenshot-dir logs/screenshots

# Screenshot plugin contract:
# - export a function, attach(bot, context), attachScreenshotPlugin(bot, context),
#   install(bot, context), or captureScreenshot(outputPath, context)
# - return a screenshot path, a Buffer/base64 image, or an object with
#   screenshot_path/path/buffer/base64 fields
# The bridge writes Buffer/base64 output to the requested path and reports
# file_exists/file_size for visual-trace quality gates.
# The included prismarine-viewer plugin is optional and needs renderer deps:
# npm install prismarine-viewer three PrismarineJS/node-canvas-webgl
# On Windows, prefer WSL or Docker for node-canvas-webgl.
# Check readiness before a screenshot run:
python -m singularity.main preflight --skip-network --screenshot-renderer
# Docker alternative for the screenshot bridge:
npm run docker:screenshot:build
New-Item -ItemType Directory -Force logs\screenshots | Out-Null
docker run --rm -it -p 3000:3000 -v ${PWD}\logs\screenshots:/app/logs/screenshots -e MC_HOST=host.docker.internal -e MC_PORT=25565 singularity-screenshot-bridge
python -m singularity.main screenshot-smoke-test --bridge-host 127.0.0.1 --bridge-port 3000 --screenshot-dir logs/screenshots

# With an OpenAI-compatible provider
python -m singularity.main run --goal "Gather wood" --llm-provider openai --llm-model deepseek-chat --api-key YOUR_KEY --llm-base-url https://api.deepseek.com/v1

# With local Ollama
python -m singularity.main run --goal "Gather wood" --llm-provider ollama --llm-model llama3

# Rule-based (no LLM needed)
python -m singularity.main run --goal "Gather 3 oak logs"
```

Use a non-default bridge port when running more than one bot bridge:

```powershell
node src/bot/bot_server.js --username SingularityA --bridge-port 3000
python -m singularity.main run --goal "Gather 3 oak logs" --bridge-port 3000
```

### Running Benchmarks
```powershell
# Readiness checks
python -m singularity.main preflight --skip-network
python -m singularity.main preflight

# M1 benchmarks (basic actions)
python -m singularity.main benchmark --suite m1 --preflight

# Run benchmarks and ingest passing traces into memory + skill candidates
python -m singularity.main benchmark --suite m1 --preflight --ingest

# Add an explicit LLM fallback critic for unknown verifier gates during ingestion
python -m singularity.main benchmark --suite m1 --ingest --promotion-critic --llm-provider openai --llm-model MODEL_NAME --llm-base-url PROVIDER_URL

# Benchmark result JSON includes reviewed policy-skill intervention metrics when they fire

# Live reviewed policy-skill ablation across the selected suite
python -m singularity.main benchmark --suite m1 --preflight --policy-skill-ablation

# Live visual action grounding ablation across the selected suite
python -m singularity.main benchmark --suite m1 --preflight --visual-action-ablation --output visual_action_benchmark_ablation.json

# Offline causal scheduling ablation (no MC server needed)
python -m singularity.main scheduling-ablation

# Replay session logs through the same ablation.
# Repeated action/subject/outcome events are aggregated into compact summaries.
python -m singularity.main scheduling-ablation --session-log logs/session_xxx.jsonl --max-cases-per-log 20 --min-value-score 0.55

# Offline reviewed policy-skill ablation (no MC server needed)
python -m singularity.main policy-skill-ablation
python -m singularity.main policy-skill-ablation --skill-storage-path workspace/skills --no-builtin

# Offline visual action grounding ablation (no MC server needed)
python -m singularity.main visual-action-ablation --output logs/benchmarks/visual_action_ablation.json
# Replay visual grounding interventions mined from real session logs
python -m singularity.main visual-action-ablation --session-log logs/session_xxx.jsonl --include-builtin --output logs/benchmarks/visual_action_ablation.json

# Queue reviewable skills from repeated high-value causal summaries in a session log
python -m singularity.main skill-candidates --session logs/session_xxx.jsonl --causal-summaries --min-causal-repeats 3 --min-causal-value 0.65

# Queue reviewable correction skills from repeated failures followed by useful recovery actions
python -m singularity.main skill-candidates --session logs/session_xxx.jsonl --failure-corrections --min-failure-repeats 2 --min-failure-value 0.55

# Report repeatedly recalled memories/experiences that are worth consolidation review
python -m singularity.main memory-consolidation-report --memory-dir workspace/memory --min-recall-count 2 --min-unique-queries 2
# Audit Echo-style transfer-axis matches from stored experience records
python -m singularity.main transfer-memory-report --memory-dir workspace/memory --query "Craft a stone pickaxe from cobblestone and sticks"
# Audit task-centric memory context for a goal plus active task metadata
python -m singularity.main task-memory-report --memory-dir workspace/memory --goal "Upgrade mining tool" --task-json "{\"title\":\"Craft stone pickaxe\",\"preconditions\":{\"inventory\":{\"cobblestone\":3,\"stick\":2}},\"success_criteria\":{\"inventory\":{\"stone_pickaxe\":1}}}"

# Audit session logs for memory write/read/manage policy gaps
python -m singularity.main memory-policy-report --session-log logs/session_xxx.jsonl --output logs/benchmarks/memory_policy.json
# The saved JSON includes `memory_policy_feedback` for future memory-write and retrieval policy tuning.
# Attribute generic memory reads to downstream plan/action/goal outcomes before retrieval weights are tuned.
python -m singularity.main memory-attribution-report --session-log logs/session_xxx.jsonl --output logs/benchmarks/memory_attribution.json
# Reports include retrieval-trace coverage, weighted match counts, and attribution policy distributions when runtime traces are present.
python -m singularity.main memory-attribution-gate --memory-attribution-report logs/benchmarks/memory_attribution.json --output logs/benchmarks/memory_attribution_gate.json
# Runtime weighted retrieval stays disabled unless this gate is approved.
python -m singularity.main run --goal "Craft torches" --enable-weighted-memory-retrieval --memory-attribution-gate logs/benchmarks/memory_attribution_gate.json
# New Agent runs log `memory_write`, `memory_read`, and `memory_manage` events plus summary metrics.
# `MemoryLifecyclePolicy` is advisory by default; strict suppression also requires an approved memory-promptware gate.
# Audit durable memory entries that would be excluded at read time.
python -m singularity.main memory-read-filter-report --memory-dir workspace/memory --query "safe coal route"
# Audit durable memories and transferable experiences for promptware-style memory injection payloads.
python -m singularity.main memory-promptware-report --memory-dir workspace/memory --output logs/benchmarks/memory_promptware.json
# Gate stricter memory enforcement on a saved audit; default thresholds require zero flagged memories.
python -m singularity.main memory-promptware-gate --memory-promptware-report logs/benchmarks/memory_promptware.json --output logs/benchmarks/memory_promptware_gate.json
# Enable strict write suppression only with an approved promptware gate.
python -m singularity.main run --goal "Craft torches" --enforce-memory-write-gate --memory-promptware-gate logs/benchmarks/memory_promptware_gate.json

# Summarize open-world exploration coverage from autonomous/session logs
python -m singularity.main exploration-trace-report --session-log logs/session_xxx.jsonl --output logs/benchmarks/exploration_trace.json
# The saved JSON includes `curriculum_feedback`, which can be applied to CurriculumManager for candidate reranking.
# Build a lightweight world-state map with visited cells, frontiers, resource hotspots, and next exploration goals.
python -m singularity.main world-model-report --session-log logs/session_xxx.jsonl --cell-size 8 --output logs/benchmarks/world_model.json
# The saved JSON includes `world_model_feedback` for frontier/resource/danger-aware curriculum reranking.
# Gate world-model feedback before allowing it to bias autonomous curriculum goals.
python -m singularity.main world-model-feedback-gate --world-model-report logs/benchmarks/world_model.json --output logs/benchmarks/world_model_gate.json
python -m singularity.main autonomous --world-model-feedback logs/benchmarks/world_model.json --world-model-gate logs/benchmarks/world_model_gate.json

# Bias runtime planning and autonomous curriculum with an advisory coaching style.
# Styles affect planner context and curriculum ranking only; action verification and safety gates still apply.
python -m singularity.main autonomous --coach-style explorer
python -m singularity.main run --goal "Explore the nearby cave and return safely" --coach-style safe
# Compare baseline curriculum choices with style-biased choices before spending live runtime.
python -m singularity.main coach-style-ablation --style safe --style explorer --output logs/benchmarks/coach_style_ablation.json
python -m singularity.main coach-style-ablation --session-log logs/session_xxx.jsonl --style explorer --output logs/benchmarks/coach_style_from_log.json
# Gate saved coaching evidence before treating a style as benchmark-ready.
python -m singularity.main coach-style-gate --coach-style-ablation logs/benchmarks/coach_style_ablation.json --style explorer --output logs/benchmarks/coach_style_gate.json
# Benchmark with a style only after the saved ablation and approved gate pass preflight.
python -m singularity.main benchmark --suite m1 --coach-style explorer --coach-style-ablation logs/benchmarks/coach_style_ablation.json --coach-style-gate logs/benchmarks/coach_style_gate.json --coach-style-preflight-output logs/benchmarks/coach_style_preflight.json

# Summarize MineEvolve-style execution progress, stagnation, and adaptor hints
# Successful action returns are discounted unless later observations show state, inventory, or verifier progress.
# Blocked or empty plans that reach goal failure before any action are reported as zero-action failures.
python -m singularity.main self-evolution-report --session-log logs/session_xxx.jsonl --output logs/benchmarks/self_evolution.json
# The saved JSON includes `self_evolution_feedback` for repair/adaptor and skill-curation experiments.
# Use it as advisory planner context in later runs without auto-mutating skills or bypassing verification.
python -m singularity.main run --goal "Craft torches" --self-evolution-feedback logs/benchmarks/self_evolution.json
# Audit whether executed actions follow the preceding planner action list.
python -m singularity.main plan-action-compliance-report --session-log logs/session_xxx.jsonl --output logs/benchmarks/plan_action_compliance.json
# Measure planner wait, stale actions, long-running action windows, unfinished
# plan suffixes, and cross-role action overlap before trying interruptible plan/act execution.
python -m singularity.main plan-act-latency-report --session-log logs/session_xxx.jsonl --output logs/benchmarks/plan_act_latency.json
python -m singularity.main plan-act-latency-report --collab-report logs/benchmarks/bm701_collab_report.json --output logs/benchmarks/bm701_plan_act_latency.json
python -m singularity.main plan-act-latency-gate --baseline-plan-act-report logs/benchmarks/bm701_baseline_plan_act_latency.json --candidate-plan-act-report logs/benchmarks/bm701_interruptible_plan_act_latency.json --baseline-verifier-report logs/benchmarks/bm701_baseline_action_verification.json --candidate-verifier-report logs/benchmarks/bm701_interruptible_action_verification.json --output logs/benchmarks/bm701_plan_act_latency_gate.json
# Mine AgenticCache-style plan transitions for explicit, default-off runtime reuse.
python -m singularity.main plan-cache-report --session-log logs/session_xxx.jsonl --output logs/benchmarks/plan_cache.json
# Optional runtime audit after a cache-assisted run; use it to prove cached plans stay verifier-safe.
python -m singularity.main plan-cache-runtime-report --session-log logs/session_cache_run.jsonl --output logs/benchmarks/plan_cache_runtime.json
python -m singularity.main plan-cache-gate --plan-cache-report logs/benchmarks/plan_cache.json --runtime-report logs/benchmarks/plan_cache_runtime.json --min-runtime-hits 1 --output logs/benchmarks/plan_cache_gate.json
python -m singularity.main run --goal "Craft torches" --enable-plan-cache --plan-cache logs/benchmarks/plan_cache.json --plan-cache-gate logs/benchmarks/plan_cache_gate.json
# Compare an ungated baseline against a module-assisted candidate across plan cache,
# visual grounding, action verification, skill memory, memory policy, and control policy signals.
python -m singularity.main agent-module-comparison-report --baseline-session-log logs/session_baseline.jsonl --candidate-session-log logs/session_candidate.jsonl --baseline-label m1_plain --candidate-label m1_module_profile --output logs/benchmarks/agent_module_comparison.json
# Separate world-state completion from the agent's terminal completion report.
python -m singularity.main terminal-commitment-report --session-log logs/session_xxx.jsonl --output logs/benchmarks/terminal_commitment.json
# Replay logged actions through deterministic pre-execution feasibility checks.
python -m singularity.main action-verification-report --session-log logs/session_xxx.jsonl --output logs/benchmarks/action_verification.json
# Replay rejected actions through verifier-guided repair candidate selection.
python -m singularity.main action-candidate-report --session-log logs/session_xxx.jsonl --output logs/benchmarks/action_candidate.json
# Aggregate action outcome values and failure-correction pairs for candidate scoring.
python -m singularity.main action-value-report --session-log logs/session_xxx.jsonl --output logs/benchmarks/action_value.json
python -m singularity.main run --goal "Craft torches" --action-value-feedback logs/benchmarks/action_value.json
# Mine XENON-style knowledge corrections from failed actions and successful recovery steps.
python -m singularity.main knowledge-correction-report --session-log logs/session_xxx.jsonl --output logs/benchmarks/knowledge_correction.json
python -m singularity.main knowledge-correction-review-template --knowledge-correction-report logs/benchmarks/knowledge_correction.json --output workspace/reviews/knowledge_correction_labels.jsonl
python -m singularity.main knowledge-correction-review-validate --label-file workspace/reviews/knowledge_correction_labels.jsonl --knowledge-correction-report logs/benchmarks/knowledge_correction.json --output logs/benchmarks/knowledge_correction_review.json
python -m singularity.main knowledge-correction-gate --knowledge-correction-report logs/benchmarks/knowledge_correction.json --output logs/benchmarks/knowledge_correction_gate.json
# Load only approved correction feedback into planner context; this remains advisory and does not mutate built-in recipes.
python -m singularity.main run --goal "Craft torches" --knowledge-correction-feedback logs/benchmarks/knowledge_correction.json --knowledge-correction-gate logs/benchmarks/knowledge_correction_gate.json
# Before spending live benchmark time, require approved gates plus suite-goal overlap.
python -m singularity.main benchmark --suite m1 --knowledge-correction-feedback logs/benchmarks/knowledge_correction.json --knowledge-correction-gate logs/benchmarks/knowledge_correction_gate.json --knowledge-correction-preflight-output logs/benchmarks/knowledge_correction_preflight.json
# Offline context ablation shows which goals actually receive XENON correction hints.
python -m singularity.main knowledge-correction-ablation --goal "Craft torches" --knowledge-correction-feedback logs/benchmarks/knowledge_correction.json --knowledge-correction-gate logs/benchmarks/knowledge_correction_gate.json --output logs/benchmarks/knowledge_correction_ablation.json
# Aggregate unresolved self-evolution counterexamples from monitor, verifier, terminal, plan/action, and action-value reports.
python -m singularity.main self-evolution-counterexample-report --self-evolution-report logs/benchmarks/self_evolution.json --terminal-commitment-report logs/benchmarks/terminal_commitment.json --plan-action-report logs/benchmarks/plan_action_compliance.json --action-verification-report logs/benchmarks/action_verification.json --action-value-report logs/benchmarks/action_value.json --output logs/benchmarks/self_evolution_counterexamples.json
# Gate any future automatic plan-suffix repair with explicit verifier and counterexample evidence.
python -m singularity.main self-evolution-gate --self-evolution-report logs/benchmarks/self_evolution.json --verifier-report logs/benchmarks/terminal_commitment.json --counterexample-report logs/benchmarks/self_evolution_counterexamples.json --output logs/benchmarks/self_evolution_gate.json

# Summarize SciCrafter-style discovery-to-application evidence from session logs
python -m singularity.main discovery-application-report --session-log logs/session_xxx.jsonl --output logs/benchmarks/discovery_application.json
# The saved JSON includes `discovery_feedback` for experiment-derived memory, task, and skill gates.
# Audit CausalGame-style contrastive evidence, bias risks, and unresolved
# counterexamples before promoting causal memories or causal-summary skills.
python -m singularity.main causal-evidence-report --session-log logs/session_xxx.jsonl --output logs/benchmarks/causal_evidence.json
python -m singularity.main causal-evidence-gate --causal-evidence-report logs/benchmarks/causal_evidence.json --output logs/benchmarks/causal_evidence_gate.json
# Use --no-require-bias-mitigation for exploratory triage; default audit mode
# rejects causal claims when logged selection/measurement/confounder risks are not mitigated.

# Summarize canonical actions, backend mappings, and low-level control candidates
python -m singularity.main action-abstraction-report --session-log logs/session_xxx.jsonl --output logs/benchmarks/action_abstraction.json
# The saved JSON includes `action_abstraction_feedback` policy hints for API-vs-visual-control selection.

# Compile a MineNPC-style mixed-initiative task preview and optional bounded validator report
python -m singularity.main mixed-initiative-report --goal "Collect 20 oak logs"
python -m singularity.main mixed-initiative-report --goal "Get me a pickaxe" --context-json "{\"memory_preferences\":{\"landmark\":\"weapon_storage\"}}"
python -m singularity.main mixed-initiative-report --goal "Craft 4 torches before night"
python -m singularity.main mixed-initiative-report --goal "Mine 3 coal ore within 12 blocks"
python -m singularity.main mixed-initiative-report --goal "Build a cobblestone wall"
# Use --evidence-file with pre_observation/post_observation/actions/recent_chat JSON to validate subtasks
# without admin commands, hidden world state, or global map shortcuts.

# Replay session logs through the same MineNPC-style template validators and
# compare bounded validator outcomes with logged GoalVerifier decisions.
# Reports also separate raw action success from bounded-policy-valid action success
# and aggregate action validity by template.
python -m singularity.main mixed-initiative-trace-report --session-log logs/session_xxx.jsonl --output logs/benchmarks/mixed_initiative_trace.json
# Built-in templates cover oak-log collection, pickaxe retrieval, generic craft/process,
# generic collect/mine, and build/place requests. The saved JSON still includes
# `template_candidates`, `mixed_initiative_feedback`, and
# `mixed_initiative_recommendations` for unsupported requests, action-policy issues,
# validator/GoalVerifier disagreements, template reviews, and candidate promotion.

# Aggregate trace recommendations into stable pending review items for template
# promotion, backend/action-policy inspection, or validator audits.
python -m singularity.main mixed-initiative-review-queue --trace-report logs/benchmarks/mixed_initiative_trace.json --output logs/benchmarks/mixed_review_queue.json
python -m singularity.main mixed-initiative-review-queue --session-log logs/session_xxx.jsonl

# Route review queue items into concrete follow-up experiment cases.
python -m singularity.main mixed-initiative-review-plan --review-queue logs/benchmarks/mixed_review_queue.json --output logs/benchmarks/mixed_review_plan.json
python -m singularity.main mixed-initiative-review-plan --session-log logs/session_xxx.jsonl

# Generate and validate operator approval labels before executing review-plan commands.
python -m singularity.main mixed-initiative-review-label-template --review-plan logs/benchmarks/mixed_review_plan.json --output workspace/reviews/mixed_review_labels.jsonl
python -m singularity.main mixed-initiative-review-label-validate --label-file workspace/reviews/mixed_review_labels.jsonl --review-plan logs/benchmarks/mixed_review_plan.json --output logs/benchmarks/mixed_review_label_validation.json

# Execute approved review labels through whitelisted internal report builders.
python -m singularity.main mixed-initiative-review-execute --label-file workspace/reviews/mixed_review_labels.jsonl --review-plan logs/benchmarks/mixed_review_plan.json --output-dir logs/benchmarks/mixed_review_artifacts --output logs/benchmarks/mixed_review_execution.json
python -m singularity.main mixed-initiative-review-execute --label-file workspace/reviews/mixed_review_labels.jsonl --review-plan logs/benchmarks/mixed_review_plan.json --dry-run

# Convert approved execution artifacts into reusable action/template policy feedback.
python -m singularity.main mixed-initiative-policy-patch --execution-report logs/benchmarks/mixed_review_execution.json --output logs/benchmarks/mixed_policy_patch.json
# Load approved patches into live runs or benchmark agents.
python -m singularity.main run --goal "Craft 4 torches" --mixed-policy-patch logs/benchmarks/mixed_policy_patch.json
python -m singularity.main benchmark --suite m1 --mixed-policy-patch logs/benchmarks/mixed_policy_patch.json
# Compare baseline vs patched action/template policy decisions before live runs.
python -m singularity.main mixed-initiative-policy-ablation --policy-patch logs/benchmarks/mixed_policy_patch.json --output logs/benchmarks/mixed_policy_ablation.json
# Run the selected live benchmark suite once without and once with the approved patch.
python -m singularity.main benchmark --suite m1 --mixed-policy-ablation --mixed-policy-patch logs/benchmarks/mixed_policy_patch.json --output mixed_policy_benchmark_ablation.json
# Gate patch promotion from offline, benchmark, and collaboration ablation evidence.
python -m singularity.main mixed-initiative-policy-gate --policy-ablation logs/benchmarks/mixed_policy_ablation.json --benchmark-ablation logs/benchmarks/mixed_policy_benchmark_ablation.json --collab-ablation logs/benchmarks/bm701_mixed_policy_ablation.json --output logs/benchmarks/mixed_policy_gate.json
# Require an approved gate report before a runtime Agent loads a mixed-policy patch.
python -m singularity.main run --goal "Craft 4 torches" --mixed-policy-patch logs/benchmarks/mixed_policy_patch.json --mixed-policy-gate logs/benchmarks/mixed_policy_gate.json
python -m singularity.main benchmark --suite m1 --mixed-policy-patch logs/benchmarks/mixed_policy_patch.json --mixed-policy-gate logs/benchmarks/mixed_policy_gate.json

# Bundle approved gates and feedback artifacts into a reusable runtime profile.
# Keep provider keys in environment variables or CLI only; profile JSON should
# contain paths and safe runtime switches, not secrets.
python -m singularity.main runtime-profile-build --name m1_visual_goal_critic --enable-goal-critic --goal-critic-gate logs/benchmarks/goal_critic_gate.json --enable-plan-cache --plan-cache logs/benchmarks/plan_cache.json --plan-cache-gate logs/benchmarks/plan_cache_gate.json --enable-weighted-memory-retrieval --memory-attribution-gate logs/benchmarks/memory_attribution_gate.json --enforce-memory-write-gate --memory-promptware-gate logs/benchmarks/memory_promptware_gate.json --mixed-policy-patch logs/benchmarks/mixed_policy_patch.json --mixed-policy-gate logs/benchmarks/mixed_policy_gate.json --output workspace/runtime/m1_visual_profile.json
python -m singularity.main runtime-profile-validate --runtime-profile workspace/runtime/m1_visual_profile.json --output logs/benchmarks/runtime_profile_validation.json
python -m singularity.main runtime-profile-security-audit --runtime-profile workspace/runtime/m1_visual_profile.json --output logs/benchmarks/runtime_profile_security.json
python -m singularity.main runtime-profile-suite-report --runtime-dir workspace/runtime --required-profile m1 --required-profile m2 --required-profile m7 --output logs/benchmarks/runtime_profile_suite.json
python -m singularity.main benchmark --suite m1 --runtime-profile workspace/runtime/m1_visual_profile.json --runtime-profile-suite-report logs/benchmarks/runtime_profile_suite.json --runtime-profile-suite-preflight-output logs/benchmarks/runtime_profile_suite_preflight.json
python -m singularity.main collab-benchmark --executor agent --runtime-profile workspace/runtime/m7_roles_profile.json --runtime-profile-suite-report logs/benchmarks/runtime_profile_suite.json --runtime-profile-suite-preflight-output logs/benchmarks/m7_runtime_profile_suite_preflight.json --preflight
# Runtime commands that load --runtime-profile automatically reject unreadable
# artifacts or promptware-like referenced content before live Agent startup.

# Seeded M1 profile from real offline action-value feedback:
python -m singularity.main runtime-profile-validate --runtime-profile workspace/runtime/m1_observed_action_value_profile.json --output logs/benchmarks/runtime_profile_validation_m1_2026-07-09.json
python -m singularity.main runtime-profile-security-audit --runtime-profile workspace/runtime/m1_observed_action_value_profile.json --output logs/benchmarks/runtime_profile_security_m1_2026-07-09.json
python -m singularity.main runtime-profile-suite-report --runtime-dir workspace/runtime --required-profile m1 --required-profile m2 --required-profile m7 --output logs/benchmarks/runtime_profile_suite_m1_2026-07-09.json

```json
{
  "type": "runtime_profile",
  "name": "m1_visual_goal_critic",
  "settings": {
    "enable_goal_critic": true,
    "coach_style": "explorer"
  },
  "gates": {
    "goal_critic": ["logs/benchmarks/goal_critic_gate.json"],
    "coach_style": ["logs/benchmarks/coach_style_gate.json"],
    "mixed_policy": ["logs/benchmarks/mixed_policy_gate.json"],
    "world_model": ["logs/benchmarks/world_model_gate.json"]
  },
  "artifacts": {
    "mixed_policy_patch": ["logs/benchmarks/mixed_policy_patch.json"],
    "world_model_feedback": ["logs/benchmarks/world_model.json"]
  }
}
```

# Replay held-out paraphrases and optional JSON/JSONL case files before promoting
# new mixed-initiative templates or changing auto-selection heuristics.
python -m singularity.main mixed-initiative-variant-report --output logs/benchmarks/mixed_initiative_variants.json
python -m singularity.main mixed-initiative-variant-report --case-file workspace/evals/mixed_variants.jsonl

# M2 benchmarks (LLM planning)
python -m singularity.main benchmark --suite m2

# Both
python -m singularity.main benchmark --suite all
```

### Running Tests
```powershell
# Goal generator tests
python tests/test_goal_generator.py

# M2 integration (needs OPENAI_API_KEY)
$env:OPENAI_API_KEY = "sk-..."
python tests/test_m2_integration.py
```

### Reviewing Skill Candidates
```powershell
# Extract candidates from a session log
python -m singularity.main skill-candidates --session logs/session_xxx.jsonl

# Extract with an explicit LLM fallback critic for candidates the deterministic verifier cannot prove
python -m singularity.main skill-candidates --session logs/session_xxx.jsonl --promotion-critic --llm-provider openai --llm-model MODEL_NAME --llm-base-url PROVIDER_URL

# If the session log includes screenshot_path, visual_analysis, grounded_resources,
# landmarks, structures, or nearby entity/block observations, the critic receives
# a compact visual_evidence summary automatically.

# Review queued candidate skills as SkillMaster-style create/update/retain/reject proposals.
# By default this requires approved task-stream transfer gate evidence before create/update proposals.
python -m singularity.main skill-edit-proposal-report --queue workspace/skills/skill_candidates.jsonl --skill-storage-path workspace/skills --task-stream-transfer-gate logs/benchmarks/task_stream_transfer_gate.json --output logs/benchmarks/skill_edit_proposals.json

# Check whether a session already has enough screenshot/VLM/API visual coverage
python -m singularity.main visual-trace-report --session-log logs/session_xxx.jsonl --output logs/benchmarks/visual_trace_report.json
python -m singularity.main visual-trace-report --session-log logs/session_xxx.jsonl --causal-summaries --failure-corrections
# The report separates raw screenshot references from verified local image files,
# missing paths, and invalid non-image files before you spend time labeling.
# `review-label-template` and visual ablations use the same gate: screenshot/VLM
# critic prompts receive only verified local image paths.

# Generate JSONL review-label templates before manual annotation
python -m singularity.main review-label-template --session-log logs/session_xxx.jsonl --mode both --output workspace/reviews/session_xxx_labels.jsonl
python -m singularity.main review-label-template --session-log logs/session_xxx.jsonl --mode promotion --causal-summaries --failure-corrections --output workspace/reviews/promotion_labels.jsonl

# Validate filled labels before using them for agreement metrics
python -m singularity.main review-label-validate --label-file workspace/reviews/session_xxx_labels.jsonl --output logs/benchmarks/session_xxx_label_validation.json

# Audit whether each planner cycle used bounded typed retrieval instead of raw accumulated transcript context
python -m singularity.main bounded-context-report --session-log logs/session_xxx.jsonl --output logs/benchmarks/bounded_context.json
python -m singularity.main memory-attribution-report --session-log logs/session_xxx.jsonl --output logs/benchmarks/memory_attribution.json
python -m singularity.main memory-attribution-gate --memory-attribution-report logs/benchmarks/memory_attribution.json --output logs/benchmarks/memory_attribution_gate.json
python -m singularity.main bounded-context-gate --bounded-context-report logs/benchmarks/bounded_context.json --output logs/benchmarks/bounded_context_gate.json

# Aggregate open-ended continual-learning diagnostics across progress, world knowledge, memory, action diversity, and horizon
python -m singularity.main continual-learning-report --session-log logs/session_xxx.jsonl --output logs/benchmarks/continual_learning.json

# Evaluate AgentCL-style controlled task streams for transfer gain, stability, held-out generalization, and memory/skill interference
# The repository includes seed streams for wood-to-tools, shelter, mining, navigation, and redstone transfer probes.
python -m singularity.main task-stream-transfer-report --stream-file workspace/evals/minecraft_task_streams.json --output logs/benchmarks/task_stream_transfer.json
# Gate memory or skill promotion on positive transfer, stable replay, held-out generalization, and low interference
python -m singularity.main task-stream-transfer-gate --transfer-report logs/benchmarks/task_stream_transfer.json --target skill:craft_stone_pickaxe --output logs/benchmarks/task_stream_transfer_gate.json

# Run the full offline visual review chain in one report
python -m singularity.main visual-review-pipeline --session-log logs/session_xxx.jsonl --mode both --output logs/benchmarks/visual_review_pipeline.json
python -m singularity.main visual-review-pipeline --session-log logs/session_xxx.jsonl --mode both --label-file workspace/reviews/session_xxx_labels.jsonl --run-ablations --promotion-critic --goal-critic --llm-provider openai --llm-model MODEL_NAME --llm-base-url PROVIDER_URL --output logs/benchmarks/visual_review_pipeline.json
# The pipeline runs visual trace coverage, generates review templates, validates
# filled labels, and optionally runs promotion, goal-verification, and visual
# action-grounding ablations. Combined label files are split by record type so
# promotion and goal-verification labels do not cross-match accidentally.

# Compare deterministic-only, API visual summary, and screenshot/VLM-assisted review
python -m singularity.main promotion-review-ablation --session-log logs/session_xxx.jsonl --promotion-critic --llm-provider openai --llm-model MODEL_NAME --llm-base-url PROVIDER_URL
python -m singularity.main promotion-review-ablation --session-log logs/session_xxx.jsonl --promotion-critic --causal-summaries --failure-corrections --label-file workspace/reviews/promotion_labels.jsonl --output logs/benchmarks/promotion_review_ablation.json

# Promotion label files may be JSONL records such as:
# {"source_log":"logs/session_xxx.jsonl","goal":"Inspect completed shelter frame","readiness":"approved","reviewer":"manual","notes":"screenshot confirms reusable skill"}

# Compare deterministic-only, API visual summary, and screenshot/VLM-assisted goal verification
python -m singularity.main goal-verification-ablation --session-log logs/session_xxx.jsonl --goal-critic --llm-provider openai --llm-model MODEL_NAME --llm-base-url PROVIDER_URL
python -m singularity.main goal-verification-ablation --session-log logs/session_xxx.jsonl --goal-critic --label-file workspace/reviews/goal_labels.jsonl --output logs/benchmarks/goal_verification_ablation.json

# Gate runtime --goal-critic use with offline/manual agreement evidence
python -m singularity.main goal-verification-critic-gate --goal-verification-ablation logs/benchmarks/goal_verification_ablation.json --label-validation logs/benchmarks/session_xxx_label_validation.json --output logs/benchmarks/goal_critic_gate.json
python -m singularity.main run --goal "Confirm base entrance is sealed" --goal-critic --goal-critic-gate logs/benchmarks/goal_critic_gate.json

# Label files may be JSONL records such as:
# {"source_log":"logs/session_xxx.jsonl","goal":"Confirm base entrance is sealed","readiness":"approved","reviewer":"manual","notes":"screenshot shows sealed entrance"}

# Or queue candidates automatically from passing benchmark traces
python -m singularity.main benchmark --suite m1 --ingest

# List pending candidates
python -m singularity.main skill-candidates

# Audit approved/custom skills as a typed graph with gates and provenance
python -m singularity.main skill-graph-report --skill-storage-path workspace/skills --output logs/benchmarks/skill_graph.json

# Score approved/custom skill contracts against a goal and current world state
python -m singularity.main skill-contract-report --skill-storage-path workspace/skills --goal "Craft torches" --world-state-json '{"inventory":{"coal":1,"stick":2},"nearby_blocks":[{"name":"coal_ore"}]}' --output logs/benchmarks/skill_contracts.json

# Audit MUSE-style per-skill replay, failure, and transfer memories
python -m singularity.main skill-memory-report --skill-storage-path workspace/skills --goal "Craft torches" --task-family crafting --output logs/benchmarks/skill_memory.json
# Audit the full skill lifecycle before treating task-family skills as runtime defaults
python -m singularity.main skill-lifecycle-report --skill-storage-path workspace/skills --goal "Craft torches" --task-family crafting --output logs/benchmarks/skill_lifecycle.json
# Gate task-family runtime-default skills with lifecycle, transfer, and optional quality evidence:
python -m singularity.main skill-runtime-default-gate --skill-lifecycle-report logs/benchmarks/skill_lifecycle.json --task-stream-transfer-gate logs/benchmarks/task_stream_transfer_gate.json --skill-memory-quality-gate logs/benchmarks/skill_memory_quality_gate.json --target-task-family crafting --require-skill-memory-quality-gate --output logs/benchmarks/skill_runtime_default_gate.json
# Load approved runtime-default gates into Agent runs, benchmarks, or M7 Agent roles.
# Review/rejected gates suppress learned default skills while built-in primitive skills remain available.
python -m singularity.main run --goal "Craft torches" --skill-runtime-default-gate logs/benchmarks/skill_runtime_default_gate.json
# Benchmark automatically preflights configured runtime-default gates before live suite execution.
# The preflight requires approved candidates whose task family overlaps the selected benchmark suite:
python -m singularity.main benchmark --suite m1 --skill-runtime-default-gate logs/benchmarks/skill_runtime_default_gate.json --skill-runtime-default-preflight-output logs/benchmarks/skill_runtime_default_preflight.json
# Approved skill candidates seed promotion/transfer memories automatically, and
# live failure-correction skills append success/failure memories during Agent runs.
# Skill-memory hints are retrieved into LLM planner context by inferred task family
# and typed as REUSE, AVOID, or REVIEW_ONLY before they can influence planning.
# Audit typed hint quality against later actions and goal outcomes in session logs:
python -m singularity.main skill-memory-quality-report --session-log logs/session_xxx.jsonl --output logs/benchmarks/skill_memory_quality.json
# The JSON includes `hint_quality_items` keyed by skill, task family, and hint type.
# Compare baseline vs quality-feedback-adjusted skill-memory hint ranking offline:
python -m singularity.main skill-memory-quality-ablation --skill-storage-path workspace/skills --quality-feedback logs/benchmarks/skill_memory_quality.json --goal "Craft torches" --task-family crafting --output logs/benchmarks/skill_memory_quality_ablation.json
# Gate REUSE promotion by matching localized `hint_quality_items` against skill-local memories:
python -m singularity.main skill-memory-quality-gate --skill-memory-report logs/benchmarks/skill_memory.json --quality-feedback logs/benchmarks/skill_memory_quality.json --output logs/benchmarks/skill_memory_quality_gate.json
# Feed approved quality feedback back into runtime retrieval ranking without mutating skills:
python -m singularity.main run --goal "Craft torches" --skill-memory-quality-feedback logs/benchmarks/skill_memory_quality.json --skill-memory-quality-gate logs/benchmarks/skill_memory_quality_gate.json
# When `--skill-memory-quality-gate` is supplied to run/autonomous/benchmark/collab-benchmark,
# feedback is loaded only if every gate report is `approved`.
# Benchmark automatically runs the quality preflight when `--skill-memory-quality-feedback` is supplied.
# The preflight requires an approved gate and an offline ranking effect before live suite runs:
python -m singularity.main benchmark --suite m1 --skill-memory-quality-feedback logs/benchmarks/skill_memory_quality.json --skill-memory-quality-gate logs/benchmarks/skill_memory_quality_gate.json --skill-memory-quality-preflight-output logs/benchmarks/skill_memory_quality_preflight.json
# Use --no-skill-memory-context on run/autonomous/benchmark/collab-benchmark for baselines.
python -m singularity.main benchmark --suite m1 --skill-memory-ablation --output logs/benchmarks/skill_memory_ablation.json

# Approve or reject a candidate
python -m singularity.main skill-candidates --approve CANDIDATE_ID
python -m singularity.main skill-candidates --approve CANDIDATE_ID --promotion-critic --llm-provider openai --llm-model MODEL_NAME --llm-base-url PROVIDER_URL
python -m singularity.main discovery-application-report --session-log logs/session_xxx.jsonl --output logs/benchmarks/discovery_application.json
python -m singularity.main skill-candidates --approve CANDIDATE_ID --discovery-skill-gate logs/benchmarks/discovery_application.json
python -m singularity.main skill-candidates --approve CANDIDATE_ID --task-stream-transfer-gate logs/benchmarks/task_stream_transfer_gate.json
python -m singularity.main skill-candidates --approve CANDIDATE_ID --causal-evidence-gate logs/benchmarks/causal_evidence.json
python -m singularity.main skill-candidates --reject CANDIDATE_ID --reason "too brittle"

# Approved causal/correction skills are loaded from workspace/skills by the agent.
# They appear as planner hints and can trigger correction sequences after matching failures.
```

### Preparing Collaboration Benchmarks
```powershell
# Dry-run BM-701 feasibility and task assignment into shared state
python -m singularity.main collab-benchmark --spec workspace/benchmarks/m7_time_sensitive_shelter.json

# Save dry-run plus static schedule analysis
python -m singularity.main collab-benchmark --spec workspace/benchmarks/m7_time_sensitive_shelter.json --output logs/benchmarks/bm701_schedule_report.json

# Execute the synchronous collaboration state-transition loop
python -m singularity.main collab-benchmark --spec workspace/benchmarks/m7_time_sensitive_shelter.json --execute

# Execute assigned tasks through live Agent.run_goal calls
python -m singularity.main collab-benchmark --spec workspace/benchmarks/m7_time_sensitive_shelter.json --execute --executor agent

# Execute live collaboration roles through separate bot bridges
# `--executor agent` prints and saves the exact bridge launch plan.
node src/bot/bot_server.js --username Singularity_resource_runner --bridge-port 3000
node src/bot/bot_server.js --username Singularity_leader_builder --bridge-port 3001
node src/bot/bot_server.js --username Singularity_single_agent --bridge-port 3002
python -m singularity.main collab-benchmark --spec workspace/benchmarks/m7_time_sensitive_shelter.json --preflight --executor agent --runtime-profile workspace/runtime/m7_roles_profile.json --runtime-profile-suite-report logs/benchmarks/runtime_profile_suite.json --runtime-profile-suite-preflight-output logs/benchmarks/bm701_runtime_profile_suite_preflight.json --role-bridge-port resource_runner=3000 --role-bridge-port leader_builder=3001 --role-bridge-port single_agent=3002 --single-agent-baseline
python -m singularity.main collab-benchmark --spec workspace/benchmarks/m7_time_sensitive_shelter.json --execute --executor agent --role-bridge-port resource_runner=3000 --role-bridge-port leader_builder=3001 --role-bridge-port single_agent=3002 --single-agent-baseline --output logs/benchmarks/bm701_collab_report.json
# Load approved mixed-initiative policy patches into every Agent executor role.
python -m singularity.main collab-benchmark --spec workspace/benchmarks/m7_time_sensitive_shelter.json --execute --executor agent --role-bridge-port resource_runner=3000 --role-bridge-port leader_builder=3001 --mixed-policy-patch logs/benchmarks/mixed_policy_patch.json --mixed-policy-gate logs/benchmarks/mixed_policy_gate.json --output logs/benchmarks/bm701_mixed_policy_report.json
# Compare Agent-backed collaboration once without and once with the approved patch.
python -m singularity.main collab-benchmark --spec workspace/benchmarks/m7_time_sensitive_shelter.json --execute --executor agent --mixed-policy-ablation --role-bridge-port resource_runner=3000 --role-bridge-port leader_builder=3001 --mixed-policy-patch logs/benchmarks/mixed_policy_patch.json --mixed-policy-gate logs/benchmarks/mixed_policy_gate.json --output logs/benchmarks/bm701_mixed_policy_ablation.json

# Use a custom shared-state file
python -m singularity.main collab-benchmark --spec workspace/benchmarks/m7_time_sensitive_shelter.json --state-path workspace/multiagent/bm701_state.json
```

`collab-benchmark --execute` dispatches at most one runnable task per role in each wave, so separate live bot bridges can work in parallel while shared-state commits stay serialized. With `--executor agent`, the JSON report includes `agent_bridge_launch_plan` and optional `single_agent_baseline_bridge_launch_plan`; each plan lists the exact `node src/bot/bot_server.js` command and reports duplicate-port conflicts. Agent bridge preflight fails fast on duplicate role ports, so use either `--bridge-port-base` or explicit `--role-bridge-port ROLE=PORT` values for multi-role live runs. `collab-benchmark --output` writes `schedule_analysis` for the collaboration spec. When execution runs, it also writes `execution.dispatch_mode`, `execution.dispatch_batches`, `execution.max_parallel_tasks`, and `execution_schedule_comparison`, which aligns each task's predicted start/finish time with the measured start/finish/duration and reports actual overlap metrics such as `actual_peak_parallel_tasks`, `actual_parallel_overlap_s`, `actual_parallel_efficiency`, and `overlapping_task_pairs`. With `--single-agent-baseline`, it additionally writes `single_agent_baseline_schedule`, `schedule_comparison`, and `single_agent_baseline_schedule_execution_comparison`. With `--mixed-policy-ablation`, it writes baseline/patched execution reports plus role session-log `control_policy` summaries for backend, preferred-control, and fallback changes.

## Architecture

```
User Goal (NL) -> Planner (LLM) -> TaskSystem -> SkillLibrary -> ActionController -> Mineflayer Bot
                                               |                                    |
                                               v                                    v
                                           Memory (L0-L6)                     MC Server
                                               ^
                                               |
                                           Observer -> Reflector
```

## Key Modules

| Module | File | Purpose |
|--------|------|---------|
| Agent | core/agent.py | Main observe-think-act loop |
| Planner | core/planner.py | LLM-powered goal decomposition |
| TaskSystem | core/task_system.py | Hierarchical task state machine |
| SkillLibrary | core/skill_library.py | 17 builtin + custom skills |
| Memory | core/memory.py | L0-L6 layered memory system |
| Observer | observation/observer.py | Game state collection (32-block scan) |
| ActionController | action/controller.py | Safe action execution |
| GoalGenerator | core/goal_generator.py | Autonomous survival goals (M4) |
| Explorer | core/explorer.py | Open-world exploration (M5) |
| SkillExtractor | core/skill_extractor.py | Extract skills from traces (M3) |
| KnowledgeBase | data/knowledge_base.py | Crafting recipes and game knowledge |
| SessionLogger | logging/session_logger.py | JSONL structured logging |

## LLM Provider Configuration

### OpenAI
```
--llm-provider openai --llm-model gpt-4o-mini
```

### Anthropic
```
--llm-provider anthropic --llm-model claude-3-5-sonnet-20241022
```

### DeepSeek
```
--llm-provider openai --llm-model deepseek-chat --llm-base-url https://api.deepseek.com/v1
```

### Qwen
```
--llm-provider openai --llm-model qwen-turbo --llm-base-url https://dashscope.aliyuncs.com/compatible-mode/v1
```

### Ollama (local)
```
--llm-provider ollama --llm-model llama3
```
