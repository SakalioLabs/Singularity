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
    let items = [
        { name: 'oak_planks', count: 3 },
        { name: 'stick', count: 2 },
    ];
    const bot = {
        entity: { position: new Vec3(10, 64, 10) },
        version: '1.20.4',
        inventory: { items: () => items },
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
            items = [{ name: 'wooden_pickaxe', count: 1 }];
        },
    };
    const handler = createCraftHandler(
        () => ({ bot, botReady: true }),
        async () => {},
    );
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

function createProbe11MissingPickupFixture() {
    const target = new Vec3(93, 139, -36);
    let removed = false;
    const bot = {
        version: '1.20.4',
        entity: { position: new Vec3(91, 139, -36) },
        entities: {},
        inventory: { items: () => [{ name: 'dark_oak_log', count: 1 }] },
        blockAt(position) {
            if (position.x === target.x && position.y === target.y && position.z === target.z) {
                return removed
                    ? { name: 'air', type: 0, position: target }
                    : { name: 'oak_log', type: 10, drops: [131], position: target };
            }
            return { name: 'air', type: 0, position };
        },
        async dig() {
            removed = true;
        },
    };
    return { bot, target };
}

async function testM4DigHandlerFailsClosedWhenExpectedDropIsMissing() {
    const strictFixture = createProbe11MissingPickupFixture();
    const strictHandler = createDigHandler(
        () => ({ bot: strictFixture.bot, botReady: true }),
        async () => {},
    );
    const strictResult = await strictHandler({
        x: strictFixture.target.x,
        y: strictFixture.target.y,
        z: strictFixture.target.z,
        require_pickup: true,
    });

    assert.strictEqual(strictResult.success, false);
    assert.strictEqual(strictResult.error, 'expected block drop was not acquired');
    assert.strictEqual(strictResult.block_removed, true);
    assert.deepStrictEqual(strictResult.expected_drops, ['oak_log']);
    assert.strictEqual(strictResult.pickup_observed, false);
    assert.strictEqual(strictResult.pickup_collection.detected, false);
    assert.deepStrictEqual(strictResult.dig_postcondition, {
        schema_version: 1,
        policy: 'm4-expected-drop-pickup-postcondition-v1',
        required: true,
        block_removed: true,
        expected_drop_required: true,
        expected_drop_observed: false,
        passed: false,
    });

    const controlFixture = createProbe11MissingPickupFixture();
    const controlHandler = createDigHandler(
        () => ({ bot: controlFixture.bot, botReady: true }),
        async () => {},
    );
    const controlResult = await controlHandler({
        x: controlFixture.target.x,
        y: controlFixture.target.y,
        z: controlFixture.target.z,
    });
    assert.strictEqual(controlResult.success, true);
    assert.strictEqual(controlResult.block_removed, true);
    assert.strictEqual(controlResult.pickup_observed, false);
    assert.strictEqual(controlResult.dig_postcondition, undefined);
    console.log('PASS: M4 Probe 11 missing pickup fails closed while legacy dig remains unchanged');
}

