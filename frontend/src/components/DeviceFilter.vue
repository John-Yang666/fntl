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
            <span class="transfer-option-row">
              <span class="option-text">
                <span class="line-group">{{ option.line }}</span>
                <span class="device-name">{{ option.name }}</span>
              </span>
              <span
                v-if="isSelected(option.key)"
                class="pin-checkbox-inline"
                @click.stop
                @mousedown.stop
              >
                <label class="pin-toggle" @click.stop @mousedown.stop>
                  <input
                    class="pin-toggle-input"
                    type="checkbox"
                    :checked="isPinned(option.key)"
                    @click.stop
                    @mousedown.stop
                    @change="(event) => handlePinnedChange(option.key, (event.target as HTMLInputElement).checked)"
                  />
                  <span class="pin-toggle-label">置顶</span>
                </label>
              </span>
            </span>
          </template>
        </el-transfer>
        <div class="transfer-tip-row">
          <div class="transfer-tip-spacer"></div>
          <div class="pin-tip">勾选“置顶”后，该设备会在拓扑图中显示在更上层。</div>
        </div>
        <div class="button-container">
          <el-button type="primary" @click="refreshPage">确认</el-button>
        </div>
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
          }>>,
        };
      }),
    );

    const successfulResponses = responses.flatMap((result, index) => {
      if (result.status === 'fulfilled') {
        return [result.value];
      }

      console.error(`获取 ${SYSTEMS[index].toUpperCase()} 设备列表失败`, result.reason);
      return [];
    });

    const mergedDevices: Device[] = [];
    successfulResponses.forEach(({ system, data }) => {
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
const isSelected = (deviceKey: string) => selectedDevices.value.includes(deviceKey);

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

.transfer-option-row {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.option-text {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.device-name {
  color: #606266;
}

.pin-checkbox-inline {
  flex: 0 0 auto;
}

.pin-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  user-select: none;
}

.pin-toggle-input {
  margin: 0;
  cursor: pointer;
}

.pin-toggle-label {
  font-size: 13px;
  color: #606266;
}

.button-container {
  margin-top: 20px;
  text-align: center;
}

.transfer-tip-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin-top: 12px;
}

.transfer-tip-spacer,
.pin-tip {
  flex: 1 1 0;
  min-width: 0;
}

.pin-tip {
  color: #606266;
  font-size: 13px;
  text-align: right;
}
</style>
