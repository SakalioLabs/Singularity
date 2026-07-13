'use strict';

const assert = require('assert');
const { EventEmitter } = require('events');
const { Vec3 } = require('vec3');
const {
    M4_PROTOCOL,
    M4_PROTOCOL_SHA256,
    M4_BM012_PROTOCOL,
    M4_BM012_PROTOCOL_SHA256,
    benchmarkProtocolStatus,
    createBenchmarkResetHandler,
    createBuildShelterCellHandler,
    createM4PlayerLifecycleTracker,
    createPlaceHandler,
    createShelterStateHandler,
} = require('../src/bot/bot_server');

const runtime = {
    seed: '12345',
    episode_id: 'offline-m4-contract-test',
    level_name: 'offline-m4-contract-test_bm011',
    server_jar_sha256: M4_PROTOCOL.server_jar_sha256,
};

function createM4Bot() {
    const spawnPoint = new Vec3(10, 64, 10);
    let items = [{ name: 'dirt', count: 4 }];
    const commands = [];
    const bot = {
        spawnPoint,
        entity: { position: new Vec3(18, 70, 18), equipment: [] },
        health: 20,
        food: 20,
        foodSaturation: 5,
        version: '1.20.4',
        game: {
            gameMode: 'creative',
            difficulty: 'hard',
            dimension: 'overworld',
            serverBrand: 'Paper',
        },
        time: { timeOfDay: 15000 },
        thunderState: 1,
        rainState: 1,
        inventory: { items: () => items },
        blockAt(position) {
            return { name: 'grass_block', type: 1, position };
        },
        chat(command) {
            commands.push(command);
            if (command.startsWith('/execute in minecraft:overworld run tp')) {
                bot.entity.position = spawnPoint.clone();
            } else if (command.startsWith('/gamemode ')) {
                bot.game.gameMode = 'survival';
            } else if (command === '/clear @s') {
                items = [];
            } else if (command.startsWith('/time set ')) {
                bot.time.timeOfDay = Number(command.split(' ').pop());
            } else if (command.startsWith('/weather ')) {
                bot.rainState = 0;
                bot.thunderState = 0;
            } else if (command.startsWith('/difficulty ')) {
                bot.game.difficulty = 'normal';
            }
        },
    };
    const emitter = new EventEmitter();
    bot.on = emitter.on.bind(emitter);
    bot.emit = emitter.emit.bind(emitter);
    return { bot, commands };
}

async function testM4ProtocolStatusPinsAutonomousRuntime() {
    const { bot } = createM4Bot();
    const status = benchmarkProtocolStatus(bot, runtime, 'm4-fixed-v1');

    assert.strictEqual(status.configured, true);
    assert.strictEqual(status.profile, 'm4-fixed-v1');
    assert.strictEqual(status.protocol_sha256, M4_PROTOCOL_SHA256);
    assert.strictEqual(status.goal_generator_id, M4_PROTOCOL.identities.goal_generator);
    assert.strictEqual(status.curriculum_id, M4_PROTOCOL.identities.curriculum);
    assert.strictEqual(status.planner_id, M4_PROTOCOL.identities.planner);
    assert.strictEqual(status.runtime_interrupt_id, M4_PROTOCOL.identities.runtime_interrupt);
    assert.strictEqual(status.player_lifecycle_verifier_id, M4_PROTOCOL.identities.player_lifecycle_verifier);
    assert.strictEqual(status.player_lifecycle_supported, true);
    assert.strictEqual(status.player_lifecycle_source, 'mineflayer_events');
    assert.deepStrictEqual(status.llm, M4_PROTOCOL.llm);
    assert.deepStrictEqual(status.runtime_controls, M4_PROTOCOL.baseline_runtime_controls);
    assert.strictEqual(status.validation_supported, true);
    assert.strictEqual(status.tasks[0].id, 'BM-011');
    assert.deepStrictEqual(status.task_contracts['BM-012'], {
        id: M4_BM012_PROTOCOL.id,
        sha256: M4_BM012_PROTOCOL_SHA256,
    });
    console.log('PASS: M4 bridge pins autonomous identities, runtime, and task scope');
}

