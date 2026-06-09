import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import type {
  AlertRecord,
  DemoDevice,
  DeviceStateUpdate,
  FaultState,
  SimulatorState,
  SwitchDataRecord,
  SystemRecords,
  SystemType,
  UserOperationRecord,
} from './types.js';

const SYSTEM_LABELS: Record<SystemType, string> = {
  bt: 'BT',
  sy: 'SY',
};

const FAULT_ALARMS: Record<Exclude<FaultState, 'normal'>, { code: number; meaning: string }> = {
  offline: { code: 9001, meaning: '通信中断' },
  direction1_fault: { code: 2001, meaning: '一方向线路故障' },
  direction2_fault: { code: 2002, meaning: '二方向线路故障' },
  alarm: { code: 1001, meaning: '设备当前告警' },
};

type BtCommandPayload = {
  function_code?: number | string;
  operation?: number | string;
  username?: string | null;
  is_custom_command?: boolean;
};

type SyCommandPayload = {
  cmd_type?: string;
  bb_name?: string;
  bb_code?: string;
  username?: string | null;
};

type StoreOptions = {
  initialState?: SimulatorState;
  persistencePath?: string;
};

export type StoreEvent = {
  type: 'device-state-changed';
  system: SystemType;
  deviceId: number;
};

const nowIso = () => new Date().toISOString();

const createRecords = (): SystemRecords => ({
  alerts: [],
  relayActions: [],
  userOperations: [],
  switchData: [],
  analogData: [],
});

const createLineDevices = (system: SystemType): DemoDevice[] => {
  const baseId = system === 'bt' ? 1 : 101;
  return [0, 1, 2].map((index) => {
    const id = baseId + index;
    const direction1Id = index === 0 ? null : id - 1;
    const direction2Id = index === 2 ? null : id + 1;
    return {
      system,
      device_id: id,
      name: `${SYSTEM_LABELS[system]}-${String(index + 1).padStart(2, '0')}`,
      depot: '演示车站',
      line: '演示线路',
      ip_address: `192.168.${system === 'bt' ? 10 : 20}.${index + 11}`,
      x_coordinate: 120 + index * 220,
      y_coordinate: system === 'bt' ? 160 : 300,
      direction1_neighbor_id: direction1Id,
      direction1_neighbor_direction: direction1Id == null ? null : 2,
      direction2_neighbor_id: direction2Id,
      direction2_neighbor_direction: direction2Id == null ? null : 1,
      direction3_neighbor_id: system === 'sy' ? null : undefined,
      direction3_neighbor_direction: system === 'sy' ? null : undefined,
      remark: '虚拟后端演示设备',
      fault: 'normal',
      analogFault: system === 'bt' ? false : undefined,
      syRunState: system === 'sy' ? 'normal' : undefined,
    };
  });
};

const createDefaultState = (): SimulatorState => ({
  devices: {
    bt: createLineDevices('bt'),
    sy: createLineDevices('sy'),
  },
  records: {
    bt: createRecords(),
    sy: createRecords(),
  },
});

const cloneState = (state: SimulatorState): SimulatorState => structuredClone(state);

const findDevice = (state: SimulatorState, system: SystemType, deviceId: number) => {
  const device = state.devices[system].find((item) => item.device_id === deviceId);
  if (!device) {
    throw new Error(`Unknown ${system.toUpperCase()} device ${deviceId}`);
  }
  return device;
};

const durationSeconds = (startIso: string, endIso = nowIso()) =>
  Math.max(0, Math.floor((Date.parse(endIso) - Date.parse(startIso)) / 1000));

class SimulatorStore {
  private state: SimulatorState;
  private nextId = 1;
  private listeners = new Set<(event: StoreEvent) => void>();
  private persistencePath: string | null;

  constructor(options: StoreOptions = {}) {
    this.persistencePath = options.persistencePath ?? null;
    const loadedState = this.loadPersistedState();
    this.state = loadedState ?? options.initialState ?? createDefaultState();
    if (!loadedState) {
      this.seedTelemetry();
      this.save();
    }
  }

  getSnapshot(): SimulatorState {
    return cloneState(this.state);
  }

