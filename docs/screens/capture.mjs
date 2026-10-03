#!/usr/bin/env node
// Capture README screenshots from a manifest (Quoin spec, GitHub pages rule 8).
// Each shot is the page at 340 CSS px and device scale 2. The 680 px PNG
// shows at 400 px beside a Quoin SVG; on a 309 px phone column, 11 px page
// text still projects to 10 px (rule 4).
//
// Usage: node capture.mjs <docs/screens/capture.json> [--only <out>]
// Manifest: {"root": "../..", "shots": [{"out": "app-light.png", "url": "index.html",
//   "scheme": "light", "height": 600 | "height_from": "../diagrams/x-light.svg",
//   "scroll": "#selector", "before": "<js run in the page>", "wait": 300}]}
// A relative url is a file under root; http(s) urls load as given. Writes each PNG
// next to the manifest and a receipt, captured.txt. Exit 1 when a shot's smallest
// visible text is under 11 CSS px or its PNG is over 500 KB.
// Needs Google Chrome; node built-ins only. The CDP pipe driver is the one in
// check-pages.mjs, copied so this file runs on its own in a public repo.

import { spawn, execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const WIDTH = 340;
const SCALE = 2;
const MIN_TEXT = 11;
const MAX_BYTES = 500 * 1024;

class Cdp {
  constructor(child) {
    this.write = child.stdio[3];
    this.read = child.stdio[4];
    this.read.setEncoding('utf8');
    this.buffer = '';
    this.next = 1;
    this.pending = new Map();
    this.waiters = [];
    this.read.on('data', (chunk) => this.consume(chunk));
  }

  consume(chunk) {
    this.buffer += chunk;
    let i;
    while ((i = this.buffer.indexOf('\0')) >= 0) {
      const raw = this.buffer.slice(0, i);
      this.buffer = this.buffer.slice(i + 1);
      if (!raw) continue;
      const msg = JSON.parse(raw);
      if (msg.id && this.pending.has(msg.id)) {
        const p = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        clearTimeout(p.timer);
        if (msg.error) p.reject(new Error(`${p.method}: ${msg.error.message}`));
        else p.resolve(msg.result || {});
        continue;
      }
      for (const w of [...this.waiters]) {
        if (w.method === msg.method && (!w.session || w.session === msg.sessionId)) {
          this.waiters.splice(this.waiters.indexOf(w), 1);
          clearTimeout(w.timer);
          w.resolve(msg.params || {});
        }
      }
    }
  }

  send(method, params = {}, session, timeout = 30000) {
    const id = this.next++;
    const msg = { id, method, params };
    if (session) msg.sessionId = session;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error(`${method}: timed out`)); }, timeout);
      this.pending.set(id, { method, resolve, reject, timer });
      this.write.write(`${JSON.stringify(msg)}\0`);
    });
  }

  waitFor(method, session, timeout = 30000) {
    return new Promise((resolve, reject) => {
      const w = { method, session, resolve, reject };
      w.timer = setTimeout(() => { this.waiters.splice(this.waiters.indexOf(w), 1); reject(new Error(`${method}: event timed out`)); }, timeout);
      this.waiters.push(w);
    });
  }
}

async function evaluate(cdp, session, expression) {
  const r = await cdp.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true }, session);
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
  return r.result?.value;
}

// Runs in the page: the smallest font size among text visible in the viewport.
const MIN_FONT = `(() => {
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let min = Infinity, node;
  while ((node = w.nextNode())) {
    if (!node.textContent.trim()) continue;
    const el = node.parentElement, s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none' || +s.opacity === 0) continue;
    const range = document.createRange(); range.selectNodeContents(node);
    const r = range.getBoundingClientRect();
    if (!r.width || !r.height || r.bottom <= 0 || r.top >= innerHeight || r.right <= 0 || r.left >= innerWidth) continue;
    min = Math.min(min, parseFloat(s.fontSize));
  }
  return min === Infinity ? null : min;
})()`;

const STILL = `(() => { const s = document.createElement('style');
  s.textContent = '*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}';
  document.head.appendChild(s); })()`;

function viewboxHeight(file) {
  const m = fs.readFileSync(file, 'utf8').match(/viewBox="\s*[\d.-]+[\s,]+[\d.-]+[\s,]+([\d.]+)[\s,]+([\d.]+)\s*"/);
  if (!m) throw new Error(`${file}: no viewBox`);
  return Math.round((+m[2] * WIDTH) / +m[1]);
}

