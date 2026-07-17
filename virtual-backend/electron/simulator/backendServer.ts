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

type RuntimeConfigGroup = 'runtime' | 'auth' | 'cleanup';
type RuntimeConfigFieldType = 'integer' | 'alarm_delay_map' | 'time' | 'boolean';

interface RuntimeConfigField {
  key: string;
  label: string;
  type: RuntimeConfigFieldType;
  group: RuntimeConfigGroup;
  min?: number;
  max?: number;
  default: unknown;
  codes?: number[];
  alarm_meanings?: Record<string, string>;
}

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

const sendText = (response: ServerResponse, status: number, body: string, contentType = 'text/plain; charset=utf-8') => {
  response.writeHead(status, {
    'access-control-allow-origin': '*',
    'content-type': contentType,
  });
  response.end(body);
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

const paginated = <T>(rows: readonly T[], query: URLSearchParams) => ({
  count: rows.length,
  results: paginate(rows, query),
});

const OPS_DEPOTS = [
  {
    id: 1,
    name: '演示车站',
    is_active: true,
    ordering: 1,
    remark: '虚拟后端默认车间',
  },
];

const OPS_LINES = [
  {
    id: 1,
    name: '演示线路',
    is_active: true,
    ordering: 1,
    remark: '虚拟后端默认线路',
  },
];

const opsDevice = (device: DemoDevice) => ({
  ...publicDevice(device),
  id: device.device_id,
  depot_id: 1,
  depot_name: device.depot,
  line_id: 1,
  line_name: device.line,
  direction1_enabled: true,
  direction2_enabled: true,
  alarm_filters: [],
  remark: device.remark,
});

const filterOpsDevices = (devices: DemoDevice[], query: URLSearchParams) => {
  const deviceId = query.get('device_id')?.trim();
  const name = query.get('name')?.trim().toLowerCase();
  const ipAddress = query.get('ip_address')?.trim();
  const depot = query.get('depot')?.trim();
  const line = query.get('line')?.trim();

  return devices
    .map(opsDevice)
    .filter((device) => !deviceId || String(device.device_id).includes(deviceId))
    .filter((device) => !name || device.name.toLowerCase().includes(name))
    .filter((device) => !ipAddress || device.ip_address.includes(ipAddress))
    .filter((device) => !depot || String(device.depot_id) === depot)
    .filter((device) => !line || String(device.line_id) === line);
};

const runtimeConfigSchema = (system: SystemType): RuntimeConfigField[] => {
  const alarmMeanings = {
    '2001': '一方向线路故障',
    '2002': '二方向线路故障',
    '9001': '通信中断',
  };
  return [
    {
      key: 'TOPOLOGY_POLL_INTERVAL_SECONDS',
      label: '拓扑轮询间隔',
      type: 'integer',
      group: 'runtime',
      min: 1,
      max: 300,
      default: 5,
    },
    {
      key: 'DEVICE_STATUS_CACHE_SECONDS',
      label: '设备状态缓存秒数',
      type: 'integer',
      group: 'runtime',
      min: 0,
      max: 3600,
      default: system === 'bt' ? 10 : 15,
    },
    {
      key: 'ALARM_DELAY_SECONDS',
      label: '告警延时',
      type: 'alarm_delay_map',
      group: 'runtime',
      min: 0,
      max: 3600,
      codes: [2001, 2002, 9001],
      alarm_meanings: alarmMeanings,
      default: { '2001': 0, '2002': 0, '9001': 5 },
    },
    {
      key: 'CLEANUP_SCHEDULE_TIME',
      label: '自动清理时间',
      type: 'time',
      group: 'cleanup',
      default: '02:30',
    },
    {
      key: 'ALARM_RECORD_RETENTION_DAYS',
      label: '历史告警 保留天数',
      type: 'integer',
      group: 'cleanup',
      min: 1,
      max: 3650,
      default: 180,
    },
    {
      key: 'ALARM_RECORD_AUTO_EXPORT',
      label: '历史告警 自动导出',
      type: 'boolean',
      group: 'cleanup',
      default: true,
    },
    {
      key: 'RELAY_ACTION_RETENTION_DAYS',
      label: '继电器动作 保留天数',
      type: 'integer',
      group: 'cleanup',
      min: 1,
      max: 3650,
      default: 180,
    },
    {
      key: 'RELAY_ACTION_AUTO_EXPORT',
      label: '继电器动作 自动导出',
      type: 'boolean',
      group: 'cleanup',
      default: true,
    },
    {
      key: 'USER_OPERATION_RETENTION_DAYS',
      label: '用户操作 保留天数',
      type: 'integer',
      group: 'cleanup',
      min: 1,
      max: 3650,
      default: 365,
    },
    {
      key: 'USER_OPERATION_AUTO_EXPORT',
      label: '用户操作 自动导出',
      type: 'boolean',
      group: 'cleanup',
      default: true,
    },
    {
      key: 'SWITCH_DATA_RETENTION_DAYS',
      label: '开关量 保留天数',
      type: 'integer',
      group: 'cleanup',
      min: 1,
      max: 3650,
      default: 90,
    },
    {
      key: 'SWITCH_DATA_AUTO_EXPORT',
      label: '开关量 自动导出',
      type: 'boolean',
      group: 'cleanup',
      default: false,
    },
    {
      key: 'ACCESS_TOKEN_LIFETIME_MINUTES',
      label: 'Access Token 有效分钟数',
      type: 'integer',
      group: 'auth',
      min: 1,
      max: 1440,
      default: 60,
    },
    {
      key: 'REFRESH_TOKEN_LIFETIME_HOURS',
      label: 'Refresh Token 有效小时数',
      type: 'integer',
      group: 'auth',
      min: 1,
      max: 720,
      default: 24,
    },
  ];
};

const runtimeConfigPayload = (system: SystemType, values?: Record<string, unknown>) => {
  const schema = runtimeConfigSchema(system);
  const defaults = Object.fromEntries(schema.map((field) => [field.key, field.default]));
  return {
    schema,
    defaults,
    values: {
      ...defaults,
      ...(values || {}),
    },
    updated_at: new Date().toISOString(),
    updated_by: 'admin',
    storage_ready: true,
    cleanup_ready: true,
    cleanup_error: null,
  };
};

const cleanupExportTestPayload = () => ({
  results: {
    alerts: {
      status: 'success',
      model: 'AlarmData',
      candidate_count: 0,
      export_path: 'DATA_DIR/cleanup_exports/alerts.csv',
      error: '',
    },
    relay_actions: {
      status: 'success',
      model: 'RelayAction',
      candidate_count: 0,
      export_path: 'DATA_DIR/cleanup_exports/relay_actions.csv',
      error: '',
    },
    user_operations: {
      status: 'success',
      model: 'UserOperation',
      candidate_count: 0,
      export_path: 'DATA_DIR/cleanup_exports/user_operations.csv',
      error: '',
    },
  },
});

const helpFaqItems = () => [
  {
    id: 1,
    title: '如何确认当前告警？',
    content: '进入当前告警页面，定位告警后点击确认。',
    display_order: 1,
    updated_at: new Date().toISOString(),
  },
  {
    id: 2,
    title: '如何切换 BT / SY 文件？',
    content: '在帮助页面的文件管理区域选择 BT 文件或 SY 文件页签。',
    display_order: 2,
    updated_at: new Date().toISOString(),
  },
];

const uploadedFiles = (system: SystemType) => [
  {
    id: 1,
    name: `${system.toUpperCase()} 操作手册.pdf`,
    upload_time: new Date().toISOString(),
  },
];

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
  const wsServer = new WebSocketServer({
    noServer: true,
    handleProtocols: (protocols) => protocols.has('bt-nms') ? 'bt-nms' : false,
  });
  const socketKinds = new WeakMap<WebSocket, { kind: 'topology' | 'device-monitor' | 'alarm'; deviceId?: number }>();
  let monitoredDeviceIds = new Set(store.getSnapshot().devices[system].map((device) => device.device_id));
  let alarmRevision = 0;
  const alarmSnapshot = () => {
    const records = store.getSnapshot().records[system].alerts;
    const current = records.filter((alert) => alert.timestamp_end == null && monitoredDeviceIds.has(alert.device_id));
    const currentUnconfirmed = current.filter((alert) => !alert.is_confirmed);
    const historicalUnconfirmed = records.filter(
      (alert) => alert.timestamp_end != null && !alert.is_confirmed && monitoredDeviceIds.has(alert.device_id),
    );
    const audible = [...currentUnconfirmed, ...historicalUnconfirmed].map((alert) => alert.id);
    return {
      type: 'alarm.snapshot',
      system,
      revision: alarmRevision,
      current_count: current.length,
      current_unconfirmed_count: currentUnconfirmed.length,
      historical_unconfirmed_count: historicalUnconfirmed.length,
      total_unconfirmed_count: audible.length,
      should_play: audible.length > 0,
      audible_occurrence_ids: audible,
    };
  };
  const broadcastAlarmSnapshot = () => {
    alarmRevision += 1;
    const payload = JSON.stringify(alarmSnapshot());
    for (const client of wsServer.clients) {
      if (client.readyState === client.OPEN && socketKinds.get(client)?.kind === 'alarm') {
        client.send(payload);
      }
    }
  };

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

      if (path === '/api/monitoring-preference') {
        if (request.method === 'GET') {
          sendJson(response, 200, {
            selection_mode: monitoredDeviceIds.size === devices.length ? 'all' : 'custom',
            device_ids: Array.from(monitoredDeviceIds).sort((a, b) => a - b),
          });
          return;
        }
        if (request.method === 'PUT') {
          const body = await readJsonBody(request);
          const allowedIds = new Set(devices.map((device) => device.device_id));
          const requestedIds: number[] = Array.isArray(body.device_ids)
            ? body.device_ids.map((value: unknown) => Number(value))
            : [];
          if (requestedIds.some((deviceId) => !allowedIds.has(deviceId))) {
            sendJson(response, 400, { detail: 'devices outside user scope' });
            return;
          }
          monitoredDeviceIds = body.selection_mode === 'all' ? allowedIds : new Set(requestedIds);
          broadcastAlarmSnapshot();
          sendJson(response, 200, {
            selection_mode: body.selection_mode,
            device_ids: Array.from(monitoredDeviceIds).sort((a, b) => a - b),
          });
          return;
        }
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

      if (path === '/api/ops/depots') {
        if (request.method === 'GET') {
          sendJson(response, 200, paginated(OPS_DEPOTS, url.searchParams));
          return;
        }
        if (request.method === 'POST') {
          sendJson(response, 201, { id: 2, ...(await readJsonBody(request)) });
          return;
        }
      }

      if (path === '/api/ops/lines') {
        if (request.method === 'GET') {
          sendJson(response, 200, paginated(OPS_LINES, url.searchParams));
          return;
        }
        if (request.method === 'POST') {
          sendJson(response, 201, { id: 2, ...(await readJsonBody(request)) });
          return;
        }
      }

      const opsDictionaryMatch = path.match(/^\/api\/ops\/(depots|lines)\/(\d+)$/);
      if (opsDictionaryMatch && ['PUT', 'PATCH'].includes(request.method || '')) {
        const source = opsDictionaryMatch[1] === 'depots' ? OPS_DEPOTS[0] : OPS_LINES[0];
        sendJson(response, 200, {
          ...source,
          id: Number(opsDictionaryMatch[2]),
          ...(await readJsonBody(request)),
        });
        return;
      }

      if (path === '/api/ops/devices/reconnect' && request.method === 'POST') {
        sendJson(response, 200, { status: 'reconnect scheduled' });
        return;
      }

      if (path === '/api/ops/devices/bulk-delete' && request.method === 'POST') {
        sendJson(response, 200, { deleted: 0 });
        return;
      }

      if (path === '/api/ops/devices/import/preview' && request.method === 'POST') {
        sendJson(response, 200, {
          summary: { create: 0, update: 0, error: 0 },
          rows: [],
          errors: [],
        });
        return;
      }

      if (path === '/api/ops/devices/import/commit' && request.method === 'POST') {
        sendJson(response, 200, { created: 0, updated: 0, errors: [] });
        return;
      }

      if (path === '/api/ops/devices/export') {
        sendText(response, 200, 'device_id,name,ip_address\n', 'text/csv; charset=utf-8');
        return;
      }

      if (path === '/api/ops/devices') {
        if (request.method === 'GET') {
          const filtered = filterOpsDevices(devices, url.searchParams);
          sendJson(response, 200, paginated(filtered, url.searchParams));
          return;
        }
        if (request.method === 'POST') {
          const body = await readJsonBody(request);
          sendJson(response, 201, {
            ...opsDevice(devices[0]),
            ...body,
            id: Number(body.device_id ?? devices[0].device_id),
          });
          return;
        }
      }

      const opsDeviceMatch = path.match(/^\/api\/ops\/devices\/([^/]+)$/);
      if (opsDeviceMatch) {
        if (request.method === 'DELETE') {
          sendJson(response, 200, { deleted: true });
          return;
        }
        if (['PUT', 'PATCH'].includes(request.method || '')) {
          const body = await readJsonBody(request);
          const existing = devices.find((device) => String(device.device_id) === opsDeviceMatch[1]) ?? devices[0];
          sendJson(response, 200, {
            ...opsDevice(existing),
            ...body,
            id: Number(opsDeviceMatch[1]),
          });
          return;
        }
      }

      if (path === '/api/runtime-config/cleanup-export-test' && request.method === 'POST') {
        sendJson(response, 200, cleanupExportTestPayload());
        return;
      }

      if (path === '/api/runtime-config') {
        if (request.method === 'GET') {
          sendJson(response, 200, runtimeConfigPayload(system));
          return;
        }
        if (request.method === 'PUT') {
          const body = await readJsonBody(request);
          sendJson(response, 200, runtimeConfigPayload(system, body.values));
          return;
        }
      }

      if (path === '/api/help-faq') {
        if (request.method === 'GET') {
          sendJson(response, 200, helpFaqItems());
          return;
        }
        if (request.method === 'PUT') {
          const body = await readJsonBody(request);
          sendJson(
            response,
            200,
            Array.isArray(body)
              ? body.map((item, index) => ({
                  id: item.id ?? index + 1,
                  title: item.title,
                  content: item.content,
                  display_order: index + 1,
                  updated_at: new Date().toISOString(),
                }))
              : helpFaqItems(),
          );
          return;
        }
      }

      if (path === '/api/uploaded-files') {
        if (request.method === 'GET') {
          sendJson(response, 200, {
            count: uploadedFiles(system).length,
            results: uploadedFiles(system),
          });
          return;
        }
        if (request.method === 'POST') {
          sendJson(response, 201, uploadedFiles(system)[0]);
          return;
        }
      }

      const uploadedFileMatch = path.match(/^\/api\/uploaded-files\/(\d+)$/);
      if (uploadedFileMatch && request.method === 'DELETE') {
        sendJson(response, 200, { deleted: true });
        return;
      }

      const downloadMatch = path.match(/^\/api\/download\/(\d+)$/);
      if (downloadMatch) {
        sendText(response, 200, `${system.toUpperCase()} demo file ${downloadMatch[1]}`, 'application/octet-stream');
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
          records.alerts.filter((alert) => alert.timestamp_end == null && monitoredDeviceIds.has(alert.device_id)),
        );
        return;
      }

      if (path === '/api/alarm-confirmations' && request.method === 'POST') {
        const body = await readJsonBody(request);
        const occurrenceIds = Array.isArray(body.alarms)
          ? body.alarms.map((item: { occurrence_id?: unknown }) => String(item.occurrence_id || '')).filter(Boolean)
          : [];
        sendJson(response, 200, store.confirmAlarmOccurrences(system, occurrenceIds));
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
        if (listEndpoint === 'alerts') {
          const alertRows = records.alerts.filter((row) =>
            row.timestamp_end != null &&
            monitoredDeviceIds.has(row.device_id) &&
            (url.searchParams.get('is_confirmed') !== 'false' || !row.is_confirmed),
          );
          sendJson(response, 200, {
            count: alertRows.length,
            results: paginate(alertRows, url.searchParams),
          });
          return;
        }
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
      path === '/ws/alarms'
        ? { kind: 'alarm' }
        : monitorMatch
        ? { kind: 'device-monitor', deviceId: Number(monitorMatch[1]) }
        : { kind: 'topology' },
    );
    if (path === '/ws/alarms') {
      socket.send(JSON.stringify(alarmSnapshot()));
    }
  });

  server.on('upgrade', (request, socket, head) => {
    const url = new URL(request.url || '/', `http://${request.headers.host || '127.0.0.1'}`);
    const path = normalizePath(url.pathname);
    if (path !== '/ws/topology' && path !== '/ws/alarms' && !path.match(/^\/ws\/device-monitor\/\d+$/)) {
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
    broadcastAlarmSnapshot();
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
