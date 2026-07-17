import { describe, expect, it, vi } from 'vitest';
import { loadMonitoringDeviceKeys, saveMonitoringDeviceKeys } from '../monitoringPreferences';

describe('backend monitoring preferences', () => {
  it('loads and qualifies BT/SY device ids', async () => {
    const store = {
      auth: { bt: { token: 'bt-token' }, sy: { token: 'sy-token' } },
      requestWithAuth: vi.fn(async (system: 'bt' | 'sy') => ({
        selection_mode: 'custom',
        device_ids: system === 'bt' ? [1, 2] : [101],
      })),
    };
    await expect(loadMonitoringDeviceKeys(store as never)).resolves.toEqual(['bt:1', 'bt:2', 'sy:101']);
  });

  it('saves all/custom selection independently per system', async () => {
    const requestWithAuth = vi.fn(async () => ({}));
    const store = {
      auth: { bt: { token: 'bt-token' }, sy: { token: 'sy-token' } },
      requestWithAuth,
    };
    await saveMonitoringDeviceKeys(
      store as never,
      ['bt:1', 'bt:2', 'sy:101'],
      ['bt:1', 'bt:2', 'sy:101', 'sy:102'],
    );
    expect(requestWithAuth).toHaveBeenCalledWith('bt', expect.objectContaining({
      data: { selection_mode: 'all', device_ids: [1, 2] },
    }));
    expect(requestWithAuth).toHaveBeenCalledWith('sy', expect.objectContaining({
      data: { selection_mode: 'custom', device_ids: [101] },
    }));
  });
});
