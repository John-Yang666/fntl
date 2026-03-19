<template>
  <el-menu
    class="el-menu-vertical-demo custom-el-menu"
    :default-active="activeDeviceKey"
    @open="handleOpen"
    @close="handleClose">
    <el-sub-menu v-for="(stations, line) in groupedDevices" :key="line" :index="line.toString()">
      <template #title >
        <p class = "el-sub-menu__title">{{ line }}</p>
      </template>
      <el-menu-item 
        v-for="station in stations" 
        :key="station.uniqueKey" 
        :index="station.uniqueKey"
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
import { SYSTEMS, getApiBase, getSystemFromRoute, makeDeviceKey, type SystemType } from '@/utils/systems';

interface Device {
  system: SystemType;
  uniqueKey: string;
  device_id: number;
  name: string;
  ip_address: string;
}

interface GroupedDevices {
  [line: string]: Device[];
}

const groupedDevices = ref<GroupedDevices>({});
const activeDeviceKey = ref<string | undefined>(undefined);

const router = useRouter();
const route = useRoute();
const emit = defineEmits(['device-selected']);

const fetchDevices = async () => {
  try {
    const responses = await Promise.allSettled(
      SYSTEMS.map(async (system) => {
        const response = await axios.get(`${getApiBase(system)}/devices-list/`);
        return {
          system,
          data: response.data as Record<string, Array<{
            device_id: number;
            name: string;
            ip_address: string;
          }>>,
        };
      }),
    );

    const mergedDevices: GroupedDevices = {};
    responses.forEach((result, index) => {
      if (result.status !== 'fulfilled') {
        console.error(`获取 ${SYSTEMS[index].toUpperCase()} 侧边栏设备列表失败`, result.reason);
        return;
      }

      const { system, data } = result.value;
      Object.entries(data).forEach(([line, stations]) => {
        if (!mergedDevices[line]) {
          mergedDevices[line] = [];
        }

        stations.forEach((station) => {
          mergedDevices[line].push({
            ...station,
            system,
            uniqueKey: makeDeviceKey(system, station.device_id),
          });
        });
      });
    });

    groupedDevices.value = mergedDevices;
    setActiveDeviceFromRoute();
  } catch (error) {
    console.error("There was an error fetching the device data!", error);
  }
};

const setActiveDeviceFromRoute = () => {
  const device_id = route.params.index as string;
  const system = getSystemFromRoute(route.params.system);
  if (device_id) {
    activeDeviceKey.value = makeDeviceKey(system, device_id);
    for (const line in groupedDevices.value) {
      const station = groupedDevices.value[line].find(
        (item) => item.system === system && item.device_id.toString() === device_id,
      );
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
  router.push({ path: `/${station.system}/device/${station.device_id}` });
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
