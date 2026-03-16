<template>
  <div class="device-filter">
    <el-collapse>
      <el-collapse-item title="选择需要监控的设备" name="1">
        <el-transfer
          v-model="selectedDevices"
          :data="deviceOptions"
          filterable
          filter-placeholder="搜索设备"
          :titles="['可选设备', '已选设备']"
          :props="{ key: 'key', label: 'name', disabled: 'disabled' }"
          @change="handleDeviceChange"
        >
          <template #default="{ option }">
            <span class="option-text">
              <span class="line-group">{{ option.line }}</span>
              <span class="device-name">{{ option.name }}</span>
            </span>
          </template>
        </el-transfer>
        <div class="button-container">
          <el-button type="primary" @click="refreshPage">确认</el-button>
        </div>
        <div class="pinned-panel">
          <div class="pinned-panel-title">已选设备置顶</div>
          <div v-if="selectedDeviceList.length > 0" class="pinned-device-list">
            <label
              v-for="device in selectedDeviceList"
              :key="device.key"
              class="pinned-device-item"
            >
              <el-checkbox
                :model-value="isPinned(device.key)"
                @change="(checked) => handlePinnedChange(device.key, checked)"
              />
              <span class="selected-device-name">
                {{ device.name }}
                <span class="device-system-tag" :class="`system-${device.system}`">
                  {{ device.system.toUpperCase() }}
                </span>
              </span>
            </label>
          </div>
          <div v-else class="empty-selected-devices">请先在右侧选择设备。</div>
        </div>
        <div class="pin-tip">勾选“置顶”后，该设备会在拓扑图中显示在更上层。</div>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script lang="ts" setup>
import { computed, onMounted, ref } from 'vue';
import axios from 'axios';
import {
  reconcilePinnedDeviceKeys,
  reconcileSelectedDeviceKeys,
  savePinnedDeviceKeys,
  saveSelectedDeviceKeys,
} from '@/utils/selectedDevices';
import { SYSTEMS, getApiBase, makeDeviceKey, type SystemType } from '@/utils/systems';

interface Device {
  key: string;
  system: SystemType;
  device_id: number;
  name: string;
  line: string;
  disabled?: boolean;
}

const allDevices = ref<Device[]>([]);
const selectedDevices = ref<string[]>([]);
const pinnedDevices = ref<string[]>([]);
const DEVICE_SETTINGS_CHANGED_EVENT = 'device-settings-changed';

const deviceOptions = computed(() => {
  return [...allDevices.value]
    .sort((a, b) => {
      const byLine = a.line.localeCompare(b.line, 'zh-CN');
      if (byLine !== 0) {
        return byLine;
      }
      return a.name.localeCompare(b.name, 'zh-CN');
    })
    .map((device) => ({
      ...device,
      disabled: false,
    }));
});

const selectedDeviceList = computed(() => {
  const selectedSet = new Set(selectedDevices.value);
  return allDevices.value.filter((device) => selectedSet.has(device.key));
});

const fetchDevices = async () => {
  try {
    const responses = await Promise.all(
      SYSTEMS.map(async (system) => ({
        system,
        data: (await axios.get(`${getApiBase(system)}/devices-list/`)).data as Record<string, Array<{
          device_id: number;
          name: string;
        }>>,
      })),
    );

    const mergedDevices: Device[] = [];
    responses.forEach(({ system, data }) => {
      Object.entries(data).forEach(([line, devices]) => {
        devices.forEach((device) => {
          mergedDevices.push({
            ...device,
            system,
            line,
            key: makeDeviceKey(system, device.device_id),
          });
        });
      });
    });

    allDevices.value = mergedDevices;

    selectedDevices.value = await reconcileSelectedDeviceKeys(
      mergedDevices.map((device) => device.key),
    );
    pinnedDevices.value = await reconcilePinnedDeviceKeys(selectedDevices.value);
  } catch (error) {
    console.error('获取设备数据时出错！', error);
  }
};

const handleDeviceChange = async () => {
  await saveSelectedDeviceKeys(selectedDevices.value);
  pinnedDevices.value = await reconcilePinnedDeviceKeys(selectedDevices.value);
  window.dispatchEvent(new CustomEvent(DEVICE_SETTINGS_CHANGED_EVENT));
};

const handlePinnedChange = async (deviceKey: string, checked: string | number | boolean) => {
  const nextPinnedDevices = checked
    ? Array.from(new Set([...pinnedDevices.value, deviceKey]))
    : pinnedDevices.value.filter((key) => key !== deviceKey);

  pinnedDevices.value = nextPinnedDevices.filter((key) => selectedDevices.value.includes(key));
  await savePinnedDeviceKeys(pinnedDevices.value);
  window.dispatchEvent(new CustomEvent(DEVICE_SETTINGS_CHANGED_EVENT));
};

const isPinned = (deviceKey: string) => pinnedDevices.value.includes(deviceKey);

const refreshPage = () => {
  location.reload();
};

onMounted(() => {
  fetchDevices();
});
</script>

<style scoped>
.device-filter {
  width: 100%;
  margin-bottom: 20px;
}

:deep(.el-transfer) {
  width: 100%;
  max-width: none;
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
  gap: 12px;
}

:deep(.el-transfer-panel) {
  width: auto;
  flex: 1 1 0;
  min-width: 0;
  max-width: none;
}

:deep(.el-transfer__buttons) {
  flex: 0 0 auto;
}

.line-group {
  font-weight: bold;
  color: #409EFF;
  margin-right: 8px;
}

.option-text {
  display: inline-block;
  max-width: 100%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.device-name {
  color: #606266;
}

.button-container {
  margin-top: 20px;
  text-align: center;
}

.selected-device-item {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.selected-device-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pin-tip {
  margin-top: 12px;
  color: #606266;
  font-size: 13px;
}

.pinned-panel {
  margin-top: 16px;
  padding: 14px 16px;
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  background: #fafafa;
}

.pinned-panel-title {
  margin-bottom: 12px;
  font-weight: 600;
  color: #303133;
}

.pinned-device-list {
  display: grid;
  gap: 10px;
}

.pinned-device-item {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  background: #fff;
}

.device-system-tag {
  display: inline-block;
  margin-left: 8px;
  padding: 1px 6px;
  border-radius: 999px;
  font-size: 12px;
  line-height: 18px;
}

.system-bt {
  color: #06b6d4;
  background: rgba(6, 182, 212, 0.12);
}

.system-sy {
  color: #2563eb;
  background: rgba(37, 99, 235, 0.12);
}

.empty-selected-devices {
  color: #909399;
  font-size: 13px;
}
</style>
