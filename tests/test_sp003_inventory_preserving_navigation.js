const assert = require('assert');
const { EventEmitter } = require('events');
const { Vec3 } = require('vec3');

const pathfinderModule = require('mineflayer-pathfinder');
const mineflayerModule = require('mineflayer');
const OriginalMovements = pathfinderModule.Movements;
const OriginalGoalNear = pathfinderModule.goals.GoalNear;
const OriginalGoalNearXZ = pathfinderModule.goals.GoalNearXZ;
const OriginalPathfinder = pathfinderModule.pathfinder;
const OriginalCreateBot = mineflayerModule.createBot;
const preload = require('../src/bot/sp003_inventory_preserving_navigation');
const { createDigHandler, createMoveToHandler } = require('../src/bot/bot_server');

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

function testPreloadPatchesPathfinderPluginOnceWithinItsNodeProcess() {
    assert.notStrictEqual(pathfinderModule.pathfinder, OriginalPathfinder);
    assert.strictEqual(preload.pathfinderStatus.originalPathfinder, OriginalPathfinder);
    assert.strictEqual(
        preload.pathfinderStatus.patchedPathfinder,
        pathfinderModule.pathfinder,
    );
    assert.strictEqual(
        preload.pathfinderStatus.policyId,
        'sp003-goalblock-completion-grounding-v1',
    );
    assert.strictEqual(
        preload.pathfinderStatus.exactGoalNearPolicyId,
        'sp003-exact-goalnear-completion-grounding-v1',
    );
    assert.strictEqual(
        preload.pathfinderStatus.stopDrainPolicyId,
        'sp003-pathfinder-stop-drain-v1',
    );
    assert.strictEqual(
        require('../src/bot/sp003_inventory_preserving_navigation').pathfinderStatus,
        preload.pathfinderStatus,
    );
    console.log('PASS: SP-003 preload patches the process-local pathfinder plugin once');
}

function testStopDrainPolicyRequiresTheDependencyLifecycleSurface() {
    assert.strictEqual(
        preload.PATHFINDER_STOP_DRAIN_POLICY_ID,
        'sp003-pathfinder-stop-drain-v1',
    );
    assert.throws(
        () => preload.installPathfinderStopDrain(null),
        /pathfinder bot/,
    );
    assert.throws(
        () => preload.installPathfinderStopDrain({ pathfinder: { setGoal() {} } }),
        /pathfinder\.stop/,
    );
    assert.throws(
        () => preload.installPathfinderStopDrain({ pathfinder: { stop() {} } }),
        /pathfinder\.setGoal/,
    );
    const stopError = new Error('original stop failed');
    let setGoalAfterStopFailure = 0;
    const stopFailure = {
        pathfinder: {
            stop() { throw stopError; },
            setGoal() { setGoalAfterStopFailure += 1; },
        },
    };
    preload.installPathfinderStopDrain(stopFailure);
    assert.throws(() => stopFailure.pathfinder.stop(), (error) => error === stopError);
    assert.strictEqual(setGoalAfterStopFailure, 0);

    const setGoalError = new Error('original setGoal failed');
    let stopBeforeSetGoalFailure = 0;
    const setGoalFailure = {
        pathfinder: {
            stop() { stopBeforeSetGoalFailure += 1; },
            setGoal() { throw setGoalError; },
        },
    };
    preload.installPathfinderStopDrain(setGoalFailure);
    assert.throws(
        () => setGoalFailure.pathfinder.stop(),
        (error) => error === setGoalError,
    );
    assert.strictEqual(stopBeforeSetGoalFailure, 1);
    console.log('PASS: SP-003 stop drain requires the exact dependency lifecycle surface');
}

