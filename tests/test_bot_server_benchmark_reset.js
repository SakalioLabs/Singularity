'use strict';

const assert = require('assert');
const { Vec3 } = require('vec3');
const {
    M1_PROTOCOL,
    M1_PROTOCOL_SHA256,
    benchmarkProtocolStatus,
    createBenchmarkResetHandler,
    createCraftHandler,
    createDigHandler,
} = require('../src/bot/bot_server');

const runtime = {
    seed: '12345',
    episode_id: 'offline-test-episode',
    level_name: 'offline-test-episode_bm003',
    server_jar_sha256: M1_PROTOCOL.server_jar_sha256,
};

function createResetBot(applyCommands = true) {
    const spawnPoint = new Vec3(10, 64, 10);
    let items = [{ name: 'dirt', count: 7 }];
    let fixtureBlock = 'dirt';
    const commands = [];
    const bot = {
        spawnPoint,
        entity: { position: new Vec3(25, 70, -4) },
        health: 8,
        food: 6,
        version: '1.20.4',
        game: {
            gameMode: 'creative',
            difficulty: 'hard',
            dimension: 'overworld',
            serverBrand: 'Paper',
        },
        time: { timeOfDay: 14000 },
        thunderState: 0,
        rainState: 1,
        inventory: { items: () => items },
        blockAt(position) {
            if (position.x === 11 && position.y === 64 && position.z === 10) {
                return { name: fixtureBlock, position };
            }
            return { name: 'air', position };
        },
        chat(command) {
            commands.push(command);
            if (!applyCommands) return;
            if (command.startsWith('/execute in minecraft:overworld run tp')) {
                bot.entity.position = spawnPoint.clone();
            } else if (command.startsWith('/gamemode ')) {
                bot.game.gameMode = 'survival';
            } else if (command === '/clear @s') {
                items = [];
            } else if (command.startsWith('/setblock ')) {
                fixtureBlock = command.endsWith('minecraft:crafting_table') ? 'crafting_table' : 'air';
            } else if (command.startsWith('/time set ')) {
                bot.time.timeOfDay = 1000;
            } else if (command.startsWith('/weather ')) {
                bot.rainState = 0;
                bot.thunderState = 0;
            } else if (command.startsWith('/difficulty ')) {
                bot.game.difficulty = 'peaceful';
            } else if (command.includes('instant_health')) {
                bot.health = 20;
            } else if (command.includes('saturation')) {
                bot.food = 20;
            } else if (command.startsWith('/give ')) {
                const match = command.match(/minecraft:([a-z0-9_]+)\s+(\d+)$/);
                if (match) items.push({ name: match[1], count: Number(match[2]) });
            }
        },
    };
    return { bot, commands };
}

async function testProtocolStatusPinsRuntimeAndDependencies() {
    const { bot } = createResetBot();
    const status = benchmarkProtocolStatus(bot, runtime);
    assert.strictEqual(status.success, true);
    assert.strictEqual(status.configured, true);
    assert.strictEqual(status.profile, 'm1-fixed-v1');
    assert.strictEqual(status.server_build, 'paper-1.20.4-499');
    assert.strictEqual(status.protocol_sha256, M1_PROTOCOL_SHA256);
    assert.strictEqual(status.tasks.length, 5);
    assert.strictEqual(status.tasks[3].success_criteria.cobblestone, 5);
    console.log('PASS: M1 bridge protocol pins runtime, dependencies, and canonical tasks');
}

async function testBenchmarkResetVerifiesObservedPostconditions() {
    const { bot, commands } = createResetBot();
    const handler = createBenchmarkResetHandler(
        () => ({ bot, botReady: true }),
        async () => {},
        runtime,
    );
    const result = await handler({ task_id: 'BM-003' });

    assert.strictEqual(result.success, true);
    assert.strictEqual(result.protocol_sha256, M1_PROTOCOL_SHA256);
    assert.strictEqual(result.server_jar_sha256, runtime.server_jar_sha256);
    assert.deepStrictEqual(result.after_state.inventory, { oak_planks: 3, stick: 2 });
    assert.strictEqual(result.after_state.fixture.block, 'crafting_table');
    assert.strictEqual(result.checks.inventory_exact, true);
    assert.strictEqual(result.checks.position_at_spawn, true);
    assert.strictEqual(result.checks.time_initialized, true);
    assert.strictEqual(result.checks.health, true);
    assert.strictEqual(result.checks.food, true);
    assert(commands.some((command) => command.includes('minecraft:crafting_table')));

    const unsupported = await handler({ task_id: 'BM-999' });
    assert.strictEqual(unsupported.success, false);
    assert.match(unsupported.error, /unsupported M1 benchmark task/);
    console.log('PASS: M1 reset proves inventory, fixture, spawn, time, weather, and player state');
}

async function testBenchmarkResetRejectsUnappliedServerCommands() {
    const { bot } = createResetBot(false);
    const handler = createBenchmarkResetHandler(
        () => ({ bot, botReady: true }),
        async () => {},
        runtime,
    );
    const result = await handler({ task_id: 'BM-002' });

    assert.strictEqual(result.success, false);
    assert(result.failed_checks.includes('inventory_exact'));
    assert(result.failed_checks.includes('position_at_spawn'));
    assert.match(result.error, /server operator/);
    console.log('PASS: M1 reset rejects chat commands that did not change observed world state');
}

