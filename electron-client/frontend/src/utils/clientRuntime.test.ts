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
    expect(getDesktopWsBase('sy')).toBe('ws://127.0.0.1/__client/proxy/sy');
    expect(getDesktopSystemOrigin('sy')).toBe('https://sy.local:8444');
  });

  it('delegates backend Admin opening to the Electron bridge', async () => {
    const openBackendAdminMock = vi.fn();
    setDesktopClientBridgeForTests({
      getConfig: vi.fn().mockResolvedValue({
        btBaseUrl: 'http://bt.local:8000',
        syBaseUrl: 'http://sy.local:8001',
      }),
      saveConfig: vi.fn(),
      openSettings: vi.fn(),
      openBackendAdmin: openBackendAdminMock,
    });
    await initializeDesktopClientConfig();

    await openBackendAdmin('bt', '/admin/myapp/device/');

    expect(openBackendAdminMock).toHaveBeenCalledWith('bt', '/admin/myapp/device/');
  });
});
