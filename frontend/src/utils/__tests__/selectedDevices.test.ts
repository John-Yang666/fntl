import { beforeEach, describe, expect, it, vi } from 'vitest';

const db = new Map<string, unknown>();

vi.mock('../indexedDB', () => ({
  getFromDB: vi.fn(async (key: string) => db.get(key) ?? null),
  saveToDB: vi.fn(async (key: string, value: unknown) => {
    db.set(key, value);
  }),
  deleteFromDB: vi.fn(async (key: string) => {
    db.delete(key);
  }),
}));

import {
  LEGACY_SELECTED_DEVICES_KEY,
  PINNED_DEVICES_KEY,
  SELECTED_DEVICES_KEY,
} from '../systems';
import {
  loadSelectedDeviceKeys,
  reconcilePinnedDeviceKeys,
  reconcileSelectedDeviceKeys,
  savePinnedDeviceKeys,
  saveSelectedDeviceKeys,
} from '../selectedDevices';

describe('selected device persistence', () => {
  beforeEach(() => {
    db.clear();
    window.localStorage.clear();
  });

  it('migrates legacy numeric BT device selections into system-qualified keys', async () => {
    db.set(LEGACY_SELECTED_DEVICES_KEY, JSON.stringify([1, '2', 'bad']));

    await expect(loadSelectedDeviceKeys()).resolves.toEqual(['bt:1', 'bt:2']);
    expect(db.get(SELECTED_DEVICES_KEY)).toBe(JSON.stringify(['bt:1', 'bt:2']));
  });

  it('deduplicates and discards invalid selected and pinned device keys', async () => {
    await saveSelectedDeviceKeys(['bt:1', 'sy:101', 'bt:1', 'xx:1']);
    await savePinnedDeviceKeys(['sy:101', 'bad', 'sy:101']);

    await expect(loadSelectedDeviceKeys()).resolves.toEqual(['bt:1', 'sy:101']);
    expect(db.get(PINNED_DEVICES_KEY)).toBe(JSON.stringify(['sy:101']));
  });

  it('reconciles stored selections and pins against available BT/SY devices', async () => {
    db.set(SELECTED_DEVICES_KEY, JSON.stringify(['bt:1', 'sy:101', 'bt:99']));
    db.set(PINNED_DEVICES_KEY, JSON.stringify(['sy:101', 'sy:999']));

    await expect(reconcileSelectedDeviceKeys(['bt:1', 'sy:101'])).resolves.toEqual(['bt:1', 'sy:101']);
    await expect(reconcilePinnedDeviceKeys(['bt:1', 'sy:101'])).resolves.toEqual(['sy:101']);
    expect(db.get(SELECTED_DEVICES_KEY)).toBe(JSON.stringify(['bt:1', 'sy:101']));
    expect(db.get(PINNED_DEVICES_KEY)).toBe(JSON.stringify(['sy:101']));
  });

  it('selects all available devices on first run', async () => {
    await expect(reconcileSelectedDeviceKeys(['bt:1', 'sy:101'])).resolves.toEqual(['bt:1', 'sy:101']);
    expect(window.localStorage.getItem('selectedDevicesSystemsMigratedV1')).toBe('true');
  });
});
