<template>
  <div class="sy-detail-root">
    <!-- 系统状态 + 各方向继电器 / 状态（A1 解析结果） -->
    <section class="card">
      <div v-if="parsedSwitch">
        <!-- 一方向（d1） -->
        <h4 class="sub-title">一方向</h4>

        <!-- 一方向切换状态（仅无三方向时显示） -->
        <div v-if="d3Mode === 'cable'" class="switch-status">
          <strong>切换状态：</strong>
          <span :class="switchPillClass(parsedSwitch.dir3.zxj)">
            {{ parsedSwitch.dir3.zxj ? '光缆' : '电缆' }}
          </span>
        </div>

        <table class="direction-table">
          <thead>
            <tr>
              <th>ZXJ</th>
              <th>FXJ</th>
              <th>ZDJ</th>
              <th>FDJ</th>
              <th>A通道</th>
              <th>B通道</th>
              <th>使用</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><span :class="relayPillClass(parsedSwitch.dir1.zxj)">{{ relayText(parsedSwitch.dir1.zxj) }}</span></td>
              <td><span :class="relayPillClass(parsedSwitch.dir1.fxj)">{{ relayText(parsedSwitch.dir1.fxj) }}</span></td>
              <td><span :class="relayPillClass(parsedSwitch.dir1.zdj)">{{ relayText(parsedSwitch.dir1.zdj) }}</span></td>
              <td><span :class="relayPillClass(parsedSwitch.dir1.fdj)">{{ relayText(parsedSwitch.dir1.fdj) }}</span></td>

              <!-- ★ 按方向：使用=否 => A/B 固定显示“无” -->
              <td>
                <span :class="channelClass(parsedSwitch.dir1.ia, parsedSwitch.dir1.used)">
                  {{ channelText(parsedSwitch.dir1.ia, parsedSwitch.dir1.used) }}
                </span>
              </td>
              <td>
                <span :class="channelClass(parsedSwitch.dir1.ib, parsedSwitch.dir1.used)">
                  {{ channelText(parsedSwitch.dir1.ib, parsedSwitch.dir1.used) }}
                </span>
              </td>

              <td><span :class="pillClass(parsedSwitch.dir1.used)">{{ yesNo(parsedSwitch.dir1.used) }}</span></td>
            </tr>
          </tbody>
        </table>

        <!-- 二方向（d2） -->
        <h4 class="sub-title">二方向</h4>

        <!-- 二方向切换状态（仅无三方向时显示） -->
        <div v-if="d3Mode === 'cable'" class="switch-status">
          <strong>切换状态：</strong>
          <span :class="switchPillClass(parsedSwitch.dir3.fxj)">
            {{ parsedSwitch.dir3.fxj ? '光缆' : '电缆' }}
          </span>
        </div>

        <table class="direction-table">
          <thead>
            <tr>
              <th>ZXJ</th>
              <th>FXJ</th>
              <th>ZDJ</th>
              <th>FDJ</th>
              <th>A通道</th>
              <th>B通道</th>
              <th>使用</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><span :class="relayPillClass(parsedSwitch.dir2.zxj)">{{ relayText(parsedSwitch.dir2.zxj) }}</span></td>
              <td><span :class="relayPillClass(parsedSwitch.dir2.fxj)">{{ relayText(parsedSwitch.dir2.fxj) }}</span></td>
              <td><span :class="relayPillClass(parsedSwitch.dir2.zdj)">{{ relayText(parsedSwitch.dir2.zdj) }}</span></td>
              <td><span :class="relayPillClass(parsedSwitch.dir2.fdj)">{{ relayText(parsedSwitch.dir2.fdj) }}</span></td>

              <!-- ★ 按方向：使用=否 => A/B 固定显示“无” -->
              <td>
                <span :class="channelClass(parsedSwitch.dir2.ia, parsedSwitch.dir2.used)">
                  {{ channelText(parsedSwitch.dir2.ia, parsedSwitch.dir2.used) }}
                </span>
              </td>
              <td>
                <span :class="channelClass(parsedSwitch.dir2.ib, parsedSwitch.dir2.used)">
                  {{ channelText(parsedSwitch.dir2.ib, parsedSwitch.dir2.used) }}
                </span>
              </td>

              <td><span :class="pillClass(parsedSwitch.dir2.used)">{{ yesNo(parsedSwitch.dir2.used) }}</span></td>
            </tr>
          </tbody>
        </table>

        <!-- 三方向 或 电缆测试（d3） -->
        <h4 class="sub-title">
          {{ d3Mode === 'dir3' ? '三方向' : '电缆测试相关信息' }}
        </h4>

        <table class="direction-table">
          <thead>
            <tr v-if="d3Mode === 'cable'">
              <th>1QHJ采集</th>
              <th>2QHJ采集</th>
              <th>1QHJ驱动</th>
              <th>2QHJ驱动</th>
              <th>上行电缆状态</th>
              <th>下行电缆状态</th>
              <th>电缆测试功能</th>
            </tr>
            <tr v-else>
              <th>ZXJ</th>
              <th>FXJ</th>
              <th>ZDJ</th>
              <th>FDJ</th>
              <th>A通道</th>
              <th>B通道</th>
              <th>使用</th>
            </tr>
          </thead>

          <tbody>
            <!-- cable 模式：电缆测试相关 -->
            <tr v-if="d3Mode === 'cable'">
              <td><span :class="relayPillClass(parsedSwitch.dir3.zxj)">{{ relayText(parsedSwitch.dir3.zxj) }}</span></td>
              <td><span :class="relayPillClass(parsedSwitch.dir3.fxj)">{{ relayText(parsedSwitch.dir3.fxj) }}</span></td>
              <td><span :class="relayPillClass(parsedSwitch.dir3.zdj)">{{ relayText(parsedSwitch.dir3.zdj) }}</span></td>
              <td><span :class="relayPillClass(parsedSwitch.dir3.fdj)">{{ relayText(parsedSwitch.dir3.fdj) }}</span></td>

              <td>
                <span
                  :class="cableStatusClass(!!parsedSwitch.dir3.cableUpOk, !!parsedSwitch.dir3.hasCableTest)"
                >
                  {{ cableStatusText(!!parsedSwitch.dir3.cableUpOk, !!parsedSwitch.dir3.hasCableTest) }}
                </span>
              </td>

              <td>
                <span
                  :class="cableStatusClass(!!parsedSwitch.dir3.cableDnOk, !!parsedSwitch.dir3.hasCableTest)"
                >
                  {{ cableStatusText(!!parsedSwitch.dir3.cableDnOk, !!parsedSwitch.dir3.hasCableTest) }}
                </span>
              </td>

              <td>
                <span :class="pillClass(!!parsedSwitch.dir3.hasCableTest)">
                  {{ !!parsedSwitch.dir3.hasCableTest ? '是' : '否' }}
                </span>
              </td>
            </tr>

            <!-- dir3 模式：第三方向（与 d1/d2 同结构） -->
            <tr v-else>
              <td><span :class="relayPillClass(parsedSwitch.dir3.zxj)">{{ relayText(parsedSwitch.dir3.zxj) }}</span></td>
              <td><span :class="relayPillClass(parsedSwitch.dir3.fxj)">{{ relayText(parsedSwitch.dir3.fxj) }}</span></td>
              <td><span :class="relayPillClass(parsedSwitch.dir3.zdj)">{{ relayText(parsedSwitch.dir3.zdj) }}</span></td>
              <td><span :class="relayPillClass(parsedSwitch.dir3.fdj)">{{ relayText(parsedSwitch.dir3.fdj) }}</span></td>

              <!-- ★ 按方向：使用=否 => A/B 固定显示“无” -->
              <td>
                <span :class="channelClass(!!parsedSwitch.dir3.ia, !!parsedSwitch.dir3.used)">
                  {{ channelText(!!parsedSwitch.dir3.ia, !!parsedSwitch.dir3.used) }}
                </span>
              </td>
              <td>
                <span :class="channelClass(!!parsedSwitch.dir3.ib, !!parsedSwitch.dir3.used)">
                  {{ channelText(!!parsedSwitch.dir3.ib, !!parsedSwitch.dir3.used) }}
                </span>
              </td>

              <td><span :class="pillClass(!!parsedSwitch.dir3.used)">{{ yesNo(!!parsedSwitch.dir3.used) }}</span></td>
            </tr>
          </tbody>
        </table>

        <!-- 系统状态（d4） -->
        <h4 class="sub-title">系统状态</h4>
        <table class="status-table">
          <thead>
            <tr>
              <th>自动切换能力</th>
              <th>励磁故障</th>
              <th>BGZJ</th>
              <th>AGZJ</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><span :class="pillClass(parsedSwitch.system.autoSwitchCapable)">{{ yesNo(parsedSwitch.system.autoSwitchCapable) }}</span></td>
              <td><span :class="pillClass(parsedSwitch.system.excitationFault, true)">{{ faultOk(parsedSwitch.system.excitationFault) }}</span></td>
              <td><span :class="gzjPillClass(parsedSwitch.system.bgzj)">{{ gzjText(parsedSwitch.system.bgzj) }}</span></td>
              <td><span :class="gzjPillClass(parsedSwitch.system.agzj)">{{ gzjText(parsedSwitch.system.agzj) }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-else class="hint">暂无可解析的 A1 状态字。</div>
    </section>

    <!-- 设备基本信息 -->
    <section class="card">
      <h2 class="card-title">设备基本信息</h2>

      <div v-if="deviceBase" class="device-base">
        <div class="device-base-left">
          <div class="row"><span class="label">设备 ID：</span><span>{{ deviceBase.device_id }}</span></div>
          <div class="row"><span class="label">名称：</span><span>{{ deviceBase.name || '—' }}</span></div>
          <div class="row"><span class="label">车间：</span><span>{{ deviceBase.depot || '—' }}</span></div>
          <div class="row"><span class="label">线路：</span><span>{{ deviceBase.line || '—' }}</span></div>
          <div class="row"><span class="label">IP：</span><span>{{ deviceBase.ip_address || '—' }}</span></div>
        </div>

        <div class="device-base-right">
          <div class="row"><span class="label">一方向启用：</span><span>{{ yesNo(deviceBase.direction1_enabled) }}</span></div>
          <div class="row"><span class="label">二方向启用：</span><span>{{ yesNo(deviceBase.direction2_enabled) }}</span></div>
          <div class="row"><span class="label">三方向启用：</span><span>{{ yesNo(deviceBase.direction3_enabled) }}</span></div>
          <div class="row"><span class="label">自动切换能力：</span><span>{{ yesNo(deviceBase.supports_auto_switch) }}</span></div>
        </div>
      </div>

      <div v-else class="hint">正在加载设备信息…</div>
    </section>

    <!-- 最新 A1 状态字快照（保留） -->
    <section class="cards-row">
      <div class="card flex-1">
        <h3 class="card-title">最新状态字快照（A1）</h3>

        <div v-if="latestSwitch">
          <div class="row"><span class="label">时间：</span><span>{{ latestSwitch.timestamp }}</span></div>
          <div class="row"><span class="label">版本：</span><span>{{ latestSwitch.version }}</span></div>
          <div class="row"><span class="label">HEX：</span><span class="mono">{{ latestSwitch.hex }}</span></div>

          <p class="secondary-text" v-if="parsedSwitch">
            d3 当前含义：
            <span v-if="d3Mode === 'dir3'">
              第三方向 ZXJ / FXJ / ZDJ / FDJ ＋ A/B 通道/使用
            </span>
            <span v-else-if="d3Mode === 'cable'">
              无第三方向；d3 仅表示 1/2QHJ 采集 / 驱动、电缆状态及电缆测试功能
            </span>
            <span v-else>（等待设备信息加载中…）</span>
          </p>
        </div>

        <div v-else class="hint">暂无 A1 状态字记录</div>
      </div>
    </section>

    <!-- 错误提示 -->
    <el-alert v-if="error" :title="error" type="error" show-icon class="mt-2" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue';
import { useRoute } from 'vue-router';
import { useUserStore } from '@/stores/userStore';
import { getSystemFromRoute } from '@/utils/systems';

/* ---------------- 路由 & 基础 URL ---------------- */
const route = useRoute();
const userStore = useUserStore();

const deviceId = ref<number>(
  parseInt(Array.isArray(route.params.index) ? route.params.index[0] : (route.params.index as string), 10)
);

/* 定时刷新句柄 */
let refreshTimer: number | null = null;

/* ---------------- 数据模型 ---------------- */
interface LatestSwitch {
  timestamp: string;
  version: string;
  hex: string;
}

interface DeviceBase {
  device_id: number;
  name: string;
  depot: string;
  line: string;
  ip_address: string;
  direction1_enabled: boolean;
  direction2_enabled: boolean;
  direction3_enabled: boolean;
  supports_auto_switch: boolean;
}

/* switch 解析后的结构 */
interface DirStatus {
  zxj: boolean;
  fxj: boolean;
  zdj: boolean;
  fdj: boolean;
  ia: boolean;
  ib: boolean;
  used: boolean;
}

/**
 * d3 有两种含义：
 * - dir3 模式：第三方向（与 d1/d2 同结构）
 * - cable 模式：电缆测试相关（1/2QHJ采集/驱动 + 电缆状态 + 测试功能位）
 */
interface Dir3Status {
  zxj: boolean;
  fxj: boolean;
  zdj: boolean;
  fdj: boolean;

  // dir3 模式才有
  ia?: boolean;
  ib?: boolean;
  used?: boolean;

  // cable 模式才有
  cableUpOk?: boolean;
  cableDnOk?: boolean;
  hasCableTest?: boolean;
}

interface SystemStatus {
  autoSwitchCapable: boolean;
  excitationFault: boolean;
  bgzj: boolean;
  agzj: boolean;
}

interface ParsedSwitch {
  dir1: DirStatus;
  dir2: DirStatus;
  dir3: Dir3Status;
  system: SystemStatus;
}

/* ---------------- 状态 ---------------- */
const deviceBase = ref<DeviceBase | null>(null);
const latestSwitch = ref<LatestSwitch | null>(null);
const error = ref<string | null>(null);

/* ---------------- 工具函数 ---------------- */
function switchPillClass(isOptical: boolean): string {
  return ['pill', isOptical ? 'pill-good' : 'pill-bad'].join(' ');
}

function hexToBytes(hex: string | null | undefined): number[] {
  if (!hex) return [];
  const clean = hex.replace(/\s+/g, '');
  const bytes: number[] = [];
  for (let i = 0; i < clean.length; i += 2) {
    const b = parseInt(clean.substring(i, i + 2), 16);
    if (!Number.isNaN(b)) bytes.push(b);
  }
  return bytes;
}

function bit(v: number, pos: number): number {
  return (v >> pos) & 0x01;
}

function parseSySwitch(
  hex: string | null | undefined,
  mode: 'dir3' | 'cable' | 'unknown'
): ParsedSwitch | null {
  const bytes = hexToBytes(hex);
  if (bytes.length === 0) return null;

  const d1 = bytes[0] ?? 0;
  const d2 = bytes[1] ?? 0;
  const d3 = bytes[2] ?? 0;
  const d4 = bytes[3] ?? 0;

  const dir1: DirStatus = {
    zxj: !!bit(d1, 7),
    fxj: !!bit(d1, 6),
    zdj: !!bit(d1, 5),
    fdj: !!bit(d1, 4),
    ia: !!bit(d1, 3),
    ib: !!bit(d1, 2),
    used: !!bit(d1, 1),
  };

  const dir2: DirStatus = {
    zxj: !!bit(d2, 7),
    fxj: !!bit(d2, 6),
    zdj: !!bit(d2, 5),
    fdj: !!bit(d2, 4),
    ia: !!bit(d2, 3),
    ib: !!bit(d2, 2),
    used: !!bit(d2, 1),
  };

  const dir3: Dir3Status =
    mode === 'dir3'
      ? {
          // 第三方向（同 d1/d2 位意义）
          zxj: !!bit(d3, 7),
          fxj: !!bit(d3, 6),
          zdj: !!bit(d3, 5),
          fdj: !!bit(d3, 4),
          ia: !!bit(d3, 3),
          ib: !!bit(d3, 2),
          used: !!bit(d3, 1),
        }
      : {
          // 电缆测试相关（1/2QHJ采集/驱动 + 电缆状态 + 电缆测试功能）
          zxj: !!bit(d3, 7), // 1QHJ采集
          fxj: !!bit(d3, 6), // 2QHJ采集
          zdj: !!bit(d3, 5), // 1QHJ驱动
          fdj: !!bit(d3, 4), // 2QHJ驱动
          cableUpOk: !!bit(d3, 3),
          cableDnOk: !!bit(d3, 2),
          hasCableTest: !!bit(d3, 1),
        };

  const system: SystemStatus = {
    autoSwitchCapable: !!bit(d4, 7),
    excitationFault: !!bit(d4, 5),
    bgzj: !!bit(d4, 1),
    agzj: !!bit(d4, 0),
  };

  return { dir1, dir2, dir3, system };
}

/* ---------------- 计算属性 ---------------- */
const d3Mode = computed<'dir3' | 'cable' | 'unknown'>(() => {
  if (!deviceBase.value) return 'unknown';
  return deviceBase.value.direction3_enabled ? 'dir3' : 'cable';
});

const parsedSwitch = computed<ParsedSwitch | null>(() => {
  if (!latestSwitch.value) return null;
  if (d3Mode.value === 'unknown') return null;
  return parseSySwitch(latestSwitch.value.hex, d3Mode.value);
});

/* ---------------- UI 辅助显示 ---------------- */
function yesNo(v: boolean | undefined | null): string {
  return v ? '是' : '否';
}
function onOff(v: boolean): string {
  return v ? '1' : '0';
}
function relayText(v: boolean): string {
  return v ? '⬆' : '⬇';
}
function okNg(v: boolean): string {
  return v ? '正常' : '异常';
}
function faultOk(v: boolean): string {
  return v ? '有故障' : '正常';
}

function pillClass(v: boolean, isFault = false): string {
  return ['pill', v ? (isFault ? 'pill-bad' : 'pill-on') : (isFault ? 'pill-good' : 'pill-off')].join(' ');
}
function relayPillClass(v: boolean): string {
  return ['pill', v ? 'pill-relay-on' : 'pill-relay-off'].join(' ');
}
function okPillClass(ok: boolean): string {
  return ['pill', ok ? 'pill-good' : 'pill-bad'].join(' ');
}

function gzjText(v: boolean): string {
  return v ? '⬆' : '⬇';
}

/** 吸起：沿用蓝色；落下：红色 */
function gzjPillClass(v: boolean): string {
  return ['pill', v ? 'pill-good' : 'pill-bad'].join(' ');
}

/**
 * ★ 需求：按方向“使用”判断
 * - used=true  => 显示 正常/异常
 * - used=false => 固定显示 无（灰色）
 */
function channelText(ok: boolean, used: boolean): string {
  return used ? okNg(ok) : '无';
}
function channelClass(ok: boolean, used: boolean): string {
  return used ? okPillClass(ok) : 'pill pill-off';
}

function cableStatusText(ok: boolean, hasCableTest: boolean): string {
  return hasCableTest ? okNg(ok) : '无';
}

function cableStatusClass(ok: boolean, hasCableTest: boolean): string {
  return hasCableTest ? okPillClass(ok) : 'pill pill-off';
}

/* ---------------- 请求：设备基础信息（老接口）---------------- */
async function fetchDeviceBase() {
  try {
    error.value = null;
    const data = await userStore.requestWithAuth<DeviceBase>(getSystemFromRoute(route.params.system), {
      method: 'get',
      url: `/device-detail/${deviceId.value}/`,
    });
    deviceBase.value = data;
  } catch (e) {
    console.error('fetchDeviceBase error', e);
    error.value = '加载设备信息失败';
    deviceBase.value = null;
  }
}

/* ---------------- 请求：最新 A1（新接口，从 cache 读）---------------- */
async function fetchDeviceSwitchData() {
  try {
    error.value = null;

    const data = await userStore.requestWithAuth<any>(getSystemFromRoute(route.params.system), {
      method: 'get',
      url: `/device_switch_data/${deviceId.value}/`,
    });
    const sw: LatestSwitch | null = (data?.latest_switch ?? data) || null;

    if (sw && typeof sw.hex === 'string') {
      latestSwitch.value = sw;
    } else {
      latestSwitch.value = null;
    }
  } catch (e) {
    console.error('fetchDeviceSwitchData error', e);
    error.value = '加载设备状态失败';
    latestSwitch.value = null;
  }
}

/* ---------------- 生命周期 & 路由监听 ---------------- */
onMounted(() => {
  fetchDeviceBase();
  fetchDeviceSwitchData();
  refreshTimer = window.setInterval(() => {
    fetchDeviceSwitchData();
  }, 1000);
});

onUnmounted(() => {
  if (refreshTimer !== null) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }
});

