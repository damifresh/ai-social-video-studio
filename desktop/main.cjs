'use strict';

/**
 * AI Social Video Studio — Electron main process.
 *
 * The app is a thin, auditable shell around the local FastAPI backend:
 *   1. pick a free loopback port,
 *   2. spawn the bundled CPython with the bundled site-packages,
 *   3. wait for /health,
 *   4. load the built React SPA from the same local origin,
 *   5. shut the backend down cleanly when the app quits.
 *
 * Nothing here talks to the internet. The renderer only gets an IPC bridge
 * with an explicit allowlist of operations.
 */

const { app, BrowserWindow, Menu, dialog, ipcMain, shell } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const net = require('node:net');
const path = require('node:path');

const APP_TITLE = 'AI Social Video Studio';
const isDev = !app.isPackaged;

// Resources root: dev -> desktop/resources, packaged -> <app>/Contents/Resources/runtime
const RUNTIME_ROOT = isDev
  ? path.join(__dirname, 'resources')
  : path.join(process.resourcesPath, 'runtime');

const PATHS = {
  runtime: RUNTIME_ROOT,
  python: path.join(RUNTIME_ROOT, 'python', 'bin', 'python3'),
  packages: path.join(RUNTIME_ROOT, 'py-packages'),
  backend: path.join(RUNTIME_ROOT, 'backend'),
  frontend: path.join(RUNTIME_ROOT, 'frontend-dist'),
  assets: path.join(RUNTIME_ROOT, 'assets'),
  models: path.join(RUNTIME_ROOT, 'models'),
  docs: path.join(RUNTIME_ROOT, 'docs'),
};

let mainWindow = null;
let splashWindow = null;
let backend = null;
let backendPort = null;
let quitting = false;
let backendStartedAt = 0;

function userDataDir() {
  return app.getPath('userData');
}

function dataDir() {
  return path.join(userDataDir(), 'data');
}

function logDir() {
  return path.join(userDataDir(), 'logs');
}

function backendLogPath() {
  return path.join(logDir(), 'backend.log');
}

function appendLog(line) {
  try {
    fs.mkdirSync(logDir(), { recursive: true });
    fs.appendFileSync(backendLogPath(), line.endsWith('\n') ? line : line + '\n');
  } catch {
    /* logging must never crash the app */
  }
}

function findFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

async function waitForHealth(port, timeoutMs = 90000) {
  const started = Date.now();
  let lastError = 'no response';
  while (Date.now() - started < timeoutMs) {
    if (!backend || backend.exitCode !== null) {
      throw new Error(`Backend exited during startup (code ${backend ? backend.exitCode : 'unknown'}).`);
    }
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 2500);
      const res = await fetch(`http://127.0.0.1:${port}/health`, { signal: ctrl.signal });
      clearTimeout(timer);
      if (res.ok) {
        const body = await res.json();
        if (body && body.ok) return body;
        lastError = 'health endpoint returned ok=false';
      } else {
        lastError = `HTTP ${res.status}`;
      }
    } catch (err) {
      lastError = err && err.message ? err.message : String(err);
    }
    await new Promise((r) => setTimeout(r, 350));
  }
  throw new Error(`Backend did not become healthy within ${Math.round(timeoutMs / 1000)} s (${lastError}).`);
}

function backendEnv(port) {
  const env = { ...process.env };
  // A clean, fully local runtime. No user site-packages, no byte-code writes into the app bundle.
  delete env.PYTHONHOME;
  env.PYTHONPATH = [PATHS.backend, PATHS.packages].join(path.delimiter);
  env.PYTHONNOUSERSITE = '1';
  env.PYTHONDONTWRITEBYTECODE = '1';
  env.PYTHONUNBUFFERED = '1';
  env.LAVS_DATA_DIR = dataDir();
  env.LAVS_ASSETS_DIR = PATHS.assets;
  env.LAVS_MODELS_DIR = PATHS.models;
  env.LAVS_FRONTEND_DIST = PATHS.frontend;
  env.LAVS_DESKTOP = '1';
  env.LAVS_PORT = String(port);
  env.PATH = [
    path.join(RUNTIME_ROOT, 'bin'),
    path.join(RUNTIME_ROOT, 'python', 'bin'),
    env.PATH || '/usr/bin:/bin:/usr/sbin:/sbin',
  ].join(path.delimiter);
  return env;
}

