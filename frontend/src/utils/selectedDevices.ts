import { getFromDB, saveToDB } from '@/utils/indexedDB';
import {
  LEGACY_SELECTED_DEVICES_KEY,
  PINNED_DEVICES_KEY,
  SELECTED_DEVICES_KEY,
  SystemType,
  makeDeviceKey,
  parseDeviceKey,
} from '@/utils/systems';

const SELECTED_DEVICES_SYSTEM_MIGRATION_KEY = 'selectedDevicesSystemsMigratedV1';

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

function normalizeLegacyDeviceList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value
      .map((item) => Number.parseInt(String(item), 10))
      .filter((item) => !Number.isNaN(item))
      .map((item) => makeDeviceKey('bt', item));
  }

  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value);
      return normalizeLegacyDeviceList(parsed);
    } catch {
      return [];
    }
  }

  return [];
}

export async function loadSelectedDeviceKeys(): Promise<string[]> {
  const currentValue = await getFromDB<string | string[]>(SELECTED_DEVICES_KEY);
  const currentKeys = normalizeDeviceKeyList(currentValue);
  if (currentValue !== null) {
    return currentKeys;
  }

  const legacyValue = await getFromDB<string | number[]>(LEGACY_SELECTED_DEVICES_KEY);
  const legacyKeys = normalizeLegacyDeviceList(legacyValue);
  if (legacyKeys.length > 0) {
    await saveSelectedDeviceKeys(legacyKeys);
  }
  return legacyKeys;
}

export async function saveSelectedDeviceKeys(keys: string[]): Promise<void> {
  const uniqueKeys = Array.from(new Set(keys)).filter((key) => parseDeviceKey(key) !== null);
  await saveToDB(SELECTED_DEVICES_KEY, JSON.stringify(uniqueKeys));
}

export async function loadPinnedDeviceKeys(): Promise<string[]> {
  const currentValue = await getFromDB<string | string[]>(PINNED_DEVICES_KEY);
  return normalizeDeviceKeyList(currentValue);
}

export async function savePinnedDeviceKeys(keys: string[]): Promise<void> {
  const uniqueKeys = Array.from(new Set(keys)).filter((key) => parseDeviceKey(key) !== null);
  await saveToDB(PINNED_DEVICES_KEY, JSON.stringify(uniqueKeys));
}

export async function reconcileSelectedDeviceKeys(availableKeys: string[]): Promise<string[]> {
  const uniqueAvailableKeys = Array.from(new Set(availableKeys)).filter((key) => parseDeviceKey(key) !== null);
  if (uniqueAvailableKeys.length === 0) {
    return [];
  }

  const currentStoredValue = await getFromDB<string | string[]>(SELECTED_DEVICES_KEY);
  const hasStoredSelection = currentStoredValue !== null;
  const storedKeys = await loadSelectedDeviceKeys();
  if (!hasStoredSelection && storedKeys.length === 0) {
    await saveSelectedDeviceKeys(uniqueAvailableKeys);
    localStorage.setItem(SELECTED_DEVICES_SYSTEM_MIGRATION_KEY, 'true');
    return uniqueAvailableKeys;
  }

  const availableSet = new Set(uniqueAvailableKeys);
  const validStoredKeys = storedKeys.filter((key) => availableSet.has(key));

  if (hasStoredSelection && storedKeys.length === 0) {
    localStorage.setItem(SELECTED_DEVICES_SYSTEM_MIGRATION_KEY, 'true');
    return [];
  }

  const migrationDone = localStorage.getItem(SELECTED_DEVICES_SYSTEM_MIGRATION_KEY) === 'true';
  if (!migrationDone && validStoredKeys.length > 0) {
    const availableSystems = new Set(uniqueAvailableKeys.map((key) => parseDeviceKey(key)?.system).filter(Boolean));
    const storedSystems = new Set(validStoredKeys.map((key) => parseDeviceKey(key)?.system).filter(Boolean));
    const missingSystems = Array.from(availableSystems).filter((system) => !storedSystems.has(system));

    if (missingSystems.length > 0) {
      const migratedKeys = Array.from(
        new Set([
          ...validStoredKeys,
          ...uniqueAvailableKeys.filter((key) => {
            const parsed = parseDeviceKey(key);
            return !!parsed && missingSystems.includes(parsed.system);
          }),
        ]),
      );
      await saveSelectedDeviceKeys(migratedKeys);
      localStorage.setItem(SELECTED_DEVICES_SYSTEM_MIGRATION_KEY, 'true');
      return migratedKeys;
    }

    localStorage.setItem(SELECTED_DEVICES_SYSTEM_MIGRATION_KEY, 'true');
  } else if (!migrationDone && hasStoredSelection) {
    localStorage.setItem(SELECTED_DEVICES_SYSTEM_MIGRATION_KEY, 'true');
  }

  if (validStoredKeys.length !== storedKeys.length) {
    await saveSelectedDeviceKeys(validStoredKeys);
  }

  return validStoredKeys;
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

export function isDeviceSelected(
  selectedKeys: Set<string>,
  system: SystemType,
  deviceId: number,
): boolean {
  return selectedKeys.has(makeDeviceKey(system, deviceId));
}
