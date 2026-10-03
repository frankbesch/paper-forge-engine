#!/usr/bin/env node
/* DOM-free PR3 performance check. No headless browser package is installed. */

const fs = require('fs');
const { performance } = require('perf_hooks');

const target = process.argv[2];
if (!target) throw new Error('usage: node tests/perf/measure.js <library.html>');

const started = performance.now();
const html = fs.readFileSync(target, 'utf8');
const marker = '<script id="library-data" type="application/json">';
const start = html.indexOf(marker) + marker.length;
const end = html.indexOf('</script>', start);
const items = JSON.parse(html.slice(start, end).replaceAll('<\\/', '</'));
const rows = items.map(item => `${item.itemId}|${item.title}|${item.kind}|${item.evidenceClass}|${item.disposition || 'Unassessed'}|${item.currentStage || item.lifecycle}|${item.nextAction || ''}`);
const renderMs = performance.now() - started;

const samples = [];
for (let run = 0; run < 5; run += 1) {
  const then = performance.now();
  items.filter(item => `${item.title} ${item.summary} ${item.themes.join(' ')}`.toLowerCase().includes('agent'));
  samples.push(performance.now() - then);
}
samples.sort((a, b) => a - b);
const filterMs = samples[2];
const externalAsset = /<(?:script|link)[^>]+(?:src|href)="https?:\/\//.test(html);

console.log(`PERF mode=dom-free items=${items.length} rows=${rows.length} first_render_ms=${renderMs.toFixed(2)} filter_median_ms=${filterMs.toFixed(2)} external_assets=${externalAsset}`);
if (items.length !== 500 || rows.length !== 500 || renderMs >= 2000 || filterMs >= 100 || externalAsset) process.exit(1);
