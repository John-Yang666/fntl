import WebSocket from 'ws';
import { afterEach, describe, expect, it } from 'vitest';
import { createBackendServer } from './backendServer.js';
import { createSimulatorStore } from './store.js';

const startedServers: Array<{ stop: () => Promise<void> }> = [];

afterEach(async () => {
  await Promise.all(startedServers.splice(0).map((server) => server.stop()));
});

const waitForOpen = (socket: WebSocket) =>
  new Promise<void>((resolve, reject) => {
    socket.once('open', () => resolve());
    socket.once('error', reject);
  });

const waitForMessage = (socket: WebSocket) =>
  new Promise<any>((resolve, reject) => {
    socket.once('message', (data) => resolve(JSON.parse(String(data))));
    socket.once('error', reject);
  });

describe('backend WebSocket API', () => {
  it('broadcasts topology updates after simulator state changes', async () => {
    const store = createSimulatorStore();
    const server = createBackendServer({ system: 'bt', store });
    const started = await server.start(0);
    startedServers.push(server);

    const socket = new WebSocket(`ws://127.0.0.1:${started.port}/ws/topology/`, [
      'bt-nms',
      'jwt.sim-access.bt.demo',
    ]);
    await waitForOpen(socket);

    const nextMessage = waitForMessage(socket);
    store.updateDeviceState({ system: 'bt', deviceId: 2, fault: 'direction1_fault' });

    await expect(nextMessage).resolves.toMatchObject({
      device_id: 2,
      device_status: 'good',
      direction1_line_status: 'bad',
      direction2_line_status: 'good',
    });

    socket.close();
  });
});
