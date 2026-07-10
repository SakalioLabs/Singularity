# Server Setup Guide

## Prerequisites
- Java 17+ (Paper 1.20.4)
- Node.js 18+
- Python 3.10+

## Controlled M1 Setup

1. Install Java 17+ and download a Paper server for Minecraft 1.20.4.
2. Place the exact jar at `mc-server/server.jar`.
3. Start it once from `mc-server/` with `java -Xmx2G -jar server.jar nogui`.
4. Read the Minecraft EULA. Accept it manually by setting `eula=true` in `mc-server/eula.txt`. No Singularity script edits this file.
5. Set these values in `mc-server/server.properties`:

   ```properties
   level-seed=12345
   online-mode=false
   server-port=25565
   ```

6. Start the server, run `op Singularity` in its console, then stop it cleanly. Confirm `Singularity` is present in `mc-server/ops.json`.
7. Install deterministic dependencies with `python -m pip install -e .` and `npm ci`.
8. Run one task in one fresh episode:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/m1-runtime.ps1 -RunBenchmark -TaskId BM-001
   ```

The script uses Bridge port `30000`, creates a unique level name, records the Paper jar SHA-256, verifies the fixed M1 protocol/reset, runs exactly one task, restores `server.properties`, and stops only processes it started. Repeat the command with BM-002 through BM-005 only after the preceding gate is truthful.

## Preflight Gates

```powershell
# Checks Python, Node, npm, and Mineflayer packages only
python -m singularity.main preflight --skip-network

# Starts a controlled server/bridge episode and runs protocol-aware M1 preflight only
powershell -ExecutionPolicy Bypass -File scripts/m1-runtime.ps1
```

Raw preflight files are runtime diagnostics and never count as live benchmark success. Port `3000` may be occupied by an unrelated local service; the controlled M1 path deliberately uses `30000`.

## Optional Screenshot Plugin

`--capture-screenshots` on the Python agent requires a renderer on the Node bridge. Start the bridge with a plugin module when one is available:

```powershell
npm install prismarine-viewer three PrismarineJS/node-canvas-webgl
python -m singularity.main preflight --skip-network --screenshot-renderer
node src/bot/bot_server.js --bridge-port 3000 --screenshot-plugin src/bot/screenshot_plugin_prismarine_viewer.js
python -m singularity.main run --goal "Inspect shelter entrance" --capture-screenshots --screenshot-dir logs/screenshots
```

The plugin may export a function, `attach(bot, context)`, `attachScreenshotPlugin(bot, context)`, `install(bot, context)`, or `captureScreenshot(outputPath, context)`. It can return a file path, a `Buffer`, base64 image bytes, or an object with `screenshot_path`, `path`, `buffer`, or `base64`. The bridge writes byte outputs to the requested path and reports `file_exists` plus `file_size` in the capture result.

The included `src/bot/screenshot_plugin_prismarine_viewer.js` plugin follows the official prismarine-viewer/headless approach and keeps its renderer dependencies optional. `node-canvas-webgl` may require WSL, Docker, or Linux native packages on Windows.

Renderer options can be passed to the bridge with `--screenshot-width`, `--screenshot-height`, `--screenshot-view-distance`, and `--screenshot-render-delay-ms`.

`benchmark --preflight --capture-screenshots` also checks the optional screenshot renderer before running a live suite.

### Docker Screenshot Bridge

If `node-canvas-webgl` is painful to install on the host, build the screenshot bridge container instead:

```powershell
npm run docker:screenshot:build
New-Item -ItemType Directory -Force logs\screenshots | Out-Null
docker run --rm -it -p 3000:3000 -v ${PWD}\logs\screenshots:/app/logs/screenshots -e MC_HOST=host.docker.internal -e MC_PORT=25565 -e MC_USERNAME=SingularityScreenshot singularity-screenshot-bridge
python -m singularity.main preflight --bridge-host 127.0.0.1 --bridge-port 3000
python -m singularity.main screenshot-smoke-test --bridge-host 127.0.0.1 --bridge-port 3000 --screenshot-dir logs/screenshots
python -m singularity.main run --goal "Inspect shelter entrance" --capture-screenshots --screenshot-dir logs/screenshots --bridge-host 127.0.0.1 --bridge-port 3000
```

See `docker/screenshot-bridge/README.md` for Linux `host-gateway` flags and renderer tuning variables.

## Multi-Bot Bridges

Run one Node bridge per Minecraft bot when testing M7 collaboration:

```powershell
node src/bot/bot_server.js --username Singularity_resource_runner --bridge-port 3000
node src/bot/bot_server.js --username Singularity_leader_builder --bridge-port 3001
node src/bot/bot_server.js --username Singularity_single_agent --bridge-port 3002
python -m singularity.main collab-benchmark --preflight --executor agent --role-bridge-port resource_runner=3000 --role-bridge-port leader_builder=3001 --role-bridge-port single_agent=3002 --single-agent-baseline
python -m singularity.main collab-benchmark --execute --executor agent --role-bridge-port resource_runner=3000 --role-bridge-port leader_builder=3001 --role-bridge-port single_agent=3002 --single-agent-baseline --output logs/benchmarks/bm701_collab_report.json
```
