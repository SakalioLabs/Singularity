# M6 Vision Module - Implementation Status

## What Was Built
- **VisionAnalyzer** (`src/singularity/vision/analyzer.py`):
  - Analyzes game observations to detect resources and dangers
  - Supports OpenAI Vision API for screenshot analysis (when API key available)
  - Falls back to text-based analysis when no VLM available
  - Detects ores, logs from nearby_blocks data
  - Detects hostile mobs from nearby_entities data
  - Grounds detected resources through the knowledge graph: drops, required tool tier, recommended tool, currently available tool, harvestability, source blocks, and craft uses
  
- **VisualMemory** (`src/singularity/vision/visual_memory.py`):
  - Stores visual observations with timestamps
  - Search by type or query string
  - Configurable max entries with automatic pruning

- **Visual trace evaluation tools**:
  - `visual-trace-report` audits session logs for screenshot paths, VLM summaries, API visual fields, visual goal coverage, and visual promotion-candidate coverage.
  - Screenshot coverage now distinguishes raw screenshot references from verified local image files, missing files, and invalid non-image payloads.
  - `review-label-template` generates JSONL manual-review templates for screenshot-backed goal verification and promotion-review ablations.
  - `review-label-validate` checks filled manual labels for valid readiness values, usable match keys, and verified screenshot evidence before agreement ablations consume them.
  - `visual-review-pipeline` combines trace audit, review-template generation, label validation, and optional promotion/goal visual ablations into one offline report; combined label files are split by record type before agreement metrics are loaded.
  - Promotion-review and goal-verification screenshot/VLM ablations now pass only verified local screenshot paths to critics and only count screenshot/VLM improvements when at least one screenshot file is verified.

- **Agent integration**:
  - Agent observations are enriched with `VisionAnalyzer` outputs by default: `grounded_resources`, `visual_resources`, and `dangers`.
  - Session logs include lightweight `vision` events for later visual trace coverage, promotion review, and goal-verification ablations.
  - Recent visual observations are stored in `VisualMemory` and summarized into the LLM planner context.
  - `--no-vision-analysis` disables the enrichment for baseline runs.
  - `VisualActionAdvisor` converts grounded resources and nearby dangers into conservative action hints. The Agent now uses those hints to move within reach of visible harvestable resources, look at them before digging, fill missing `dig` coordinates, and prepend a retreat action when a hostile entity is close. `--no-visual-action-grounding` disables this online intervention for ablations.
  - Session summaries and benchmark results now include visual action grounding metrics: suggestion events, total suggestions, intervention counts, intervention phases, suggestion/intervention kinds, action types, and goals.
  - `visual-action-ablation` compares disabled versus enabled visual action grounding on built-in offline cases for coordinate fill, resource approach, target focus, danger retreat, and unrelated-resource no-op behavior. It can also mine replay cases from session JSONL `visual_action_intervention` events and nearby logged plans.
  - `visual-review-pipeline --run-ablations` now includes visual action grounding ablation summaries alongside promotion-review and goal-verification visual ablations.
  - `benchmark --visual-action-ablation` runs live benchmark tasks twice with visual action grounding disabled and enabled, then reports status changes, visual action counts, and intervention phases.
  - `--capture-screenshots` enables an optional bridge renderer hook. The Node bridge can now load a renderer module with `--screenshot-plugin`, accept file paths, `Buffer`, or base64 image outputs, write byte outputs to the requested path, and report `file_exists`/`file_size`. The included `screenshot_plugin_prismarine_viewer.js` plugin uses prismarine-viewer once optional renderer dependencies are installed. The Agent passes verified paths into `VisionAnalyzer`, records them in `vision` events, and stores them in `VisualMemory`. Capture remains disabled by default and plain Mineflayer runs report unsupported until a renderer/plugin is attached.
  - `preflight --screenshot-renderer` runs the prismarine screenshot plugin's dependency self-check, and `benchmark --preflight --capture-screenshots` performs the same renderer check before live benchmark suites.
  - `docker/screenshot-bridge` provides a Docker/WSL-friendly screenshot bridge path with `node-canvas-webgl` native dependencies isolated from the default install; the Node bridge now supports `--bridge-host 0.0.0.0` for container port mapping.
  - `screenshot-smoke-test` requests one live bridge screenshot and verifies the resulting image file is visible and valid from Python, catching missing Docker volume mounts before full Agent sessions.

## Test Coverage (52 tests + Docker recipe checks)
- VisionAnalyzer: Resource detection, danger detection, empty input, API ready
- Graph grounding: harvestable ores, missing-tool resources, hand-collectable logs, prioritized resource targets
- VisualMemory: Add, search, prune, clear, count
- Integration: End-to-end with observer data and memory
- Visual action grounding: visible resource approach/focus, harvest coordinates, danger retreat suggestions, Agent coordinate fill, Agent approach/focus-action prepend, Agent safety-action prepend, session/benchmark intervention metrics, built-in disabled-vs-enabled offline ablation, session-log replay ablation, unified visual-review-pipeline ablation reporting, and live benchmark disabled-vs-enabled ablation reporting
- Bridge contract: screenshot capture command dispatch and Agent screenshot-path propagation into visual logs/memory
- Node screenshot plugin loader: renderer modules can attach screenshot capture and return image bytes for bridge file output
- Prismarine screenshot plugin: optional dependency diagnostics, output format selection, and camera yaw/pitch target math
- Screenshot renderer preflight: Python preflight parses the Node plugin dependency report and surfaces actionable install/WSL/Docker remedies
- Screenshot smoke test: valid bridge captures pass local image validation, while container-only files produce a Docker volume-mount remedy
- Visual trace quality gate: verified local image files, missing screenshot paths, and invalid screenshot payloads
- Ablation gate: missing or invalid screenshot paths are filtered before promotion/goal critics see screenshot-backed evidence
- Manual label validation: label files can be checked before agreement metrics are computed
- Visual review pipeline: trace coverage, template generation, label validation, and optional promotion/goal ablations are exercised together

## Next Steps
1. Build and run `docker/screenshot-bridge` with `logs/screenshots` mounted, then pass `screenshot-smoke-test`
2. Capture a real screenshot-backed live session with `--capture-screenshots`
3. VLM integration with real screenshots
4. Run live visual action grounding against resource and danger scenarios
5. Screenshot-backed navigation/action grounding
