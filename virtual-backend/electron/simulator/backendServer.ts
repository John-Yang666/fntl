import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';
import { Buffer } from 'node:buffer';
import { WebSocketServer, type WebSocket } from 'ws';
import type { DemoDevice, FaultState, SystemType } from './types.js';
import { createSimulatorStore } from './store.js';

type SimulatorStore = ReturnType<typeof createSimulatorStore>;

interface BackendServerOptions {
  system: SystemType;
  store: SimulatorStore;
}

type RecordEndpoint = 'alerts' | 'relay-actions' | 'user-operations' | 'switch-data' | 'analog-data';

const RECORD_ENDPOINTS: Record<RecordEndpoint, keyof ReturnType<SimulatorStore['getSnapshot']>['records']['bt']> = {
  alerts: 'alerts',
  'relay-actions': 'relayActions',
  'user-operations': 'userOperations',
  'switch-data': 'switchData',
  'analog-data': 'analogData',
};

const DEMO_USER = {
  username: 'admin',
  email: 'admin@beitong.demo',
  groups: ['演示用户'],
  is_staff: true,
  is_superuser: true,
  permissions: ['*'],
};

const normalizePath = (pathname: string) =>
  pathname.length > 1 && pathname.endsWith('/') ? pathname.slice(0, -1) : pathname;

const readJsonBody = async (request: IncomingMessage) => {
  const chunks: Buffer[] = [];
  for await (const chunk of request) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  const rawBody = Buffer.concat(chunks).toString('utf8').trim();
  if (!rawBody) {
    return {};
  }
  return JSON.parse(rawBody);
};

const sendJson = (response: ServerResponse, status: number, body: unknown) => {
  response.writeHead(status, {
    'access-control-allow-origin': '*',
    'access-control-allow-methods': 'GET,POST,PUT,PATCH,DELETE,OPTIONS',
    'access-control-allow-headers': 'authorization,content-type',
    'content-type': 'application/json; charset=utf-8',
  });
  response.end(JSON.stringify(body));
};

const sendHtml = (response: ServerResponse, html: string) => {
  response.writeHead(200, {
    'access-control-allow-origin': '*',
    'content-type': 'text/html; charset=utf-8',
  });
  response.end(html);
};

const sendNotFound = (response: ServerResponse) => sendJson(response, 404, { detail: 'Not found' });

const buildToken = (system: SystemType, kind: 'access' | 'refresh') =>
  `sim-${kind}.${system}.${Buffer.from(`admin:${Date.now()}`).toString('base64url')}`;

const publicDevice = (device: DemoDevice) => ({
  id: device.device_id,
  device_id: device.device_id,
  name: device.name,
  depot: device.depot,
  line: device.line,
  ip_address: device.ip_address,
  x_coordinate: device.x_coordinate,
  y_coordinate: device.y_coordinate,
  direction1_neighbor_id: device.direction1_neighbor_id,
  direction1_neighbor_direction: device.direction1_neighbor_direction,
  direction2_neighbor_id: device.direction2_neighbor_id,
  direction2_neighbor_direction: device.direction2_neighbor_direction,
  direction3_neighbor_id: device.direction3_neighbor_id ?? null,
  direction3_neighbor_direction: device.direction3_neighbor_direction ?? null,
  direction1_enabled: true,
  direction2_enabled: true,
  direction3_enabled: false,
  supports_auto_switch: device.system === 'sy',
  alarm_filters: [],
  remark: device.remark,
});

const deviceStatus = (fault: FaultState) => {
  if (fault === 'offline') return 'offline';
  if (fault === 'alarm') return 'bad';
  return 'good';
};

const directionStatus = (fault: FaultState, direction: 1 | 2) => {
  if (fault === 'offline') return 'offline';
  if (fault === 'direction1_fault' && direction === 1) return 'bad';
  if (fault === 'direction2_fault' && direction === 2) return 'bad';
  return 'good';
};

const topologyStatus = (device: DemoDevice) => ({
  device_id: device.device_id,
  device_status: deviceStatus(device.fault),
  direction1_line_status: directionStatus(device.fault, 1),
  direction2_line_status: directionStatus(device.fault, 2),
  direction3_line_status: 'null',
});

const groupDevicesByLine = (devices: DemoDevice[]) =>
  devices.reduce<Record<string, ReturnType<typeof publicDevice>[]>>((grouped, device) => {
    grouped[device.line] = grouped[device.line] || [];
    grouped[device.line].push(publicDevice(device));
    return grouped;
  }, {});