function deferredStopPathfinderBot() {
    const calls = {
        goto: [],
        stop: 0,
        setGoal: [],
        pathStop: 0,
        worldMutations: 0,
    };
    let stopPathing = false;
    let firstGoto = true;
    const firstError = new Error('Took to long to decide path to goal!');
    const bot = new EventEmitter();
    bot.pathfinder = {
        setGoal(goal) {
            calls.setGoal.push(goal);
            bot.emit('goal_updated', goal, false);
            if (stopPathing) {
                stopPathing = false;
                calls.pathStop += 1;
                bot.emit('path_stop');
            }
        },
        stop() {
            calls.stop += 1;
            stopPathing = true;
            return 'stopped';
        },
        async goto(goal) {
            calls.goto.push(goal);
            const poisoned = stopPathing;
            this.setGoal(goal);
            if (poisoned) {
                throw new Error(
                    'Path was stopped before it could be completed! Thus, the desired goal was not reached.',
                );
            }
            if (firstGoto) {
                firstGoto = false;
                throw firstError;
            }
            return { reached: goal };
        },
    };
    return {
        bot,
        calls,
        firstError,
        stopPending: () => stopPathing,
    };
}

async function testStopDrainConsumesDeferredStopBeforeTheNextGoto() {
    const { bot, calls, firstError, stopPending } = deferredStopPathfinderBot();
    const originalStop = bot.pathfinder.stop;
    const originalSetGoal = bot.pathfinder.setGoal;

    assert.strictEqual(preload.installPathfinderStopDrain(bot), bot);
    const patchedStop = bot.pathfinder.stop;
    assert.strictEqual(preload.installPathfinderStopDrain(bot), bot);
    assert.strictEqual(bot.pathfinder.stop, patchedStop);
    await assert.rejects(bot.pathfinder.goto({ id: 'first' }), (error) => error === firstError);
    assert.strictEqual(bot.pathfinder.stop(), 'stopped');

    assert.strictEqual(stopPending(), false);
    assert.deepStrictEqual(await bot.pathfinder.goto({ id: 'second' }), {
        reached: { id: 'second' },
    });
    assert.strictEqual(calls.goto.length, 2);
    assert.strictEqual(calls.stop, 1);
    assert.strictEqual(calls.setGoal.filter(goal => goal === null).length, 1);
    assert.strictEqual(calls.pathStop, 1);
    assert.strictEqual(calls.worldMutations, 0);

    const status = preload.pathfinderStopDrainStatus(bot);
    assert.strictEqual(status.policyId, 'sp003-pathfinder-stop-drain-v1');
    assert.strictEqual(status.drainMethod, 'setGoal(null)');
    assert.strictEqual(status.immediate, true);
    assert.strictEqual(status.automaticRetryAllowed, false);
    assert.strictEqual(status.worldMutationAllowed, false);
    assert.strictEqual(status.originalStop, originalStop);
    assert.strictEqual(status.originalSetGoal, originalSetGoal);
    assert.strictEqual(status.patchedStop, patchedStop);
    console.log('PASS: SP-003 stop drain consumes one deferred stop before the next goto');
}

async function testStopDrainStillRejectsAnActiveGoto() {
    const bot = new EventEmitter();
    const calls = { stop: 0, setGoal: [], pathStop: 0 };
    let stopPathing = false;
    bot.pathfinder = {
        setGoal(goal) {
            calls.setGoal.push(goal);
            bot.emit('goal_updated', goal, false);
            if (stopPathing) {
                stopPathing = false;
                calls.pathStop += 1;
                bot.emit('path_stop');
            }
        },
        stop() {
            calls.stop += 1;
            stopPathing = true;
        },
        goto(goal) {
            return new Promise((resolve, reject) => {
                const cleanup = () => {
                    bot.removeListener('goal_updated', changed);
                    bot.removeListener('path_stop', stopped);
                };
                const changed = (newGoal) => {
                    if (newGoal === goal) return;
                    cleanup();
                    reject(new Error('The goal was changed before it could be completed!'));
                };
                const stopped = () => {
                    cleanup();
                    reject(new Error('Path was stopped before it could be completed!'));
                };
                bot.on('goal_updated', changed);
                bot.on('path_stop', stopped);
                this.setGoal(goal);
            });
        },
    };
    preload.installPathfinderStopDrain(bot);

    const pending = bot.pathfinder.goto({ id: 'active' });
    bot.pathfinder.stop();
    await assert.rejects(pending, /goal was changed/);
    assert.strictEqual(calls.stop, 1);
    assert.strictEqual(calls.setGoal.filter(goal => goal === null).length, 1);
    assert.strictEqual(calls.pathStop, 1);
    assert.strictEqual(stopPathing, false);
    console.log('PASS: SP-003 immediate stop drain still rejects an active goto');
}

