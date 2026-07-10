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
const crypto = require('crypto');
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
const BENCHMARK_SEED = getArg('benchmark-seed', '');
const BENCHMARK_EPISODE = getArg('benchmark-episode', '');
const BENCHMARK_LEVEL_NAME = getArg('benchmark-level-name', '');
const BENCHMARK_SERVER_JAR_SHA256 = getArg('benchmark-server-jar-sha256', '');
const SCREENSHOT_PLUGIN = getArg('screenshot-plugin', '');
const SCREENSHOT_OPTIONS = {
    width: parseInt(getArg('screenshot-width', '512')),
    height: parseInt(getArg('screenshot-height', '512')),
    viewDistance: parseInt(getArg('screenshot-view-distance', '4')),
    renderDelayMs: parseInt(getArg('screenshot-render-delay-ms', '500')),
};

const M1_PROTOCOL_PATH = path.resolve(__dirname, '..', 'singularity', 'data', 'm1_protocol.json');
const M1_PROTOCOL_BYTES = fs.readFileSync(M1_PROTOCOL_PATH);
const M1_PROTOCOL = JSON.parse(M1_PROTOCOL_BYTES.toString('utf8'));
const M1_PROTOCOL_SHA256 = crypto.createHash('sha256').update(M1_PROTOCOL_BYTES).digest('hex');

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

