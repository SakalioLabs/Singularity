const assert = require('assert');
const { EventEmitter } = require('events');
const { Vec3 } = require('vec3');

const pathfinderModule = require('mineflayer-pathfinder');
const mineflayerModule = require('mineflayer');
const OriginalMovements = pathfinderModule.Movements;
const OriginalGoalNear = pathfinderModule.goals.GoalNear;
const OriginalGoalNearXZ = pathfinderModule.goals.GoalNearXZ;
const OriginalCreateBot = mineflayerModule.createBot;
const preload = require('../src/bot/sp003_inventory_preserving_navigation');
const { createDigHandler } = require('../src/bot/bot_server');

function testPreloadReplacesOnlyTheProcessLocalMovementsConstructor() {
    assert.strictEqual(preload.POLICY_ID, 'sp003-runtime-preload-v2');
    assert.notStrictEqual(pathfinderModule.Movements, OriginalMovements);
    assert.strictEqual(preload.status.originalMovements, OriginalMovements);
    assert.strictEqual(preload.status.patchedMovements, pathfinderModule.Movements);
    assert.strictEqual(
        require('../src/bot/sp003_inventory_preserving_navigation').status,
        preload.status,
    );
    console.log('PASS: SP-003 preload patches Movements once within its Node process');
}

function testMovementHardeningDisablesHiddenWorldMutation() {
    const movements = {
        canDig: true,
        allow1by1towers: true,
        scafoldingBlocks: [1, 4],
        allowParkour: true,
        allowSprinting: true,
    };

    const hardened = preload.hardenMovements(movements);

    assert.strictEqual(hardened, movements);
    assert.strictEqual(hardened.canDig, false);
    assert.strictEqual(hardened.allow1by1towers, false);
    assert.deepStrictEqual(hardened.scafoldingBlocks, []);
    assert.strictEqual(hardened.allowParkour, true);
    assert.strictEqual(hardened.allowSprinting, true);
    assert.strictEqual(
        hardened.sp003InventoryPreservationPolicy,
        'sp003-runtime-preload-v2',
    );
    assert.throws(() => preload.hardenMovements(null), /Movements instance/);
    console.log('PASS: SP-003 movement hardening forbids digging and scaffolding');
}

function testPreloadTightensOnlyUnitRangeThreeDimensionalGoals() {
    assert.strictEqual(
        preload.EXACT_UNIT_GOAL_NEAR_POLICY_ID,
        'sp003-exact-unit-goal-near-v1',
    );
    assert.notStrictEqual(pathfinderModule.goals.GoalNear, OriginalGoalNear);
    assert.strictEqual(pathfinderModule.goals.GoalNearXZ, OriginalGoalNearXZ);
    assert.strictEqual(preload.goalStatus.originalGoalNear, OriginalGoalNear);
    assert.strictEqual(preload.goalStatus.patchedGoalNear, pathfinderModule.goals.GoalNear);

    const unit = new pathfinderModule.goals.GoalNear(125, 139, -37, 1);
    assert.strictEqual(unit.rangeSq, 0);
    assert.strictEqual(unit.isEnd({ x: 124, y: 139, z: -37 }), false);
    assert.deepStrictEqual(unit.sp003ExactUnitGoalNear, {
        policyId: 'sp003-exact-unit-goal-near-v1',
        requestedRange: 1,
        effectiveRange: 0,
        transformed: true,
    });

    const nonUnit = new pathfinderModule.goals.GoalNear(125, 139, -37, 2);
    assert.strictEqual(nonUnit.rangeSq, 4);
    assert.strictEqual(nonUnit.isEnd({ x: 124, y: 139, z: -37 }), true);
    assert.strictEqual(nonUnit.sp003ExactUnitGoalNear.transformed, false);
    assert.strictEqual(preload.exactUnitGoalNearRange(0), 0);
    assert.strictEqual(preload.exactUnitGoalNearRange(2), 2);
    console.log('PASS: SP-003 preload tightens only unit-range GoalNear instances');
}

