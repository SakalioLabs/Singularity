'use strict';

const assert = require('assert');
const { Vec3 } = require('vec3');
const {
    SMELT_OUTPUT_SETTLEMENT_POLICY_ID,
    createSmeltHandler,
} = require('../src/bot/sp004_bot_server');

function removeInventory(items, name, count) {
    const stack = items.find((item) => item.name === name);
    assert(stack && stack.count >= count);
    stack.count -= count;
    return items.filter((item) => item.count > 0);
}

function createSmeltFixture(options = {}) {
    let items = (options.items || [
        { name: 'raw_iron', count: 3 },
        { name: 'coal', count: 1 },
    ]).map((item) => ({ ...item }));
    let inputSlot = options.inputSlot || null;
    let fuelSlot = options.fuelSlot || null;
    let outputSlot = options.outputSlot || null;
    let openCount = 0;
    let putInputCount = 0;
    let putFuelCount = 0;
    let takeOutputCount = 0;
    let closeCount = 0;
    const furnaceBlock = {
        name: 'furnace',
        type: 61,
        position: new Vec3(1, 64, 0),
    };
    const furnace = {
        inputItem: () => inputSlot,
        fuelItem: () => fuelSlot,
        outputItem: () => outputSlot,
        async putInput(_type, _metadata, count) {
            putInputCount += 1;
            items = removeInventory(items, 'raw_iron', count);
            inputSlot = { name: 'raw_iron', count };
        },
        async putFuel(_type, _metadata, count) {
            putFuelCount += 1;
            items = removeInventory(items, 'coal', count);
            fuelSlot = { name: 'coal', count };
        },
        async takeOutput() {
            takeOutputCount += 1;
            const taken = outputSlot;
            outputSlot = null;
            const existing = items.find((item) => item.name === taken.name);
            if (existing) existing.count += taken.count;
            else items.push({ name: taken.name, count: taken.count });
            return taken;
        },
        close() {
            closeCount += 1;
        },
    };
    const bot = {
        version: '1.20.4',
        entity: { position: new Vec3(0, 64, 0) },
        inventory: { items: () => items },
        findBlock: () => options.furnaceMissing ? null : furnaceBlock,
        blockAt: () => options.furnaceMissing ? null : furnaceBlock,
        async openFurnace() {
            openCount += 1;
            return furnace;
        },
    };
    return {
        bot,
        furnace,
        setCompletedOutput(count = 3) {
            inputSlot = null;
            fuelSlot = null;
            outputSlot = { name: 'iron_ingot', count };
        },
        counters() {
            return {
                openCount,
                putInputCount,
                putFuelCount,
                takeOutputCount,
                closeCount,
            };
        },
    };
}

async function testSmeltHandlerCollectsThreeVerifiedIronIngots() {
    const fixture = createSmeltFixture();
    let waits = 0;
    const handler = createSmeltHandler(
        () => ({ bot: fixture.bot, botReady: true }),
        async () => {
            waits += 1;
            if (waits === 2) fixture.setCompletedOutput(3);
        },
    );

    const result = await handler({
        item: 'iron_ingot',
        input: 'raw_iron',
        fuel: 'coal',
        count: 3,
        timeout_ms: 35000,
    });

    assert.strictEqual(result.success, true);
    assert.strictEqual(result.policy_id, SMELT_OUTPUT_SETTLEMENT_POLICY_ID);
    assert.strictEqual(result.smelt_attempts, 1);
    assert.strictEqual(result.smelt_retry_count, 0);
    assert.strictEqual(result.automatic_retry, false);
    assert.strictEqual(result.output_settled, true);
    assert.strictEqual(result.output_collected_count, 3);
    assert.strictEqual(result.output_inventory_increase, 3);
    assert.strictEqual(result.input_inventory_decrease, 3);
    assert.strictEqual(result.fuel_inventory_decrease, 1);
    assert.deepStrictEqual(result.inventory_signed_delta, {
        coal: -1,
        iron_ingot: 3,
        raw_iron: -3,
    });
    assert.deepStrictEqual(result.furnace_position, { x: 1, y: 64, z: 0 });
    assert.strictEqual(result.furnace_closed, true);
    assert.deepStrictEqual(fixture.counters(), {
        openCount: 1,
        putInputCount: 1,
        putFuelCount: 1,
        takeOutputCount: 1,
        closeCount: 1,
    });
    console.log('PASS: smelt handler collects three machine-settled iron ingots');
}

