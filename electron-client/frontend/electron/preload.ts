import { contextBridge, ipcRenderer } from 'electron';
import type { ClientConfig } from './config.js';

contextBridge.exposeInMainWorld('btNmsClient', {
  getConfig: () => ipcRenderer.invoke('client:getConfig') as Promise<ClientConfig | null>,
  saveConfig: (config: ClientConfig) => ipcRenderer.invoke('client:saveConfig', config) as Promise<void>,
  openSettings: () => ipcRenderer.invoke('client:openSettings') as Promise<void>,
  openBackendAdmin: (system: 'bt' | 'sy', path: string) =>
    ipcRenderer.invoke('client:openBackendAdmin', system, path) as Promise<void>,
});

ipcRenderer.on('client:open-settings', () => {
  window.dispatchEvent(new CustomEvent('bt-nms-client-open-settings'));
});
