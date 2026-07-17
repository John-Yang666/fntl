import {
  getDesktopAdminBase,
  getDesktopApiBase,
  getDesktopSystemOrigin,
  getDesktopWsBase,
  isDesktopClient,
} from '@/utils/clientRuntime';

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

export const PINNED_DEVICES_KEY = 'pinnedDevicesV1';

export function isSystemType(value: unknown): value is SystemType {
  return value === 'bt' || value === 'sy';
}

export function getSystemFromRoute(value: unknown): SystemType {
  return isSystemType(value) ? value : 'bt';
}

export function getSystemOrigin(system: SystemType): string {
  if (isDesktopClient()) {
    return getDesktopSystemOrigin(system);
  }
  return window.location.origin;
}

export function getApiBase(system: SystemType): string {
  if (isDesktopClient()) {
    return getDesktopApiBase(system);
  }
  return system === 'bt' ? '/bt-api' : '/sy-api';
}

export function getWsBase(system: SystemType): string {
  if (isDesktopClient()) {
    return getDesktopWsBase(system);
  }
  const wsScheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${wsScheme}://${window.location.host}/${system === 'bt' ? 'bt-ws' : 'sy-ws'}`;
}

export function getAdminBase(system: SystemType): string {
  if (isDesktopClient()) {
    return getDesktopAdminBase(system);
  }
  return system === 'bt' ? '/bt-admin' : '/sy-admin';
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
