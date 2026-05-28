import fs from 'node:fs';
import http, { type IncomingMessage, type ServerResponse } from 'node:http';
import https from 'node:https';
import path from 'node:path';
import { pipeline } from 'node:stream';
import { promisify } from 'node:util';
import { WebSocket, WebSocketServer } from 'ws';
import type { ClientConfig } from './config.js';

type SystemType = 'bt' | 'sy';
type ProxyKind = 'http' | 'websocket';

const streamPipeline = promisify(pipeline);
const PROXY_PREFIX = /^\/__client\/proxy\/(bt|sy)\/(api|ws)(\/.*)?$/;

const MIME_TYPES: Record<string, string> = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.ico': 'image/x-icon',
  '.jpeg': 'image/jpeg',
  '.jpg': 'image/jpeg',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.mp3': 'audio/mpeg',
  '.png': 'image/png',
  '.svg': 'image/svg+xml; charset=utf-8',
  '.webp': 'image/webp',
};

export interface DesktopServer {
  origin: string;
  port: number;
  close: () => Promise<void>;
}

export interface StartDesktopServerOptions {
  distDir: string;
  getConfig: () => Promise<ClientConfig | null>;
}

function configKeyForSystem(system: SystemType): keyof ClientConfig {
  return system === 'bt' ? 'btBaseUrl' : 'syBaseUrl';
}

function joinBackendPath(prefix: 'api' | 'ws', suffix: string | undefined): string {
  const normalizedSuffix = suffix && suffix !== '/' ? suffix : '/';
  return `/${prefix}${normalizedSuffix.startsWith('/') ? normalizedSuffix : `/${normalizedSuffix}`}`;
}

export function resolveProxyTargetUrl(
  config: ClientConfig,
  incomingUrl: string,
  kind: ProxyKind = 'http',
): string {
  const localUrl = new URL(incomingUrl, 'http://127.0.0.1');
  const match = localUrl.pathname.match(PROXY_PREFIX);
  if (!match) {
    throw new Error('Unsupported desktop proxy path');
  }

  const system = match[1] as SystemType;
  const prefix = match[2] as 'api' | 'ws';
  if ((kind === 'http' && prefix !== 'api') || (kind === 'websocket' && prefix !== 'ws')) {
    throw new Error('Unsupported desktop proxy path');
  }

  const target = new URL(config[configKeyForSystem(system)]);
  target.pathname = joinBackendPath(prefix, match[3]);
  target.search = localUrl.search;
  target.hash = '';
  if (kind === 'websocket') {
    target.protocol = target.protocol === 'https:' ? 'wss:' : 'ws:';
  }
  return target.toString();
}

function writeJson(res: ServerResponse, statusCode: number, payload: unknown): void {
  const body = JSON.stringify(payload);
  res.writeHead(statusCode, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body),
  });
  res.end(body);
}

function stripHopByHopHeaders(headers: IncomingMessage['headers']): http.OutgoingHttpHeaders {
  const result: http.OutgoingHttpHeaders = { ...headers };
  [
    'connection',
    'host',
    'keep-alive',
    'proxy-authenticate',
    'proxy-authorization',
    'te',
    'trailer',
    'transfer-encoding',
    'upgrade',
  ].forEach((header) => {
    delete result[header];
  });
  return result;
}

async function proxyHttpRequest(
  req: IncomingMessage,
  res: ServerResponse,
  getConfig: () => Promise<ClientConfig | null>,
): Promise<void> {
  const config = await getConfig();
  if (!config) {
    writeJson(res, 503, { detail: '客户端服务地址未配置' });
    return;
  }

  let targetUrl: URL;
  try {
    targetUrl = new URL(resolveProxyTargetUrl(config, req.url || '/', 'http'));
  } catch (error) {
    writeJson(res, 404, { detail: error instanceof Error ? error.message : 'Unsupported desktop proxy path' });
    return;
  }

  const transport = targetUrl.protocol === 'https:' ? https : http;
  const upstream = transport.request(
    targetUrl,
    {
      method: req.method,
      headers: {
        ...stripHopByHopHeaders(req.headers),
        host: targetUrl.host,
      },
      rejectUnauthorized: false,
    },
    (upstreamRes) => {
      res.writeHead(upstreamRes.statusCode || 502, upstreamRes.headers);
      upstreamRes.pipe(res);
    },
  );

  upstream.on('error', (error) => {
    if (!res.headersSent) {
      writeJson(res, 502, { detail: `后端请求失败: ${error.message}` });
    } else {
      res.destroy(error);
    }
  });

  req.pipe(upstream);
}

