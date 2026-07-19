'use strict';

const POLICY_ID = 'sp003-runtime-preload-v2';
const CRAFT_SETTLEMENT_DELAY_MS = 1000;
const FIRST_TABLE_TOOL_CRAFT_READINESS_POLICY_ID = 'sp003-first-table-tool-craft-readiness-v1';
const FIRST_TABLE_TOOL_CRAFT_READINESS_TIMEOUT_MS = 1500;
const FIRST_TABLE_TOOL_CRAFT_READINESS_POST_CLOSE_WAIT_MS = 100;
const TABLE_TOOL_CRAFT_ITEMS = new Set(['wooden_pickaxe', 'stone_pickaxe']);
const EXACT_UNIT_GOAL_NEAR_POLICY_ID = 'sp003-exact-unit-goal-near-v1';
const EXACT_UNIT_GOAL_NEAR_REQUESTED_RANGE = 1;
const EXACT_UNIT_GOAL_NEAR_EFFECTIVE_RANGE = 0;
const GOALBLOCK_COMPLETION_GROUNDING_POLICY_ID = 'sp003-goalblock-completion-grounding-v1';
const EXACT_GOALNEAR_COMPLETION_GROUNDING_POLICY_ID = 'sp003-exact-goalnear-completion-grounding-v1';
const PATHFINDER_STOP_DRAIN_POLICY_ID = 'sp003-pathfinder-stop-drain-v1';
const DOWNSTEP_TRANSITION_CLEARANCE_POLICY_ID = 'sp003-downstep-transition-clearance-v1';
const GOALBLOCK_NUDGE_PULSE_MS = 125;
const GOALBLOCK_NUDGE_MAX_PULSES = 4;
const GOALBLOCK_NUDGE_MAX_HORIZONTAL_DISTANCE = 1.6;
const MOVEMENTS_PATCH_MARK = Symbol.for('singularity.sp003.inventoryPreservingNavigation');
const GOAL_NEAR_PATCH_MARK = Symbol.for('singularity.sp003.exactUnitGoalNear');
const PATHFINDER_PLUGIN_PATCH_MARK = Symbol.for('singularity.sp003.pathfinderPlugin');
const BOT_PATHFINDER_PATCH_MARK = Symbol.for('singularity.sp003.goalBlockCompletionGrounding');
const BOT_PATHFINDER_STOP_DRAIN_MARK = Symbol.for('singularity.sp003.pathfinderStopDrain');
const CREATE_BOT_PATCH_MARK = Symbol.for('singularity.sp003.createBot');
const BOT_CRAFT_INSTALL_MARK = Symbol.for('singularity.sp003.craftSettlementInstall');
const BOT_CRAFT_PATCH_MARK = Symbol.for('singularity.sp003.craftSettlement');
const BOT_CRAFT_READINESS_STATE_MARK = Symbol.for('singularity.sp003.firstTableToolCraftReadiness');
const pathfinderModule = require('mineflayer-pathfinder');
const mineflayerModule = require('mineflayer');
const { Vec3 } = require('vec3');

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

function flooredPosition(position) {
    if (!position) return null;
    if (typeof position.floored === 'function') return position.floored();
    const values = [position.x, position.y, position.z].map(Number);
    if (!values.every(Number.isFinite)) return null;
    return new Vec3(
        Math.floor(values[0]),
        Math.floor(values[1]),
        Math.floor(values[2]),
    );
}

function blockCollision(bot, position) {
    const block = typeof bot?.blockAt === 'function' ? bot.blockAt(position) : null;
    const name = String(block?.name || 'air');
    const type = Number(block?.type || 0);
    const collision = String(
        block?.boundingBox || ((type === 0 || name === 'air') ? 'empty' : 'block'),
    );
    return { name, type, collision };
}

