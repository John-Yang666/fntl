import type { SystemType } from '@/utils/systems';

export interface ClientConfig {
  btBaseUrl: string;
  syBaseUrl: string;
}

export interface BtNmsClientBridge {
  getConfig: () => Promise<ClientConfig | null>;
  saveConfig: (config: ClientConfig) => Promise<void>;
  openSettings: () => Promise<void>;
  openBackendAdmin: (system: SystemType, path: string) => Promise<void>;
}

export const DEFAULT_CLIENT_CONFIG: ClientConfig = {
  btBaseUrl: 'http://127.0.0.1:8000',
  syBaseUrl: 'http://127.0.0.1:8001',
};

let bridgeOverride: BtNmsClientBridge | null | undefined;
let desktopConfig: ClientConfig | null = null;
let configLoaded = false;

function normalizeBackendBaseUrl(value: string): string {
  return value.trim().replace(/\/+$/, '');
}

export function getClientBridge(): BtNmsClientBridge | null {
  if (bridgeOverride !== undefined) {
    return bridgeOverride;
  }
  if (typeof window === 'undefined') {
    return null;
  }
  return window.btNmsClient ?? null;
}

export function setDesktopClientBridgeForTests(bridge: BtNmsClientBridge | null): void {
  bridgeOverride = bridge;
  desktopConfig = null;
  configLoaded = false;
}

export function isDesktopClient(): boolean {
  return !!getClientBridge();
}

export async function initializeDesktopClientConfig(): Promise<ClientConfig | null> {
  const bridge = getClientBridge();
  if (!bridge) {
    desktopConfig = null;
    configLoaded = true;
    return null;
  }
  const config = await bridge.getConfig();
  desktopConfig = config ? {
    btBaseUrl: normalizeBackendBaseUrl(config.btBaseUrl),
    syBaseUrl: normalizeBackendBaseUrl(config.syBaseUrl),
  } : null;
  configLoaded = true;
  return desktopConfig;
}

export function hasLoadedDesktopClientConfig(): boolean {
  return configLoaded;
}

export function getDesktopClientConfig(): ClientConfig | null {
  return desktopConfig;
}

export async function saveDesktopClientConfig(config: ClientConfig): Promise<void> {
  const bridge = getClientBridge();
  if (!bridge) {
    throw new Error('Desktop client bridge is unavailable');
  }
  const normalized = {
    btBaseUrl: normalizeBackendBaseUrl(config.btBaseUrl),
    syBaseUrl: normalizeBackendBaseUrl(config.syBaseUrl),
  };
  await bridge.saveConfig(normalized);
  desktopConfig = normalized;
  configLoaded = true;
}

export async function openDesktopSettings(): Promise<void> {
  await getClientBridge()?.openSettings();
}

export function getDesktopApiBase(system: SystemType): string {
  return `/__client/proxy/${system}/api`;
}

export function getDesktopWsBase(system: SystemType): string {
  const protocol = typeof window !== 'undefined' && window.location.protocol === 'https:' ? 'wss' : 'ws';
  const host = typeof window !== 'undefined' ? window.location.host : '127.0.0.1';
  return `${protocol}://${host}/__client/proxy/${system}`;
}

export function getDesktopSystemOrigin(system: SystemType): string {
  const config = desktopConfig || DEFAULT_CLIENT_CONFIG;
  return system === 'bt' ? config.btBaseUrl : config.syBaseUrl;
}

export async function openBackendAdmin(system: SystemType, path: string): Promise<void> {
  const bridge = getClientBridge();
  if (bridge) {
    await bridge.openBackendAdmin(system, path);
    return;
  }
  window.open(`${getDesktopSystemOrigin(system)}${path}`, '_blank');
}
