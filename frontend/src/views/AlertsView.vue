<template>
  <div>
    <div class="filter-container">
      <select v-model="selectedDevice" @change="applyFilters">
        <option value="">所有设备</option>
        <option v-for="device in deviceNames" :key="device" :value="device">{{ device }}</option>
      </select>
      <select v-model="selectedAlarmMeaning" @change="applyFilters">
        <option value="">所有告警</option>
        <option v-for="meaning in alarmMeanings" :key="meaning">{{ meaning }}</option>
      </select>
      <el-button @click="refreshAlerts" class="refresh-button">刷新告警</el-button> <!-- Refresh Button -->
    </div>
    <table>
      <thead>
        <tr>
          <th>序号</th>
          <th>设备ID</th>
          <th>设备名称</th>
          <th>告警码</th>
          <th>告警含义</th>
          <th>起始时间</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(alert, index) in filteredAlerts" :key="index">
          <td>{{ index + 1 }}</td>
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
import axios from 'axios';
import { ref, computed, onMounted } from 'vue';
import { saveToDB, getFromDB, deleteFromDB } from '@/utils/indexedDB';

interface Alert {
  device_id: number;
  device_name: string;
  alarm_code: number;
  alarm_meaning: string;
  timestamp: string;  // timestamp_start
  confirmed: boolean; // is_confirmed
}

// 动态获取当前浏览器地址栏的 IP 或域名
const backendPort = import.meta.env.VITE_BACKEND_PORT;
const baseURL = `${window.location.protocol}//${window.location.hostname}:${backendPort}/api`;

const alerts = ref<Alert[]>([]);
const selectedDevice = ref('');
const selectedAlarmMeaning = ref('');
const deviceNames = ref<string[]>([]);
const alarmMeanings = ref<string[]>([]);
const selecteddevice_ids = ref<number[]>([]);

const fetchAlerts = async () => {
  try {
    const response = await axios.get(`${baseURL}/active-alarms/`);
    //const response = await axios.get(`${baseURL}/red-alert/`);
    alerts.value = response.data;

    // 提取过滤器选项
    const devicesSet = new Set<string>();
    const alarmMeaningsSet = new Set<string>();
    alerts.value.forEach(alert => {
      devicesSet.add(alert.device_name);
      alarmMeaningsSet.add(alert.alarm_meaning);
    });

    deviceNames.value = Array.from(devicesSet);
    alarmMeanings.value = Array.from(alarmMeaningsSet);

    applyFilters();
  } catch (error) {
    console.error('Failed to fetch alerts:', error);
  }
};


const filteredAlerts = computed(() => {
  return alerts.value
    .filter(alert => {
      // First filter by selected device
      const deviceSelected = selecteddevice_ids.value.length === 0 || selecteddevice_ids.value.includes(alert.device_id);
      
      // Then filter by selected device name and alarm meaning
      return deviceSelected &&
             (selectedDevice.value ? alert.device_name === selectedDevice.value : true) &&
             (selectedAlarmMeaning.value ? alert.alarm_meaning === selectedAlarmMeaning.value : true);
    })
    .sort((a, b) => {
      // Sort by confirmation status first, then by timestamp in descending order
      if (a.confirmed === b.confirmed) {
        return new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime();
      }
      return a.confirmed ? 1 : -1; // Unconfirmed first
    });
});

const applyFilters = () => {
  // Any filtering logic can go here if necessary
};

const confirmAlert = async (alert: Alert) => {
  try {
    await axios.post(`${baseURL}/active-alarms/${alert.device_id}/${alert.alarm_code}/confirm/`);
    alert.confirmed = true;  // 本地立即显示已确认（基于用户操作）
  } catch (error) {
    console.error("确认告警失败：", error);
  }
};



const persistAlertState = (alert: Alert) => {
  const alertKey = `${alert.device_id}_${alert.alarm_code}`;
  const alertData = {
    confirmed: true,
    timestamp: alert.timestamp
  };
  
  // Save the alert state in localStorage
  localStorage.setItem(alertKey, JSON.stringify(alertData));
};

const restoreAlertState = () => {
  alerts.value.forEach(alert => {
    const alertKey = `${alert.device_id}_${alert.alarm_code}`;
    const storedAlert = localStorage.getItem(alertKey);
    
    if (storedAlert) {
      const storedAlertData = JSON.parse(storedAlert);
      
      // Compare the stored timestamp with the current alert's timestamp
      if (storedAlertData.timestamp === alert.timestamp) {
        alert.confirmed = storedAlertData.confirmed;
      } else {
        alert.confirmed = false; // Reset confirmation if the timestamp has changed
      }
    }
  });
};

// Format timestamp to local time and add 16 hours
const formatToLocalTime = (timestamp: string): string => {
  const date = new Date(timestamp);  // 不再拼接 Z

  if (isNaN(date.getTime())) throw new Error("Invalid timestamp");

  const formatter = new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone: "Asia/Shanghai"
  });

  return formatter.format(date).replace(/\//g, "-").replace(",", "");
};


// Refresh the alert data
const refreshAlerts = () => {
  fetchAlerts(); // Fetch the alerts again
};

onMounted(async () => {
  const storedSelectedDevices = await getFromDB<string>('selectedDevices');
  if (storedSelectedDevices) {
    selecteddevice_ids.value = JSON.parse(storedSelectedDevices);
  }
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
  justify-content: space-between;
  margin-top: 20px;
  margin-bottom: 20px;
}

select {
  padding: 5px;
  font-size: 14px;
}

.refresh-button {
  margin-left: 20px;
}
</style>