async function testCraftHandlerUsesGroundedNearbyTable() {
    const table = { name: 'crafting_table', position: new Vec3(11, 64, 10) };
    const calls = {};
    const bot = {
        entity: { position: new Vec3(10, 64, 10) },
        version: '1.20.4',
        findBlock(options) {
            calls.find = options;
            return table;
        },
        recipesFor(itemId, metadata, count, craftingTable) {
            calls.recipe = { itemId, metadata, count, craftingTable };
            return [{ id: 'wooden-pickaxe-recipe' }];
        },
        async craft(recipe, count, craftingTable) {
            calls.craft = { recipe, count, craftingTable };
        },
    };
    const handler = createCraftHandler(() => ({ bot, botReady: true }));
    const result = await handler({ item: 'wooden_pickaxe', count: 1 });

    assert.strictEqual(result.success, true);
    assert.strictEqual(result.crafting_table_found, true);
    assert.strictEqual(calls.recipe.craftingTable, table);
    assert.strictEqual(calls.craft.craftingTable, table);
    assert.deepStrictEqual(result.crafting_table_position, { x: 11, y: 64, z: 10 });
    console.log('PASS: Craft execution grounds 3x3 recipes to an observed nearby workbench');
}

async function testDigHandlerWaitsForObservedPickup() {
    const target = new Vec3(11, 64, 10);
    let removed = false;
    let items = [{ name: 'wooden_pickaxe', count: 1 }];
    let polls = 0;
    const bot = {
        version: '1.20.4',
        entity: { position: new Vec3(10, 64, 10) },
        inventory: { items: () => items },
        blockAt(position) {
            if (position.x === target.x && position.y === target.y && position.z === target.z) {
                return removed
                    ? { name: 'air', type: 0, position: target }
                    : { name: 'stone', type: 1, drops: [35], position: target };
            }
            return { name: 'air', type: 0, position };
        },
        async dig() {
            removed = true;
        },
    };
    const handler = createDigHandler(
        () => ({ bot, botReady: true }),
        async () => {
            polls += 1;
            if (polls === 1) items = [...items, { name: 'dirt', count: 1 }];
            if (polls === 2) items = [...items, { name: 'cobblestone', count: 1 }];
        },
    );
    const result = await handler({ x: 11, y: 64, z: 10 });

    assert.strictEqual(result.success, true);
    assert.strictEqual(result.block_removed, true);
    assert.strictEqual(result.target_block_before.name, 'stone');
    assert.strictEqual(result.target_block_after.name, 'air');
    assert.strictEqual(result.pickup_observed, true);
    assert.deepStrictEqual(result.expected_drops, ['cobblestone']);
    assert.deepStrictEqual(result.pickup_inventory_delta, { dirt: 1, cobblestone: 1 });
    assert(result.pickup_waited_ms > 0);
    console.log('PASS: Dig execution waits for a bounded, observed inventory pickup');
}

async function testDigHandlerApproachesObservedDropForPickup() {
    const target = new Vec3(11, 64, 10);
    const drop = {
        id: 7,
        name: 'item',
        position: new Vec3(13, 64, 10),
        getDroppedItem: () => ({ name: 'cobblestone' }),
    };
    let removed = false;
    let items = [];
    let navigationCalls = 0;
    let navigationGoal = null;
    const bot = {
        version: '1.20.4',
        entity: { position: new Vec3(10, 64, 10) },
        entities: { 7: drop },
        inventory: { items: () => items },
        blockAt(position) {
            if (position.x === target.x && position.y === target.y && position.z === target.z) {
                return removed
                    ? { name: 'air', type: 0, position: target }
                    : { name: 'stone', type: 1, drops: [35], position: target };
            }
            return { name: 'air', type: 0, position };
        },
        async dig() {
            removed = true;
        },
        pathfinder: {
            async goto(goal) {
                navigationCalls += 1;
                navigationGoal = goal;
                bot.entity.position = drop.position.clone();
                items = [{ name: 'cobblestone', count: 1 }];
            },
            stop() {},
        },
    };
    const handler = createDigHandler(
        () => ({ bot, botReady: true }),
        async () => {},
    );
    const result = await handler({ x: 11, y: 64, z: 10 });

    assert.strictEqual(result.success, true);
    assert.strictEqual(result.block_removed, true);
    assert.strictEqual(result.pickup_observed, true);
    assert.deepStrictEqual(result.expected_drops, ['cobblestone']);
    assert.deepStrictEqual(result.pickup_inventory_delta, { cobblestone: 1 });
    assert.strictEqual(result.pickup_collection.detected, true);
    assert.strictEqual(result.pickup_collection.attempted, true);
    assert.strictEqual(navigationCalls, 1);
    assert.strictEqual(navigationGoal.constructor.name, 'GoalNear');
    console.log('PASS: Dig execution approaches its observed drop and verifies pickup');
}

async function main() {
    assert.strictEqual(M1_PROTOCOL.episode_strategy, 'fresh_level_per_task_run_v1');
    await testProtocolStatusPinsRuntimeAndDependencies();
    await testBenchmarkResetVerifiesObservedPostconditions();
    await testBenchmarkResetRejectsUnappliedServerCommands();
    await testCraftHandlerUsesGroundedNearbyTable();
    await testDigHandlerWaitsForObservedPickup();
    await testDigHandlerApproachesObservedDropForPickup();
    console.log('\nBot server benchmark reset tests PASSED');
}

main().catch((error) => {
    console.error(error);
    process.exit(1);
});
