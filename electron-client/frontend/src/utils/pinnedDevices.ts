import { getFromDB, saveToDB } from '@/utils/indexedDB';
import {
  PINNED_DEVICES_KEY,
  parseDeviceKey,
} from '@/utils/systems';

function normalizeDeviceKeyList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value
      .map((item) => (typeof item === 'string' ? item : String(item)))
      .filter((item) => parseDeviceKey(item) !== null);
  }

  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value);
      return normalizeDeviceKeyList(parsed);
    } catch {
      return [];
    }
  }

  return [];
}

export async function loadPinnedDeviceKeys(): Promise<string[]> {
  const currentValue = await getFromDB<string | string[]>(PINNED_DEVICES_KEY);
  return normalizeDeviceKeyList(currentValue);
}

export async function savePinnedDeviceKeys(keys: string[]): Promise<void> {
  const uniqueKeys = Array.from(new Set(keys)).filter((key) => parseDeviceKey(key) !== null);
  await saveToDB(PINNED_DEVICES_KEY, JSON.stringify(uniqueKeys));
}

export async function reconcilePinnedDeviceKeys(availableKeys: string[]): Promise<string[]> {
  const uniqueAvailableKeys = Array.from(new Set(availableKeys)).filter((key) => parseDeviceKey(key) !== null);
  if (uniqueAvailableKeys.length === 0) {
    await savePinnedDeviceKeys([]);
    return [];
  }

  const storedKeys = await loadPinnedDeviceKeys();
  const availableSet = new Set(uniqueAvailableKeys);
  const validStoredKeys = storedKeys.filter((key) => availableSet.has(key));

  if (validStoredKeys.length !== storedKeys.length) {
    await savePinnedDeviceKeys(validStoredKeys);
  }

  return validStoredKeys;
}
