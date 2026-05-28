import { describe, expect, it } from 'vitest';
import {
  DEFAULT_CLIENT_CONFIG,
  normalizeBackendBaseUrl,
  normalizeClientConfig,
} from './config';

describe('desktop client config', () => {
  it('normalizes backend URLs by trimming whitespace and trailing slashes', () => {
    expect(normalizeBackendBaseUrl(' http://192.168.1.10:8000/// ')).toBe('http://192.168.1.10:8000');
  });

  it('falls back to default BT and SY URLs when config is missing', () => {
    expect(normalizeClientConfig(null)).toEqual(DEFAULT_CLIENT_CONFIG);
  });

  it('rejects non-http backend URLs', () => {
    expect(() => normalizeBackendBaseUrl('file:///tmp/backend')).toThrow('Backend URL must start with http:// or https://');
  });
});
