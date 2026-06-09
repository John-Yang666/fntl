import { mkdtemp, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { afterEach, describe, expect, it } from 'vitest';
import { createSimulatorStore } from './store.js';

const tempDirs: string[] = [];

afterEach(async () => {
  await Promise.all(tempDirs.splice(0).map((dir) => rm(dir, { recursive: true, force: true })));
});

describe('simulator state persistence', () => {
  it('loads state previously saved to a JSON file', async () => {
    const dir = await mkdtemp(join(tmpdir(), 'bt-nms-sim-'));
    tempDirs.push(dir);
    const stateFile = join(dir, 'state.json');

    const firstStore = createSimulatorStore({ persistencePath: stateFile });
    firstStore.updateDeviceState({ system: 'bt', deviceId: 1, fault: 'offline', analogFault: true });

    const secondStore = createSimulatorStore({ persistencePath: stateFile });
    const snapshot = secondStore.getSnapshot();

    expect(snapshot.devices.bt[0]).toMatchObject({
      fault: 'offline',
      analogFault: true,
    });
    expect(snapshot.records.bt.alerts[0]).toMatchObject({
      device_id: 1,
      alarm_code: 9001,
    });
  });
});
