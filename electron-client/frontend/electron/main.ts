import { app, BrowserWindow, ipcMain, Menu, nativeImage, shell, Tray } from 'electron';
import path from 'node:path';
import { DEFAULT_CLIENT_CONFIG, loadClientConfig, saveClientConfig, type ClientConfig } from './config.js';
import { startDesktopServer, type DesktopServer } from './proxy.js';

type SystemType = 'bt' | 'sy';

let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let desktopServer: DesktopServer | null = null;
let clientConfig: ClientConfig | null = null;

const APP_NAME = '贝通网管客户端';

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
  if (!mainWindow) {
    return;
  }
  if (mainWindow.isMinimized()) {
    mainWindow.restore();
  }
  mainWindow.show();
  mainWindow.focus();
}

function requestSettingsDialog(): void {
  showMainWindow();
  mainWindow?.webContents.send('client:open-settings');
}

function buildAdminUrl(system: SystemType, adminPath: string): string {
  const config = clientConfig || DEFAULT_CLIENT_CONFIG;
  const baseUrl = system === 'bt' ? config.btBaseUrl : config.syBaseUrl;
  const target = new URL(adminPath.replace(/^\/+/, ''), `${baseUrl}/`);
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

function createMainWindow(startUrl: string): void {
  mainWindow = new BrowserWindow({
    title: APP_NAME,
    width: 1360,
    height: 860,
    minWidth: 1100,
    minHeight: 720,
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: getPreloadPath(),
      sandbox: false,
    },
  });

  mainWindow.once('ready-to-show', () => {
    showMainWindow();
  });
  mainWindow.on('closed', () => {
    mainWindow = null;
  });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (desktopServer && url.startsWith(desktopServer.origin)) {
      return { action: 'allow' };
    }
    void shell.openExternal(url);
    return { action: 'deny' };
  });

  void mainWindow.loadURL(startUrl);
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
  });
  createMainWindow(desktopServer.origin);
  createTray();
  Menu.setApplicationMenu(null);

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0 && desktopServer) {
      createMainWindow(desktopServer.origin);
    } else {
      showMainWindow();
    }
  });
}

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
  app.quit();
});
