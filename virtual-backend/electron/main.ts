import { app, BrowserWindow, shell } from 'electron';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { createBackendServer } from './simulator/backendServer.js';
import { createControlServer } from './simulator/controlServer.js';
import { createSimulatorStore } from './simulator/store.js';
import type { SystemType } from './simulator/types.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const DEFAULT_PORTS: Record<SystemType, number> = {
  bt: 8000,
  sy: 8001,
};

type ServiceStatus = {
  port: number;
  running: boolean;
  error?: string;
};

const serviceStatus: Record<SystemType, ServiceStatus> = {
  bt: { port: DEFAULT_PORTS.bt, running: false },
  sy: { port: DEFAULT_PORTS.sy, running: false },
};

const stateFilePath = () => join(app.getPath('userData'), 'simulator-state.json');
const staticRootPath = () => join(__dirname, '..', 'dist');

let mainWindow: BrowserWindow | null = null;
let shutdownServers: Array<() => Promise<void>> = [];
let controlPort: number | null = null;
let bootstrapPromise: Promise<void> | null = null;

const startBackendService = async (system: SystemType, store: ReturnType<typeof createSimulatorStore>) => {
  const server = createBackendServer({ system, store });
  shutdownServers.push(server.stop);
  try {
    const started = await server.start(DEFAULT_PORTS[system]);
    serviceStatus[system] = {
      port: started.port,
      running: true,
    };
  } catch (error) {
    serviceStatus[system] = {
      port: DEFAULT_PORTS[system],
      running: false,
      error: error instanceof Error ? error.message : String(error),
    };
  }
};

const createWindow = async (controlPort: number) => {
  mainWindow = new BrowserWindow({
    width: 1180,
    height: 760,
    minWidth: 960,
    minHeight: 620,
    title: '贝通网管虚拟后端',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  await mainWindow.loadURL(`http://127.0.0.1:${controlPort}/`);
  mainWindow.on('closed', () => {
    mainWindow = null;
  });
};

const bootstrap = async () => {
  if (controlPort !== null) {
    await createWindow(controlPort);
    return;
  }

  const store = createSimulatorStore({ persistencePath: stateFilePath() });
  await Promise.all([
    startBackendService('bt', store),
    startBackendService('sy', store),
  ]);

  const controlServer = createControlServer({
    store,
    staticRoot: staticRootPath(),
    getServiceStatus: () => ({ ...serviceStatus }),
  });
  shutdownServers.push(controlServer.stop);
  const control = await controlServer.start(0);
  controlPort = control.port;
  await createWindow(controlPort);
};

const ensureBootstrapped = () => {
  bootstrapPromise = bootstrapPromise ?? bootstrap();
  return bootstrapPromise;
};

app.whenReady().then(ensureBootstrapped);

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0 && mainWindow === null) {
    ensureBootstrapped().catch((error) => {
      console.error('Failed to restart virtual backend window', error);
    });
  }
});

app.on('before-quit', async () => {
  const stops = shutdownServers;
  shutdownServers = [];
  controlPort = null;
  bootstrapPromise = null;
  await Promise.allSettled(stops.map((stop) => stop()));
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
