<template>
  <div class="records-view">
    <div class="system-summary-grid">
      <section v-for="system in systems" :key="system" class="system-summary-card">
        <div class="summary-header">
          <h2>{{ labels[system] }} 记录概览</h2>
          <div class="summary-actions">
            <el-button @click="openAdmin(system, 'alarmdata')">后台告警</el-button>
            <el-button @click="openAdmin(system, 'relayaction')">后台继电器</el-button>
            <el-button @click="openAdmin(system, 'useroperation')">后台操作</el-button>
          </div>
        </div>
        <div class="summary-stats">
          <div class="stat-card">
            <span class="stat-label">历史告警</span>
            <strong>{{ summary[system].alerts }}</strong>
          </div>
          <div class="stat-card">
            <span class="stat-label">继电器动作</span>
            <strong>{{ summary[system].relayActions }}</strong>
          </div>
        </div>
      </section>
    </div>

    <section class="table-section">
      <div class="section-header">
        <h2>历史告警</h2>
        <span class="section-count">{{ filteredAlerts.length }} 条</span>
      </div>
      <el-table :data="filteredAlerts" stripe>
        <el-table-column prop="systemLabel" label="系统" width="90" />
        <el-table-column prop="device_id" label="设备ID" width="100" />
        <el-table-column prop="device_name" label="设备名称" min-width="180" />
        <el-table-column prop="alarm_code" label="告警码" width="100" />
        <el-table-column prop="timestamp" label="开始时间" min-width="180">
          <template #default="{ row }">
            {{ formatToLocalTime(row.timestamp) }}
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section class="table-section">
      <div class="section-header">
        <h2>继电器动作</h2>
        <span class="section-count">{{ filteredRelayActions.length }} 条</span>
      </div>
      <el-table :data="filteredRelayActions" stripe>
        <el-table-column prop="systemLabel" label="系统" width="90" />
        <el-table-column prop="device_id" label="设备ID" width="100" />
        <el-table-column prop="device_name" label="设备名称" min-width="180" />
        <el-table-column prop="relay" label="继电器" min-width="140" />
        <el-table-column prop="action" label="动作" min-width="120" />
        <el-table-column prop="timestamp" label="时间" min-width="180">
          <template #default="{ row }">
            {{ formatToLocalTime(row.timestamp) }}
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<script lang="ts" setup>
import { computed, onMounted, ref } from 'vue';
import axios from 'axios';
import { reconcileSelectedDeviceKeys } from '@/utils/selectedDevices';
import { SYSTEM_LABELS, SYSTEMS, getApiBase, getSystemOrigin, makeDeviceKey, type SystemType } from '@/utils/systems';

interface AlertRecord {
  uniqueKey: string;
  system: SystemType;
  systemLabel: string;
  device_id: number;
  device_name: string;
  alarm_code: number;
  timestamp: string;
}

interface RelayActionRecord {
  uniqueKey: string;
  system: SystemType;
  systemLabel: string;
  device_id: number;
  device_name: string;
  relay: string;
  action: string;
  timestamp: string;
}

interface SummaryState {
  alerts: number;
  relayActions: number;
}

const systems = SYSTEMS;
const labels = SYSTEM_LABELS;
const alerts = ref<AlertRecord[]>([]);
const relayActions = ref<RelayActionRecord[]>([]);
const selectedDeviceKeys = ref<string[]>([]);
const summary = ref<Record<SystemType, SummaryState>>({
  bt: { alerts: 0, relayActions: 0 },
  sy: { alerts: 0, relayActions: 0 },
});

const filteredAlerts = computed(() => {
  const selectedSet = new Set(selectedDeviceKeys.value);
  return alerts.value.filter((record) =>
    selectedSet.size === 0 || selectedSet.has(makeDeviceKey(record.system, record.device_id)),
  );
});

const filteredRelayActions = computed(() => {
  const selectedSet = new Set(selectedDeviceKeys.value);
  return relayActions.value.filter((record) =>
    selectedSet.size === 0 || selectedSet.has(makeDeviceKey(record.system, record.device_id)),
  );
});

const formatToLocalTime = (timestamp: string): string => {
  if (!timestamp) {
    return '-';
  }

  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return timestamp;
  }

  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZone: 'Asia/Shanghai',
  }).format(date).replace(/\//g, '-').replace(',', '');
};