function createProbe14RequiredToolFixture(options = {}) {
    const mcData = require('minecraft-data')('1.20.4');
    const target = new Vec3(114, 133, -29);
    const handHarvestable = options.handHarvestable === true;
    const blockName = handHarvestable ? 'oak_log' : (options.blockName || 'stone');
    const dropName = handHarvestable
        ? 'oak_log'
        : (blockName === 'iron_ore' ? 'raw_iron' : 'cobblestone');
    const toolNames = options.toolNames || ['wooden_pickaxe'];
    const tools = toolNames.map(name => ({
        name,
        type: mcData.itemsByName[name].id,
        count: 1,
    }));
    const tool = tools[0];
    const planks = {
        name: 'oak_planks',
        type: mcData.itemsByName.oak_planks.id,
        count: 3,
    };
    let heldItem = planks;
    let removed = false;
    let items = options.toolAvailable === false ? [planks] : [...tools, planks];
    const operations = [];
    const entity = { position: new Vec3(114.5, 134, -28.5), equipment: [heldItem] };
    const bot = {
        version: '1.20.4',
        entity,
        get heldItem() {
            return heldItem;
        },
        inventory: { items: () => items },
        blockAt(position) {
            if (position.x === target.x && position.y === target.y && position.z === target.z) {
                if (removed) return { name: 'air', type: 0, position: target };
                return {
                    name: blockName,
                    type: mcData.blocksByName[blockName].id,
                    drops: [mcData.itemsByName[dropName].id],
                    position: target,
                    harvestTools: handHarvestable
                        ? undefined
                        : mcData.blocksByName[blockName].harvestTools,
                    canHarvest: itemType => (
                        handHarvestable
                        || Boolean(mcData.blocksByName[blockName].harvestTools?.[itemType])
                    ),
                };
            }
            return { name: 'air', type: 0, position };
        },
        async equip(item, destination) {
            operations.push(`equip:${item.name}:${destination}`);
            if (options.equipThrows) throw new Error('injected equip failure');
            if (options.equipEffective !== false) {
                heldItem = item;
                entity.equipment[0] = item;
            }
        },
        async dig(block) {
            operations.push(`dig:${block.name}`);
            removed = true;
            if (options.acquireDrop) {
                items = [...items, { name: dropName, type: mcData.itemsByName[dropName].id, count: 1 }];
            }
        },
    };
    return {
        bot,
        target,
        tool,
        tools,
        operations,
        removed: () => removed,
    };
}

async function testM4DigRequiredToolEquipReplaysProbe14BeforeMutation() {
    const fixture = createProbe14RequiredToolFixture({ equipEffective: false });
    const handler = createDigHandler(
        () => ({ bot: fixture.bot, botReady: true }),
        async () => {},
    );
    const result = await handler({
        x: fixture.target.x,
        y: fixture.target.y,
        z: fixture.target.z,
        require_pickup: true,
        require_tool_equip: true,
    });

    assert.strictEqual(result.success, false);
    assert.strictEqual(result.error, 'required harvest tool wooden_pickaxe was not equipped');
    assert.strictEqual(result.block_removed, false);
    assert.strictEqual(fixture.removed(), false);
    assert.deepStrictEqual(fixture.operations, ['equip:wooden_pickaxe:hand']);
    assert.strictEqual(result.target_block_before.name, 'stone');
    assert.strictEqual(result.target_block_after.name, 'stone');
    assert.strictEqual(result.dig_tool_equip.policy, 'm4-dig-required-tool-equip-v1');
    assert.strictEqual(result.dig_tool_equip.required, true);
    assert.strictEqual(result.dig_tool_equip.selected_tool, 'wooden_pickaxe');
    assert.strictEqual(result.dig_tool_equip.equipped_tool, 'oak_planks');
    assert.strictEqual(result.dig_tool_equip.equip_attempted, true);
    assert.strictEqual(result.dig_tool_equip.equip_confirmed, false);
    assert.strictEqual(result.dig_tool_equip.mutation_allowed, false);
    assert.strictEqual(result.dig_tool_equip.passed, false);
    assert.strictEqual(result.dig_postcondition.block_removed, false);
    assert.strictEqual(result.dig_postcondition.passed, false);
    console.log('PASS: Probe 14 held-item mismatch now fails before stone mutation');
}

async function testM4DigRequiredToolEquipConfirmsCompatibleToolBeforeMutation() {
    const fixture = createProbe14RequiredToolFixture({ acquireDrop: true });
    const handler = createDigHandler(
        () => ({ bot: fixture.bot, botReady: true }),
        async () => {},
    );
    const result = await handler({
        x: fixture.target.x,
        y: fixture.target.y,
        z: fixture.target.z,
        require_pickup: true,
        require_tool_equip: true,
    });

    assert.strictEqual(result.success, true);
    assert.strictEqual(result.block_removed, true);
    assert.deepStrictEqual(result.pickup_inventory_delta, { cobblestone: 1 });
    assert.deepStrictEqual(fixture.operations, ['equip:wooden_pickaxe:hand', 'dig:stone']);
    assert.strictEqual(result.dig_tool_equip.selected_tool_type, fixture.tool.type);
    assert.strictEqual(result.dig_tool_equip.equipped_tool, 'wooden_pickaxe');
    assert.strictEqual(result.dig_tool_equip.equipped_tool_type, fixture.tool.type);
    assert.strictEqual(result.dig_tool_equip.equip_confirmed, true);
    assert.strictEqual(result.dig_tool_equip.mutation_allowed, true);
    assert.strictEqual(result.dig_tool_equip.passed, true);
    assert.strictEqual(result.dig_postcondition.passed, true);
    console.log('PASS: M4 equips and confirms a compatible harvest tool before dig');
}

