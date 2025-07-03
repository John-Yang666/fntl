<template>
  <div>
    <!-- 网络板状态 & 用户命令回复 -->
    <div v-if="commandReplyStatus.length" class="command-reply-block">
      <div
        v-for="(status, idx) in commandReplyStatus"
        :key="idx"
        class="status-container"
      >
        <p class="status-text-left">
          网管板状态: {{ networkBoardStatus }}
        </p>
        <p class="status-text-right">
          一方向用户操作命令: {{ status.Status1 }}； 二方向用户操作命令: {{ status.Status2 }}
        </p>
      </div>
    </div>

    <!-- 折叠开关 -->
    <el-button @click="toggleCollapse1">
      {{ isCollapsed1 ? '显示一方向信息' : '隐藏一方向信息' }}
    </el-button>
    <el-button @click="toggleCollapse2">
      {{ isCollapsed2 ? '显示二方向信息' : '隐藏二方向信息' }}
    </el-button>

    <!-- 方向一 -->
    <template v-if="!isCollapsed1">
      <div>
        <h3>一方向单板状态</h3>
        <BoardStatusComponent :boards="boards1" />
      </div>
      <el-divider />
      <div>
        <h3>一方向设备主要状态信息</h3>
        <el-button @click="showNeighbor = !showNeighbor">
          {{ showNeighbor ? '隐藏邻站信息' : '显示邻站信息' }}
        </el-button>
        <el-table :data="direction1MainStatus" border style="width:100%">
          <CustomTableColumn prop="Status1"  label="站间A通道" />
          <CustomTableColumn prop="Status2"  label="站间B通道" />
          <CustomTableColumn prop="Status3"  label="CPU板A通信" />
          <CustomTableColumn prop="Status4"  label="CPU板B通信" />
          <CustomTableColumn prop="Status5"  label="QHJ" />
          <CustomTableColumn prop="Status52" label="电缆状态" />
          <CustomTableColumn prop="Status6"  label="切换模式" />
          <template v-if="showNeighbor">
            <CustomTableColumn prop="Status7"  label="邻站QHJ" />
            <CustomTableColumn prop="Status72" label="邻站电缆状态" />
            <CustomTableColumn prop="Status8"  label="邻站切换模式" />
          </template>
        </el-table>

        <h3>一方向动作继电器状态信息</h3>
        <h4>A系</h4>
        <el-table :data="direction1RelayStatusA" border style="width:100%">
          <CustomTableColumn prop="Status1" label="本站ZDJ" />
          <CustomTableColumn prop="Status2" label="本站FDJ" />
          <CustomTableColumn prop="Status3" label="本站ZXJ" />
          <CustomTableColumn prop="Status4" label="本站FXJ" />
          <template v-if="showNeighbor">
            <CustomTableColumn prop="Status5" label="邻站ZDJ" />
            <CustomTableColumn prop="Status6" label="邻站FDJ" />
            <CustomTableColumn prop="Status7" label="邻站ZXJ" />
            <CustomTableColumn prop="Status8" label="邻站FXJ" />
          </template>
        </el-table>
        <h4>B系</h4>
        <el-table :data="direction1RelayStatusB" border style="width:100%">
          <CustomTableColumn prop="Status1" label="本站ZDJ" />
          <CustomTableColumn prop="Status2" label="本站FDJ" />
          <CustomTableColumn prop="Status3" label="本站ZXJ" />
          <CustomTableColumn prop="Status4" label="本站FXJ" />
          <template v-if="showNeighbor">
            <CustomTableColumn prop="Status5" label="邻站ZDJ" />
            <CustomTableColumn prop="Status6" label="邻站FDJ" />
            <CustomTableColumn prop="Status7" label="邻站ZXJ" />
            <CustomTableColumn prop="Status8" label="邻站FXJ" />
          </template>
        </el-table>
      </div>
      <el-divider />
    </template>

    <!-- 方向二 -->
    <template v-if="!isCollapsed2">
      <div>
        <h3>二方向单板状态</h3>
        <BoardStatusComponent :boards="boards2" />
      </div>
      <el-divider />
      <div>
        <h3>二方向设备主要状态信息</h3>
        <el-button @click="showNeighbor = !showNeighbor">
          {{ showNeighbor ? '隐藏邻站信息' : '显示邻站信息' }}
        </el-button>
        <el-table :data="direction2MainStatus" border style="width:100%">
          <CustomTableColumn prop="Status1"  label="站间A通道" />
          <CustomTableColumn prop="Status2"  label="站间B通道" />
          <CustomTableColumn prop="Status3"  label="CPU板A通信" />
          <CustomTableColumn prop="Status4"  label="CPU板B通信" />
          <CustomTableColumn prop="Status5"  label="QHJ" />
          <CustomTableColumn prop="Status52" label="电缆状态" />
          <CustomTableColumn prop="Status6"  label="切换模式" />
          <template v-if="showNeighbor">
            <CustomTableColumn prop="Status7"  label="邻站QHJ" />
            <CustomTableColumn prop="Status72" label="邻站电缆状态" />
            <CustomTableColumn prop="Status8"  label="邻站切换模式" />
          </template>
        </el-table>

        <h3>二方向动作继电器状态信息</h3>
        <h4>A系</h4>
        <el-table :data="direction2RelayStatusA" border style="width:100%">
          <CustomTableColumn prop="Status1" label="本站ZDJ" />
          <CustomTableColumn prop="Status2" label="本站FDJ" />
          <CustomTableColumn prop="Status3" label="本站ZXJ" />
          <CustomTableColumn prop="Status4" label="本站FXJ" />
          <template v-if="showNeighbor">
            <CustomTableColumn prop="Status5" label="邻站ZDJ" />
            <CustomTableColumn prop="Status6" label="邻站FDJ" />
            <CustomTableColumn prop="Status7" label="邻站ZXJ" />
            <CustomTableColumn prop="Status8" label="邻站FXJ" />
          </template>
        </el-table>
        <h4>B系</h4>
        <el-table :data="direction2RelayStatusB" border style="width:100%">
          <CustomTableColumn prop="Status1" label="本站ZDJ" />
          <CustomTableColumn prop="Status2" label="本站FDJ" />
          <CustomTableColumn prop="Status3" label="本站ZXJ" />
          <CustomTableColumn prop="Status4" label="本站FXJ" />
          <template v-if="showNeighbor">
            <CustomTableColumn prop="Status5" label="邻站ZDJ" />
            <CustomTableColumn prop="Status6" label="邻站FDJ" />
            <CustomTableColumn prop="Status7" label="邻站ZXJ" />
            <CustomTableColumn prop="Status8" label="邻站FXJ" />
          </template>
        </el-table>
      </div>
    </template>

    <!-- 错误提示 -->
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
      class="mt-2"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue';
