#!/usr/bin/env node
'use strict';

/**
 * Automated Electron UI smoke test — no extra npm dependency required.
 *
 * Launches the real desktop app with Chrome DevTools Protocol enabled, clicks
 * the primary navigation links, waits for each route's real heading, exercises
 * the Auto-Clip prompter (chat box, chips, Preview), checks that the loopback
 * backend reports online, and writes deliverables/ui_smoke.json.
 *
 * Usage:
 *   node scripts/ui_smoke.cjs
 *   npm --prefix desktop run smoke
 */

const { spawn } = require('node:child_process');
const { once } = require('node:events');
const fs = require('node:fs');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..');
const DESKTOP = path.join(ROOT, 'desktop');
const REPORT = process.env.UI_SMOKE_REPORT
  ? path.resolve(ROOT, process.env.UI_SMOKE_REPORT)
  : path.join(ROOT, 'deliverables', 'ui_smoke.json');
const TIMEOUT_MS = Number(process.env.UI_SMOKE_TIMEOUT || 90000);
const NAV = [
  ['Dashboard', '/', 'Dashboard'],
  ['Auto-Clip Studio', '/clip', 'New clip project'],
  ['M2 Benchmark', '/benchmark', 'M2 HARDWARE BENCHMARK'],
  ['Settings', '/settings', 'Settings & system'],
  ['Dashboard', '/', 'Dashboard'],
];

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const port = server.address().port;
      server.close(() => resolve(port));
    });
  });
}

class CDP {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.exceptions = [];
    this.consoleErrors = [];
    this.closed = false;
    this.keepalive = setInterval(() => {}, 1000);
    ws.addEventListener('close', () => {
      this.closed = true;
      clearInterval(this.keepalive);
      for (const { reject } of this.pending.values()) {
        reject(new Error('CDP connection closed'));
      }
      this.pending.clear();
    });
    ws.addEventListener('message', (event) => {
      let msg;
      try { msg = JSON.parse(event.data); } catch { return; }
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(msg.error.message || JSON.stringify(msg.error)));
        else resolve(msg.result || {});
        return;
      }
      if (msg.method === 'Runtime.exceptionThrown') {
        const detail = msg.params?.exceptionDetails?.exception?.description ||
          msg.params?.exceptionDetails?.text || 'uncaught page exception';
        this.exceptions.push(String(detail));
      }
      if (msg.method === 'Log.entryAdded' && msg.params?.entry?.level === 'error') {
        const text = String(msg.params.entry.text || '');
        if (!/favicon/i.test(text)) this.consoleErrors.push(text);
      }
    });
  }

  static async connect(url) {
    const ws = new WebSocket(url);
    await new Promise((resolve, reject) => {
      ws.addEventListener('open', resolve, { once: true });
      ws.addEventListener('error', (event) => reject(new Error(String(event.message || event))), { once: true });
    });
    return new CDP(ws);
  }

  send(method, params = {}) {
    if (this.closed) return Promise.reject(new Error('CDP connection closed'));
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression) {
    const result = await this.send('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise: true,
    });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text || 'evaluate failed');
    }
    return result.result?.value;
  }

  close() {
    clearInterval(this.keepalive);
    try { this.ws.close(); } catch { /* ignore */ }
  }
}