async function testM4DigRequiredToolEquipSelectsIronHarvestTier() {
    const fixture = createProbe14RequiredToolFixture({
        blockName: 'iron_ore',
        toolNames: ['wooden_pickaxe', 'stone_pickaxe'],
        acquireDrop: true,
    });
    const handler = createDigHandler(
        () => ({ bot: fixture.bot, botReady: true }),
        async () => {},
    );
    const result = await handler({
        x: fixture.target.x,
        y: fixture.target.y,
        z: fixture.target.z,
        require_pickup: true,
        require_tool_equip: true,
    });

    assert.strictEqual(result.success, true);
    assert.deepStrictEqual(result.expected_drops, ['raw_iron']);
    assert.deepStrictEqual(result.pickup_inventory_delta, { raw_iron: 1 });
    assert.deepStrictEqual(fixture.operations, ['equip:stone_pickaxe:hand', 'dig:iron_ore']);
    assert.deepStrictEqual(
        result.dig_tool_equip.compatible_inventory_tools.map(item => item.name),
        ['stone_pickaxe'],
    );
    assert.strictEqual(result.dig_tool_equip.selected_tool, 'stone_pickaxe');
    assert.strictEqual(result.dig_tool_equip.equipped_tool, 'stone_pickaxe');
    assert.strictEqual(result.dig_tool_equip.passed, true);
    console.log('PASS: M4 selects stone pickaxe over incompatible wood for iron ore');
}

async function testM4DigRequiredToolEquipFailsClosedForMissingToolAndEquipError() {
    const missing = createProbe14RequiredToolFixture({ toolAvailable: false });
    const missingResult = await createDigHandler(
        () => ({ bot: missing.bot, botReady: true }),
        async () => {},
    )({
        x: missing.target.x,
        y: missing.target.y,
        z: missing.target.z,
        require_pickup: true,
        require_tool_equip: true,
    });
    assert.strictEqual(missingResult.success, false);
    assert.strictEqual(missingResult.error, 'no compatible harvest tool available for stone');
    assert.strictEqual(missingResult.dig_tool_equip.equip_attempted, false);
    assert.strictEqual(missingResult.dig_tool_equip.mutation_allowed, false);
    assert.strictEqual(missing.removed(), false);
    assert.deepStrictEqual(missing.operations, []);

    const equipError = createProbe14RequiredToolFixture({ equipThrows: true });
    const equipErrorResult = await createDigHandler(
        () => ({ bot: equipError.bot, botReady: true }),
        async () => {},
    )({
        x: equipError.target.x,
        y: equipError.target.y,
        z: equipError.target.z,
        require_pickup: true,
        require_tool_equip: true,
    });
    assert.strictEqual(equipErrorResult.success, false);
    assert.match(equipErrorResult.error, /could not equip required harvest tool/);
    assert.strictEqual(equipErrorResult.dig_tool_equip.equip_attempted, true);
    assert.strictEqual(equipErrorResult.dig_tool_equip.equip_confirmed, false);
    assert.strictEqual(equipError.removed(), false);
    assert.deepStrictEqual(equipError.operations, ['equip:wooden_pickaxe:hand']);
    console.log('PASS: Missing or failed M4 harvest-tool equip cannot mutate the block');
}