import { useRoute } from 'vue-router';
import axios from 'axios';
import { parseSwitchStatus } from '@/utils/statusParser';
import type { Board, DeviceStatus, RelayStatus } from '@/utils/types';
import BoardStatusComponent from './BoardStatusComponent.vue';
import CustomTableColumn from './CustomTableColumn.vue';

/* ---------------- 参数 & 路由 ---------------- */
const backendPort = import.meta.env.VITE_BACKEND_PORT;
const baseURL     = `${window.location.protocol}//${window.location.hostname}:${backendPort}/api`;
const route       = useRoute();
const device_id   = ref<number>(
  parseInt(
    Array.isArray(route.params.index)
      ? route.params.index[0]
      : (route.params.index as string),
    10
  )
);

/* ---------------- 折叠 ---------------- */
const isCollapsed1 = ref(false);
const isCollapsed2 = ref(false);
const showNeighbor = ref(true);
const getKey = (id: number|null, s: string) => `isCollapsed_${id}_${s}`;
const toggleCollapse1 = () => {
  isCollapsed1.value = !isCollapsed1.value;
  localStorage.setItem(getKey(device_id.value, '1'), JSON.stringify(isCollapsed1.value));
};
const toggleCollapse2 = () => {
  isCollapsed2.value = !isCollapsed2.value;
  localStorage.setItem(getKey(device_id.value, '2'), JSON.stringify(isCollapsed2.value));
};
const restoreCollapse = () => {
  if (device_id.value !== null) {
    isCollapsed1.value = JSON.parse(localStorage.getItem(getKey(device_id.value, '1'))||'false');
    isCollapsed2.value = JSON.parse(localStorage.getItem(getKey(device_id.value, '2'))||'false');
  }
};

/* ---------------- 响应式数据 ---------------- */
const boards1                = ref<Board[]>([]);
const boards2                = ref<Board[]>([]);
const direction1MainStatus   = ref<DeviceStatus[]>([]);
const direction1RelayStatusA = ref<RelayStatus[]>([]);
const direction1RelayStatusB = ref<RelayStatus[]>([]);
const direction2MainStatus   = ref<DeviceStatus[]>([]);
const direction2RelayStatusA = ref<RelayStatus[]>([]);
const direction2RelayStatusB = ref<RelayStatus[]>([]);
const error                  = ref<string|null>(null);

