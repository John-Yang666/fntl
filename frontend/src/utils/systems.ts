export type SystemType = 'bt' | 'sy';

export const SYSTEMS: SystemType[] = ['bt', 'sy'];

export const SYSTEM_LABELS: Record<SystemType, string> = {
  bt: 'BT',
  sy: 'SY',
};

export const TOKEN_STORAGE_KEYS: Record<SystemType, string> = {
  bt: 'token_bt',
  sy: 'token_sy',
};

export const USER_STORAGE_KEYS: Record<SystemType, string> = {
  bt: 'user_bt',
  sy: 'user_sy',
};

export const SELECTED_DEVICES_KEY = 'selectedDevicesV2';
export const PINNED_DEVICES_KEY = 'pinnedDevicesV1';
export const LEGACY_SELECTED_DEVICES_KEY = 'selectedDevices';

export function isSystemType(value: unknown): value is SystemType {
  return value === 'bt' || value === 'sy';
}

export function getSystemFromRoute(value: unknown): SystemType {
  return isSystemType(value) ? value : 'bt';
}

function getBackendPort(system: SystemType): string {
  return system === 'bt'
    ? import.meta.env.VITE_BT_BACKEND_PORT || '8000'
    : import.meta.env.VITE_SY_BACKEND_PORT || '8001';
}

function getWsPort(system: SystemType): string {
  return system === 'bt'
    ? import.meta.env.VITE_BT_WS_PORT || getBackendPort(system)
    : import.meta.env.VITE_SY_WS_PORT || getBackendPort(system);
}

export function getSystemOrigin(system: SystemType): string {
  return `${window.location.protocol}//${window.location.hostname}:${getBackendPort(system)}`;
}

export function getApiBase(system: SystemType): string {
  return `${getSystemOrigin(system)}/api`;
}

export function getWsBase(system: SystemType): string {
  const wsScheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${wsScheme}://${window.location.hostname}:${getWsPort(system)}`;
}

export function makeDeviceKey(system: SystemType, deviceId: number | string): string {
  return `${system}:${deviceId}`;
}

export function parseDeviceKey(key: string): { system: SystemType; deviceId: number } | null {
  const [system, rawId] = key.split(':');
  if (!isSystemType(system)) {
    return null;
  }

  const deviceId = Number.parseInt(rawId, 10);
  if (Number.isNaN(deviceId)) {
    return null;
  }

  return { system, deviceId };
}