async function testPickupTimeoutCannotPoisonTheFollowingMove() {
    const mcData = require('minecraft-data')('1.20.4');
    const target = new Vec3(1, 64, 0);
    const drop = {
        id: 1111,
        name: 'item',
        position: new Vec3(1.5, 64, 0.5),
        getDroppedItem: () => ({ name: 'oak_log' }),
    };
    const calls = { goto: [], stop: 0, setGoal: [], pathStop: 0, dig: 0 };
    let stopPathing = false;
    let removed = false;
    let clockMs = 0;
    const bot = {
        version: '1.20.4',
        entity: { position: new Vec3(0.5, 64, 0.5), onGround: true },
        entities: { [drop.id]: drop },
        inventory: { items: () => [] },
        blockAt(position) {
            if (position.x === target.x && position.y === target.y && position.z === target.z) {
                return removed
                    ? { name: 'air', type: 0, boundingBox: 'empty', position: target }
                    : {
                        name: 'oak_log',
                        type: mcData.blocksByName.oak_log.id,
                        boundingBox: 'block',
                        drops: [mcData.itemsByName.oak_log.id],
                        position: target,
                    };
            }
            return { name: 'air', type: 0, boundingBox: 'empty', position };
        },
        async dig() {
            calls.dig += 1;
            removed = true;
        },
        pathfinder: {
            setGoal(goal) {
                calls.setGoal.push(goal);
                if (stopPathing) {
                    stopPathing = false;
                    calls.pathStop += 1;
                }
            },
            stop() {
                calls.stop += 1;
                stopPathing = true;
            },
            async goto(goal) {
                calls.goto.push(goal);
                const poisoned = stopPathing;
                this.setGoal(goal);
                if (poisoned) {
                    throw new Error(
                        'Path was stopped before it could be completed! Thus, the desired goal was not reached.',
                    );
                }
                if (calls.goto.length === 1) {
                    throw new Error('Took to long to decide path to goal!');
                }
                bot.entity.position = new Vec3(goal.x + 0.5, goal.y, goal.z + 0.5);
            },
        },
    };
    preload.installPathfinderStopDrain(bot);
    preload.installPathfinderGoalCompletion(bot, async () => {});
    const wait = async (ms) => { clockMs += Number(ms) || 0; };
    const dig = createDigHandler(
        () => ({ bot, botReady: true }),
        wait,
        { monotonicMs: () => clockMs },
    );
    const move = createMoveToHandler(() => ({ bot, botReady: true }));

    const digResult = await dig({ x: 1, y: 64, z: 0, require_pickup: true });
    assert.strictEqual(digResult.success, false);
    assert.strictEqual(
        digResult.pickup_collection.direct_navigation.error,
        'Took to long to decide path to goal!',
    );
    assert.strictEqual(stopPathing, false);

    const moveResult = await move({ x: 4, y: 64, z: 0, tolerance: 1, timeout_ms: 100 });
    assert.strictEqual(moveResult.success, true);
    assert.strictEqual(moveResult.reached, true);
    assert.strictEqual(calls.goto.length, 2);
    assert.strictEqual(calls.stop, 1);
    assert.strictEqual(calls.setGoal.filter(goal => goal === null).length, 1);
    assert.strictEqual(calls.pathStop, 1);
    assert.strictEqual(calls.dig, 1);
    console.log('PASS: a pickup timeout cannot poison the following Bridge move');
}