async function main() {
  const argv = process.argv.slice(2);
  const oi = argv.indexOf('--only');
  const only = oi >= 0 ? argv.splice(oi, 2)[1] : null;
  const manifestPath = path.resolve(argv[0] || 'docs/screens/capture.json');
  const dir = path.dirname(manifestPath);
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  const root = path.resolve(dir, manifest.root || '.');
  const shots = manifest.shots.filter((s) => !only || s.out === only);

  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'quoin-capture-'));
  const child = spawn(CHROME, ['--headless=new', '--remote-debugging-pipe', '--disable-gpu', '--hide-scrollbars',
    '--no-first-run', '--no-default-browser-check', '--disable-sync', '--font-render-hinting=none',
    `--user-data-dir=${profile}`, 'about:blank'], { stdio: ['ignore', 'ignore', 'pipe', 'pipe', 'pipe'] });
  const cdp = new Cdp(child);
  const { product } = await cdp.send('Browser.getVersion');
  const { targetInfos } = await cdp.send('Target.getTargets');
  const target = targetInfos.find((t) => t.type === 'page') || await cdp.send('Target.createTarget', { url: 'about:blank' });
  const { sessionId: s } = await cdp.send('Target.attachToTarget', { targetId: target.targetId, flatten: true });
  await cdp.send('Page.enable', {}, s);
  await cdp.send('Runtime.enable', {}, s);

  const receipt = [];
  const failures = [];
  for (const shot of shots) {
    const height = shot.height_from ? viewboxHeight(path.resolve(dir, shot.height_from)) : shot.height;
    const [file, hash = ''] = shot.url.split(/(?=#)/);
    const url = /^https?:/.test(shot.url) ? shot.url : pathToFileURL(path.resolve(root, file)).href + hash;
    await cdp.send('Emulation.setDeviceMetricsOverride',
      { width: WIDTH, height, deviceScaleFactor: SCALE, mobile: true }, s);
    await cdp.send('Emulation.setEmulatedMedia',
      { features: [{ name: 'prefers-color-scheme', value: shot.scheme || 'light' }] }, s);
    for (const u of ['about:blank', url]) {  // blank first, so a hash-only change still loads
      const loaded = cdp.waitFor('Page.loadEventFired', s, 45000);
      await cdp.send('Page.navigate', { url: u }, s);
      await loaded;
    }
    await evaluate(cdp, s, STILL);
    await evaluate(cdp, s, 'document.fonts.ready.then(() => true)');
    if (shot.before) await evaluate(cdp, s, `(async () => { ${shot.before} })()`);
    if (shot.scroll) {
      await evaluate(cdp, s, `(() => { const e = document.querySelector(${JSON.stringify(shot.scroll)});
        if (!e) throw new Error('scroll target ${shot.scroll} not found'); e.scrollIntoView({ block: 'start' }); })()`);
    }
    await new Promise((r) => setTimeout(r, shot.wait ?? 300));
    const minText = await evaluate(cdp, s, MIN_FONT);
    const { data } = await cdp.send('Page.captureScreenshot', { format: 'png' }, s);
    const out = path.join(dir, shot.out);
    fs.writeFileSync(out, Buffer.from(data, 'base64'));
    const bytes = fs.statSync(out).size;
    const line = `${shot.out}: ${WIDTH * SCALE}x${height * SCALE} px, ${(bytes / 1024).toFixed(0)} KB, `
      + `smallest text ${minText} CSS px, ${shot.scheme || 'light'}, ${shot.url}`;
    receipt.push(line);
    if (minText !== null && minText < MIN_TEXT) failures.push(`${shot.out}: smallest text ${minText} CSS px, under ${MIN_TEXT}`);
    if (bytes > MAX_BYTES) failures.push(`${shot.out}: ${(bytes / 1024).toFixed(0)} KB, over ${MAX_BYTES / 1024} KB`);
    console.log(line);
  }
  await new Promise((resolve) => { child.once('exit', resolve); child.kill(); });
  fs.rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });

  let head = '';
  try {
    head = execFileSync('git', ['-C', root, 'rev-parse', '--short', 'HEAD'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
    const rel = path.relative(root, dir);
    const dirty = execFileSync('git', ['-C', root, 'status', '--porcelain', '--untracked-files=no'], { encoding: 'utf8' })
      .split('\n').map((l) => l.slice(3)).filter((f) => f && !f.startsWith(rel));
    if (dirty.length) head += `; uncommitted: ${dirty.join(', ')}`;
  } catch { /* not a repo */ }
  if (!only) {
    fs.writeFileSync(path.join(dir, 'captured.txt'),
      `Captured by capture.mjs from ${path.basename(manifestPath)} at ${WIDTH} CSS px, scale ${SCALE}.\n`
      + `${product}${head ? `, repo at ${head}` : ''}.\n\n${receipt.join('\n')}\n`);
  }
  if (failures.length) {
    console.log(`capture: ${failures.length} failure(s)`);
    for (const f of failures) console.log(`  ${f}`);
    process.exit(1);
  }
  console.log(`capture: ${shots.length} shot(s) PASS`);
}

main().catch((e) => { console.error(`capture: ${e.message}`); process.exit(2); });
