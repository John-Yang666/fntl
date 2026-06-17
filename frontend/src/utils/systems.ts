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

const API_BASES: Record<SystemType, string> = {
  bt: '/bt-api',
  sy: '/sy-api',
};

const WS_PATHS: Record<SystemType, string> = {
  bt: '/bt-ws',
  sy: '/sy-ws',
};

const ADMIN_BASES: Record<SystemType, string> = {
  bt: '/bt-admin',
  sy: '/sy-admin',
};

export function isSystemType(value: unknown): value is SystemType {
  return value === 'bt' || value === 'sy';
}

export function getSystemFromRoute(value: unknown): SystemType {
  return isSystemType(value) ? value : 'bt';
}

export function getSystemOrigin(_system: SystemType): string {
  return window.location.origin;
}

export function getApiBase(system: SystemType): string {
  return API_BASES[system];
}

export function getWsBase(system: SystemType): string {
  const wsScheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${wsScheme}://${window.location.host}${WS_PATHS[system]}`;
}

export function getAdminBase(system: SystemType): string {
  return ADMIN_BASES[system];
}

export function buildAuthWebSocketProtocols(token: string | null | undefined): string[] {
  return token ? ['bt-nms', `jwt.${token}`] : ['bt-nms'];
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