async function testBM012ResetUsesTaskBoundDaylightWithoutItemsOrFixtures() {
    const { bot, commands } = createM4Bot();
    const bm012Runtime = {
        ...runtime,
        episode_id: 'offline-m4-bm012-contract-test',
        level_name: 'offline-m4-bm012-contract-test_bm012',
    };
    const lifecycle = createM4PlayerLifecycleTracker({ trackerId: 'offline-bm012-lifecycle' });
    lifecycle.attach(bot);
    bot.emit('spawn');
    const reset = createBenchmarkResetHandler(
        () => ({ bot, botReady: true, playerLifecycleTracker: lifecycle }),
        async () => {},
        bm012Runtime,
    );

    const result = await reset({ task_id: 'BM-012' });

    assert.strictEqual(result.success, true, JSON.stringify(result));
    assert.strictEqual(result.task_contract_id, M4_BM012_PROTOCOL.id);
    assert.strictEqual(result.task_contract_sha256, M4_BM012_PROTOCOL_SHA256);
    assert.strictEqual(result.after_state.time_of_day, 0);
    assert.strictEqual(result.expected.time_of_day, 0);
    assert.deepStrictEqual(result.after_state.inventory, {});
    assert(commands.includes('/time set 0'));
    assert(!commands.some(command => command.startsWith('/give ')));
    assert.strictEqual(result.checks.player_lifecycle_baseline, true);
    console.log('PASS: BM-012 reset is task-bound daylight with no granted resources or fixtures');
}

async function testM4ResetUsesNaturalSurvivalStateWithoutFixtures() {
    const { bot, commands } = createM4Bot();
    let clock = 1000;
    const lifecycle = createM4PlayerLifecycleTracker({
        trackerId: 'offline-m4-lifecycle-tracker',
        nowMs: () => ++clock,
        monotonicMs: () => ++clock,
    });
    lifecycle.attach(bot);
    bot.emit('spawn');
    bot.health = 0;
    bot.emit('death');
    bot.health = 20;
    bot.emit('spawn');
    const reset = createBenchmarkResetHandler(
        () => ({ bot, botReady: true, playerLifecycleTracker: lifecycle }),
        async () => {},
        runtime,
    );
    const result = await reset({ task_id: 'BM-011' });

    assert.strictEqual(result.success, true, JSON.stringify(result));
    assert.strictEqual(result.profile, 'm4-fixed-v1');
    assert.deepStrictEqual(result.after_state.inventory, {});
    assert.strictEqual(result.after_state.game_mode, 'survival');
    assert.strictEqual(result.after_state.difficulty, 'normal');
    assert.strictEqual(result.after_state.time_of_day, 9000);
    assert.strictEqual(result.after_state.weather, 'clear');
    assert.strictEqual(result.after_state.food_saturation, 5);
    assert.strictEqual(result.checks.saturation, true);
    assert.strictEqual(result.checks.fixture, true);
    assert.strictEqual(result.checks.player_lifecycle_baseline, true);
    assert.strictEqual(result.player_lifecycle.baseline_death_count_total, 1);
    assert.strictEqual(result.player_lifecycle.baseline_respawn_count_total, 1);
    assert.strictEqual(result.player_lifecycle.death_count, 0);
    assert.strictEqual(result.player_lifecycle.respawn_count, 0);
    assert.strictEqual(result.player_lifecycle.uninterrupted, true);
    assert.deepStrictEqual(result.gamerules, M4_PROTOCOL.gamerules);
    assert(commands.includes('/effect clear @s'));
    assert(commands.includes('/gamerule doDaylightCycle true'));
    assert(commands.includes('/gamerule doMobSpawning true'));
    assert(!commands.some(command => command.startsWith('/give ')));
    assert(!commands.some(command => command.includes('minecraft:saturation')));
    assert.strictEqual(result.structure_baseline.blocks, undefined);
    bot.health = 0;
    bot.emit('death');
    let active = lifecycle.snapshot();
    assert.strictEqual(active.death_count, 1);
    assert.strictEqual(active.respawn_count, 0);
    assert.strictEqual(active.pending_respawn_count, 1);
    assert.strictEqual(active.uninterrupted, false);
    bot.health = 20;
    bot.emit('spawn');
    active = lifecycle.snapshot();
    assert.strictEqual(active.death_count, 1);
    assert.strictEqual(active.respawn_count, 1);
    assert.strictEqual(active.pending_respawn_count, 0);
    assert.strictEqual(active.last_death.kind, 'death');
    assert.strictEqual(active.last_respawn.kind, 'respawn');
    console.log('PASS: M4 reset proves empty natural survival state without fixtures or granted items');
}