async function testM4DigRequiredToolEquipPreservesHandAndLegacyPaths() {
    const hand = createProbe14RequiredToolFixture({
        handHarvestable: true,
        toolAvailable: false,
        acquireDrop: true,
    });
    const handResult = await createDigHandler(
        () => ({ bot: hand.bot, botReady: true }),
        async () => {},
    )({
        x: hand.target.x,
        y: hand.target.y,
        z: hand.target.z,
        require_pickup: true,
        require_tool_equip: true,
    });
    assert.strictEqual(handResult.success, true);
    assert.strictEqual(handResult.dig_tool_equip.required, false);
    assert.strictEqual(handResult.dig_tool_equip.equip_attempted, false);
    assert.strictEqual(handResult.dig_tool_equip.mutation_allowed, true);
    assert.deepStrictEqual(hand.operations, ['dig:oak_log']);

    const legacy = createProbe14RequiredToolFixture({ toolAvailable: false });
    const legacyResult = await createDigHandler(
        () => ({ bot: legacy.bot, botReady: true }),
        async () => {},
    )({ x: legacy.target.x, y: legacy.target.y, z: legacy.target.z });
    assert.strictEqual(legacyResult.success, true);
    assert.strictEqual(legacyResult.dig_tool_equip, undefined);
    assert.deepStrictEqual(legacy.operations, ['dig:stone']);
    console.log('PASS: Hand-harvestable M4 and legacy dig behavior remain compatible');
}

async function testM4DigHandlerWaitsForDropAndUsesReachablePickupGoal() {
    const target = new Vec3(93, 139, -36);
    const drop = {
        id: 11,
        name: 'item',
        position: new Vec3(94, 138, -36),
        getDroppedItem: () => ({ name: 'oak_log' }),
    };
    let removed = false;
    let items = [{ name: 'dark_oak_log', count: 1 }];
    let waitCalls = 0;
    let navigationGoal = null;
    const bot = {
        version: '1.20.4',
        entity: { position: new Vec3(91, 139, -36) },
        entities: {},
        inventory: { items: () => items },
        blockAt(position) {
            if (position.x === target.x && position.y === target.y && position.z === target.z) {
                return removed
                    ? { name: 'air', type: 0, position: target }
                    : { name: 'oak_log', type: 10, drops: [131], position: target };
            }
            return { name: 'air', type: 0, position };
        },
        async dig() {
            removed = true;
        },
        pathfinder: {
            async goto(goal) {
                navigationGoal = goal;
                bot.entity.position = drop.position.clone();
                items = [...items, { name: 'oak_log', count: 1 }];
            },
            stop() {},
        },
    };
    const handler = createDigHandler(
        () => ({ bot, botReady: true }),
        async () => {
            waitCalls += 1;
            if (waitCalls === 11) bot.entities[drop.id] = drop;
        },
    );
    const result = await handler({ x: target.x, y: target.y, z: target.z, require_pickup: true });

    assert.strictEqual(result.success, true);
    assert.strictEqual(result.pickup_observed, true);
    assert.deepStrictEqual(result.pickup_inventory_delta, { oak_log: 1 });
    assert.strictEqual(result.pickup_collection.detected, true);
    assert.strictEqual(result.pickup_collection.attempted, true);
    assert(result.pickup_collection.detection_waited_ms > 0);
    assert.strictEqual(result.pickup_collection.goal_range, 1);
    assert.strictEqual(navigationGoal.constructor.name, 'GoalNear');
    assert.strictEqual(navigationGoal.rangeSq, 1);
    assert.strictEqual(result.dig_postcondition.passed, true);
    console.log('PASS: M4 dig waits for a delayed drop and uses a reachable pickup goal');
}

function createProbe12FalsePickupCompletionFixture(options = {}) {
    const target = new Vec3(93, 138, -36);
    const drop = {
        id: 871,
        name: 'item',
        position: new Vec3(93.125, 138, -35.334716796875),
        getDroppedItem: () => ({ name: 'oak_log' }),
    };
    let removed = false;
    let items = [{ name: 'dark_oak_log', count: 3 }];
    let clockMs = 0;
    const navigationGoals = [];
    const falseCompletionPosition = new Vec3(
        93.34238234601303,
        140.07472379453523,
        -35.48680946380416,
    );
    const bot = {
        version: '1.20.4',
        entity: {
            position: new Vec3(
                93.50127136141536,
                140.07472379453523,
                -35.491858797329925,
            ),
        },
        entities: { [drop.id]: drop },
        inventory: { items: () => items },
        blockAt(position) {
            if (position.x === target.x && position.y === target.y && position.z === target.z) {
                return removed
                    ? { name: 'air', type: 0, boundingBox: 'empty', position: target }
                    : { name: 'oak_log', type: 46, boundingBox: 'block', drops: [131], position: target };
            }
            if (position.x === target.x && position.y === target.y - 1 && position.z === target.z) {
                if (options.standable === false) {
                    return { name: 'air', type: 0, boundingBox: 'empty', position };
                }
                return { name: 'oak_log', type: 46, boundingBox: 'block', position };
            }
            return { name: 'air', type: 0, boundingBox: 'empty', position };
        },
        async dig() {
            removed = true;
        },
        pathfinder: {
            async goto(goal) {
                navigationGoals.push(goal);
                if (navigationGoals.length === 1) {
                    clockMs += 2000;
                    bot.entity.position = falseCompletionPosition.clone();
                    return;
                }
                clockMs += 500;
                if (options.fallbackMoves !== false) {
                    bot.entity.position = new Vec3(target.x + 0.5, target.y, target.z + 0.5);
                }
                if (options.acquireOnFallback !== false) {
                    items = [...items, { name: 'oak_log', count: 1 }];
                }
            },
            stop() {},
        },
    };
    return {
        bot,
        target,
        drop,
        navigationGoals,
        monotonicMs: () => clockMs,
    };
}