  subscribe(listener: (event: StoreEvent) => void) {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  reset(): SimulatorState {
    this.state = createDefaultState();
    this.nextId = 1;
    this.seedTelemetry();
    this.save();
    return this.getSnapshot();
  }

  broadcastAll() {
    for (const system of ['bt', 'sy'] as const) {
      for (const device of this.state.devices[system]) {
        this.emit({ type: 'device-state-changed', system, deviceId: device.device_id });
      }
    }
  }

  updateDeviceState(update: DeviceStateUpdate): SimulatorState {
    const device = findDevice(this.state, update.system, update.deviceId);
    if (update.fault) {
      device.fault = update.fault;
      this.syncAlertForDevice(update.system, device);
    }
    if (typeof update.analogFault === 'boolean' && device.system === 'bt') {
      device.analogFault = update.analogFault;
      this.appendAnalogData(device);
    }
    if (update.syRunState && device.system === 'sy') {
      device.syRunState = update.syRunState;
    }
    this.appendSwitchData(device);
    this.save();
    this.emit({ type: 'device-state-changed', system: update.system, deviceId: update.deviceId });
    return this.getSnapshot();
  }

  handleBtCommand(deviceId: number, payload: BtCommandPayload) {
    const device = findDevice(this.state, 'bt', deviceId);
    const functionCode = Number(payload.function_code ?? 0);
    const operation = Number(payload.operation ?? 0);
    const operationLabel = this.describeBtOperation(functionCode, operation, Boolean(payload.is_custom_command));

    if (!payload.is_custom_command) {
      if ((functionCode === 1 || functionCode === 2) && operation === 2) {
        this.updateDeviceState({ system: 'bt', deviceId, fault: 'normal' });
      } else if (functionCode === 1 && (operation === 1 || operation === 3)) {
        this.updateDeviceState({ system: 'bt', deviceId, fault: 'direction1_fault' });
      } else if (functionCode === 2 && (operation === 1 || operation === 3)) {
        this.updateDeviceState({ system: 'bt', deviceId, fault: 'direction2_fault' });
      }
    }

    this.appendUserOperation('bt', device, String(payload.function_code ?? ''), operationLabel, payload.username ?? null);
    this.save();
    return { status: `BT ${device.name} ${operationLabel}` };
  }

  handleSyCommand(deviceId: number, payload: SyCommandPayload) {
    const device = findDevice(this.state, 'sy', deviceId);
    const commandName = payload.bb_name || payload.bb_code || 'UNKNOWN';

    if (payload.bb_name === 'UP_AUTO' || payload.bb_name === 'DOWN_AUTO') {
      this.updateDeviceState({ system: 'sy', deviceId, fault: 'normal' });
    } else if (payload.bb_name === 'UP_FORCE_CABLE') {
      this.updateDeviceState({ system: 'sy', deviceId, fault: 'direction1_fault' });
    } else if (payload.bb_name === 'DOWN_FORCE_CABLE') {
      this.updateDeviceState({ system: 'sy', deviceId, fault: 'direction2_fault' });
    } else if (payload.bb_name === 'REMOTE_START_LOCAL') {
      this.updateDeviceState({ system: 'sy', deviceId, syRunState: 'started' });
    } else if (payload.bb_name === 'FORCE_A_DROP') {
      this.updateDeviceState({ system: 'sy', deviceId, syRunState: 'main_disabled' });
    } else if (payload.bb_name === 'FORCE_B_DROP') {
      this.updateDeviceState({ system: 'sy', deviceId, syRunState: 'backup_disabled' });
    }

    this.appendUserOperation('sy', device, commandName, this.describeSyOperation(commandName), payload.username ?? null);
    this.save();
    return { status: `SY ${device.name} 命令已发送` };
  }

  confirmAlarm(system: SystemType, deviceId: number, alarmCode: number) {
    const alert = this.state.records[system].alerts.find(
      (item) =>
        item.device_id === deviceId &&
        item.alarm_code === alarmCode &&
        item.timestamp_end == null,
    );
    if (!alert) {
      throw new Error(`Active alarm ${deviceId}/${alarmCode} not found`);
    }
    alert.is_confirmed = true;
    alert.confirmed = true;
    this.save();
    return { status: '告警已确认' };
  }

  private syncAlertForDevice(system: SystemType, device: DemoDevice) {
    const records = this.state.records[system].alerts;
    if (device.fault === 'normal') {
      for (const alert of records) {
        if (alert.device_id === device.device_id && alert.timestamp_end == null) {
          alert.timestamp_end = nowIso();
          alert.duration_seconds = durationSeconds(alert.timestamp, alert.timestamp_end);
        }
      }
      return;
    }

    const alarm = FAULT_ALARMS[device.fault];
    const existing = records.find(
      (alert) =>
        alert.device_id === device.device_id &&
        alert.alarm_code === alarm.code &&
        alert.timestamp_end == null,
    );
    if (existing) {
      return;
    }

    records.unshift({
      id: this.createId('alert'),
      device_id: device.device_id,
      device_name: device.name,
      alarm_code: alarm.code,
      alarm_meaning: alarm.meaning,
      timestamp: nowIso(),
      timestamp_end: null,
      is_confirmed: false,
      confirmed: false,
      duration_seconds: 0,
    });
  }

  private appendUserOperation(
    system: SystemType,
    device: DemoDevice,
    functionCode: string,
    operation: string,
    username: string | null,
  ) {
    const record: UserOperationRecord = {
      id: this.createId('op'),
      device: device.device_id,
      device_id: device.device_id,
      device_name: device.name,
      function_code: functionCode,
      operation,
      username,
      timestamp: nowIso(),
    };
    this.state.records[system].userOperations.unshift(record);
  }

  private appendSwitchData(device: DemoDevice) {
    const statusText = this.describeDeviceStatus(device);
    const record: SwitchDataRecord = {
      id: this.createId('switch'),
      device: device.device_id,
      device_id: device.device_id,
      device_name: device.name,
      switch_status_text: statusText,
      switch_status_hex: this.buildSwitchHex(device),
      version: device.system === 'sy' ? 'A1-virtual' : undefined,
      timestamp: nowIso(),
    };
    this.state.records[device.system].switchData.unshift(record);
  }

  private appendAnalogData(device: DemoDevice) {
    if (device.system !== 'bt') {
      return;
    }
    const abnormal = Boolean(device.analogFault);
    this.state.records.bt.analogData.unshift({
      id: this.createId('analog'),
      device: device.device_id,
      device_id: device.device_id,
      device_name: device.name,
      voltage_1: abnormal ? 7.6 : 12.1,
      current_1: abnormal ? 0.1 : 1.2,
      voltage_2: abnormal ? 15.8 : 12.0,
      current_2: abnormal ? 2.7 : 1.1,
      timestamp: nowIso(),
    });
  }

  private seedTelemetry() {
    for (const system of ['bt', 'sy'] as const) {
      for (const device of this.state.devices[system]) {
        this.appendSwitchData(device);
        this.appendAnalogData(device);
      }
    }
  }

  private describeBtOperation(functionCode: number, operation: number, custom: boolean) {
    if (custom) {
      return '自定义命令';
    }
    if (functionCode === 5) {
      return '重启网管板';
    }
    const direction = functionCode === 1 ? '一方向' : functionCode === 2 ? '二方向' : `功能码${functionCode}`;
    const mode = operation === 1 ? '强制电缆' : operation === 2 ? '自动' : operation === 3 ? '强制光缆' : `操作${operation}`;
    return `${direction}${mode}`;
  }

  private describeSyOperation(commandName: string) {
    const labels: Record<string, string> = {
      UP_FORCE_CABLE: '上行强制电缆',
      UP_AUTO: '上行自动',
      DOWN_FORCE_CABLE: '下行强制电缆',
      DOWN_AUTO: '下行自动',
      REMOTE_START_LOCAL: '启动当前设备',
      FORCE_A_DROP: '停用主机',
      FORCE_B_DROP: '停用备机',
    };
    return labels[commandName] ?? `自定义命令 ${commandName}`;
  }

  private describeDeviceStatus(device: DemoDevice) {
    const labels: Record<FaultState, string> = {
      normal: '正常',
      offline: '通信中断',
      direction1_fault: '一方向故障',
      direction2_fault: '二方向故障',
      alarm: '当前告警',
    };
    return labels[device.fault];
  }

  private buildSwitchHex(device: DemoDevice) {
    const faultNibble: Record<FaultState, string> = {
      normal: '0',
      offline: '9',
      direction1_fault: '1',
      direction2_fault: '2',
      alarm: 'A',
    };
    return `7F7F${String(device.device_id).padStart(2, '0')}${faultNibble[device.fault]}0F7`;
  }

  private createId(prefix: string) {
    return `${prefix}-${this.nextId++}`;
  }

  private emit(event: StoreEvent) {
    for (const listener of this.listeners) {
      listener(event);
    }
  }

  private loadPersistedState() {
    if (!this.persistencePath || !existsSync(this.persistencePath)) {
      return null;
    }
    const parsed = JSON.parse(readFileSync(this.persistencePath, 'utf8')) as SimulatorState;
    this.nextId = this.computeNextId(parsed);
    return parsed;
  }

  private save() {
    if (!this.persistencePath) {
      return;
    }
    mkdirSync(dirname(this.persistencePath), { recursive: true });
    writeFileSync(this.persistencePath, `${JSON.stringify(this.state, null, 2)}\n`, 'utf8');
  }

  private computeNextId(state: SimulatorState) {
    const allIds = Object.values(state.records).flatMap((records) => [
      ...records.alerts.map((record) => record.id),
      ...records.relayActions.map((record) => record.id),
      ...records.userOperations.map((record) => record.id),
      ...records.switchData.map((record) => record.id),
      ...records.analogData.map((record) => record.id),
    ]);
    const max = allIds.reduce((highest, id) => {
      const numeric = Number(String(id).split('-').pop());
      return Number.isFinite(numeric) ? Math.max(highest, numeric) : highest;
    }, 0);
    return max + 1;
  }
}

export const createSimulatorStore = (options?: SimulatorState | StoreOptions) => {
  if (options && 'devices' in options) {
    return new SimulatorStore({ initialState: options });
  }
  return new SimulatorStore(options);
};