async function testM4ResetRejectsLifecycleWithoutInitialMineflayerSpawn() {
    const { bot } = createM4Bot();
    const lifecycle = createM4PlayerLifecycleTracker({ trackerId: 'missing-spawn-tracker' });
    lifecycle.attach(bot);
    const reset = createBenchmarkResetHandler(
        () => ({ bot, botReady: true, playerLifecycleTracker: lifecycle }),
        async () => {},
        runtime,
    );

    const result = await reset({ task_id: 'BM-011' });

    assert.strictEqual(result.success, false);
    assert.strictEqual(result.checks.player_lifecycle_baseline, false);
    assert(result.failed_checks.includes('player_lifecycle_baseline'));
    console.log('PASS: M4 reset fails closed without an observed Mineflayer spawn baseline');
}

function positionKey(position) {
    return `${Number(position.x)},${Number(position.y)},${Number(position.z)}`;
}

function createShelterBot() {
    const blocks = new Map();
    const oakPlanks = { name: 'oak_planks', count: 4 };
    const darkOakSapling = { name: 'dark_oak_sapling', count: 1 };
    const equipCalls = [];
    const player = { position: new Vec3(0.5, 64, 0.5), equipment: [darkOakSapling] };
    const zombie = { name: 'zombie', type: 'mob', position: new Vec3(4, 64, 0) };
    const bot = {
        entity: player,
        entities: { player, 17: zombie },
        inventory: { items: () => [oakPlanks, darkOakSapling] },
        get heldItem() {
            return this.entity.equipment[0] || null;
        },
        blockAt(position) {
            const name = blocks.get(positionKey(position)) || 'air';
            return {
                name,
                type: name === 'air' ? 0 : 1,
                boundingBox: name === 'air' ? 'empty' : 'block',
                position: position.clone ? position.clone() : new Vec3(position.x, position.y, position.z),
            };
        },
        async equip(item, destination) {
            equipCalls.push({ item: item.name, destination });
            this.entity.equipment[0] = item;
        },
        async placeBlock(reference, face) {
            if (!this.heldItem) throw new Error('must be holding an item to place');
            const target = reference.position.plus(face);
            blocks.set(positionKey(target), this.heldItem.name);
        },
    };
    blocks.set('0,63,0', 'stone');
    for (const [dx, dz] of [[0, -1], [1, 0], [0, 1], [-1, 0]]) {
        blocks.set(`${dx},64,${dz}`, 'oak_planks');
        blocks.set(`${dx},65,${dz}`, 'oak_planks');
    }
    blocks.set('0,66,0', 'oak_planks');
    return { bot, blocks, equipCalls };
}

async function testM4ShelterSnapshotReturnsCompleteBoundedMachineState() {
    const { bot } = createShelterBot();
    const handler = createShelterStateHandler(() => ({ bot, botReady: true }));
    const snapshot = await handler();

    assert.strictEqual(snapshot.success, true);
    assert.strictEqual(snapshot.type, 'm4_shelter_machine_snapshot');
    assert.strictEqual(snapshot.source, 'mineflayer_world_state');
    assert.deepStrictEqual(snapshot.player_cell, { x: 0, y: 64, z: 0 });
    assert.strictEqual(snapshot.blocks.length, 36);
    assert.strictEqual(snapshot.blocks.filter(block => block.solid).length, 10);
    assert.strictEqual(snapshot.nearby_hostiles.length, 1);
    assert.strictEqual(snapshot.nearby_hostiles[0].name, 'zombie');
    assert(snapshot.blocks.some(block => block.position.x === 0 && block.position.y === 64 && block.position.z === 0 && block.passable));
    console.log('PASS: M4 bridge emits the complete bounded shelter machine snapshot');
}

async function testM4PlaceHandlerReturnsObservedCoordinateDelta() {
    const { bot, blocks, equipCalls } = createShelterBot();
    blocks.delete('0,64,0');
    const handler = createPlaceHandler(() => ({ bot, botReady: true }));
    const missing = await handler({ item: 'oak_planks' });
    assert.strictEqual(missing.success, false);
    assert.match(missing.error, /finite reference coordinates/);
    const unavailable = await handler({ x: 0, y: 63, z: 0, item: 'crafting_table' });
    assert.strictEqual(unavailable.success, false);
    assert.strictEqual(unavailable.error, 'crafting_table is not available for placement');
    assert.deepStrictEqual(equipCalls, []);
    assert.strictEqual(blocks.has('0,64,0'), false);
    const result = await handler({ x: 0, y: 63, z: 0, item: 'oak_planks' });

    assert.strictEqual(result.success, true);
    assert.deepStrictEqual(equipCalls, [{ item: 'oak_planks', destination: 'hand' }]);
    assert.strictEqual(result.equipped_item, 'oak_planks');
    assert.strictEqual(result.requested_item_equipped, true);
    assert.strictEqual(result.equip_policy_id, 'm4-place-requested-item-equip-v1');
    assert.strictEqual(result.target_occupancy_policy_id, 'm4-place-target-occupancy-v1');
    assert.deepStrictEqual(result.placed_position, { x: 0, y: 64, z: 0 });
    assert.strictEqual(result.target_block_before.name, 'air');
    assert.strictEqual(result.target_block_after.name, 'oak_planks');
    assert.strictEqual(result.target_block_after.solid, true);
    console.log('PASS: M4 place evidence binds the requested action to an observed block delta');
}