watch(
  () => route.params.index,
  (val) => {
    deviceId.value = parseInt(Array.isArray(val) ? val[0] : (val as string), 10);
    fetchDeviceBase();
    fetchDeviceSwitchData();
  }
);
</script>

<style scoped>
.sy-detail-root {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 通用卡片 */
.card {
  background: #fff;
  border-radius: 10px;
  padding: 10px 0px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}

.cards-row {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}

.flex-1 {
  flex: 1 1 260px;
}

.card-title {
  font-size: 18px;
  font-weight: 600;
  margin: 0 0 8px;
}

.sub-title {
  font-size: 16px;
  font-weight: 600;
  margin: 16px 0 8px;
}

/* 设备信息区域 */
.device-base {
  display: flex;
  flex-wrap: wrap;
  gap: 24px;
  margin-top: 8px;
}

.device-base-left,
.device-base-right {
  min-width: 260px;
}

.row {
  margin: 4px 0;
}

.label {
  display: inline-block;
  min-width: 110px;
  color: #666;
}

.mono {
  font-family: Menlo, SFMono-Regular, Consolas, 'Liberation Mono', monospace;
}

.secondary-text {
  margin-top: 6px;
  font-size: 13px;
  color: #888;
}

.hint {
  color: #999;
  font-size: 13px;
}

/* 表格样式 */
.status-table,
.direction-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 4px;
  font-size: 13px;
}