const paginate = (rows: readonly unknown[], query: URLSearchParams) => {
  const page = Math.max(1, Number(query.get('page') || 1));
  const pageSize = Math.max(1, Number(query.get('page_size') || query.get('pageSize') || rows.length || 1));
  const start = (page - 1) * pageSize;
  return rows.slice(start, start + pageSize);
};

const switchStatusBytes = (device: DemoDevice) => {
  const bytes = new Uint8Array(16);
  if (device.fault === 'direction1_fault') {
    bytes[7] = 0b01000000;
  } else if (device.fault === 'direction2_fault') {
    bytes[11] = 0b01000000;
  }
  return Buffer.from(bytes).toString('base64');
};

const latestAnalogRows = (store: SimulatorStore, deviceId: number) =>
  store.getSnapshot().records.bt.analogData.filter((record) => record.device_id === deviceId);

const latestSwitchHex = (device: DemoDevice) => {
  const faultCode: Record<FaultState, string> = {
    normal: '00',
    offline: '90',
    direction1_fault: '10',
    direction2_fault: '20',
    alarm: 'A0',
  };
  return `7F 7F ${String(device.device_id).padStart(2, '0')} ${faultCode[device.fault]} 00 00 00 F7`;
};

const monitorPayload = (store: SimulatorStore, device: DemoDevice) => {
  const snapshot = store.getSnapshot();
  const records = snapshot.records[device.system];
  return {
    device_id: device.device_id,
    analog: records.analogData
      .filter((record) => record.device_id === device.device_id)
      .slice(0, 20),
    relay: records.relayActions
      .filter((record) => record.device_id === device.device_id)
      .slice(0, 20),
  };
};