function phase107GoalBlockBot(overrides = {}) {
    const target = new Vec3(124, 139, -38);
    const calls = {
        goto: [],
        lookAt: [],
        controls: [],
        waits: [],
    };
    const bot = {
        entity: {
            position: new Vec3(124.43808494193001, 140, -36.47195326706993),
            onGround: true,
        },
        blockAt(position) {
            if (position.x === target.x && position.y === target.y - 1 && position.z === target.z) {
                return { name: 'stone', type: 1, boundingBox: 'block', position };
            }
            return { name: 'air', type: 0, boundingBox: 'empty', position };
        },
        async lookAt(position) {
            calls.lookAt.push(position.clone ? position.clone() : position);
        },
        setControlState(name, value) {
            calls.controls.push([name, value]);
        },
        pathfinder: {
            async goto(goal) {
                calls.goto.push(goal);
            },
        },
    };
    Object.assign(bot, overrides);
    return { bot, calls, target };
}

function phase109ExactGoalNearBot(overrides = {}) {
    const target = new Vec3(124, 140, -38);
    const calls = {
        goto: [],
        lookAt: [],
        controls: [],
        waits: [],
    };
    const bot = {
        entity: {
            position: new Vec3(124.37141158620051, 141, -36.49928173222183),
            onGround: true,
        },
        blockAt(position) {
            if (position.x === target.x && position.y === target.y - 1 && position.z === target.z) {
                return { name: 'stone', type: 1, boundingBox: 'block', position };
            }
            return { name: 'air', type: 0, boundingBox: 'empty', position };
        },
        async lookAt(position) {
            calls.lookAt.push(position.clone ? position.clone() : position);
        },
        setControlState(name, value) {
            calls.controls.push([name, value]);
        },
        pathfinder: {
            async goto(goal) {
                calls.goto.push(goal);
            },
        },
    };
    Object.assign(bot, overrides);
    return { bot, calls, target };
}

async function testFalseResolvedGoalBlockUsesBoundedClearDownStep() {
    const { bot, calls, target } = phase107GoalBlockBot();
    const wait = async (ms) => {
        calls.waits.push(ms);
        if (calls.waits.length === 2) {
            bot.entity.position = new Vec3(target.x + 0.5, target.y, target.z + 0.5);
            bot.entity.onGround = true;
        }
    };
    const goal = new pathfinderModule.goals.GoalBlock(target.x, target.y, target.z);
    const proof = preload.goalBlockNudgeProof(bot, goal);

    assert.strictEqual(proof.eligible, true);
    assert.deepStrictEqual(proof.issues, []);
    assert.strictEqual(proof.support.name, 'stone');
    assert.strictEqual(proof.feet.collision, 'empty');
    assert.strictEqual(proof.head.collision, 'empty');
    assert.strictEqual(preload.installPathfinderGoalCompletion(bot, wait), bot);
    assert.strictEqual(preload.installPathfinderGoalCompletion(bot, wait), bot);
    await bot.pathfinder.goto(goal);

    assert.strictEqual(calls.goto.length, 1);
    assert.deepStrictEqual(calls.waits, [125, 125]);
    assert.strictEqual(calls.lookAt.length, 1);
    assert.deepStrictEqual(calls.controls, [['forward', true], ['forward', false]]);
    assert.strictEqual(goal.isEnd(bot.entity.position.floored()), true);
    console.log('PASS: false-resolved GoalBlock enters the proven clear down-step cell');
}

