# Server Setup Guide

## Prerequisites
- Java 17+ (Paper 1.20.4)
- Node.js 18+
- Python 3.10+

## Steps
1. Install Java 17: https://adoptium.net/
2. Download Paper 1.20.4 from https://papermc.io/
3. Start server: java -Xmx2G -jar paper.jar nogui
4. Accept EULA after reading it: set eula=true in eula.txt
5. Set online-mode=false in server.properties
6. npm install
7. node src/bot/bot_server.js --bridge-port 3000
8. python -m singularity.main preflight --bridge-port 3000
9. python -m singularity.main run --goal "Gather 3 oak logs"

## Preflight Gates

```powershell
# Checks Python, Node, npm, and Mineflayer packages only
python -m singularity.main preflight --skip-network

# Also checks bridge TCP, bot spawn health, and MC server reachability
python -m singularity.main preflight
```

If `bot_bridge` passes but `bot_session` fails, restart `node src/bot/bot_server.js` after the Minecraft server is running.

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
