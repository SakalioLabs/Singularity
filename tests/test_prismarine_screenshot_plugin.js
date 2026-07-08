const assert = require('assert');

const plugin = require('../src/bot/screenshot_plugin_prismarine_viewer');

function testCameraTargetFromYawPitchLooksForward() {
    const target = plugin.cameraTargetFromYawPitch({ x: 10, y: 64, z: 10 }, 0, 0, 8);

    assert.strictEqual(target.x, 10);
    assert.strictEqual(target.y, 64);
    assert.strictEqual(target.z, 18);
    console.log('PASS: Prismarine screenshot camera target follows yaw/pitch');
}

function testOutputFormatDefaultsToPng() {
    assert.strictEqual(plugin.getOutputFormat('capture.png'), 'png');
    assert.strictEqual(plugin.getOutputFormat('capture.jpg'), 'jpeg');
    assert.strictEqual(plugin.getOutputFormat('capture.jpeg'), 'jpeg');
    assert.strictEqual(plugin.getOutputFormat('capture'), 'png');
    console.log('PASS: Prismarine screenshot output format detection works');
}

function testMissingRendererDependenciesHaveActionableError() {
    assert.throws(
        () => plugin.loadRendererDependencies((name) => {
            throw new Error(`Cannot find module '${name}'`);
        }),
        (error) => {
            assert.match(error.message, /prismarine-viewer/);
            assert.match(error.message, /node-canvas-webgl/);
            assert.match(error.message, /npm install prismarine-viewer three PrismarineJS\/node-canvas-webgl/);
            assert.match(error.message, /WSL or Docker/);
            return true;
        }
    );
    console.log('PASS: Prismarine screenshot plugin reports missing optional dependencies');
}

function testInspectRendererDependenciesReportsStatus() {
    const report = plugin.inspectRendererDependencies((name) => ({ name }));

    assert.strictEqual(report.ok, true);
    assert.strictEqual(report.plugin, 'prismarine_viewer');
    assert.strictEqual(report.checks.length, plugin.REQUIRED_RENDERER_PACKAGES.length);
    assert.ok(report.checks.every(check => check.status === 'pass'));

    const missingReport = plugin.inspectRendererDependencies((name) => {
        if (name === 'three') {
            throw new Error('missing three');
        }
        return { name };
    });
    assert.strictEqual(missingReport.ok, false);
    assert.ok(missingReport.checks.some(check => check.name === 'three' && check.status === 'missing'));
    assert.match(missingReport.install_command, /node-canvas-webgl/);
    console.log('PASS: Prismarine screenshot plugin dependency inspection reports status');
}

testCameraTargetFromYawPitchLooksForward();
testOutputFormatDefaultsToPng();
testMissingRendererDependenciesHaveActionableError();
testInspectRendererDependenciesReportsStatus();
console.log('\nPrismarine screenshot plugin tests PASSED');
