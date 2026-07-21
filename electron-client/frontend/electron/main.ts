import { execFile } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
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
import { DEFAULT_CLIENT_CONFIG, loadClientConfig, saveClientConfig, type ClientConfig } from './config.js';
import { resolveDesktopServerPort, startDesktopServer, type DesktopServer } from './proxy.js';
import {
  BACKGROUND_LAUNCH_ARGUMENT,
  buildWatchdogTaskArguments,
  consumeRelaunchAttempt,
  isBackgroundLaunch,
  LOGIN_ITEM_NAME,
  RecoveryThrottle,
  shouldRecoverRenderer,
  WATCHDOG_INSTALL_MARKER,
} from './recovery.js';
import { buildDesktopWebPreferences, buildDesktopWindowOpenResponse } from './windowOptions.js';

type SystemType = 'bt' | 'sy';
type LogLevel = 'INFO' | 'WARN' | 'ERROR';

const APP_NAME = '贝通网管客户端';
const LOG_MAX_BYTES = 5 * 1024 * 1024;
const MAIN_RELAUNCH_LIMIT = 3;
const MAIN_RELAUNCH_WINDOW_MS = 5 * 60 * 1_000;
const PROXY_HEALTH_INTERVAL_MS = 30_000;
const PROXY_HEALTH_FAILURE_LIMIT = 3;
const RENDERER_UNRESPONSIVE_TIMEOUT_MS = 10_000;
const rendererRecoveryThrottle = new RecoveryThrottle(4, 2 * 60 * 1_000);
const windows = new Set<BrowserWindow>();
const recoveringWindows = new Set<number>();
const unresponsiveTimers = new Map<number, NodeJS.Timeout>();

let focusedWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let desktopServer: DesktopServer | null = null;
let clientConfig: ClientConfig | null = null;
let healthTimer: NodeJS.Timeout | null = null;
let consecutiveHealthFailures = 0;
let isQuitting = false;
let relaunchScheduled = false;

app.setName(APP_NAME);
const backgroundLaunch = isBackgroundLaunch(process.argv);

// Alarm playback must not wait for a user gesture in the always-on desktop client.
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');

function getAppRoot(): string {
  return app.getAppPath();
}

function getConfigPath(): string {
  return path.join(app.getPath('userData'), 'client-config.json');
}

function getRecoveryStatePath(): string {
  return path.join(app.getPath('userData'), 'recovery-state.json');
}

function getPreloadPath(): string {
  return path.join(getAppRoot(), 'electron-dist', 'preload.js');
}

function getDistDir(): string {
  return path.join(getAppRoot(), 'dist');
}

function stringifyError(error: unknown): string {
  if (error instanceof Error) {
    return error.stack || error.message;
  }
  return String(error);
}

function writeClientLog(level: LogLevel, message: string, error?: unknown): void {
  const suffix = error === undefined ? '' : `\n${stringifyError(error)}`;
  const line = `[${new Date().toISOString()}] [${level}] ${message}${suffix}\n`;
  try {
    const logDirectory = path.join(app.getPath('userData'), 'logs');
    const logPath = path.join(logDirectory, 'client.log');
    fs.mkdirSync(logDirectory, { recursive: true });
    try {
      if (fs.statSync(logPath).size >= LOG_MAX_BYTES) {
        const previousLogPath = `${logPath}.1`;
        fs.rmSync(previousLogPath, { force: true });
        fs.renameSync(logPath, previousLogPath);
      }
    } catch {
      // The log does not exist yet.
    }
    fs.appendFileSync(logPath, line, 'utf8');
  } catch (logError) {
    console.error('Unable to write client log', logError);
  }

  if (level === 'ERROR') {
    console.error(message, error);
  } else if (level === 'WARN') {
    console.warn(message, error);
  } else {
    console.info(message);
  }
}

function loadRelaunchHistory(): number[] {
  try {
    const parsed = JSON.parse(fs.readFileSync(getRecoveryStatePath(), 'utf8')) as { relaunches?: unknown };
    return Array.isArray(parsed.relaunches)
      ? parsed.relaunches.filter((value): value is number => typeof value === 'number')
      : [];
  } catch {
    return [];
  }
}

function saveRelaunchHistory(history: number[]): void {
  try {
    fs.mkdirSync(app.getPath('userData'), { recursive: true });
    fs.writeFileSync(
      getRecoveryStatePath(),
      `${JSON.stringify({ relaunches: history }, null, 2)}\n`,
      'utf8',
    );
  } catch (error) {
    writeClientLog('WARN', '无法保存客户端恢复状态', error);
  }
}

function scheduleAppRelaunch(reason: string, error?: unknown): void {
  if (isQuitting || relaunchScheduled) {
    return;
  }

  const decision = consumeRelaunchAttempt(
    loadRelaunchHistory(),
    Date.now(),
    MAIN_RELAUNCH_LIMIT,
    MAIN_RELAUNCH_WINDOW_MS,
  );
  saveRelaunchHistory(decision.history);

  if (!decision.allowed) {
    writeClientLog('ERROR', `客户端重启次数超限，退出并等待外部看门狗恢复：${reason}`, error);
    isQuitting = true;
    setTimeout(() => app.exit(1), 250).unref();
    return;
  }

  relaunchScheduled = true;
  writeClientLog('ERROR', `客户端即将自动重启：${reason}`, error);
  setTimeout(() => {
    isQuitting = true;
    app.relaunch();
    app.exit(1);
  }, 500).unref();
}

