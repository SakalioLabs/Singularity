const assert = require('assert');
const { EventEmitter } = require('events');

const pathfinderModule = require('mineflayer-pathfinder');
const mineflayerModule = require('mineflayer');
const OriginalMovements = pathfinderModule.Movements;
const OriginalCreateBot = mineflayerModule.createBot;
const preload = require('../src/bot/sp003_inventory_preserving_navigation');

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
