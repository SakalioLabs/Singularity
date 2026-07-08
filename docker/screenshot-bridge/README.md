# Screenshot Bridge Container

This container runs the Node Mineflayer bridge with the optional prismarine-viewer screenshot plugin enabled. It keeps `node-canvas-webgl` out of the default local install while giving Windows users a Docker/WSL-friendly path for real screenshot traces.

## Build

```powershell
docker build -f docker/screenshot-bridge/Dockerfile -t singularity-screenshot-bridge .
```

## Run

For Docker Desktop on Windows or macOS, `host.docker.internal` usually reaches a Minecraft server running on the host:

```powershell
New-Item -ItemType Directory -Force logs\screenshots | Out-Null
docker run --rm -it -p 3000:3000 `
  -v ${PWD}\logs\screenshots:/app/logs/screenshots `
  -e MC_HOST=host.docker.internal `
  -e MC_PORT=25565 `
  -e MC_USERNAME=SingularityScreenshot `
  singularity-screenshot-bridge
```

On Linux, add a host-gateway mapping when the Minecraft server runs on the host:

```bash
mkdir -p logs/screenshots
docker run --rm -it -p 3000:3000 \
  -v "$PWD/logs/screenshots:/app/logs/screenshots" \
  --add-host=host.docker.internal:host-gateway \
  -e MC_HOST=host.docker.internal \
  -e MC_PORT=25565 \
  -e MC_USERNAME=SingularityScreenshot \
  singularity-screenshot-bridge
```

Then connect the Python agent to the mapped bridge:

```powershell
python -m singularity.main preflight --bridge-host 127.0.0.1 --bridge-port 3000
python -m singularity.main screenshot-smoke-test --bridge-host 127.0.0.1 --bridge-port 3000 --screenshot-dir logs/screenshots
python -m singularity.main run --goal "Inspect shelter entrance" --capture-screenshots --screenshot-dir logs/screenshots --bridge-host 127.0.0.1 --bridge-port 3000
```

## Renderer Options

Set these environment variables to tune the renderer:

- `SCREENSHOT_WIDTH`
- `SCREENSHOT_HEIGHT`
- `SCREENSHOT_VIEW_DISTANCE`
- `SCREENSHOT_RENDER_DELAY_MS`

The container checks `src/bot/screenshot_plugin_prismarine_viewer.js --check` before starting the bridge, so missing optional renderer dependencies fail early.