async function testPhase97PickupGeometryUsesExactGoalAndObservedInventoryDelta() {
    const target = new Vec3(125, 139, -37);
    const drop = {
        id: 1021,
        name: 'item',
        position: new Vec3(125.125, 139, -36.792724609375),
        getDroppedItem: () => ({ name: 'cobblestone' }),
    };
    let removed = false;
    let items = [
        { name: 'wooden_pickaxe', count: 1 },
        { name: 'cobblestone', count: 1 },
    ];
    let clockMs = 0;
    const goals = [];
    const bot = {
        version: '1.20.4',
        entity: {
            position: new Vec3(
                124.43412237234119,
                140,
                -36.48877523049243,
            ),
        },
        entities: { [drop.id]: drop },
        inventory: { items: () => items },
        blockAt(position) {
            if (position.x === target.x && position.y === target.y && position.z === target.z) {
                return removed
                    ? { name: 'air', type: 0, boundingBox: 'empty', position: target }
                    : { name: 'stone', type: 1, boundingBox: 'block', drops: [35], position: target };
            }
            return { name: 'air', type: 0, boundingBox: 'empty', position };
        },
        async dig() {
            removed = true;
        },
        pathfinder: {
            async goto(goal) {
                goals.push(goal);
                bot.entity.position = drop.position.clone();
                items = [...items, { name: 'cobblestone', count: 1 }];
                clockMs += 500;
            },
            stop() {},
        },
    };
    const handler = createDigHandler(
        () => ({ bot, botReady: true }),
        async (ms) => { clockMs += Number(ms) || 0; },
        { monotonicMs: () => clockMs },
    );

    const result = await handler({
        x: target.x,
        y: target.y,
        z: target.z,
        require_pickup: true,
    });

    assert.strictEqual(result.success, true);
    assert.strictEqual(result.pickup_observed, true);
    assert.deepStrictEqual(result.pickup_inventory_delta, { cobblestone: 1 });
    assert.strictEqual(goals.length, 1);
    assert.strictEqual(goals[0].rangeSq, 0);
    assert.strictEqual(goals[0].sp003ExactUnitGoalNear.requestedRange, 1);
    assert.strictEqual(result.pickup_collection.completion_grounded_by, 'inventory_delta');
    assert.strictEqual(result.dig_postcondition.passed, true);
    console.log('PASS: Phase97 pickup geometry uses an exact goal and real inventory delta');
}

function testPreloadPatchesCreateBotOnceWithinItsNodeProcess() {
    assert.strictEqual(preload.CRAFT_SETTLEMENT_DELAY_MS, 1000);
    assert.notStrictEqual(mineflayerModule.createBot, OriginalCreateBot);
    assert.strictEqual(preload.craftStatus.originalCreateBot, OriginalCreateBot);
    assert.strictEqual(preload.craftStatus.patchedCreateBot, mineflayerModule.createBot);
    assert.strictEqual(preload.craftStatus.installationEvent, 'inject_allowed');
    assert.strictEqual(preload.craftStatus.synchronousCraftRequired, false);
    assert.strictEqual(
        require('../src/bot/sp003_inventory_preserving_navigation').craftStatus,
        preload.craftStatus,
    );
    console.log('PASS: SP-003 preload patches createBot once within its Node process');
}

async function testCraftSettlementWaitsForMineflayerPluginInjection() {
    const calls = [];
    const waits = [];
    const bot = new EventEmitter();
    bot.once('inject_allowed', () => {
        bot.craft = async (...args) => {
            calls.push(args);
            return { crafted: args[0] };
        };
    });

    assert.strictEqual(preload.installCraftSettlement(bot, async (ms) => waits.push(ms)), bot);
    assert.strictEqual(preload.installCraftSettlement(bot, async () => {}), bot);
    assert.strictEqual(bot.listenerCount('inject_allowed'), 2);
    assert.strictEqual(bot.craft, undefined);

    bot.emit('inject_allowed');
    assert.strictEqual(typeof bot.craft, 'function');
    assert.deepStrictEqual(
        await bot.craft('wooden_pickaxe', 1, { name: 'crafting_table' }),
        { crafted: 'wooden_pickaxe' },
    );
    assert.strictEqual(calls.length, 1);
    assert.deepStrictEqual(waits, [1000]);
    console.log('PASS: SP-003 craft settlement waits for Mineflayer plugin injection');
}

