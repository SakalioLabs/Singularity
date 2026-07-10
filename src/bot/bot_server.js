/**
 * Mineflayer Bot Bridge Server
 * 
 * Runs a persistent TCP socket server that the Python agent connects to.
 * Handles commands from the agent and returns bot state.
 * 
 * Usage: node bot_server.js [--host localhost] [--port 25565] [--bridge-port 3000]
 * Optional screenshots: --screenshot-plugin ./path/to/plugin.js
 */

const { Vec3 } = require('vec3');
const mineflayer = require('mineflayer');
const net = require('net');
const fs = require('fs');
const path = require('path');
const { pathfinder, Movements, goals } = require('mineflayer-pathfinder');

// Parse CLI args
const args = process.argv.slice(2);
function getArg(name, defaultVal) {
    const idx = args.indexOf(`--${name}`);
    return idx >= 0 && args[idx + 1] ? args[idx + 1] : defaultVal;
}

const MC_HOST = getArg('host', 'localhost');
const MC_PORT = parseInt(getArg('port', '25565'));
const MC_USERNAME = getArg('username', 'Singularity');
const MC_VERSION = getArg('version', '1.20.4');
const BRIDGE_HOST = getArg('bridge-host', '127.0.0.1');
const BRIDGE_PORT = parseInt(getArg('bridge-port', '3000'));
const SCREENSHOT_PLUGIN = getArg('screenshot-plugin', '');
const SCREENSHOT_OPTIONS = {
    width: parseInt(getArg('screenshot-width', '512')),
    height: parseInt(getArg('screenshot-height', '512')),
    viewDistance: parseInt(getArg('screenshot-view-distance', '4')),
    renderDelayMs: parseInt(getArg('screenshot-render-delay-ms', '500')),
};

let bot = null;
let botReady = false;
let lastBotError = "";
let screenshotPluginCapture = null;
let screenshotPluginStatus = {
    configured: Boolean(SCREENSHOT_PLUGIN),
    loaded: false,
    supported: false,
    source: SCREENSHOT_PLUGIN,
    options: SCREENSHOT_OPTIONS,
    error: '',
};

function resolveScreenshotPluginSpec(pluginSpec) {
    const spec = String(pluginSpec || '').trim();
    if (!spec) return '';
    const looksLikePath =
        path.isAbsolute(spec) ||
        spec.startsWith('.') ||
        spec.includes('/') ||
        spec.includes('\\');
    return looksLikePath ? path.resolve(process.cwd(), spec) : spec;
}

function publicScreenshotPluginStatus(status) {
    const { capture, ...publicStatus } = status || {};
    return publicStatus;
}

function attachScreenshotPlugin(botInstance, pluginSpec, options = {}) {
    const source = String(pluginSpec || '').trim();
    const status = {
        configured: Boolean(source),
        loaded: false,
        supported: false,
        source,
        resolved: '',
        options,
        error: '',
        capture: null,
    };
    if (!source) return status;

    try {
        const resolved = resolveScreenshotPluginSpec(source);
        status.resolved = resolved;
        const moduleValue = require(resolved);
        const plugin = moduleValue && moduleValue.default ? moduleValue.default : moduleValue;
        const context = {
            bot: botInstance,
            fs,
            path,
            options,
            minecraft: {
                host: MC_HOST,
                port: MC_PORT,
                username: MC_USERNAME,
                version: MC_VERSION,
            },
            bridge: {
                port: BRIDGE_PORT,
            },
        };

        let attached = null;
        if (typeof plugin === 'function') {
            attached = plugin(botInstance, context);
        } else if (plugin && typeof plugin.attachScreenshotPlugin === 'function') {
            attached = plugin.attachScreenshotPlugin(botInstance, context);
        } else if (plugin && typeof plugin.attach === 'function') {
            attached = plugin.attach(botInstance, context);
        } else if (plugin && typeof plugin.install === 'function') {
            attached = plugin.install(botInstance, context);
        }

        let capture = null;
        if (typeof attached === 'function') {
            capture = attached;
        } else if (attached && typeof attached.captureScreenshot === 'function') {
            capture = attached.captureScreenshot.bind(attached);
        } else if (plugin && typeof plugin.captureScreenshot === 'function') {
            capture = plugin.captureScreenshot.bind(plugin);
        } else if (botInstance && typeof botInstance.captureScreenshot === 'function') {
            capture = botInstance.captureScreenshot.bind(botInstance);
        }

        if (capture && botInstance && typeof botInstance.captureScreenshot !== 'function') {
            botInstance.captureScreenshot = capture;
        }

        status.loaded = true;
        status.supported = Boolean(capture);
        status.capture = capture;
        if (!capture) {
            status.error = 'plugin loaded but did not expose a screenshot capture function';
        }
    } catch (e) {
        status.error = e.message;
    }
    return status;
}