// 命令回复 & 网络板状态
const commandReplyStatus = ref([{ Status1: 'null', Status2: 'null' }]);
const networkBoardStatus = ref<'正常'|'离线'>('正常');

/* ---------- 清空所有状态 ---------- */
function clearAllStatuses() {
  const empty = parseSwitchStatus('');
  boards1.value                = empty.boards1;
  boards2.value                = empty.boards2;
  direction1MainStatus.value   = empty.direction1MainStatus;
  direction1RelayStatusA.value = empty.direction1RelayStatusA;
  direction1RelayStatusB.value = empty.direction1RelayStatusB;
  direction2MainStatus.value   = empty.direction2MainStatus;
  direction2RelayStatusA.value = empty.direction2RelayStatusA;
  direction2RelayStatusB.value = empty.direction2RelayStatusB;

  commandReplyStatus.value = [{ Status1: 'null', Status2: 'null' }];
  networkBoardStatus.value = '正常';
}

/* ---------- 位 & 字节 辅助 ---------- */
function getChar(bin: string, charIndex: number): string|null {
  const start = (charIndex - 4) * 8;
  return bin && start >= 0 && start + 8 <= bin.length
    ? bin.slice(start, start + 8)
    : null;
}
function getBitValueFromChar(byte: string, bitIndex: number): string {
  return byte[7 - bitIndex] ?? '0';
}

/* ---------------- 轮询获取并解析 ---------------- */
const fetchSwitchStatus = async () => {
  // 每次开始前清空
  //clearAllStatuses();
  error.value = null;

  try {
    const { data } = await axios.get(`${baseURL}/switch-status/${device_id.value}/`);
    const bin = Array.from(Uint8Array.from(atob(data.switch_status), c => c.charCodeAt(0)))
      .map(b => b.toString(2).padStart(8,'0')).join('');

    // 解析主状态
    const parsed = parseSwitchStatus(bin);
    boards1.value                = parsed.boards1;
    boards2.value                = parsed.boards2;
    direction1MainStatus.value   = parsed.direction1MainStatus;
    direction1RelayStatusA.value = parsed.direction1RelayStatusA;
    direction1RelayStatusB.value = parsed.direction1RelayStatusB;
    direction2MainStatus.value   = parsed.direction2MainStatus;
    direction2RelayStatusA.value = parsed.direction2RelayStatusA;
    direction2RelayStatusB.value = parsed.direction2RelayStatusB;

    // 解析命令回复：字节7 bits6/5 → 一方向
    const c7  = getChar(bin, 7);
    const c11 = getChar(bin,11);
    if (c7) {
      const m1 = getBitValueFromChar(c7,6) + getBitValueFromChar(c7,5);
      commandReplyStatus.value[0].Status1 = {
        '00':'无效','01':'强制电缆','10':'自动','11':'强制光缆'
      }[m1] ?? 'null';
    }
    if (c11) {
      const m2 = getBitValueFromChar(c11,6) + getBitValueFromChar(c11,5);
      commandReplyStatus.value[0].Status2 = {
        '00':'无效','01':'强制电缆','10':'自动','11':'强制光缆'
      }[m2] ?? 'null';
    }

    networkBoardStatus.value = '正常';
  } catch (e) {
    console.error('Error fetching switch status', e);
    error.value = '未获取设备状态';
    // 保持全 null
    clearAllStatuses();
    networkBoardStatus.value = '离线';
  }
};

/* ---------------- 生命周期 ---------------- */
let timer: ReturnType<typeof setInterval>;
onMounted(() => {
  restoreCollapse();
  clearAllStatuses();
  fetchSwitchStatus();
  timer = setInterval(fetchSwitchStatus, 1000);
});
onUnmounted(() => {
  clearInterval(timer);
});

/* ---------------- 路由变化 ---------------- */
watch(() => route.params.index, val => {
  device_id.value = parseInt(Array.isArray(val)?val[0]:(val as string), 10);
  restoreCollapse();
  clearAllStatuses();
  fetchSwitchStatus();
});
</script>

<style scoped>
.mt-2 { margin-top: 16px; }

.status-container {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
}
.status-text-left  { flex: 1; text-align: left; }
.status-text-right { flex: 2; text-align: right; }
</style>