async function testM4PlaceHandlerRejectsUnequippedRequestedItemBeforeMutation() {
    const { bot, blocks } = createShelterBot();
    blocks.delete('0,64,0');
    let placeCalls = 0;
    bot.inventory = {
        items: () => [
            { name: 'crafting_table', count: 1 },
            { name: 'dark_oak_sapling', count: 1 },
        ],
    };
    bot.equip = async () => {};
    bot.placeBlock = async () => {
        placeCalls += 1;
        blocks.set('0,64,0', 'dark_oak_sapling');
    };
    const handler = createPlaceHandler(() => ({ bot, botReady: true }));
    const result = await handler({ x: 0, y: 63, z: 0, item: 'crafting_table' });

    assert.strictEqual(result.success, false);
    assert.strictEqual(result.error, 'requested item crafting_table was not equipped');
    assert.strictEqual(result.equipped_item, 'dark_oak_sapling');
    assert.strictEqual(result.equip_policy_id, 'm4-place-requested-item-equip-v1');
    assert.strictEqual(placeCalls, 0);
    assert.strictEqual(blocks.has('0,64,0'), false);
    console.log('PASS: M4 place handler fails closed before world mutation when exact equip does not hold');
}

async function testM4PlaceHandlerRejectsOccupiedTargetBeforeMutation() {
    for (const occupiedBy of ['dark_oak_log', 'grass_block']) {
        const { bot, blocks, equipCalls } = createShelterBot();
        blocks.set('0,64,0', occupiedBy);
        let placeCalls = 0;
        bot.placeBlock = async () => {
            placeCalls += 1;
        };
        const handler = createPlaceHandler(() => ({ bot, botReady: true }));
        const result = await handler({ x: 0, y: 63, z: 0, item: 'oak_planks' });

        assert.strictEqual(result.success, false);
        assert.strictEqual(result.error, `placement target is occupied by ${occupiedBy}`);
        assert.strictEqual(result.target_occupancy_policy_id, 'm4-place-target-occupancy-v1');
        assert.strictEqual(result.requires_replan, true);
        assert.deepStrictEqual(result.reference_position, { x: 0, y: 63, z: 0 });
        assert.deepStrictEqual(result.placed_position, { x: 0, y: 64, z: 0 });
        assert.strictEqual(result.target_block_before.name, occupiedBy);
        assert.strictEqual(result.target_block_before.solid, true);
        assert.strictEqual(result.required_target_state, 'air_or_replaceable');
        assert.deepStrictEqual(equipCalls, []);
        assert.strictEqual(placeCalls, 0);
        assert.strictEqual(blocks.get('0,64,0'), occupiedBy);
    }
    console.log('PASS: M4 place handler rejects Probe 7 occupied targets before equip or mutation');
}