function imageBytesFromCaptureResult(result) {
    if (Buffer.isBuffer(result)) return result;
    if (!result || typeof result !== 'object') return null;
    for (const key of ['buffer', 'bytes', 'image']) {
        if (Buffer.isBuffer(result[key])) return result[key];
    }
    for (const key of ['base64', 'image_base64']) {
        if (typeof result[key] === 'string' && result[key]) {
            return Buffer.from(result[key], 'base64');
        }
    }
    return null;
}

function screenshotPathFromCaptureResult(result, requestedPath) {
    if (typeof result === 'string' && result) return result;
    if (result && typeof result === 'object') {
        for (const key of ['screenshot_path', 'path', 'file', 'filename']) {
            if (typeof result[key] === 'string' && result[key]) return result[key];
        }
    }
    return requestedPath || '';
}

function fileStatusForScreenshot(screenshotPath) {
    if (!screenshotPath) return { file_exists: false, file_size: 0 };
    const resolved = path.resolve(screenshotPath);
    try {
        const stat = fs.statSync(resolved);
        return {
            file_exists: stat.isFile(),
            file_size: stat.isFile() ? stat.size : 0,
        };
    } catch (e) {
        return { file_exists: false, file_size: 0 };
    }
}

function findScreenshotCapture(activeBot) {
    if (typeof screenshotPluginCapture === 'function') return screenshotPluginCapture;
    if (activeBot && typeof activeBot.captureScreenshot === 'function') {
        return activeBot.captureScreenshot.bind(activeBot);
    }
    if (activeBot?.viewer && typeof activeBot.viewer.captureScreenshot === 'function') {
        return activeBot.viewer.captureScreenshot.bind(activeBot.viewer);
    }
    if (activeBot?.viewer && typeof activeBot.viewer.screenshot === 'function') {
        return activeBot.viewer.screenshot.bind(activeBot.viewer);
    }
    return null;
}

function createCaptureScreenshotHandler(getState = () => ({ bot, botReady })) {
    return async (params = {}) => {
        const requestedPath = params.path || '';
        const state = getState() || {};
        const activeBot = state.bot;
        const ready = Boolean(state.botReady && activeBot?.entity);
        try {
            if (!activeBot || !ready) {
                return {
                    success: false,
                    supported: false,
                    error: 'bot is not ready for screenshot capture',
                    requested_path: requestedPath,
                    screenshot_plugin: publicScreenshotPluginStatus(screenshotPluginStatus),
                };
            }

            const captureFn = findScreenshotCapture(activeBot);
            if (!captureFn) {
                return {
                    success: false,
                    supported: false,
                    error: 'Screenshot capture requires a renderer plugin that exposes captureScreenshot or screenshot',
                    requested_path: requestedPath,
                    screenshot_plugin: publicScreenshotPluginStatus(screenshotPluginStatus),
                };
            }

            const result = await captureFn(requestedPath, { path: requestedPath, bot: activeBot });
            if (result && typeof result === 'object' && result.success === false) {
                return {
                    success: false,
                    supported: true,
                    error: result.error || 'renderer reported screenshot capture failure',
                    requested_path: requestedPath,
                    screenshot_plugin: publicScreenshotPluginStatus(screenshotPluginStatus),
                };
            }

            const bytes = imageBytesFromCaptureResult(result);
            const screenshotPath = screenshotPathFromCaptureResult(result, requestedPath);
            if (bytes) {
                if (!screenshotPath) {
                    return {
                        success: false,
                        supported: true,
                        error: 'renderer returned image bytes but no output path was requested',
                        screenshot_plugin: publicScreenshotPluginStatus(screenshotPluginStatus),
                    };
                }
                fs.mkdirSync(path.dirname(path.resolve(screenshotPath)), { recursive: true });
                fs.writeFileSync(screenshotPath, bytes);
            }

            if (!screenshotPath) {
                return {
                    success: false,
                    supported: true,
                    error: 'renderer did not return a screenshot path',
                    screenshot_plugin: publicScreenshotPluginStatus(screenshotPluginStatus),
                };
            }

            return {
                success: true,
                supported: true,
                source: result?.source || screenshotPluginStatus.source || 'bridge_renderer',
                screenshot_path: screenshotPath,
                requested_path: requestedPath,
                screenshot_plugin: publicScreenshotPluginStatus(screenshotPluginStatus),
                ...fileStatusForScreenshot(screenshotPath),
            };
        } catch (e) {
            return {
                success: false,
                supported: true,
                error: e.message,
                requested_path: requestedPath,
                screenshot_plugin: publicScreenshotPluginStatus(screenshotPluginStatus),
            };
        }
    };
}