async function refreshClientConfig(): Promise<ClientConfig | null> {
  clientConfig = await loadClientConfig(getConfigPath());
  return clientConfig;
}

function getActiveWindow(): BrowserWindow | null {
  if (focusedWindow && !focusedWindow.isDestroyed()) {
    return focusedWindow;
  }
  return Array.from(windows).find((window) => !window.isDestroyed()) ?? null;
}

function showMainWindow(): void {
  const targetWindow = getActiveWindow();
  if (!targetWindow) {
    createClientWindow(true);
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
  const targetWindow = getActiveWindow();
  if (!targetWindow) {
    return;
  }
  if (targetWindow.webContents.isLoadingMainFrame()) {
    targetWindow.webContents.once('did-finish-load', () => {
      targetWindow.webContents.send('client:open-settings');
    });
    return;
  }
  targetWindow.webContents.send('client:open-settings');
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

function quitFromUserAction(): void {
  isQuitting = true;
  app.quit();
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
    { label: '退出', click: quitFromUserAction },
  ]));
  tray.on('click', showMainWindow);
}

function clearUnresponsiveTimer(windowId: number): void {
  const timer = unresponsiveTimers.get(windowId);
  if (timer) {
    clearTimeout(timer);
    unresponsiveTimers.delete(windowId);
  }
}

function recoverRenderer(window: BrowserWindow, reason: string): void {
  if (isQuitting || window.isDestroyed() || recoveringWindows.has(window.id)) {
    return;
  }
  if (!rendererRecoveryThrottle.consume()) {
    scheduleAppRelaunch(`渲染进程连续异常：${reason}`);
    return;
  }

  recoveringWindows.add(window.id);
  clearUnresponsiveTimer(window.id);
  writeClientLog('WARN', `正在恢复窗口 ${window.id}：${reason}`);

  const finishRecovery = (): void => {
    recoveringWindows.delete(window.id);
  };
  const recoveryTimeout = setTimeout(finishRecovery, 15_000);
  recoveryTimeout.unref();
  window.webContents.once('did-finish-load', () => {
    clearTimeout(recoveryTimeout);
    finishRecovery();
  });

  try {
    if (reason === '窗口持续无响应') {
      window.webContents.forcefullyCrashRenderer();
    }
    window.webContents.reloadIgnoringCache();
  } catch (error) {
    clearTimeout(recoveryTimeout);
    finishRecovery();
    const shouldShow = window.isVisible();
    const replacement = createClientWindow(shouldShow);
    if (replacement) {
      window.destroy();
    } else {
      scheduleAppRelaunch('无法重建客户端窗口', error);
    }
  }
}

function registerWindowRecovery(window: BrowserWindow): void {
  window.webContents.on('render-process-gone', (_event, details) => {
    writeClientLog('WARN', `窗口 ${window.id} 渲染进程退出：${details.reason}`);
    if (shouldRecoverRenderer(details.reason)) {
      recoverRenderer(window, `渲染进程退出：${details.reason}`);
    }
  });

  window.on('unresponsive', () => {
    if (unresponsiveTimers.has(window.id)) {
      return;
    }
    writeClientLog('WARN', `窗口 ${window.id} 无响应，等待自动恢复`);
    const timer = setTimeout(() => {
      unresponsiveTimers.delete(window.id);
      recoverRenderer(window, '窗口持续无响应');
    }, RENDERER_UNRESPONSIVE_TIMEOUT_MS);
    timer.unref();
    unresponsiveTimers.set(window.id, timer);
  });
  window.on('responsive', () => clearUnresponsiveTimer(window.id));

  window.webContents.on(
    'did-fail-load',
    (_event, errorCode, errorDescription, validatedUrl, isMainFrame) => {
      if (!isMainFrame || errorCode === -3 || isQuitting) {
        return;
      }
      writeClientLog(
        'WARN',
        `窗口 ${window.id} 页面加载失败：${errorCode} ${errorDescription} ${validatedUrl}`,
      );
      setTimeout(() => recoverRenderer(window, `页面加载失败：${errorCode}`), 1_000).unref();
    },
  );
}

function createMainWindow(
  startUrl: string,
  openOptions?: BrowserWindowConstructorOptions,
  showWhenReady = true,
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
  registerWindowRecovery(window);

  window.once('ready-to-show', () => {
    if (!showWhenReady || window.isDestroyed()) {
      return;
    }
    if (window.isMinimized()) {
      window.restore();
    }
    window.show();
    window.focus();
  });
  window.on('focus', () => {
    focusedWindow = window;
  });
  window.on('close', (event) => {
    if (!isQuitting && windows.size === 1) {
      event.preventDefault();
      window.hide();
      writeClientLog('INFO', '最后一个窗口已隐藏到托盘');
    }
  });
  window.on('closed', () => {
    clearUnresponsiveTimer(window.id);
    recoveringWindows.delete(window.id);
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
        createWindow: (options) => createMainWindow(url, options, true).webContents,
      };
    }

    void shell.openExternal(url);
    return response;
  });

  void window.loadURL(startUrl);
  return window;
}

