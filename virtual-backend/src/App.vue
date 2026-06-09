<template>
  <main class="app-shell">
    <header class="topbar">
      <div>
        <h1>贝通网管虚拟后端</h1>
        <div class="service-row">
          <span :class="serviceClass(state?.services.bt.running)">BT {{ serviceLabel(state?.services.bt) }}</span>
          <span :class="serviceClass(state?.services.sy.running)">SY {{ serviceLabel(state?.services.sy) }}</span>
        </div>
      </div>
      <div class="toolbar">
        <a class="button ghost" :href="adminUrl('bt')" target="_blank">BT Admin</a>
        <a class="button ghost" :href="adminUrl('sy')" target="_blank">SY Admin</a>
        <button class="button" type="button" @click="broadcast">广播</button>
        <button class="button danger" type="button" @click="reset">重置</button>
      </div>
    </header>

    <section v-if="error" class="notice error">{{ error }}</section>
    <section v-if="portErrors.length" class="notice warning">
      <div v-for="item in portErrors" :key="item">{{ item }}</div>
    </section>

    <section class="summary-grid">
      <article v-for="card in summaryCards" :key="card.label" class="metric">
        <span>{{ card.label }}</span>
        <strong>{{ card.value }}</strong>
      </article>
    </section>

    <section class="systems-grid">
      <article v-for="system in systems" :key="system" class="system-panel">
        <div class="panel-header">
          <h2>{{ system.toUpperCase() }}</h2>
          <span>{{ devices(system).length }} 台设备</span>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>名称</th>
                <th>IP</th>
                <th>故障状态</th>
                <th v-if="system === 'bt'">模拟量</th>
                <th v-if="system === 'sy'">主备状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="device in devices(system)" :key="device.device_id">
                <td>{{ device.device_id }}</td>
                <td>{{ device.name }}</td>
                <td>{{ device.ip_address }}</td>
                <td>
                  <select :value="device.fault" @change="setFault(system, device.device_id, $event)">
                    <option v-for="option in faultOptions" :key="option.value" :value="option.value">
                      {{ option.label }}
                    </option>
                  </select>
                </td>
                <td v-if="system === 'bt'">
                  <label class="checkline">
                    <input
                      type="checkbox"
                      :checked="Boolean(device.analogFault)"
                      @change="setAnalogFault(device.device_id, $event)"
                    >
                    异常
                  </label>
                </td>
                <td v-if="system === 'sy'">
                  <select :value="device.syRunState || 'normal'" @change="setSyRunState(device.device_id, $event)">
                    <option value="normal">正常</option>
                    <option value="started">已启动</option>
                    <option value="main_disabled">主机停用</option>
                    <option value="backup_disabled">备机停用</option>
                  </select>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>
    </section>

    <section class="records-panel">
      <div class="panel-header">
        <h2>当前告警</h2>
        <span>{{ activeAlarms.length }} 条</span>
      </div>
      <table>
        <thead>
          <tr>
            <th>系统</th>
            <th>设备</th>
            <th>告警码</th>
            <th>含义</th>
            <th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="alert in activeAlarms" :key="`${alert.system}-${alert.id}`">
            <td>{{ alert.system.toUpperCase() }}</td>
            <td>{{ alert.device_name }}</td>
            <td>{{ alert.alarm_code }}</td>
            <td>{{ alert.alarm_meaning }}</td>
            <td>{{ formatTime(alert.timestamp) }}</td>
          </tr>
          <tr v-if="activeAlarms.length === 0">
            <td colspan="5" class="empty">无当前告警</td>
          </tr>
        </tbody>
      </table>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';

type SystemType = 'bt' | 'sy';
type FaultState = 'normal' | 'offline' | 'direction1_fault' | 'direction2_fault' | 'alarm';

interface DemoDevice {
  device_id: number;
  name: string;
  ip_address: string;
  fault: FaultState;
  analogFault?: boolean;
  syRunState?: 'normal' | 'started' | 'main_disabled' | 'backup_disabled';
}

