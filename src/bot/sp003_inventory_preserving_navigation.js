'use strict';

const POLICY_ID = 'sp003-inventory-preserving-navigation-v1';
const PATCH_MARK = Symbol.for('singularity.sp003.inventoryPreservingNavigation');
const pathfinderModule = require('mineflayer-pathfinder');

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

if (!pathfinderModule[PATCH_MARK]) {
    const OriginalMovements = pathfinderModule.Movements;
    class SP003InventoryPreservingMovements extends OriginalMovements {
        constructor(...args) {
            super(...args);
            hardenMovements(this);
        }
    }
    pathfinderModule.Movements = SP003InventoryPreservingMovements;
    pathfinderModule[PATCH_MARK] = Object.freeze({
        policyId: POLICY_ID,
        originalMovements: OriginalMovements,
        patchedMovements: SP003InventoryPreservingMovements,
    });
}

module.exports = {
    POLICY_ID,
    hardenMovements,
    status: pathfinderModule[PATCH_MARK],
};