async function testM4BoundedSealedCellBuildReturnsNineObservedDeltas() {
    const blocks = new Map();
    let plankCount = 10;
    const player = { position: new Vec3(0.5, 64, 0.5) };
    const bot = {
        entity: player,
        inventory: {
            items: () => plankCount > 0 ? [{ name: 'oak_planks', count: plankCount }] : [],
        },
        blockAt(position) {
            const name = blocks.get(positionKey(position)) || 'air';
            return {
                name,
                type: name === 'air' ? 0 : 1,
                boundingBox: name === 'air' ? 'empty' : 'block',
                position: position.clone ? position.clone() : new Vec3(position.x, position.y, position.z),
            };
        },
        async equip() {},
        async dig(block) {
            blocks.delete(positionKey(block.position));
        },
        async placeBlock(reference, face) {
            blocks.set(positionKey(reference.position.plus(face)), 'oak_planks');
            plankCount -= 1;
        },
    };
    blocks.set('0,63,0', 'stone');
    for (const [dx, dz] of [[0, -1], [1, 0], [0, 1], [-1, 0]]) {
        blocks.set(`${dx},63,${dz}`, 'dirt');
    }
    blocks.set('0,64,-1', 'oak_leaves');
    const handler = createBuildShelterCellHandler(
        () => ({ bot, botReady: true }),
        async () => {},
    );
    const result = await handler({
        origin: { x: 0, y: 64, z: 0 },
        material: 'oak_planks',
    });

    assert.strictEqual(result.success, true, JSON.stringify(result));
    assert.strictEqual(result.template_id, 'm4-sealed-cell-v1');
    assert.strictEqual(result.required_block_count, 9);
    assert.strictEqual(result.placed_count, 9);
    assert.strictEqual(result.placement_deltas.length, 9);
    assert.deepStrictEqual(result.removed_positions, [
        { x: 0, y: 64, z: -1 },
        { x: 1, y: 66, z: 0 },
    ]);
    assert.deepStrictEqual(result.temporary_scaffold, { x: 1, y: 66, z: 0 });
    assert.strictEqual(result.preflight.passed, true);
    assert.strictEqual(result.atomicity.passed, true);
    assert.strictEqual(result.atomicity.mode, 'committed_complete_template');
    assert.strictEqual(plankCount, 0);
    assert.strictEqual(blocks.get('0,66,0'), 'oak_planks');
    console.log('PASS: M4 bounded sealed-cell action places nine machine-observed blocks');
}

async function testM4BoundedSealedCellPreflightRejectsProbe16GeometryWithoutMutation() {
    const blocks = new Map();
    let plankCount = 16;
    let placeCalls = 0;
    let digCalls = 0;
    const player = { position: new Vec3(0.5, 64, 0.5) };
    const bot = {
        entity: player,
        inventory: { items: () => [{ name: 'oak_planks', count: plankCount }] },
        blockAt(position) {
            const name = blocks.get(positionKey(position)) || 'air';
            return {
                name,
                type: name === 'air' ? 0 : 1,
                boundingBox: name === 'air' ? 'empty' : 'block',
                position: position.clone ? position.clone() : new Vec3(position.x, position.y, position.z),
            };
        },
        async equip() {},
        async dig(block) {
            digCalls += 1;
            blocks.delete(positionKey(block.position));
        },
        async placeBlock(reference, face) {
            placeCalls += 1;
            blocks.set(positionKey(reference.position.plus(face)), 'oak_planks');
            plankCount -= 1;
        },
    };
    blocks.set('0,64,-2', 'dark_oak_log');
    blocks.set('1,63,0', 'grass_block');
    for (const position of ['3,63,0', '3,63,-1', '4,63,0', '3,63,1', '2,63,0']) {
        blocks.set(position, 'grass_block');
    }
    const beforeBlocks = [...blocks.entries()].sort();
    const handler = createBuildShelterCellHandler(
        () => ({ bot, botReady: true }),
        async () => {},
    );

    const result = await handler({
        origin: { x: 0, y: 64, z: 0 },
        material: 'oak_planks',
    });

    assert.strictEqual(result.success, false, JSON.stringify(result));
    assert.strictEqual(result.error, 'no grounded neighbor exists for sealed-cell placement');
    assert.deepStrictEqual(result.failed_position, { x: 0, y: 64, z: 1 });
    assert.strictEqual(result.placed_count, 0);
    assert.strictEqual(result.preflight.passed, false);
    assert.strictEqual(result.atomicity.passed, true);
    assert.strictEqual(result.atomicity.mode, 'mutation_free_preflight_rejection');
    assert.strictEqual(result.atomicity.mutation_count, 0);
    assert.strictEqual(result.atomicity.inventory_preserved, true);
    assert.strictEqual(result.relocation_required, true);
    assert.deepStrictEqual(result.relocation_origin, { x: 3, y: 64, z: 0 });
    assert.deepStrictEqual(result.relocation_target, { x: 3.5, y: 64, z: 0.5 });
    assert.strictEqual(plankCount, 16);
    assert.strictEqual(placeCalls, 0);
    assert.strictEqual(digCalls, 0);
    assert.deepStrictEqual([...blocks.entries()].sort(), beforeBlocks);
    console.log('PASS: M4 shelter preflight rejects Probe 16 geometry without mutation or material loss');
}

