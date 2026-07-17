import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PINNED_DEVICES_KEY } from '../systems';
import {
  loadPinnedDeviceKeys,
  reconcilePinnedDeviceKeys,
  savePinnedDeviceKeys,
} from '../pinnedDevices';

const db = new Map<string, unknown>();

vi.mock('../indexedDB', () => ({
  getFromDB: vi.fn(async (key: string) => db.get(key) ?? null),
  saveToDB: vi.fn(async (key: string, value: unknown) => { db.set(key, value); }),
}));

describe('pinned device persistence', () => {
  beforeEach(() => db.clear());

  it('deduplicates and discards invalid pinned device keys', async () => {
    await savePinnedDeviceKeys(['sy:101', 'bad', 'sy:101']);
    await expect(loadPinnedDeviceKeys()).resolves.toEqual(['sy:101']);
  });

  it('removes pins for devices that are no longer monitored', async () => {
    db.set(PINNED_DEVICES_KEY, JSON.stringify(['bt:1', 'sy:101', 'sy:999']));
    await expect(reconcilePinnedDeviceKeys(['bt:1', 'sy:101'])).resolves.toEqual(['bt:1', 'sy:101']);
    expect(db.get(PINNED_DEVICES_KEY)).toBe(JSON.stringify(['bt:1', 'sy:101']));
  });
});