async function waitForTarget(port, child, logs) {
  const deadline = Date.now() + TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`Electron exited before UI loaded (code ${child.exitCode}).\n${logs()}`);
    }
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/list`);
      const targets = await response.json();
      const page = targets.find((t) => t.type === 'page' && /^http:\/\/127\.0\.0\.1:\d+\//.test(t.url));
      if (page && page.webSocketDebuggerUrl) return page;
    } catch { /* app still starting */ }
    await sleep(300);
  }
  throw new Error(`Timed out waiting for the app UI.\n${logs()}`);
}

async function waitFor(cdp, expression, label, timeout = 20000) {
  const deadline = Date.now() + timeout;
  let last;
  while (Date.now() < deadline) {
    try {
      last = await cdp.evaluate(expression);
      if (last) return last;
    } catch (err) {
      last = String(err.message || err);
    }
    await sleep(250);
  }
  throw new Error(`Timed out waiting for ${label}. Last value: ${JSON.stringify(last)}`);
}

async function main() {
  const checks = [];
  const started = new Date().toISOString();
  let failed = 0;
  let child;
  let cdp;
  let clipProjectId = null;
  let packagedBin = null;

  const check = async (name, fn) => {
    try {
      const detail = await fn();
      checks.push({ name, status: 'PASS', detail: detail || null });
      console.log(`[PASS     ] ${name}`);
    } catch (err) {
      failed += 1;
      checks.push({ name, status: 'FAIL', error: String(err.message || err) });
      console.error(`[FAIL     ] ${name}: ${err.message || err}`);
    }
  };

  try {
    const electronEntry = require.resolve('electron', { paths: [DESKTOP] });
    packagedBin = process.env.UI_SMOKE_BIN;
    const electronBin = packagedBin || require(electronEntry);
    if (typeof electronBin !== 'string') throw new Error('electron package did not resolve to a binary');
    if (typeof WebSocket !== 'function' || typeof fetch !== 'function') {
      throw new Error('Node 22+ with global WebSocket and fetch is required');
    }

    const port = await freePort();
    let logBuffer = '';
    const logs = () => logBuffer.slice(-4000);
    const launchArgs = packagedBin
      ? [`--remote-debugging-port=${port}`]
      : [DESKTOP, `--remote-debugging-port=${port}`];
    child = spawn(electronBin, launchArgs, {
      cwd: packagedBin ? path.dirname(electronBin) : DESKTOP,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    child.stdout.on('data', (d) => { logBuffer += d.toString(); });
    child.stderr.on('data', (d) => { logBuffer += d.toString(); });

    const target = await waitForTarget(port, child, logs);
    cdp = await CDP.connect(target.webSocketDebuggerUrl);
    await cdp.send('Runtime.enable');
    await cdp.send('Log.enable');
    await cdp.send('Page.enable');

    await check('initial Dashboard route renders', async () => {
      await waitFor(cdp, `location.pathname === '/' && document.body.innerText.includes('Dashboard')`, 'Dashboard route');
      return 'Dashboard';
    });

    await check('all primary navigation links are present', async () => {
      const missing = await cdp.evaluate(`(() => {
        const labels = ['Dashboard','New Project','Auto-Clip Studio','Asset Library','Export Center','M2 Benchmark','Settings'];
        const text = document.body.innerText;
        return labels.filter((label) => !text.includes(label));
      })()`);
      if (missing.length) throw new Error(`missing nav labels: ${missing.join(', ')}`);
      return '7/7 labels';
    });

    for (const [label, route, heading] of NAV.slice(1)) {
      await check(`click ${label} → ${route}`, async () => {
        const clicked = await cdp.evaluate(`(() => {
          const label = ${JSON.stringify(label)};
          const link = [...document.querySelectorAll('a')].find((a) => a.textContent.trim() === label);
          if (!link) return false;
          link.click();
          return true;
        })()`);
        if (!clicked) throw new Error(`nav link ${label} not found`);
        await waitFor(cdp, `location.pathname === ${JSON.stringify(route)}`, `route ${route}`);
        await waitFor(cdp, `document.body.innerText.includes(${JSON.stringify(heading)})`, `heading ${heading}`);
        return heading;
      });
    }

    await check('prompter is visible on Auto-Clip Studio category', async () => {
      await cdp.evaluate(`(() => {
        const link = [...document.querySelectorAll('a')]
          .find((a) => a.textContent.trim() === 'Auto-Clip Studio');
        if (link) link.click();
      })()`);
      await waitFor(cdp, `location.pathname === '/clip'`, 'route /clip');
      await waitFor(cdp, `document.body.innerText.includes('Prompter · describe the outcome')`, 'category prompter panel');

      await check('built-in director presets render', async () => {
        await waitFor(cdp, `document.querySelectorAll('[data-testid="prompter-preset"]').length >= 5`, 'director presets');
        const count = await cdp.evaluate(`document.querySelectorAll('[data-testid="prompter-preset"]').length`);
        return `${count} presets`;
      });

      const details = await cdp.evaluate(`(() => {
        const area = document.querySelector('[data-testid="prompter-input"]');
        const chips = document.querySelectorAll('[data-testid="prompter-chip"]');
        if (!area) return { textarea: false, chips: 0 };
        const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
        setter.call(area, 'Funny 15s TikTok clips about habits; avoid jargon');
        area.dispatchEvent(new Event('input', { bubbles: true }));
        const preview = [...document.querySelectorAll('button')]
          .find((b) => b.textContent.trim() === 'Preview');
        if (preview) preview.click();
        return { textarea: true, chips: chips.length, preview: !!preview };
      })()`);
      if (!details.textarea || !details.preview || details.chips < 3) {
        throw new Error(`category prompter incomplete: ${JSON.stringify(details)}`);
      }
      await waitFor(cdp, `document.body.innerText.includes('Parsed:')`, 'category parsed brief summary');
      return `${details.chips}/3 chips, Preview OK`;
    });

    await check('local director is the only planner and reports status', async () => {
      const hasLlmToggle = await cdp.evaluate(
        `!!document.querySelector('[data-testid="prompter-llm-toggle"]')`,
      );
      if (hasLlmToggle) throw new Error('LLM toggle is still rendered');
      const badge = await cdp.evaluate(`document.body.innerText`);
      if (!badge.includes('local director')) throw new Error('local director badge missing');
      await cdp.evaluate(`(() => {
        const preview = [...document.querySelectorAll('button')]
          .find((b) => b.textContent.trim() === 'Preview');
        if (!preview) throw new Error('Preview button missing');
        preview.click();
      })()`);
      await waitFor(
        cdp,
        `/director rules/.test(document.body.innerText)`,
        'local director status',
      );
      return 'deterministic director only';
    });

    await check('one-clip auto-clipping toggle is opt-in', async () => {
      const initial = await cdp.evaluate(`(() => {
        const button = document.querySelector('[data-testid="prompter-single-toggle"]');
        if (!button || button.getAttribute('aria-pressed') !== 'false') return false;
        button.click();
        return true;
      })()`);
      if (!initial) throw new Error('one-clip toggle missing or not opt-in');
      await waitFor(cdp, `document.body.innerText.includes('One clip: on')`, 'one-clip toggle on label');
      await cdp.evaluate(`document.querySelector('[data-testid="prompter-single-toggle"]').click()`);
      await waitFor(cdp, `document.body.innerText.includes('One clip: off')`, 'one-clip toggle off label');
      return 'opt-in one-clip toggle OK';
    });

    await check('captions toggle is on by default on the category page', async () => {
      const initial = await cdp.evaluate(`(() => {
        const button = document.querySelector('[data-testid="prompter-captions-toggle"]');
        if (!button || button.getAttribute('aria-pressed') !== 'true') return false;
        button.click();
        return true;
      })()`);
      if (!initial) throw new Error('captions toggle missing or not enabled by default');
      await waitFor(cdp, `document.body.innerText.includes('Captions: off')`, 'captions off label');
      await cdp.evaluate(`document.querySelector('[data-testid="prompter-captions-toggle"]').click()`);
      await waitFor(cdp, `document.body.innerText.includes('Captions: on')`, 'captions on label');
      return 'default-on toggle and status OK';
    });

    await check('automatic transitions toggle is on by default', async () => {
      const initial = await cdp.evaluate(`(() => {
        const button = document.querySelector('[data-testid="prompter-transitions-toggle"]');
        if (!button || button.getAttribute('aria-pressed') !== 'true') return false;
        button.click();
        return true;
      })()`);
      if (!initial) throw new Error('transitions toggle missing or not enabled by default');
      await waitFor(cdp, `document.body.innerText.includes('Transitions: cut')`, 'transitions cut label');
      await cdp.evaluate(`document.querySelector('[data-testid="prompter-transitions-toggle"]').click()`);
      await waitFor(cdp, `document.body.innerText.includes('Transitions: smooth')`, 'transitions smooth label');
      return 'default-on toggle and status OK';
    });

    await check('create temporary clip project and open prompter workspace', async () => {
      await cdp.evaluate(`(() => {
        const link = [...document.querySelectorAll('a')]
          .find((a) => a.textContent.trim() === 'Auto-Clip Studio');
        if (link) link.click();
      })()`);
      await waitFor(cdp, `location.pathname === '/clip'`, 'route /clip');
      await waitFor(cdp, `document.body.innerText.includes('New clip project')`, 'clip project form');
      const created = await cdp.evaluate(`(() => {
        const button = [...document.querySelectorAll('button')]
          .find((b) => b.textContent.trim() === 'Create project');
        if (!button) return false;
        button.click();
        return true;
      })()`);
      if (!created) throw new Error('Create project button not found');
      await waitFor(cdp, `location.pathname.startsWith('/clip/')`, 'clip project route');
      clipProjectId = await cdp.evaluate(`location.pathname.split('/').filter(Boolean).pop()`);
      if (!clipProjectId) throw new Error('clip project route had no id');
      await waitFor(cdp, `document.body.innerText.includes('Prompter · describe the outcome')`, 'prompter panel');
      return `/clip/${clipProjectId}`;
    });

    await check('prompter chat box and suggestion chips render', async () => {
      const details = await cdp.evaluate(`(() => {
        const area = document.querySelector('[data-testid="prompter-input"]');
        const chips = document.querySelectorAll('[data-testid="prompter-chip"]');
        return { textarea: !!area, chips: chips.length };
      })()`);
      if (!details.textarea) throw new Error('prompter textarea not found');
      if (details.chips < 3) throw new Error(`expected 3 suggestion chips, found ${details.chips}`);
      return `${details.chips}/3 chips`;
    });

    await check('prompter Preview parses the brief locally', async () => {
      const clicked = await cdp.evaluate(`(() => {
        const area = document.querySelector('[data-testid="prompter-input"]');
        if (!area) return false;
        const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
        setter.call(area, 'Funny 15s TikTok clips about habits; avoid jargon');
        area.dispatchEvent(new Event('input', { bubbles: true }));
        const preview = [...document.querySelectorAll('button')]
          .find((b) => b.textContent.trim() === 'Preview');
        if (!preview) return false;
        preview.click();
        return true;
      })()`);
      if (!clicked) throw new Error('prompter textarea or Preview button not found');
      await waitFor(cdp, `document.body.innerText.includes('Parsed:')`, 'parsed brief summary');
      const text = await cdp.evaluate(`document.body.innerText`);
      for (const expected of ['funny tone', 'TIKTOK', 'habits', 'jargon', '15s']) {
        if (!text.includes(expected)) throw new Error(`parsed brief missing ${expected}`);
      }
      return 'funny tone / TIKTOK / habits / avoid jargon / 15s';
    });

    await check('import timed transcript for director plan', async () => {
      const srt = [
        '1', '00:00:00,000 --> 00:00:10,000',
        'Most people quit habits because the system is too complicated.', '',
        '2', '00:00:10,000 --> 00:00:20,000',
        'The fix is one tiny habit you can repeat every morning.', '',
        '3', '00:00:20,000 --> 00:00:30,000',
        'You can build a simple routine without any special tools.', '',
        '4', '00:00:30,000 --> 00:00:40,000',
        'Small steps become reliable results when you repeat them.',
      ].join('\n');
      const imported = await cdp.evaluate(`(async () => {
        const r = await fetch('/api/clip/projects/${clipProjectId}/transcript/import', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ content: ${JSON.stringify(srt)}, filename: 'director.srt' }),
        });
        const d = await r.json();
        return { ok: r.ok, cues: d.transcript?.segments?.length || 0 };
      })()`);
      if (!imported.ok || imported.cues < 4) throw new Error(`transcript import failed: ${JSON.stringify(imported)}`);
      await cdp.evaluate(`(() => {
        const reload = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Reload');
        if (reload) reload.click();
      })()`);
      await waitFor(cdp, `document.body.innerText.includes('timing')`, 'project transcript state');
      return `${imported.cues} cues`;
    });

    await check('director preview parses the deterministic plan', async () => {
      await cdp.evaluate(`(() => {
        const area = document.querySelector('[data-testid="prompter-input"]');
        const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
        setter.call(area, 'Funny 15s TikTok clips about habits; avoid jargon');
        area.dispatchEvent(new Event('input', { bubbles: true }));
        const preview = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Preview');
        if (!preview) throw new Error('Preview button missing');
        preview.click();
      })()`);
      await waitFor(cdp, `/director rules/.test(document.body.innerText)`, 'director status');
      await waitFor(cdp, `document.body.innerText.includes('Parsed:')`, 'parsed brief summary');
      const text = await cdp.evaluate(`document.body.innerText`);
      if (/Big Pickle|LLM:/.test(text)) throw new Error('LLM director copy still visible');
      return 'director preview OK';
    });

    await check('generated clips carry director audit metadata', async () => {
      await cdp.evaluate(`(() => {
        const button = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Generate clips');
        if (!button || button.disabled) throw new Error('Generate clips button unavailable');
        button.click();
      })()`);
      await waitFor(cdp, `(async () => {
        const r = await fetch('/api/clip/projects/${clipProjectId}/jobs');
        const d = await r.json();
        const job = (d.jobs || [])[0];
        return job && ['succeeded', 'failed', 'canceled', 'interrupted'].includes(job.status);
      })()`, 'director job completion', 60000);
      const jobState = await cdp.evaluate(`(async () => {
        const r = await fetch('/api/clip/projects/${clipProjectId}/jobs');
        const d = await r.json();
        const job = (d.jobs || [])[0] || {};
        return { status: job.status, error: job.error, message: job.message };
      })()`);
      if (jobState.status !== 'succeeded') throw new Error(`director job failed: ${JSON.stringify(jobState)}`);
      await waitFor(cdp, `(async () => {
        const r = await fetch('/api/clip/projects/${clipProjectId}/clips');
        const d = await r.json();
        return (d.clips || []).length >= 1;
      })()`, 'director candidates', 20000);
      const audit = await cdp.evaluate(`(async () => {
        const r = await fetch('/api/clip/projects/${clipProjectId}/clips');
        const d = await r.json();
        const params = d.clips[0]?.score_json?.params || {};
        return {
          clips: d.clips.length,
          brief: !!params.brief,
          components: Object.keys(d.clips[0]?.score_json?.components || {}),
          copy: d.clips[0]?.copy || null,
        };
      })()`);
      if (!audit.brief || !audit.components.includes('brief_fit') || !audit.copy?.grounding?.all_grounded) {
        throw new Error(`director audit missing: ${JSON.stringify(audit)}`);
      }
      return `${audit.clips} clips, grounded copy, brief_fit`;
    });

    await check('project captions toggle persists and updates transcript candidates', async () => {
      const initial = await cdp.evaluate(`(() => {
        const button = document.querySelector('[data-testid="prompter-captions-toggle"]');
        if (!button || button.getAttribute('aria-pressed') !== 'true') return false;
        button.click();
        return true;
      })()`);
      if (!initial) throw new Error('project captions toggle missing or not enabled by default');
      await waitFor(cdp, `document.body.innerText.includes('Captions: off')`, 'project captions off label');
      await waitFor(cdp, `(async () => {
        const [project, clips] = await Promise.all([
          fetch('/api/clip/projects/${clipProjectId}').then((r) => r.json()),
          fetch('/api/clip/projects/${clipProjectId}/clips').then((r) => r.json()),
        ]);
        const list = clips.clips || [];
        return project.project?.settings?.burn_captions === false &&
          project.project?.burn_captions === false &&
          list.length >= 1 &&
          list.every((c) => c.edit?.burn_captions === false && c.state === 'stale');
      })()`, 'persisted captions off and stale transcript candidates', 20000);

      await cdp.evaluate(`document.querySelector('[data-testid="prompter-captions-toggle"]').click()`);
      await waitFor(cdp, `document.body.innerText.includes('Captions: on')`, 'project captions on label');
      await waitFor(cdp, `(async () => {
        const [project, clips] = await Promise.all([
          fetch('/api/clip/projects/${clipProjectId}').then((r) => r.json()),
          fetch('/api/clip/projects/${clipProjectId}/clips').then((r) => r.json()),
        ]);
        const list = clips.clips || [];
        return project.project?.settings?.burn_captions === true &&
          project.project?.burn_captions === true &&
          list.length >= 1 &&
          list.every((c) => c.edit?.burn_captions === true);
      })()`, 'persisted captions on', 20000);
      return 'project setting and transcript candidate defaults propagate';
    });

    await check('project one-clip mode assembles one final video from ordered scenes', async () => {
      const toggled = await cdp.evaluate(`(() => {
        const button = document.querySelector('[data-testid="prompter-single-toggle"]');
        if (!button || button.getAttribute('aria-pressed') !== 'false') return false;
        button.click();
        return true;
      })()`);
      if (!toggled) throw new Error('project one-clip toggle missing or not opt-in');
      await waitFor(cdp, `document.body.innerText.includes('One clip: on')`, 'project one-clip toggle on');
      await waitFor(cdp, `document.body.innerText.includes('auto-clip · 1 video')`, 'one-video badge');
      await waitFor(cdp, `(async () => {
        const r = await fetch('/api/clip/projects/${clipProjectId}');
        const d = await r.json();
        return d.project?.settings?.single_clip === true;
      })()`, 'persisted one-clip project setting');

      const previousJobId = await cdp.evaluate(`(async () => {
        const r = await fetch('/api/clip/projects/${clipProjectId}/jobs');
        const d = await r.json();
        return (d.jobs || [])[0]?.id || null;
      })()`);
      await waitFor(cdp, `(() => {
        const button = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Generate clips');
        return !!button && !button.disabled;
      })()`, 'Generate clips ready for one-clip run', 20000);
      await cdp.evaluate(`(() => {
        const button = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Generate clips');
        if (!button || button.disabled) throw new Error('Generate clips button unavailable');
        button.click();
      })()`);
      await waitFor(cdp, `(async () => {
        const r = await fetch('/api/clip/projects/${clipProjectId}/jobs');
        const d = await r.json();
        const job = (d.jobs || [])[0];
        return !!job && job.id !== ${JSON.stringify(previousJobId)} &&
          job.meta?.single_clip === true &&
          ['succeeded', 'failed', 'canceled', 'interrupted'].includes(job.status);
      })()`, 'one-clip job completion', 60000);

      const result = await cdp.evaluate(`(async () => {
        const [jobs, clips] = await Promise.all([
          fetch('/api/clip/projects/${clipProjectId}/jobs').then((r) => r.json()),
          fetch('/api/clip/projects/${clipProjectId}/clips').then((r) => r.json()),
        ]);
        const job = (jobs.jobs || [])[0] || {};
        const list = clips.clips || [];
        const clip = list[0] || {};
        const params = clip.score_json?.params || {};
        const assembly = clip.assembly || clip.score_json?.assembly || params.assembly || {};
        const segments = clip.segments || clip.score_json?.segments || [];
        const ranges = segments.map((s) => [Number(s.start), Number(s.end)]);
        const nonOverlapping = ranges.every((a, i) => ranges.every((b, j) =>
          i === j || a[1] <= b[0] + 0.001 || b[1] <= a[0] + 0.001));
        const timeline = assembly.timeline || { start: clip.start_sec, end: clip.end_sec };
        return {
          status: job.status,
          error: job.error,
          jobMeta: job.meta?.single_clip === true,
          directionFlag: job.meta?.direction?.single_clip === true,
          assemblyInJobMeta: !!job.meta?.direction?.assembly,
          count: list.length,
          selectedCount: list.filter((c) => c.selected === true).length,
          selected: clip.selected === true,
          param: params.single_clip === true,
          countParam: params.count,
          grounded: clip.copy?.grounding?.all_grounded === true,
          clipId: clip.id,
          startSec: Number(clip.start_sec),
          endSec: Number(clip.end_sec),
          timelineStart: Number(timeline.start),
          timelineEnd: Number(timeline.end),
          segmentCount: segments.length,
          assemblySegmentCount: Number(assembly.segment_count || 0),
          roles: segments.map((s) => s.role),
          orders: segments.map((s) => Number(s.plan_order)),
          sourceRanges: ranges,
          nonOverlapping,
          groundedSegments: segments.every((s) => !!s.boundary_evidence?.authority &&
            Number.isInteger(s.sentence_start) && Number.isInteger(s.sentence_end) && s.end >= s.start),
          durationMatches: Math.abs(Number(clip.duration_sec) -
            segments.reduce((sum, s) => sum + Number(s.duration || 0), 0)) < 0.05,
          authority: assembly.boundary_authority || '',
        };
      })()`);
      if (result.status !== 'succeeded') {
        throw new Error(`one-clip job failed: ${JSON.stringify(result)}`);
      }
      if (!result.jobMeta || !result.directionFlag || !result.assemblyInJobMeta) {
        throw new Error(`one-clip job meta missing assembly audit: ${JSON.stringify(result)}`);
      }
      if (result.count !== 1 || result.countParam !== 1 || result.selectedCount !== 1 || !result.selected ||
          !result.param || !result.grounded) {
        throw new Error(`one-clip candidate not render-ready: ${JSON.stringify(result)}`);
      }
      if (result.segmentCount < 2 || result.assemblySegmentCount !== result.segmentCount ||
          !result.durationMatches || !result.groundedSegments || !result.nonOverlapping) {
        throw new Error(`assembly metadata invalid: ${JSON.stringify(result)}`);
      }
      if (result.startSec !== 0 || result.timelineStart !== 0 ||
          Math.abs(result.endSec - result.timelineEnd) > 0.001) {
        throw new Error(`assembled timeline invalid: ${JSON.stringify(result)}`);
      }
      if (result.orders.some((order, index) => order !== index) || result.roles.some((role) => !role) ||
          !result.authority.includes('transcript sentence ranges')) {
        throw new Error(`scene order or boundary authority invalid: ${JSON.stringify(result)}`);
      }

      await waitFor(cdp, `document.body.innerText.includes('ordered scenes')`, 'assembled video summary', 20000);
      const uiText = await cdp.evaluate(`document.body.innerText`);
      for (const expected of ['assembled ·', 'ordered scenes', 'Sentence ranges are authoritative']) {
        if (!uiText.includes(expected)) throw new Error(`assembled UI missing ${expected}`);
      }

      const guard = await cdp.evaluate(`(async () => {
        const r = await fetch('/api/clip/clips/${result.clipId}', {
          method: 'PATCH',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ start_sec: 0, end_sec: 1 }),
        });
        const body = await r.text();
        const after = await (await fetch('/api/clip/projects/${clipProjectId}/clips')).json();
        const unchanged = (after.clips || []).find((c) => c.id === ${JSON.stringify(result.clipId)}) || {};
        return { status: r.status, body, endSec: Number(unchanged.end_sec) };
      })()`);
      if (guard.status !== 400 || !/Assembled clips/.test(guard.body) ||
          Math.abs(guard.endSec - result.endSec) > 0.001) {
        throw new Error(`assembled boundary edit was not guarded: ${JSON.stringify(guard)}`);
      }

      return `1 selected grounded candidate from ${result.segmentCount} ordered scenes; timeline 0–${result.endSec}s`;
    });

    await check('one-clip mode shows a playable final video preview before export', async () => {
      // The one-clip fixture above leaves a single selected assembled candidate.
      // Give it a real source, then verify the UI renders and plays the final
      // MP4 (captions/crop/assembly included), not the raw unclipped source.
      const ffmpeg = await cdp.evaluate(`fetch('/api/clip/diagnostics').then((r) => r.json()).then((d) => d.ffmpeg)`);
      if (!ffmpeg || !fs.existsSync(ffmpeg)) throw new Error(`ffmpeg unavailable: ${ffmpeg}`);
      const hasSource = await cdp.evaluate(`(async () => {
        const d = await (await fetch('/api/clip/projects/${clipProjectId}')).json();
        return (d.project?.sources || []).length > 0;
      })()`);
      if (!hasSource) {
        const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'lavs-final-preview-'));
        const file = path.join(dir, 'source.mp4');
        await new Promise((resolve, reject) => {
          const proc = spawn(ffmpeg, [
            '-hide_banner', '-loglevel', 'error', '-y',
            '-f', 'lavfi', '-i', 'color=c=blue:s=320x180:r=15:d=2.0',
            '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:d=2.0',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-shortest', file,
          ], { stdio: 'ignore' });
          proc.on('exit', (code) => code === 0 ? resolve() : reject(new Error(`preview source encode failed: ${code}`)));
        });
        const encoded = fs.readFileSync(file).toString('base64');
        const uploaded = await cdp.evaluate(`(async () => {
          const binary = atob(${JSON.stringify(encoded)});
          const bytes = new Uint8Array(binary.length);
          for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
          const fd = new FormData();
          fd.append('file', new File([bytes], 'source.mp4', { type: 'video/mp4' }));
          const r = await fetch('/api/clip/projects/${clipProjectId}/source', { method: 'POST', body: fd });
          return { ok: r.ok, hasSource: !!(await r.json()).source };
        })()`);
        fs.rmSync(dir, { recursive: true, force: true });
        if (!uploaded.ok || !uploaded.hasSource) throw new Error(`preview source upload failed: ${JSON.stringify(uploaded)}`);
      }
      await waitFor(cdp, `!!document.querySelector('[data-testid="clip-final-preview-panel"]')`,
        'final preview panel', 20000);
      // Wait for any auto-render job to settle before using the button.
      await waitFor(cdp, `(() => {
        const b = document.querySelector('[data-testid="clip-render-preview-button"]');
        return !!b && !b.disabled;
      })()`, 'final preview render button ready', 90000);
      if (await cdp.evaluate(`!!document.querySelector('[data-testid="clip-final-preview-pending"]')`)) {
        await cdp.evaluate(`document.querySelector('[data-testid="clip-render-preview-button"]').click()`);
      }
      try {
        await waitFor(cdp, `(() => {
          const v = document.querySelector('[data-testid="clip-final-preview"]');
          return !!v && !!v.getAttribute('src');
        })()`, 'rendered final preview video', 90000);
      } catch (e) {
        const dbg = await cdp.evaluate(`(async () => {
          const jobs = await (await fetch('/api/clip/projects/${clipProjectId}/jobs')).json();
          const d = await (await fetch('/api/clip/projects/${clipProjectId}/clips')).json();
          return {
            panel: document.querySelector('[data-testid="clip-final-preview-panel"]')?.innerText.slice(0, 500),
            clips: (d.clips || []).map((c) => ({ id: c.id, selected: c.selected, renders: (c.renders || []).length, state: c.state })),
            jobs: (jobs.jobs || []).slice(0, 5).map((j) => ({ type: j.type, status: j.status, error: j.error, message: j.message, stage: j.stage })),
          };
        })()`);
        throw new Error(`final preview video timeout: ${JSON.stringify(dbg)}`);
      }
      const preview = await cdp.evaluate(`(() => {
        const v = document.querySelector('[data-testid="clip-final-preview"]');
        return v ? {
          controls: v.controls,
          src: v.getAttribute('src'),
          inDom: !!v.parentElement,
          panelText: document.querySelector('[data-testid="clip-final-preview-panel"]').innerText.slice(0, 300),
        } : null;
      })()`);
      if (!preview || !preview.controls || !preview.inDom ||
          !/\/api\/clip\/clips\/[^?]+\/file/.test(preview.src || '')) {
        throw new Error(`final preview not playable: ${JSON.stringify(preview)}`);
      }
      if (!/Final video preview/.test(preview.panelText) || !/not the raw source/.test(preview.panelText)) {
        throw new Error(`final preview panel copy missing: ${JSON.stringify(preview)}`);
      }
      return `rendered final MP4 preview ready (${preview.src})`;
    });

    await check('multiple videos upload, reorder and combine with cuts or smooth transitions', async () => {
      const ffmpeg = await cdp.evaluate(`fetch('/api/clip/diagnostics').then((r) => r.json()).then((d) => d.ffmpeg)`);
      if (!ffmpeg || !fs.existsSync(ffmpeg)) throw new Error(`ffmpeg unavailable: ${ffmpeg}`);
      // The final-preview check added a source; remove it so this check starts
      // with a clean two-source project and can assert upload order exactly.
      await cdp.evaluate(`(async () => {
        const d = await (await fetch('/api/clip/projects/${clipProjectId}')).json();
        const ids = (d.project?.sources || []).map((s) => s.id);
        for (const sid of ids) {
          await fetch('/api/clip/sources/' + sid, { method: 'DELETE' });
        }
      })()`);
      const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'lavs-combine-'));
      const files = [path.join(dir, 'first.mp4'), path.join(dir, 'second.mp4')];
      const colors = ['blue', 'red'];
      for (let i = 0; i < files.length; i += 1) {
        await new Promise((resolve, reject) => {
          const proc = spawn(ffmpeg, [
            '-hide_banner', '-loglevel', 'error', '-y',
            '-f', 'lavfi', '-i', `color=c=${colors[i]}:s=320x180:r=15:d=3.0`,
            '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:d=3.0',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-shortest', files[i],
          ], { stdio: 'ignore' });
          proc.on('exit', (code) => code === 0 ? resolve() : reject(new Error(`fixture encode failed: ${code}`)));
        });
      }
      const encoded = files.map((f) => fs.readFileSync(f).toString('base64'));
      const uploaded = await cdp.evaluate(`(async () => {
        const encoded = ${JSON.stringify(encoded)};
        const asFile = (b64, name) => {
          const binary = atob(b64);
          const bytes = new Uint8Array(binary.length);
          for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
          return new File([bytes], name, { type: 'video/mp4' });
        };
        const fd = new FormData();
        fd.append('files', asFile(encoded[0], 'first.mp4'));
        fd.append('files', asFile(encoded[1], 'second.mp4'));
        const r = await fetch('/api/clip/projects/${clipProjectId}/sources', { method: 'POST', body: fd });
        const d = await r.json();
        return {
          ok: r.ok, added: d.added,
          names: (d.sources || []).map((s) => s.original_name),
          ids: (d.sources || []).map((s) => s.id),
        };
      })()`);
      if (!uploaded.ok || uploaded.added !== 2 || uploaded.names.join(',') !== 'first.mp4,second.mp4' ||
          uploaded.ids.length !== 2) {
        throw new Error(`multi-source upload failed: ${JSON.stringify(uploaded)}`);
      }
      // Synthetic fixture videos contain sine waves, so import small timed SRTs
      // for each source instead of depending on speech recognition.
      const sourceCaptions = await cdp.evaluate(`(async () => {
        const ids = ${JSON.stringify(uploaded.ids)};
        const texts = [
          '1\\n00:00:00,200 --> 00:00:01,200\\nFirst source line\\n\\n',
          '1\\n00:00:00,300 --> 00:00:01,400\\nSecond source line\\n\\n',
        ];
        const out = [];
        for (let i = 0; i < ids.length; i += 1) {
          const r = await fetch('/api/clip/sources/' + ids[i] + '/transcript/import', {
            method: 'POST', headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ content: texts[i], filename: 'source-' + (i + 1) + '.srt' }),
          });
          const d = await r.json();
          out.push({ ok: r.ok, cues: (d.transcript?.sentences || []).length });
        }
        return out;
      })()`);
      if (!sourceCaptions.every((c) => c.ok && c.cues > 0)) {
        throw new Error(`per-source caption import failed: ${JSON.stringify(sourceCaptions)}`);
      }
      // Multi-source upload was done through the API, so navigate away and back
      // to make React refetch the project (needed to enable the combine button).
      // Wait for each route's real content — the URL changes before React has
      // rendered the next page, and this pathname was already active on entry.
      await cdp.evaluate(`(() => {
        const link = [...document.querySelectorAll('a')].find((a) => a.textContent.trim() === 'Auto-Clip Studio');
        if (!link) throw new Error('Auto-Clip Studio link missing');
        link.click();
      })()`);
      await waitFor(cdp, `location.pathname === '/clip'`, 'clip category route after upload');
      await waitFor(cdp, `document.body.innerText.includes('New clip project')`, 'clip category rendered');
      // The project list is fetched asynchronously; wait for the specific link.
      await waitFor(cdp, `!!document.querySelector('a[href="/clip/${clipProjectId}"]')`, 'project link in list');
      await cdp.evaluate(`(() => {
        const project = document.querySelector('a[href="/clip/${clipProjectId}"]');
        if (!project) throw new Error('project link missing on clip category');
        project.click();
      })()`);
      await waitFor(cdp, `(() => location.pathname === '/clip/${clipProjectId}' &&
        !!document.querySelector('[data-testid="prompter-transitions-toggle"]') &&
        !!document.querySelector('[data-testid="clip-combine-button"]'))()`,
      'project page rendered after upload');

      // The combine must honour the user-facing Target Duration control, not the
      // sum of the uploaded source files. Add a 5s custom target through the UI.
      const targetSet = await cdp.evaluate(`(() => {
        const input = document.querySelector('[data-testid="duration-custom-input"]');
        const add = document.querySelector('[data-testid="duration-custom-add"]');
        if (!input || !add) throw new Error('target duration control missing');
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
        setter.call(input, '5');
        input.dispatchEvent(new Event('input', { bubbles: true }));
        add.click();
        return true;
      })()`);
      if (!targetSet) throw new Error('could not set the combine target duration');
      await waitFor(cdp, `document.querySelector('[data-testid="combine-target-label"]')?.textContent.includes('5s')`,
        'combine target label', 20000);

      const reordered = await cdp.evaluate(`(async () => {
        const list = await (await fetch('/api/clip/projects/${clipProjectId}/sources')).json();
        const ids = (list.sources || []).map((s) => s.id).reverse();
        const r = await fetch('/api/clip/projects/${clipProjectId}/sources/order', {
          method: 'PATCH', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ source_ids: ids }),
        });
        const d = await r.json();
        return { ok: r.ok, names: (d.sources || []).map((s) => s.original_name) };
      })()`);
      if (!reordered.ok || reordered.names[0] !== 'second.mp4') {
        throw new Error(`source reorder failed: ${JSON.stringify(reordered)}`);
      }

      const switched = await cdp.evaluate(`(() => {
        const button = document.querySelector('[data-testid="prompter-transitions-toggle"]');
        if (!button || button.getAttribute('aria-pressed') !== 'true') return false;
        button.click();
        return true;
      })()`);
      if (!switched) {
        const state = await cdp.evaluate(`(async () => {
          const b = document.querySelector('[data-testid="prompter-transitions-toggle"]');
          const d = await (await fetch('/api/clip/projects/${clipProjectId}')).json();
          return { aria: b?.getAttribute('aria-pressed'), project: d.project?.transitions, settings: d.project?.settings };
        })()`);
        throw new Error(`project transitions toggle was not enabled by default: ${JSON.stringify(state)}`);
      }
      await waitFor(cdp, `document.body.innerText.includes('Transitions: cut')`, 'project transitions cut label');
      await waitFor(cdp, `(async () => {
        const d = await (await fetch('/api/clip/projects/${clipProjectId}')).json();
        return d.project?.settings?.transitions === false;
      })()`, 'persisted transitions off');

      const previousCombine = await cdp.evaluate(`(async () => {
        const d = await (await fetch('/api/clip/projects/${clipProjectId}/jobs')).json();
        return (d.jobs || []).find((j) => j.type === 'combine')?.id || null;
      })()`);
      await cdp.evaluate(`(() => {
        const button = document.querySelector('[data-testid="clip-combine-button"]');
        if (!button || button.disabled) throw new Error('combine button unavailable');
        button.click();
      })()`);
      await waitFor(cdp, `(async () => {
        const d = await (await fetch('/api/clip/projects/${clipProjectId}/jobs')).json();
        const job = (d.jobs || []).find((j) => j.type === 'combine');
        return !!job && job.id !== ${JSON.stringify(previousCombine)} &&
          ['succeeded', 'failed', 'canceled', 'interrupted'].includes(job.status);
      })()`, 'combine job completion', 90000);

      const cut = await cdp.evaluate(`(async () => {
        const [jobs, clips] = await Promise.all([
          fetch('/api/clip/projects/${clipProjectId}/jobs').then((r) => r.json()),
          fetch('/api/clip/projects/${clipProjectId}/clips').then((r) => r.json()),
        ]);
        const job = (jobs.jobs || []).find((j) => j.type === 'combine') || {};
        const item = (clips.clips || []).find((c) => c.assembly?.kind === 'source_combine') || {};
        const render = await fetch('/api/clip/clips/' + item.id + '/file');
        return {
          status: job.status, jobTransitions: job.meta?.transitions,
          jobTarget: job.meta?.target_duration,
          jobCaptions: job.meta?.result?.captions,
          target: item.assembly?.target_duration,
          mode: item.assembly?.transition_mode, sourceCount: item.assembly?.segment_count,
          order: (item.segments || []).map((s) => s.name),
          duration: Number(item.duration_sec), selected: item.selected === true,
          renders: (item.renders || []).length, download: render.status,
          engine: item.score_json?.engine,
          burnCaptions: item.edit?.burn_captions,
          captionEnabled: item.assembly?.captions?.enabled,
          cueCount: Number(item.assembly?.captions?.cue_count || 0),
        };
      })()`);
      if (cut.status !== 'succeeded' || cut.jobTransitions !== false || cut.mode !== 'cut' ||
          cut.sourceCount !== 2 || cut.order.join(',') !== 'second.mp4,first.mp4' ||
          cut.jobTarget !== 5 || cut.target !== 5 ||
          !cut.selected || cut.renders < 1 || cut.download !== 200 || cut.engine !== 'source-combine/v1' ||
          cut.burnCaptions !== true || cut.captionEnabled !== true || cut.cueCount < 1) {
        throw new Error(`cut combine invalid: ${JSON.stringify(cut)}`);
      }
      if (Math.abs(cut.duration - 5) > 0.25) {
        throw new Error(`cut combine duration should respect the 5s target: ${JSON.stringify(cut)}`);
      }
      await waitFor(cdp, `document.body.innerText.includes('Combined video')`, 'combine candidate UI', 20000);
      const ui = await cdp.evaluate(`document.body.innerText`);
      for (const expected of ['combined videos', 'straight cuts', '5s target', 'burned-in subtitles come only from each source transcript']) {
        if (!ui.includes(expected)) throw new Error(`combine UI missing ${expected}`);
      }

      // Toggle smooth transitions back on and re-combine through the real UI so
      // React refreshes its candidate list (the combine job replaces the old one).
      const switchedBack = await cdp.evaluate(`(() => {
        const b = document.querySelector('[data-testid="prompter-transitions-toggle"]');
        if (!b || b.getAttribute('aria-pressed') !== 'false') return false;
        b.click();
        return true;
      })()`);
      if (!switchedBack) throw new Error('could not switch transitions back on through the UI');
      await waitFor(cdp, `document.body.innerText.includes('Transitions: smooth')`, 'project transitions smooth label');
      await waitFor(cdp, `(async () => {
        const d = await (await fetch('/api/clip/projects/${clipProjectId}')).json();
        return d.project?.settings?.transitions === true;
      })()`, 'persisted transitions on');
      const beforeSmooth = await cdp.evaluate(`(async () => {
        const d = await (await fetch('/api/clip/projects/${clipProjectId}/jobs')).json();
        return (d.jobs || []).find((j) => j.type === 'combine')?.id || null;
      })()`);
      await cdp.evaluate(`(() => {
        const button = document.querySelector('[data-testid="clip-combine-button"]');
        if (!button || button.disabled) throw new Error('smooth combine button unavailable');
        button.click();
      })()`);
      await waitFor(cdp, `(async () => {
        const d = await (await fetch('/api/clip/projects/${clipProjectId}/jobs')).json();
        const job = (d.jobs || []).find((j) => j.type === 'combine');
        return !!job && job.id !== ${JSON.stringify(beforeSmooth)} &&
          ['succeeded', 'failed', 'canceled', 'interrupted'].includes(job.status);
      })()`, 'smooth combine completion', 90000);
      await waitFor(cdp, `document.body.innerText.includes('smooth transitions')`, 'smooth combine candidate UI', 20000);
      const smooth = await cdp.evaluate(`(async () => {
        const d = await (await fetch('/api/clip/projects/${clipProjectId}/clips')).json();
        const item = (d.clips || []).find((c) => c.assembly?.kind === 'source_combine') || {};
        return {
          mode: item.assembly?.transition_mode,
          duration: Number(item.duration_sec),
          target: item.assembly?.target_duration,
          count: item.assembly?.segment_count,
          burnCaptions: item.edit?.burn_captions,
          captionEnabled: item.assembly?.captions?.enabled,
          cueCount: Number(item.assembly?.captions?.cue_count || 0),
        };
      })()`);
      if (smooth.mode !== 'fade' || smooth.count !== 2 || smooth.target !== 5 ||
          Math.abs(smooth.duration - 5) > 0.25 ||
          smooth.burnCaptions !== true || smooth.captionEnabled !== true || smooth.cueCount < 1) {
        throw new Error(`smooth combine invalid: ${JSON.stringify(smooth)}`);
      }

      await check('combined candidate burned-in captions follow the project toggle', async () => {
        const initial = await cdp.evaluate(`(() => {
          const button = document.querySelector('[data-testid="prompter-captions-toggle"]');
          if (!button || button.getAttribute('aria-pressed') !== 'true') return false;
          button.click();
          return true;
        })()`);
        if (!initial) throw new Error('project captions toggle was not enabled before combine');
        await waitFor(cdp, `document.body.innerText.includes('Captions: off')`, 'combine captions off label');
        await waitFor(cdp, `(async () => {
          const [project, clips] = await Promise.all([
            fetch('/api/clip/projects/${clipProjectId}').then((r) => r.json()),
            fetch('/api/clip/projects/${clipProjectId}/clips').then((r) => r.json()),
          ]);
          const list = clips.clips || [];
          const combine = list.find((c) => c.assembly?.kind === 'source_combine');
          const transcripts = list.filter((c) => c.assembly?.kind !== 'source_combine');
          return project.project?.settings?.burn_captions === false &&
            !!combine && combine.edit?.burn_captions === false && combine.state === 'stale' &&
            transcripts.length >= 1 &&
            transcripts.every((c) => c.edit?.burn_captions === false && c.state === 'stale');
        })()`, 'combine captions propagate off with transcript candidates', 20000);

        await cdp.evaluate(`document.querySelector('[data-testid="prompter-captions-toggle"]').click()`);
        await waitFor(cdp, `document.body.innerText.includes('Captions: on')`, 'combine captions on label');
        await waitFor(cdp, `(async () => {
          const d = await (await fetch('/api/clip/projects/${clipProjectId}')).json();
          return d.project?.settings?.burn_captions === true;
        })()`, 'persisted captions on', 20000);
        const restored = await cdp.evaluate(`(async () => {
          const [project, clips] = await Promise.all([
            fetch('/api/clip/projects/${clipProjectId}').then((r) => r.json()),
            fetch('/api/clip/projects/${clipProjectId}/clips').then((r) => r.json()),
          ]);
          const combine = (clips.clips || []).find((c) => c.assembly?.kind === 'source_combine') || {};
          return {
            setting: project.project?.settings?.burn_captions,
            combineCaptions: combine.edit?.burn_captions,
            state: combine.state,
          };
        })()`);
        if (restored.setting !== true || restored.combineCaptions !== true) {
          throw new Error(`captions restore invalid: ${JSON.stringify(restored)}`);
        }
        return 'project captions toggle propagates to the combined candidate';
      });

      // Isolate the combine candidate. Earlier transcript candidates refer to a
      // different (long) source than these 1.2 s fixtures, so they are not valid
      // exports in this synthetic project.
      await cdp.evaluate(`(async () => {
        const d = await (await fetch('/api/clip/projects/${clipProjectId}/clips')).json();
        for (const c of (d.clips || [])) {
          if (c.selected && c.assembly?.kind !== 'source_combine') {
            const box = document.querySelector('[data-testid="clip-select-' + c.id + '"]');
            if (box && box.checked) box.click();
          }
        }
      })()`);
      await waitFor(cdp, `(async () => {
        const d = await (await fetch('/api/clip/projects/${clipProjectId}/clips')).json();
        const selected = (d.clips || []).filter((c) => c.selected);
        return selected.length === 1 && selected[0].assembly?.kind === 'source_combine';
      })()`, 'only combine candidate selected', 20000);
      // Make sure React has refetched before Export reads its selected list.
      await cdp.evaluate(`(() => {
        const reload = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Reload');
        if (reload) reload.click();
      })()`);
      await waitFor(cdp, `(() => {
        const boxes = [...document.querySelectorAll('[data-testid^="clip-select-"]')];
        const checked = boxes.filter((b) => b.checked);
        return checked.length === 1 &&
          document.querySelector('[data-testid="clip-export-batch-button"]')?.textContent.includes('1 selected');
      })()`, 'UI selection isolated to combine candidate', 20000);

      // The reported failure was at the Export level: clicking Export must render
      // the combine from its stored source list, not as a single-source assembly.
      const beforeExport = await cdp.evaluate(`(async () => {
        const d = await (await fetch('/api/clip/projects/${clipProjectId}/jobs')).json();
        return (d.jobs || []).find((j) => j.type === 'batch_export')?.id || null;
      })()`);
      await waitFor(cdp, `(() => {
        const b = document.querySelector('[data-testid="clip-export-batch-button"]');
        return !!b && !b.disabled;
      })()`, 'batch export button ready', 30000);
      await cdp.evaluate(`document.querySelector('[data-testid="clip-export-batch-button"]').click()`);
      await waitFor(cdp, `(async () => {
        const d = await (await fetch('/api/clip/projects/${clipProjectId}/jobs')).json();
        const job = (d.jobs || []).find((j) => j.type === 'batch_export');
        return !!job && job.id !== ${JSON.stringify(beforeExport)} &&
          ['succeeded', 'failed', 'canceled', 'interrupted'].includes(job.status);
      })()`, 'batch export completion', 180000);
      const exported = await cdp.evaluate(`(async () => {
        const [jobs, exports] = await Promise.all([
          fetch('/api/clip/projects/${clipProjectId}/jobs').then((r) => r.json()),
          fetch('/api/clip/projects/${clipProjectId}/exports').then((r) => r.json()),
        ]);
        const job = (jobs.jobs || []).find((j) => j.type === 'batch_export') || {};
        const items = (exports.manifest?.items) || [];
        const combine = items.find((i) => i.assembly?.kind === 'source_combine') || {};
        return {
          status: job.status, failed: job.meta?.result?.failed,
          jobError: String(job.error || '').slice(0, 300),
          items: items.map((i) => ({ title: i.title, error: String(i.error || '').slice(0, 300) })),
          file: !!combine.file, error: combine.error,
          mode: combine.transition?.mode,
          target: combine.combine?.target_duration,
          sources: (combine.combine?.sources || []).length,
          validation: combine.validation?.ok,
          captions: combine.assembly?.captions?.enabled,
          cueCount: Number(combine.assembly?.captions?.cue_count || 0),
        };
      })()`);
      if (exported.status !== 'succeeded' || exported.failed !== 0 || !exported.file ||
          exported.error || exported.mode !== 'fade' || exported.sources !== 2 ||
          exported.target !== 5 || exported.validation !== true ||
          exported.captions !== true || exported.cueCount < 1) {
        throw new Error(`combined video export failed: ${JSON.stringify(exported)}`);
      }
      fs.rmSync(dir, { recursive: true, force: true });
      return `2 sources reordered to a 5s target, cuts ${cut.duration}s, crossfade ${smooth.duration}s and batch export succeeded`;
    });

    await check('loopback backend reports online', async () => {
      await waitFor(cdp, `document.body.innerText.includes('online')`, 'online status', 30000);
      return 'online';
    });

    await check('no uncaught page exceptions', async () => {
      if (cdp.exceptions.length) throw new Error(cdp.exceptions.slice(0, 3).join(' | '));
      return 'none';
    });
  } catch (err) {
    failed += 1;
    checks.push({ name: 'harness', status: 'FAIL', error: String(err.message || err) });
    console.error(`[FAIL     ] harness: ${err.message || err}`);
  } finally {
    if (cdp && clipProjectId) {
      try {
        await cdp.evaluate(`(async () => {
          await fetch('/api/clip/projects/${clipProjectId}?delete_files=true', { method: 'DELETE' });
        })()`);
        console.log(`[CLEANUP   ] removed temporary clip project ${clipProjectId}`);
      } catch (err) {
        console.error(`[CLEANUP   ] could not remove ${clipProjectId}: ${err.message || err}`);
      }
    }
    if (cdp) cdp.close();
    if (child && child.exitCode === null) {
      child.kill('SIGTERM');
      try {
        await Promise.race([once(child, 'exit'), sleep(5000)]);
      } catch { /* ignore */ }
      if (child.exitCode === null) child.kill('SIGKILL');
    }
    const report = {
      id: 'ui-smoke-' + Date.now().toString(36),
      started_at: started,
      finished_at: new Date().toISOString(),
      status: failed ? 'FAIL' : 'PASS',
      total: checks.length,
      pass: checks.filter((c) => c.status === 'PASS').length,
      fail: failed,
      checks,
      environment: { node: process.version, electron: packagedBin ? 'packaged app' : 'dev app', cdp: true },
    };
    fs.mkdirSync(path.dirname(REPORT), { recursive: true });
    fs.writeFileSync(REPORT, JSON.stringify(report, null, 2) + '\n');
    console.log(`\nUI_SMOKE ${report.status}: ${report.pass} PASS / ${report.fail} FAIL`);
    console.log(`REPORT ${path.relative(ROOT, REPORT)}`);
    if (failed) process.exitCode = 1;
  }
}

main();
