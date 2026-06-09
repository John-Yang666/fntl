import { describe, expect, it } from 'vitest';
import { createSimulatorStore } from './store.js';

describe('simulator store', () => {
  it('creates three BT and three SY devices on the demo line', () => {
    const store = createSimulatorStore();
    const snapshot = store.getSnapshot();

    expect(snapshot.devices.bt.map((device) => device.name)).toEqual(['BT-01', 'BT-02', 'BT-03']);
    expect(snapshot.devices.sy.map((device) => device.name)).toEqual(['SY-01', 'SY-02', 'SY-03']);
    expect(snapshot.devices.bt.every((device) => device.line === '演示线路')).toBe(true);
    expect(snapshot.devices.sy.every((device) => device.line === '演示线路')).toBe(true);
    expect(snapshot.devices.bt[1].direction1_neighbor_id).toBe(1);
    expect(snapshot.devices.bt[1].direction2_neighbor_id).toBe(3);
  });

  it('switches a device fault and creates an active alarm record', () => {
    const store = createSimulatorStore();

    store.updateDeviceState({ system: 'bt', deviceId: 2, fault: 'direction1_fault' });
    const snapshot = store.getSnapshot();
    const device = snapshot.devices.bt.find((item) => item.device_id === 2);

    expect(device?.fault).toBe('direction1_fault');
    expect(snapshot.records.bt.alerts).toHaveLength(1);
    expect(snapshot.records.bt.alerts[0]).toMatchObject({
      device_id: 2,
      device_name: 'BT-02',
      alarm_code: 2001,
      timestamp_end: null,
      is_confirmed: false,
    });
  });

  it('applies BT and SY remote commands to state and operation records', () => {
    const store = createSimulatorStore();

    store.handleBtCommand(1, {
      function_code: 1,
      operation: 1,
      username: 'admin',
    });
    store.handleSyCommand(101, {
      cmd_type: 'BB',
      bb_name: 'REMOTE_START_LOCAL',
      username: 'admin',
    });

    const snapshot = store.getSnapshot();
    expect(snapshot.devices.bt[0].fault).toBe('direction1_fault');
    expect(snapshot.devices.sy[0].syRunState).toBe('started');
    expect(snapshot.records.bt.userOperations[0]).toMatchObject({
      device_id: 1,
      username: 'admin',
      function_code: '1',
    });
    expect(snapshot.records.sy.userOperations[0]).toMatchObject({
      device_id: 101,
      username: 'admin',
      function_code: 'REMOTE_START_LOCAL',
    });
  });
});