function createSP001AdjacentPickupMarginFixture(options = {}) {
    const target = new Vec3(94, 131, -32);
    const drop = {
        id: 322,
        name: 'item',
        position: new Vec3(94.125, 131, -31.875),
        getDroppedItem: () => ({ name: 'oak_log' }),
    };
    let removed = false;
    let items = [{ name: 'dark_oak_log', count: 3 }];
    let clockMs = 0;
    let forward = false;
    let nudgeAcquired = false;
    const navigationGoals = [];
    const controlStates = [];
    const bot = {
        version: '1.20.4',
        entity: {
            position: new Vec3(95.57907285827427, 131, -31.494351547541445),
        },
        entities: { [drop.id]: drop },
        inventory: { items: () => items },
        blockAt(position) {
            if (position.x === target.x && position.y === target.y && position.z === target.z) {
                return removed
                    ? { name: 'air', type: 0, boundingBox: 'empty', position: target }
                    : { name: 'oak_log', type: 46, boundingBox: 'block', drops: [131], position: target };
            }
            if (position.x === 94 && position.y === 132 && position.z === -32) {
                return { name: 'dirt', type: 9, boundingBox: 'block', position };
            }
            if (position.x === 95 && position.y === 130 && position.z === -32) {
                return { name: 'stone', type: 1, boundingBox: 'block', position };
            }
            return { name: 'air', type: 0, boundingBox: 'empty', position };
        },
        async dig() {
            removed = true;
        },
        async lookAt() {},
        setControlState(name, value) {
            if (name === 'forward') forward = value === true;
            controlStates.push({ name, value });
        },
        pathfinder: {
            async goto(goal) {
                navigationGoals.push(goal);
                if (navigationGoals.length === 1) {
                    clockMs += 2000;
                    return;
                }
                clockMs += 500;
                if (options.sameCellGoalResolvesWithoutMovement === true) return;
                bot.entity.position = new Vec3(95.5, 131, -31.5);
                items = [...items, { name: 'oak_log', count: 1 }];
            },
            stop() {},
        },
    };
    return {
        bot,
        target,
        navigationGoals,
        controlStates,
        monotonicMs: () => clockMs,
        async wait(ms) {
            clockMs += Number(ms) || 0;
            if (forward && options.acquireOnNudge === true && !nudgeAcquired) {
                bot.entity.position = new Vec3(95.35, 131, -31.5);
                items = [...items, { name: 'oak_log', count: 1 }];
                nudgeAcquired = true;
            }
        },
    };
}

