import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import {
  DEFAULT_DESKTOP_SERVER_PORT,
  resolveDesktopServerPort,
  resolveProxyTargetUrl,
  startDesktopServer,
  type DesktopServer,
} from './proxy';

const config = {
  btBaseUrl: 'http://frontend.example.local:38173',
  syBaseUrl: 'https://frontend.example.local:38443',
};

describe('desktop local proxy URL mapping', () => {
  it('uses a stable local port and validates explicit diagnostic overrides', () => {
    expect(resolveDesktopServerPort([])).toBe(DEFAULT_DESKTOP_SERVER_PORT);
    expect(resolveDesktopServerPort(['--desktop-server-port=52368'])).toBe(52_368);
    expect(() => resolveDesktopServerPort(['--desktop-server-port=70000'])).toThrow('无效的客户端本地端口');
  });

  it('maps BT API requests to the configured frontend /bt-api path', () => {
    expect(resolveProxyTargetUrl(config, '/__client/proxy/bt/api/token/?next=/main')).toBe(
      'http://frontend.example.local:38173/bt-api/token/?next=/main',
    );
  });

  it('maps SY websocket requests to /sy-ws and wss when the configured frontend is https', () => {
    expect(resolveProxyTargetUrl(config, '/__client/proxy/sy/ws/topology/?token=abc', 'websocket')).toBe(
      'wss://frontend.example.local:38443/sy-ws/topology/?token=abc',
    );
  });

  it('rejects unknown proxy routes', () => {
    expect(() => resolveProxyTargetUrl(config, '/api/token/')).toThrow('Unsupported desktop proxy path');
  });
});

describe('desktop local proxy HTTP forwarding', () => {
  const servers: Array<{ close: () => Promise<void> }> = [];

  afterEach(async () => {
    await Promise.all(servers.splice(0).map((server) => server.close()));
  });

  it('forwards POST JSON bodies with their content length intact', async () => {
    const upstream = http.createServer((req, res) => {
      const chunks: Buffer[] = [];
      req.on('data', (chunk: Buffer) => chunks.push(chunk));
      req.on('end', () => {
        res.writeHead(200, { 'content-type': 'application/json' });
        res.end(JSON.stringify({
          url: req.url,
          contentLength: req.headers['content-length'],
          body: Buffer.concat(chunks).toString('utf8'),
        }));
      });
    });
    await new Promise<void>((resolve) => upstream.listen(0, '127.0.0.1', resolve));
    servers.push({
      close: () => new Promise<void>((resolve, reject) => {
        upstream.close((error) => (error ? reject(error) : resolve()));
      }),
    });
    const upstreamAddress = upstream.address();
    if (!upstreamAddress || typeof upstreamAddress === 'string') {
      throw new Error('Unable to start upstream test server');
    }

    const distDir = await fs.mkdtemp(path.join(os.tmpdir(), 'bt-nms-desktop-proxy-'));
    await fs.writeFile(path.join(distDir, 'index.html'), '<!doctype html>');
    servers.push({ close: () => fs.rm(distDir, { recursive: true, force: true }) });

    const desktopServer: DesktopServer = await startDesktopServer({
      distDir,
      port: 0,
      getConfig: async () => ({
        btBaseUrl: `http://127.0.0.1:${upstreamAddress.port}`,
        syBaseUrl: 'http://127.0.0.1:38173',
      }),
    });
    servers.push(desktopServer);

    const body = JSON.stringify({ username: '__probe__', password: '__probe__' });
    const response = await fetch(`${desktopServer.origin}/__client/proxy/bt/api/token/`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body,
    });

    await expect(response.json()).resolves.toEqual({
      url: '/bt-api/token/',
      contentLength: String(Buffer.byteLength(body)),
      body,
    });
  });
});