function numericCoordinate(params, key) {
    const raw = params?.[key];
    if (raw === null || raw === undefined) return null;
    if (typeof raw === 'string' && raw.trim() === '') return null;
    const value = Number(raw);
    return Number.isFinite(value) ? value : null;
}

function positionPayload(position) {
    if (!position) return null;
    return {
        x: Number(position.x),
        y: Number(position.y),
        z: Number(position.z),
    };
}

function navigationDistance(position, target, includeY = true) {
    if (!position || !target) return null;
    const dx = Number(position.x) - Number(target.x);
    const dy = includeY ? Number(position.y) - Number(target.y) : 0;
    const dz = Number(position.z) - Number(target.z);
    if (![dx, dy, dz].every(Number.isFinite)) return null;
    return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

function navigationTimeoutMs(distance, requested) {
    const explicit = Number(requested);
    if (Number.isFinite(explicit) && explicit > 0) {
        return Math.max(1000, Math.min(60000, Math.round(explicit)));
    }
    const estimated = 5000 + (Math.max(0, Number(distance) || 0) / 2.5) * 1000;
    return Math.max(5000, Math.min(60000, Math.round(estimated)));
}

function createMoveToHandler(
    getState = () => ({ bot, botReady }),
    options = {},
) {
    const goalFactory = options.goalFactory || ((target, tolerance, hasExplicitY) => (
        hasExplicitY
            ? new goals.GoalNear(
                Math.floor(target.x),
                Math.floor(target.y),
                Math.floor(target.z),
                Math.max(1, Math.ceil(tolerance)),
            )
            : new goals.GoalNearXZ(
                Math.floor(target.x),
                Math.floor(target.z),
                Math.max(1, Math.ceil(tolerance)),
            )
    ));
    return async (params = {}) => {
        const state = getState() || {};
        const activeBot = state.bot;
        if (!state.botReady || !activeBot?.entity?.position) {
            return { success: false, reached: false, error: 'bot is not ready for navigation' };
        }
        const x = numericCoordinate(params, 'x');
        const z = numericCoordinate(params, 'z');
        const explicitY = numericCoordinate(params, 'y');
        const y = explicitY ?? Number(activeBot.entity.position.y);
        if (x === null || z === null || !Number.isFinite(y)) {
            return { success: false, reached: false, error: 'move_to requires finite x and z coordinates' };
        }
        if (!activeBot.pathfinder || typeof activeBot.pathfinder.goto !== 'function') {
            return { success: false, reached: false, error: 'pathfinder is unavailable' };
        }

        const target = new Vec3(x, y, z);
        const toleranceValue = numericCoordinate(params, 'tolerance');
        const tolerance = Number.isFinite(toleranceValue)
            ? Math.max(1, Math.min(8, toleranceValue))
            : 2;
        const initialDistance = navigationDistance(activeBot.entity.position, target, explicitY !== null);
        const timeoutMs = navigationTimeoutMs(initialDistance, params.timeout_ms);
        let timer = null;
        try {
            const navigation = Promise.resolve(activeBot.pathfinder.goto(goalFactory(target, tolerance, explicitY !== null)));
            const timeout = new Promise((_, reject) => {
                timer = setTimeout(() => reject(new Error(`navigation timed out after ${timeoutMs}ms`)), timeoutMs);
            });
            await Promise.race([navigation, timeout]);
            const finalPosition = activeBot.entity.position;
            const distance = navigationDistance(finalPosition, target, explicitY !== null);
            const reached = distance !== null && distance <= tolerance + 0.75;
            if (!reached) {
                return {
                    success: false,
                    reached: false,
                    error: 'pathfinder completed without reaching the target tolerance',
                    position: positionPayload(finalPosition),
                    target: positionPayload(target),
                    distance_to_target: distance,
                    tolerance,
                };
            }
            return {
                success: true,
                reached: true,
                position: positionPayload(finalPosition),
                target: positionPayload(target),
                distance_to_target: distance,
                tolerance,
            };
        } catch (e) {
            if (activeBot.pathfinder && typeof activeBot.pathfinder.stop === 'function') {
                activeBot.pathfinder.stop();
            }
            const finalPosition = activeBot.entity?.position;
            return {
                success: false,
                reached: false,
                error: e.message,
                position: positionPayload(finalPosition),
                target: positionPayload(target),
                distance_to_target: navigationDistance(finalPosition, target, explicitY !== null),
                tolerance,
            };
        } finally {
            if (timer) clearTimeout(timer);
        }
    };
}

function createWalkToHandler(getState = () => ({ bot, botReady })) {
    return async (params = {}) => {
        const state = getState() || {};
        const activeBot = state.bot;
        if (!state.botReady || !activeBot?.entity?.position) {
            return { success: false, reached: false, error: 'bot is not ready for navigation' };
        }
        const x = numericCoordinate(params, 'x');
        const z = numericCoordinate(params, 'z');
        const explicitY = numericCoordinate(params, 'y');
        const y = explicitY ?? Number(activeBot.entity.position.y);
        if (x === null || z === null || !Number.isFinite(y)) {
            return { success: false, reached: false, error: 'walk_to requires finite x and z coordinates' };
        }
        const target = new Vec3(x, y, z);
        try {
            await activeBot.lookAt(target);
            activeBot.setControlState('forward', true);
            const durationMs = Math.max(100, Math.min(10000, Number(params.ms) || 2000));
            await new Promise(resolve => setTimeout(resolve, durationMs));
            activeBot.setControlState('forward', false);
            const finalPosition = activeBot.entity.position;
            const distance = navigationDistance(finalPosition, target, explicitY !== null);
            const reached = distance !== null && distance <= 2.75;
            return {
                success: true,
                reached,
                partial: !reached,
                position: positionPayload(finalPosition),
                target: positionPayload(target),
                distance_to_target: distance,
            };
        } catch (e) {
            activeBot.setControlState('forward', false);
            return { success: false, reached: false, error: e.message };
        }
    };
}

function installConfiguredScreenshotPlugin(botInstance) {
    screenshotPluginStatus = attachScreenshotPlugin(botInstance, SCREENSHOT_PLUGIN, SCREENSHOT_OPTIONS);
    screenshotPluginCapture = screenshotPluginStatus.capture || null;
    if (SCREENSHOT_PLUGIN && !screenshotPluginStatus.supported) {
        console.warn(`[Screenshot] Plugin not ready: ${screenshotPluginStatus.error}`);
    } else if (SCREENSHOT_PLUGIN) {
        console.log(`[Screenshot] Plugin loaded from ${screenshotPluginStatus.resolved || SCREENSHOT_PLUGIN}`);
    }
}

function connectBot() {
    botReady = false;
    bot = mineflayer.createBot({
        host: MC_HOST,
        port: MC_PORT,
        username: MC_USERNAME,
        version: MC_VERSION,
    });

    bot.loadPlugin(pathfinder);
    installConfiguredScreenshotPlugin(bot);

    bot.on('spawn', () => {
        botReady = true;
        lastBotError = "";
        console.log(`[Bot] Spawned in world at ${bot.entity.position}`);
        const mcData = require('minecraft-data')(bot.version);
        const defaultMove = new Movements(bot, mcData);
        defaultMove.canOpenDoors = true;
        defaultMove.allowParkour = true;
        defaultMove.allowSprinting = true;
        bot.pathfinder.setMovements(defaultMove);
    });

    bot.on('error', (err) => {
        lastBotError = err.message;
        console.error('[Bot] Error:', err.message);
    });
    bot.on('kicked', (reason) => console.warn('[Bot] Kicked:', reason));
    bot.on('end', () => {
        botReady = false;
        console.log('[Bot] Disconnected - reconnecting in 5s');
        setTimeout(connectBot, 5000);
    });
}

// Command handlers
const handlers = {
    health: () => ({
        success: true,
        bridge: true,
        bot_created: Boolean(bot),
        bot_ready: botReady && Boolean(bot?.entity),
        mc_host: MC_HOST,
        mc_port: MC_PORT,
        bridge_host: BRIDGE_HOST,
        bridge_port: BRIDGE_PORT,
        username: MC_USERNAME,
        version: bot?.version || MC_VERSION,
        position: botReady && bot?.entity ? bot.entity.position : null,
        last_error: lastBotError,
        screenshot_capture_supported: Boolean(findScreenshotCapture(bot)),
        screenshot_plugin: publicScreenshotPluginStatus(screenshotPluginStatus),
    }),

    get_player_state: () => ({
        position: bot.entity.position,
        health: bot.health,
        food: bot.food,
        foodSaturation: bot.foodSaturation,
        oxygenLevel: bot.oxygenLevel,
        experience: bot.experience,
        dimension: bot.game?.dimension || null,
        gameMode: bot.game?.gameMode || null,
        selectedSlot: bot.quickBarSlot,
        equipment: Array.isArray(bot.entity?.equipment)
            ? bot.entity.equipment.map((item, slot) => item ? ({ slot, name: item.name, count: item.count }) : null)
            : [],
        yaw: bot.entity.yaw,
        pitch: bot.entity.pitch,
    }),

    get_inventory: () => ({
        items: bot.inventory.items().map(i => ({
            name: i.name,
            displayName: i.displayName,
            count: i.count,
            slot: i.slot,
            metadata: i.metadata,
        })),
    }),

    get_nearby_entities: (params) => {
        const radius = Math.min(params.radius || 16, 16);
        const entities = [];
        for (const [id, entity] of Object.entries(bot.entities)) {
            if (entity === bot.entity) continue;
            const dist = bot.entity.position.distanceTo(entity.position);
            if (dist <= radius) {
                entities.push({
                    id: parseInt(id),
                    name: entity.name || entity.type || 'unknown',
                    type: entity.type,
                    distance: dist,
                    position: entity.position,
                    health: entity.health,
                    hostile: entity.type === 'hostile',
                });
            }
        }
        return { entities };
    },

    get_nearby_blocks: (params) => {
        const radius = params.radius || 5;
        const blocks = [];
        const pos = bot.entity.position;
        for (let x = -radius; x <= radius; x++) {
            for (let y = -3; y <= 3; y++) {
                for (let z = -radius; z <= radius; z++) {
                    const block = bot.blockAt(pos.offset(x, y, z));
                    if (block && block.type !== 0) {
                        blocks.push({
                            name: block.name,
                            position: block.position,
                            distance: Math.sqrt(x*x + y*y + z*z),
                        });
                    }
                }
            }
        }
        blocks.sort((a, b) => a.distance - b.distance);
        return { blocks: blocks.slice(0, 50) };
    },

    get_block_below: () => {
        const pos = bot.entity.position.offset(0, -1, 0);
        const block = bot.blockAt(pos);
        return { block: block ? block.name : 'air' };
    },

    get_time: () => ({ time: bot.time.timeOfDay }),

    get_weather: () => ({
        weather: bot.thunderState > 0 ? 'thunder' : bot.rainState > 0 ? 'rain' : 'clear'
    }),

    get_biome: () => {
        const block = bot.blockAt(bot.entity.position);
        return { biome: block ? block.biome?.name || 'unknown' : 'unknown' };
    },

    get_light_level: () => {
        const block = bot.blockAt(bot.entity.position.offset(0, 1, 0));
        return { light_level: block ? block.light : 0 };
    },

    capture_screenshot: createCaptureScreenshotHandler(),

    get_nearby_trees: (params) => {
        const radius = Math.min(params.radius || 16, 16);
        const treeNames = new Set(['oak_log','birch_log','spruce_log','jungle_log','acacia_log','dark_oak_log']);
        const trees = [];
        const pos = bot.entity.position;
        for (let x = -radius; x <= radius; x++) {
            for (let y = -2; y <= 5; y++) {
                for (let z = -radius; z <= radius; z++) {
                    const block = bot.blockAt(pos.offset(x, y, z));
                    if (block && treeNames.has(block.name)) {
                        trees.push({
                            name: block.name,
                            position: block.position,
                            distance: Math.sqrt(x*x + y*y + z*z),
                        });
                    }
                }
            }
        }
        trees.sort((a, b) => a.distance - b.distance);
        return { trees: trees.slice(0, 10) };
    },
    walk_to: createWalkToHandler(),
    move_to: createMoveToHandler(),

    look_at: async (params) => {
        try {
            await bot.lookAt(new Vec3(params.x, params.y, params.z));
            return { success: true };
        } catch (e) {
            return { success: false, error: e.message };
        }
    },

    dig: async (params) => {
        try {
            let block;
            if (params.x != null && params.y != null && params.z != null) {
                block = bot.blockAt(new Vec3(params.x, params.y, params.z));
            } else {
                block = bot.blockAt(bot.entity.position.offset(0, -1, 0));
            }
            if (!block || block.type === 0) return { success: false, error: 'No block to dig' };
            await bot.dig(block);
            return { success: true, block: block.name };
        } catch (e) {
            return { success: false, error: e.message };
        }
    },

    place: async (params) => {
        try {
            const referenceBlock = bot.blockAt(new Vec3(params.x, params.y, params.z));
            if (!referenceBlock) return { success: false, error: 'No reference block' };
            await bot.placeBlock(referenceBlock, new Vec3(0, 1, 0));
            return { success: true };
        } catch (e) {
            return { success: false, error: e.message };
        }
    },

    craft: async (params) => {
        try {
            const mcData = require('minecraft-data')(bot.version);
            const recipes = bot.recipesFor(mcData.itemsByName[params.item]?.id || 0, null, 1, null);
            if (!recipes || recipes.length === 0) return { success: false, error: `No recipe for ${params.item}` };
            await bot.craft(recipes[0], params.count || 1);
            return { success: true, item: params.item };
        } catch (e) {
            return { success: false, error: e.message };
        }
    },

    attack: (params) => {
        try {
            const entity = params.entity_id ? bot.entities[params.entity_id] : null;
            if (entity) bot.attack(entity);
            return { success: true };
        } catch (e) {
            return { success: false, error: e.message };
        }
    },

    equip: async (params) => {
        try {
            const item = bot.inventory.items().find(i => i.name === params.item);
            if (!item) return { success: false, error: `Item ${params.item} not in inventory` };
            const dest = params.destination === 'off-hand' ? 'off-hand' : 'hand';
            await bot.equip(item, dest);
            return { success: true };
        } catch (e) {
            return { success: false, error: e.message };
        }
    },

    use_item: async () => {
        try {
            bot.activateItem();
            return { success: true };
        } catch (e) {
            return { success: false, error: e.message };
        }
    },

    chat: (params) => {
        bot.chat(params.message || '');
        return { success: true };
    },
};

function createBridgeServer() {
    return net.createServer((socket) => {
        console.log(`[Bridge] Python client connected`);
        let buffer = '';

        socket.on('data', async (data) => {
            buffer += data.toString();
            const lines = buffer.split('\n');
            buffer = lines.pop(); // Keep incomplete line in buffer

            for (const line of lines) {
                if (!line.trim()) continue;
                try {
                    const msg = JSON.parse(line);
                    const handler = handlers[msg.command];
                    if (!handler) {
                        socket.write(JSON.stringify({ success: false, error: `Unknown command: ${msg.command}` }) + '\n');
                        continue;
                    }
                    const result = await handler(msg.params || {});
                    socket.write(JSON.stringify(result) + '\n');
                } catch (e) {
                    socket.write(JSON.stringify({ success: false, error: e.message }) + '\n');
                }
            }
        });

        socket.on('close', () => console.log('[Bridge] Client disconnected'));
        socket.on('error', (err) => console.error('[Bridge] Socket error:', err.message));
    });
}

function startBridge() {
    connectBot();
    const server = createBridgeServer();
    server.listen(BRIDGE_PORT, BRIDGE_HOST, () => {
        console.log(`[Bridge] Listening on ${BRIDGE_HOST}:${BRIDGE_PORT}`);
        console.log(`[Bridge] Connecting to MC server ${MC_HOST}:${MC_PORT} as ${MC_USERNAME}`);
    });
    return server;
}

if (require.main === module) {
    startBridge();
}

module.exports = {
    attachScreenshotPlugin,
    createBridgeServer,
    createCaptureScreenshotHandler,
    createMoveToHandler,
    createWalkToHandler,
    fileStatusForScreenshot,
    imageBytesFromCaptureResult,
    navigationDistance,
    navigationTimeoutMs,
    publicScreenshotPluginStatus,
    resolveScreenshotPluginSpec,
    screenshotPathFromCaptureResult,
    startBridge,
};
