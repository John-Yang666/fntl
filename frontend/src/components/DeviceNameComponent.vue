<template>
  <h2>当前设备: {{ currentDeviceName }}</h2>

  <!-- 显示备注信息 -->
  <div v-if="remark !== null">
    <p v-html="remark.replace(/\n/g, '<br />')"></p>
  </div>
  <div v-else>
    <p>
      一方向邻站设备: {{ direction1NeighborName || '无' }}, 方向{{ direction1NeighborDirection || '无' }}<br>
      二方向邻站设备: {{ direction2NeighborName || '无' }}, 方向{{ direction2NeighborDirection || '无' }}
    </p>
  </div>

</template>

<script lang="ts" setup>
import { ref, onMounted, watch } from 'vue';
import { useRoute } from 'vue-router';
import { useUserStore } from '@/stores/userStore';
import { getSystemFromRoute } from '@/utils/systems';

const emit = defineEmits<{
  (e: 'loaded', payload: { name: string; isBackup: boolean; deviceId: number | null }): void
}>();

const route = useRoute();
const userStore = useUserStore();
const currentDeviceName = ref<string>(''); // 当前设备名称
const direction1NeighborName = ref<string | null>(null); // 一方向邻站设备名称
const direction1NeighborDirection = ref<string | null>(null); // 一方向邻站设备方向
const direction2NeighborName = ref<string | null>(null); // 二方向邻站设备名称
const direction2NeighborDirection = ref<string | null>(null); // 二方向邻站设备方向
const device_id = ref<number | null>(null); // 当前设备 ID
const currentUrl = ref<string>(''); // 当前 URL

// 获取设备详情
const remark = ref<string | null>(null); // 设备备注

const fetchDeviceDetails = async (id: number) => {
  if (isNaN(id)) {
    console.error('Invalid device ID');
    emit('loaded', { name: '', isBackup: false, deviceId: null });
    return;
  }

  try {
    const system = getSystemFromRoute(route.params.system);
    const device = await userStore.requestWithAuth<Record<string, any>>(system, {
      method: 'get',
      url: `/devices/retrieve_with_stations/?device_id=${id}`,
    }) || {};

    currentDeviceName.value = device.name || '未知设备';
    direction1NeighborName.value = device.direction1_neighbor_name || null;
    direction1NeighborDirection.value = device.direction1_neighbor_direction || null;
    direction2NeighborName.value = device.direction2_neighbor_name || null;
    direction2NeighborDirection.value = device.direction2_neighbor_direction || null;
    remark.value = device.remark || null; // 获取备注字段
    emit('loaded', {
      name: currentDeviceName.value,
      isBackup: currentDeviceName.value.includes('备机'),
      deviceId: id,
    });
  } catch (error) {
    console.error('Failed to fetch device details:', error);
    currentDeviceName.value = '';
    direction1NeighborName.value = null;
    direction1NeighborDirection.value = null;
    direction2NeighborName.value = null;
    direction2NeighborDirection.value = null;
    remark.value = null; // 重置备注
    emit('loaded', { name: '', isBackup: false, deviceId: id });
  }
};


// 更新设备详情
const updateDeviceDetails = () => {
  const idStr = route.params.index?.toString(); // 确保 `index` 转为字符串
  const id = idStr ? parseInt(idStr, 10) : NaN;
  if (!isNaN(id)) {
    device_id.value = id;
    fetchDeviceDetails(id);
  } else {
    console.error('Invalid device ID');
    device_id.value = null; // 重置为 null
    emit('loaded', { name: '', isBackup: false, deviceId: null });
  }
};

// 生命周期钩子和监听器
const handleDeviceUpdate = () => {
  currentUrl.value = window.location.href; // 更新当前 URL
  updateDeviceDetails();
};

onMounted(() => {
  handleDeviceUpdate();
});

watch(() => [route.params.system, route.params.index], handleDeviceUpdate);
</script>

<style scoped>
/* 必要的样式 */
</style>
