#!/usr/bin/env node
/**
 * Read-only live dashboard for one M4 Mineflayer episode.
 *
 * It opens independent bridge connections and exposes no control endpoint.
 */

const fs = require('fs');
const http = require('http');
const net = require('net');
const path = require('path');

function arg(name, fallback = '') {
    const index = process.argv.indexOf(`--${name}`);
    return index >= 0 && index + 1 < process.argv.length
        ? process.argv[index + 1]
        : fallback;
}

function bridgeRequest(command, params = {}, options = {}) {
    const host = options.host || '127.0.0.1';
    const port = Number(options.port || 30000);
    const timeoutMs = Number(options.timeoutMs || 2000);
    return new Promise((resolve, reject) => {
        const socket = net.createConnection({ host, port });
        let buffer = '';
        const finish = (error, value) => {
            socket.destroy();
            error ? reject(error) : resolve(value);
        };
        socket.setTimeout(timeoutMs, () => finish(new Error('bridge timeout')));
        socket.on('connect', () => {
            socket.write(`${JSON.stringify({ command, params })}\n`);
        });
        socket.on('data', chunk => {
            buffer += chunk.toString('utf8');
            const newline = buffer.indexOf('\n');
            if (newline < 0) return;
            try {
                finish(null, JSON.parse(buffer.slice(0, newline)));
            } catch (error) {
                finish(error);
            }
        });
        socket.on('error', error => finish(error));
    });
}

function recentEvents(evidenceDir, limit = 24) {
    try {
        const candidates = fs.readdirSync(evidenceDir)
            .filter(name => /^session_.+\.jsonl$/.test(name))
            .map(name => path.join(evidenceDir, name));
        if (!candidates.length) return [];
        const latest = candidates.sort((a, b) =>
            fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs
        )[0];
        const bytes = fs.readFileSync(latest);
        const tail = bytes.subarray(Math.max(0, bytes.length - 160000)).toString('utf8');
        return tail.split(/\r?\n/)
            .filter(Boolean)
            .slice(-limit)
            .map(line => {
                try {
                    const event = JSON.parse(line);
                    const data = event.data || {};
                    const action = data.action || {};
                    return {
                        elapsed_s: event.elapsed_s,
                        type: event.type,
                        goal: data.goal || '',
                        status: data.status || '',
                        action: action.type || '',
                        reasoning: data.reasoning || data.error || '',
                    };
                } catch (_error) {
                    return null;
                }
            })
            .filter(Boolean);
    } catch (_error) {
        return [];
    }
}

async function snapshot(options) {
    const request = (command, params = {}) => bridgeRequest(command, params, options);
    const calls = await Promise.allSettled([
        request('health'),
        request('get_player_state'),
        request('get_inventory'),
        request('get_nearby_blocks', { radius: 8 }),
        request('get_nearby_entities', { radius: 16 }),
        request('get_time'),
        request('get_weather'),
        request('get_biome'),
    ]);
    const value = index => calls[index].status === 'fulfilled' ? calls[index].value : {};
    return {
        generated_at: new Date().toISOString(),
        episode_id: options.episodeId,
        health: value(0),
        player: value(1),
        inventory: value(2).items || [],
        blocks: value(3).blocks || [],
        entities: value(4).entities || [],
        time: value(5).time,
        weather: value(6).weather,
        biome: value(7).biome,
        events: recentEvents(options.evidenceDir),
        read_only: true,
    };
}

