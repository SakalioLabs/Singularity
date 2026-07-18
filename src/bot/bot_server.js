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
const requestedCraftMaxAttempts = parseInt(getArg('craft-max-attempts', '3'), 10);
const CRAFT_MAX_ATTEMPTS = Number.isFinite(requestedCraftMaxAttempts)
    ? Math.max(1, Math.min(3, requestedCraftMaxAttempts))
    : 3;
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
const M2_PROTOCOL_PATH = path.resolve(__dirname, '..', 'singularity', 'data', 'm2_protocol.json');
const M2_PROTOCOL_BYTES = fs.readFileSync(M2_PROTOCOL_PATH);
const M2_PROTOCOL = JSON.parse(M2_PROTOCOL_BYTES.toString('utf8'));
const M2_PROTOCOL_SHA256 = crypto.createHash('sha256').update(M2_PROTOCOL_BYTES).digest('hex');
const M4_PROTOCOL_PATH = path.resolve(__dirname, '..', 'singularity', 'data', 'm4_protocol.json');
const M4_PROTOCOL_BYTES = fs.readFileSync(M4_PROTOCOL_PATH);
const M4_PROTOCOL = JSON.parse(M4_PROTOCOL_BYTES.toString('utf8'));
const M4_PROTOCOL_SHA256 = crypto.createHash('sha256').update(M4_PROTOCOL_BYTES).digest('hex');
const M4_BM012_PROTOCOL_PATH = path.resolve(__dirname, '..', 'singularity', 'data', 'm4_bm012_protocol.json');
const M4_BM012_PROTOCOL_BYTES = fs.readFileSync(M4_BM012_PROTOCOL_PATH);
const M4_BM012_PROTOCOL = JSON.parse(M4_BM012_PROTOCOL_BYTES.toString('utf8'));
const M4_BM012_PROTOCOL_SHA256 = crypto.createHash('sha256').update(M4_BM012_PROTOCOL_BYTES).digest('hex');
const M4_PATHFINDER_RECOVERY_POLICY_ID = 'm4-deadline-bound-pathfinder-readiness-v1';
const CRAFT_INVENTORY_REFRESH_POLICY_ID = 'crafting-table-window-items-inventory-refresh-v1';
const HOSTILE_ENTITY_NAMES = new Set([
    'blaze', 'bogged', 'breeze', 'cave_spider', 'creeper', 'drowned', 'elder_guardian',
    'endermite', 'evoker', 'ghast', 'guardian', 'hoglin', 'husk', 'magma_cube',
    'phantom', 'piglin_brute', 'pillager', 'ravager', 'shulker', 'silverfish',
    'skeleton', 'slime', 'spider', 'stray', 'vex', 'vindicator', 'warden', 'witch',
    'wither', 'wither_skeleton', 'zoglin', 'zombie', 'zombie_villager', 'zombified_piglin',
]);

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

function createM4PlayerLifecycleTracker(options = {}) {
    const nowMs = options.nowMs || (() => Date.now());
    const monotonicMs = options.monotonicMs || (() => Number(process.hrtime.bigint() / 1000000n));
    const trackerId = String(options.trackerId || crypto.randomUUID());
    const attachedBots = new WeakSet();
    let eventSequence = 0;
    let spawnCountTotal = 0;
    let deathCountTotal = 0;
    let respawnCountTotal = 0;
    let pendingRespawns = 0;
    let lastDeath = null;
    let lastRespawn = null;
    let baseline = null;

    function evidence(kind, activeBot) {
        eventSequence += 1;
        return {
            kind,
            event_sequence: eventSequence,
            observed_at_ms: Number(nowMs()),
            bridge_monotonic_ms: Number(monotonicMs()),
            position: compactPosition(activeBot?.entity?.position),
            health: Number(activeBot?.health ?? 0),
        };
    }

    function attach(activeBot) {
        if (!activeBot || typeof activeBot.on !== 'function' || attachedBots.has(activeBot)) {
            return false;
        }
        attachedBots.add(activeBot);
        activeBot.on('death', () => {
            deathCountTotal += 1;
            pendingRespawns += 1;
            lastDeath = {
                ...evidence('death', activeBot),
                death_count_total: deathCountTotal,
            };
        });
        activeBot.on('spawn', () => {
            spawnCountTotal += 1;
            if (pendingRespawns > 0) {
                pendingRespawns -= 1;
                respawnCountTotal += 1;
                lastRespawn = {
                    ...evidence('respawn', activeBot),
                    respawn_count_total: respawnCountTotal,
                    spawn_count_total: spawnCountTotal,
                };
            }
        });
        return true;
    }

    function startEpisode(runtime = {}) {
        pendingRespawns = 0;
        const identity = {
            tracker_id: trackerId,
            episode_id: String(runtime.episode_id || ''),
            level_name: String(runtime.level_name || ''),
            profile: String(runtime.profile || ''),
            protocol_sha256: String(runtime.protocol_sha256 || ''),
            baseline_death_count_total: deathCountTotal,
            baseline_respawn_count_total: respawnCountTotal,
            baseline_spawn_count_total: spawnCountTotal,
            baseline_observed_at_ms: Number(nowMs()),
            baseline_bridge_monotonic_ms: Number(monotonicMs()),
            initial_spawn_observed: spawnCountTotal > 0,
        };
        baseline = {
            ...identity,
            baseline_id: crypto.createHash('sha256')
                .update(JSON.stringify(identity))
                .digest('hex'),
        };
        return snapshot();
    }

    function snapshot() {
        if (!baseline) {
            return {
                type: 'm4_player_lifecycle',
                schema_version: 1,
                verifier_id: 'm4-player-lifecycle-verifier-v1',
                source: 'mineflayer_events',
                tracker_id: trackerId,
                baseline_established: false,
            };
        }
        const deathCount = deathCountTotal - baseline.baseline_death_count_total;
        const respawnCount = respawnCountTotal - baseline.baseline_respawn_count_total;
        const spawnCount = spawnCountTotal - baseline.baseline_spawn_count_total;
        return {
            type: 'm4_player_lifecycle',
            schema_version: 1,
            verifier_id: 'm4-player-lifecycle-verifier-v1',
            source: 'mineflayer_events',
            profile: baseline.profile,
            protocol_sha256: baseline.protocol_sha256,
            tracker_id: baseline.tracker_id,
            episode_id: baseline.episode_id,
            level_name: baseline.level_name,
            baseline_id: baseline.baseline_id,
            baseline_established: true,
            initial_spawn_observed: baseline.initial_spawn_observed,
            baseline_death_count_total: baseline.baseline_death_count_total,
            baseline_respawn_count_total: baseline.baseline_respawn_count_total,
            baseline_spawn_count_total: baseline.baseline_spawn_count_total,
            baseline_observed_at_ms: baseline.baseline_observed_at_ms,
            baseline_bridge_monotonic_ms: baseline.baseline_bridge_monotonic_ms,
            death_count_total: deathCountTotal,
            respawn_count_total: respawnCountTotal,
            spawn_count_total: spawnCountTotal,
            death_count: deathCount,
            respawn_count: respawnCount,
            spawn_count: spawnCount,
            pending_respawn_count: Math.max(0, deathCount - respawnCount),
            uninterrupted: deathCount === 0 && respawnCount === 0,
            last_death: lastDeath && lastDeath.death_count_total > baseline.baseline_death_count_total
                ? { ...lastDeath }
                : null,
            last_respawn: lastRespawn && lastRespawn.respawn_count_total > baseline.baseline_respawn_count_total
                ? { ...lastRespawn }
                : null,
        };
    }

    return { attach, snapshot, startEpisode };
}

const m4PlayerLifecycleTracker = createM4PlayerLifecycleTracker();

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

function resetM4PathfinderState(activeBot) {
    const report = {
        type: 'm4_navigation_recovery',
        schema_version: 1,
        policy_id: M4_PATHFINDER_RECOVERY_POLICY_ID,
        success: false,
        pathfinder_ready: false,
        goal_cleared: false,
        movement_stopped: false,
        control_states_cleared: false,
        command_replayed: false,
        world_mutation: false,
    };
    const activePathfinder = activeBot?.pathfinder;
    if (
        !activePathfinder
        || typeof activePathfinder.stop !== 'function'
        || typeof activePathfinder.setGoal !== 'function'
        || typeof activePathfinder.isMoving !== 'function'
        || typeof activeBot.clearControlStates !== 'function'
    ) {
        return { ...report, error: 'pathfinder recovery controls are unavailable' };
    }
    try {
        activePathfinder.stop();
        activePathfinder.setGoal(null);
        activeBot.clearControlStates();
        const goalCleared = activePathfinder.goal === null;
        const movementStopped = activePathfinder.isMoving() === false;
        return {
            ...report,
            success: goalCleared && movementStopped,
            pathfinder_ready: goalCleared && movementStopped,
            goal_cleared: goalCleared,
            movement_stopped: movementStopped,
            control_states_cleared: true,
            error: goalCleared && movementStopped ? '' : 'pathfinder state remained active after reset',
        };
    } catch (error) {
        return { ...report, error: error.message };
    }
}