function prioritizeTreeResults(trees, limit = 10) {
    const sorted = [...(trees || [])].sort((a, b) => Number(a.distance) - Number(b.distance));
    const selected = sorted.slice(0, Math.max(1, Number(limit) || 10));
    const selectedNames = new Set(selected.map(tree => tree.name));
    for (const tree of sorted) {
        if (!selectedNames.has(tree.name)) {
            selected.push(tree);
            selectedNames.add(tree.name);
        }
    }
    return selected.sort((a, b) => Number(a.distance) - Number(b.distance));
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
                Math.max(1, Math.floor(tolerance - 0.5)),
            )
            : new goals.GoalNearXZ(
                Math.floor(target.x),
                Math.floor(target.z),
                Math.max(1, Math.floor(tolerance - 0.5)),
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
            const reached = distance !== null && distance <= tolerance;
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
            const distance = navigationDistance(finalPosition, target, explicitY !== null);
            const reached = distance !== null && distance <= tolerance;
            const result = {
                success: reached,
                reached,
                position: positionPayload(finalPosition),
                target: positionPayload(target),
                distance_to_target: distance,
                tolerance,
            };
            if (reached) {
                result.pathfinder_warning = e.message;
            } else {
                result.error = e.message;
            }
            return result;
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

function installedBenchmarkDependencies() {
    return {
        mineflayer: require('mineflayer/package.json').version,
        'mineflayer-pathfinder': require('mineflayer-pathfinder/package.json').version,
        'minecraft-data': require('minecraft-data/package.json').version,
    };
}

function benchmarkRuntime(overrides = {}) {
    return {
        seed: String(overrides.seed ?? BENCHMARK_SEED),
        episode_id: String(overrides.episode_id ?? BENCHMARK_EPISODE),
        level_name: String(overrides.level_name ?? BENCHMARK_LEVEL_NAME),
        server_jar_sha256: String(overrides.server_jar_sha256 ?? BENCHMARK_SERVER_JAR_SHA256).toLowerCase(),
    };
}

function benchmarkProtocolStatus(activeBot, runtimeOverrides = {}) {
    const runtime = benchmarkRuntime(runtimeOverrides);
    const dependencies = installedBenchmarkDependencies();
    const serverBrand = String(activeBot?.game?.serverBrand || '');
    const observedMinecraftVersion = String(activeBot?.version || '');
    const errors = [];
    if (runtime.seed !== M1_PROTOCOL.world_seed) {
        errors.push(`benchmark seed ${runtime.seed || '<missing>'} does not match ${M1_PROTOCOL.world_seed}`);
    }
    if (!runtime.episode_id) {
        errors.push('benchmark episode id is missing');
    }
    if (!runtime.level_name || !runtime.level_name.startsWith(`${runtime.episode_id}_`)) {
        errors.push('benchmark level name is missing or is not unique to the episode');
    }
    if (!/^[a-f0-9]{64}$/.test(runtime.server_jar_sha256)) {
        errors.push('server jar sha256 is missing or invalid');
    } else if (runtime.server_jar_sha256 !== M1_PROTOCOL.server_jar_sha256) {
        errors.push(`server jar sha256 does not match pinned ${M1_PROTOCOL.server_build}`);
    }
    for (const [name, expected] of Object.entries(M1_PROTOCOL.dependencies || {})) {
        if (dependencies[name] !== expected) {
            errors.push(`${name}=${dependencies[name] || '<missing>'}, expected ${expected}`);
        }
    }
    if (activeBot?.entity && !/paper/i.test(serverBrand)) {
        errors.push(`server brand ${serverBrand || '<missing>'} is not Paper`);
    }
    if (activeBot?.entity && observedMinecraftVersion !== M1_PROTOCOL.minecraft_version) {
        errors.push(`Minecraft version ${observedMinecraftVersion || '<missing>'} does not match ${M1_PROTOCOL.minecraft_version}`);
    }
    return {
        success: true,
        configured: errors.length === 0,
        profile: M1_PROTOCOL.profile,
        protocol_sha256: M1_PROTOCOL_SHA256,
        minecraft_version: M1_PROTOCOL.minecraft_version,
        observed_minecraft_version: observedMinecraftVersion,
        server_type: M1_PROTOCOL.server_type,
        server_build: M1_PROTOCOL.server_build,
        server_jar_policy: M1_PROTOCOL.server_jar_policy,
        agent_id: M1_PROTOCOL.agent_id,
        planner_id: M1_PROTOCOL.planner_id,
        action_backend_id: M1_PROTOCOL.action_backend_id,
        verifier_id: M1_PROTOCOL.verifier_id,
        server_brand: serverBrand,
        seed: runtime.seed,
        episode_id: runtime.episode_id,
        level_name: runtime.level_name,
        server_jar_sha256: runtime.server_jar_sha256,
        episode_strategy: M1_PROTOCOL.episode_strategy,
        dependencies,
        tasks: M1_PROTOCOL.tasks,
        reset_supported: true,
        errors,
    };
}

function createBenchmarkProtocolHandler(
    getState = () => ({ bot, botReady }),
    runtimeOverrides = {},
) {
    return () => {
        const state = getState() || {};
        return benchmarkProtocolStatus(state.bot, runtimeOverrides);
    };
}

function inventoryCounts(activeBot) {
    const counts = {};
    const items = activeBot?.inventory?.items?.() || [];
    for (const item of items) {
        if (!item?.name) continue;
        counts[item.name] = (counts[item.name] || 0) + Number(item.count || 0);
    }
    return counts;
}

function positiveInventoryDelta(before, after) {
    const delta = {};
    for (const name of new Set([...Object.keys(before || {}), ...Object.keys(after || {})])) {
        const change = Number(after?.[name] || 0) - Number(before?.[name] || 0);
        if (change > 0) delta[name] = change;
    }
    return delta;
}

async function waitForInventoryIncrease(
    activeBot,
    before,
    wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    maxWaitMs = 2000,
    expectedItems = [],
) {
    const pollMs = 100;
    const expected = new Set(expectedItems || []);
    for (let elapsed = 0; elapsed <= maxWaitMs; elapsed += pollMs) {
        const after = inventoryCounts(activeBot);
        const delta = positiveInventoryDelta(before, after);
        const expectedObserved = expected.size === 0
            ? Object.keys(delta).length > 0
            : [...expected].some(name => Number(delta[name] || 0) > 0);
        if (expectedObserved) {
            return { observed: true, inventory: after, delta, waited_ms: elapsed };
        }
        if (elapsed < maxWaitMs) await wait(pollMs);
    }
    return {
        observed: false,
        inventory: inventoryCounts(activeBot),
        delta: {},
        waited_ms: maxWaitMs,
    };
}

function blockDropNames(activeBot, block) {
    try {
        const mcData = require('minecraft-data')(activeBot.version);
        return (block?.drops || [])
            .map(drop => mcData.items[Number(drop?.id ?? drop)]?.name)
            .filter(Boolean);
    } catch (_) {
        return [];
    }
}

function nearestDroppedItem(activeBot, target, expectedItems = []) {
    const expected = new Set(expectedItems || []);
    const candidates = [];
    for (const entity of Object.values(activeBot?.entities || {})) {
        if (!entity?.position || entity === activeBot.entity) continue;
        let stack = null;
        try {
            stack = typeof entity.getDroppedItem === 'function' ? entity.getDroppedItem() : null;
        } catch (_) {
            stack = null;
        }
        if (entity.name !== 'item' && !stack) continue;
        if (stack?.name && expected.size > 0 && !expected.has(stack.name)) continue;
        const targetDistance = navigationDistance(entity.position, target, true);
        if (targetDistance === null || targetDistance > 8) continue;
        candidates.push({
            entity,
            item_name: stack?.name || '',
            target_distance: targetDistance,
            player_distance: navigationDistance(activeBot.entity.position, entity.position, true),
        });
    }
    candidates.sort((a, b) => Number(a.player_distance) - Number(b.player_distance));
    return candidates[0] || null;
}

async function approachDroppedItem(activeBot, target, expectedItems, timeoutMs = 6000) {
    const drop = nearestDroppedItem(activeBot, target, expectedItems);
    if (!drop) return { detected: false, attempted: false };
    const details = {
        detected: true,
        attempted: false,
        entity_id: drop.entity.id ?? null,
        item_name: drop.item_name,
        position: positionPayload(drop.entity.position),
        initial_distance: drop.player_distance,
    };
    if (!activeBot.pathfinder || typeof activeBot.pathfinder.goto !== 'function') {
        return { ...details, error: 'pathfinder is unavailable for pickup collection' };
    }

    const dropPosition = drop.entity.position.clone
        ? drop.entity.position.clone()
        : new Vec3(drop.entity.position.x, drop.entity.position.y, drop.entity.position.z);
    let timer = null;
    try {
        details.attempted = true;
        const navigation = Promise.resolve(activeBot.pathfinder.goto(
            new goals.GoalNear(
                Math.floor(dropPosition.x),
                Math.floor(dropPosition.y),
                Math.floor(dropPosition.z),
                0,
            ),
        ));
        const timeout = new Promise((_, reject) => {
            timer = setTimeout(() => reject(new Error(`pickup navigation timed out after ${timeoutMs}ms`)), timeoutMs);
        });
        await Promise.race([navigation, timeout]);
        details.success = true;
    } catch (error) {
        details.success = false;
        details.error = error.message;
        if (typeof activeBot.pathfinder.stop === 'function') activeBot.pathfinder.stop();
    } finally {
        if (timer) clearTimeout(timer);
    }
    details.final_distance = navigationDistance(activeBot.entity.position, dropPosition, true);
    return details;
}

function compactPosition(position) {
    if (!position) return null;
    return {
        x: Number(position.x),
        y: Number(position.y),
        z: Number(position.z),
    };
}

function fixturePosition(spawnPoint) {
    return new Vec3(
        Math.floor(Number(spawnPoint.x)) + 1,
        Math.floor(Number(spawnPoint.y)),
        Math.floor(Number(spawnPoint.z)),
    );
}

function benchmarkBotState(activeBot, spawnPoint) {
    const fixture = spawnPoint ? fixturePosition(spawnPoint) : null;
    const fixtureBlock = fixture && activeBot?.blockAt ? activeBot.blockAt(fixture) : null;
    return {
        position: compactPosition(activeBot?.entity?.position),
        spawn_position: compactPosition(spawnPoint),
        health: Number(activeBot?.health ?? 0),
        food: Number(activeBot?.food ?? 0),
        inventory: inventoryCounts(activeBot),
        game_mode: String(activeBot?.game?.gameMode || ''),
        difficulty: String(activeBot?.game?.difficulty || ''),
        dimension: String(activeBot?.game?.dimension || ''),
        time_of_day: Number(activeBot?.time?.timeOfDay ?? -1),
        weather: activeBot?.thunderState > 0 ? 'thunder' : activeBot?.rainState > 0 ? 'rain' : 'clear',
        fixture: fixture ? {
            position: compactPosition(fixture),
            block: String(fixtureBlock?.name || 'air'),
        } : null,
    };
}

function inventoryExactlyMatches(actual, expected) {
    const normalize = (value) => Object.fromEntries(
        Object.entries(value || {})
            .filter(([, count]) => Number(count) > 0)
            .map(([name, count]) => [name, Number(count)])
            .sort(([a], [b]) => a.localeCompare(b)),
    );
    return JSON.stringify(normalize(actual)) === JSON.stringify(normalize(expected));
}

function positionDistance(a, b) {
    if (!a || !b) return Number.POSITIVE_INFINITY;
    return Math.sqrt(
        Math.pow(Number(a.x) - Number(b.x), 2) +
        Math.pow(Number(a.y) - Number(b.y), 2) +
        Math.pow(Number(a.z) - Number(b.z), 2)
    );
}

function benchmarkResetChecks(postState, taskSpec) {
    const expectedBlocks = Array.isArray(taskSpec.initial_blocks) ? taskSpec.initial_blocks : [];
    const expectedFixture = expectedBlocks[0]?.name || 'air';
    const finalDistance = positionDistance(postState.position, postState.spawn_position);
    return {
        inventory_exact: inventoryExactlyMatches(postState.inventory, taskSpec.initial_inventory),
        position_at_spawn: finalDistance <= 1.5,
        position_distance: Number.isFinite(finalDistance) ? Number(finalDistance.toFixed(3)) : null,
        game_mode: postState.game_mode === M1_PROTOCOL.game_mode,
        difficulty: postState.difficulty === M1_PROTOCOL.difficulty,
        dimension: /overworld/i.test(postState.dimension),
        daytime: postState.time_of_day >= 0 && postState.time_of_day < 12000,
        time_initialized: Math.abs(postState.time_of_day - Number(M1_PROTOCOL.time_of_day)) <= 600,
        weather: postState.weather === M1_PROTOCOL.weather,
        health: postState.health >= 20,
        food: postState.food >= 20,
        fixture: postState.fixture?.block === expectedFixture,
    };
}

function createBenchmarkResetHandler(
    getState = () => ({ bot, botReady }),
    wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    runtimeOverrides = {},
) {
    return async (params = {}) => {
        const state = getState() || {};
        const activeBot = state.bot;
        const ready = Boolean(state.botReady && activeBot?.entity);
        if (!ready) {
            return { success: false, error: 'bot is not ready for benchmark reset' };
        }
        const protocolStatus = benchmarkProtocolStatus(activeBot, runtimeOverrides);
        if (!protocolStatus.configured) {
            return {
                success: false,
                error: 'M1 benchmark protocol is not configured',
                protocol_errors: protocolStatus.errors,
            };
        }
        const taskId = String(params.task_id || '');
        const taskSpec = M1_PROTOCOL.tasks.find((task) => task.id === taskId);
        if (!taskSpec) {
            return { success: false, error: `unsupported M1 benchmark task: ${taskId || '<missing>'}` };
        }
        const spawnPoint = activeBot.spawnPoint;
        if (!spawnPoint || ![spawnPoint.x, spawnPoint.y, spawnPoint.z].every(Number.isFinite)) {
            return { success: false, error: 'bot spawn point is unavailable' };
        }

        const beforeState = benchmarkBotState(activeBot, spawnPoint);
        const fixture = fixturePosition(spawnPoint);
        const fixtureSpec = Array.isArray(taskSpec.initial_blocks) ? taskSpec.initial_blocks[0] : null;
        const commands = [
            `/execute in minecraft:overworld run tp @s ${spawnPoint.x} ${spawnPoint.y} ${spawnPoint.z}`,
            `/gamemode ${M1_PROTOCOL.game_mode} @s`,
            '/clear @s',
            '/kill @e[type=minecraft:item,distance=..16]',
            `/setblock ${fixture.x} ${fixture.y} ${fixture.z} minecraft:air`,
        ];
        if (fixtureSpec) {
            commands.push(`/setblock ${fixture.x} ${fixture.y} ${fixture.z} minecraft:${fixtureSpec.name}`);
        }
        commands.push(
            `/time set ${M1_PROTOCOL.time_of_day}`,
            `/weather ${M1_PROTOCOL.weather}`,
            `/difficulty ${M1_PROTOCOL.difficulty}`,
            '/effect give @s minecraft:instant_health 1 255 true',
            '/effect give @s minecraft:saturation 1 255 true',
        );
        for (const [item, count] of Object.entries(taskSpec.initial_inventory || {})) {
            commands.push(`/give @s minecraft:${item} ${Number(count)}`);
        }

        try {
            for (const command of commands) {
                activeBot.chat(command);
                await wait(400);
            }
            await wait(600);
        } catch (error) {
            return { success: false, error: `benchmark reset command failed: ${error.message}` };
        }

        const afterState = benchmarkBotState(activeBot, spawnPoint);
        const checks = benchmarkResetChecks(afterState, taskSpec);
        const failedChecks = Object.entries(checks)
            .filter(([name, value]) => name !== 'position_distance' && value !== true)
            .map(([name]) => name);
        const success = failedChecks.length === 0;
        return {
            success,
            error: success ? '' : 'benchmark reset postconditions failed; ensure the bot is a server operator',
            profile: M1_PROTOCOL.profile,
            protocol_sha256: M1_PROTOCOL_SHA256,
            episode_id: protocolStatus.episode_id,
            level_name: protocolStatus.level_name,
            seed: protocolStatus.seed,
            server_brand: protocolStatus.server_brand,
            observed_minecraft_version: protocolStatus.observed_minecraft_version,
            server_jar_sha256: protocolStatus.server_jar_sha256,
            task_id: taskId,
            expected: {
                initial_inventory: taskSpec.initial_inventory,
                initial_blocks: taskSpec.initial_blocks,
                game_mode: M1_PROTOCOL.game_mode,
                difficulty: M1_PROTOCOL.difficulty,
                time_of_day: M1_PROTOCOL.time_of_day,
                weather: M1_PROTOCOL.weather,
            },
            before_state: beforeState,
            after_state: afterState,
            checks,
            failed_checks: failedChecks,
            command_count: commands.length,
        };
    };
}

function createCraftHandler(getState = () => ({ bot, botReady })) {
    return async (params = {}) => {
        const state = getState() || {};
        const activeBot = state.bot;
        if (!state.botReady || !activeBot?.entity) {
            return { success: false, error: 'bot is not ready to craft' };
        }
        try {
            const itemName = String(params.item || '');
            const count = Math.max(1, Number(params.count || 1));
            const mcData = require('minecraft-data')(activeBot.version);
            const item = mcData.itemsByName[itemName];
            if (!item) return { success: false, error: `Unknown item ${itemName}` };
            const tableType = mcData.blocksByName.crafting_table?.id;
            const craftingTable = tableType == null ? null : activeBot.findBlock({
                matching: tableType,
                maxDistance: 5,
            });
            const recipes = activeBot.recipesFor(item.id, null, count, craftingTable);
            if (!recipes || recipes.length === 0) {
                return {
                    success: false,
                    error: `No recipe for ${itemName}`,
                    crafting_table_found: Boolean(craftingTable),
                };
            }
            await activeBot.craft(recipes[0], count, craftingTable);
            return {
                success: true,
                item: itemName,
                count,
                crafting_table_found: Boolean(craftingTable),
                crafting_table_position: compactPosition(craftingTable?.position),
            };
        } catch (e) {
            return { success: false, error: e.message };
        }
    };
}

function createDigHandler(
    getState = () => ({ bot, botReady }),
    wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
) {
    return async (params = {}) => {
        const state = getState() || {};
        const activeBot = state.bot;
        if (!state.botReady || !activeBot?.entity?.position) {
            return { success: false, pickup_observed: false, error: 'bot is not ready to dig' };
        }
        try {
            let block;
            if (params.x != null && params.y != null && params.z != null) {
                block = activeBot.blockAt(new Vec3(params.x, params.y, params.z));
            } else {
                block = activeBot.blockAt(activeBot.entity.position.offset(0, -1, 0));
            }
            if (!block || block.type === 0 || block.name === 'air') {
                return { success: false, pickup_observed: false, error: 'No block to dig' };
            }
            const target = block.position?.clone ? block.position.clone() : new Vec3(block.position.x, block.position.y, block.position.z);
            const beforeInventory = inventoryCounts(activeBot);
            const blockName = block.name;
            const expectedDrops = blockDropNames(activeBot, block);
            const targetBlockBefore = {
                name: blockName,
                type: Number(block.type),
                position: compactPosition(target),
            };
            await activeBot.dig(block);
            let pickup = await waitForInventoryIncrease(activeBot, beforeInventory, wait, 1000, expectedDrops);
            let pickupCollection = { detected: false, attempted: false };
            if (!pickup.observed) {
                pickupCollection = await approachDroppedItem(activeBot, target, expectedDrops);
                const collected = await waitForInventoryIncrease(activeBot, beforeInventory, wait, 1500, expectedDrops);
                pickup = {
                    ...collected,
                    waited_ms: pickup.waited_ms + collected.waited_ms,
                };
            }
            const blockAfter = activeBot.blockAt(target);
            return {
                success: true,
                block: blockName,
                expected_drops: expectedDrops,
                target: compactPosition(target),
                block_removed: !blockAfter || blockAfter.type === 0 || blockAfter.name !== blockName,
                target_block_before: targetBlockBefore,
                target_block_after: {
                    name: String(blockAfter?.name || 'air'),
                    type: Number(blockAfter?.type || 0),
                    position: compactPosition(target),
                },
                pickup_observed: pickup.observed,
                pickup_inventory_delta: pickup.delta,
                pickup_waited_ms: pickup.waited_ms,
                pickup_collection: pickupCollection,
            };
        } catch (e) {
            return { success: false, pickup_observed: false, error: e.message };
        }
    };
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
        server_brand: bot?.game?.serverBrand || '',
        position: botReady && bot?.entity ? bot.entity.position : null,
        last_error: lastBotError,
        benchmark_protocol: {
            profile: M1_PROTOCOL.profile,
            configured: benchmarkProtocolStatus(bot).configured,
            episode_id: BENCHMARK_EPISODE,
            seed: BENCHMARK_SEED,
        },
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
    benchmark_protocol: createBenchmarkProtocolHandler(),
    benchmark_reset: createBenchmarkResetHandler(),

    get_nearby_trees: (params = {}) => {
        const radius = Math.max(1, Math.min(Number(params.radius) || 16, 32));
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
        return { trees: prioritizeTreeResults(trees, 10) };
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

    dig: createDigHandler(),

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

    craft: createCraftHandler(),

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
    M1_PROTOCOL,
    M1_PROTOCOL_SHA256,
    attachScreenshotPlugin,
    benchmarkBotState,
    benchmarkProtocolStatus,
    benchmarkResetChecks,
    createBridgeServer,
    createBenchmarkProtocolHandler,
    createBenchmarkResetHandler,
    createCraftHandler,
    createDigHandler,
    createCaptureScreenshotHandler,
    createMoveToHandler,
    createWalkToHandler,
    fileStatusForScreenshot,
    imageBytesFromCaptureResult,
    navigationDistance,
    navigationTimeoutMs,
    prioritizeTreeResults,
    positiveInventoryDelta,
    publicScreenshotPluginStatus,
    resolveScreenshotPluginSpec,
    screenshotPathFromCaptureResult,
    startBridge,
};
