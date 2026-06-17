import { describe, expect, it } from 'vitest';
import {
  DEFAULT_CLIENT_CONFIG,
  normalizeFrontendBaseUrl,
  normalizeClientConfig,
} from './config';

describe('desktop client config', () => {
  it('normalizes frontend entry URLs and migrates old backend ports', () => {
    expect(normalizeFrontendBaseUrl(' http://192.168.1.10:8000/// ')).toBe('http://192.168.1.10:38173');
    expect(normalizeFrontendBaseUrl(' https://192.168.1.10:8444/// ')).toBe('https://192.168.1.10:38443');
  });

  it('falls back to default BT and SY URLs when config is missing', () => {
    expect(normalizeClientConfig(null)).toEqual(DEFAULT_CLIENT_CONFIG);
  });

  it('rejects non-http frontend URLs', () => {
    expect(() => normalizeFrontendBaseUrl('file:///tmp/frontend')).toThrow('Frontend entry URL must start with http:// or https://');
  });
});