const renderAdmin = (system: SystemType, store: SimulatorStore) => {
  const snapshot = store.getSnapshot();
  const devices = snapshot.devices[system];
  const records = snapshot.records[system];
  const activeAlarms = records.alerts.filter((alert) => alert.timestamp_end == null && !alert.is_confirmed);
  const title = `${system.toUpperCase()} 仿真 Admin`;
  const deviceRows = devices
    .map(
      (device) => `<tr><td>${device.device_id}</td><td>${device.name}</td><td>${device.ip_address}</td><td>${device.fault}</td></tr>`,
    )
    .join('');
  const alarmRows = activeAlarms
    .map(
      (alert) =>
        `<tr><td>${alert.device_id}</td><td>${alert.device_name}</td><td>${alert.alarm_code}</td><td>${alert.alarm_meaning}</td><td>${alert.timestamp}</td></tr>`,
    )
    .join('');
  const operationRows = records.userOperations
    .slice(0, 20)
    .map(
      (record) =>
        `<tr><td>${record.device_id ?? ''}</td><td>${record.device_name ?? ''}</td><td>${record.function_code}</td><td>${record.operation}</td><td>${record.username ?? ''}</td><td>${record.timestamp}</td></tr>`,
    )
    .join('');

  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>${title}</title>
  <style>
    body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:24px;background:#f6f7f9;color:#1f2937}
    h1{font-size:22px;margin:0 0 18px}
    h2{font-size:16px;margin:24px 0 10px}
    table{border-collapse:collapse;width:100%;background:white;border:1px solid #d8dee6}
    th,td{border-bottom:1px solid #e5e7eb;padding:8px 10px;text-align:left;font-size:13px}
    th{background:#eef2f7}
  </style>
</head>
<body>
  <h1>${title}</h1>
  <h2>设备</h2>
  <table><thead><tr><th>ID</th><th>名称</th><th>IP</th><th>状态</th></tr></thead><tbody>${deviceRows}</tbody></table>
  <h2>当前告警</h2>
  <table><thead><tr><th>设备ID</th><th>设备名</th><th>告警码</th><th>含义</th><th>时间</th></tr></thead><tbody>${alarmRows}</tbody></table>
  <h2>用户操作</h2>
  <table><thead><tr><th>设备ID</th><th>设备名</th><th>功能码</th><th>操作</th><th>用户</th><th>时间</th></tr></thead><tbody>${operationRows}</tbody></table>
</body>
</html>`;
};

export const createBackendServer = ({ system, store }: BackendServerOptions) => {
  const wsServer = new WebSocketServer({ noServer: true });
  const socketKinds = new WeakMap<WebSocket, { kind: 'topology' | 'device-monitor'; deviceId?: number }>();

  const server = createServer(async (request, response) => {
    response.setHeader('access-control-allow-origin', '*');
    response.setHeader('access-control-allow-methods', 'GET,POST,PUT,PATCH,DELETE,OPTIONS');
    response.setHeader('access-control-allow-headers', 'authorization,content-type');
    if (request.method === 'OPTIONS') {
      response.writeHead(204);
      response.end();
      return;
    }

    try {
      const url = new URL(request.url || '/', `http://${request.headers.host || '127.0.0.1'}`);
      const path = normalizePath(url.pathname);
      const snapshot = store.getSnapshot();
      const devices = snapshot.devices[system];
      const records = snapshot.records[system];

      if (path === '/admin') {
        sendHtml(response, renderAdmin(system, store));
        return;
      }

      if (path === '/api/token' && request.method === 'POST') {
        const body = await readJsonBody(request);
        if (body.username !== 'admin' || body.password !== 'admin') {
          sendJson(response, 401, { detail: 'Invalid demo credentials' });
          return;
        }
        sendJson(response, 200, {
          access: buildToken(system, 'access'),
          refresh: buildToken(system, 'refresh'),
        });
        return;
      }

      if (path === '/api/token/refresh' && request.method === 'POST') {
        sendJson(response, 200, { access: buildToken(system, 'access') });
        return;
      }

      if (path === '/api/user') {
        sendJson(response, 200, DEMO_USER);
        return;
      }

      if (path === '/api/devices-list') {
        sendJson(response, 200, groupDevicesByLine(devices));
        return;
      }

      if (path === '/api/devices/retrieve_with_stations') {
        const deviceId = Number(url.searchParams.get('device_id'));
        const device = devices.find((item) => item.device_id === deviceId);
        if (!device) {
          sendJson(response, 404, { detail: 'Device not found' });
          return;
        }
        const findName = (id: number | null) => devices.find((item) => item.device_id === id)?.name ?? null;
        sendJson(response, 200, {
          ...publicDevice(device),
          direction1_neighbor_name: findName(device.direction1_neighbor_id),
          direction2_neighbor_name: findName(device.direction2_neighbor_id),
        });
        return;
      }

      if (path === '/api/devices') {
        const deviceId = url.searchParams.get('device_id');
        const filtered = deviceId
          ? devices.filter((device) => String(device.device_id) === String(deviceId))
          : devices;
        sendJson(response, 200, {
          count: filtered.length,
          results: filtered.map(publicDevice),
        });
        return;
      }

      if (path === '/api/all-topology-status') {
        sendJson(response, 200, {
          topology_statuses: Object.fromEntries(
            devices.map((device) => [String(device.device_id), topologyStatus(device)]),
          ),
        });
        return;
      }

      if (path === '/api/active-alarms') {
        sendJson(
          response,
          200,
          records.alerts.filter((alert) => alert.timestamp_end == null && !alert.is_confirmed),
        );
        return;
      }

      const confirmMatch = path.match(/^\/api\/active-alarms\/(\d+)\/(\d+)\/confirm$/);
      if (confirmMatch && request.method === 'POST') {
        sendJson(response, 200, store.confirmAlarm(system, Number(confirmMatch[1]), Number(confirmMatch[2])));
        return;
      }

      const sendBtMatch = path.match(/^\/api\/send-command\/(\d+)$/);
      if (sendBtMatch && request.method === 'POST') {
        sendJson(response, 200, store.handleBtCommand(Number(sendBtMatch[1]), await readJsonBody(request)));
        return;
      }

      const sendSyMatch = path.match(/^\/api\/sy\/send-command\/(\d+)$/);
      if (sendSyMatch && request.method === 'POST') {
        sendJson(response, 200, store.handleSyCommand(Number(sendSyMatch[1]), await readJsonBody(request)));
        return;
      }

      const switchMatch = path.match(/^\/api\/switch-status\/(\d+)$/);
      if (switchMatch) {
        const device = devices.find((item) => item.device_id === Number(switchMatch[1]));
        if (!device) {
          sendJson(response, 404, { detail: 'Device not found' });
          return;
        }
        sendJson(response, 200, {
          device_id: device.device_id,
          switch_status: switchStatusBytes(device),
          timestamp: new Date().toISOString(),
        });
        return;
      }

      const analogMatch = path.match(/^\/api\/analog-status\/(\d+)$/);
      if (analogMatch) {
        const rows = latestAnalogRows(store, Number(analogMatch[1]));
        sendJson(response, 200, rows[0] || null);
        return;
      }

      const detailMatch = path.match(/^\/api\/device-detail\/(\d+)$/);
      if (detailMatch) {
        const device = devices.find((item) => item.device_id === Number(detailMatch[1]));
        if (!device) {
          sendJson(response, 404, { detail: 'Device not found' });
          return;
        }
        sendJson(response, 200, publicDevice(device));
        return;
      }

      const sySwitchMatch = path.match(/^\/api\/device_switch_data\/(\d+)$/);
      if (sySwitchMatch) {
        const device = devices.find((item) => item.device_id === Number(sySwitchMatch[1]));
        if (!device) {
          sendJson(response, 404, { detail: 'Device not found' });
          return;
        }
        sendJson(response, 200, {
          latest_switch: {
            timestamp: new Date().toISOString(),
            version: 'A1-virtual',
            hex: latestSwitchHex(device),
          },
        });
        return;
      }

      const recordCountMatch = path.match(/^\/api\/([^/]+)\/count$/);
      const countEndpoint = recordCountMatch?.[1] as RecordEndpoint | undefined;
      if (countEndpoint && countEndpoint in RECORD_ENDPOINTS) {
        const rows = records[RECORD_ENDPOINTS[countEndpoint]];
        sendJson(response, 200, { count: rows.length, approximate: false });
        return;
      }

      const recordListMatch = path.match(/^\/api\/([^/]+)$/);
      const listEndpoint = recordListMatch?.[1] as RecordEndpoint | undefined;
      if (listEndpoint && listEndpoint in RECORD_ENDPOINTS) {
        const rows = records[RECORD_ENDPOINTS[listEndpoint]];
        sendJson(response, 200, {
          count: rows.length,
          results: paginate(rows, url.searchParams),
        });
        return;
      }

      sendNotFound(response);
    } catch (error) {
      sendJson(response, 500, {
        detail: error instanceof Error ? error.message : 'Internal simulator error',
      });
    }
  });

  wsServer.on('connection', (socket, request) => {
    const url = new URL(request.url || '/', `http://${request.headers.host || '127.0.0.1'}`);
    const path = normalizePath(url.pathname);
    const monitorMatch = path.match(/^\/ws\/device-monitor\/(\d+)$/);
    socketKinds.set(
      socket,
      monitorMatch
        ? { kind: 'device-monitor', deviceId: Number(monitorMatch[1]) }
        : { kind: 'topology' },
    );
  });

  server.on('upgrade', (request, socket, head) => {
    const url = new URL(request.url || '/', `http://${request.headers.host || '127.0.0.1'}`);
    const path = normalizePath(url.pathname);
    if (path !== '/ws/topology' && !path.match(/^\/ws\/device-monitor\/\d+$/)) {
      socket.destroy();
      return;
    }
    wsServer.handleUpgrade(request, socket, head, (webSocket) => {
      wsServer.emit('connection', webSocket, request);
    });
  });

  const unsubscribe = store.subscribe((event) => {
    if (event.system !== system) {
      return;
    }
    const snapshot = store.getSnapshot();
    const device = snapshot.devices[system].find((item) => item.device_id === event.deviceId);
    if (!device) {
      return;
    }

    for (const client of wsServer.clients) {
      if (client.readyState !== client.OPEN) {
        continue;
      }
      const kind = socketKinds.get(client);
      if (!kind) {
        continue;
      }
      if (kind.kind === 'topology') {
        client.send(JSON.stringify(topologyStatus(device)));
      } else if (kind.kind === 'device-monitor' && kind.deviceId === device.device_id) {
        client.send(JSON.stringify(monitorPayload(store, device)));
      }
    }
  });

  return {
    start: (port: number) =>
      new Promise<{ port: number }>((resolve, reject) => {
        server.once('error', reject);
        server.listen(port, '127.0.0.1', () => {
          server.off('error', reject);
          resolve({ port: (server.address() as AddressInfo).port });
        });
      }),
    stop: () =>
      new Promise<void>((resolve, reject) => {
        unsubscribe();
        for (const client of wsServer.clients) {
          client.close();
        }
        wsServer.close();
        if (!server.listening) {
          resolve();
          return;
        }
        server.close((error) => {
          if (error) {
            reject(error);
            return;
          }
          resolve();
        });
      }),
    nodeServer: server,
  };
};