async function testM4PickupCompletionUsesProbe12StandableFallback() {
    const fixture = createProbe12FalsePickupCompletionFixture();
    const handler = createDigHandler(
        () => ({ bot: fixture.bot, botReady: true }),
        async () => {},
        { monotonicMs: fixture.monotonicMs },
    );
    const result = await handler({
        x: fixture.target.x,
        y: fixture.target.y,
        z: fixture.target.z,
        require_pickup: true,
    });

    assert.strictEqual(result.success, true);
    assert.strictEqual(result.pickup_observed, true);
    assert.deepStrictEqual(result.pickup_inventory_delta, { oak_log: 1 });
    assert.strictEqual(result.pickup_collection.completion_policy, 'm4-pickup-collection-completion-grounding-v1');
    assert.strictEqual(result.pickup_collection.direct_navigation.pathfinder_resolved, true);
    assert.strictEqual(result.pickup_collection.direct_navigation.completion_grounded, false);
    assert(Math.abs(result.pickup_collection.initial_distance - 2.1144154202377106) < 1e-9);
    assert(Math.abs(result.pickup_collection.direct_navigation.final_distance - 2.0916180548327694) < 1e-9);
    assert.strictEqual(result.pickup_collection.fallback_attempt_limit, 1);
    assert.strictEqual(result.pickup_collection.fallback_attempt_count, 1);
    assert.deepStrictEqual(result.pickup_collection.fallback_candidate.position, { x: 93, y: 138, z: -36 });
    assert.strictEqual(result.pickup_collection.fallback_candidate.support.solid, true);
    assert.strictEqual(result.pickup_collection.fallback_candidate.feet.passable, true);
    assert.strictEqual(result.pickup_collection.fallback_candidate.head.passable, true);
    assert.strictEqual(result.pickup_collection.fallback_navigation.goal_type, 'GoalBlock');
    assert.strictEqual(result.pickup_collection.fallback_navigation.timeout_ms, 4000);
    assert.strictEqual(result.pickup_collection.fallback_navigation.inventory_delta_observed, true);
    assert.strictEqual(result.pickup_collection.completion_grounded, true);
    assert.strictEqual(result.pickup_collection.completion_grounded_by, 'inventory_delta');
    assert.strictEqual(fixture.navigationGoals.length, 2);
    assert.strictEqual(fixture.navigationGoals[0].constructor.name, 'GoalNear');
    assert.strictEqual(fixture.navigationGoals[1].constructor.name, 'GoalBlock');
    assert.strictEqual(result.dig_postcondition.passed, true);
    console.log('PASS: Probe 12 false pickup completion uses one grounded standable-cell fallback');
}

async function testM4PickupCompletionFallbackFailsClosedAndStopsAfterOneAttempt() {
    const fixture = createProbe12FalsePickupCompletionFixture({
        acquireOnFallback: false,
        fallbackMoves: false,
    });
    const handler = createDigHandler(
        () => ({ bot: fixture.bot, botReady: true }),
        async () => {},
        { monotonicMs: fixture.monotonicMs },
    );
    const result = await handler({
        x: fixture.target.x,
        y: fixture.target.y,
        z: fixture.target.z,
        require_pickup: true,
    });

    assert.strictEqual(result.success, false);
    assert.strictEqual(result.error, 'expected block drop was not acquired');
    assert.strictEqual(result.pickup_observed, false);
    assert.strictEqual(result.pickup_collection.success, false);
    assert.strictEqual(result.pickup_collection.completion_grounded, false);
    assert.strictEqual(result.pickup_collection.fallback_attempt_count, 1);
    assert.strictEqual(result.pickup_collection.fallback_navigation.pathfinder_resolved, true);
    assert.strictEqual(result.pickup_collection.fallback_navigation.completion_grounded, false);
    assert.match(result.pickup_collection.error, /outside acquisition range/);
    assert.strictEqual(fixture.navigationGoals.length, 2);
    assert.strictEqual(result.dig_postcondition.passed, false);
    console.log('PASS: M4 pickup fallback remains fail-closed and performs no third navigation');
}

