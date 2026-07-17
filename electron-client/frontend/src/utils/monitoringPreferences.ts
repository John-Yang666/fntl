import type { useUserStore } from '@/stores/userStore';
import { SYSTEMS, makeDeviceKey, parseDeviceKey, type SystemType } from '@/utils/systems';

interface MonitoringPreference {
  selection_mode: 'all' | 'custom';
  device_ids: number[];
}

type UserStore = ReturnType<typeof useUserStore>;

export async function loadMonitoringDeviceKeys(userStore: UserStore): Promise<string[]> {
  const authenticatedSystems = SYSTEMS.filter((system) => !!userStore.auth[system].token);
  const results = await Promise.allSettled(
    authenticatedSystems.map(async (system) => ({
      system,
      preference: await userStore.requestWithAuth<MonitoringPreference>(system, {
        method: 'get',
        url: '/monitoring-preference/',
      }),
    })),
  );

  return results.flatMap((result, index) => {
    if (result.status === 'rejected') {
      console.error(`获取 ${authenticatedSystems[index].toUpperCase()} 监控设备配置失败`, result.reason);
      return [];
    }
    return result.value.preference.device_ids.map((deviceId) =>
      makeDeviceKey(result.value.system, deviceId),
    );
  });
}

export async function saveMonitoringDeviceKeys(
  userStore: UserStore,
  selectedKeys: string[],
  availableKeys: string[],
): Promise<void> {
  const selectedBySystem: Record<SystemType, Set<number>> = { bt: new Set(), sy: new Set() };
  const availableBySystem: Record<SystemType, Set<number>> = { bt: new Set(), sy: new Set() };

  selectedKeys.forEach((key) => {
    const parsed = parseDeviceKey(key);
    if (parsed) selectedBySystem[parsed.system].add(parsed.deviceId);
  });
  availableKeys.forEach((key) => {
    const parsed = parseDeviceKey(key);
    if (parsed) availableBySystem[parsed.system].add(parsed.deviceId);
  });

  const authenticatedSystems = SYSTEMS.filter((system) => !!userStore.auth[system].token);
  const results = await Promise.allSettled(authenticatedSystems.map((system) => {
    const selected = Array.from(selectedBySystem[system]).sort((a, b) => a - b);
    const selectionMode = selected.length === availableBySystem[system].size ? 'all' : 'custom';
    return userStore.requestWithAuth(system, {
      method: 'put',
      url: '/monitoring-preference/',
      data: { selection_mode: selectionMode, device_ids: selected },
    });
  }));

  const failures = results.flatMap((result, index) =>
    result.status === 'rejected' ? [authenticatedSystems[index].toUpperCase()] : [],
  );
  if (failures.length > 0) {
    throw new Error(`${failures.join('、')} 监控设备配置保存失败`);
  }
}
