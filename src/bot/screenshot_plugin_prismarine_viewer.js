/**
 * Optional prismarine-viewer screenshot plugin for bot_server.js.
 *
 * Runtime dependencies are intentionally optional because node-canvas-webgl can
 * require platform-specific native setup. Install them only for screenshot runs:
 *   npm install prismarine-viewer three PrismarineJS/node-canvas-webgl
 */

const fs = require('fs');
const path = require('path');
const { Worker } = require('worker_threads');

const REQUIRED_RENDERER_PACKAGES = [
    'prismarine-viewer',
    'node-canvas-webgl/lib',
    'three',
    'vec3',
];
const INSTALL_COMMAND = 'npm install prismarine-viewer three PrismarineJS/node-canvas-webgl';
const WINDOWS_HINT = 'On Windows, prefer WSL or Docker for node-canvas-webgl.';

function missingRendererDependencyMessage(missing) {
    return (
        'Missing optional prismarine screenshot dependencies. ' +
        `Install with \`${INSTALL_COMMAND}\`. ` +
        `${WINDOWS_HINT} Missing: ` +
        missing.join('; ')
    );
}

function inspectRendererDependencies(requireFn = require) {
    const checks = [];
    for (const packageName of REQUIRED_RENDERER_PACKAGES) {
        try {
            requireFn(packageName);
            checks.push({
                name: packageName,
                status: 'pass',
                detail: 'available',
            });
        } catch (error) {
            checks.push({
                name: packageName,
                status: 'missing',
                detail: error.message,
            });
        }
    }
    return {
        plugin: 'prismarine_viewer',
        ok: checks.every(check => check.status === 'pass'),
        install_command: INSTALL_COMMAND,
        windows_hint: WINDOWS_HINT,
        checks,
    };
}

function loadRendererDependencies(requireFn = require) {
    const missing = [];
    const loaded = {};
    for (const packageName of REQUIRED_RENDERER_PACKAGES) {
        try {
            loaded[packageName] = requireFn(packageName);
        } catch (error) {
            missing.push(`${packageName}: ${error.message}`);
        }
    }
    if (missing.length) {
        throw new Error(missingRendererDependencyMessage(missing));
    }
    return {
        viewerApi: loaded['prismarine-viewer'].viewer,
        createCanvas: loaded['node-canvas-webgl/lib'].createCanvas,
        THREE: loaded.three,
        Vec3: loaded.vec3.Vec3,
    };
}

function cameraTargetFromYawPitch(position, yaw = 0, pitch = 0, distance = 8) {
    const x = position.x - Math.sin(yaw) * Math.cos(pitch) * distance;
    const y = position.y - Math.sin(pitch) * distance;
    const z = position.z + Math.cos(yaw) * Math.cos(pitch) * distance;
    return { x, y, z };
}

function getOutputFormat(outputPath) {
    const ext = path.extname(String(outputPath || '')).toLowerCase();
    return ext === '.jpg' || ext === '.jpeg' ? 'jpeg' : 'png';
}

function streamToBuffer(stream) {
    return new Promise((resolve, reject) => {
        const chunks = [];
        stream.on('data', chunk => chunks.push(chunk));
        stream.on('error', reject);
        stream.on('end', () => resolve(Buffer.concat(chunks)));
    });
}

class PrismarineScreenshotCamera {
    constructor(bot, dependencies, options = {}) {
        this.bot = bot;
        this.dependencies = dependencies;
        this.viewDistance = Number(options.viewDistance || options.view_distance || 4);
        this.width = Number(options.width || 512);
        this.height = Number(options.height || 512);
        this.renderDelayMs = Number(options.renderDelayMs || options.render_delay_ms || 500);
        this.ready = false;
        this.worldView = null;
        this.viewer = null;
        this.renderer = null;
        this.canvas = null;
    }

    async init(center) {
        const { viewerApi, createCanvas, THREE } = this.dependencies;
        const { Viewer, WorldView } = viewerApi;

        global.Worker = global.Worker || Worker;
        this.canvas = createCanvas(this.width, this.height);
        this.renderer = new THREE.WebGLRenderer({
            canvas: this.canvas,
            preserveDrawingBuffer: true,
        });
        this.renderer.setSize(this.width, this.height, false);
        this.viewer = new Viewer(this.renderer);
        this.viewer.setVersion(this.bot.version);
        this.worldView = new WorldView(this.bot.world, this.viewDistance, center);
        this.viewer.listen(this.worldView);
        this.viewer.camera.aspect = this.width / this.height;
        this.viewer.camera.updateProjectionMatrix();
        await this.worldView.init(center);
        this.ready = true;
    }

