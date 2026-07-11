'use strict';

const assert = require('assert');
const { Vec3 } = require('vec3');
const {
    M2_PROTOCOL,
    M2_PROTOCOL_SHA256,
    benchmarkProtocolStatus,
    createBuildShelterHandler,
    createBenchmarkResetHandler,
    createBenchmarkVerifyHandler,
    createCraftHandler,
    prioritizeNearbyBlocks,
} = require('../src/bot/bot_server');

const runtime = {
    seed: '12345',
    episode_id: 'offline-m2-contract-test',
    level_name: 'offline-m2-contract-test_bm010',
    server_jar_sha256: M2_PROTOCOL.server_jar_sha256,
};

function positionKey(x, y, z) {
    return `${Number(x)},${Number(y)},${Number(z)}`;
}

function createM2Bot() {
    const spawnPoint = new Vec3(10, 64, 10);
    const blocks = new Map();
    let items = [{ name: 'dirt', count: 4 }];
    const commands = [];
    const bot = {
        spawnPoint,
        entity: { position: new Vec3(18, 70, 18), equipment: [] },
        health: 7,
        food: 5,
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
            const name = blocks.get(positionKey(position.x, position.y, position.z)) || 'air';
            return { name, type: name === 'air' ? 0 : 1, position };
        },
        chat(command) {
            commands.push(command);
            if (command.startsWith('/execute in minecraft:overworld run tp')) {
                bot.entity.position = spawnPoint.clone();
            } else if (command.startsWith('/gamemode ')) {
                bot.game.gameMode = 'survival';
            } else if (command === '/clear @s') {
                items = [];
            } else if (command.startsWith('/setblock ')) {
                const match = command.match(/^\/setblock\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+minecraft:([a-z0-9_]+)$/);
                if (match) blocks.set(positionKey(match[1], match[2], match[3]), match[4]);
            } else if (command.startsWith('/fill ')) {
                const match = command.match(/^\/fill\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+minecraft:([a-z0-9_]+)$/);
                if (match) {
                    const values = match.slice(1, 7).map(Number);
                    const [x1, y1, z1, x2, y2, z2] = values;
                    for (let x = Math.min(x1, x2); x <= Math.max(x1, x2); x++) {
                        for (let y = Math.min(y1, y2); y <= Math.max(y1, y2); y++) {
                            for (let z = Math.min(z1, z2); z <= Math.max(z1, z2); z++) {
                                blocks.set(positionKey(x, y, z), match[7]);
                            }
                        }
                    }
                }
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
    return { bot, blocks, commands };
}

async function testM2ProtocolStatusIsIndependentFromM1() {
    const { bot } = createM2Bot();
    const status = benchmarkProtocolStatus(bot, runtime, 'm2-fixed-v1');
    assert.strictEqual(status.configured, true);
    assert.strictEqual(status.profile, 'm2-fixed-v1');
    assert.strictEqual(status.protocol_sha256, M2_PROTOCOL_SHA256);
    assert.strictEqual(status.planner_id, 'llm-root-planner-v1');
    assert.strictEqual(status.llm.base_url, 'https://opencode.ai/zen/go/v1');
    assert.strictEqual(status.llm.model, 'deepseek-v4-flash');
    assert.strictEqual(M2_PROTOCOL.deadline_policy.id, 'm2-hard-total-deadline-v1');
    assert.strictEqual(M2_PROTOCOL.deadline_policy.planner_max_retries, 0);
    assert.strictEqual(status.validation_supported, true);
    assert.strictEqual(status.tasks.length, 5);
    assert.strictEqual(status.tasks[4].goal, 'Build a simple 5x5 shelter');
    console.log('PASS: M2 bridge reports its own fixed protocol and exact tasks');
}

async function testNearbyBlockSelectionPreservesRareGroundedTargets() {
    const blocks = [];
    for (let index = 0; index < 60; index++) {
        blocks.push({
            name: 'dark_oak_leaves',
            distance: 1 + index * 0.01,
            position: { x: index, y: 64, z: 0 },
        });
    }
    blocks.push({ name: 'crafting_table', distance: 1.5, position: { x: 1, y: 64, z: 1 } });
    blocks.push({ name: 'stone', distance: 4, position: { x: 4, y: 64, z: 0 } });

    const selected = prioritizeNearbyBlocks(blocks, 50);
    assert.strictEqual(selected.length, 50);
    assert.deepStrictEqual(selected.slice(0, 3).map(block => block.name), [
        'dark_oak_leaves',
        'crafting_table',
        'stone',
    ]);
    assert.strictEqual(selected.filter(block => block.name === 'stone').length, 1);
    console.log('PASS: nearby-block selection keeps rare grounded targets inside the fixed context budget');
}

async function testCraftHandlerRejectsTransientInventoryAndRetries() {
    let items = [
        { name: 'oak_planks', count: 3 },
        { name: 'stick', count: 2 },
    ];
    let craftAttempts = 0;
    let waitsInAttempt = 0;
    const waitDurations = [];
    const bot = {
        version: '1.20.4',
        entity: { position: new Vec3(0, 64, 0) },
        inventory: { items: () => items },
        findBlock: () => ({ position: new Vec3(1, 64, 0) }),
        recipesFor: () => [{ result: { count: 1 } }],
        async craft() {
            craftAttempts += 1;
            waitsInAttempt = 0;
            items = [{ name: 'wooden_pickaxe', count: 1 }];
        },
    };
    const wait = async (duration) => {
        waitDurations.push(duration);
        waitsInAttempt += 1;
        if (craftAttempts === 1 && waitsInAttempt === 3) {
            items = [
                { name: 'oak_planks', count: 3 },
                { name: 'stick', count: 2 },
            ];
        }
    };
    const handler = createCraftHandler(
        () => ({ bot, botReady: true }),
        wait,
    );
    const result = await handler({ item: 'wooden_pickaxe', count: 1 });
    assert.strictEqual(result.success, true);
    assert.strictEqual(craftAttempts, 2);
    assert.strictEqual(result.craft_attempts, 2);
    assert.strictEqual(result.craft_retry_count, 1);
    assert.strictEqual(result.stable_ms, 800);
    assert.deepStrictEqual(result.inventory_delta, { wooden_pickaxe: 1 });
    assert.strictEqual(result.attempts[0].success, false);
    assert.strictEqual(result.attempts[1].success, true);
    assert(waitDurations.includes(3000));
    console.log('PASS: craft handler ignores rolled-back inventory ghosts and records a bounded retry');
}

async function testM2ResetBuildsFixturesAndRecordsEmptyShelterBaseline() {
    const { bot, commands } = createM2Bot();
    const reset = createBenchmarkResetHandler(
        () => ({ bot, botReady: true }),
        async () => {},
        runtime,
    );
    const bm007 = await reset({ task_id: 'BM-007' });
    assert.strictEqual(bm007.success, true);
    assert.strictEqual(bm007.profile, 'm2-fixed-v1');
    assert.deepStrictEqual(bm007.after_state.inventory, { oak_log: 2 });
    assert.deepStrictEqual(
        bm007.after_state.fixture_blocks.map(item => item.name),
        ['crafting_table', 'stone', 'stone', 'stone'],
    );

    const bm010 = await reset({ task_id: 'BM-010' });
    assert.strictEqual(bm010.success, true);
    assert.deepStrictEqual(bm010.after_state.inventory, { cobblestone: 64 });
    assert.strictEqual(bm010.structure_baseline.blocks.length, 75);
    assert(bm010.structure_baseline.blocks.every(block => block.name === 'air'));
    assert(commands.some(command => command.includes('minecraft:stone')));
    assert(commands.some(command => command.startsWith('/fill ')));
    console.log('PASS: M2 reset proves exact fixtures and captures an empty construction baseline');
}

async function testM2VerificationReturnsObservedStateWithoutDeclaringGoalSuccess() {
    const { bot, blocks } = createM2Bot();
    const reset = createBenchmarkResetHandler(
        () => ({ bot, botReady: true }),
        async () => {},
        runtime,
    );
    await reset({ task_id: 'BM-010' });

    const origin = { x: 13, y: 64, z: 13 };
    for (let x = origin.x; x < origin.x + 5; x++) {
        for (let z = origin.z; z < origin.z + 5; z++) {
            const perimeter = x === origin.x || x === origin.x + 4 || z === origin.z || z === origin.z + 4;
            if (perimeter) {
                for (const y of [origin.y, origin.y + 1]) {
                    if (!(x === origin.x + 2 && z === origin.z)) {
                        blocks.set(positionKey(x, y, z), 'cobblestone');
                    }
                }
            }
            blocks.set(positionKey(x, origin.y + 2, z), 'cobblestone');
        }
    }
    bot.entity.position = new Vec3(15.5, 64, 15.5);
    const verify = createBenchmarkVerifyHandler(
        () => ({ bot, botReady: true }),
        runtime,
    );
    const evidence = await verify({ task_id: 'BM-010' });
    assert.strictEqual(evidence.success, true);
    assert.strictEqual(evidence.goal_completed, undefined);
    assert.strictEqual(evidence.structure_post.blocks.length, 75);
    assert.deepStrictEqual(evidence.player_position, { x: 15.5, y: 64, z: 15.5 });
    console.log('PASS: M2 verification emits raw world evidence and no self-certified success');
}

async function testBoundedShelterHandlerPlacesTheFixedTemplate() {
    const { bot, blocks } = createM2Bot();
    const reset = createBenchmarkResetHandler(
        () => ({ bot, botReady: true }),
        async () => {},
        runtime,
    );
    await reset({ task_id: 'BM-010' });
    bot.equip = async () => {};
    bot.pathfinder = {
        async goto(goal) {
            bot.entity.position = new Vec3(
                Number(goal.x ?? bot.entity.position.x),
                Number(goal.y ?? 64),
                Number(goal.z ?? bot.entity.position.z),
            );
        },
        stop() {},
    };
    bot.placeBlock = async (reference, face) => {
        const target = reference.position.plus(face);
        blocks.set(positionKey(target.x, target.y, target.z), 'cobblestone');
        const stack = bot.inventory.items().find(item => item.name === 'cobblestone');
        stack.count -= 1;
    };
    const handler = createBuildShelterHandler(
        () => ({ bot, botReady: true }),
        async () => {},
    );
    const result = await handler({
        origin: { x: 13, y: 64, z: 13 },
        material: 'cobblestone',
    });
    assert.strictEqual(result.success, true);
    assert.strictEqual(result.required_block_count, 55);
    assert.strictEqual(result.wall_block_count, 30);
    assert.strictEqual(result.roof_block_count, 25);
    assert.strictEqual(result.placed_count, 55);
    assert.strictEqual(result.inventory_after.cobblestone, 9);
    assert.strictEqual(blocks.get(positionKey(15, 64, 13)), 'air');
    assert.strictEqual(blocks.get(positionKey(15, 65, 13)), 'air');
    assert.strictEqual(blocks.get(positionKey(15, 66, 15)), 'cobblestone');
    console.log('PASS: Bounded shelter handler performs 55 real placement calls and preserves its entrance');
}

async function main() {
    await testM2ProtocolStatusIsIndependentFromM1();
    await testNearbyBlockSelectionPreservesRareGroundedTargets();
    await testCraftHandlerRejectsTransientInventoryAndRetries();
    await testM2ResetBuildsFixturesAndRecordsEmptyShelterBaseline();
    await testM2VerificationReturnsObservedStateWithoutDeclaringGoalSuccess();
    await testBoundedShelterHandlerPlacesTheFixedTemplate();
    console.log('\nBot server M2 protocol tests PASSED');
}

main().catch(error => {
    console.error(error);
    process.exit(1);
});