async function testFalseResolvedExactUnitGoalNearUsesBoundedClearDownStep() {
    const { bot, calls, target } = phase109ExactGoalNearBot();
    const wait = async (ms) => {
        calls.waits.push(ms);
        if (calls.waits.length === 2) {
            bot.entity.position = new Vec3(target.x + 0.5, target.y, target.z + 0.5);
            bot.entity.onGround = true;
        }
    };
    const goal = new pathfinderModule.goals.GoalNear(
        target.x,
        target.y,
        target.z,
        1,
    );
    const proof = preload.goalCompletionNudgeProof(bot, goal);

    assert.deepStrictEqual(goal.sp003ExactUnitGoalNear, {
        policyId: 'sp003-exact-unit-goal-near-v1',
        requestedRange: 1,
        effectiveRange: 0,
        transformed: true,
    });
    assert.strictEqual(proof.policyId, 'sp003-exact-goalnear-completion-grounding-v1');
    assert.strictEqual(proof.goalType, 'SP003ExactUnitGoalNear');
    assert.strictEqual(proof.eligible, true);
    assert.deepStrictEqual(proof.issues, []);
    preload.installPathfinderGoalCompletion(bot, wait);
    await bot.pathfinder.goto(goal);

    assert.strictEqual(calls.goto.length, 1);
    assert.deepStrictEqual(calls.waits, [125, 125]);
    assert.deepStrictEqual(calls.controls, [['forward', true], ['forward', false]]);
    assert.strictEqual(goal.isEnd(bot.entity.position.floored()), true);

    const blocked = phase109ExactGoalNearBot();
    blocked.bot.blockAt = (position) => {
        if (position.x === target.x && position.y === target.y + 1 && position.z === target.z) {
            return { name: 'dirt', type: 9, boundingBox: 'block', position };
        }
        if (position.x === target.x && position.y === target.y - 1 && position.z === target.z) {
            return { name: 'stone', type: 1, boundingBox: 'block', position };
        }
        return { name: 'air', type: 0, boundingBox: 'empty', position };
    };
    preload.installPathfinderGoalCompletion(blocked.bot, async () => {});
    await assert.rejects(
        blocked.bot.pathfinder.goto(goal),
        (error) => (
            error.policyId === 'sp003-exact-goalnear-completion-grounding-v1'
            && error.issues.includes('goal_head_must_be_passable')
        ),
    );
    assert.deepStrictEqual(blocked.calls.controls, []);
    console.log('PASS: false-resolved exact GoalNear enters only a proven clear down-step cell');
}

async function testMoveToHandlerCannotAcceptPhase109PositionOutsideExactGoal() {
    const { bot, calls, target } = phase109ExactGoalNearBot();
    preload.installPathfinderGoalCompletion(bot, async (ms) => {
        calls.waits.push(ms);
        if (calls.waits.length === 2) {
            bot.entity.position = new Vec3(target.x + 0.5, target.y, target.z + 0.5);
        }
    });
    const moveTo = createMoveToHandler(() => ({ bot, botReady: true }));

    const result = await moveTo({
        x: 124.5,
        y: 140,
        z: -37.5,
        tolerance: 1.6,
    });

    assert.strictEqual(result.success, true);
    assert.strictEqual(result.reached, true);
    assert.deepStrictEqual(result.position, { x: 124.5, y: 140, z: -37.5 });
    assert.strictEqual(result.distance_to_target, 0);
    assert.strictEqual(calls.goto.length, 1);
    assert.strictEqual(
        calls.goto[0].sp003ExactUnitGoalNear.transformed,
        true,
    );
    assert.deepStrictEqual(calls.waits, [125, 125]);
    assert.strictEqual(calls.goto[0].isEnd(bot.entity.position.floored()), true);
    console.log('PASS: Phase109 move_to reaches the exact stand cell before success');
}

async function testGoalBlockGroundingRejectsUnprovenGeometryAndMissingControls() {
    const solidHead = phase107GoalBlockBot();
    solidHead.bot.blockAt = (position) => {
        if (
            position.x === solidHead.target.x
            && position.y === solidHead.target.y + 1
            && position.z === solidHead.target.z
        ) {
            return { name: 'dirt', type: 9, boundingBox: 'block', position };
        }
        if (
            position.x === solidHead.target.x
            && position.y === solidHead.target.y - 1
            && position.z === solidHead.target.z
        ) {
            return { name: 'stone', type: 1, boundingBox: 'block', position };
        }
        return { name: 'air', type: 0, boundingBox: 'empty', position };
    };
    const goal = new pathfinderModule.goals.GoalBlock(
        solidHead.target.x,
        solidHead.target.y,
        solidHead.target.z,
    );
    preload.installPathfinderGoalCompletion(solidHead.bot, async () => {});
    await assert.rejects(
        solidHead.bot.pathfinder.goto(goal),
        (error) => (
            error.name === 'SP003GoalCompletionGroundingError'
            && error.issues.includes('goal_head_must_be_passable')
        ),
    );
    assert.deepStrictEqual(solidHead.calls.controls, []);

    const missingControls = phase107GoalBlockBot();
    delete missingControls.bot.lookAt;
    preload.installPathfinderGoalCompletion(missingControls.bot, async () => {});
    await assert.rejects(
        missingControls.bot.pathfinder.goto(goal),
        (error) => error.issues.includes('bounded_recovery_controls_unavailable'),
    );
    assert.deepStrictEqual(missingControls.calls.waits, []);
    console.log('PASS: GoalBlock grounding rejects unproven geometry and controls');
}

