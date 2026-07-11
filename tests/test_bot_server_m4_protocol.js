'use strict';

const assert = require('assert');
const { Vec3 } = require('vec3');
const {
    M4_PROTOCOL,
    M4_PROTOCOL_SHA256,
    benchmarkProtocolStatus,
    createBenchmarkResetHandler,
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

    assert.strictEqual(result.success, true);
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

async function main() {
    await testM4ProtocolStatusPinsAutonomousRuntime();
    await testM4ResetUsesNaturalSurvivalStateWithoutFixtures();
    console.log('\nBot server M4 protocol tests PASSED');
}

main().catch(error => {
    console.error(error);
    process.exit(1);
});