async function startBackend() {
  for (const [label, target] of [
    ['Python runtime', PATHS.python],
    ['Backend package', path.join(PATHS.backend, 'app', 'main.py')],
    ['Built frontend', path.join(PATHS.frontend, 'index.html')],
  ]) {
    if (!fs.existsSync(target)) {
      throw new Error(`${label} is missing from this build:\n${target}`);
    }
  }

  await fsp.mkdir(dataDir(), { recursive: true });
  await fsp.mkdir(logDir(), { recursive: true });

  backendPort = await findFreePort();
  const args = [
    '-m', 'uvicorn', 'app.main:app',
    '--host', '127.0.0.1',
    '--port', String(backendPort),
    '--log-level', 'info',
  ];

  appendLog(`\n=== ${new Date().toISOString()} starting backend on 127.0.0.1:${backendPort} ===`);
  appendLog(`python: ${PATHS.python}`);
  appendLog(`data:   ${dataDir()}`);

  backend = spawn(PATHS.python, args, {
    cwd: PATHS.backend,
    env: backendEnv(backendPort),
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  backendStartedAt = Date.now();

  const pipe = (stream, tag) => {
    let buf = '';
    stream.on('data', (chunk) => {
      buf += chunk.toString();
      const lines = buf.split('\n');
      buf = lines.pop() || '';
      for (const line of lines) appendLog(`[${tag}] ${line}`);
    });
  };
  pipe(backend.stdout, 'out');
  pipe(backend.stderr, 'err');

  backend.on('exit', (code, signal) => {
    appendLog(`[exit] backend code=${code} signal=${signal}`);
    if (quitting) return;
    if (mainWindow && !mainWindow.isDestroyed() && Date.now() - backendStartedAt > 4000) {
      showFatal(
        'The local engine stopped unexpectedly.',
        `The backend process exited (code ${code}${signal ? `, signal ${signal}` : ''}). ` +
          'Renders in progress are marked interrupted and their files stay on disk.',
      );
    }
  });

  const health = await waitForHealth(backendPort);
  appendLog(`[health] ${JSON.stringify(health)}`);
  return health;
}

async function stopBackend(reason = 'quit') {
  if (!backend || backend.exitCode !== null) {
    backend = null;
    return;
  }
  appendLog(`[stop] ${reason}`);
  const proc = backend;
  backend = null;
  try {
    proc.kill('SIGTERM');
  } catch {
    /* already gone */
  }
  await new Promise((resolve) => {
    const timer = setTimeout(() => {
      try {
        proc.kill('SIGKILL');
      } catch {
        /* ignore */
      }
      resolve();
    }, 6000);
    proc.once('exit', () => {
      clearTimeout(timer);
      resolve();
    });
  });
}

function splashHtml(status) {
  const safe = String(status).replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]));
  return `data:text/html;charset=utf-8,${encodeURIComponent(`<!doctype html>
