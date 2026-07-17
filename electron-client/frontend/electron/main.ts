import {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  Menu,
  nativeImage,
  shell,
  Tray,
  type BrowserWindowConstructorOptions,
} from 'electron';
import path from 'node:path';
import { DEFAULT_CLIENT_CONFIG, loadClientConfig, saveClientConfig, type ClientConfig } from './config.js';
import { resolveDesktopServerPort, startDesktopServer, type DesktopServer } from './proxy.js';
import { buildDesktopWebPreferences, buildDesktopWindowOpenResponse } from './windowOptions.js';

type SystemType = 'bt' | 'sy';

const windows = new Set<BrowserWindow>();
let focusedWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let desktopServer: DesktopServer | null = null;
let clientConfig: ClientConfig | null = null;

const APP_NAME = '贝通网管客户端';

// Alarm playback must not wait for a user gesture in the always-on desktop client.
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');

function getAppRoot(): string {
  return app.getAppPath();
}

function getConfigPath(): string {
  return path.join(app.getPath('userData'), 'client-config.json');
}

function getPreloadPath(): string {
  return path.join(getAppRoot(), 'electron-dist', 'preload.js');
}

function getDistDir(): string {
  return path.join(getAppRoot(), 'dist');
}

async function refreshClientConfig(): Promise<ClientConfig | null> {
  clientConfig = await loadClientConfig(getConfigPath());
  return clientConfig;
}

function showMainWindow(): void {
  const targetWindow = focusedWindow && !focusedWindow.isDestroyed()
    ? focusedWindow
    : Array.from(windows).find((window) => !window.isDestroyed());
  if (!targetWindow) {
    return;
  }
  if (targetWindow.isMinimized()) {
    targetWindow.restore();
  }
  targetWindow.show();
  targetWindow.focus();
  focusedWindow = targetWindow;
}

function requestSettingsDialog(): void {
  showMainWindow();
  const targetWindow = focusedWindow && !focusedWindow.isDestroyed()
    ? focusedWindow
    : Array.from(windows).find((window) => !window.isDestroyed());
  targetWindow?.webContents.send('client:open-settings');
}

function buildAdminUrl(system: SystemType, adminPath: string): string {
  const config = clientConfig || DEFAULT_CLIENT_CONFIG;
  const baseUrl = system === 'bt' ? config.btBaseUrl : config.syBaseUrl;
  const adminPrefix = system === 'bt' ? '/bt-admin' : '/sy-admin';
  const normalizedPath = adminPath.startsWith('/bt-admin/') || adminPath.startsWith('/sy-admin/')
    ? adminPath
    : `${adminPrefix}/${adminPath.replace(/^\/?(admin\/)?/, '')}`;
  const target = new URL(normalizedPath.replace(/^\/+/, ''), `${baseUrl}/`);
  return target.toString();
}

function createTray(): void {
  const iconPath = path.join(getDistDir(), 'favicon.ico');
  const image = nativeImage.createFromPath(iconPath);
  tray = new Tray(image.isEmpty() ? nativeImage.createEmpty() : image);
  tray.setToolTip(APP_NAME);
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: '打开客户端', click: showMainWindow },
    { label: '服务地址设置', click: requestSettingsDialog },
    { type: 'separator' },
    { label: '退出', click: () => app.quit() },
  ]));
  tray.on('click', showMainWindow);
}

function createMainWindow(
  startUrl: string,
  openOptions?: BrowserWindowConstructorOptions,
): BrowserWindow {
  const baseOptions: BrowserWindowConstructorOptions = openOptions ?? {
    width: 1360,
    height: 860,
    minWidth: 1100,
    minHeight: 720,
  };
  const window = new BrowserWindow({
    title: APP_NAME,
    show: false,
    ...baseOptions,
    webPreferences: {
      ...baseOptions.webPreferences,
      ...buildDesktopWebPreferences(getPreloadPath()),
    },
  });

  windows.add(window);
  focusedWindow = window;

  window.once('ready-to-show', () => {
    if (window.isMinimized()) {
      window.restore();
    }
    window.show();
    window.focus();
  });
  window.on('focus', () => {
    focusedWindow = window;
  });
  window.on('closed', () => {
    windows.delete(window);
    if (focusedWindow === window) {
      focusedWindow = Array.from(windows).find((item) => !item.isDestroyed()) ?? null;
    }
  });
  window.webContents.setWindowOpenHandler(({ url }) => {
    const response = buildDesktopWindowOpenResponse(url, desktopServer?.origin, getPreloadPath());
    if (response.action === 'allow') {
      return {
        ...response,
        outlivesOpener: true,
        createWindow: (options) => createMainWindow(url, options).webContents,
      };
    }

    void shell.openExternal(url);
    return response;
  });

  void window.loadURL(startUrl);
  return window;
}

function createClientWindow(): void {
  if (!desktopServer) {
    showMainWindow();
    return;
  }
  createMainWindow(desktopServer.origin);
}

function registerIpcHandlers(): void {
  ipcMain.handle('client:getConfig', async () => {
    return clientConfig;
  });

  ipcMain.handle('client:saveConfig', async (_event, config: Partial<ClientConfig>) => {
    clientConfig = await saveClientConfig(getConfigPath(), config);
  });

  ipcMain.handle('client:openSettings', async () => {
    requestSettingsDialog();
  });

  ipcMain.handle('client:openBackendAdmin', async (_event, system: SystemType, adminPath: string) => {
    if (system !== 'bt' && system !== 'sy') {
      throw new Error('Unsupported system');
    }
    await shell.openExternal(buildAdminUrl(system, adminPath));
  });
}

async function bootstrap(): Promise<void> {
  app.setName(APP_NAME);
  await app.whenReady();
  await refreshClientConfig();
  registerIpcHandlers();

  desktopServer = await startDesktopServer({
    distDir: getDistDir(),
    getConfig: async () => clientConfig,
    port: resolveDesktopServerPort(process.argv),
  });
  createClientWindow();
  createTray();
  Menu.setApplicationMenu(null);

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0 && desktopServer) {
      createClientWindow();
    } else {
      showMainWindow();
    }
  });
}

const hasSingleInstanceLock = app.requestSingleInstanceLock();
if (!hasSingleInstanceLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    createClientWindow();
  });

  app.on('before-quit', () => {
    tray?.destroy();
    tray = null;
  });

  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
      app.quit();
    }
  });

  void bootstrap().catch((error) => {
    console.error(error);
    dialog.showErrorBox(
      APP_NAME,
      `客户端启动失败：${error instanceof Error ? error.message : String(error)}`,
    );
    app.quit();
  });
}