async function testSP001PickupFallbackUsesBoundedAdjacentCandidateMargin() {
    const fixture = createSP001AdjacentPickupMarginFixture();
    const handler = createDigHandler(
        () => ({ bot: fixture.bot, botReady: true }),
        async () => {},
        { monotonicMs: fixture.monotonicMs },
    );
    const result = await handler({
        x: fixture.target.x,
        y: fixture.target.y,
        z: fixture.target.z,
        require_pickup: true,
    });

    assert.strictEqual(result.success, true);
    assert.strictEqual(result.pickup_observed, true);
    assert.deepStrictEqual(result.pickup_inventory_delta, { oak_log: 1 });
    assert.strictEqual(result.pickup_collection.goal_range, 1);
    assert.strictEqual(result.pickup_collection.fallback_candidate_margin, 0.5);
    assert.strictEqual(result.pickup_collection.fallback_candidate_max_distance, 1.5);
    assert.strictEqual(result.pickup_collection.direct_navigation.completion_grounded, false);
    assert(result.pickup_collection.initial_distance > 1.5);
    assert.deepStrictEqual(
        result.pickup_collection.fallback_candidate.position,
        { x: 95, y: 131, z: -32 },
    );
    assert(result.pickup_collection.fallback_candidate.expected_pickup_distance > 1);
    assert(result.pickup_collection.fallback_candidate.expected_pickup_distance <= 1.5);
    assert.strictEqual(result.pickup_collection.fallback_same_cell_nudge.required, true);
    assert.strictEqual(result.pickup_collection.fallback_same_cell_nudge.attempted, true);
    assert.strictEqual(result.pickup_collection.fallback_same_cell_nudge.completion_grounded, false);
    assert.strictEqual(result.pickup_collection.fallback_navigation.distance_grounded, false);
    assert.strictEqual(result.pickup_collection.fallback_navigation.inventory_delta_observed, true);
    assert.strictEqual(result.pickup_collection.completion_grounded_by, 'inventory_delta');
    assert.strictEqual(fixture.navigationGoals.length, 2);
    console.log('PASS: SP-001 pickup fallback uses a bounded adjacent candidate margin');
}

async function testSP001PickupFallbackNudgesSameCellAlias() {
    const fixture = createSP001AdjacentPickupMarginFixture({
        sameCellGoalResolvesWithoutMovement: true,
        acquireOnNudge: true,
    });
    const handler = createDigHandler(
        () => ({ bot: fixture.bot, botReady: true }),
        fixture.wait,
        { monotonicMs: fixture.monotonicMs },
    );
    const result = await handler({
        x: fixture.target.x,
        y: fixture.target.y,
        z: fixture.target.z,
        require_pickup: true,
    });

    assert.strictEqual(result.success, true);
    assert.strictEqual(result.pickup_observed, true);
    assert.deepStrictEqual(result.pickup_inventory_delta, { oak_log: 1 });
    assert.strictEqual(result.pickup_collection.fallback_attempt_count, 1);
    assert.strictEqual(result.pickup_collection.fallback_same_cell_nudge_attempt_limit, 1);
    assert.strictEqual(result.pickup_collection.fallback_same_cell_nudge_attempt_count, 1);
    assert.strictEqual(result.pickup_collection.fallback_same_cell_nudge.required, true);
    assert.strictEqual(result.pickup_collection.fallback_same_cell_nudge.attempted, true);
    assert.strictEqual(result.pickup_collection.fallback_same_cell_nudge.duration_ms, 100);
    assert.strictEqual(
        result.pickup_collection.fallback_same_cell_nudge.inventory_delta_observed,
        true,
    );
    assert.strictEqual(result.pickup_collection.fallback_same_cell_nudge.completion_grounded, true);
    assert.strictEqual(result.pickup_collection.completion_grounded_by, 'inventory_delta');
    assert.strictEqual(result.pickup_collection.fallback_navigation, undefined);
    assert.strictEqual(fixture.navigationGoals.length, 1);
    assert.deepStrictEqual(fixture.controlStates, [
        { name: 'forward', value: true },
        { name: 'forward', value: false },
    ]);
    console.log('PASS: SP-001 same-cell fallback performs one bounded grounded center nudge');
}

async function testSP001SameCellNudgeStillRequiresGrounding() {
    const fixture = createSP001AdjacentPickupMarginFixture({
        sameCellGoalResolvesWithoutMovement: true,
        acquireOnNudge: false,
    });
    const handler = createDigHandler(
        () => ({ bot: fixture.bot, botReady: true }),
        fixture.wait,
        { monotonicMs: fixture.monotonicMs },
    );
    const result = await handler({
        x: fixture.target.x,
        y: fixture.target.y,
        z: fixture.target.z,
        require_pickup: true,
    });

    assert.strictEqual(result.success, false);
    assert.strictEqual(result.pickup_observed, false);
    assert.strictEqual(result.pickup_collection.fallback_attempt_count, 1);
    assert.strictEqual(result.pickup_collection.fallback_same_cell_nudge.attempted, true);
    assert.strictEqual(
        result.pickup_collection.fallback_same_cell_nudge.completion_grounded,
        false,
    );
    assert.strictEqual(result.pickup_collection.fallback_navigation.pathfinder_resolved, true);
    assert.strictEqual(result.pickup_collection.fallback_navigation.completion_grounded, false);
    assert.strictEqual(fixture.navigationGoals.length, 2);
    assert.deepStrictEqual(fixture.controlStates, [
        { name: 'forward', value: true },
        { name: 'forward', value: false },
    ]);
    console.log('PASS: SP-001 same-cell nudge cannot self-certify without grounded pickup');
}