function completionGroundingKind(goal) {
    if (goal instanceof pathfinderModule.goals.GoalBlock) {
        return {
            goalType: 'GoalBlock',
            policyId: GOALBLOCK_COMPLETION_GROUNDING_POLICY_ID,
        };
    }
    const metadata = goal?.sp003ExactUnitGoalNear;
    if (
        goal instanceof pathfinderModule.goals.GoalNear
        && metadata?.policyId === EXACT_UNIT_GOAL_NEAR_POLICY_ID
        && Number(metadata.requestedRange) === EXACT_UNIT_GOAL_NEAR_REQUESTED_RANGE
        && Number(metadata.effectiveRange) === EXACT_UNIT_GOAL_NEAR_EFFECTIVE_RANGE
        && metadata.transformed === true
    ) {
        return {
            goalType: 'SP003ExactUnitGoalNear',
            policyId: EXACT_GOALNEAR_COMPLETION_GROUNDING_POLICY_ID,
        };
    }
    return null;
}

function goalCompletionNudgeProof(bot, goal) {
    const currentPosition = bot?.entity?.position;
    const currentCell = flooredPosition(currentPosition);
    const completionKind = completionGroundingKind(goal);
    const issues = [];
    if (!completionKind) issues.push('goal_must_have_supported_completion_grounding');
    if (!currentCell) issues.push('current_position_must_be_finite');
    if (bot?.entity?.onGround !== true) issues.push('player_must_be_grounded');

    const target = new Vec3(
        Math.floor(Number(goal?.x)),
        Math.floor(Number(goal?.y)),
        Math.floor(Number(goal?.z)),
    );
    if (![target.x, target.y, target.z].every(Number.isFinite)) {
        issues.push('goal_coordinates_must_be_finite');
    }
    if (currentCell) {
        const dx = target.x - currentCell.x;
        const dy = target.y - currentCell.y;
        const dz = target.z - currentCell.z;
        if (dy !== -1) issues.push('goal_must_be_exactly_one_level_lower');
        if (Math.max(Math.abs(dx), Math.abs(dz)) !== 1) {
            issues.push('goal_must_be_horizontally_adjacent');
        }
    }

    const expectedPlayerPosition = new Vec3(target.x + 0.5, target.y, target.z + 0.5);
    const horizontalDistance = currentPosition
        ? Math.hypot(
            Number(currentPosition.x) - expectedPlayerPosition.x,
            Number(currentPosition.z) - expectedPlayerPosition.z,
        )
        : null;
    if (
        horizontalDistance === null
        || !Number.isFinite(horizontalDistance)
        || horizontalDistance > GOALBLOCK_NUDGE_MAX_HORIZONTAL_DISTANCE
    ) {
        issues.push('goal_center_outside_bounded_horizontal_distance');
    }

    const support = blockCollision(bot, target.offset(0, -1, 0));
    const feet = blockCollision(bot, target);
    const head = blockCollision(bot, target.offset(0, 1, 0));
    const transitionUpperHead = blockCollision(bot, target.offset(0, 2, 0));
    if (support.collision !== 'block' || support.type === 0 || support.name === 'air') {
        issues.push('goal_support_must_be_solid');
    }
    if (feet.collision !== 'empty') issues.push('goal_feet_must_be_passable');
    if (head.collision !== 'empty') issues.push('goal_head_must_be_passable');
    if (transitionUpperHead.collision !== 'empty') {
        issues.push('goal_transition_upper_head_must_be_passable');
    }

    return {
        policyId: completionKind?.policyId || GOALBLOCK_COMPLETION_GROUNDING_POLICY_ID,
        transitionPolicyId: DOWNSTEP_TRANSITION_CLEARANCE_POLICY_ID,
        goalType: completionKind?.goalType || '',
        eligible: issues.length === 0,
        issues,
        currentCell,
        target,
        expectedPlayerPosition,
        horizontalDistance,
        support,
        feet,
        head,
        transitionUpperHead,
    };
}

function goalBlockNudgeProof(bot, goal) {
    const proof = goalCompletionNudgeProof(bot, goal);
    if (goal instanceof pathfinderModule.goals.GoalBlock) return proof;
    return {
        ...proof,
        policyId: GOALBLOCK_COMPLETION_GROUNDING_POLICY_ID,
        eligible: false,
        issues: [...proof.issues, 'goal_must_be_goalblock'],
    };
}

function goalCompletionError(message, issues = [], policyId = GOALBLOCK_COMPLETION_GROUNDING_POLICY_ID) {
    const error = new Error(message);
    error.name = 'SP003GoalCompletionGroundingError';
    error.policyId = policyId;
    error.issues = [...issues];
    return error;
}

