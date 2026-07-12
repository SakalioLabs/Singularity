'use strict';

const assert = require('assert');
const { Vec3 } = require('vec3');
const {
    M4_PROTOCOL,
    M4_PROTOCOL_SHA256,
    benchmarkProtocolStatus,
    createBenchmarkResetHandler,
    createBuildShelterCellHandler,
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
                bot.time.timeOfDay = 9000;
            } else if (command.startsWith('/weather ')) {
                bot.rainState = 0;
                bot.thunderState = 0;
            } else if (command.startsWith('/difficulty ')) {
                bot.game.difficulty = 'normal';
            }
        },
    };
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
    assert.deepStrictEqual(status.llm, M4_PROTOCOL.llm);
    assert.deepStrictEqual(status.runtime_controls, M4_PROTOCOL.baseline_runtime_controls);
    assert.strictEqual(status.validation_supported, true);
    assert.strictEqual(status.tasks[0].id, 'BM-011');
    console.log('PASS: M4 bridge pins autonomous identities, runtime, and task scope');
}

async function testM4ResetUsesNaturalSurvivalStateWithoutFixtures() {
    const { bot, commands } = createM4Bot();
    const reset = createBenchmarkResetHandler(
        () => ({ bot, botReady: true }),
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
    assert.deepStrictEqual(result.gamerules, M4_PROTOCOL.gamerules);
    assert(commands.includes('/effect clear @s'));
    assert(commands.includes('/gamerule doDaylightCycle true'));
    assert(commands.includes('/gamerule doMobSpawning true'));
    assert(!commands.some(command => command.startsWith('/give ')));
    assert(!commands.some(command => command.includes('minecraft:saturation')));
    assert.strictEqual(result.structure_baseline.blocks, undefined);
    console.log('PASS: M4 reset proves empty natural survival state without fixtures or granted items');
}

function positionKey(position) {
    return `${Number(position.x)},${Number(position.y)},${Number(position.z)}`;
}

function createShelterBot() {
    const blocks = new Map();
    const player = { position: new Vec3(0.5, 64, 0.5) };
    const zombie = { name: 'zombie', type: 'mob', position: new Vec3(4, 64, 0) };
    const bot = {
        entity: player,
        entities: { player, 17: zombie },
        blockAt(position) {
            const name = blocks.get(positionKey(position)) || 'air';
            return {
                name,
                type: name === 'air' ? 0 : 1,
                boundingBox: name === 'air' ? 'empty' : 'block',
                position: position.clone ? position.clone() : new Vec3(position.x, position.y, position.z),
            };
        },
        async placeBlock(reference, face) {
            const target = reference.position.plus(face);
            blocks.set(positionKey(target), 'oak_planks');
        },
    };
    blocks.set('0,63,0', 'stone');
    for (const [dx, dz] of [[0, -1], [1, 0], [0, 1], [-1, 0]]) {
        blocks.set(`${dx},64,${dz}`, 'oak_planks');
        blocks.set(`${dx},65,${dz}`, 'oak_planks');
    }
    blocks.set('0,66,0', 'oak_planks');
    return { bot, blocks };
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
    const { bot, blocks } = createShelterBot();
    blocks.delete('0,64,0');
    const handler = createPlaceHandler(() => ({ bot, botReady: true }));
    const missing = await handler({ item: 'oak_planks' });
    assert.strictEqual(missing.success, false);
    assert.match(missing.error, /finite reference coordinates/);
    const result = await handler({ x: 0, y: 63, z: 0, item: 'oak_planks' });

    assert.strictEqual(result.success, true);
    assert.deepStrictEqual(result.placed_position, { x: 0, y: 64, z: 0 });
    assert.strictEqual(result.target_block_before.name, 'air');
    assert.strictEqual(result.target_block_after.name, 'oak_planks');
    assert.strictEqual(result.target_block_after.solid, true);
    console.log('PASS: M4 place evidence binds the requested action to an observed block delta');
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
    assert.strictEqual(plankCount, 0);
    assert.strictEqual(blocks.get('0,66,0'), 'oak_planks');
    console.log('PASS: M4 bounded sealed-cell action places nine machine-observed blocks');
}

async function main() {
    await testM4ProtocolStatusPinsAutonomousRuntime();
    await testM4ResetUsesNaturalSurvivalStateWithoutFixtures();
    await testM4ShelterSnapshotReturnsCompleteBoundedMachineState();
    await testM4PlaceHandlerReturnsObservedCoordinateDelta();
    await testM4BoundedSealedCellBuildReturnsNineObservedDeltas();
    console.log('\nBot server M4 protocol tests PASSED');
}

main().catch(error => {
    console.error(error);
    process.exit(1);
});
