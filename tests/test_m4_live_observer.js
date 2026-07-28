const assert = require('assert');
const observer = require('../scripts/m4_live_observer.js');

const html = observer.renderHtml('m4_episode_test');
assert.ok(html.includes('M4 Live Observer'));
assert.ok(html.includes('m4_episode_test'));
assert.ok(html.includes('read-only'));
assert.ok(html.includes('/api/snapshot'));
assert.ok(!html.includes('/api/action'));
assert.deepStrictEqual(observer.recentEvents('__missing_m4_observer_dir__'), []);

console.log('PASS: M4 live observer is read-only and renders its episode binding');