const openAdmin = (system: SystemType, model: string) => {
  window.open(`${getSystemOrigin(system)}/admin/myapp/${model}/`, '_blank');
};

const fetchDeviceNames = async (): Promise<Record<SystemType, Map<number, string>>> => {
  const deviceMaps: Record<SystemType, Map<number, string>> = {
    bt: new Map<number, string>(),
    sy: new Map<number, string>(),
  };

  const responses = await Promise.all(
    systems.map(async (system) => ({
      system,
      data: (await axios.get(`${getApiBase(system)}/devices-list/`)).data as Record<string, Array<{
        device_id: number;
        name: string;
      }>>,
    })),
  );

  const availableKeys: string[] = [];
  responses.forEach(({ system, data }) => {
    Object.values(data).forEach((devices) => {
      devices.forEach((device) => {
        deviceMaps[system].set(device.device_id, device.name);
        availableKeys.push(makeDeviceKey(system, device.device_id));
      });
    });
  });

  selectedDeviceKeys.value = await reconcileSelectedDeviceKeys(availableKeys);
  return deviceMaps;
};

const fetchRecords = async () => {
  const deviceMaps = await fetchDeviceNames();

  const responses = await Promise.all(
    systems.map(async (system) => ({
      system,
      alerts: (await axios.get(`${getApiBase(system)}/alerts/?page_size=20`)).data as {
        count: number;
        results: Array<{
          device_id: number;
          alarm_code: number;
          timestamp: string;
        }>;
      },
      relayActions: (await axios.get(`${getApiBase(system)}/relay-actions/?page_size=20`)).data as {
        count: number;
        results: Array<{
          id: string;
          device?: number;
          device_id?: number;
          relay: string;
          action: string;
          timestamp: string;
        }>;
      },
    })),
  );

  alerts.value = [];
  relayActions.value = [];

  responses.forEach(({ system, alerts: alertData, relayActions: relayData }) => {
    summary.value[system] = {
      alerts: alertData.count ?? alertData.results.length,
      relayActions: relayData.count ?? relayData.results.length,
    };

    alerts.value.push(
      ...alertData.results.map((record) => ({
        uniqueKey: `${system}:alert:${record.device_id}:${record.alarm_code}:${record.timestamp}`,
        system,
        systemLabel: labels[system],
        device_id: record.device_id,
        device_name: deviceMaps[system].get(record.device_id) || `设备 ${record.device_id}`,
        alarm_code: record.alarm_code,
        timestamp: record.timestamp,
      })),
    );

    relayActions.value.push(
      ...relayData.results.map((record) => {
        const deviceId = record.device_id ?? record.device ?? 0;
        return {
          uniqueKey: `${system}:relay:${record.id}`,
          system,
          systemLabel: labels[system],
          device_id: deviceId,
          device_name: deviceMaps[system].get(deviceId) || `设备 ${deviceId}`,
          relay: record.relay,
          action: record.action,
          timestamp: record.timestamp,
        };
      }),
    );
  });

  alerts.value.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
  relayActions.value.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
};

onMounted(async () => {
  await fetchRecords();
});
</script>

<style scoped>
.records-view {
  display: flex;
  flex-direction: column;
  gap: 24px;
  margin-top: 24px;
}

.system-summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 16px;
}

.system-summary-card {
  border: 1px solid #dcdfe6;
  border-radius: 12px;
  padding: 20px;
  background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
}

.summary-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 16px;
}

.summary-header h2 {
  margin: 0;
}

.summary-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.summary-stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(120px, 1fr));
  gap: 12px;
}

.stat-card {
  padding: 14px 16px;
  border-radius: 10px;
  background: #eef5ff;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.stat-label {
  color: #5b6b82;
  font-size: 14px;
}

.stat-card strong {
  font-size: 24px;
  color: #1d4ed8;
}

.table-section {
  border: 1px solid #dcdfe6;
  border-radius: 12px;
  padding: 20px;
  background: #ffffff;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.section-header h2 {
  margin: 0;
}

.section-count {
  color: #5b6b82;
  font-size: 14px;
}
</style>