function createRecoverNavigationHandler(
    getState = () => ({ bot, botReady }),
    options = {},
) {
    const yieldEventLoop = options.yieldEventLoop || (() => new Promise(resolve => setTimeout(resolve, 0)));
    return async (params = {}) => {
        const state = getState() || {};
        const activeBot = state.bot;
        if (!state.botReady || !activeBot?.entity?.position) {
            return {
                type: 'm4_navigation_recovery',
                schema_version: 1,
                policy_id: M4_PATHFINDER_RECOVERY_POLICY_ID,
                success: false,
                pathfinder_ready: false,
                goal_cleared: false,
                movement_stopped: false,
                control_states_cleared: false,
                command_replayed: false,
                world_mutation: false,
                trigger_command: String(params.trigger_command || ''),
                error: 'bot is not ready for navigation recovery',
            };
        }
        const firstPass = resetM4PathfinderState(activeBot);
        if (!firstPass.success) {
            return { ...firstPass, trigger_command: String(params.trigger_command || '') };
        }
        await yieldEventLoop();
        const finalPass = resetM4PathfinderState(activeBot);
        return {
            ...finalPass,
            trigger_command: String(params.trigger_command || ''),
            reset_pass_count: 2,
        };
    };
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

function prioritizeNearbyBlocks(blocks, limit = 50) {
    const maximum = Math.max(1, Number(limit) || 50);
    const sorted = [...(blocks || [])].sort((a, b) => Number(a.distance) - Number(b.distance));
    const selected = [];
    const selectedBlocks = new Set();
    const selectedNames = new Set();
    for (const block of sorted) {
        const name = String(block?.name || '');
        if (!name || selectedNames.has(name)) continue;
        selected.push(block);
        selectedBlocks.add(block);
        selectedNames.add(name);
        if (selected.length >= maximum) return selected;
    }
    for (const block of sorted) {
        if (selectedBlocks.has(block)) continue;
        selected.push(block);
        if (selected.length >= maximum) break;
    }
    return selected;
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
            let navigationRecovery = null;
            if (params.recover_pathfinder_on_failure === true) {
                navigationRecovery = resetM4PathfinderState(activeBot);
            } else if (activeBot.pathfinder && typeof activeBot.pathfinder.stop === 'function') {
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
            if (navigationRecovery) result.navigation_recovery = navigationRecovery;
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

function benchmarkProtocolBundle(profile = '') {
    const requested = String(profile || '').trim().toLowerCase();
    if (requested === M4_PROTOCOL.profile.toLowerCase() || requested === 'm4') {
        return { protocol: M4_PROTOCOL, protocolSha256: M4_PROTOCOL_SHA256 };
    }
    if (requested === M2_PROTOCOL.profile.toLowerCase() || requested === 'm2') {
        return { protocol: M2_PROTOCOL, protocolSha256: M2_PROTOCOL_SHA256 };
    }
    return { protocol: M1_PROTOCOL, protocolSha256: M1_PROTOCOL_SHA256 };
}

function benchmarkTaskBundle(taskId = '') {
    const normalized = String(taskId || '').trim().toUpperCase();
    if (M4_PROTOCOL.tasks.some(task => task.id === normalized)) {
        return { protocol: M4_PROTOCOL, protocolSha256: M4_PROTOCOL_SHA256 };
    }
    if (M2_PROTOCOL.tasks.some(task => task.id === normalized)) {
        return { protocol: M2_PROTOCOL, protocolSha256: M2_PROTOCOL_SHA256 };
    }
    return { protocol: M1_PROTOCOL, protocolSha256: M1_PROTOCOL_SHA256 };
}

function m4TaskContract(taskId = '') {
    const normalized = String(taskId || '').trim().toUpperCase();
    if (normalized === M4_BM012_PROTOCOL.task_id) {
        return { contract: M4_BM012_PROTOCOL, contractSha256: M4_BM012_PROTOCOL_SHA256 };
    }
    return { contract: null, contractSha256: '' };
}

function benchmarkProtocolStatus(activeBot, runtimeOverrides = {}, profile = '') {
    const { protocol, protocolSha256 } = benchmarkProtocolBundle(profile || runtimeOverrides.profile);
    const runtime = benchmarkRuntime(runtimeOverrides);
    const dependencies = installedBenchmarkDependencies();
    const serverBrand = String(activeBot?.game?.serverBrand || '');
    const observedMinecraftVersion = String(activeBot?.version || '');
    const errors = [];
    if (
        protocol.profile === M4_PROTOCOL.profile
        && M4_BM012_PROTOCOL.base_protocol_sha256 !== M4_PROTOCOL_SHA256
    ) {
        errors.push('BM-012 task contract is not bound to the active M4 base protocol');
    }
    if (runtime.seed !== protocol.world_seed) {
        errors.push(`benchmark seed ${runtime.seed || '<missing>'} does not match ${protocol.world_seed}`);
    }
    if (!runtime.episode_id) {
        errors.push('benchmark episode id is missing');
    }
    if (!runtime.level_name || !runtime.level_name.startsWith(`${runtime.episode_id}_`)) {
        errors.push('benchmark level name is missing or is not unique to the episode');
    }
    if (!/^[a-f0-9]{64}$/.test(runtime.server_jar_sha256)) {
        errors.push('server jar sha256 is missing or invalid');
    } else if (runtime.server_jar_sha256 !== protocol.server_jar_sha256) {
        errors.push(`server jar sha256 does not match pinned ${protocol.server_build}`);
    }
    const expectedDependencies = Object.keys(protocol.dependencies || {}).length > 0
        ? protocol.dependencies
        : {
            mineflayer: protocol.runtime_versions?.mineflayer,
            'mineflayer-pathfinder': protocol.runtime_versions?.mineflayer_pathfinder,
            'minecraft-data': protocol.runtime_versions?.minecraft_data,
        };
    for (const [name, expected] of Object.entries(expectedDependencies)) {
        if (!expected) continue;
        if (dependencies[name] !== expected) {
            errors.push(`${name}=${dependencies[name] || '<missing>'}, expected ${expected}`);
        }
    }
    const expectedNode = String(protocol.runtime_versions?.node || '');
    const observedNode = String(process.version || '').replace(/^v/, '');
    if (expectedNode && observedNode !== expectedNode) {
        errors.push(`node=${observedNode || '<missing>'}, expected ${expectedNode}`);
    }
    if (activeBot?.entity && !/paper/i.test(serverBrand)) {
        errors.push(`server brand ${serverBrand || '<missing>'} is not Paper`);
    }
    if (activeBot?.entity && observedMinecraftVersion !== protocol.minecraft_version) {
        errors.push(`Minecraft version ${observedMinecraftVersion || '<missing>'} does not match ${protocol.minecraft_version}`);
    }
    return {
        success: true,
        configured: errors.length === 0,
        profile: protocol.profile,
        protocol_sha256: protocolSha256,
        minecraft_version: protocol.minecraft_version,
        observed_minecraft_version: observedMinecraftVersion,
        server_type: protocol.server_type,
        server_build: protocol.server_build,
        server_jar_policy: protocol.server_jar_policy,
        agent_id: protocol.agent_id || protocol.identities?.agent || '',
        goal_generator_id: protocol.identities?.goal_generator || '',
        curriculum_id: protocol.identities?.curriculum || '',
        planner_id: protocol.planner_id || protocol.identities?.planner || '',
        planner_schema_id: protocol.planner_schema_id || '',
        planner_schema_sha256: protocol.planner_schema_sha256 || '',
        action_backend_id: protocol.action_backend_id || protocol.identities?.action_backend || '',
        verifier_id: protocol.verifier_id || protocol.identities?.goal_verifier || '',
        runtime_interrupt_id: protocol.identities?.runtime_interrupt || '',
        skill_runtime_profile_id: protocol.skill_runtime_profile_id || protocol.identities?.skill_runtime_profile || '',
        player_lifecycle_verifier_id: protocol.identities?.player_lifecycle_verifier || '',
        player_lifecycle_supported: protocol.profile === M4_PROTOCOL.profile,
        player_lifecycle_source: protocol.validation_contract?.survival?.player_lifecycle_source || '',
        reset_protocol_sha256: protocol.reset_protocol_sha256 || '',
        validation_protocol_sha256: protocol.validation_protocol_sha256 || '',
        llm: protocol.llm || {},
        runtime_controls: protocol.baseline_runtime_controls || {},
        server_brand: serverBrand,
        seed: runtime.seed,
        episode_id: runtime.episode_id,
        level_name: runtime.level_name,
        server_jar_sha256: runtime.server_jar_sha256,
        episode_strategy: protocol.episode_strategy,
        dependencies,
        runtime_versions: {
            node: observedNode,
            python: protocol.runtime_versions?.python || '',
        },
        tasks: protocol.tasks,
        task_contracts: protocol.profile === M4_PROTOCOL.profile ? {
            [M4_BM012_PROTOCOL.task_id]: {
                id: M4_BM012_PROTOCOL.id,
                sha256: M4_BM012_PROTOCOL_SHA256,
            },
        } : {},
        reset_supported: true,
        validation_supported: protocol.profile !== M1_PROTOCOL.profile,
        errors,
    };
}

function createBenchmarkProtocolHandler(
    getState = () => ({ bot, botReady }),
    runtimeOverrides = {},
) {
    return (params = {}) => {
        const state = getState() || {};
        return benchmarkProtocolStatus(state.bot, runtimeOverrides, params.profile);
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

function signedInventoryDelta(before, after) {
    const delta = {};
    for (const name of new Set([...Object.keys(before || {}), ...Object.keys(after || {})])) {
        const change = Number(after?.[name] || 0) - Number(before?.[name] || 0);
        if (change !== 0) delta[name] = change;
    }
    return delta;
}

function inventoryIncreaseState(activeBot, before, expectedItems = []) {
    const inventory = inventoryCounts(activeBot);
    const delta = positiveInventoryDelta(before, inventory);
    const expected = new Set(expectedItems || []);
    const observed = expected.size === 0
        ? Object.keys(delta).length > 0
        : [...expected].some(name => Number(delta[name] || 0) > 0);
    return { observed, inventory, delta };
}

async function waitForInventoryIncrease(
    activeBot,
    before,
    wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    maxWaitMs = 2000,
    expectedItems = [],
) {
    const pollMs = 100;
    for (let elapsed = 0; elapsed <= maxWaitMs; elapsed += pollMs) {
        const state = inventoryIncreaseState(activeBot, before, expectedItems);
        if (state.observed) {
            return { ...state, waited_ms: elapsed };
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

const M4_DIG_REQUIRED_TOOL_EQUIP_POLICY_ID = 'm4-dig-required-tool-equip-v1';
const M4_PICKUP_FALLBACK_CANDIDATE_MARGIN = 0.5;
const M4_PICKUP_SAME_CELL_NUDGE_MS = 100;

function blockHarvestToolTypes(block) {
    const harvestTools = block?.harvestTools;
    if (harvestTools === null || harvestTools === undefined) return [];
    if (typeof harvestTools !== 'object' || Array.isArray(harvestTools)) return null;
    return Object.entries(harvestTools)
        .filter(([, allowed]) => Boolean(allowed))
        .map(([itemType]) => Number(itemType))
        .filter(itemType => Number.isInteger(itemType) && itemType > 0)
        .sort((left, right) => left - right);
}

function itemCanHarvestBlock(block, item, harvestToolTypes) {
    const itemType = Number(item?.type);
    if (!Number.isInteger(itemType) || !harvestToolTypes.includes(itemType)) return false;
    if (typeof block?.canHarvest !== 'function') return true;
    try {
        return block.canHarvest(itemType) === true;
    } catch (_) {
        return false;
    }
}

function compatibleHarvestTools(activeBot, block, harvestToolTypes) {
    let inventoryItems = [];
    try {
        inventoryItems = activeBot?.inventory?.items?.() || [];
    } catch (_) {
        return [];
    }
    return inventoryItems.filter(item => (
        Number(item?.count || 0) > 0
        && itemCanHarvestBlock(block, item, harvestToolTypes)
    ));
}

function heldItemForConfirmation(activeBot) {
    return activeBot?.heldItem || (
        Array.isArray(activeBot?.entity?.equipment) ? activeBot.entity.equipment[0] : null
    );
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

async function waitForDroppedItem(
    activeBot,
    target,
    expectedItems,
    wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    maxWaitMs = 0,
) {
    const pollMs = 100;
    for (let elapsed = 0; elapsed <= maxWaitMs; elapsed += pollMs) {
        const drop = nearestDroppedItem(activeBot, target, expectedItems);
        if (drop) return { drop, waited_ms: elapsed };
        if (elapsed < maxWaitMs) await wait(pollMs);
    }
    return { drop: null, waited_ms: maxWaitMs };
}

function pickupStandableCandidate(activeBot, dropPosition, maximumDistance) {
    if (!activeBot?.blockAt || !dropPosition) return null;
    const base = {
        x: Math.floor(dropPosition.x),
        y: Math.floor(dropPosition.y),
        z: Math.floor(dropPosition.z),
    };
    const offsets = [
        [0, 0, 0],
        [1, 0, 0],
        [-1, 0, 0],
        [0, 0, 1],
        [0, 0, -1],
        [1, 0, 1],
        [1, 0, -1],
        [-1, 0, 1],
        [-1, 0, -1],
        [0, -1, 0],
        [0, 1, 0],
    ];
    const candidates = [];
    for (const [dx, dy, dz] of offsets) {
        const position = new Vec3(base.x + dx, base.y + dy, base.z + dz);
        const support = shelterBlockState(activeBot, position.offset(0, -1, 0));
        const feet = shelterBlockState(activeBot, position);
        const head = shelterBlockState(activeBot, position.offset(0, 1, 0));
        if (!support.solid || !feet.passable || !head.passable) continue;
        const expectedPlayerPosition = new Vec3(position.x + 0.5, position.y, position.z + 0.5);
        const pickupDistance = navigationDistance(expectedPlayerPosition, dropPosition, true);
        if (pickupDistance === null || pickupDistance > maximumDistance) continue;
        candidates.push({
            position: positionPayload(position),
            expected_player_position: positionPayload(expectedPlayerPosition),
            expected_pickup_distance: pickupDistance,
            current_distance: navigationDistance(activeBot.entity?.position, expectedPlayerPosition, true),
            support,
            feet,
            head,
        });
    }
    candidates.sort((left, right) => (
        Number(left.expected_pickup_distance) - Number(right.expected_pickup_distance) ||
        Number(left.current_distance) - Number(right.current_distance) ||
        Number(left.position.y) - Number(right.position.y) ||
        Number(left.position.x) - Number(right.position.x) ||
        Number(left.position.z) - Number(right.position.z)
    ));
    return candidates[0] || null;
}

async function approachDroppedItem(
    activeBot,
    target,
    expectedItems,
    wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    detectionWaitMs = 0,
    goalRange = 0,
    timeoutMs = 6000,
    options = {},
) {
    const detection = await waitForDroppedItem(
        activeBot,
        target,
        expectedItems,
        wait,
        detectionWaitMs,
    );
    const drop = detection.drop;
    if (!drop) {
        return {
            detected: false,
            attempted: false,
            detection_waited_ms: detection.waited_ms,
        };
    }
    const details = {
        detected: true,
        attempted: false,
        detection_waited_ms: detection.waited_ms,
        entity_id: drop.entity.id ?? null,
        item_name: drop.item_name,
        position: positionPayload(drop.entity.position),
        initial_distance: drop.player_distance,
        goal_range: goalRange,
    };
    if (!activeBot.pathfinder || typeof activeBot.pathfinder.goto !== 'function') {
        return { ...details, error: 'pathfinder is unavailable for pickup collection' };
    }

    const dropPosition = drop.entity.position.clone
        ? drop.entity.position.clone()
        : new Vec3(drop.entity.position.x, drop.entity.position.y, drop.entity.position.z);
    const completionGrounding = options.completionGrounding === true;
    if (!completionGrounding) {
        let timer = null;
        try {
            details.attempted = true;
            const navigation = Promise.resolve(activeBot.pathfinder.goto(
                new goals.GoalNear(
                    Math.floor(dropPosition.x),
                    Math.floor(dropPosition.y),
                    Math.floor(dropPosition.z),
                    goalRange,
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

    const monotonicMs = typeof options.monotonicMs === 'function'
        ? options.monotonicMs
        : () => Number(process.hrtime.bigint() / 1000000n);
    const navigationDeadlineMs = monotonicMs() + timeoutMs;
    const beforeInventory = options.beforeInventory || {};
    const currentDropPosition = () => {
        const current = activeBot.entities?.[drop.entity.id];
        const position = current?.position || drop.entity.position || dropPosition;
        return position?.clone
            ? position.clone()
            : new Vec3(position.x, position.y, position.z);
    };
    const runGroundedNavigation = async (goal, goalType) => {
        const remainingMs = Math.max(0, Math.floor(navigationDeadlineMs - monotonicMs()));
        const attempt = {
            attempted: false,
            goal_type: goalType,
            timeout_ms: remainingMs,
            pathfinder_resolved: false,
        };
        if (remainingMs <= 0) {
            attempt.error = 'pickup navigation budget exhausted';
            return attempt;
        }
        let timer = null;
        try {
            attempt.attempted = true;
            const navigation = Promise.resolve(activeBot.pathfinder.goto(goal));
            const timeout = new Promise((_, reject) => {
                timer = setTimeout(
                    () => reject(new Error(`pickup navigation timed out after ${remainingMs}ms`)),
                    remainingMs,
                );
            });
            await Promise.race([navigation, timeout]);
            attempt.pathfinder_resolved = true;
        } catch (error) {
            attempt.error = error.message;
            if (typeof activeBot.pathfinder.stop === 'function') activeBot.pathfinder.stop();
        } finally {
            if (timer) clearTimeout(timer);
        }
        const observedDropPosition = currentDropPosition();
        const inventoryState = inventoryIncreaseState(activeBot, beforeInventory, expectedItems);
        attempt.position = positionPayload(activeBot.entity?.position);
        attempt.drop_position = positionPayload(observedDropPosition);
        attempt.final_distance = navigationDistance(activeBot.entity?.position, observedDropPosition, true);
        attempt.goal_range = goalRange;
        attempt.distance_grounded = attempt.final_distance !== null && attempt.final_distance <= goalRange;
        attempt.inventory_delta_observed = inventoryState.observed;
        attempt.inventory_delta = inventoryState.delta;
        attempt.completion_grounded = attempt.distance_grounded || attempt.inventory_delta_observed;
        return attempt;
    };

    details.attempted = true;
    details.completion_policy = 'm4-pickup-collection-completion-grounding-v1';
    details.navigation_budget_ms = timeoutMs;
    details.fallback_attempt_limit = 1;
    details.fallback_attempt_count = 0;
    details.fallback_candidate_margin = M4_PICKUP_FALLBACK_CANDIDATE_MARGIN;
    details.fallback_candidate_max_distance = goalRange + details.fallback_candidate_margin;
    details.fallback_same_cell_nudge_attempt_limit = 1;
    details.fallback_same_cell_nudge_attempt_count = 0;
    const directGoal = new goals.GoalNear(
        Math.floor(dropPosition.x),
        Math.floor(dropPosition.y),
        Math.floor(dropPosition.z),
        goalRange,
    );
    const direct = await runGroundedNavigation(directGoal, 'GoalNear');
    details.direct_navigation = direct;
    details.final_distance = direct.final_distance ?? details.initial_distance;
    details.inventory_delta_observed = direct.inventory_delta_observed === true;
    details.inventory_delta = direct.inventory_delta || {};
    if (direct.completion_grounded) {
        details.success = true;
        details.completion_grounded = true;
        details.completion_grounded_by = direct.inventory_delta_observed ? 'inventory_delta' : 'measured_distance';
        if (direct.error) details.pathfinder_warning = direct.error;
        return details;
    }
    if (!direct.pathfinder_resolved) {
        details.success = false;
        details.completion_grounded = false;
        details.error = direct.error || 'pickup navigation did not reach the acquisition envelope';
        return details;
    }

    const fallbackDropPosition = currentDropPosition();
    const candidate = pickupStandableCandidate(
        activeBot,
        fallbackDropPosition,
        details.fallback_candidate_max_distance,
    );
    details.fallback_candidate = candidate;
    if (!candidate) {
        details.success = false;
        details.completion_grounded = false;
        details.error = 'pickup navigation completed outside acquisition range and no standable fallback was available';
        return details;
    }

    details.fallback_attempt_count = 1;
    const currentPosition = activeBot.entity?.position;
    const candidateAliasesCurrentCell = Boolean(currentPosition) && (
        Math.floor(Number(currentPosition.x)) === Number(candidate.position.x)
        && Math.floor(Number(currentPosition.y)) === Number(candidate.position.y)
        && Math.floor(Number(currentPosition.z)) === Number(candidate.position.z)
    );
    if (candidateAliasesCurrentCell) {
        const nudge = {
            policy_id: 'm4-pickup-same-cell-center-nudge-v1',
            required: true,
            attempted: false,
            duration_ms: 0,
            initial_position: positionPayload(currentPosition),
            target_position: candidate.expected_player_position,
            initial_center_distance: navigationDistance(
                currentPosition,
                candidate.expected_player_position,
                false,
            ),
            inventory_delta_observed: false,
            inventory_delta: {},
            completion_grounded: false,
        };
        details.fallback_same_cell_nudge_attempt_count = 1;
        details.fallback_same_cell_nudge = nudge;
        const remainingMs = Math.max(0, Math.floor(navigationDeadlineMs - monotonicMs()));
        const durationMs = Math.min(M4_PICKUP_SAME_CELL_NUDGE_MS, remainingMs);
        if (
            durationMs > 0
            && typeof activeBot.lookAt === 'function'
            && typeof activeBot.setControlState === 'function'
        ) {
            const center = candidate.expected_player_position;
            const lookTarget = new Vec3(
                Number(center.x),
                Number(activeBot.entity.position.y) + 1.62,
                Number(center.z),
            );
            try {
                nudge.attempted = true;
                nudge.duration_ms = durationMs;
                await activeBot.lookAt(lookTarget);
                activeBot.setControlState('forward', true);
                await wait(durationMs);
            } catch (error) {
                nudge.error = error.message;
            } finally {
                activeBot.setControlState('forward', false);
            }
            const observedDropPosition = currentDropPosition();
            const inventoryState = inventoryIncreaseState(activeBot, beforeInventory, expectedItems);
            nudge.position = positionPayload(activeBot.entity?.position);
            nudge.drop_position = positionPayload(observedDropPosition);
            nudge.final_distance = navigationDistance(
                activeBot.entity?.position,
                observedDropPosition,
                true,
            );
            nudge.distance_grounded = nudge.final_distance !== null && nudge.final_distance <= goalRange;
            nudge.inventory_delta_observed = inventoryState.observed;
            nudge.inventory_delta = inventoryState.delta;
            nudge.completion_grounded = nudge.distance_grounded || nudge.inventory_delta_observed;
            if (nudge.completion_grounded) {
                details.final_distance = nudge.final_distance;
                details.inventory_delta_observed = nudge.inventory_delta_observed;
                details.inventory_delta = nudge.inventory_delta;
                details.success = true;
                details.completion_grounded = true;
                details.completion_grounded_by = nudge.inventory_delta_observed
                    ? 'inventory_delta'
                    : 'measured_distance';
                return details;
            }
        } else {
            nudge.error = durationMs <= 0
                ? 'pickup navigation budget exhausted before same-cell nudge'
                : 'same-cell pickup nudge controls are unavailable';
        }
    }
    const fallback = await runGroundedNavigation(
        new goals.GoalBlock(candidate.position.x, candidate.position.y, candidate.position.z),
        'GoalBlock',
    );
    details.fallback_navigation = fallback;
    details.final_distance = fallback.final_distance ?? details.final_distance;
    details.inventory_delta_observed = fallback.inventory_delta_observed === true;
    details.inventory_delta = fallback.inventory_delta || {};
    details.success = fallback.completion_grounded === true;
    details.completion_grounded = details.success;
    if (details.success) {
        details.completion_grounded_by = fallback.inventory_delta_observed ? 'inventory_delta' : 'measured_distance';
        if (fallback.error) details.pathfinder_warning = fallback.error;
    } else {
        details.error = fallback.error || 'pickup fallback completed outside acquisition range';
    }
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

const M4_PLAYER_COLLISION_WIDTH = 0.6;
const M4_PLAYER_COLLISION_HEIGHT = 1.8;
const M4_PLAYER_COLLISION_EPSILON = 1e-9;

function m4PlayerCollisionEvidence(position) {
    const playerPosition = compactPosition(position);
    if (!playerPosition || !Object.values(playerPosition).every(Number.isFinite)) return null;
    const halfWidth = M4_PLAYER_COLLISION_WIDTH / 2;
    const box = {
        min: {
            x: playerPosition.x - halfWidth,
            y: playerPosition.y,
            z: playerPosition.z - halfWidth,
        },
        max: {
            x: playerPosition.x + halfWidth,
            y: playerPosition.y + M4_PLAYER_COLLISION_HEIGHT,
            z: playerPosition.z + halfWidth,
        },
        width: M4_PLAYER_COLLISION_WIDTH,
        height: M4_PLAYER_COLLISION_HEIGHT,
    };
    const axisCells = {};
    for (const axis of ['x', 'y', 'z']) {
        const first = Math.floor(box.min[axis] + M4_PLAYER_COLLISION_EPSILON);
        const last = Math.floor(box.max[axis] - M4_PLAYER_COLLISION_EPSILON);
        axisCells[axis] = Array.from({ length: last - first + 1 }, (_, index) => first + index);
    }
    const cells = [];
    for (const x of axisCells.x) {
        for (const y of axisCells.y) {
            for (const z of axisCells.z) cells.push({ x, y, z });
        }
    }
    return { player_position: playerPosition, player_collision_box: box, player_collision_cells: cells };
}

function m4AdjacentPlaceReferences(referencePosition, collisionCells) {
    const occupied = new Set(collisionCells.map(cell => `${cell.x},${cell.y},${cell.z}`));
    const reference = compactPosition(referencePosition);
    return [[1, 0], [-1, 0], [0, 1], [0, -1]]
        .map(([dx, dz]) => ({ x: reference.x + dx, y: reference.y, z: reference.z + dz }))
        .filter(candidate => !occupied.has(`${candidate.x},${candidate.y + 1},${candidate.z}`));
}

function entityName(entity) {
    return String(entity?.name || entity?.mobType || entity?.displayName || entity?.type || 'unknown')
        .trim()
        .toLowerCase()
        .replace(/^minecraft:/, '')
        .replace(/\s+/g, '_');
}

function isHostileEntity(entity) {
    const kind = String(entity?.kind || '').toLowerCase();
    return Boolean(
        entity?.hostile === true ||
        entity?.type === 'hostile' ||
        kind.includes('hostile') ||
        HOSTILE_ENTITY_NAMES.has(entityName(entity))
    );
}

function shelterBlockState(activeBot, position) {
    const block = activeBot?.blockAt ? activeBot.blockAt(position) : null;
    const name = String(block?.name || 'air');
    const type = Number(block?.type || 0);
    const collision = String(block?.boundingBox || ((type === 0 || name === 'air') ? 'empty' : 'block'));
    const solid = type !== 0 && name !== 'air' && collision === 'block';
    return {
        name,
        type,
        position: compactPosition(position),
        collision,
        solid,
        passable: collision === 'empty',
    };
}

function createShelterStateHandler(getState = () => ({ bot, botReady })) {
    return () => {
        const state = getState() || {};
        const activeBot = state.bot;
        if (!state.botReady || !activeBot?.entity?.position || typeof activeBot.blockAt !== 'function') {
            return {
                success: false,
                type: 'm4_shelter_machine_snapshot',
                source: 'mineflayer_world_state',
                error: 'bot is not ready for shelter-state verification',
            };
        }
        const playerPosition = compactPosition(activeBot.entity.position);
        const playerCell = {
            x: Math.floor(playerPosition.x),
            y: Math.floor(playerPosition.y),
            z: Math.floor(playerPosition.z),
        };
        const blocks = [];
        for (let dx = -1; dx <= 1; dx++) {
            for (let dy = -1; dy <= 2; dy++) {
                for (let dz = -1; dz <= 1; dz++) {
                    blocks.push(shelterBlockState(
                        activeBot,
                        new Vec3(playerCell.x + dx, playerCell.y + dy, playerCell.z + dz),
                    ));
                }
            }
        }
        const nearbyHostiles = [];
        for (const [id, entity] of Object.entries(activeBot.entities || {})) {
            if (entity === activeBot.entity || !entity?.position || !isHostileEntity(entity)) continue;
            const distance = activeBot.entity.position.distanceTo(entity.position);
            if (!Number.isFinite(distance) || distance > 16) continue;
            const position = compactPosition(entity.position);
            nearbyHostiles.push({
                id: Number(id),
                name: entityName(entity),
                position,
                cell: {
                    x: Math.floor(position.x),
                    y: Math.floor(position.y),
                    z: Math.floor(position.z),
                },
                distance,
            });
        }
        nearbyHostiles.sort((left, right) => left.distance - right.distance);
        return {
            success: true,
            type: 'm4_shelter_machine_snapshot',
            schema_version: 1,
            source: 'mineflayer_world_state',
            strategy_input: 'sealed_cell_v1',
            player_position: playerPosition,
            player_cell: playerCell,
            bounds: {
                min: { x: playerCell.x - 1, y: playerCell.y - 1, z: playerCell.z - 1 },
                max: { x: playerCell.x + 1, y: playerCell.y + 2, z: playerCell.z + 1 },
            },
            blocks,
            nearby_hostiles: nearbyHostiles,
            observed_at_ms: Date.now(),
        };
    };
}

function createPlaceHandler(getState = () => ({ bot, botReady })) {
    return async (params = {}) => {
        const equipPolicyId = 'm4-place-requested-item-equip-v1';
        const targetOccupancyPolicyId = 'm4-place-target-occupancy-v1';
        const targetPlayerOccupancyPolicyId = 'm4-place-target-player-occupancy-v1';
        const requirePlayerClearance = params.require_player_clearance === true;
        const state = getState() || {};
        const activeBot = state.bot;
        if (!state.botReady || !activeBot?.entity?.position) {
            return { success: false, error: 'bot is not ready to place a block' };
        }
        const rawCoordinates = [params.x, params.y, params.z];
        if (!rawCoordinates.every(value => value !== null && value !== undefined && value !== '')) {
            return { success: false, error: 'place requires finite reference coordinates' };
        }
        const coordinates = rawCoordinates.map(Number);
        if (!coordinates.every(Number.isFinite)) {
            return { success: false, error: 'place requires finite reference coordinates' };
        }
        const item = String(params.item || '').trim();
        if (!item) {
            return { success: false, error: 'place requires an item name', equip_policy_id: equipPolicyId };
        }
        let equippedItem = '';
        let playerClearanceEvidence = {};
        try {
            const referencePosition = new Vec3(...coordinates.map(Math.floor));
            const referenceBlock = activeBot.blockAt(referencePosition);
            if (!referenceBlock) return { success: false, error: 'No reference block' };
            const targetPosition = referencePosition.offset(0, 1, 0);
            const before = shelterBlockState(activeBot, targetPosition);
            const inventoryItem = activeBot.inventory?.items?.().find(
                entry => entry.name === item && Number(entry.count || 0) > 0,
            );
            if (!inventoryItem) {
                return {
                    success: false,
                    error: `${item} is not available for placement`,
                    item,
                    equip_policy_id: equipPolicyId,
                    target_occupancy_policy_id: targetOccupancyPolicyId,
                    ...(requirePlayerClearance ? {
                        target_player_occupancy_policy_id: targetPlayerOccupancyPolicyId,
                    } : {}),
                };
            }
            if (before.solid) {
                return {
                    success: false,
                    error: `placement target is occupied by ${before.name}`,
                    item,
                    equip_policy_id: equipPolicyId,
                    target_occupancy_policy_id: targetOccupancyPolicyId,
                    ...(requirePlayerClearance ? {
                        target_player_occupancy_policy_id: targetPlayerOccupancyPolicyId,
                    } : {}),
                    requires_replan: true,
                    reference_position: compactPosition(referencePosition),
                    placed_position: compactPosition(targetPosition),
                    target_block_before: before,
                    required_target_state: 'air_or_replaceable',
                };
            }
            if (requirePlayerClearance) {
                const collision = m4PlayerCollisionEvidence(activeBot.entity.position);
                if (!collision) {
                    return {
                        success: false,
                        error: 'M4 placement requires a finite player position',
                        item,
                        equip_policy_id: equipPolicyId,
                        target_occupancy_policy_id: targetOccupancyPolicyId,
                        target_player_occupancy_policy_id: targetPlayerOccupancyPolicyId,
                        requires_replan: true,
                        reference_position: compactPosition(referencePosition),
                        placed_position: compactPosition(targetPosition),
                        target_block_before: before,
                        required_target_state: 'air_or_replaceable_and_outside_player_collision_cells',
                    };
                }
                const target = compactPosition(targetPosition);
                const targetIntersectsPlayer = collision.player_collision_cells.some(
                    cell => cell.x === target.x && cell.y === target.y && cell.z === target.z,
                );
                const adjacentReferenceCandidates = m4AdjacentPlaceReferences(
                    referencePosition,
                    collision.player_collision_cells,
                );
                playerClearanceEvidence = {
                    target_player_occupancy_policy_id: targetPlayerOccupancyPolicyId,
                    ...collision,
                    target_intersects_player: targetIntersectsPlayer,
                    adjacent_reference_candidates: adjacentReferenceCandidates,
                    replan_mode: 'next_cycle',
                    replan_candidate_limit: 4,
                };
                if (targetIntersectsPlayer) {
                    return {
                        success: false,
                        error: 'placement target intersects the player collision cells',
                        item,
                        equip_policy_id: equipPolicyId,
                        target_occupancy_policy_id: targetOccupancyPolicyId,
                        ...playerClearanceEvidence,
                        requires_replan: true,
                        replan_reason: 'choose one adjacent reference whose target clears block and player occupancy',
                        reference_position: compactPosition(referencePosition),
                        placed_position: target,
                        target_block_before: before,
                        required_target_state: 'air_or_replaceable_and_outside_player_collision_cells',
                    };
                }
            }
            try {
                await activeBot.equip(inventoryItem, 'hand');
            } catch (error) {
                return {
                    success: false,
                    error: `could not equip ${item}: ${error.message}`,
                    item,
                    equip_policy_id: equipPolicyId,
                    target_occupancy_policy_id: targetOccupancyPolicyId,
                    ...playerClearanceEvidence,
                };
            }
            const heldItem = activeBot.heldItem || (
                Array.isArray(activeBot.entity?.equipment) ? activeBot.entity.equipment[0] : null
            );
            equippedItem = String(heldItem?.name || '');
            if (equippedItem !== item) {
                return {
                    success: false,
                    error: `requested item ${item} was not equipped`,
                    item,
                    equipped_item: equippedItem,
                    equip_policy_id: equipPolicyId,
                    target_occupancy_policy_id: targetOccupancyPolicyId,
                    ...playerClearanceEvidence,
                };
            }
            await activeBot.placeBlock(referenceBlock, new Vec3(0, 1, 0));
            const after = shelterBlockState(activeBot, targetPosition);
            const observed = after.name !== 'air' && after.name !== before.name && after.name === item;
            return {
                success: observed,
                error: observed ? '' : 'placed block was not observed at the target',
                item,
                equipped_item: equippedItem,
                requested_item_equipped: true,
                equip_policy_id: equipPolicyId,
                target_occupancy_policy_id: targetOccupancyPolicyId,
                ...playerClearanceEvidence,
                reference_position: compactPosition(referencePosition),
                placed_position: compactPosition(targetPosition),
                target_block_before: before,
                target_block_after: after,
            };
        } catch (e) {
            return {
                success: false,
                error: e.message,
                item,
                equipped_item: equippedItem,
                requested_item_equipped: equippedItem === item,
                equip_policy_id: equipPolicyId,
                target_occupancy_policy_id: targetOccupancyPolicyId,
                ...playerClearanceEvidence,
            };
        }
    };
}

function fixturePosition(spawnPoint) {
    return new Vec3(
        Math.floor(Number(spawnPoint.x)) + 1,
        Math.floor(Number(spawnPoint.y)),
        Math.floor(Number(spawnPoint.z)),
    );
}

function relativeWorldPosition(spawnPoint, relative = {}) {
    return new Vec3(
        Math.floor(Number(spawnPoint.x)) + Math.floor(Number(relative.x || 0)),
        Math.floor(Number(spawnPoint.y)) + Math.floor(Number(relative.y || 0)),
        Math.floor(Number(spawnPoint.z)) + Math.floor(Number(relative.z || 0)),
    );
}

function fixtureBlockStates(activeBot, spawnPoint, taskSpec) {
    const specs = Array.isArray(taskSpec?.initial_blocks) ? taskSpec.initial_blocks : [];
    return specs.map(spec => {
        const position = relativeWorldPosition(spawnPoint, spec.relative_position || {});
        const block = activeBot?.blockAt ? activeBot.blockAt(position) : null;
        return {
            expected_name: String(spec.name || ''),
            name: String(block?.name || 'air'),
            position: compactPosition(position),
            relative_position: spec.relative_position || {},
        };
    });
}

function constructionSnapshot(activeBot, spawnPoint, taskSpec) {
    const zone = taskSpec?.fixture?.construction_zone;
    if (!zone || !spawnPoint) return {};
    const origin = relativeWorldPosition(spawnPoint, zone.origin_relative || {});
    const size = zone.size || {};
    const width = Math.max(1, Math.floor(Number(size.x || 0)));
    const height = Math.max(1, Math.floor(Number(size.y || 0)));
    const depth = Math.max(1, Math.floor(Number(size.z || 0)));
    const blocks = [];
    for (let x = 0; x < width; x++) {
        for (let y = 0; y < height; y++) {
            for (let z = 0; z < depth; z++) {
                const position = origin.offset(x, y, z);
                const block = activeBot?.blockAt ? activeBot.blockAt(position) : null;
                blocks.push({
                    name: String(block?.name || 'air'),
                    position: compactPosition(position),
                });
            }
        }
    }
    const snapshot = {
        origin: compactPosition(origin),
        size: { x: width, y: height, z: depth },
        blocks,
    };
    snapshot.sha256 = crypto.createHash('sha256').update(JSON.stringify(snapshot)).digest('hex');
    return snapshot;
}

function benchmarkBotState(activeBot, spawnPoint, taskSpec = null) {
    const firstSpec = Array.isArray(taskSpec?.initial_blocks) ? taskSpec.initial_blocks[0] : null;
    const fixture = spawnPoint
        ? (firstSpec ? relativeWorldPosition(spawnPoint, firstSpec.relative_position || {}) : fixturePosition(spawnPoint))
        : null;
    const fixtureBlock = fixture && activeBot?.blockAt ? activeBot.blockAt(fixture) : null;
    return {
        position: compactPosition(activeBot?.entity?.position),
        spawn_position: compactPosition(spawnPoint),
        health: Number(activeBot?.health ?? 0),
        food: Number(activeBot?.food ?? 0),
        food_saturation: Number(activeBot?.foodSaturation ?? 0),
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
        fixture_blocks: spawnPoint ? fixtureBlockStates(activeBot, spawnPoint, taskSpec) : [],
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

function benchmarkResetChecks(postState, taskSpec, protocol = M1_PROTOCOL, taskContract = null) {
    const expectedBlocks = Array.isArray(taskSpec.initial_blocks) ? taskSpec.initial_blocks : [];
    const expectedInventory = taskSpec.initial_inventory || protocol.initial_inventory || {};
    const expectedTime = Number(
        taskContract?.initial_time_of_day ?? protocol.time_of_day ?? protocol.initial_time_of_day
    );
    const expectedPlayer = protocol.initial_player_state || {};
    const isM4 = protocol.profile === M4_PROTOCOL.profile;
    const expectedFixture = expectedBlocks[0]?.name || 'air';
    const finalDistance = positionDistance(postState.position, postState.spawn_position);
    const fixturesMatch = expectedBlocks.length === postState.fixture_blocks.length
        && postState.fixture_blocks.every(item => item.name === item.expected_name);
    return {
        inventory_exact: inventoryExactlyMatches(postState.inventory, expectedInventory),
        position_at_spawn: finalDistance <= 1.5,
        position_distance: Number.isFinite(finalDistance) ? Number(finalDistance.toFixed(3)) : null,
        game_mode: postState.game_mode === protocol.game_mode,
        difficulty: postState.difficulty === protocol.difficulty,
        dimension: /overworld/i.test(postState.dimension),
        daytime: postState.time_of_day >= 0 && postState.time_of_day < 12000,
        time_initialized: Math.abs(postState.time_of_day - expectedTime) <= 600,
        weather: postState.weather === protocol.weather,
        health: postState.health >= Number(expectedPlayer.health ?? 20),
        food: postState.food >= Number(expectedPlayer.food ?? 20),
        saturation: !isM4 || Math.abs(postState.food_saturation - Number(expectedPlayer.saturation ?? 5)) <= 0.25,
        fixture: isM4
            ? true
            : protocol.profile === M1_PROTOCOL.profile
            ? postState.fixture?.block === expectedFixture
            : fixturesMatch,
    };
}

function regionCommand(spawnPoint, region, blockName) {
    const min = relativeWorldPosition(spawnPoint, region.min || {});
    const max = relativeWorldPosition(spawnPoint, region.max || {});
    return `/fill ${min.x} ${min.y} ${min.z} ${max.x} ${max.y} ${max.z} minecraft:${blockName}`;
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
        const taskId = String(params.task_id || '').toUpperCase();
        const { protocol, protocolSha256 } = benchmarkTaskBundle(taskId);
        const protocolStatus = benchmarkProtocolStatus(activeBot, runtimeOverrides, protocol.profile);
        if (!protocolStatus.configured) {
            return {
                success: false,
                error: `${protocol.profile} benchmark protocol is not configured`,
                protocol_errors: protocolStatus.errors,
            };
        }
        const taskSpec = protocol.tasks.find((task) => task.id === taskId);
        if (!taskSpec) {
            const suite = protocol.profile === M1_PROTOCOL.profile
                ? 'M1'
                : protocol.profile === M2_PROTOCOL.profile ? 'M2' : 'M4';
            return { success: false, error: `unsupported ${suite} benchmark task: ${taskId || '<missing>'}` };
        }
        const spawnPoint = activeBot.spawnPoint;
        if (!spawnPoint || ![spawnPoint.x, spawnPoint.y, spawnPoint.z].every(Number.isFinite)) {
            return { success: false, error: 'bot spawn point is unavailable' };
        }

        const beforeState = benchmarkBotState(activeBot, spawnPoint, taskSpec);
        const isM4 = protocol.profile === M4_PROTOCOL.profile;
        const { contract: taskContract, contractSha256 } = isM4
            ? m4TaskContract(taskId)
            : { contract: null, contractSha256: '' };
        const initialInventory = taskSpec.initial_inventory || protocol.initial_inventory || {};
        const initialTime = Number(
            taskContract?.initial_time_of_day ?? protocol.time_of_day ?? protocol.initial_time_of_day
        );
        const commands = [
            `/execute in minecraft:overworld run tp @s ${spawnPoint.x} ${spawnPoint.y} ${spawnPoint.z}`,
            `/gamemode ${protocol.game_mode} @s`,
            '/clear @s',
            '/kill @e[type=minecraft:item,distance=..16]',
        ];
        const fixture = taskSpec.fixture || {};
        if (protocol.profile === M1_PROTOCOL.profile) {
            const position = fixturePosition(spawnPoint);
            commands.push(`/setblock ${position.x} ${position.y} ${position.z} minecraft:air`);
        } else {
            for (const region of fixture.clear_regions || []) {
                commands.push(regionCommand(spawnPoint, region, 'air'));
            }
            for (const spec of taskSpec.initial_blocks || []) {
                const position = relativeWorldPosition(spawnPoint, spec.relative_position || {});
                commands.push(`/setblock ${position.x} ${position.y} ${position.z} minecraft:air`);
            }
            for (const region of fixture.fill_regions || []) {
                commands.push(regionCommand(spawnPoint, region, String(region.name || 'air')));
            }
        }
        for (const spec of taskSpec.initial_blocks || []) {
            const position = relativeWorldPosition(spawnPoint, spec.relative_position || {});
            commands.push(`/setblock ${position.x} ${position.y} ${position.z} minecraft:${spec.name}`);
        }
        commands.push(
            `/time set ${initialTime}`,
            `/weather ${protocol.weather}`,
            `/difficulty ${protocol.difficulty}`,
        );
        if (isM4) {
            commands.push('/effect clear @s');
            for (const [name, value] of Object.entries(protocol.gamerules || {})) {
                commands.push(`/gamerule ${name} ${value ? 'true' : 'false'}`);
            }
        } else {
            commands.push(
                '/effect give @s minecraft:instant_health 1 255 true',
                '/effect give @s minecraft:saturation 1 255 true',
            );
        }
        for (const [item, count] of Object.entries(initialInventory)) {
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

        const afterState = benchmarkBotState(activeBot, spawnPoint, taskSpec);
        const structureBaseline = constructionSnapshot(activeBot, spawnPoint, taskSpec);
        const checks = benchmarkResetChecks(afterState, taskSpec, protocol, taskContract);
        const lifecycleTracker = state.playerLifecycleTracker || m4PlayerLifecycleTracker;
        const playerLifecycle = isM4 && lifecycleTracker && typeof lifecycleTracker.startEpisode === 'function'
            ? lifecycleTracker.startEpisode({
                episode_id: protocolStatus.episode_id,
                level_name: protocolStatus.level_name,
                profile: protocol.profile,
                protocol_sha256: protocolSha256,
            })
            : null;
        if (isM4) {
            checks.player_lifecycle_baseline = Boolean(
                playerLifecycle
                && playerLifecycle.baseline_established === true
                && playerLifecycle.initial_spawn_observed === true
                && playerLifecycle.episode_id === protocolStatus.episode_id
                && playerLifecycle.protocol_sha256 === protocolSha256
                && playerLifecycle.death_count === 0
                && playerLifecycle.respawn_count === 0
                && playerLifecycle.uninterrupted === true
            );
        }
        const failedChecks = Object.entries(checks)
            .filter(([name, value]) => name !== 'position_distance' && value !== true)
            .map(([name]) => name);
        const success = failedChecks.length === 0;
        return {
            success,
            error: success ? '' : 'benchmark reset postconditions failed; ensure the bot is a server operator',
            profile: protocol.profile,
            protocol_sha256: protocolSha256,
            reset_protocol_sha256: protocol.reset_protocol_sha256 || '',
            validation_protocol_sha256: protocol.validation_protocol_sha256 || '',
            episode_id: protocolStatus.episode_id,
            level_name: protocolStatus.level_name,
            seed: protocolStatus.seed,
            server_brand: protocolStatus.server_brand,
            observed_minecraft_version: protocolStatus.observed_minecraft_version,
            server_jar_sha256: protocolStatus.server_jar_sha256,
            task_id: taskId,
            task_contract_id: String(taskContract?.id || ''),
            task_contract_sha256: contractSha256,
            expected: {
                initial_inventory: initialInventory,
                initial_blocks: taskSpec.initial_blocks,
                game_mode: protocol.game_mode,
                difficulty: protocol.difficulty,
                time_of_day: initialTime,
                weather: protocol.weather,
                gamerules: protocol.gamerules || {},
            },
            before_state: beforeState,
            after_state: afterState,
            structure_baseline: structureBaseline,
            ...(isM4 ? { player_lifecycle: playerLifecycle } : {}),
            checks,
            failed_checks: failedChecks,
            command_count: commands.length,
            gamerules: protocol.gamerules || {},
        };
    };
}

function createBenchmarkVerifyHandler(
    getState = () => ({ bot, botReady }),
    runtimeOverrides = {},
) {
    return async (params = {}) => {
        const state = getState() || {};
        const activeBot = state.bot;
        if (!state.botReady || !activeBot?.entity) {
            return { success: false, error: 'bot is not ready for benchmark verification' };
        }
        const taskId = String(params.task_id || '').trim().toUpperCase();
        const { protocol, protocolSha256 } = benchmarkTaskBundle(taskId);
        const taskSpec = protocol.tasks.find(task => task.id === taskId);
        if (!taskSpec || protocol.profile !== M2_PROTOCOL.profile) {
            return { success: false, error: `unsupported M2 verification task: ${taskId || '<missing>'}` };
        }
        const protocolStatus = benchmarkProtocolStatus(activeBot, runtimeOverrides, protocol.profile);
        if (!protocolStatus.configured) {
            return {
                success: false,
                error: `${protocol.profile} benchmark protocol is not configured`,
                protocol_errors: protocolStatus.errors,
            };
        }
        const spawnPoint = activeBot.spawnPoint;
        if (!spawnPoint || ![spawnPoint.x, spawnPoint.y, spawnPoint.z].every(Number.isFinite)) {
            return { success: false, error: 'bot spawn point is unavailable' };
        }
        const equipment = Array.isArray(activeBot.entity?.equipment)
            ? activeBot.entity.equipment
                .map((item, slot) => item ? ({ slot, name: item.name, count: item.count }) : null)
                .filter(Boolean)
            : [];
        return {
            success: true,
            profile: protocol.profile,
            protocol_sha256: protocolSha256,
            validation_protocol_sha256: protocol.validation_protocol_sha256,
            task_id: taskId,
            inventory: inventoryCounts(activeBot),
            player_position: compactPosition(activeBot.entity.position),
            equipment,
            fixture_blocks: fixtureBlockStates(activeBot, spawnPoint, taskSpec),
            structure_post: constructionSnapshot(activeBot, spawnPoint, taskSpec),
            observed_at_ms: Date.now(),
        };
    };
}

function shelterTemplatePositions(origin) {
    const ox = Math.floor(Number(origin.x));
    const oy = Math.floor(Number(origin.y));
    const oz = Math.floor(Number(origin.z));
    const entranceX = ox + 2;
    const entranceZ = oz;
    const walls = [];
    for (let level = 0; level < 2; level++) {
        for (let x = ox; x < ox + 5; x++) {
            for (let z = oz; z < oz + 5; z++) {
                const perimeter = x === ox || x === ox + 4 || z === oz || z === oz + 4;
                if (!perimeter || (x === entranceX && z === entranceZ)) continue;
                walls.push(new Vec3(x, oy + level, z));
            }
        }
    }
    const roof = [];
    for (let x = ox; x < ox + 5; x++) {
        for (let z = oz; z < oz + 5; z++) {
            const perimeter = x === ox || x === ox + 4 || z === oz || z === oz + 4;
            if (perimeter) roof.push(new Vec3(x, oy + 2, z));
        }
    }
    for (let x = ox + 1; x < ox + 4; x++) {
        for (let z = oz + 1; z < oz + 4; z++) {
            roof.push(new Vec3(x, oy + 2, z));
        }
    }
    return {
        positions: [...walls, ...roof],
        wall_count: walls.length,
        roof_count: roof.length,
        entrance: { x: entranceX, z: entranceZ, min_y: oy, max_y: oy + 1 },
    };
}

function placementReference(activeBot, target) {
    const candidates = [
        { offset: new Vec3(0, -1, 0), face: new Vec3(0, 1, 0) },
        { offset: new Vec3(-1, 0, 0), face: new Vec3(1, 0, 0) },
        { offset: new Vec3(1, 0, 0), face: new Vec3(-1, 0, 0) },
        { offset: new Vec3(0, 0, -1), face: new Vec3(0, 0, 1) },
        { offset: new Vec3(0, 0, 1), face: new Vec3(0, 0, -1) },
    ];
    for (const candidate of candidates) {
        const position = target.plus(candidate.offset);
        const block = activeBot.blockAt(position);
        if (isSolidBlock(block)) {
            return { block, face: candidate.face };
        }
    }
    return null;
}

function sealedCellTemplatePositions(origin) {
    const walls = [];
    for (const [dx, dz] of [[0, -1], [1, 0], [0, 1], [-1, 0]]) {
        walls.push(origin.offset(dx, 0, dz));
    }
    for (const [dx, dz] of [[0, -1], [1, 0], [0, 1], [-1, 0]]) {
        walls.push(origin.offset(dx, 1, dz));
    }
    return [...walls, origin.offset(0, 2, 0)];
}

function blockPositionKey(position) {
    return `${Number(position.x)},${Number(position.y)},${Number(position.z)}`;
}

function isSolidBlock(block) {
    return Boolean(
        block
        && block.type !== 0
        && block.name !== 'air'
        && block.boundingBox !== 'empty'
    );
}

function simulatedPlacementReference(solidAt, target) {
    const candidates = [
        { offset: new Vec3(0, -1, 0), face: new Vec3(0, 1, 0) },
        { offset: new Vec3(-1, 0, 0), face: new Vec3(1, 0, 0) },
        { offset: new Vec3(1, 0, 0), face: new Vec3(-1, 0, 0) },
        { offset: new Vec3(0, 0, -1), face: new Vec3(0, 0, 1) },
        { offset: new Vec3(0, 0, 1), face: new Vec3(0, 0, -1) },
    ];
    for (const candidate of candidates) {
        const position = target.plus(candidate.offset);
        if (solidAt(position)) {
            return {
                position: compactPosition(position),
                face: compactPosition(candidate.face),
            };
        }
    }
    return null;
}

function sealedCellPlacementPreflight(activeBot, origin) {
    const targets = sealedCellTemplatePositions(origin);
    const virtualSolidity = new Map();
    const solidAt = position => {
        const key = blockPositionKey(position);
        if (virtualSolidity.has(key)) return virtualSolidity.get(key);
        return isSolidBlock(activeBot.blockAt(position));
    };
    const setSolid = (position, solid) => virtualSolidity.set(blockPositionKey(position), Boolean(solid));
    const placementOrder = [];
    let temporaryScaffold = null;

    for (const target of targets) {
        setSolid(target, false);
        let reference = simulatedPlacementReference(solidAt, target);
        if (!reference && target.equals(origin.offset(0, 2, 0))) {
            const scaffoldTarget = origin.offset(1, 2, 0);
            if (solidAt(scaffoldTarget)) {
                return {
                    passed: false,
                    error: 'temporary scaffold target is occupied',
                    failed_position: compactPosition(scaffoldTarget),
                    placement_order: placementOrder,
                };
            }
            const scaffoldReference = simulatedPlacementReference(solidAt, scaffoldTarget);
            if (!scaffoldReference) {
                return {
                    passed: false,
                    error: 'no grounded neighbor exists for temporary roof scaffold',
                    failed_position: compactPosition(scaffoldTarget),
                    placement_order: placementOrder,
                };
            }
            setSolid(scaffoldTarget, true);
            temporaryScaffold = compactPosition(scaffoldTarget);
            reference = simulatedPlacementReference(solidAt, target);
        }
        if (!reference) {
            return {
                passed: false,
                error: 'no grounded neighbor exists for sealed-cell placement',
                failed_position: compactPosition(target),
                placement_order: placementOrder,
            };
        }
        placementOrder.push({
            position: compactPosition(target),
            reference,
        });
        setSolid(target, true);
    }
    return {
        passed: true,
        target_count: targets.length,
        placement_order: placementOrder,
        temporary_scaffold: temporaryScaffold,
    };
}

function findSealedCellRelocation(activeBot, origin, maxRadius = 6) {
    const yOffsets = [0, 1, -1, 2, -2];
    for (let radius = 1; radius <= maxRadius; radius++) {
        const offsets = [];
        for (let dx = -radius; dx <= radius; dx++) {
            for (let dz = -radius; dz <= radius; dz++) {
                if (Math.max(Math.abs(dx), Math.abs(dz)) !== radius) continue;
                offsets.push({ dx, dz, distance: (dx * dx) + (dz * dz) });
            }
        }
        offsets.sort((left, right) => (
            left.distance - right.distance || left.dx - right.dx || left.dz - right.dz
        ));
        for (const { dx, dz } of offsets) {
            for (const dy of yOffsets) {
                const candidate = origin.offset(dx, dy, dz);
                if (isSolidBlock(activeBot.blockAt(candidate))) continue;
                if (isSolidBlock(activeBot.blockAt(candidate.offset(0, 1, 0)))) continue;
                if (!isSolidBlock(activeBot.blockAt(candidate.offset(0, -1, 0)))) continue;
                const preflight = sealedCellPlacementPreflight(activeBot, candidate);
                if (!preflight.passed) continue;
                return {
                    origin: compactPosition(candidate),
                    target: {
                        x: Number(candidate.x) + 0.5,
                        y: Number(candidate.y),
                        z: Number(candidate.z) + 0.5,
                    },
                    search_radius: maxRadius,
                };
            }
        }
    }
    return null;
}

function createBuildShelterCellHandler(
    getState = () => ({ bot, botReady }),
    wait = ms => new Promise(resolve => setTimeout(resolve, ms)),
) {
    return async (params = {}) => {
        const state = getState() || {};
        const activeBot = state.bot;
        if (!state.botReady || !activeBot?.entity?.position) {
            return { success: false, error: 'bot is not ready to build an M4 sealed cell' };
        }
        const requested = params.origin && typeof params.origin === 'object' ? params.origin : {};
        if (![requested.x, requested.y, requested.z].every(Number.isFinite)) {
            return { success: false, error: 'build_shelter_cell requires a finite origin' };
        }
        const origin = new Vec3(
            Math.floor(requested.x),
            Math.floor(requested.y),
            Math.floor(requested.z),
        );
        const playerCell = new Vec3(
            Math.floor(activeBot.entity.position.x),
            Math.floor(activeBot.entity.position.y),
            Math.floor(activeBot.entity.position.z),
        );
        if (!origin.equals(playerCell)) {
            return {
                success: false,
                error: 'build_shelter_cell origin must match the current player cell',
                requested_origin: compactPosition(origin),
                player_cell: compactPosition(playerCell),
            };
        }
        const allowed = new Set([
            'cobblestone', 'dirt', 'oak_planks', 'spruce_planks', 'birch_planks',
            'jungle_planks', 'acacia_planks', 'dark_oak_planks', 'mangrove_planks',
            'cherry_planks', 'bamboo_planks', 'crimson_planks', 'warped_planks',
        ]);
        const material = String(params.material || '');
        if (!allowed.has(material)) {
            return { success: false, error: `sealed-cell material ${material || '<missing>'} is not allowlisted` };
        }
        const targets = sealedCellTemplatePositions(origin);
        const requiredCount = targets.length;
        const requiredInventoryCount = requiredCount + 1;
        const beforeInventory = inventoryCounts(activeBot);
        if (Number(beforeInventory[material] || 0) < requiredInventoryCount) {
            return {
                success: false,
                error: `sealed-cell template requires ${requiredInventoryCount} ${material} including one temporary scaffold`,
                required_count: requiredInventoryCount,
                available_count: Number(beforeInventory[material] || 0),
            };
        }
        const preflight = sealedCellPlacementPreflight(activeBot, origin);
        if (!preflight.passed) {
            const relocation = findSealedCellRelocation(activeBot, origin);
            const afterInventory = inventoryCounts(activeBot);
            const inventoryPreserved = Number(afterInventory[material] || 0)
                === Number(beforeInventory[material] || 0);
            return {
                success: false,
                template_id: 'm4-sealed-cell-v1',
                material,
                origin: compactPosition(origin),
                error: preflight.error,
                failed_position: preflight.failed_position,
                placed_count: 0,
                placed_positions: [],
                placement_deltas: [],
                inventory_before: beforeInventory,
                inventory_after: afterInventory,
                preflight,
                atomicity: {
                    passed: inventoryPreserved,
                    mode: 'mutation_free_preflight_rejection',
                    scope: 'final_placements_and_material_inventory',
                    mutation_count: 0,
                    inventory_preserved: inventoryPreserved,
                },
                relocation_required: Boolean(relocation),
                relocation_origin: relocation?.origin || null,
                relocation_target: relocation?.target || null,
                relocation_search_radius: relocation?.search_radius || 6,
            };
        }
        const item = activeBot.inventory.items().find(entry => entry.name === material);
        if (!item) return { success: false, error: `${material} is not available for placement` };
        try {
            await activeBot.equip(item, 'hand');
        } catch (error) {
            return { success: false, error: `could not equip ${material}: ${error.message}` };
        }

        const placedPositions = [];
        const removedPositions = [];
        const placementDeltas = [];
        let temporaryScaffold = null;
        const rollbackPlacements = async () => {
            const candidates = [...placedPositions];
            if (temporaryScaffold) candidates.push(temporaryScaffold);
            const unique = [];
            const seen = new Set();
            for (const position of candidates.reverse()) {
                const key = blockPositionKey(position);
                if (seen.has(key)) continue;
                seen.add(key);
                unique.push(position);
            }
            const removed = [];
            const issues = [];
            for (const position of unique) {
                const target = new Vec3(position.x, position.y, position.z);
                const block = activeBot.blockAt(target);
                if (!isSolidBlock(block)) continue;
                if (block.name !== material) {
                    issues.push(`rollback target changed to ${block.name} at ${blockPositionKey(position)}`);
                    continue;
                }
                if (typeof activeBot.dig !== 'function') {
                    issues.push(`dig unavailable for rollback at ${blockPositionKey(position)}`);
                    continue;
                }
                try {
                    await activeBot.dig(block, true);
                    await wait(50);
                    if (isSolidBlock(activeBot.blockAt(target))) {
                        issues.push(`rollback block remained at ${blockPositionKey(position)}`);
                    } else {
                        removed.push(compactPosition(position));
                    }
                } catch (error) {
                    issues.push(`rollback failed at ${blockPositionKey(position)}: ${error.message}`);
                }
            }
            let inventoryAfter = inventoryCounts(activeBot);
            const expectedCount = Number(beforeInventory[material] || 0);
            let waitedMs = 0;
            while (Number(inventoryAfter[material] || 0) < expectedCount && waitedMs < 2000) {
                await wait(100);
                waitedMs += 100;
                inventoryAfter = inventoryCounts(activeBot);
            }
            const inventoryRecovered = Number(inventoryAfter[material] || 0) >= expectedCount;
            if (!inventoryRecovered) {
                issues.push(
                    `rollback inventory recovered ${Number(inventoryAfter[material] || 0)}/${expectedCount} ${material}`,
                );
            }
            const residualPositions = unique.filter(position => {
                const block = activeBot.blockAt(new Vec3(position.x, position.y, position.z));
                return isSolidBlock(block) && block.name === material;
            });
            return {
                passed: issues.length === 0 && residualPositions.length === 0,
                attempted_positions: unique,
                removed_positions: removed,
                residual_positions: residualPositions,
                inventory_recovered: inventoryRecovered,
                inventory_before: beforeInventory,
                inventory_after: inventoryAfter,
                waited_ms: waitedMs,
                issues,
            };
        };
        const failWithRollback = async failure => {
            const originalPlacedCount = placedPositions.length + (temporaryScaffold ? 1 : 0);
            const rollback = await rollbackPlacements();
            const relocation = rollback.passed ? findSealedCellRelocation(activeBot, origin) : null;
            return {
                success: false,
                template_id: 'm4-sealed-cell-v1',
                material,
                origin: compactPosition(origin),
                ...failure,
                placed_count: 0,
                placed_positions: [],
                placement_deltas: [],
                cleared_original_positions: removedPositions,
                temporary_scaffold: null,
                inventory_before: beforeInventory,
                inventory_after: rollback.inventory_after,
                preflight,
                atomicity: {
                    passed: rollback.passed,
                    mode: 'rollback_after_partial_mutation',
                    scope: 'final_placements_and_material_inventory',
                    original_placed_count: originalPlacedCount,
                    residual_placed_count: rollback.residual_positions.length,
                    inventory_preserved: rollback.inventory_recovered,
                },
                rollback,
                relocation_required: Boolean(relocation),
                relocation_origin: relocation?.origin || null,
                relocation_target: relocation?.target || null,
                relocation_search_radius: relocation?.search_radius || 6,
            };
        };
        for (const target of targets) {
            let existing = activeBot.blockAt(target);
            if (existing && existing.type !== 0 && existing.name !== 'air') {
                if (typeof activeBot.dig !== 'function') {
                    return failWithRollback({
                        error: `sealed-cell target is occupied by ${existing.name}`,
                        failed_position: compactPosition(target),
                    });
                }
                try {
                    await activeBot.dig(existing, true);
                    await wait(50);
                } catch (error) {
                    return failWithRollback({
                        error: `could not clear sealed-cell target: ${error.message}`,
                        failed_position: compactPosition(target),
                    });
                }
                const cleared = activeBot.blockAt(target);
                if (cleared && cleared.type !== 0 && cleared.name !== 'air') {
                    return failWithRollback({
                        error: `sealed-cell target remained occupied by ${cleared.name}`,
                        failed_position: compactPosition(target),
                    });
                }
                removedPositions.push(compactPosition(target));
                existing = cleared;
            }
            const before = shelterBlockState(activeBot, target);
            let reference = placementReference(activeBot, target);
            if (!reference && target.equals(origin.offset(0, 2, 0))) {
                const scaffoldTarget = origin.offset(1, 2, 0);
                const scaffoldBefore = activeBot.blockAt(scaffoldTarget);
                if (scaffoldBefore && scaffoldBefore.type !== 0 && scaffoldBefore.name !== 'air') {
                    return failWithRollback({
                        error: `temporary scaffold target is occupied by ${scaffoldBefore.name}`,
                        failed_position: compactPosition(scaffoldTarget),
                    });
                }
                const scaffoldReference = placementReference(activeBot, scaffoldTarget);
                if (!scaffoldReference) {
                    return failWithRollback({
                        error: 'no grounded neighbor exists for temporary roof scaffold',
                        failed_position: compactPosition(scaffoldTarget),
                    });
                }
                try {
                    await activeBot.placeBlock(scaffoldReference.block, scaffoldReference.face);
                } catch (error) {
                    if (activeBot.blockAt(scaffoldTarget)?.name === material) {
                        temporaryScaffold = compactPosition(scaffoldTarget);
                    }
                    return failWithRollback({
                        error: `temporary roof scaffold placement failed: ${error.message}`,
                        failed_position: compactPosition(scaffoldTarget),
                    });
                }
                temporaryScaffold = compactPosition(scaffoldTarget);
                await wait(50);
                const scaffoldAfter = activeBot.blockAt(scaffoldTarget);
                if (scaffoldAfter?.name !== material) {
                    return failWithRollback({
                        error: 'temporary roof scaffold was not observed',
                        failed_position: compactPosition(scaffoldTarget),
                    });
                }
                reference = placementReference(activeBot, target);
            }
            if (!reference) {
                return failWithRollback({
                    error: 'no grounded neighbor exists for sealed-cell placement',
                    failed_position: compactPosition(target),
                });
            }
            try {
                await activeBot.placeBlock(reference.block, reference.face);
                await wait(50);
            } catch (error) {
                if (activeBot.blockAt(target)?.name === material) {
                    placedPositions.push(compactPosition(target));
                }
                return failWithRollback({
                    error: `sealed-cell placement failed: ${error.message}`,
                    failed_position: compactPosition(target),
                });
            }
            const after = shelterBlockState(activeBot, target);
            if (after.name !== material) {
                return failWithRollback({
                    error: 'placed sealed-cell block was not observed at the target',
                    failed_position: compactPosition(target),
                    observed_block: after.name,
                });
            }
            placedPositions.push(compactPosition(target));
            placementDeltas.push({
                target_block_before: before,
                target_block_after: after,
            });
        }
        if (temporaryScaffold) {
            const scaffoldPosition = new Vec3(
                temporaryScaffold.x,
                temporaryScaffold.y,
                temporaryScaffold.z,
            );
            const scaffoldBlock = activeBot.blockAt(scaffoldPosition);
            try {
                await activeBot.dig(scaffoldBlock, true);
                await wait(50);
            } catch (error) {
                return failWithRollback({
                    error: `could not remove temporary roof scaffold: ${error.message}`,
                    failed_position: temporaryScaffold,
                });
            }
            removedPositions.push(temporaryScaffold);
        }
        return {
            success: true,
            template_id: 'm4-sealed-cell-v1',
            material,
            origin: compactPosition(origin),
            required_block_count: requiredCount,
            required_inventory_count: requiredInventoryCount,
            placed_count: placedPositions.length,
            placed_positions: placedPositions,
            removed_positions: removedPositions,
            placement_deltas: placementDeltas,
            temporary_scaffold: temporaryScaffold,
            inventory_before: beforeInventory,
            inventory_after: inventoryCounts(activeBot),
            player_position: compactPosition(activeBot.entity.position),
            preflight,
            atomicity: {
                passed: true,
                mode: 'committed_complete_template',
                scope: 'final_placements_and_material_inventory',
                committed: true,
                original_placed_count: placedPositions.length + (temporaryScaffold ? 1 : 0),
                residual_placed_count: placedPositions.length,
                inventory_preserved: null,
            },
        };
    };
}

async function moveWithinPlacementRange(activeBot, target, timeoutMs = 15000) {
    const currentDistance = navigationDistance(activeBot.entity.position, target, true);
    if (currentDistance !== null && currentDistance <= 4.25) return { moved: false, reached: true };
    if (!activeBot.pathfinder || typeof activeBot.pathfinder.goto !== 'function') {
        return { moved: false, reached: false, error: 'pathfinder is unavailable' };
    }
    let timer = null;
    try {
        const navigation = Promise.resolve(activeBot.pathfinder.goto(
            new goals.GoalNearXZ(Math.floor(target.x), Math.floor(target.z), 2),
        ));
        const timeout = new Promise((_, reject) => {
            timer = setTimeout(() => reject(new Error(`placement navigation timed out after ${timeoutMs}ms`)), timeoutMs);
        });
        await Promise.race([navigation, timeout]);
        const distance = navigationDistance(activeBot.entity.position, target, true);
        return { moved: true, reached: distance !== null && distance <= 4.5, distance };
    } catch (error) {
        if (typeof activeBot.pathfinder.stop === 'function') activeBot.pathfinder.stop();
        return { moved: true, reached: false, error: error.message };
    } finally {
        if (timer) clearTimeout(timer);
    }
}

function createBuildShelterHandler(
    getState = () => ({ bot, botReady }),
    wait = ms => new Promise(resolve => setTimeout(resolve, ms)),
) {
    return async (params = {}) => {
        const state = getState() || {};
        const activeBot = state.bot;
        if (!state.botReady || !activeBot?.entity?.position) {
            return { success: false, error: 'bot is not ready to build a shelter' };
        }
        const taskSpec = M2_PROTOCOL.tasks.find(task => task.id === 'BM-010');
        const expectedOrigin = relativeWorldPosition(
            activeBot.spawnPoint,
            taskSpec.fixture.construction_zone.origin_relative,
        );
        const requestedOrigin = params.origin && typeof params.origin === 'object'
            ? params.origin
            : { x: params.x, y: params.y, z: params.z };
        if (![requestedOrigin.x, requestedOrigin.y, requestedOrigin.z].every(Number.isFinite)) {
            return { success: false, error: 'build_shelter_5x5 requires a finite origin' };
        }
        const origin = new Vec3(
            Math.floor(requestedOrigin.x),
            Math.floor(requestedOrigin.y),
            Math.floor(requestedOrigin.z),
        );
        if (!origin.equals(expectedOrigin)) {
            return {
                success: false,
                error: 'requested shelter origin does not match the fixed M2 construction zone',
                requested_origin: compactPosition(origin),
                expected_origin: compactPosition(expectedOrigin),
            };
        }
        const allowed = new Set(M2_PROTOCOL.validation_contract.shelter.allowed_structure_blocks || []);
        const material = String(params.material || '');
        if (!allowed.has(material)) {
            return { success: false, error: `shelter material ${material || '<missing>'} is not allowlisted` };
        }
        const template = shelterTemplatePositions(origin);
        const requiredCount = template.positions.length;
        const beforeInventory = inventoryCounts(activeBot);
        if (Number(beforeInventory[material] || 0) < requiredCount) {
            return {
                success: false,
                error: `shelter template requires ${requiredCount} ${material}`,
                required_count: requiredCount,
                available_count: Number(beforeInventory[material] || 0),
            };
        }
        const item = activeBot.inventory.items().find(entry => entry.name === material);
        if (!item) return { success: false, error: `${material} is not available for placement` };
        try {
            await activeBot.equip(item, 'hand');
        } catch (error) {
            return { success: false, error: `could not equip ${material}: ${error.message}` };
        }

        const placedPositions = [];
        const alreadyPresent = [];
        for (const target of template.positions) {
            const existing = activeBot.blockAt(target);
            if (existing?.name === material) {
                alreadyPresent.push(compactPosition(target));
                continue;
            }
            if (existing && existing.type !== 0 && existing.name !== 'air') {
                return {
                    success: false,
                    error: `construction target is occupied by ${existing.name}`,
                    failed_position: compactPosition(target),
                    placed_count: placedPositions.length,
                };
            }
            const navigation = await moveWithinPlacementRange(activeBot, target);
            if (!navigation.reached) {
                return {
                    success: false,
                    error: navigation.error || 'could not reach shelter placement range',
                    failed_position: compactPosition(target),
                    placed_count: placedPositions.length,
                };
            }
            const reference = placementReference(activeBot, target);
            if (!reference) {
                return {
                    success: false,
                    error: 'no grounded neighbor exists for shelter placement',
                    failed_position: compactPosition(target),
                    placed_count: placedPositions.length,
                };
            }
            try {
                await activeBot.placeBlock(reference.block, reference.face);
                await wait(100);
            } catch (error) {
                return {
                    success: false,
                    error: `shelter placement failed: ${error.message}`,
                    failed_position: compactPosition(target),
                    placed_count: placedPositions.length,
                };
            }
            const observed = activeBot.blockAt(target);
            if (observed?.name !== material) {
                return {
                    success: false,
                    error: 'placed shelter block was not observed at the target',
                    failed_position: compactPosition(target),
                    observed_block: String(observed?.name || 'air'),
                    placed_count: placedPositions.length,
                };
            }
            placedPositions.push(compactPosition(target));
        }

        const center = origin.offset(2, 0, 2);
        if (activeBot.pathfinder && typeof activeBot.pathfinder.goto === 'function') {
            try {
                await activeBot.pathfinder.goto(new goals.GoalNear(center.x, center.y, center.z, 1));
            } catch (error) {
                return {
                    success: false,
                    error: `shelter built but player could not enter: ${error.message}`,
                    placed_count: placedPositions.length,
                };
            }
        }
        const afterInventory = inventoryCounts(activeBot);
        return {
            success: true,
            template_id: 'shelter-outer-5x5-v1',
            material,
            origin: compactPosition(origin),
            required_block_count: requiredCount,
            wall_block_count: template.wall_count,
            roof_block_count: template.roof_count,
            placed_count: placedPositions.length,
            already_present_count: alreadyPresent.length,
            placed_positions: placedPositions,
            entrance: template.entrance,
            inventory_before: beforeInventory,
            inventory_after: afterInventory,
            player_position: compactPosition(activeBot.entity.position),
            structure_post: constructionSnapshot(activeBot, activeBot.spawnPoint, taskSpec),
        };
    };
}

async function waitForStableCraftOutput(
    activeBot,
    inventoryBefore,
    itemName,
    minimumIncrease,
    wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    maxWaitMs = 2500,
    stableWindowMs = 750,
) {
    const pollMs = 100;
    let observedSince = null;
    let latestInventory = inventoryCounts(activeBot);
    for (let elapsed = 0; elapsed <= maxWaitMs; elapsed += pollMs) {
        latestInventory = inventoryCounts(activeBot);
        const increase = Number(latestInventory[itemName] || 0) - Number(inventoryBefore[itemName] || 0);
        if (increase >= minimumIncrease) {
            if (observedSince == null) observedSince = elapsed;
            if (elapsed - observedSince >= stableWindowMs) {
                return {
                    observed: true,
                    inventory: latestInventory,
                    delta: positiveInventoryDelta(inventoryBefore, latestInventory),
                    waited_ms: elapsed,
                    stable_ms: elapsed - observedSince,
                };
            }
        } else {
            observedSince = null;
        }
        if (elapsed < maxWaitMs) await wait(pollMs);
    }
    return {
        observed: false,
        inventory: latestInventory,
        delta: positiveInventoryDelta(inventoryBefore, latestInventory),
        waited_ms: maxWaitMs,
        stable_ms: 0,
    };
}

async function refreshCraftingTableInventory(
    activeBot,
    craftingTable,
    wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    timeoutMs = 1500,
    postCloseWaitMs = 100,
) {
    const inventoryBefore = inventoryCounts(activeBot);
    const base = {
        policy_id: CRAFT_INVENTORY_REFRESH_POLICY_ID,
        attempted: false,
        success: false,
        authoritative: false,
        source: 'crafting_table_window_items',
        timeout_ms: timeoutMs,
        post_close_wait_ms: postCloseWaitMs,
        crafting_table_position: compactPosition(craftingTable?.position),
        inventory_before: inventoryBefore,
    };
    if (!craftingTable) {
        return { ...base, error: 'crafting_table_unavailable' };
    }
    if (typeof activeBot?.openBlock !== 'function' || typeof activeBot?.closeWindow !== 'function') {
        return { ...base, error: 'window_refresh_api_unavailable' };
    }

    let timeoutHandle = null;
    let timedOut = false;
    const openPromise = Promise.resolve().then(() => activeBot.openBlock(craftingTable));
    const timeoutPromise = new Promise((resolve) => {
        timeoutHandle = setTimeout(() => {
            timedOut = true;
            resolve({ timeout: true });
        }, timeoutMs);
    });
    try {
        const outcome = await Promise.race([
            openPromise.then((window) => ({ window })),
            timeoutPromise,
        ]);
        if (outcome?.timeout) {
            openPromise.then((window) => {
                try {
                    if (window) activeBot.closeWindow(window);
                } catch (_) {
                    // A late authoritative window is closed best-effort after the bounded timeout.
                }
            }).catch(() => {});
            return { ...base, attempted: true, error: 'window_items_timeout' };
        }
        if (timeoutHandle) clearTimeout(timeoutHandle);
        const window = outcome?.window;
        if (!window) {
            return { ...base, attempted: true, error: 'window_open_missing' };
        }
        activeBot.closeWindow(window);
        if (postCloseWaitMs > 0) await wait(postCloseWaitMs);
        const inventoryAfter = inventoryCounts(activeBot);
        return {
            ...base,
            attempted: true,
            success: true,
            authoritative: true,
            window_items_observed: true,
            window_id: Number.isFinite(Number(window.id)) ? Number(window.id) : null,
            window_type: String(window.type || ''),
            inventory_after: inventoryAfter,
            inventory_signed_delta: signedInventoryDelta(inventoryBefore, inventoryAfter),
        };
    } catch (error) {
        if (timeoutHandle) clearTimeout(timeoutHandle);
        return {
            ...base,
            attempted: true,
            error: String(error?.message || error || 'window_refresh_failed'),
        };
    } finally {
        if (!timedOut && timeoutHandle) clearTimeout(timeoutHandle);
    }
}

function createCraftHandler(
    getState = () => ({ bot, botReady }),
    wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    options = {},
) {
    const requestedMaxAttempts = Number(options.maxAttempts ?? 3);
    const maxAttempts = Number.isFinite(requestedMaxAttempts)
        ? Math.max(1, Math.min(3, requestedMaxAttempts))
        : 3;
    const retryCooldownMs = Math.max(0, Number(options.retryCooldownMs ?? 3000) || 0);
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
            const inventoryBefore = inventoryCounts(activeBot);
            const attempts = [];
            for (let attempt = 1; attempt <= maxAttempts; attempt++) {
                const recipes = activeBot.recipesFor(item.id, null, count, craftingTable);
                if (!recipes || recipes.length === 0) {
                    attempts.push({
                        attempt,
                        success: false,
                        error: `No recipe for ${itemName}`,
                        inventory: inventoryCounts(activeBot),
                    });
                    break;
                }
                const recipe = recipes[0];
                const outputPerCraft = Math.max(1, Number(recipe?.result?.count || 1));
                const craftCalls = Math.max(1, Math.ceil(count / outputPerCraft));
                await activeBot.craft(recipe, craftCalls, craftingTable);
                const authoritativeInventoryRefresh = await refreshCraftingTableInventory(
                    activeBot,
                    craftingTable,
                    wait,
                );
                const settlement = await waitForStableCraftOutput(
                    activeBot,
                    inventoryBefore,
                    itemName,
                    count,
                    wait,
                );
                attempts.push({
                    attempt,
                    success: settlement.observed,
                    output_per_craft: outputPerCraft,
                    craft_calls: craftCalls,
                    settlement_waited_ms: settlement.waited_ms,
                    stable_ms: settlement.stable_ms,
                    inventory: settlement.inventory,
                    inventory_delta: settlement.delta,
                    inventory_signed_delta: signedInventoryDelta(
                        inventoryBefore,
                        settlement.inventory,
                    ),
                    authoritative_inventory_refresh: authoritativeInventoryRefresh,
                });
                if (settlement.observed) {
                    return {
                        success: true,
                        item: itemName,
                        count,
                        requested_output_count: count,
                        output_per_craft: outputPerCraft,
                        craft_calls: craftCalls,
                        craft_attempts: attempt,
                        craft_retry_count: attempt - 1,
                        settlement_waited_ms: settlement.waited_ms,
                        stable_ms: settlement.stable_ms,
                        inventory_before: inventoryBefore,
                        inventory_after: settlement.inventory,
                        inventory_delta: settlement.delta,
                        inventory_signed_delta: signedInventoryDelta(
                            inventoryBefore,
                            settlement.inventory,
                        ),
                        authoritative_inventory_refresh: authoritativeInventoryRefresh,
                        attempts,
                        crafting_table_found: Boolean(craftingTable),
                        crafting_table_position: compactPosition(craftingTable?.position),
                    };
                }
                if (attempt < maxAttempts) {
                    attempts[attempts.length - 1].retry_cooldown_ms = retryCooldownMs;
                    await wait(retryCooldownMs);
                }
            }
            const finalInventory = inventoryCounts(activeBot);
            return {
                success: false,
                error: `Crafted ${itemName} output did not remain stable after ${maxAttempts} attempts`,
                item: itemName,
                requested_output_count: count,
                craft_attempts: attempts.length,
                craft_retry_count: Math.max(0, attempts.length - 1),
                inventory_before: inventoryBefore,
                inventory_after: finalInventory,
                inventory_signed_delta: signedInventoryDelta(
                    inventoryBefore,
                    finalInventory,
                ),
                attempts,
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
    options = {},
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
            const strictPickupPostcondition = params.require_pickup === true;
            const strictToolEquip = params.require_tool_equip === true;
            const targetBlockBefore = {
                name: blockName,
                type: Number(block.type),
                position: compactPosition(target),
            };
            const failBeforeDig = (error, digToolEquip) => {
                const result = {
                    success: false,
                    error,
                    block: blockName,
                    expected_drops: expectedDrops,
                    target: compactPosition(target),
                    block_removed: false,
                    target_block_before: targetBlockBefore,
                    target_block_after: { ...targetBlockBefore },
                    pickup_observed: false,
                    pickup_inventory_delta: {},
                    pickup_waited_ms: 0,
                    pickup_collection: { detected: false, attempted: false },
                    dig_tool_equip: digToolEquip,
                };
                if (strictPickupPostcondition) {
                    result.dig_postcondition = {
                        schema_version: 1,
                        policy: 'm4-expected-drop-pickup-postcondition-v1',
                        required: true,
                        block_removed: false,
                        expected_drop_required: expectedDrops.length > 0,
                        expected_drop_observed: false,
                        passed: false,
                    };
                }
                return result;
            };
            let digToolEquip;
            if (strictToolEquip) {
                const harvestToolTypes = blockHarvestToolTypes(block);
                if (harvestToolTypes === null) {
                    digToolEquip = {
                        schema_version: 1,
                        policy: M4_DIG_REQUIRED_TOOL_EQUIP_POLICY_ID,
                        required: true,
                        block: blockName,
                        metadata_valid: false,
                        harvest_tool_item_types: [],
                        compatible_inventory_tools: [],
                        selected_tool: null,
                        selected_tool_type: null,
                        equip_attempted: false,
                        equip_confirmed: false,
                        mutation_allowed: false,
                        passed: false,
                    };
                    return failBeforeDig(`harvest tool metadata is invalid for ${blockName}`, digToolEquip);
                }
                const toolRequired = harvestToolTypes.length > 0;
                digToolEquip = {
                    schema_version: 1,
                    policy: M4_DIG_REQUIRED_TOOL_EQUIP_POLICY_ID,
                    required: toolRequired,
                    block: blockName,
                    metadata_valid: true,
                    harvest_tool_item_types: harvestToolTypes,
                    compatible_inventory_tools: [],
                    selected_tool: null,
                    selected_tool_type: null,
                    equipped_tool: null,
                    equipped_tool_type: null,
                    equip_attempted: false,
                    equip_confirmed: null,
                    mutation_allowed: !toolRequired,
                    passed: !toolRequired,
                };
                if (toolRequired) {
                    const compatibleTools = compatibleHarvestTools(activeBot, block, harvestToolTypes);
                    digToolEquip.compatible_inventory_tools = compatibleTools.map(item => ({
                        name: String(item.name || ''),
                        type: Number(item.type),
                        count: Number(item.count || 0),
                    }));
                    const selectedTool = compatibleTools[0] || null;
                    if (!selectedTool) {
                        digToolEquip.equip_confirmed = false;
                        return failBeforeDig(
                            `no compatible harvest tool available for ${blockName}`,
                            digToolEquip,
                        );
                    }
                    digToolEquip.selected_tool = String(selectedTool.name || '');
                    digToolEquip.selected_tool_type = Number(selectedTool.type);
                    digToolEquip.equip_attempted = true;
                    try {
                        await activeBot.equip(selectedTool, 'hand');
                    } catch (error) {
                        digToolEquip.equip_confirmed = false;
                        return failBeforeDig(
                            `could not equip required harvest tool ${digToolEquip.selected_tool}: ${error.message}`,
                            digToolEquip,
                        );
                    }
                    const heldItem = heldItemForConfirmation(activeBot);
                    digToolEquip.equipped_tool = String(heldItem?.name || '');
                    digToolEquip.equipped_tool_type = Number.isInteger(Number(heldItem?.type))
                        ? Number(heldItem.type)
                        : null;
                    const exactToolConfirmed = (
                        digToolEquip.equipped_tool === digToolEquip.selected_tool
                        && digToolEquip.equipped_tool_type === digToolEquip.selected_tool_type
                        && itemCanHarvestBlock(block, heldItem, harvestToolTypes)
                    );
                    digToolEquip.equip_confirmed = exactToolConfirmed;
                    digToolEquip.mutation_allowed = exactToolConfirmed;
                    digToolEquip.passed = exactToolConfirmed;
                    if (!exactToolConfirmed) {
                        return failBeforeDig(
                            `required harvest tool ${digToolEquip.selected_tool} was not equipped`,
                            digToolEquip,
                        );
                    }
                }
            }
            await activeBot.dig(block);
            let pickup = await waitForInventoryIncrease(activeBot, beforeInventory, wait, 1000, expectedDrops);
            let pickupCollection = { detected: false, attempted: false };
            if (!pickup.observed) {
                pickupCollection = await approachDroppedItem(
                    activeBot,
                    target,
                    expectedDrops,
                    wait,
                    strictPickupPostcondition ? 1500 : 0,
                    strictPickupPostcondition ? 1 : 0,
                    6000,
                    {
                        completionGrounding: strictPickupPostcondition,
                        beforeInventory,
                        monotonicMs: options.monotonicMs,
                    },
                );
                const collected = await waitForInventoryIncrease(activeBot, beforeInventory, wait, 1500, expectedDrops);
                pickup = {
                    ...collected,
                    waited_ms: pickup.waited_ms + collected.waited_ms,
                };
            }
            const blockAfter = activeBot.blockAt(target);
            const blockRemoved = !blockAfter || blockAfter.type === 0 || blockAfter.name !== blockName;
            const pickupRequired = strictPickupPostcondition && expectedDrops.length > 0;
            const success = strictPickupPostcondition
                ? blockRemoved && (!pickupRequired || pickup.observed)
                : true;
            const result = {
                success,
                block: blockName,
                expected_drops: expectedDrops,
                target: compactPosition(target),
                block_removed: blockRemoved,
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
            if (digToolEquip) result.dig_tool_equip = digToolEquip;
            if (strictPickupPostcondition) {
                result.dig_postcondition = {
                    schema_version: 1,
                    policy: 'm4-expected-drop-pickup-postcondition-v1',
                    required: true,
                    block_removed: blockRemoved,
                    expected_drop_required: pickupRequired,
                    expected_drop_observed: pickup.observed,
                    passed: success,
                };
                if (!blockRemoved) {
                    result.error = 'dug block is still present';
                } else if (pickupRequired && !pickup.observed) {
                    result.error = 'expected block drop was not acquired';
                }
            }
            return result;
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

    m4PlayerLifecycleTracker.attach(bot);
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
        craft_policy: {
            max_attempts: CRAFT_MAX_ATTEMPTS,
            automatic_retry: CRAFT_MAX_ATTEMPTS > 1,
        },
        screenshot_capture_supported: Boolean(findScreenshotCapture(bot)),
        screenshot_plugin: publicScreenshotPluginStatus(screenshotPluginStatus),
    }),

    get_player_state: () => {
        const state = {
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
        };
        const lifecycle = m4PlayerLifecycleTracker.snapshot();
        if (lifecycle.baseline_established === true) {
            state.playerLifecycle = lifecycle;
        }
        return state;
    },

    get_inventory: () => ({
        items: bot.inventory.items().map(i => ({
            name: i.name,
            displayName: i.displayName,
            count: i.count,
            slot: i.slot,
            metadata: i.metadata,
        })),
    }),

    get_player_lifecycle: () => m4PlayerLifecycleTracker.snapshot(),

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
                    hostile: isHostileEntity(entity),
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
        return { blocks: prioritizeNearbyBlocks(blocks, 50) };
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

    get_shelter_state: createShelterStateHandler(),

    capture_screenshot: createCaptureScreenshotHandler(),
    benchmark_protocol: createBenchmarkProtocolHandler(),
    benchmark_reset: createBenchmarkResetHandler(),
    benchmark_verify: createBenchmarkVerifyHandler(),
    build_shelter_5x5: createBuildShelterHandler(),
    build_shelter_cell: createBuildShelterCellHandler(),

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

    recover_navigation: createRecoverNavigationHandler(),

    look_at: async (params) => {
        try {
            await bot.lookAt(new Vec3(params.x, params.y, params.z));
            return { success: true };
        } catch (e) {
            return { success: false, error: e.message };
        }
    },

    dig: createDigHandler(),

    place: createPlaceHandler(),

    craft: createCraftHandler(
        () => ({ bot, botReady }),
        (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
        { maxAttempts: CRAFT_MAX_ATTEMPTS },
    ),

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
    CRAFT_INVENTORY_REFRESH_POLICY_ID,
    M1_PROTOCOL,
    M1_PROTOCOL_SHA256,
    M2_PROTOCOL,
    M2_PROTOCOL_SHA256,
    M4_PROTOCOL,
    M4_PROTOCOL_SHA256,
    M4_BM012_PROTOCOL,
    M4_BM012_PROTOCOL_SHA256,
    attachScreenshotPlugin,
    benchmarkBotState,
    benchmarkProtocolBundle,
    benchmarkProtocolStatus,
    benchmarkResetChecks,
    benchmarkTaskBundle,
    m4TaskContract,
    constructionSnapshot,
    createBridgeServer,
    createM4PlayerLifecycleTracker,
    createBenchmarkProtocolHandler,
    createBenchmarkResetHandler,
    createBenchmarkVerifyHandler,
    createBuildShelterHandler,
    createBuildShelterCellHandler,
    createCraftHandler,
    createDigHandler,
    createPlaceHandler,
    createShelterStateHandler,
    createCaptureScreenshotHandler,
    createMoveToHandler,
    createRecoverNavigationHandler,
    createWalkToHandler,
    fileStatusForScreenshot,
    imageBytesFromCaptureResult,
    navigationDistance,
    navigationTimeoutMs,
    resetM4PathfinderState,
    prioritizeNearbyBlocks,
    prioritizeTreeResults,
    positiveInventoryDelta,
    publicScreenshotPluginStatus,
    resolveScreenshotPluginSpec,
    screenshotPathFromCaptureResult,
    shelterBlockState,
    sealedCellTemplatePositions,
    shelterTemplatePositions,
    startBridge,
};
