'use strict';

const POLICY_ID = 'sp003-runtime-preload-v2';
const CRAFT_SETTLEMENT_DELAY_MS = 1000;
const EXACT_UNIT_GOAL_NEAR_POLICY_ID = 'sp003-exact-unit-goal-near-v1';
const EXACT_UNIT_GOAL_NEAR_REQUESTED_RANGE = 1;
const EXACT_UNIT_GOAL_NEAR_EFFECTIVE_RANGE = 0;
const MOVEMENTS_PATCH_MARK = Symbol.for('singularity.sp003.inventoryPreservingNavigation');
const GOAL_NEAR_PATCH_MARK = Symbol.for('singularity.sp003.exactUnitGoalNear');
const CREATE_BOT_PATCH_MARK = Symbol.for('singularity.sp003.createBot');
const BOT_CRAFT_INSTALL_MARK = Symbol.for('singularity.sp003.craftSettlementInstall');
const BOT_CRAFT_PATCH_MARK = Symbol.for('singularity.sp003.craftSettlement');
const pathfinderModule = require('mineflayer-pathfinder');
const mineflayerModule = require('mineflayer');

const waitForSettlement = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function exactUnitGoalNearRange(range) {
    return Number(range) === EXACT_UNIT_GOAL_NEAR_REQUESTED_RANGE
        ? EXACT_UNIT_GOAL_NEAR_EFFECTIVE_RANGE
        : range;
}

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

function installCraftSettlement(bot, wait = waitForSettlement) {
    if (!bot || typeof bot !== 'object' || typeof bot.once !== 'function') {
        throw new TypeError('SP-003 craft settlement requires an event-capable mineflayer bot');
    }
    if (typeof wait !== 'function') {
        throw new TypeError('SP-003 craft settlement requires a wait function');
    }
    if (bot[BOT_CRAFT_PATCH_MARK] || bot[BOT_CRAFT_INSTALL_MARK]) return bot;
    if (typeof bot.craft === 'function') return wrapCraftSettlement(bot, wait);

    const installAfterPluginInjection = () => wrapCraftSettlement(bot, wait);
    Object.defineProperty(bot, BOT_CRAFT_INSTALL_MARK, {
        configurable: false,
        enumerable: false,
        writable: false,
        value: Object.freeze({
            policyId: POLICY_ID,
            event: 'inject_allowed',
            handler: installAfterPluginInjection,
        }),
    });
    bot.once('inject_allowed', installAfterPluginInjection);
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

if (!pathfinderModule[GOAL_NEAR_PATCH_MARK]) {
    const OriginalGoalNear = pathfinderModule.goals.GoalNear;
    class SP003ExactUnitGoalNear extends OriginalGoalNear {
        constructor(x, y, z, range) {
            const effectiveRange = exactUnitGoalNearRange(range);
            super(x, y, z, effectiveRange);
            this.sp003ExactUnitGoalNear = Object.freeze({
                policyId: EXACT_UNIT_GOAL_NEAR_POLICY_ID,
                requestedRange: range,
                effectiveRange,
                transformed: Number(range) === EXACT_UNIT_GOAL_NEAR_REQUESTED_RANGE,
            });
        }
    }
    pathfinderModule.goals.GoalNear = SP003ExactUnitGoalNear;
    pathfinderModule[GOAL_NEAR_PATCH_MARK] = Object.freeze({
        policyId: EXACT_UNIT_GOAL_NEAR_POLICY_ID,
        requestedRange: EXACT_UNIT_GOAL_NEAR_REQUESTED_RANGE,
        effectiveRange: EXACT_UNIT_GOAL_NEAR_EFFECTIVE_RANGE,
        originalGoalNear: OriginalGoalNear,
        patchedGoalNear: SP003ExactUnitGoalNear,
    });
}

if (!mineflayerModule[CREATE_BOT_PATCH_MARK]) {
    const originalCreateBot = mineflayerModule.createBot;
    mineflayerModule.createBot = function sp003CreateBot(...args) {
        return installCraftSettlement(originalCreateBot.apply(this, args));
    };
    mineflayerModule[CREATE_BOT_PATCH_MARK] = Object.freeze({
        policyId: POLICY_ID,
        delayMs: CRAFT_SETTLEMENT_DELAY_MS,
        installationEvent: 'inject_allowed',
        synchronousCraftRequired: false,
        originalCreateBot,
        patchedCreateBot: mineflayerModule.createBot,
    });
}

module.exports = {
    POLICY_ID,
    CRAFT_SETTLEMENT_DELAY_MS,
    EXACT_UNIT_GOAL_NEAR_POLICY_ID,
    EXACT_UNIT_GOAL_NEAR_REQUESTED_RANGE,
    EXACT_UNIT_GOAL_NEAR_EFFECTIVE_RANGE,
    exactUnitGoalNearRange,
    hardenMovements,
    installCraftSettlement,
    wrapCraftSettlement,
    status: pathfinderModule[MOVEMENTS_PATCH_MARK],
    goalStatus: pathfinderModule[GOAL_NEAR_PATCH_MARK],
    craftStatus: mineflayerModule[CREATE_BOT_PATCH_MARK],
};
