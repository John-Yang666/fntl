<template>
  <div class="device-filter">
    <el-collapse>
      <el-collapse-item title="选择需要监控的设备" name="1">
        <el-transfer
          v-model="selectedDevices"
          :data="filteredDeviceOptions"
          filterable
          filter-placeholder="搜索设备"
          :titles="['可选设备', '已选设备']"
          :props="{ key: 'device_id', label: 'name', disabled: 'disabled' }"
          @change="handleDeviceChange"
        >
          <template v-slot:left-default="{ option }">
            <span v-if="option.isGroup" class="line-group">{{ option.line }}</span>
            <span v-else>{{ option.name }}</span>
          </template>
        </el-transfer>
        <div class="button-container">
          <el-button type="primary" @click="refreshPage">确认</el-button>
        </div>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script lang="ts" setup>
import { ref, onMounted, computed } from 'vue';
import axios from 'axios';
import { saveToDB, getFromDB, deleteFromDB } from '@/utils/indexedDB'; // 假设已经实现了这些函数 
 
interface Device {
  device_id: number;
  name: string;
  line: string;
  isGroup?: boolean;
  disabled?: boolean;
}
 
interface GroupedDevices {
  [line: string]: Device[];
}
 
const deviceOptions = ref<Device[]>([]);
const selectedDevices = ref<number[]>([]);
 
// 动态获取当前浏览器地址栏的 IP 或域名 
const backendPort = import.meta.env.VITE_BACKEND_PORT;
const baseURL = `${window.location.protocol}//${window.location.hostname}:${backendPort}/api`;
 
const fetchDevices = async () => {
  try {
    const response = await axios.get(`${baseURL}/devices-list/`); 
    const data: GroupedDevices = response.data; 
 
    const groupedDevices: Device[] = [];
 
    for (const line in data) {
      groupedDevices.push({ 
        device_id: -1,
        name: line,
        line,
        isGroup: true,
        disabled: true,
      });
 
      data[line].forEach((device: Device) => {
        const deviceWithLine = {
          ...device,
          line,
          isGroup: false,
          disabled: false,
        };
        groupedDevices.push(deviceWithLine); 
      });
    }
 
    deviceOptions.value  = groupedDevices;
 
    // 从 IndexedDB 中读取 selectedDevices 
    const storedSelectedDevices = await getFromDB<string>('selectedDevices');
    if (storedSelectedDevices) {
      selectedDevices.value  = JSON.parse(storedSelectedDevices);
    }
  } catch (error) {
    console.error(' 获取设备数据时出错！', error);
  }
};
 
const filteredDeviceOptions = computed(() => {
  return deviceOptions.value.filter(option  => !option.isGroup); 
});
 
const handleDeviceChange = async () => {
  // 将 selectedDevices 存储到 IndexedDB 
  await saveToDB('selectedDevices', JSON.stringify(selectedDevices.value)); 
};
 
const refreshPage = () => {
  location.reload(); 
};
 
onMounted(() => {
  fetchDevices();
});
</script>

<style scoped>
.device-filter {
  margin-bottom: 20px;
}

.line-group {
  font-weight: bold;
  color: #409EFF;
  padding: 5px 0;
  display: block;
  border-bottom: 1px solid #ebeef5;
  margin-bottom: 5px;
}

.button-container {
  margin-top: 20px;
  text-align: center;
}
</style>