function pathfinderStopDrainStatus(bot) {
    return bot?.pathfinder?.[BOT_PATHFINDER_STOP_DRAIN_MARK] || null;
}

function installPathfinderStopDrain(bot) {
    if (!bot || typeof bot !== 'object' || !bot.pathfinder) {
        throw new TypeError('SP-003 stop drain requires a pathfinder bot');
    }
    if (typeof bot.pathfinder.stop !== 'function') {
        throw new TypeError('SP-003 stop drain requires pathfinder.stop');
    }
    if (typeof bot.pathfinder.setGoal !== 'function') {
        throw new TypeError('SP-003 stop drain requires pathfinder.setGoal');
    }
    if (bot.pathfinder[BOT_PATHFINDER_STOP_DRAIN_MARK]) return bot;

    const originalStop = bot.pathfinder.stop;
    const originalSetGoal = bot.pathfinder.setGoal;
    bot.pathfinder.stop = function sp003StopAndDrain(...args) {
        const result = originalStop.apply(this, args);
        originalSetGoal.call(this, null);
        return result;
    };
    Object.defineProperty(bot.pathfinder, BOT_PATHFINDER_STOP_DRAIN_MARK, {
        configurable: false,
        enumerable: false,
        writable: false,
        value: Object.freeze({
            policyId: PATHFINDER_STOP_DRAIN_POLICY_ID,
            drainMethod: 'setGoal(null)',
            immediate: true,
            automaticRetryAllowed: false,
            worldMutationAllowed: false,
            originalStop,
            originalSetGoal,
            patchedStop: bot.pathfinder.stop,
        }),
    });
    return bot;
}

function installPathfinderGoalCompletion(bot, wait = waitForSettlement) {
    if (!bot || typeof bot !== 'object' || !bot.pathfinder) {
        throw new TypeError('SP-003 goal completion grounding requires a pathfinder bot');
    }
    if (typeof bot.pathfinder.goto !== 'function') {
        throw new TypeError('SP-003 goal completion grounding requires pathfinder.goto');
    }
    if (typeof wait !== 'function') {
        throw new TypeError('SP-003 goal completion grounding requires a wait function');
    }
    if (bot.pathfinder[BOT_PATHFINDER_PATCH_MARK]) return bot;

    const originalGoto = bot.pathfinder.goto;
    bot.pathfinder.goto = async function sp003GroundedGoto(goal) {
        const result = await originalGoto.call(this, goal);
        const currentCell = flooredPosition(bot.entity?.position);
        if (typeof goal?.isEnd !== 'function') return result;
        if (currentCell && goal.isEnd(currentCell)) return result;
        const completionKind = completionGroundingKind(goal);
        if (!completionKind) return result;

        const proof = goalCompletionNudgeProof(bot, goal);
        if (!proof.eligible) {
            throw goalCompletionError(
                `SP-003 ${proof.goalType} resolved outside the goal: ${proof.issues.join(', ')}`,
                proof.issues,
                proof.policyId,
            );
        }
        if (
            typeof bot.lookAt !== 'function'
            || typeof bot.setControlState !== 'function'
        ) {
            throw goalCompletionError(
                `SP-003 ${proof.goalType} recovery controls are unavailable`,
                ['bounded_recovery_controls_unavailable'],
                proof.policyId,
            );
        }

        const lookTarget = new Vec3(
            proof.expectedPlayerPosition.x,
            Number(bot.entity.position.y) + 1.62,
            proof.expectedPlayerPosition.z,
        );
        await bot.lookAt(lookTarget);
        try {
            bot.setControlState('forward', true);
            for (let pulse = 0; pulse < GOALBLOCK_NUDGE_MAX_PULSES; pulse += 1) {
                const support = blockCollision(bot, proof.target.offset(0, -1, 0));
                const feet = blockCollision(bot, proof.target);
                const head = blockCollision(bot, proof.target.offset(0, 1, 0));
                const transitionUpperHead = blockCollision(
                    bot,
                    proof.target.offset(0, 2, 0),
                );
                if (
                    support.collision !== 'block'
                    || support.type === 0
                    || support.name === 'air'
                    || feet.collision !== 'empty'
                    || head.collision !== 'empty'
                    || transitionUpperHead.collision !== 'empty'
                ) {
                    throw goalCompletionError(
                        `SP-003 ${proof.goalType} recovery geometry changed during movement`,
                        ['goal_geometry_changed_during_recovery'],
                        proof.policyId,
                    );
                }
                await wait(GOALBLOCK_NUDGE_PULSE_MS);
                if (goal.isEnd(flooredPosition(bot.entity?.position))) return result;
            }
        } finally {
            bot.setControlState('forward', false);
        }
        throw goalCompletionError(
            `SP-003 ${proof.goalType} remained unresolved after bounded recovery`,
            ['bounded_recovery_exhausted'],
            proof.policyId,
        );
    };
    Object.defineProperty(bot.pathfinder, BOT_PATHFINDER_PATCH_MARK, {
        configurable: false,
        enumerable: false,
        writable: false,
        value: Object.freeze({
            policyId: GOALBLOCK_COMPLETION_GROUNDING_POLICY_ID,
            exactGoalNearPolicyId: EXACT_GOALNEAR_COMPLETION_GROUNDING_POLICY_ID,
            transitionPolicyId: DOWNSTEP_TRANSITION_CLEARANCE_POLICY_ID,
            pulseMs: GOALBLOCK_NUDGE_PULSE_MS,
            maximumPulses: GOALBLOCK_NUDGE_MAX_PULSES,
            originalGoto,
            patchedGoto: bot.pathfinder.goto,
        }),
    });
    return bot;
}

