<template>
  <div data-testid="alerts-view">
    <div class="filter-container">
      <select v-model="selectedSystem">
        <option value="">所有系统</option>
        <option value="bt">BT</option>
        <option value="sy">SY</option>
      </select>
      <select v-model="selectedDevice">
        <option value="">所有设备</option>
        <option v-for="device in deviceNames" :key="device" :value="device">{{ device }}</option>
      </select>
      <select v-model="selectedAlarmMeaning">
        <option value="">所有告警</option>
        <option v-for="meaning in alarmMeanings" :key="meaning">{{ meaning }}</option>
      </select>
      <el-button @click="refreshAlerts" class="refresh-button">刷新告警</el-button>
    </div>
    <table>
      <thead>
        <tr>
          <th>序号</th>
          <th>系统</th>
          <th>设备ID</th>
          <th>设备名称</th>
          <th>告警码</th>
          <th>告警含义</th>
          <th>起始时间</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(alert, index) in filteredAlerts" :key="alert.uniqueKey">
          <td>{{ index + 1 }}</td>
          <td>{{ alert.system.toUpperCase() }}</td>
          <td>{{ alert.device_id }}</td>
          <td>{{ alert.device_name }}</td>
          <td>{{ alert.alarm_code }}</td>
          <td>{{ alert.alarm_meaning }}</td>
          <td>{{ formatToLocalTime(alert.timestamp) }}</td>
          <td>
            <el-button v-if="!alert.confirmed" @click="confirmAlert(alert)">确认</el-button>
            <span v-else>已确认</span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useUserStore } from '@/stores/userStore';
import { loadSelectedDeviceKeys } from '@/utils/selectedDevices';
import { SYSTEMS, makeDeviceKey, type SystemType } from '@/utils/systems';

interface Alert {
  system: SystemType;
  uniqueKey: string;
  device_id: number;
  device_name: string;
  alarm_code: number;
  alarm_meaning: string;
  timestamp: string;
  confirmed: boolean;
}

const alerts = ref<Alert[]>([]);
const selectedSystem = ref('');
const selectedDevice = ref('');
const selectedAlarmMeaning = ref('');
const deviceNames = ref<string[]>([]);
const alarmMeanings = ref<string[]>([]);
const selectedDeviceKeys = ref<string[]>([]);
const userStore = useUserStore();

const fetchAlerts = async () => {
  const settledResponses = await Promise.allSettled(
    SYSTEMS.map(async (system) => ({
      system,
      alerts: await userStore.requestWithAuth<Array<{
        device_id: number;
        device_name: string;
        alarm_code: number;
        alarm_meaning: string;
        timestamp: string;
        confirmed: boolean;
      }>>(system, {
        method: 'get',
        url: '/active-alarms/',
      }),
    })),
  );

  const responses = settledResponses
    .flatMap((result) => {
      if (result.status === 'fulfilled') {
        return [result.value];
      }
      console.error('Failed to fetch alerts:', result.reason);
      return [];
    });

  alerts.value = responses.flatMap(({ system, alerts: systemAlerts }) =>
    systemAlerts.map((alert) => ({
      system,
      uniqueKey: `${system}:${alert.device_id}:${alert.alarm_code}:${alert.timestamp}`,
      ...alert,
    })),
  );

  const devicesSet = new Set<string>();
  const alarmMeaningsSet = new Set<string>();
  alerts.value.forEach((alert) => {
    devicesSet.add(alert.device_name);
    alarmMeaningsSet.add(alert.alarm_meaning);
  });

  deviceNames.value = Array.from(devicesSet);
  alarmMeanings.value = Array.from(alarmMeaningsSet);
};

const filteredAlerts = computed(() => {
  const selectedSet = new Set(selectedDeviceKeys.value);
  return alerts.value
    .filter((alert) => {
      const deviceSelected =
        selectedSet.size === 0 || selectedSet.has(makeDeviceKey(alert.system, alert.device_id));

      return deviceSelected &&
        (selectedSystem.value ? alert.system === selectedSystem.value : true) &&
        (selectedDevice.value ? alert.device_name === selectedDevice.value : true) &&
        (selectedAlarmMeaning.value ? alert.alarm_meaning === selectedAlarmMeaning.value : true);
    })
    .sort((a, b) => {
      if (a.confirmed === b.confirmed) {
        return new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime();
      }
      return a.confirmed ? 1 : -1;
    });
});

const confirmAlert = async (alert: Alert) => {
  try {
    await userStore.requestWithAuth(alert.system, {
      method: 'post',
      url: `/active-alarms/${alert.device_id}/${alert.alarm_code}/confirm/`,
    });
    alert.confirmed = true;
  } catch (error) {
    console.error('确认告警失败：', error);
  }
};

const formatToLocalTime = (timestamp: string): string => {
  const date = new Date(timestamp);
  if (isNaN(date.getTime())) throw new Error('Invalid timestamp');

  const formatter = new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZone: 'Asia/Shanghai'
  });

  return formatter.format(date).replace(/\//g, '-').replace(',', '');
};

const refreshAlerts = () => {
  fetchAlerts();
};

onMounted(async () => {
  selectedDeviceKeys.value = await loadSelectedDeviceKeys();
  fetchAlerts();
});
</script>

<style scoped>
table {
  width: 100%;
  border-collapse: collapse;
}

th, td {
  border: 1px solid #ddd;
  padding: 8px;
}

th {
  background-color: #f2f2f2;
}

.filter-container {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-top: 20px;
  margin-bottom: 20px;
}

select {
  padding: 5px;
  font-size: 14px;
}
</style>
