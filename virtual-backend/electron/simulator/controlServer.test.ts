import { afterEach, describe, expect, it } from 'vitest';
import { createControlServer } from './controlServer.js';
import { createSimulatorStore } from './store.js';

const startedServers: Array<{ stop: () => Promise<void> }> = [];

const startControlServer = async () => {
  const store = createSimulatorStore();
  const server = createControlServer({
    store,
    getServiceStatus: () => ({
      bt: { port: 8000, running: true },
      sy: { port: 8001, running: true },
    }),
  });
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

describe('control HTTP API', () => {
  it('returns simulator state and service status', async () => {
    const { baseUrl } = await startControlServer();

    const state = await requestJson(`${baseUrl}/__sim/state`);

    expect(state.body.services.bt).toEqual({ port: 8000, running: true });
    expect(state.body.devices.bt).toHaveLength(3);
    expect(state.body.devices.sy).toHaveLength(3);
  });

  it('updates and resets simulator state', async () => {
    const { baseUrl } = await startControlServer();

    const update = await requestJson(`${baseUrl}/__sim/device-state`, {
      method: 'POST',
      body: JSON.stringify({ system: 'bt', deviceId: 3, fault: 'offline', analogFault: true }),
    });
    expect(update.body.devices.bt[2]).toMatchObject({ fault: 'offline', analogFault: true });

    const reset = await requestJson(`${baseUrl}/__sim/reset`, { method: 'POST' });
    expect(reset.body.devices.bt[2]).toMatchObject({ fault: 'normal', analogFault: false });
  });

  it('accepts manual broadcast requests', async () => {
    const { baseUrl } = await startControlServer();

    const broadcast = await requestJson(`${baseUrl}/__sim/broadcast`, { method: 'POST' });

    expect(broadcast.body).toEqual({ status: 'broadcasted' });
  });
});
