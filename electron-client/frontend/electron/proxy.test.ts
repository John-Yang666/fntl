import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { resolveProxyTargetUrl, startDesktopServer, type DesktopServer } from './proxy';

const config = {
  btBaseUrl: 'http://bt.example.local:8000',
  syBaseUrl: 'https://sy.example.local:8444',
};

describe('desktop local proxy URL mapping', () => {
  it('maps BT API requests to the configured backend /api path', () => {
    expect(resolveProxyTargetUrl(config, '/__client/proxy/bt/api/token/?next=/main')).toBe(
      'http://bt.example.local:8000/api/token/?next=/main',
    );
  });

  it('maps SY websocket requests to wss when the configured backend is https', () => {
    expect(resolveProxyTargetUrl(config, '/__client/proxy/sy/ws/topology/?token=abc', 'websocket')).toBe(
      'wss://sy.example.local:8444/ws/topology/?token=abc',
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
      getConfig: async () => ({
        btBaseUrl: `http://127.0.0.1:${upstreamAddress.port}`,
        syBaseUrl: 'http://127.0.0.1:8001',
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
      contentLength: String(Buffer.byteLength(body)),
      body,
    });
  });
});