.status-table th,
.status-table td,
.direction-table th,
.direction-table td {
  border: 1.5px solid #c0c4cc;
  padding: 6px 8px;
  text-align: center;
}

/* 彩色小胶囊基础样式 */
.pill {
  display: inline-flex;
  align-items: center;       /* 垂直居中 */
  justify-content: center;   /* 水平居中 */
  min-width: 40px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  line-height: 1.3;
}

/* 普通 on/off */
.pill-on {
  background-color: #ecfdf3;
  color: #137333;
  border: 1px solid #b7ebc6;
}

.pill-off {
  background-color: #f5f7fa;
  color: #606266;
  border: 1px solid #dcdfe6;
}

/* 正常=绿、异常/故障=红 */
.pill-good {
  background-color: #ecfdf3;
  color: #137333;
  border: 1px solid #b7ebc6;
}

.pill-bad {
  background-color: #fdecec;
  color: #d93025;
  border: 1px solid #f5c6cb;
}

/* 继电器：吸起=蓝，落下=灰 */
.pill-relay-on {
  background-color: #e3f2fd;
  color: #1565c0;
  border: 1px solid #90caf9;
}

.pill-relay-off {
  background-color: #f5f7fa;
  color: #606266;
  border: 1px solid #dcdfe6;
}

.mt-2 {
  margin-top: 16px;
}

.switch-status {
  margin: 6px 0 12px 0;
  font-size: 13px;
}
</style>