function compactCraftingTablePosition(craftingTable) {
    const position = craftingTable?.position;
    const values = [position?.x, position?.y, position?.z].map(Number);
    if (!values.every(Number.isFinite)) return null;
    return { x: values[0], y: values[1], z: values[2] };
}

function craftInventoryCounts(bot) {
    if (typeof bot?.inventory?.items !== 'function') {
        throw new TypeError('SP-003 craft readiness requires inventory items');
    }
    const counts = {};
    for (const item of bot.inventory.items()) {
        const name = String(item?.name || '');
        const count = Number(item?.count || 0);
        if (name && Number.isFinite(count) && count > 0) {
            counts[name] = Number(counts[name] || 0) + count;
        }
    }
    return Object.fromEntries(
        Object.entries(counts).sort(([left], [right]) => left.localeCompare(right)),
    );
}

function craftInventoriesMatch(left, right) {
    return JSON.stringify(left) === JSON.stringify(right);
}

function tableToolCraftTarget(bot, recipe, craftingTable) {
    if (!craftingTable || recipe?.requiresTable !== true) return '';
    const resultId = Number(recipe?.result?.id);
    const target = String(
        recipe?.result?.name
        || (Number.isFinite(resultId) ? bot?.registry?.items?.[resultId]?.name : '')
        || '',
    );
    return TABLE_TOOL_CRAFT_ITEMS.has(target) ? target : '';
}

function craftReadinessError(message, proof) {
    const error = new Error(message);
    error.name = 'SP003FirstTableToolCraftReadinessError';
    error.policyId = FIRST_TABLE_TOOL_CRAFT_READINESS_POLICY_ID;
    error.proof = proof;
    return error;
}

