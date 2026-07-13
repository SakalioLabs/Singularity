const assert = require('assert');
const { Vec3 } = require('vec3');

const {
    createMoveToHandler,
    createRecoverNavigationHandler,
    createWalkToHandler,
    navigationDistance,
    navigationTimeoutMs,
    prioritizeTreeResults,
} = require('../src/bot/bot_server');

function mockBot(position = new Vec3(0, 64, 0)) {
    const bot = {
        entity: { position },
        pathfinder: {
            stopped: false,
            async goto(goal) {
                bot.entity.position = new Vec3(goal.target.x, goal.target.y, goal.target.z);
            },
            stop() {
                this.stopped = true;
            },
        },
    };
    return bot;
}

function deferredStopBot(failFirstNavigation = true) {
    const bot = {
        entity: { position: new Vec3(0, 64, 0) },
        controlClearCount: 0,
        clearControlStates() {
            this.controlClearCount += 1;
        },
    };
    let firstNavigation = Boolean(failFirstNavigation);
    bot.pathfinder = {
        goal: null,
        moving: false,
        pendingStop: false,
        gotoCount: 0,
        async goto(goal) {
            this.gotoCount += 1;
            if (this.pendingStop) {
                this.setGoal(goal);
                const error = new Error('Path was stopped before it could be completed! Thus, the desired goal was not reached.');
                error.name = 'PathStopped';
                throw error;
            }
            this.goal = goal;
            this.moving = true;
            if (firstNavigation) {
                firstNavigation = false;
                const error = new Error('navigation timed out after 60000ms');
                error.name = 'Timeout';
                throw error;
            }
            bot.entity.position = new Vec3(goal.target.x, goal.target.y, goal.target.z);
            this.goal = null;
            this.moving = false;
        },
        stop() {
            this.pendingStop = true;
        },
        setGoal(goal) {
            if (this.pendingStop) {
                this.pendingStop = false;
                this.goal = null;
                this.moving = false;
                return;
            }
            this.goal = goal;
            this.moving = goal !== null;
        },
        isMoving() {
            return this.moving;
        },
    };
    return bot;
}

function goalFactory(target, tolerance) {
    return { target, tolerance };
}

async function testMoveToSucceedsOnlyInsideTolerance() {
    const bot = mockBot();
    const handler = createMoveToHandler(
        () => ({ bot, botReady: true }),
        { goalFactory },
    );

    const result = await handler({ x: 12, y: 64, z: -4, tolerance: 2 });

    assert.strictEqual(result.success, true);
    assert.strictEqual(result.reached, true);
    assert.ok(result.distance_to_target <= result.tolerance);
    console.log('PASS: move_to succeeds after pathfinder reaches target tolerance');
}

async function testMoveToRejectsFalseSuccessfulPathfinderCompletion() {
    const bot = mockBot();
    bot.pathfinder.goto = async () => {};
    const handler = createMoveToHandler(
        () => ({ bot, botReady: true }),
        { goalFactory },
    );

    const result = await handler({ x: 20, z: 0, tolerance: 2 });

    assert.strictEqual(result.success, false);
    assert.strictEqual(result.reached, false);
    assert.match(result.error, /without reaching/);
    assert.ok(result.distance_to_target > result.tolerance);
    console.log('PASS: move_to rejects pathfinder completion outside target tolerance');
}

async function testMoveToAcceptsMeasuredArrivalAfterLatePathfinderError() {
    const bot = mockBot();
    bot.pathfinder.goto = async () => {
        bot.entity.position = new Vec3(9, 64, 0);
        throw new Error('late pathfinder failure');
    };
    const handler = createMoveToHandler(
        () => ({ bot, botReady: true }),
        { goalFactory },
    );

    const result = await handler({ x: 10, z: 0, tolerance: 2 });

    assert.strictEqual(result.success, true);
    assert.strictEqual(result.reached, true);
    assert.ok(result.distance_to_target <= result.tolerance);
    assert.match(result.pathfinder_warning, /late pathfinder failure/);
    console.log('PASS: move_to uses measured arrival after a late pathfinder error');
}

