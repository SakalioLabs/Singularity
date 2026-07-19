'use strict';

const POLICY_ID = 'sp003-runtime-preload-v2';
const CRAFT_SETTLEMENT_DELAY_MS = 1000;
const MOVEMENTS_PATCH_MARK = Symbol.for('singularity.sp003.inventoryPreservingNavigation');
const CREATE_BOT_PATCH_MARK = Symbol.for('singularity.sp003.createBot');
const BOT_CRAFT_PATCH_MARK = Symbol.for('singularity.sp003.craftSettlement');
const pathfinderModule = require('mineflayer-pathfinder');
const mineflayerModule = require('mineflayer');

const waitForSettlement = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function hardenMovements(movements) {
    if (!movements || typeof movements !== 'object') {
        throw new TypeError('SP-003 navigation requires a Movements instance');
    }
    movements.canDig = false;
    movements.allow1by1towers = false;
    movements.scafoldingBlocks = [];
    movements.sp003InventoryPreservationPolicy = POLICY_ID;
    return movements;
}

function wrapCraftSettlement(bot, wait = waitForSettlement) {
    if (!bot || typeof bot !== 'object' || typeof bot.craft !== 'function') {
        throw new TypeError('SP-003 craft settlement requires a mineflayer bot');
    }
    if (typeof wait !== 'function') {
        throw new TypeError('SP-003 craft settlement requires a wait function');
    }
    if (bot[BOT_CRAFT_PATCH_MARK]) return bot;

    const originalCraft = bot.craft;
    bot.craft = async function sp003CraftWithSettlement(...args) {
        const result = await originalCraft.apply(this, args);
        const craftingTable = args[2];
        if (craftingTable !== null && craftingTable !== undefined) {
            await wait(CRAFT_SETTLEMENT_DELAY_MS);
        }
        return result;
    };
    Object.defineProperty(bot, BOT_CRAFT_PATCH_MARK, {
        configurable: false,
        enumerable: false,
        writable: false,
        value: Object.freeze({
            policyId: POLICY_ID,
            delayMs: CRAFT_SETTLEMENT_DELAY_MS,
            originalCraft,
            patchedCraft: bot.craft,
        }),
    });
    return bot;
}

if (!pathfinderModule[MOVEMENTS_PATCH_MARK]) {
    const OriginalMovements = pathfinderModule.Movements;
    class SP003InventoryPreservingMovements extends OriginalMovements {
        constructor(...args) {
            super(...args);
            hardenMovements(this);
        }
    }
    pathfinderModule.Movements = SP003InventoryPreservingMovements;
    pathfinderModule[MOVEMENTS_PATCH_MARK] = Object.freeze({
        policyId: POLICY_ID,
        originalMovements: OriginalMovements,
        patchedMovements: SP003InventoryPreservingMovements,
    });
}

if (!mineflayerModule[CREATE_BOT_PATCH_MARK]) {
    const originalCreateBot = mineflayerModule.createBot;
    mineflayerModule.createBot = function sp003CreateBot(...args) {
        return wrapCraftSettlement(originalCreateBot.apply(this, args));
    };
    mineflayerModule[CREATE_BOT_PATCH_MARK] = Object.freeze({
        policyId: POLICY_ID,
        delayMs: CRAFT_SETTLEMENT_DELAY_MS,
        originalCreateBot,
        patchedCreateBot: mineflayerModule.createBot,
    });
}

module.exports = {
    POLICY_ID,
    CRAFT_SETTLEMENT_DELAY_MS,
    hardenMovements,
    wrapCraftSettlement,
    status: pathfinderModule[MOVEMENTS_PATCH_MARK],
    craftStatus: mineflayerModule[CREATE_BOT_PATCH_MARK],
};