async function preflightFirstTableToolCraft(
    bot,
    targetItem,
    craftingTable,
    wait = waitForSettlement,
    options = {},
) {
    const timeoutMs = Math.max(
        1,
        Number(options.timeoutMs ?? FIRST_TABLE_TOOL_CRAFT_READINESS_TIMEOUT_MS) || 0,
    );
    const postCloseWaitMs = Math.max(
        0,
        Number(
            options.postCloseWaitMs
            ?? FIRST_TABLE_TOOL_CRAFT_READINESS_POST_CLOSE_WAIT_MS,
        ) || 0,
    );
    const tablePosition = compactCraftingTablePosition(craftingTable);
    const inventoryBefore = craftInventoryCounts(bot);
    const proof = {
        type: 'sp003_first_table_tool_craft_readiness_proof',
        schema_version: 1,
        policy_id: FIRST_TABLE_TOOL_CRAFT_READINESS_POLICY_ID,
        target_item: targetItem,
        crafting_table_position: tablePosition,
        attempt_limit: 1,
        attempt_count: 1,
        timeout_ms: timeoutMs,
        post_close_wait_ms: postCloseWaitMs,
        inventory_before: inventoryBefore,
        inventory_after: null,
        inventory_unchanged: false,
        window_id: null,
        window_type: '',
        open_count: 1,
        close_count: 0,
        original_craft_call_count: 0,
        world_mutation: false,
        passed: false,
    };
    if (String(craftingTable?.name || '') !== 'crafting_table' || !tablePosition) {
        throw craftReadinessError(
            'SP-003 craft readiness requires one exact crafting table',
            proof,
        );
    }
    if (typeof bot?.openBlock !== 'function' || typeof bot?.closeWindow !== 'function') {
        throw craftReadinessError(
            'SP-003 craft readiness window APIs are unavailable',
            proof,
        );
    }
    if (typeof wait !== 'function') {
        throw new TypeError('SP-003 craft readiness requires a wait function');
    }

    let timeoutHandle = null;
    let timedOut = false;
    const openPromise = Promise.resolve().then(() => bot.openBlock(craftingTable));
    const timeoutPromise = new Promise((resolve) => {
        timeoutHandle = setTimeout(() => {
            timedOut = true;
            resolve({ timeout: true });
        }, timeoutMs);
    });
    try {
        const outcome = await Promise.race([
            openPromise.then((window) => ({ window })),
            timeoutPromise,
        ]);
        if (outcome?.timeout) {
            openPromise.then((window) => {
                try {
                    if (window) bot.closeWindow(window);
                } catch (_) {
                    // A late readiness window is closed best-effort after timeout.
                }
            }).catch(() => {});
            throw craftReadinessError(
                'SP-003 first table tool craft readiness timed out',
                proof,
            );
        }
        if (timeoutHandle) clearTimeout(timeoutHandle);
        const window = outcome?.window;
        if (!window) {
            throw craftReadinessError(
                'SP-003 first table tool craft readiness opened no window',
                proof,
            );
        }
        proof.window_id = Number.isFinite(Number(window.id)) ? Number(window.id) : null;
        proof.window_type = String(window.type || '');
        bot.closeWindow(window);
        proof.close_count = 1;
        if (!proof.window_type.startsWith('minecraft:crafting')) {
            throw craftReadinessError(
                'SP-003 first table tool craft readiness opened a non-crafting window',
                proof,
            );
        }
        if (postCloseWaitMs > 0) await wait(postCloseWaitMs);
        proof.inventory_after = craftInventoryCounts(bot);
        proof.inventory_unchanged = craftInventoriesMatch(
            proof.inventory_before,
            proof.inventory_after,
        );
        if (!proof.inventory_unchanged) {
            throw craftReadinessError(
                'SP-003 first table tool craft readiness changed inventory',
                proof,
            );
        }
        proof.passed = true;
        return proof;
    } catch (error) {
        if (timeoutHandle) clearTimeout(timeoutHandle);
        if (error?.name === 'SP003FirstTableToolCraftReadinessError') throw error;
        throw craftReadinessError(
            `SP-003 first table tool craft readiness failed: ${error?.message || error}`,
            proof,
        );
    } finally {
        if (!timedOut && timeoutHandle) clearTimeout(timeoutHandle);
    }
}