async function testM4MoveFailureDrainsDeferredPathfinderStopWithoutChangingLegacy() {
    const strictBot = deferredStopBot();
    const strictHandler = createMoveToHandler(
        () => ({ bot: strictBot, botReady: true }),
        { goalFactory },
    );

    const failed = await strictHandler({
        x: 10,
        y: 64,
        z: 0,
        recover_pathfinder_on_failure: true,
    });
    const recovered = await strictHandler({
        x: 10,
        y: 64,
        z: 0,
        recover_pathfinder_on_failure: true,
    });

    assert.strictEqual(failed.success, false);
    assert.strictEqual(failed.navigation_recovery.policy_id, 'm4-deadline-bound-pathfinder-readiness-v1');
    assert.strictEqual(failed.navigation_recovery.pathfinder_ready, true);
    assert.strictEqual(strictBot.pathfinder.pendingStop, false);
    assert.strictEqual(recovered.success, true);
    assert.strictEqual(recovered.reached, true);

    const legacyBot = deferredStopBot();
    const legacyHandler = createMoveToHandler(
        () => ({ bot: legacyBot, botReady: true }),
        { goalFactory },
    );
    const legacyFailure = await legacyHandler({ x: 10, y: 64, z: 0 });
    const legacyCascade = await legacyHandler({ x: 10, y: 64, z: 0 });

    assert.strictEqual(legacyFailure.success, false);
    assert.strictEqual(legacyFailure.navigation_recovery, undefined);
    assert.strictEqual(legacyCascade.success, false);
    assert.match(legacyCascade.error, /Path was stopped/);
    assert.strictEqual(legacyBot.pathfinder.pendingStop, true);
    console.log('PASS: strict M4 drains deferred pathfinder stop while legacy behavior is unchanged');
}

async function testNavigationRecoveryCommandConfirmsReadinessBeforeNextMove() {
    const bot = deferredStopBot(false);
    bot.pathfinder.stop();
    const recoveryHandler = createRecoverNavigationHandler(
        () => ({ bot, botReady: true }),
        { yieldEventLoop: async () => {} },
    );
    const report = await recoveryHandler({ trigger_command: 'move_to' });

    assert.strictEqual(report.success, true);
    assert.strictEqual(report.policy_id, 'm4-deadline-bound-pathfinder-readiness-v1');
    assert.strictEqual(report.pathfinder_ready, true);
    assert.strictEqual(report.goal_cleared, true);
    assert.strictEqual(report.movement_stopped, true);
    assert.strictEqual(report.control_states_cleared, true);
    assert.strictEqual(report.command_replayed, false);
    assert.strictEqual(report.world_mutation, false);
    assert.strictEqual(report.reset_pass_count, 2);
    assert.strictEqual(bot.pathfinder.pendingStop, false);

    const moveHandler = createMoveToHandler(
        () => ({ bot, botReady: true }),
        { goalFactory },
    );
    const nextMove = await moveHandler({
        x: 6,
        y: 64,
        z: 0,
        recover_pathfinder_on_failure: true,
    });
    assert.strictEqual(nextMove.success, true);
    assert.strictEqual(nextMove.reached, true);
    console.log('PASS: recovery command confirms clean pathfinder state before the next move');
}

async function testMoveToRejectsInvalidCoordinatesAndUnavailableBot() {
    const bot = mockBot();
    const handler = createMoveToHandler(
        () => ({ bot, botReady: true }),
        { goalFactory },
    );
    const notReady = createMoveToHandler(
        () => ({ bot, botReady: false }),
        { goalFactory },
    );

    const invalid = await handler({ x: null, z: 4 });
    const unavailable = await notReady({ x: 1, z: 1 });

    assert.strictEqual(invalid.success, false);
    assert.match(invalid.error, /finite x and z/);
    assert.strictEqual(unavailable.success, false);
    assert.match(unavailable.error, /not ready/);
    console.log('PASS: move_to rejects invalid coordinates and unavailable bot state');
}

