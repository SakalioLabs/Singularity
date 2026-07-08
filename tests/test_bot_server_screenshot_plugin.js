const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const {
    attachScreenshotPlugin,
    createCaptureScreenshotHandler,
    imageBytesFromCaptureResult,
} = require('../src/bot/bot_server');

async function testScreenshotPluginWritesRendererBytes() {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'singularity-screenshot-plugin-'));
    const pluginPath = path.join(tmpDir, 'fake_plugin.js');
    const outputPath = path.join(tmpDir, 'capture.png');
    fs.writeFileSync(pluginPath, `
module.exports = function attach(bot) {
    return async function captureScreenshot(outputPath) {
        return {
            source: 'fake_screenshot_plugin',
            buffer: Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00])
        };
    };
};
`);

    const bot = { entity: { position: { x: 0, y: 64, z: 0 } } };
    const status = attachScreenshotPlugin(bot, pluginPath);
    assert.strictEqual(status.loaded, true);
    assert.strictEqual(status.supported, true);
    assert.strictEqual(typeof bot.captureScreenshot, 'function');

    const handler = createCaptureScreenshotHandler(() => ({ bot, botReady: true }));
    const result = await handler({ path: outputPath });

    assert.strictEqual(result.success, true);
    assert.strictEqual(result.supported, true);
    assert.strictEqual(result.source, 'fake_screenshot_plugin');
    assert.strictEqual(result.screenshot_path, outputPath);
    assert.strictEqual(result.file_exists, true);
    assert.strictEqual(result.file_size, 10);
    assert.deepStrictEqual(fs.readFileSync(outputPath).subarray(0, 8), Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]));
    console.log('PASS: Screenshot plugin writes renderer bytes');
}

async function testScreenshotCaptureReportsUnsupportedWithoutPlugin() {
    const bot = { entity: { position: { x: 0, y: 64, z: 0 } } };
    const handler = createCaptureScreenshotHandler(() => ({ bot, botReady: true }));
    const result = await handler({ path: 'unused.png' });

    assert.strictEqual(result.success, false);
    assert.strictEqual(result.supported, false);
    assert.match(result.error, /renderer plugin/);
    console.log('PASS: Screenshot capture reports unsupported without plugin');
}

function testImageBytesFromBase64Result() {
    const bytes = imageBytesFromCaptureResult({ image_base64: Buffer.from('png').toString('base64') });
    assert.ok(Buffer.isBuffer(bytes));
    assert.strictEqual(bytes.toString('utf-8'), 'png');
    console.log('PASS: Screenshot capture accepts base64 renderer output');
}

(async () => {
    await testScreenshotPluginWritesRendererBytes();
    await testScreenshotCaptureReportsUnsupportedWithoutPlugin();
    testImageBytesFromBase64Result();
    console.log('\nBot server screenshot plugin tests PASSED');
})().catch((error) => {
    console.error(error);
    process.exit(1);
});