function testCraftSettlementFailsClosedWhenCraftPluginIsMissingAfterInjection() {
    const bot = new EventEmitter();
    preload.installCraftSettlement(bot, async () => {});
    assert.throws(() => bot.emit('inject_allowed'), /mineflayer bot/);
    assert.throws(
        () => preload.installCraftSettlement({}),
        /event-capable mineflayer bot/,
    );
    assert.throws(
        () => preload.installCraftSettlement(new EventEmitter(), null),
        /wait function/,
    );
    console.log('PASS: SP-003 deferred craft settlement fails closed without craft plugin');
}

async function testRealMineflayerCreateBotInstallsAfterPluginInjection() {
    const client = new EventEmitter();
    Object.assign(client, {
        version: '1.20.4',
        wait_connect: false,
        write() {},
        writeChannel() {},
        registerChannel() {},
        chat() {},
        end() {},
    });

    const bot = mineflayerModule.createBot({
        username: 'SP003LifecycleSmoke',
        version: '1.20.4',
        client,
        logErrors: false,
    });
    assert.strictEqual(bot.craft, undefined);
    await new Promise((resolve, reject) => {
        const timeout = setTimeout(
            () => reject(new Error('Mineflayer did not emit inject_allowed')),
            1000,
        );
        bot.once('inject_allowed', () => setImmediate(() => {
            clearTimeout(timeout);
            resolve();
        }));
    });
    assert.strictEqual(typeof bot.craft, 'function');
    assert.strictEqual(bot.craft.name, 'sp003CraftWithSettlement');
    console.log('PASS: real Mineflayer createBot installs settlement after plugin injection');
}

async function testCraftSettlementIsBoundedToInteractiveCrafts() {
    const calls = [];
    const waits = [];
    const bot = {
        async craft(...args) {
            calls.push(args);
            return { crafted: args[0] };
        },
    };
    const wait = async (ms) => waits.push(ms);

    assert.strictEqual(preload.wrapCraftSettlement(bot, wait), bot);
    assert.strictEqual(preload.wrapCraftSettlement(bot, wait), bot);
    assert.deepStrictEqual(await bot.craft('planks', 1, null), { crafted: 'planks' });
    assert.deepStrictEqual(waits, []);
    const table = { name: 'crafting_table' };
    assert.deepStrictEqual(
        await bot.craft('wooden_pickaxe', 1, table),
        { crafted: 'wooden_pickaxe' },
    );
    assert.strictEqual(calls.length, 2);
    assert.deepStrictEqual(waits, [1000]);
    console.log('PASS: SP-003 interactive craft settles once without a backend retry');
}

async function testCraftFailurePropagatesWithoutSettlementDelay() {
    const waits = [];
    const error = new Error('craft failed');
    const bot = {
        async craft() {
            throw error;
        },
    };
    preload.wrapCraftSettlement(bot, async (ms) => waits.push(ms));

    await assert.rejects(
        bot.craft('wooden_pickaxe', 1, { name: 'crafting_table' }),
        (caught) => caught === error,
    );
    assert.deepStrictEqual(waits, []);
    assert.throws(() => preload.wrapCraftSettlement(null), /mineflayer bot/);
    assert.throws(
        () => preload.wrapCraftSettlement({ craft() {} }, null),
        /wait function/,
    );
    console.log('PASS: SP-003 craft failures propagate without hidden retries or delay');
}

async function main() {
    testPreloadReplacesOnlyTheProcessLocalMovementsConstructor();
    testMovementHardeningDisablesHiddenWorldMutation();
    testPreloadTightensOnlyUnitRangeThreeDimensionalGoals();
    await testPhase97PickupGeometryUsesExactGoalAndObservedInventoryDelta();
    testPreloadPatchesCreateBotOnceWithinItsNodeProcess();
    await testCraftSettlementWaitsForMineflayerPluginInjection();
    testCraftSettlementFailsClosedWhenCraftPluginIsMissingAfterInjection();
    await testRealMineflayerCreateBotInstallsAfterPluginInjection();
    await testCraftSettlementIsBoundedToInteractiveCrafts();
    await testCraftFailurePropagatesWithoutSettlementDelay();
    console.log('\nSP-003 runtime preload tests PASSED');
}

main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