async function testM4BoundedSealedCellRollsBackUnexpectedPartialPlacement() {
    const blocks = new Map();
    let plankCount = 10;
    let placeCalls = 0;
    let digCalls = 0;
    const player = { position: new Vec3(0.5, 64, 0.5) };
    const bot = {
        entity: player,
        inventory: {
            items: () => plankCount > 0 ? [{ name: 'oak_planks', count: plankCount }] : [],
        },
        blockAt(position) {
            const name = blocks.get(positionKey(position)) || 'air';
            return {
                name,
                type: name === 'air' ? 0 : 1,
                boundingBox: name === 'air' ? 'empty' : 'block',
                position: position.clone ? position.clone() : new Vec3(position.x, position.y, position.z),
            };
        },
        async equip() {},
        async dig(block) {
            digCalls += 1;
            if (block.name === 'oak_planks') plankCount += 1;
            blocks.delete(positionKey(block.position));
        },
        async placeBlock(reference, face) {
            placeCalls += 1;
            blocks.set(positionKey(reference.position.plus(face)), 'oak_planks');
            plankCount -= 1;
            if (placeCalls === 4) throw new Error('injected placement fault after server placement');
        },
    };
    blocks.set('0,63,0', 'stone');
    for (const [dx, dz] of [[0, -1], [1, 0], [0, 1], [-1, 0]]) {
        blocks.set(`${dx},63,${dz}`, 'dirt');
    }
    const originalBlocks = [...blocks.entries()].sort();
    const handler = createBuildShelterCellHandler(
        () => ({ bot, botReady: true }),
        async () => {},
    );

    const result = await handler({
        origin: { x: 0, y: 64, z: 0 },
        material: 'oak_planks',
    });

    assert.strictEqual(result.success, false, JSON.stringify(result));
    assert.strictEqual(result.error, 'sealed-cell placement failed: injected placement fault after server placement');
    assert.strictEqual(result.placed_count, 0);
    assert.deepStrictEqual(result.placed_positions, []);
    assert.strictEqual(result.atomicity.passed, true);
    assert.strictEqual(result.atomicity.mode, 'rollback_after_partial_mutation');
    assert.strictEqual(result.atomicity.original_placed_count, 4);
    assert.strictEqual(result.atomicity.inventory_preserved, true);
    assert.strictEqual(result.rollback.removed_positions.length, 4);
    assert.deepStrictEqual(result.rollback.residual_positions, []);
    assert.strictEqual(result.rollback.inventory_recovered, true);
    assert.deepStrictEqual(result.rollback.issues, []);
    assert.strictEqual(plankCount, 10);
    assert.strictEqual(placeCalls, 4);
    assert.strictEqual(digCalls, 4);
    assert.deepStrictEqual([...blocks.entries()].sort(), originalBlocks);

    plankCount = 10;
    placeCalls = 0;
    digCalls = 0;
    bot.dig = async () => {
        digCalls += 1;
        throw new Error('injected rollback fault');
    };
    const failedRollback = await handler({
        origin: { x: 0, y: 64, z: 0 },
        material: 'oak_planks',
    });
    assert.strictEqual(failedRollback.success, false);
    assert.strictEqual(failedRollback.atomicity.passed, false);
    assert.strictEqual(failedRollback.atomicity.residual_placed_count, 4);
    assert.strictEqual(failedRollback.atomicity.inventory_preserved, false);
    assert.strictEqual(failedRollback.rollback.residual_positions.length, 4);
    assert.strictEqual(failedRollback.rollback.issues.length, 5);
    assert.strictEqual(failedRollback.relocation_required, false);
    console.log('PASS: M4 shelter action rolls back unexpected partial placement and restores material');
}

async function main() {
    await testM4ProtocolStatusPinsAutonomousRuntime();
    await testM4ResetUsesNaturalSurvivalStateWithoutFixtures();
    await testBM012ResetUsesTaskBoundDaylightWithoutItemsOrFixtures();
    await testM4ResetRejectsLifecycleWithoutInitialMineflayerSpawn();
    await testM4ShelterSnapshotReturnsCompleteBoundedMachineState();
    await testM4PlaceHandlerReturnsObservedCoordinateDelta();
    await testM4PlaceHandlerRejectsUnequippedRequestedItemBeforeMutation();
    await testM4PlaceHandlerRejectsOccupiedTargetBeforeMutation();
    await testM4BoundedSealedCellBuildReturnsNineObservedDeltas();
    await testM4BoundedSealedCellPreflightRejectsProbe16GeometryWithoutMutation();
    await testM4BoundedSealedCellRollsBackUnexpectedPartialPlacement();
    console.log('\nBot server M4 protocol tests PASSED');
}

main().catch(error => {
    console.error(error);
    process.exit(1);
});