async function serveStatic(req: IncomingMessage, res: ServerResponse, distDir: string): Promise<void> {
  const requestUrl = new URL(req.url || '/', 'http://127.0.0.1');
  const decodedPathname = decodeURIComponent(requestUrl.pathname);
  const relativePath = decodedPathname === '/' ? 'index.html' : decodedPathname.replace(/^\/+/, '');
  const candidatePath = path.resolve(distDir, relativePath);
  const resolvedDist = path.resolve(distDir);
  let filePath = candidatePath.startsWith(resolvedDist) ? candidatePath : path.join(resolvedDist, 'index.html');

  try {
    const stat = await fs.promises.stat(filePath);
    if (stat.isDirectory()) {
      filePath = path.join(filePath, 'index.html');
    }
  } catch {
    filePath = path.join(resolvedDist, 'index.html');
  }

  const extension = path.extname(filePath).toLowerCase();
  res.writeHead(200, {
    'content-type': MIME_TYPES[extension] || 'application/octet-stream',
  });
  await streamPipeline(fs.createReadStream(filePath), res);
}

function parseWebSocketProtocols(header: string | string[] | undefined): string[] {
  if (!header) {
    return [];
  }
  const raw = Array.isArray(header) ? header.join(',') : header;
  return raw.split(',').map((value) => value.trim()).filter(Boolean);
}

function bridgeWebSockets(clientSocket: WebSocket, upstreamSocket: WebSocket): void {
  clientSocket.on('message', (data, isBinary) => {
    if (upstreamSocket.readyState === WebSocket.OPEN) {
      upstreamSocket.send(data, { binary: isBinary });
    }
  });
  upstreamSocket.on('message', (data, isBinary) => {
    if (clientSocket.readyState === WebSocket.OPEN) {
      clientSocket.send(data, { binary: isBinary });
    }
  });
  clientSocket.on('close', () => upstreamSocket.close());
  upstreamSocket.on('close', () => clientSocket.close());
  clientSocket.on('error', () => upstreamSocket.close());
  upstreamSocket.on('error', () => clientSocket.close());
}

export async function startDesktopServer(options: StartDesktopServerOptions): Promise<DesktopServer> {
  const webSocketServer = new WebSocketServer({ noServer: true });
  const server = http.createServer((req, res) => {
    void (async () => {
      if ((req.url || '').startsWith('/__client/proxy/')) {
        await proxyHttpRequest(req, res, options.getConfig);
        return;
      }
      await serveStatic(req, res, options.distDir);
    })().catch((error) => {
      if (!res.headersSent) {
        writeJson(res, 500, { detail: error instanceof Error ? error.message : '客户端本机服务异常' });
      } else {
        res.destroy(error instanceof Error ? error : undefined);
      }
    });
  });

  server.on('upgrade', (req, socket, head) => {
    void (async () => {
      const config = await options.getConfig();
      if (!config) {
        socket.destroy();
        return;
      }
      const targetUrl = resolveProxyTargetUrl(config, req.url || '/', 'websocket');
      webSocketServer.handleUpgrade(req, socket, head, (clientSocket) => {
        const upstreamSocket = new WebSocket(targetUrl, parseWebSocketProtocols(req.headers['sec-websocket-protocol']), {
          rejectUnauthorized: false,
        });
        upstreamSocket.on('open', () => bridgeWebSockets(clientSocket, upstreamSocket));
        upstreamSocket.on('error', () => clientSocket.close());
      });
    })().catch(() => socket.destroy());
  });

  await new Promise<void>((resolve) => {
    server.listen(0, '127.0.0.1', resolve);
  });
  const address = server.address();
  if (!address || typeof address === 'string') {
    throw new Error('Unable to start desktop local server');
  }

  return {
    origin: `http://127.0.0.1:${address.port}`,
    port: address.port,
    close: async () => {
      webSocketServer.close();
      await new Promise<void>((resolve, reject) => {
        server.close((error) => (error ? reject(error) : resolve()));
      });
    },
  };
}
