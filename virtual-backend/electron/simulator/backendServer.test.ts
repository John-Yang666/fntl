import { afterEach, describe, expect, it } from 'vitest';
import { createBackendServer } from './backendServer.js';
import { createSimulatorStore } from './store.js';

const startedServers: Array<{ stop: () => Promise<void> }> = [];

const startDemoServer = async (system: 'bt' | 'sy') => {
  const store = createSimulatorStore();
  const server = createBackendServer({ system, store });
  const started = await server.start(0);
  startedServers.push(server);
  return { store, baseUrl: `http://127.0.0.1:${started.port}` };
};

const requestJson = async (url: string, init?: RequestInit) => {
  const response = await fetch(url, {
    ...init,
    headers: {
      'content-type': 'application/json',
      ...(init?.headers || {}),
    },
  });
  const body = await response.json();
  return { response, body };
};

afterEach(async () => {
  await Promise.all(startedServers.splice(0).map((server) => server.stop()));
});

describe('backend HTTP API', () => {
  it('authenticates the fixed demo account and serves the demo user', async () => {
    const { baseUrl } = await startDemoServer('bt');

    const token = await requestJson(`${baseUrl}/api/token/`, {
      method: 'POST',
      body: JSON.stringify({ username: 'admin', password: 'admin' }),
    });
    expect(token.response.status).toBe(200);
    expect(token.body.access).toMatch(/^sim-access\./);

    const user = await requestJson(`${baseUrl}/api/user/`, {
      headers: { authorization: `Bearer ${token.body.access}` },
    });
    expect(user.body).toMatchObject({
      username: 'admin',
      is_superuser: true,
      groups: ['演示用户'],
    });
  });

  it('serves device lists and topology status in frontend-compatible shapes', async () => {
    const { store, baseUrl } = await startDemoServer('bt');
    store.updateDeviceState({ system: 'bt', deviceId: 2, fault: 'direction2_fault' });

    const devices = await requestJson(`${baseUrl}/api/devices-list/`);
    expect(devices.body['演示线路']).toHaveLength(3);
    expect(devices.body['演示线路'][1]).toMatchObject({
      device_id: 2,
      direction1_neighbor_id: 1,
      direction2_neighbor_id: 3,
    });

    const topology = await requestJson(`${baseUrl}/api/all-topology-status/`);
    expect(topology.body.topology_statuses['2']).toMatchObject({
      device_id: 2,
      device_status: 'good',
      direction1_line_status: 'good',
      direction2_line_status: 'bad',
    });
  });

  it('accepts remote commands and exposes generated records with count endpoints', async () => {
    const { baseUrl } = await startDemoServer('sy');

    const command = await requestJson(`${baseUrl}/api/sy/send-command/101/`, {
      method: 'POST',
      body: JSON.stringify({
        username: 'admin',
        cmd_type: 'BB',
        bb_name: 'UP_FORCE_CABLE',
      }),
    });
    expect(command.body.status).toContain('命令已发送');

    const active = await requestJson(`${baseUrl}/api/active-alarms/`);
    expect(active.body).toHaveLength(1);
    expect(active.body[0]).toMatchObject({ device_id: 101, alarm_code: 2001 });

    const records = await requestJson(`${baseUrl}/api/user-operations/?page=1&page_size=10`);
    expect(records.body.results[0]).toMatchObject({
      device_id: 101,
      username: 'admin',
      function_code: 'UP_FORCE_CABLE',
    });

    const count = await requestJson(`${baseUrl}/api/user-operations/count/`);
    expect(count.body).toEqual({ count: 1, approximate: false });
  });

  it('persists monitoring selection and confirms current alarms by occurrence id', async () => {
    const { store, baseUrl } = await startDemoServer('bt');
    const preference = await requestJson(`${baseUrl}/api/monitoring-preference/`, {
      method: 'PUT',
      body: JSON.stringify({ selection_mode: 'custom', device_ids: [2] }),
    });
    expect(preference.body).toEqual({ selection_mode: 'custom', device_ids: [2] });

    store.updateDeviceState({ system: 'bt', deviceId: 2, fault: 'direction1_fault' });
    const active = await requestJson(`${baseUrl}/api/active-alarms/`);
    const occurrenceId = active.body[0].id;
    const confirmation = await requestJson(`${baseUrl}/api/alarm-confirmations/`, {
      method: 'POST',
      body: JSON.stringify({ alarms: [{ source: 'current', occurrence_id: occurrenceId }] }),
    });
    expect(confirmation.body).toEqual({ confirmed: 1, skipped: 0 });
    const confirmed = await requestJson(`${baseUrl}/api/active-alarms/`);
    expect(confirmed.body[0].confirmed).toBe(true);
  });

  it('serves ops, runtime, help, and file-management compatibility endpoints', async () => {
    const { baseUrl } = await startDemoServer('bt');

    const opsDevices = await requestJson(`${baseUrl}/api/ops/devices/?device_id=2`);
    expect(opsDevices.response.status).toBe(200);
    expect(opsDevices.body).toMatchObject({
      count: 1,
      results: [
        {
          device_id: 2,
          name: 'BT-02',
          depot_name: '演示车站',
          line_name: '演示线路',
        },
      ],
    });

    const depots = await requestJson(`${baseUrl}/api/ops/depots/`);
    expect(depots.body.results[0]).toMatchObject({ name: '演示车站', is_active: true });

    const runtime = await requestJson(`${baseUrl}/api/runtime-config/`);
    expect(runtime.body.schema.some((field: { key: string }) => field.key === 'CLEANUP_SCHEDULE_TIME')).toBe(true);
    expect(runtime.body.values.CLEANUP_SCHEDULE_TIME).toBe('02:30');

    const cleanupExport = await requestJson(`${baseUrl}/api/runtime-config/cleanup-export-test/`, {
      method: 'POST',
      body: JSON.stringify({}),
    });
    expect(cleanupExport.body.results.alerts).toMatchObject({
      status: 'success',
      model: 'AlarmData',
    });

    const faq = await requestJson(`${baseUrl}/api/help-faq/`);
    expect(faq.body[0]).toMatchObject({ title: '如何确认当前告警？' });

    const files = await requestJson(`${baseUrl}/api/uploaded-files/`);
    expect(files.body.results[0]).toMatchObject({ name: 'BT 操作手册.pdf' });
  });
});