function createClientWindow(showWhenReady = true): BrowserWindow | null {
  if (!desktopServer) {
    return null;
  }
  return createMainWindow(desktopServer.origin, undefined, showWhenReady);
}

function registerIpcHandlers(): void {
  ipcMain.handle('client:getConfig', async () => clientConfig);

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

function registerWindowsWatchdog(): void {
  if (process.platform !== 'win32' || !app.isPackaged) {
    return;
  }
  const installMarker = path.join(path.dirname(process.execPath), WATCHDOG_INSTALL_MARKER);
  if (!fs.existsSync(installMarker)) {
    writeClientLog('INFO', '免安装模式不注册 Windows 系统级看门狗');
    return;
  }

  try {
    app.setLoginItemSettings({
      openAtLogin: true,
      path: process.execPath,
      args: [BACKGROUND_LAUNCH_ARGUMENT],
      enabled: true,
      name: LOGIN_ITEM_NAME,
    });
  } catch (error) {
    writeClientLog('WARN', '无法配置 Windows 登录启动', error);
  }

  execFile(
    'schtasks.exe',
    buildWatchdogTaskArguments(process.execPath),
    { windowsHide: true },
    (error, stdout, stderr) => {
      if (error) {
        writeClientLog('WARN', `无法注册 Windows 看门狗计划任务：${stderr || error.message}`);
        return;
      }
      writeClientLog('INFO', `Windows 看门狗计划任务已就绪${stdout ? `：${stdout.trim()}` : ''}`);
    },
  );
}

function probeDesktopServer(origin: string): Promise<boolean> {
  return new Promise((resolve) => {
    const request = http.get(`${origin}/?health=${Date.now()}`, (response) => {
      response.resume();
      resolve(response.statusCode === 200);
    });
    request.setTimeout(5_000, () => request.destroy(new Error('health check timeout')));
    request.on('error', () => resolve(false));
  });
}

function startDesktopServerHealthMonitor(): void {
  if (!desktopServer || healthTimer) {
    return;
  }
  healthTimer = setInterval(() => {
    if (!desktopServer || isQuitting) {
      return;
    }
    void probeDesktopServer(desktopServer.origin).then((healthy) => {
      consecutiveHealthFailures = healthy ? 0 : consecutiveHealthFailures + 1;
      if (consecutiveHealthFailures >= PROXY_HEALTH_FAILURE_LIMIT) {
        scheduleAppRelaunch('客户端本机代理连续三次无响应');
      }
    });
  }, PROXY_HEALTH_INTERVAL_MS);
  healthTimer.unref();
}

async function bootstrap(): Promise<void> {
  await app.whenReady();
  await refreshClientConfig();
  registerIpcHandlers();

  desktopServer = await startDesktopServer({
    distDir: getDistDir(),
    getConfig: async () => clientConfig,
    port: resolveDesktopServerPort(process.argv),
  });
  createClientWindow(!backgroundLaunch);
  createTray();
  registerWindowsWatchdog();
  startDesktopServerHealthMonitor();
  Menu.setApplicationMenu(null);
  writeClientLog(
    'INFO',
    `客户端启动完成，版本 ${app.getVersion()}，本机代理 ${desktopServer.origin}${backgroundLaunch ? '，后台模式' : ''}`,
  );

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createClientWindow(true);
    } else {
      showMainWindow();
    }
  });
}

process.on('uncaughtException', (error) => {
  scheduleAppRelaunch('主进程未捕获异常', error);
});
process.on('unhandledRejection', (reason) => {
  scheduleAppRelaunch('主进程未处理 Promise 异常', reason);
});

const hasSingleInstanceLock = app.requestSingleInstanceLock();
if (!hasSingleInstanceLock) {
  app.quit();
} else {
  app.on('second-instance', (_event, commandLine) => {
    if (!isBackgroundLaunch(commandLine)) {
      createClientWindow(true);
    }
  });

  app.on('before-quit', () => {
    isQuitting = true;
    if (healthTimer) {
      clearInterval(healthTimer);
      healthTimer = null;
    }
    tray?.destroy();
    tray = null;
  });

  app.on('window-all-closed', () => {
    if (!isQuitting && desktopServer) {
      setTimeout(() => {
        if (!isQuitting && windows.size === 0) {
          createClientWindow(false);
        }
      }, 250).unref();
    }
  });

  void bootstrap().catch((error) => {
    writeClientLog('ERROR', '客户端启动失败', error);
    if (!backgroundLaunch) {
      dialog.showErrorBox(APP_NAME, `客户端启动失败：${stringifyError(error)}`);
    }
    isQuitting = true;
    app.quit();
  });
}
