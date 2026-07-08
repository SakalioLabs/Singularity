FROM node:20-bookworm-slim

ENV NODE_ENV=production
ENV MC_HOST=host.docker.internal
ENV MC_PORT=25565
ENV MC_USERNAME=SingularityScreenshot
ENV MC_VERSION=1.20.4
ENV BRIDGE_HOST=0.0.0.0
ENV BRIDGE_PORT=3000
ENV SCREENSHOT_WIDTH=512
ENV SCREENSHOT_HEIGHT=512
ENV SCREENSHOT_VIEW_DISTANCE=4
ENV SCREENSHOT_RENDER_DELAY_MS=500

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        git \
        make \
        g++ \
        python3 \
        xvfb \
        xserver-xorg-dev \
        libxi-dev \
        libxext-dev \
        libgl1-mesa-dev \
        libglu1-mesa-dev \
        libgl1-mesa-dri \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev
RUN npm install --omit=dev prismarine-viewer three PrismarineJS/node-canvas-webgl

COPY src/bot ./src/bot

EXPOSE 3000
VOLUME ["/app/logs/screenshots"]

CMD ["sh", "-lc", "node src/bot/screenshot_plugin_prismarine_viewer.js --check && xvfb-run -s \"-ac -screen 0 ${SCREENSHOT_WIDTH}x${SCREENSHOT_HEIGHT}x24\" node src/bot/bot_server.js --host ${MC_HOST} --port ${MC_PORT} --username ${MC_USERNAME} --version ${MC_VERSION} --bridge-host ${BRIDGE_HOST} --bridge-port ${BRIDGE_PORT} --screenshot-plugin src/bot/screenshot_plugin_prismarine_viewer.js --screenshot-width ${SCREENSHOT_WIDTH} --screenshot-height ${SCREENSHOT_HEIGHT} --screenshot-view-distance ${SCREENSHOT_VIEW_DISTANCE} --screenshot-render-delay-ms ${SCREENSHOT_RENDER_DELAY_MS}"]
