import { describe, expect, it } from 'vitest';
import {
  buildAuthWebSocketProtocols,
  getAdminBase,
  getApiBase,
  getSystemFromRoute,
  getWsBase,
  makeDeviceKey,
  parseDeviceKey,
} from '../systems';

describe('systems helpers', () => {
  it('builds BT/SY API and WebSocket paths through the frontend origin', () => {
    window.history.pushState({}, '', 'http://fntl.local:5173/main');

    expect(getApiBase('bt')).toBe('/bt-api');
    expect(getApiBase('sy')).toBe('/sy-api');
    expect(getWsBase('bt')).toBe('ws://fntl.local:5173/bt-ws');
    expect(getWsBase('sy')).toBe('ws://fntl.local:5173/sy-ws');
    expect(getAdminBase('bt')).toBe('/bt-admin');
    expect(getAdminBase('sy')).toBe('/sy-admin');
  });

  it('uses BT as the fallback route system and validates device keys', () => {
    expect(getSystemFromRoute('sy')).toBe('sy');
    expect(getSystemFromRoute('unknown')).toBe('bt');
    expect(makeDeviceKey('sy', 101)).toBe('sy:101');
    expect(parseDeviceKey('bt:12')).toEqual({ system: 'bt', deviceId: 12 });
    expect(parseDeviceKey('xx:12')).toBeNull();
    expect(parseDeviceKey('bt:not-a-number')).toBeNull();
  });

  it('builds authenticated WebSocket subprotocols without leaking empty tokens', () => {
    expect(buildAuthWebSocketProtocols('abc.def')).toEqual(['bt-nms', 'jwt.abc.def']);
    expect(buildAuthWebSocketProtocols('')).toEqual(['bt-nms']);
    expect(buildAuthWebSocketProtocols(null)).toEqual(['bt-nms']);
  });
});
