import { describe, expect, it } from 'vitest';
import {
  buildDesktopWindowOpenResponse,
  buildDesktopWebPreferences,
} from './windowOptions';

describe('desktop Electron window options', () => {
  it('uses the preload bridge for every desktop window', () => {
    expect(buildDesktopWebPreferences('C:\\client\\preload.js')).toEqual({
      contextIsolation: true,
      nodeIntegration: false,
      preload: 'C:\\client\\preload.js',
      sandbox: false,
    });
  });

  it('allows local client windows with the same preload bridge', () => {
    expect(buildDesktopWindowOpenResponse(
      'http://127.0.0.1:49152/sy/device/1',
      'http://127.0.0.1:49152',
      'C:\\client\\preload.js',
    )).toEqual({
      action: 'allow',
      overrideBrowserWindowOptions: {
        webPreferences: {
          contextIsolation: true,
          nodeIntegration: false,
          preload: 'C:\\client\\preload.js',
          sandbox: false,
        },
      },
    });
  });

  it('denies external windows so callers can open them in the system browser', () => {
    expect(buildDesktopWindowOpenResponse(
      'https://example.com/admin/',
      'http://127.0.0.1:49152',
      'C:\\client\\preload.js',
    )).toEqual({ action: 'deny' });
  });
});
