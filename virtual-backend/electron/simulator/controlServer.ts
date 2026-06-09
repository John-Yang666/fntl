import { createReadStream } from 'node:fs';
import { access, stat } from 'node:fs/promises';
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';
import { extname, join, normalize } from 'node:path';
import { createSimulatorStore } from './store.js';

type SimulatorStore = ReturnType<typeof createSimulatorStore>;

type ServiceStatus = {
  bt: { port: number; running: boolean; error?: string };
  sy: { port: number; running: boolean; error?: string };
};

interface ControlServerOptions {
  store: SimulatorStore;
  getServiceStatus: () => ServiceStatus;
  staticRoot?: string;
}

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

const jsonHeaders = {
  'access-control-allow-origin': '*',
  'access-control-allow-methods': 'GET,POST,OPTIONS',
  'access-control-allow-headers': 'content-type',
  'content-type': 'application/json; charset=utf-8',
};

const sendJson = (response: ServerResponse, status: number, body: unknown) => {
  response.writeHead(status, jsonHeaders);
  response.end(JSON.stringify(body));
};

const contentTypes: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
};

const statePayload = (store: SimulatorStore, getServiceStatus: () => ServiceStatus) => ({
  services: getServiceStatus(),
  ...store.getSnapshot(),
});

const sendStaticFile = async (response: ServerResponse, staticRoot: string, pathname: string) => {
  const requestedPath = pathname === '/' ? '/index.html' : pathname;
  const filePath = normalize(join(staticRoot, requestedPath));
  if (!filePath.startsWith(normalize(staticRoot))) {
    sendJson(response, 403, { detail: 'Forbidden' });
    return;
  }
  try {
    await access(filePath);
    const stats = await stat(filePath);
    if (!stats.isFile()) {
      throw new Error('Not a file');
    }
    response.writeHead(200, {
      'content-type': contentTypes[extname(filePath)] || 'application/octet-stream',
    });
    createReadStream(filePath).pipe(response);
  } catch {
    const fallback = join(staticRoot, 'index.html');
    response.writeHead(200, {
      'content-type': 'text/html; charset=utf-8',
    });
    createReadStream(fallback).pipe(response);
  }
};

export const createControlServer = ({ store, getServiceStatus, staticRoot }: ControlServerOptions) => {
  const server = createServer(async (request, response) => {
    response.setHeader('access-control-allow-origin', '*');
    response.setHeader('access-control-allow-methods', 'GET,POST,OPTIONS');
    response.setHeader('access-control-allow-headers', 'content-type');
    if (request.method === 'OPTIONS') {
      response.writeHead(204);
      response.end();
      return;
    }

    try {
      const url = new URL(request.url || '/', `http://${request.headers.host || '127.0.0.1'}`);
      const path = normalizePath(url.pathname);

      if (path === '/__sim/state') {
        sendJson(response, 200, statePayload(store, getServiceStatus));
        return;
      }

      if (path === '/__sim/device-state' && request.method === 'POST') {
        store.updateDeviceState(await readJsonBody(request));
        sendJson(response, 200, statePayload(store, getServiceStatus));
        return;
      }

      if (path === '/__sim/reset' && request.method === 'POST') {
        store.reset();
        sendJson(response, 200, statePayload(store, getServiceStatus));
        return;
      }

      if (path === '/__sim/broadcast' && request.method === 'POST') {
        store.broadcastAll();
        sendJson(response, 200, { status: 'broadcasted' });
        return;
      }

      if (staticRoot) {
        await sendStaticFile(response, staticRoot, url.pathname);
        return;
      }

      sendJson(response, 404, { detail: 'Not found' });
    } catch (error) {
      sendJson(response, 500, {
        detail: error instanceof Error ? error.message : 'Internal simulator error',
      });
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
  };
};