function renderHtml(episodeId) {
    const safeEpisode = JSON.stringify(String(episodeId || 'M4'));
    return `<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>M4 Live Observer</title>
<style>
:root{color-scheme:dark;font:14px system-ui;background:#07111f;color:#e8f0ff}
body{margin:0;padding:18px;background:radial-gradient(circle at top,#142943,#07111f 55%)}
h1{margin:0 0 4px;font-size:22px} .muted{color:#91a4bc}.grid{display:grid;grid-template-columns:minmax(420px,1.1fr) minmax(360px,.9fr);gap:14px;margin-top:14px}
.card{background:#0d1b2dcc;border:1px solid #29415f;border-radius:12px;padding:14px;box-shadow:0 12px 30px #0006}
#map{width:100%;height:520px;background:#050a11;border-radius:9px}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.stat{background:#13263d;padding:9px;border-radius:8px}
.inventory{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}.chip{background:#1b3656;border:1px solid #355a82;padding:5px 8px;border-radius:999px}
.events{max-height:440px;overflow:auto}.event{padding:7px;border-bottom:1px solid #243a55}.action{color:#63d7ff}.goal{color:#8ef0a7}.bad{color:#ff8a8a}
@media(max-width:900px){.grid{grid-template-columns:1fr}#map{height:420px}}
</style></head>
<body><h1>M4 Live Observer</h1><div class="muted" id="episode"></div>
<div class="grid"><section class="card"><canvas id="map" width="720" height="520"></canvas></section>
<section class="card"><div class="stats" id="stats"></div><div class="inventory" id="inventory"></div><div class="events" id="events"></div></section></div>
<script>
const episode=${safeEpisode};document.querySelector('#episode').textContent=episode+' · read-only · no control channel';
const colors={oak_log:'#9a6a35',stone:'#6f7b86',cobblestone:'#7e8792',coal_ore:'#34383e',iron_ore:'#b8886d',crafting_table:'#b7762f',furnace:'#59636f',water:'#3282d8',grass_block:'#4b9b4b',dirt:'#765336'};
function esc(v){return String(v??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function draw(s){const c=document.querySelector('#map'),x=c.getContext('2d');x.clearRect(0,0,c.width,c.height);x.fillStyle='#050a11';x.fillRect(0,0,c.width,c.height);
 const p=s.player?.position||s.health?.position||{x:0,y:0,z:0},scale=25,cx=c.width/2,cy=c.height/2;
 for(const b of s.blocks||[]){const q=b.position||{},dx=(q.x-p.x)*scale,dz=(q.z-p.z)*scale;if(Math.abs(dx)>cx||Math.abs(dz)>cy)continue;x.fillStyle=colors[b.name]||'#46566a';x.fillRect(cx+dx-10,cy+dz-10,20,20)}
 for(const e of s.entities||[]){const q=e.position||{},dx=(q.x-p.x)*scale,dz=(q.z-p.z)*scale;x.fillStyle=e.hostile?'#ff4f5e':'#ffd166';x.beginPath();x.arc(cx+dx,cy+dz,6,0,Math.PI*2);x.fill()}
 x.save();x.translate(cx,cy);x.rotate(-(Number(s.player?.yaw)||0));x.fillStyle='#5de1ff';x.beginPath();x.moveTo(0,-14);x.lineTo(10,11);x.lineTo(0,7);x.lineTo(-10,11);x.closePath();x.fill();x.restore();
 x.fillStyle='#d9e7f7';x.font='13px system-ui';x.fillText('top-down nearby machine state',12,20)}
function render(s){draw(s);const p=s.player||{};document.querySelector('#stats').innerHTML=[
 ['Health',p.health],['Food',p.food],['Time',s.time],['Biome',s.biome],['Weather',s.weather],['Position',p.position?Object.values(p.position).map(v=>Number(v).toFixed(1)).join(', '):'—']
 ].map(v=>'<div class="stat"><b>'+esc(v[0])+'</b><br>'+esc(v[1]??'—')+'</div>').join('');
 document.querySelector('#inventory').innerHTML=(s.inventory||[]).map(i=>'<span class="chip">'+esc(i.name)+' × '+esc(i.count)+'</span>').join('')||'<span class="muted">empty inventory</span>';
 document.querySelector('#events').innerHTML=(s.events||[]).slice().reverse().map(e=>'<div class="event"><span class="muted">'+esc(e.elapsed_s??'')+'s · '+esc(e.type)+'</span> '+(e.action?'<span class="action">'+esc(e.action)+'</span> ':'')+(e.goal?'<span class="goal">'+esc(e.goal)+'</span> ':'')+'<div>'+esc(e.reasoning||e.status||'')+'</div></div>').join('')}
async function poll(){try{const r=await fetch('/api/snapshot',{cache:'no-store'});render(await r.json())}catch(e){document.querySelector('#events').innerHTML='<div class="bad">'+esc(e)+'</div>'}}
poll();setInterval(poll,1000);
</script></body></html>`;
}

function start() {
    const options = {
        host: arg('bridge-host', '127.0.0.1'),
        port: Number(arg('bridge-port', '30000')),
        observerPort: Number(arg('observer-port', '30080')),
        episodeId: arg('episode-id', 'M4'),
        evidenceDir: path.resolve(arg('evidence-dir', 'logs/benchmarks/m4')),
    };
    const server = http.createServer(async (request, response) => {
        response.setHeader('Cache-Control', 'no-store');
        if (request.url === '/api/snapshot') {
            response.setHeader('Content-Type', 'application/json; charset=utf-8');
            try {
                response.end(JSON.stringify(await snapshot(options)));
            } catch (error) {
                response.statusCode = 503;
                response.end(JSON.stringify({ error: error.message, read_only: true }));
            }
            return;
        }
        if (request.url === '/' || request.url === '/index.html') {
            response.setHeader('Content-Type', 'text/html; charset=utf-8');
            response.end(renderHtml(options.episodeId));
            return;
        }
        response.statusCode = 404;
        response.end('not found');
    });
    server.listen(options.observerPort, '127.0.0.1', () => {
        console.log(`M4 observer listening on http://127.0.0.1:${options.observerPort}/`);
    });
}

if (require.main === module) {
    if (process.argv.includes('--check')) {
        console.log(JSON.stringify({ ok: true, read_only: true, dependencies: ['node:http', 'node:net'] }));
    } else {
        start();
    }
}

module.exports = { bridgeRequest, recentEvents, renderHtml, snapshot };