<html><head><meta charset="utf-8"><style>
  :root { color-scheme: dark; }
  html,body { margin:0; height:100%; background:#090c14; color:#e6ebf5;
    font: 13px/1.5 -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif; }
  .wrap { height:100%; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:18px; }
  .logo { width:76px; height:76px; border-radius:20px;
    background: linear-gradient(145deg,#6366f1,#8b5cf6 55%,#06b6d4);
    display:flex; align-items:center; justify-content:center; font-size:34px;
    box-shadow: 0 18px 50px rgba(99,102,241,.35); }
  h1 { margin:0; font-size:17px; font-weight:600; letter-spacing:-.01em; }
  .status { color:#8b96ab; font-size:12px; min-height:18px; }
  .bar { width:190px; height:3px; border-radius:3px; background:#1b2233; overflow:hidden; }
  .bar i { display:block; width:40%; height:100%; border-radius:3px;
    background:linear-gradient(90deg,#6366f1,#22d3ee); animation: slide 1.15s ease-in-out infinite; }
  .hint { position:fixed; bottom:18px; color:#4b5568; font-size:11px; }
  @keyframes slide { 0%{transform:translateX(-110%)} 100%{transform:translateX(360%)} }
</style></head>
<body><div class="wrap">
  <div class="logo">🎬</div>
  <h1>AI Social Video Studio</h1>
  <div class="status">${safe}</div>
  <div class="bar"><i></i></div>
  <div class="hint">Everything runs on this Mac — no cloud, no accounts.</div>
</div></body></html>`)}`;
}

function createSplash() {
  splashWindow = new BrowserWindow({
    width: 420,
    height: 300,
    resizable: false,
    frame: false,
    show: true,
    center: true,
    backgroundColor: '#090c14',
    webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false },
  });
  splashWindow.loadURL(splashHtml('Starting the local engine…'));
  splashWindow.on('closed', () => {
    splashWindow = null;
  });
}

function setSplashStatus(status) {
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.loadURL(splashHtml(status));
  }
}

function createWindow(port) {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 940,
    minWidth: 1040,
    minHeight: 700,
    show: false,
    title: APP_TITLE,
    backgroundColor: '#070a12',
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 16, y: 18 },
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      spellcheck: false,
      devTools: true,
    },
  });

  mainWindow.once('ready-to-show', () => {
    if (splashWindow && !splashWindow.isDestroyed()) splashWindow.close();
    mainWindow.show();
    mainWindow.focus();
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  // Keep the app on its own origin. Anything else goes to the user's browser.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) shell.openExternal(url).catch(() => {});
    return { action: 'deny' };
  });
  mainWindow.webContents.on('will-navigate', (event, url) => {
    try {
      const target = new URL(url);
      if (target.hostname === '127.0.0.1' && target.port === String(port)) return;
    } catch {
      /* fall through */
    }
    event.preventDefault();
    if (/^https?:\/\//i.test(url)) shell.openExternal(url).catch(() => {});
  });

  mainWindow.loadURL(`http://127.0.0.1:${port}/`);
}

function showFatal(title, detail) {
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.close();
    splashWindow = null;
  }
  const log = backendLogPath();
  dialog
    .showMessageBox({
      type: 'error',
      title: APP_TITLE,
      message: title,
      detail: `${detail}\n\nBackend log:\n${log}`,
      buttons: ['Quit', 'Show log'],
      defaultId: 1,
      cancelId: 0,
    })
    .then((r) => {
      if (r.response === 1 && fs.existsSync(log)) shell.showItemInFolder(log);
      quitting = true;
      app.quit();
    })
    .catch(() => {
      quitting = true;
      app.quit();
    });
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.show();
}

function isInside(child, parent) {
  const rel = path.relative(parent, child);
  return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel));
}

const allowedOpenRoots = () => [
  dataDir(),
  PATHS.runtime,
  PATHS.docs,
  PATHS.assets,
  PATHS.models,
  logDir(),
].filter(Boolean);

