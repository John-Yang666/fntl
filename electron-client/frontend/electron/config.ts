import { promises as fs } from 'node:fs';
import path from 'node:path';

export interface ClientConfig {
  btBaseUrl: string;
  syBaseUrl: string;
}

export const DEFAULT_CLIENT_CONFIG: ClientConfig = {
  btBaseUrl: 'http://127.0.0.1:8000',
  syBaseUrl: 'http://127.0.0.1:8001',
};

export function normalizeBackendBaseUrl(value: string): string {
  const trimmed = value.trim().replace(/\/+$/, '');
  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch (error) {
    throw new Error('Backend URL must be a valid absolute URL');
  }

  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new Error('Backend URL must start with http:// or https://');
  }

  parsed.pathname = parsed.pathname.replace(/\/+$/, '');
  parsed.search = '';
  parsed.hash = '';
  return parsed.toString().replace(/\/+$/, '');
}

export function normalizeClientConfig(config: Partial<ClientConfig> | null | undefined): ClientConfig {
  return {
    btBaseUrl: normalizeBackendBaseUrl(config?.btBaseUrl || DEFAULT_CLIENT_CONFIG.btBaseUrl),
    syBaseUrl: normalizeBackendBaseUrl(config?.syBaseUrl || DEFAULT_CLIENT_CONFIG.syBaseUrl),
  };
}

export async function loadClientConfig(configPath: string): Promise<ClientConfig | null> {
  try {
    const raw = await fs.readFile(configPath, 'utf-8');
    return normalizeClientConfig(JSON.parse(raw) as Partial<ClientConfig>);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      return null;
    }
    throw error;
  }
}

export async function saveClientConfig(configPath: string, config: Partial<ClientConfig>): Promise<ClientConfig> {
  const normalized = normalizeClientConfig(config);
  await fs.mkdir(path.dirname(configPath), { recursive: true });
  await fs.writeFile(configPath, `${JSON.stringify(normalized, null, 2)}\n`, 'utf-8');
  return normalized;
}
