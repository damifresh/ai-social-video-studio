'use strict';

const { contextBridge, ipcRenderer } = require('electron');

/**
 * Minimal, allowlisted bridge. The renderer never gets Node or arbitrary IPC:
 * only these allowlisted calls cross the boundary, and the main process validates
 * every path/link again on its side.
 */
contextBridge.exposeInMainWorld('desktop', {
  version: process.env.npm_package_version || '1.0.0',
  platform: process.platform,
  info: () => ipcRenderer.invoke('desktop:info'),
  revealDataFolder: () => ipcRenderer.invoke('desktop:revealDataFolder'),
  openPath: (target) => ipcRenderer.invoke('desktop:openPath', target),
  openExternal: (url) => ipcRenderer.invoke('desktop:openExternal', url),
  chooseDirectory: () => ipcRenderer.invoke('desktop:chooseDirectory'),
});