function buildMenu() {
  const template = [
    {
      label: APP_TITLE,
      submenu: [
        { role: 'about', label: `About ${APP_TITLE}` },
        { type: 'separator' },
        {
          label: 'Open Data Folder',
          accelerator: 'CmdOrCtrl+Shift+D',
          click: () => shell.openPath(dataDir()).catch(() => {}),
        },
        {
          label: 'Open Backend Log',
          click: () => {
            const log = backendLogPath();
            if (fs.existsSync(log)) shell.openPath(log).catch(() => {});
            else shell.openPath(logDir()).catch(() => {});
          },
        },
        {
          label: 'Open Documentation',
          click: () => {
            const readme = path.join(PATHS.docs, 'TECHNICAL_DOCUMENTATION.md');
            shell.openPath(fs.existsSync(readme) ? readme : PATHS.docs).catch(() => {});
          },
        },
        { type: 'separator' },
        { role: 'hide' },
        { role: 'hideOthers' },
        { role: 'unhide' },
        { type: 'separator' },
        { role: 'quit' },
      ],
    },
    {
      label: 'Edit',
      submenu: [
        { role: 'undo' },
        { role: 'redo' },
        { type: 'separator' },
        { role: 'cut' },
        { role: 'copy' },
        { role: 'paste' },
        { role: 'selectAll' },
      ],
    },
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'forceReload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' },
      ],
    },
    {
      label: 'Window',
      submenu: [{ role: 'minimize' }, { role: 'zoom' }, { role: 'front' }],
    },
    {
      role: 'help',
      submenu: [
        {
          label: 'Troubleshooting Guide',
          click: () => shell.openPath(path.join(PATHS.docs, 'TROUBLESHOOTING.md')).catch(() => {}),
        },
        {
          label: 'Hardware & Limitations',
          click: () => shell.openPath(path.join(PATHS.docs, 'HARDWARE_LIMITATIONS.md')).catch(() => {}),
        },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function registerIpc() {
  ipcMain.handle('desktop:info', () => ({
    version: app.getVersion(),
    platform: process.platform,
    packaged: app.isPackaged,
    runtime: RUNTIME_ROOT,
    dataDir: dataDir(),
    logPath: backendLogPath(),
    port: backendPort,
  }));

  ipcMain.handle('desktop:revealDataFolder', async () => {
    const target = dataDir();
    await fsp.mkdir(target, { recursive: true });
    const error = await shell.openPath(target);
    return error ? null : target;
  });

  ipcMain.handle('desktop:openPath', async (_event, target) => {
    if (typeof target !== 'string' || !target) throw new Error('A file path is required.');
    let resolved;
    try {
      resolved = await fsp.realpath(target);
    } catch {
      // The file may not exist yet (e.g. a not-yet-written subtitle). Allow a clean parent.
      resolved = path.resolve(target);
    }
    if (!allowedOpenRoots().some((root) => isInside(resolved, path.resolve(root)))) {
      throw new Error('This path is outside the studio folders.');
    }
    const error = await shell.openPath(resolved);
    if (error) throw new Error(error);
    return resolved;
  });

  ipcMain.handle('desktop:openExternal', async (_event, url) => {
    if (typeof url !== 'string' || !/^https:\/\//i.test(url)) {
      throw new Error('Only https:// links are opened externally.');
    }
    await shell.openExternal(url);
  });

  ipcMain.handle('desktop:chooseDirectory', async () => {
    const result = await dialog.showOpenDialog({ properties: ['openDirectory', 'createDirectory'] });
    return result.canceled ? null : result.filePaths[0] || null;
  });
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    } else if (backendPort) {
      createWindow(backendPort);
    }
  });

  app.whenReady().then(async () => {
    app.setName(APP_TITLE);
    buildMenu();
    registerIpc();
    createSplash();
    try {
      setSplashStatus('Starting the local engine…');
      const health = await startBackend();
      setSplashStatus(`Loading studio (v${health.version})…`);
      createWindow(backendPort);
    } catch (err) {
      console.error('[startup]', err);
      appendLog(`[startup] ${err && err.stack ? err.stack : err}`);
      showFatal(
        'The local engine could not start.',
        `${err && err.message ? err.message : String(err)}\n\n` +
          `Bundled Python: ${PATHS.python}\nRuntime folder: ${RUNTIME_ROOT}`,
      );
    }
  });

  app.on('activate', () => {
    if (!mainWindow && backendPort) createWindow(backendPort);
  });

  app.on('window-all-closed', () => {
    // Desktop app: closing the window quits and stops the engine.
    app.quit();
  });

  let shutdownStarted = false;
  app.on('before-quit', (event) => {
    if (shutdownStarted) return;
    shutdownStarted = true;
    quitting = true;
    event.preventDefault();
    stopBackend('app quit')
      .catch(() => {})
      .finally(() => app.exit(0));
  });

  for (const sig of ['SIGINT', 'SIGTERM']) {
    process.on(sig, () => {
      quitting = true;
      stopBackend(sig).finally(() => app.exit(0));
    });
  }
}