function firstTableToolCraftReadinessStatus(bot) {
    const state = bot?.[BOT_CRAFT_READINESS_STATE_MARK];
    if (!state) {
        return {
            installed: false,
            policyId: FIRST_TABLE_TOOL_CRAFT_READINESS_POLICY_ID,
            status: 'uninstalled',
            attemptCount: 0,
            originalCraftCallCount: 0,
            proof: null,
        };
    }
    return {
        installed: true,
        policyId: FIRST_TABLE_TOOL_CRAFT_READINESS_POLICY_ID,
        status: state.status,
        attemptCount: state.attemptCount,
        originalCraftCallCount: state.originalCraftCallCount,
        proof: state.proof ? JSON.parse(JSON.stringify(state.proof)) : null,
    };
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
    const readinessState = {
        status: 'pending',
        attemptCount: 0,
        originalCraftCallCount: 0,
        proof: null,
    };
    Object.defineProperty(bot, BOT_CRAFT_READINESS_STATE_MARK, {
        configurable: false,
        enumerable: false,
        writable: false,
        value: readinessState,
    });
    bot.craft = async function sp003CraftWithSettlement(...args) {
        const craftingTable = args[2];
        const targetItem = tableToolCraftTarget(bot, args[0], craftingTable);
        if (targetItem && readinessState.status === 'failed') {
            throw craftReadinessError(
                'SP-003 first table tool craft readiness already failed',
                readinessState.proof,
            );
        }
        if (targetItem && readinessState.status === 'pending') {
            readinessState.attemptCount += 1;
            try {
                readinessState.proof = await preflightFirstTableToolCraft(
                    bot,
                    targetItem,
                    craftingTable,
                    wait,
                );
                readinessState.status = 'ready';
            } catch (error) {
                readinessState.status = 'failed';
                readinessState.proof = error?.proof || null;
                throw error;
            }
        }
        if (targetItem) readinessState.originalCraftCallCount += 1;
        const result = await originalCraft.apply(this, args);
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
            readinessPolicyId: FIRST_TABLE_TOOL_CRAFT_READINESS_POLICY_ID,
            readinessTimeoutMs: FIRST_TABLE_TOOL_CRAFT_READINESS_TIMEOUT_MS,
            readinessPostCloseWaitMs: FIRST_TABLE_TOOL_CRAFT_READINESS_POST_CLOSE_WAIT_MS,
            readinessState,
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

if (!pathfinderModule[PATHFINDER_PLUGIN_PATCH_MARK]) {
    const originalPathfinder = pathfinderModule.pathfinder;
    pathfinderModule.pathfinder = function sp003PathfinderPlugin(...args) {
        const result = originalPathfinder.apply(this, args);
        installPathfinderStopDrain(args[0]);
        installPathfinderGoalCompletion(args[0]);
        return result;
    };
    pathfinderModule[PATHFINDER_PLUGIN_PATCH_MARK] = Object.freeze({
        policyId: GOALBLOCK_COMPLETION_GROUNDING_POLICY_ID,
        exactGoalNearPolicyId: EXACT_GOALNEAR_COMPLETION_GROUNDING_POLICY_ID,
        transitionPolicyId: DOWNSTEP_TRANSITION_CLEARANCE_POLICY_ID,
        stopDrainPolicyId: PATHFINDER_STOP_DRAIN_POLICY_ID,
        originalPathfinder,
        patchedPathfinder: pathfinderModule.pathfinder,
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
    FIRST_TABLE_TOOL_CRAFT_READINESS_POLICY_ID,
    FIRST_TABLE_TOOL_CRAFT_READINESS_TIMEOUT_MS,
    FIRST_TABLE_TOOL_CRAFT_READINESS_POST_CLOSE_WAIT_MS,
    EXACT_UNIT_GOAL_NEAR_POLICY_ID,
    EXACT_UNIT_GOAL_NEAR_REQUESTED_RANGE,
    EXACT_UNIT_GOAL_NEAR_EFFECTIVE_RANGE,
    GOALBLOCK_COMPLETION_GROUNDING_POLICY_ID,
    EXACT_GOALNEAR_COMPLETION_GROUNDING_POLICY_ID,
    PATHFINDER_STOP_DRAIN_POLICY_ID,
    DOWNSTEP_TRANSITION_CLEARANCE_POLICY_ID,
    GOALBLOCK_NUDGE_PULSE_MS,
    GOALBLOCK_NUDGE_MAX_PULSES,
    GOALBLOCK_NUDGE_MAX_HORIZONTAL_DISTANCE,
    exactUnitGoalNearRange,
    completionGroundingKind,
    goalCompletionNudgeProof,
    goalBlockNudgeProof,
    hardenMovements,
    pathfinderStopDrainStatus,
    installPathfinderStopDrain,
    installPathfinderGoalCompletion,
    tableToolCraftTarget,
    preflightFirstTableToolCraft,
    firstTableToolCraftReadinessStatus,
    installCraftSettlement,
    wrapCraftSettlement,
    status: pathfinderModule[MOVEMENTS_PATCH_MARK],
    goalStatus: pathfinderModule[GOAL_NEAR_PATCH_MARK],
    pathfinderStatus: pathfinderModule[PATHFINDER_PLUGIN_PATCH_MARK],
    craftStatus: mineflayerModule[CREATE_BOT_PATCH_MARK],
};
