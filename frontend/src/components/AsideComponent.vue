<template>
  <el-menu
    class="el-menu-vertical-demo custom-el-menu"
    :default-active="activedevice_id"
    @open="handleOpen"
    @close="handleClose">
    <el-sub-menu v-for="(stations, line) in groupedDevices" :key="line" :index="line.toString()">
      <template #title >
        <p class = "el-sub-menu__title">{{ line }}</p>
      </template>
      <el-menu-item 
        v-for="station in stations" 
        :key="station.device_id" 
        :index="station.device_id.toString()"
        @click="navigateToDevice(station)">
        {{ station.name }}
      </el-menu-item>
    </el-sub-menu>
  </el-menu>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import axios from 'axios';

interface Device {
  device_id: number;
  name: string;
  ip_address: string;
}

interface GroupedDevices {
  [line: string]: Device[];
}

const groupedDevices = ref<GroupedDevices>({});
const activedevice_id = ref<string | undefined>(undefined);

const router = useRouter();
const route = useRoute();
const emit = defineEmits(['device-selected']);

// 动态获取当前浏览器地址栏的 IP 或域名
const backendPort = import.meta.env.VITE_BACKEND_PORT;
const baseURL = `${window.location.protocol}//${window.location.hostname}:${backendPort}/api`;

const fetchDevices = async () => {
  try {
    const response = await axios.get(`${baseURL}/devices-list/`);
    groupedDevices.value = response.data;
    setActiveDeviceFromRoute();
  } catch (error) {
    console.error("There was an error fetching the device data!", error);
  }
};

const setActiveDeviceFromRoute = () => {
  const device_id = route.params.index as string;
  if (device_id) {
    activedevice_id.value = device_id;
    // Find the device name based on the device_id and emit it
    for (const line in groupedDevices.value) {
      const station = groupedDevices.value[line].find(station => station.device_id.toString() === device_id);
      if (station) {
        emit('device-selected', station.name);
        break;
      }
    }
  }
};

onMounted(() => {
  fetchDevices();
});

// 监听路由变化并更新activedevice_id
watch(route, () => {
  setActiveDeviceFromRoute();
});

const handleOpen = (key: string, keyPath: string[]) => {
  console.log(key, keyPath);
};

const handleClose = (key: string, keyPath: string[]) => {
  console.log(key, keyPath);
};

const navigateToDevice = (station: Device) => {
  router.push({ path: `/device/${station.device_id}` });
  emit('device-selected', station.name);
};
</script>

<style scoped>
.custom-el-menu .el-menu-item {
  height: 30px !important; /* 调整高度 */
  line-height: 20px !important; /* 调整行高 */
  font-size: 16px; /* 调整字体大小 */
}

.el-sub-menu__title {
  height: 30px !important; /* 调整子菜单标题高度 */
  font-size: 17px; /* 调整字体大小 */
  font-weight: bold;
  padding-left: 10px !important;
}
</style>