async function testGoalBlockGroundingStopsAfterExactPulseBudget() {
    const { bot, calls, target } = phase107GoalBlockBot();
    const goal = new pathfinderModule.goals.GoalBlock(target.x, target.y, target.z);
    preload.installPathfinderGoalCompletion(bot, async (ms) => calls.waits.push(ms));

    await assert.rejects(
        bot.pathfinder.goto(goal),
        (error) => error.issues.includes('bounded_recovery_exhausted'),
    );
    assert.deepStrictEqual(calls.waits, [125, 125, 125, 125]);
    assert.deepStrictEqual(calls.controls, [['forward', true], ['forward', false]]);

    const exact = phase109ExactGoalNearBot();
    const exactGoal = new pathfinderModule.goals.GoalNear(
        exact.target.x,
        exact.target.y,
        exact.target.z,
        1,
    );
    preload.installPathfinderGoalCompletion(
        exact.bot,
        async (ms) => exact.calls.waits.push(ms),
    );
    await assert.rejects(
        exact.bot.pathfinder.goto(exactGoal),
        (error) => (
            error.policyId === 'sp003-exact-goalnear-completion-grounding-v1'
            && error.issues.includes('bounded_recovery_exhausted')
        ),
    );
    assert.deepStrictEqual(exact.calls.waits, [125, 125, 125, 125]);
    console.log('PASS: GoalBlock grounding fails closed after four movement pulses');
}

async function testGoalBlockGroundingPreservesOtherGoalsAndOriginalFailures() {
    const falseNear = phase107GoalBlockBot();
    const wait = async (ms) => falseNear.calls.waits.push(ms);
    preload.installPathfinderGoalCompletion(falseNear.bot, wait);
    const near = new pathfinderModule.goals.GoalNear(124, 139, -38, 0);
    await falseNear.bot.pathfinder.goto(near);
    const nonUnit = new pathfinderModule.goals.GoalNear(124, 139, -38, 2);
    await falseNear.bot.pathfinder.goto(nonUnit);
    const unmarked = new OriginalGoalNear(124, 139, -38, 1);
    await falseNear.bot.pathfinder.goto(unmarked);
    assert.strictEqual(falseNear.calls.goto.length, 3);
    assert.deepStrictEqual(falseNear.calls.waits, []);
    assert.deepStrictEqual(falseNear.calls.controls, []);

    const originalError = new Error('original pathfinder failure');
    const rejected = phase107GoalBlockBot({
        pathfinder: {
            async goto() {
                throw originalError;
            },
        },
    });
    preload.installPathfinderGoalCompletion(rejected.bot, async () => {});
    await assert.rejects(
        rejected.bot.pathfinder.goto(
            new pathfinderModule.goals.GoalBlock(124, 139, -38),
        ),
        (error) => error === originalError,
    );
    console.log('PASS: GoalBlock grounding preserves other goals and original failures');
}