async function testSmeltHandlerRejectsMissingMaterialsBeforeOpeningFurnace() {
    const fixture = createSmeltFixture({
        items: [
            { name: 'raw_iron', count: 2 },
            { name: 'coal', count: 1 },
        ],
    });
    const handler = createSmeltHandler(
        () => ({ bot: fixture.bot, botReady: true }),
        async () => {},
    );

    const result = await handler({ item: 'iron_ingot', count: 3 });

    assert.strictEqual(result.success, false);
    assert.match(result.error, /Insufficient raw_iron/);
    assert.strictEqual(result.fail_closed_before_furnace_open, true);
    assert.deepStrictEqual(fixture.counters(), {
        openCount: 0,
        putInputCount: 0,
        putFuelCount: 0,
        takeOutputCount: 0,
        closeCount: 0,
    });
    console.log('PASS: smelt handler rejects missing input before furnace mutation');
}

async function testSmeltHandlerRequiresObservedFurnace() {
    const fixture = createSmeltFixture({ furnaceMissing: true });
    const handler = createSmeltHandler(
        () => ({ bot: fixture.bot, botReady: true }),
        async () => {},
    );

    const result = await handler({ item: 'iron_ingot', count: 3 });

    assert.strictEqual(result.success, false);
    assert.match(result.error, /No observed furnace/);
    assert.strictEqual(result.fail_closed_before_furnace_open, true);
    assert.strictEqual(fixture.counters().openCount, 0);
    console.log('PASS: smelt handler requires a machine-observed nearby furnace');
}

async function testSmeltHandlerRejectsOccupiedFurnaceBeforeDepositing() {
    const fixture = createSmeltFixture({
        outputSlot: { name: 'iron_ingot', count: 1 },
    });
    const handler = createSmeltHandler(
        () => ({ bot: fixture.bot, botReady: true }),
        async () => {},
    );

    const result = await handler({ item: 'iron_ingot', count: 3 });

    assert.strictEqual(result.success, false);
    assert.match(result.error, /slots must be empty/);
    assert.strictEqual(result.fail_closed_before_furnace_mutation, true);
    assert.strictEqual(result.furnace_closed, true);
    assert.deepStrictEqual(fixture.counters(), {
        openCount: 1,
        putInputCount: 0,
        putFuelCount: 0,
        takeOutputCount: 0,
        closeCount: 1,
    });
    console.log('PASS: smelt handler refuses to mix audited output with occupied slots');
}

async function testSmeltHandlerTimesOutWithoutRetryOrFalseSuccess() {
    const fixture = createSmeltFixture();
    const handler = createSmeltHandler(
        () => ({ bot: fixture.bot, botReady: true }),
        async () => {},
    );

    const result = await handler({
        item: 'iron_ingot',
        count: 3,
        timeout_ms: 500,
    });

    assert.strictEqual(result.success, false);
    assert.match(result.error, /Timed out/);
    assert.strictEqual(result.smelt_attempts, 1);
    assert.strictEqual(result.smelt_retry_count, 0);
    assert.strictEqual(result.automatic_retry, false);
    assert.strictEqual(result.furnace_mutated, true);
    assert.strictEqual(result.furnace_closed, true);
    assert.deepStrictEqual(fixture.counters(), {
        openCount: 1,
        putInputCount: 1,
        putFuelCount: 1,
        takeOutputCount: 0,
        closeCount: 1,
    });
    console.log('PASS: smelt timeout fails once without retry or false success');
}

async function main() {
    await testSmeltHandlerCollectsThreeVerifiedIronIngots();
    await testSmeltHandlerRejectsMissingMaterialsBeforeOpeningFurnace();
    await testSmeltHandlerRequiresObservedFurnace();
    await testSmeltHandlerRejectsOccupiedFurnaceBeforeDepositing();
    await testSmeltHandlerTimesOutWithoutRetryOrFalseSuccess();
    console.log('\nBot server smelt tests PASSED');
}

main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
