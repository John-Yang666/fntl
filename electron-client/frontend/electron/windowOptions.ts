import type { BrowserWindowConstructorOptions, WebPreferences, WindowOpenHandlerResponse } from 'electron';

export function buildDesktopWebPreferences(preloadPath: string): WebPreferences {
  return {
    contextIsolation: true,
    nodeIntegration: false,
    preload: preloadPath,
    sandbox: false,
  };
}

export function buildDesktopWindowOpenResponse(
  url: string,
  desktopOrigin: string | null | undefined,
  preloadPath: string,
): WindowOpenHandlerResponse {
  if (desktopOrigin && url.startsWith(desktopOrigin)) {
    const overrideBrowserWindowOptions: BrowserWindowConstructorOptions = {
      webPreferences: buildDesktopWebPreferences(preloadPath),
    };
    return {
      action: 'allow',
      overrideBrowserWindowOptions,
    };
  }

  return { action: 'deny' };
}
