import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  getDesktopApiBase,
  getDesktopSystemOrigin,
  getDesktopWsBase,
  initializeDesktopClientConfig,
  isDesktopClient,
  openBackendAdmin,
  setDesktopClientBridgeForTests,
} from './clientRuntime';

describe('frontend desktop client runtime', () => {
  afterEach(() => {
    setDesktopClientBridgeForTests(null);
    vi.restoreAllMocks();
  });

  it('reports non-desktop mode when the Electron bridge is unavailable', () => {
    expect(isDesktopClient()).toBe(false);
  });

  it('initializes desktop config and exposes local proxy API and WebSocket bases', async () => {
    setDesktopClientBridgeForTests({
      getConfig: vi.fn().mockResolvedValue({
        btBaseUrl: 'http://bt.local:8000',
        syBaseUrl: 'https://sy.local:8444',
      }),
      saveConfig: vi.fn(),
      openSettings: vi.fn(),
      openBackendAdmin: vi.fn(),
    });

    await initializeDesktopClientConfig();

    expect(isDesktopClient()).toBe(true);
    expect(getDesktopApiBase('bt')).toBe('/__client/proxy/bt/api');
    expect(getDesktopWsBase('sy')).toBe('ws://127.0.0.1/__client/proxy/sy/ws');
    expect(getDesktopSystemOrigin('bt')).toBe('http://bt.local:38173');
    expect(getDesktopSystemOrigin('sy')).toBe('https://sy.local:38443');
  });

  it('delegates same-origin Admin opening to the Electron bridge', async () => {
    const openBackendAdminMock = vi.fn();
    setDesktopClientBridgeForTests({
      getConfig: vi.fn().mockResolvedValue({
        btBaseUrl: 'http://frontend.local:38173',
        syBaseUrl: 'http://frontend.local:38173',
      }),
      saveConfig: vi.fn(),
      openSettings: vi.fn(),
      openBackendAdmin: openBackendAdminMock,
    });
    await initializeDesktopClientConfig();

    await openBackendAdmin('bt', '/bt-admin/myapp/device/');

    expect(openBackendAdminMock).toHaveBeenCalledWith('bt', '/bt-admin/myapp/device/');
  });
});