async function testPickupClosesThroughGroundedExactGoalNear() {
    const target = new Vec3(124, 139, -38);
    const drop = {
        id: 949,
        name: 'item',
        position: new Vec3(124.875, 139, -37.875),
        getDroppedItem: () => ({ name: 'cobblestone' }),
    };
    let removed = false;
    let items = [{ name: 'wooden_pickaxe', type: 816, count: 1 }];
    let clockMs = 0;
    let forward = false;
    let movementPulses = 0;
    const goals = [];
    const bot = {
        version: '1.20.4',
        entity: {
            position: new Vec3(124.43808494193001, 140, -36.47195326706993),
            onGround: true,
        },
        entities: { [drop.id]: drop },
        inventory: { items: () => items },
        blockAt(position) {
            if (position.x === target.x && position.y === target.y && position.z === target.z) {
                return removed
                    ? { name: 'air', type: 0, boundingBox: 'empty', position: target }
                    : { name: 'stone', type: 1, boundingBox: 'block', drops: [35], position: target };
            }
            if (position.x === target.x && position.y === target.y - 1 && position.z === target.z) {
                return { name: 'stone', type: 1, boundingBox: 'block', position };
            }
            return { name: 'air', type: 0, boundingBox: 'empty', position };
        },
        async dig() {
            removed = true;
        },
        async lookAt() {},
        setControlState(name, value) {
            if (name === 'forward') forward = value;
        },
        pathfinder: {
            async goto(goal) {
                goals.push(goal);
            },
            stop() {},
        },
    };
    preload.installPathfinderGoalCompletion(bot, async (ms) => {
        clockMs += Number(ms) || 0;
        if (forward) {
            movementPulses += 1;
            if (movementPulses === 2) {
                bot.entity.position = new Vec3(target.x + 0.5, target.y, target.z + 0.5);
                items = [...items, { name: 'cobblestone', count: 1 }];
            }
        }
    });
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
    assert.strictEqual(result.block_removed, true);
    assert.strictEqual(result.pickup_observed, true);
    assert.deepStrictEqual(result.pickup_inventory_delta, { cobblestone: 1 });
    assert.strictEqual(goals.length, 1);
    assert.strictEqual(goals[0] instanceof pathfinderModule.goals.GoalNear, true);
    assert.strictEqual(result.pickup_collection.direct_navigation.pathfinder_resolved, true);
    assert.strictEqual(result.pickup_collection.direct_navigation.completion_grounded, true);
    assert.strictEqual(result.pickup_collection.fallback_attempt_count, 0);
    assert.strictEqual(result.pickup_collection.fallback_navigation, undefined);
    assert.strictEqual(result.pickup_collection.completion_grounded_by, 'inventory_delta');
    assert.strictEqual(movementPulses, 2);
    assert.strictEqual(goals[0].isEnd(bot.entity.position.floored()), true);
    console.log('PASS: exact GoalNear reaches the clear foot cell and collects cobblestone');
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
    bot.loadPlugin(pathfinderModule.pathfinder);
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
    assert.strictEqual(typeof bot.pathfinder?.goto, 'function');
    assert.strictEqual(bot.pathfinder.goto.name, 'sp003GroundedGoto');
    assert.strictEqual(bot.pathfinder.stop.name, 'sp003StopAndDrain');
    assert.strictEqual(
        preload.pathfinderStopDrainStatus(bot).policyId,
        'sp003-pathfinder-stop-drain-v1',
    );
    console.log('PASS: real Mineflayer lifecycle installs settlement and goal grounding');
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
    testPreloadPatchesPathfinderPluginOnceWithinItsNodeProcess();
    testStopDrainPolicyRequiresTheDependencyLifecycleSurface();
    await testStopDrainConsumesDeferredStopBeforeTheNextGoto();
    await testStopDrainStillRejectsAnActiveGoto();
    await testPickupTimeoutCannotPoisonTheFollowingMove();
    await testFalseResolvedGoalBlockUsesBoundedClearDownStep();
    await testFalseResolvedExactUnitGoalNearUsesBoundedClearDownStep();
    await testMoveToHandlerCannotAcceptPhase109PositionOutsideExactGoal();
    await testGoalBlockGroundingRejectsUnprovenGeometryAndMissingControls();
    await testGoalBlockGroundingStopsAfterExactPulseBudget();
    await testGoalBlockGroundingPreservesOtherGoalsAndOriginalFailures();
    await testPickupClosesThroughGroundedExactGoalNear();
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