interface AlertRecord {
  id: string;
  device_id: number;
  device_name: string;
  alarm_code: number;
  alarm_meaning: string;
  timestamp: string;
  timestamp_end: string | null;
  is_confirmed: boolean;
}

interface ServiceStatus {
  port: number;
  running: boolean;
  error?: string;
}

interface ControlState {
  services: Record<SystemType, ServiceStatus>;
  devices: Record<SystemType, DemoDevice[]>;
  records: Record<SystemType, { alerts: AlertRecord[] }>;
}

const systems: SystemType[] = ['bt', 'sy'];
const state = ref<ControlState | null>(null);
const error = ref('');

const faultOptions: Array<{ value: FaultState; label: string }> = [
  { value: 'normal', label: '正常' },
  { value: 'offline', label: '通信中断' },
  { value: 'direction1_fault', label: '一方向故障' },
  { value: 'direction2_fault', label: '二方向故障' },
  { value: 'alarm', label: '当前告警' },
];

const devices = (system: SystemType) => state.value?.devices[system] || [];

const activeAlarms = computed(() => {
  if (!state.value) return [];
  return systems.flatMap((system) =>
    state.value!.records[system].alerts
      .filter((alert) => alert.timestamp_end == null && !alert.is_confirmed)
      .map((alert) => ({ ...alert, system })),
  );
});

const summaryCards = computed(() => [
  { label: 'BT设备', value: devices('bt').length },
  { label: 'SY设备', value: devices('sy').length },
  { label: '当前告警', value: activeAlarms.value.length },
  {
    label: '异常设备',
    value: systems.reduce(
      (total, system) => total + devices(system).filter((device) => device.fault !== 'normal').length,
      0,
    ),
  },
]);

const portErrors = computed(() => {
  if (!state.value) return [];
  return systems.flatMap((system) => {
    const service = state.value!.services[system];
    return service.running ? [] : [`${system.toUpperCase()} ${service.port} 未启动：${service.error || '端口不可用'}`];
  });
});

const loadState = async () => {
  try {
    error.value = '';
    const response = await fetch('/__sim/state');
    state.value = await response.json();
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载状态失败';
  }
};

const postJson = async (path: string, body?: unknown) => {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: body == null ? undefined : JSON.stringify(body),
  });
  const payload = await response.json();
  if (payload.devices) {
    state.value = payload;
  }
  return payload;
};

const setFault = async (system: SystemType, deviceId: number, event: Event) => {
  await postJson('/__sim/device-state', {
    system,
    deviceId,
    fault: (event.target as HTMLSelectElement).value,
  });
};

const setAnalogFault = async (deviceId: number, event: Event) => {
  await postJson('/__sim/device-state', {
    system: 'bt',
    deviceId,
    analogFault: (event.target as HTMLInputElement).checked,
  });
};

const setSyRunState = async (deviceId: number, event: Event) => {
  await postJson('/__sim/device-state', {
    system: 'sy',
    deviceId,
    syRunState: (event.target as HTMLSelectElement).value,
  });
};

const reset = async () => {
  await postJson('/__sim/reset');
};

const broadcast = async () => {
  await postJson('/__sim/broadcast');
  await loadState();
};

const adminUrl = (system: SystemType) => {
  const port = system === 'bt' ? 8000 : 8001;
  return `http://127.0.0.1:${port}/admin/`;
};

const serviceLabel = (service?: ServiceStatus) => {
  if (!service) return '未启动';
  return service.running ? `127.0.0.1:${service.port}` : `${service.port} 未启动`;
};

const serviceClass = (running?: boolean) => ['service-pill', running ? 'ok' : 'bad'];

const formatTime = (value: string) => new Date(value).toLocaleString();

onMounted(() => {
  loadState();
  window.setInterval(loadState, 5000);
});
</script>