async function testM4PickupCompletionRejectsUnsupportedFallbackCell() {
    const fixture = createProbe12FalsePickupCompletionFixture({ standable: false });
    const handler = createDigHandler(
        () => ({ bot: fixture.bot, botReady: true }),
        async () => {},
        { monotonicMs: fixture.monotonicMs },
    );
    const result = await handler({
        x: fixture.target.x,
        y: fixture.target.y,
        z: fixture.target.z,
        require_pickup: true,
    });

    assert.strictEqual(result.success, false);
    assert.strictEqual(result.pickup_collection.success, false);
    assert.strictEqual(result.pickup_collection.fallback_candidate, null);
    assert.strictEqual(result.pickup_collection.fallback_attempt_count, 0);
    assert.match(result.pickup_collection.error, /no standable fallback/);
    assert.strictEqual(fixture.navigationGoals.length, 1);
    console.log('PASS: M4 pickup completion rejects an unsupported fallback cell before navigation');
}

async function testPickupCompletionGroundingLeavesLegacyDigUnchanged() {
    const fixture = createProbe12FalsePickupCompletionFixture();
    const handler = createDigHandler(
        () => ({ bot: fixture.bot, botReady: true }),
        async () => {},
        { monotonicMs: fixture.monotonicMs },
    );
    const result = await handler({
        x: fixture.target.x,
        y: fixture.target.y,
        z: fixture.target.z,
    });

    assert.strictEqual(result.success, true);
    assert.strictEqual(result.pickup_observed, false);
    assert.strictEqual(result.pickup_collection.success, true);
    assert.strictEqual(result.pickup_collection.completion_policy, undefined);
    assert.strictEqual(result.pickup_collection.fallback_navigation, undefined);
    assert.strictEqual(fixture.navigationGoals.length, 1);
    assert.strictEqual(result.dig_postcondition, undefined);
    console.log('PASS: Pickup completion grounding leaves the fixed legacy dig path unchanged');
}

async function main() {
    assert.strictEqual(M1_PROTOCOL.episode_strategy, 'fresh_level_per_task_run_v1');
    await testProtocolStatusPinsRuntimeAndDependencies();
    await testBenchmarkResetVerifiesObservedPostconditions();
    await testBenchmarkResetRejectsUnappliedServerCommands();
    await testCraftHandlerUsesGroundedNearbyTable();
    await testDigHandlerWaitsForObservedPickup();
    await testDigHandlerApproachesObservedDropForPickup();
    await testM4DigHandlerFailsClosedWhenExpectedDropIsMissing();
    await testM4DigRequiredToolEquipReplaysProbe14BeforeMutation();
    await testM4DigRequiredToolEquipConfirmsCompatibleToolBeforeMutation();
    await testM4DigRequiredToolEquipSelectsIronHarvestTier();
    await testM4DigRequiredToolEquipFailsClosedForMissingToolAndEquipError();
    await testM4DigRequiredToolEquipPreservesHandAndLegacyPaths();
    await testM4DigHandlerWaitsForDropAndUsesReachablePickupGoal();
    await testM4PickupCompletionUsesProbe12StandableFallback();
    await testM4PickupCompletionFallbackFailsClosedAndStopsAfterOneAttempt();
    await testSP001PickupFallbackUsesBoundedAdjacentCandidateMargin();
    await testSP001PickupFallbackNudgesSameCellAlias();
    await testSP001SameCellNudgeStillRequiresGrounding();
    await testM4PickupCompletionRejectsUnsupportedFallbackCell();
    await testPickupCompletionGroundingLeavesLegacyDigUnchanged();
    console.log('\nBot server benchmark reset tests PASSED');
}

main().catch((error) => {
    console.error(error);
    process.exit(1);
});