    async ensureReady() {
        if (typeof this.bot.waitForChunksToLoad === 'function') {
            await this.bot.waitForChunksToLoad();
        }
        const center = this.bot.entity.position.clone
            ? this.bot.entity.position.clone()
            : new this.dependencies.Vec3(this.bot.entity.position.x, this.bot.entity.position.y, this.bot.entity.position.z);
        if (!this.ready) {
            await this.init(center);
        } else if (this.worldView && typeof this.worldView.updatePosition === 'function') {
            await this.worldView.updatePosition(center);
        }
    }

    async capture(outputPath) {
        if (!this.bot?.entity?.position) {
            return { success: false, error: 'bot entity position is unavailable for screenshot capture' };
        }
        await this.ensureReady();

        const eyeHeight = Number(this.bot.entity.height || 1.62);
        const position = this.bot.entity.position;
        const cameraPosition = {
            x: position.x,
            y: position.y + eyeHeight,
            z: position.z,
        };
        const target = cameraTargetFromYawPitch(
            cameraPosition,
            Number(this.bot.entity.yaw || 0),
            Number(this.bot.entity.pitch || 0),
        );

        this.viewer.camera.position.set(cameraPosition.x, cameraPosition.y, cameraPosition.z);
        this.viewer.camera.lookAt(target.x, target.y, target.z);
        if (this.renderDelayMs > 0) {
            await new Promise(resolve => setTimeout(resolve, this.renderDelayMs));
        }
        this.renderer.render(this.viewer.scene, this.viewer.camera);

        const format = getOutputFormat(outputPath);
        const stream = format === 'jpeg'
            ? this.canvas.createJPEGStream({ quality: 95, progressive: false })
            : this.canvas.createPNGStream();
        const buffer = this.dependencies.viewerApi.getBufferFromStream
            ? await this.dependencies.viewerApi.getBufferFromStream(stream)
            : await streamToBuffer(stream);

        if (outputPath) {
            fs.mkdirSync(path.dirname(path.resolve(outputPath)), { recursive: true });
            fs.writeFileSync(outputPath, buffer);
        }
        return {
            success: true,
            source: 'prismarine_viewer',
            screenshot_path: outputPath,
            buffer: outputPath ? undefined : buffer,
            width: this.width,
            height: this.height,
            format,
        };
    }

    close() {
        if (this.viewer && typeof this.viewer.close === 'function') {
            this.viewer.close();
        }
        this.ready = false;
    }
}

function attach(bot, context = {}) {
    const options = context.options || {};
    const dependencies = loadRendererDependencies();
    const camera = new PrismarineScreenshotCamera(bot, dependencies, options);
    bot.prismarineScreenshotCamera = camera;
    return {
        captureScreenshot: outputPath => camera.capture(outputPath),
        close: () => camera.close(),
    };
}

module.exports = attach;
module.exports.attach = attach;
module.exports.attachScreenshotPlugin = attach;
module.exports.cameraTargetFromYawPitch = cameraTargetFromYawPitch;
module.exports.getOutputFormat = getOutputFormat;
module.exports.inspectRendererDependencies = inspectRendererDependencies;
module.exports.loadRendererDependencies = loadRendererDependencies;
module.exports.missingRendererDependencyMessage = missingRendererDependencyMessage;
module.exports.PrismarineScreenshotCamera = PrismarineScreenshotCamera;
module.exports.REQUIRED_RENDERER_PACKAGES = REQUIRED_RENDERER_PACKAGES;
module.exports.INSTALL_COMMAND = INSTALL_COMMAND;
module.exports.WINDOWS_HINT = WINDOWS_HINT;

if (require.main === module) {
    if (process.argv.includes('--check')) {
        const report = inspectRendererDependencies();
        console.log(JSON.stringify(report, null, 2));
        process.exit(report.ok ? 0 : 1);
    }
    console.log(JSON.stringify({
        plugin: 'prismarine_viewer',
        usage: 'node src/bot/screenshot_plugin_prismarine_viewer.js --check',
        install_command: INSTALL_COMMAND,
        windows_hint: WINDOWS_HINT,
    }, null, 2));
}
