/**
 * Mineflayer Bot Bridge Server
 * 
 * Runs a persistent TCP socket server that the Python agent connects to.
 * Handles commands from the agent and returns bot state.
 * 
 * Usage: node bot_server.js [--host localhost] [--port 25565] [--bridge-port 3000]
 */

const { Vec3 } = require('vec3');
const mineflayer = require('mineflayer');
const net = require('net');
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
const BRIDGE_PORT = parseInt(getArg('bridge-port', '3000'));

let bot = null;

function createBot() {
    bot = mineflayer.createBot({
        host: MC_HOST,
        port: MC_PORT,
        username: MC_USERNAME,
        version: MC_VERSION,
    });

    bot.loadPlugin(pathfinder);

    bot.on('spawn', () => {
        console.log(`[Bot] Spawned in world at ${bot.entity.position}`);
        const mcData = require('minecraft-data')(bot.version);
        const defaultMove = new Movements(bot, mcData);
        defaultMove.canOpenDoors = true;
        defaultMove.allowParkour = true;
        defaultMove.allowSprinting = true;
        defaultMove.blocksToAvoid.delete(mcData.blocksByName.leaves?.id);
        defaultMove.blocksToAvoid.delete(mcData.blocksByName.oak_leaves?.id);
        bot.pathfinder.setMovements(defaultMove);
    });

    bot.on('error', (err) => console.error('[Bot] Error:', err.message));
    bot.on('kicked', (reason) => console.warn('[Bot] Kicked:', reason));
    bot.on('end', () => console.log('[Bot] Disconnected'));
}

// Command handlers
const handlers = {
    get_player_state: () => ({
        position: bot.entity.position,
        health: bot.health,
        food: bot.food,
        experience: bot.experience,
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
        move_to: async (params) => {
        const MOVE_TIMEOUT = 2000;
        try {
            const goal = new goals.GoalNear(params.x, params.y || bot.entity.position.y, params.z, 1);
            const result = await Promise.race([
                bot.pathfinder.goto(goal).then(() => ({ ok: true })),
                new Promise((_, rej) => setTimeout(() => rej(new Error('Pathfinding timeout')), MOVE_TIMEOUT))
            ]);
            return { success: true, position: bot.entity.position };
        } catch (e) {
            bot.pathfinder.stop();
            return { success: false, error: e.message };
        }
    },

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

// TCP Bridge Server
const server = net.createServer((socket) => {
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

// Start
createBot();
server.listen(BRIDGE_PORT, '127.0.0.1', () => {
    console.log(`[Bridge] Listening on 127.0.0.1:${BRIDGE_PORT}`);
    console.log(`[Bridge] Connecting to MC server ${MC_HOST}:${MC_PORT} as ${MC_USERNAME}`);
});