async function testMoveToSelectsHorizontalOrThreeDimensionalGoal() {
    const bot = mockBot();
    let observedGoal = null;
    bot.pathfinder.goto = async (goal) => {
        observedGoal = goal;
        bot.entity.position = new Vec3(3, 70, 4);
    };
    const handler = createMoveToHandler(() => ({ bot, botReady: true }));

    // BotBridge serializes an omitted Python y value as JSON null.
    const horizontal = await handler({ x: 3, y: null, z: 4 });
    assert.strictEqual(horizontal.success, true);
    assert.strictEqual(observedGoal.constructor.name, 'GoalNearXZ');

    bot.entity.position = new Vec3(0, 64, 0);
    const spatial = await handler({ x: 3, y: 70, z: 4 });
    assert.strictEqual(spatial.success, true);
    assert.strictEqual(observedGoal.constructor.name, 'GoalNear');
    console.log('PASS: move_to selects horizontal or three-dimensional pathfinder goals');
}

async function testWalkToUsesHorizontalDistanceUnlessYIsExplicit() {
    const bot = mockBot();
    bot.lookAt = async () => {};
    bot.setControlState = (control, enabled) => {
        if (control === 'forward' && enabled === false) {
            bot.entity.position = new Vec3(3, 80, 4);
        }
    };
    const handler = createWalkToHandler(() => ({ bot, botReady: true }));

    const horizontal = await handler({ x: 3, y: null, z: 4, ms: 1 });
    assert.strictEqual(horizontal.reached, true);
    assert.strictEqual(horizontal.distance_to_target, 0);

    bot.entity.position = new Vec3(0, 64, 0);
    const spatial = await handler({ x: 3, y: 64, z: 4, ms: 1 });
    assert.strictEqual(spatial.reached, false);
    assert.strictEqual(spatial.partial, true);
    assert.ok(spatial.distance_to_target > 2.75);
    console.log('PASS: walk_to distinguishes horizontal and three-dimensional targets');
}

function testNavigationMetricsAreBoundedAndDeterministic() {
    assert.strictEqual(navigationDistance(new Vec3(0, 0, 0), new Vec3(3, 4, 0)), 5);
    assert.strictEqual(navigationDistance(new Vec3(0, 0, 0), new Vec3(3, 40, 4), false), 5);
    assert.strictEqual(navigationTimeoutMs(0), 5000);
    assert.strictEqual(navigationTimeoutMs(1000), 60000);
    assert.strictEqual(navigationTimeoutMs(10, 250), 1000);
    console.log('PASS: navigation distance and timeout metrics are bounded');
}

function testTreeResultsPreserveNearestCandidatePerSpecies() {
    const trees = Array.from({ length: 12 }, (_, index) => ({
        name: 'dark_oak_log',
        position: { x: index, y: 64, z: 0 },
        distance: index + 1,
    }));
    trees.push({
        name: 'oak_log',
        position: { x: 14, y: 64, z: 0 },
        distance: 14,
    });

    const selected = prioritizeTreeResults(trees, 10);

    assert.strictEqual(selected.filter(tree => tree.name === 'dark_oak_log').length, 10);
    assert.strictEqual(selected.filter(tree => tree.name === 'oak_log').length, 1);
    console.log('PASS: tree scan preserves a nearest candidate for every observed species');
}

(async () => {
    await testMoveToSucceedsOnlyInsideTolerance();
    await testMoveToRejectsFalseSuccessfulPathfinderCompletion();
    await testMoveToAcceptsMeasuredArrivalAfterLatePathfinderError();
    await testM4MoveFailureDrainsDeferredPathfinderStopWithoutChangingLegacy();
    await testNavigationRecoveryCommandConfirmsReadinessBeforeNextMove();
    await testMoveToRejectsInvalidCoordinatesAndUnavailableBot();
    await testMoveToSelectsHorizontalOrThreeDimensionalGoal();
    await testWalkToUsesHorizontalDistanceUnlessYIsExplicit();
    testNavigationMetricsAreBoundedAndDeterministic();
    testTreeResultsPreserveNearestCandidatePerSpecies();
    console.log('\nBot server navigation tests PASSED');
})().catch((error) => {
    console.error(error);
    process.exit(1);
});
