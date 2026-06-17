<template>
  <section class="analog-monitor">
    <header class="monitor-header">
      <div>
        <h2>闭塞电压监测图</h2>
        <p>故障分析视图，按时间对齐电压变化与继电器动作。</p>
        <div class="monitor-status-row">
          <span class="status-dot" :class="monitorConnectionState"></span>
          <span>{{ monitorConnectionLabel }}</span>
        </div>
      </div>
      <div class="summary-grid">
        <div class="summary-card">
          <span>时间窗口</span>
          <strong>{{ rangeSummary }}</strong>
        </div>
        <div class="summary-card">
          <span>最新电压</span>
          <strong>{{ latestVoltageSummary }}</strong>
        </div>
        <div class="summary-card">
          <span>动作继电器</span>
          <strong>{{ activeRelayNames.length }} 个</strong>
        </div>
        <div class="summary-card">
          <span>异常电压</span>
          <strong :class="hasAbnormalPoints ? 'is-alert' : 'is-normal'">
            {{ anomalySummary }}
          </strong>
        </div>
        <div class="summary-card">
          <span>异常电流</span>
          <strong :class="hasAbnormalCurrent ? 'is-alert' : 'is-normal'">
            {{ currentAnomalySummary }}
          </strong>
        </div>
      </div>
    </header>

    <section class="toolbar-panel">
      <div class="quick-range-row">
        <span class="section-label">快捷范围</span>
        <button
          v-for="preset in quickRanges"
          :key="preset.key"
          type="button"
          class="range-button"
          :class="{ active: activeQuickRange === preset.key }"
          @click="applyQuickRange(preset.key)"
        >
          {{ preset.label }}
        </button>
      </div>

      <div class="control-row">
        <label>
          最大加载记录数
          <select v-model.number="selectedPageSize">
            <option value="100">100</option>
            <option value="1000">1000</option>
            <option value="10000">10000（可能造成卡顿）</option>
          </select>
        </label>
        <label>
          开始时间
          <input v-model="startTime" type="datetime-local" @change="setCustomRange" />
        </label>
        <label>
          结束时间
          <input v-model="endTime" type="datetime-local" @change="setCustomRange" />
        </label>
        <label class="checkbox-label">
          <input v-model="showCurrent" type="checkbox" />
          显示电流
        </label>
        <label class="checkbox-label">
          <input v-model="showOnlyActiveRelays" type="checkbox" />
          仅显示有动作继电器
        </label>
        <button type="button" class="primary-button" @click="fetchData">刷新</button>
        <button type="button" class="ghost-button" @click="jumpToLatest">回到最新</button>
        <button type="button" class="ghost-button" @click="resetZoom">重置缩放</button>
      </div>

      <div class="control-row">
        <label>
          异常电压阈值（V）
          <input v-model.number="voltageWarningLimitInput" type="number" min="0" step="1" />
        </label>
        <label>
          异常电流阈值（mA）
          <input v-model.number="currentWarningLimitInput" type="number" min="0" step="0.1" />
        </label>
      </div>

      <div class="filter-row">
        <div class="series-toggles">
          <span class="section-label">模拟量筛选</span>
          <button
            v-for="series in analogSeriesToggles"
            :key="series.key"
            type="button"
            class="toggle-chip"
            :class="{ active: series.visible }"
            @click="toggleSeries(series.key)"
          >
            <span class="chip-swatch" :style="{ backgroundColor: series.color }"></span>
            {{ series.label }}
          </button>
        </div>

        <div class="relay-focus" v-if="visibleRelayNames.length">
          <span class="section-label">继电器选择</span>
          <button type="button" class="ghost-button relay-bulk-button" @click="selectAllVisibleRelays">
            全选
          </button>
          <button type="button" class="ghost-button relay-bulk-button" @click="clearSelectedRelays">
            清空
          </button>
          <button
            v-for="relay in visibleRelayNames"
            :key="relay"
            type="button"
            class="relay-chip"
            :class="{ active: selectedRelayNames.includes(relay), focused: focusedRelay === relay }"
            @click="toggleRelaySelection(relay)"
          >
            <span class="chip-swatch" :style="{ backgroundColor: getRelayColor(relay) }"></span>
            {{ relay }}
          </button>
        </div>
      </div>

      <div class="band-legend">
        <span class="band band-normal">正常范围</span>
        <span class="band band-alert">异常范围</span>
      </div>
    </section>

    <div v-if="loading" class="panel-empty">正在加载监测数据...</div>
    <div v-else-if="!hasAnyData" class="panel-empty">当前时间范围内无模拟量和继电器动作数据。</div>
    <template v-else>
      <section class="chart-panel">
        <div class="panel-title-row">
          <div>
            <p>选中的继电器状态线直接叠加到主图里，与电压电流共用时间轴和缩放。</p>
          </div>
          <div class="panel-meta">
            <span>采样点 {{ displayedAnalogRows.length }}</span>
            <span v-if="rawAnalogRows.length > displayedAnalogRows.length">已降采样</span>
            <span>已选继电器 {{ selectedRelayNames.length }} 条</span>
          </div>
        </div>
        <div v-if="hasAnalogData" class="chart-container analog-chart">
          <Line ref="analogChartRef" :data="analogChartData" :options="analogChartOptions" />
        </div>
        <div v-else class="panel-empty panel-empty-inline">当前时间范围内无模拟量数据。</div>
      </section>
    </template>
  </section>
</template>

<script lang="ts" setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { Line } from 'vue-chartjs';
import { useUserStore } from '@/stores/userStore';
import {
  Chart as ChartJS,
  type Chart,
  type ChartEvent,
  type ChartDataset,
  type ChartOptions,
  type Plugin,
  type TooltipItem,
  LineElement,
  PointElement,
  LinearScale,
  TimeScale,
  Title,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js';
import 'chartjs-adapter-date-fns';
import zoomPlugin from 'chartjs-plugin-zoom';
import { buildAuthWebSocketProtocols, getSystemFromRoute, getWsBase } from '@/utils/systems';

type QuickRangeKey = '5m' | '30m' | '2h' | '24h' | 'custom';
type SeriesKey = 'voltage_1' | 'voltage_2' | 'current_1' | 'current_2';
type MonitorConnectionState = 'idle' | 'connecting' | 'live' | 'reconnecting' | 'fallback';

interface AnalogData {
  id: number;
  voltage_1: number;
  current_1: number;
  voltage_2: number;
  current_2: number;
  timestamp: string;
  device: number;
}

interface RelayActionData {
  id: number;
  relay: string;
  action: string;
  timestamp: string;
  device: number;
}

interface RelayMarker {
  id: number;
  relay: string;
  action: string;
  timestamp: string;
  x: number;
  y: number;
  color: string;
}

interface DeviceMonitorUpdatePayload {
  device_id: number;
  analog?: AnalogData[];
  relay?: RelayActionData[];
}

interface AnalogMonitorPrefs {
  selectedPageSize: number;
  showCurrent: boolean;
  showOnlyActiveRelays: boolean;
  voltageWarningLimit: number;
  currentWarningLimit: number;
}

const baseRelayOrder = [
  '一方向本站QHJ',
  '一方向邻站QHJ',
  '二方向本站QHJ',
  '二方向邻站QHJ',
  '一方向本站ZDJ',
  '一方向本站FDJ',
  '一方向本站ZXJ',
  '一方向本站FXJ',
  '一方向邻站ZDJ',
  '一方向邻站FDJ',
  '一方向邻站ZXJ',
  '一方向邻站FXJ',
  '二方向本站ZDJ',
  '二方向本站FDJ',
  '二方向本站ZXJ',
  '二方向本站FXJ',
  '二方向邻站ZDJ',
  '二方向邻站FDJ',
  '二方向邻站ZXJ',
  '二方向邻站FXJ',
] as const;

const relayCatalog = [
  '一方向本站QHJ',
  '一方向邻站QHJ',
  '二方向本站QHJ',
  '二方向邻站QHJ',
  '一方向本站ZDJ(A系)',
  '一方向本站ZDJ(B系)',
  '一方向本站FDJ(A系)',
  '一方向本站FDJ(B系)',
  '一方向本站ZXJ(A系)',
  '一方向本站ZXJ(B系)',
  '一方向本站FXJ(A系)',
  '一方向本站FXJ(B系)',
  '一方向邻站ZDJ(A系)',
  '一方向邻站ZDJ(B系)',
  '一方向邻站FDJ(A系)',
  '一方向邻站FDJ(B系)',
  '一方向邻站ZXJ(A系)',
  '一方向邻站ZXJ(B系)',
  '一方向邻站FXJ(A系)',
  '一方向邻站FXJ(B系)',
  '二方向本站ZDJ(A系)',
  '二方向本站ZDJ(B系)',
  '二方向本站FDJ(A系)',
  '二方向本站FDJ(B系)',
  '二方向本站ZXJ(A系)',
  '二方向本站ZXJ(B系)',
  '二方向本站FXJ(A系)',
  '二方向本站FXJ(B系)',
  '二方向邻站ZDJ(A系)',
  '二方向邻站ZDJ(B系)',
  '二方向邻站FDJ(A系)',
  '二方向邻站FDJ(B系)',
  '二方向邻站ZXJ(A系)',
  '二方向邻站ZXJ(B系)',
  '二方向邻站FXJ(A系)',
  '二方向邻站FXJ(B系)',
] as const;

const colorMap: Record<(typeof baseRelayOrder)[number], string> = {
  一方向本站QHJ: '#7c3aed',
  一方向邻站QHJ: '#4f46e5',
  二方向本站QHJ: '#0f766e',
  二方向邻站QHJ: '#b45309',
  一方向本站ZDJ: '#df3b57',
  一方向本站FDJ: '#2978b5',
  一方向本站ZXJ: '#c79a00',
  一方向本站FXJ: '#008a84',
  一方向邻站ZDJ: '#7a49d6',
  一方向邻站FDJ: '#d67a00',
  一方向邻站ZXJ: '#6f7881',
  一方向邻站FXJ: '#3559d6',
  二方向本站ZDJ: '#159f5b',
  二方向本站FDJ: '#d22b8f',
  二方向本站ZXJ: '#dd5f91',
  二方向本站FXJ: '#0f6f72',
  二方向邻站ZDJ: '#b89300',
  二方向邻站FDJ: '#6a2083',
  二方向邻站ZXJ: '#2f855a',
  二方向邻站FXJ: '#0b57d0',
};

const quickRanges = [
  { key: '5m', label: '最近 5 分钟', minutes: 5 },
  { key: '30m', label: '最近 30 分钟', minutes: 30 },
  { key: '2h', label: '最近 2 小时', minutes: 120 },
  { key: '24h', label: '最近 24 小时', minutes: 1440 },
] as const;

const MAX_ANALOG_POINTS = 2500;
const RELAY_STATE_LOW = 0.18;
const RELAY_STATE_HIGH = 0.82;
const RELAY_BASELINE = 0.5;
const RELAY_HOVER_WINDOW_MS = 1500;
const FUTURE_DATA_TOLERANCE_MS = 1000;
const DATE_TIME_FORMATTER = new Intl.DateTimeFormat('zh-CN', {
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});
const ANALOG_MONITOR_PREFS_KEY = 'bt:analog_monitor_prefs:v1';

function getRelayBaseName(relayName: string) {
  return relayName.replace(/\((A|B)系\)$/, '');
}

function getRelaySeriesRank(relayName: string) {
  if (relayName.endsWith('(A系)')) return 1;
  if (relayName.endsWith('(B系)')) return 2;
  return 0;
}

function getRelayColor(relayName: string) {
  const baseName = getRelayBaseName(relayName) as (typeof baseRelayOrder)[number];
  return colorMap[baseName] ?? '#6f7881';
}

function compareRelayNames(left: string, right: string) {
  const leftBase = getRelayBaseName(left);
  const rightBase = getRelayBaseName(right);
  const leftIndex = baseRelayOrder.indexOf(leftBase as (typeof baseRelayOrder)[number]);
  const rightIndex = baseRelayOrder.indexOf(rightBase as (typeof baseRelayOrder)[number]);
  const safeLeftIndex = leftIndex === -1 ? Number.MAX_SAFE_INTEGER : leftIndex;
  const safeRightIndex = rightIndex === -1 ? Number.MAX_SAFE_INTEGER : rightIndex;

  if (safeLeftIndex !== safeRightIndex) {
    return safeLeftIndex - safeRightIndex;
  }

  const seriesDiff = getRelaySeriesRank(left) - getRelaySeriesRank(right);
  if (seriesDiff !== 0) {
    return seriesDiff;
  }

  return left.localeCompare(right, 'zh-CN');
}

function sortRelayNames(relayNames: Iterable<string>) {
  return Array.from(new Set(relayNames)).sort(compareRelayNames);
}

const analogBandsPlugin: Plugin<'line'> = {
  id: 'analogBands',
  beforeDraw(chart, _args, pluginOptions) {
    const options = pluginOptions as { enabled?: boolean; warningLimit?: number } | undefined;
    if (!options?.enabled) return;

    const yScale = chart.scales.voltage;
    const xScale = chart.scales.x;
    if (!yScale || !xScale) return;

    const { ctx, chartArea } = chart;
    if (!chartArea) return;

    const warningLimit = Math.max(0, options.warningLimit ?? 130);
    const bands = [
      { from: -warningLimit, to: warningLimit, color: 'rgba(25, 159, 91, 0.10)' },
      { from: yScale.min, to: -warningLimit, color: 'rgba(223, 59, 87, 0.10)' },
      { from: warningLimit, to: yScale.max, color: 'rgba(223, 59, 87, 0.10)' },
    ];

    ctx.save();
    for (const band of bands) {
      const top = yScale.getPixelForValue(Math.max(band.from, band.to));
      const bottom = yScale.getPixelForValue(Math.min(band.from, band.to));
      const height = bottom - top;
      if (height <= 0) continue;
      ctx.fillStyle = band.color;
      ctx.fillRect(chartArea.left, top, chartArea.right - chartArea.left, height);
    }

    const zeroY = yScale.getPixelForValue(0);
    ctx.strokeStyle = 'rgba(22, 32, 44, 0.35)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(chartArea.left, zeroY);
    ctx.lineTo(chartArea.right, zeroY);
    ctx.stroke();
    ctx.restore();
  },
};

const linkedCursorPlugin: Plugin<'line'> = {
  id: 'linkedCursor',
  afterDatasetsDraw(chart) {
    const timestamp = (chart as any).$linkedCursorTimestamp;
    if (timestamp == null) return;

    const xScale = chart.scales.x;
    if (!xScale || Number.isNaN(timestamp)) return;

    const x = xScale.getPixelForValue(timestamp);
    if (!Number.isFinite(x)) return;

    const { ctx, chartArea } = chart;
    ctx.save();
    ctx.strokeStyle = 'rgba(22, 32, 44, 0.22)';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(x, chartArea.top);
    ctx.lineTo(x, chartArea.bottom);
    ctx.stroke();
    ctx.restore();
  },
};

const pinnedViewportPlugin: Plugin<'line'> = {
  id: 'pinnedViewport',
  beforeUpdate(chart) {
    const pinnedRange = (chart as any).$pinnedViewportRange as { min?: number; max?: number } | null | undefined;
    const xScale = chart.options.scales?.x as { min?: number; max?: number } | undefined;
    if (!xScale) return;

    if (!pinnedRange || (pinnedRange.min == null && pinnedRange.max == null)) {
      return;
    }

    xScale.min = pinnedRange.min;
    xScale.max = pinnedRange.max;
  },
};

ChartJS.register(
  Title,
  Tooltip,
  Legend,
  LineElement,
  PointElement,
  LinearScale,
  TimeScale,
  Filler,
  zoomPlugin,
  analogBandsPlugin,
  linkedCursorPlugin,
  pinnedViewportPlugin
);

const route = useRoute();
const userStore = useUserStore();
const rawData = ref<{ analog: AnalogData[]; relay: RelayActionData[] }>({ analog: [], relay: [] });
const deviceId = ref<number>(parseInt(Array.isArray(route.params.index) ? route.params.index[0] : (route.params.index as string), 10));
const loading = ref(false);
const selectedPageSize = ref(1000);
const showCurrent = ref(false);
const showOnlyActiveRelays = ref(true);
const focusedRelay = ref<string | null>(null);
const selectedRelayNames = ref<string[]>([]);
const activeQuickRange = ref<QuickRangeKey>('5m');
const sharedXAxisRange = ref<{ min?: number; max?: number }>({});
const viewportLocked = ref(false);
const voltageWarningLimitInput = ref(130);
const currentWarningLimitInput = ref(120);
const analogChartRef = ref<any>(null);
const syncingZoom = ref(false);
const monitorSocket = ref<WebSocket | null>(null);
const reconnectTimer = ref<number | null>(null);
const fallbackPollTimer = ref<number | null>(null);
const realtimeGuardTimer = ref<number | null>(null);
const monitorConnectionState = ref<MonitorConnectionState>('idle');
const monitorWsCandidateIndex = ref(0);
const lastRealtimeDataAt = ref<number>(0);

const seriesVisibility = reactive<Record<SeriesKey, boolean>>({
  voltage_1: true,
  voltage_2: true,
  current_1: false,
  current_2: false,
});

const now = new Date();
const defaultStartTime = new Date(now.getTime() - 5 * 60_000);
const startTime = ref(formatDateInput(defaultStartTime));
const endTime = ref('');

function loadAnalogMonitorPrefs(): Partial<AnalogMonitorPrefs> {
  if (typeof window === 'undefined') {
    return {};
  }

  try {
    const rawPrefs = window.localStorage.getItem(ANALOG_MONITOR_PREFS_KEY);
    if (!rawPrefs) {
      return {};
    }
    const parsedPrefs = JSON.parse(rawPrefs) as Partial<AnalogMonitorPrefs>;
    return typeof parsedPrefs === 'object' && parsedPrefs ? parsedPrefs : {};
  } catch (error) {
    console.warn('Failed to load analog monitor preferences:', error);
    return {};
  }
}

function saveAnalogMonitorPrefs() {
  if (typeof window === 'undefined') {
    return;
  }

  const prefs: AnalogMonitorPrefs = {
    selectedPageSize: selectedPageSize.value,
    showCurrent: showCurrent.value,
    showOnlyActiveRelays: showOnlyActiveRelays.value,
    voltageWarningLimit: voltageWarningLimitInput.value,
    currentWarningLimit: currentWarningLimitInput.value,
  };

  window.localStorage.setItem(ANALOG_MONITOR_PREFS_KEY, JSON.stringify(prefs));
}

function formatDateInput(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${year}-${month}-${day}T${hours}:${minutes}`;
}

function parseTimestamp(timestamp: string) {
  return new Date(timestamp).getTime();
}

function getAllowedMaxTimestamp() {
  if (endTime.value) {
    const endTimestamp = parseTimestamp(endTime.value);
    if (Number.isFinite(endTimestamp)) {
      return endTimestamp;
    }
  }
  return Date.now() + FUTURE_DATA_TOLERANCE_MS;
}

function isTimestampAllowed(timestamp: string) {
  const parsedTimestamp = parseTimestamp(timestamp);
  return Number.isFinite(parsedTimestamp) && parsedTimestamp <= getAllowedMaxTimestamp();
}

function filterAllowedAnalogRows(rows: AnalogData[]) {
  return rows.filter((row) => row.timestamp && isTimestampAllowed(row.timestamp));
}

function filterAllowedRelayRows(rows: RelayActionData[]) {
  return rows.filter((row) => row.timestamp && isTimestampAllowed(row.timestamp));
}

function formatDisplayTime(timestamp: string | number | undefined) {
  if (timestamp == null || timestamp === '') return '--';
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return '--';
  return DATE_TIME_FORMATTER.format(date).replace(/\//g, '-');
}

function formatValue(value: number | undefined, unit: string) {
  if (value == null || Number.isNaN(value)) return '--';
  return `${value.toFixed(2)} ${unit}`;
}

function setCustomRange() {
  activeQuickRange.value = 'custom';
  sharedXAxisRange.value = {};
  viewportLocked.value = false;
}

function applyQuickRange(rangeKey: Exclude<QuickRangeKey, 'custom'>) {
  const preset = quickRanges.find((item) => item.key === rangeKey);
  if (!preset) return;

  const current = new Date();
  const start = new Date(current.getTime() - preset.minutes * 60_000);
  startTime.value = formatDateInput(start);
  endTime.value = '';
  activeQuickRange.value = rangeKey;
  sharedXAxisRange.value = {};
  viewportLocked.value = false;
  fetchData();
}

function jumpToLatest() {
  const targetRange = activeQuickRange.value === 'custom' ? '5m' : activeQuickRange.value;
  applyQuickRange(targetRange as Exclude<QuickRangeKey, 'custom'>);
}

function toggleSeries(key: SeriesKey) {
  if (key.startsWith('current')) {
    showCurrent.value = true;
  }
  seriesVisibility[key] = !seriesVisibility[key];

  if (key.startsWith('current') && !seriesVisibility.current_1 && !seriesVisibility.current_2) {
    showCurrent.value = false;
  }
}

function toggleRelaySelection(relay: string) {
  const isSelected = selectedRelayNames.value.includes(relay);
  if (isSelected) {
    selectedRelayNames.value = selectedRelayNames.value.filter((item) => item !== relay);
    if (focusedRelay.value === relay) {
      focusedRelay.value = selectedRelayNames.value[0] ?? null;
    }
    return;
  }

  selectedRelayNames.value = sortRelayNames([...selectedRelayNames.value, relay]);
  focusedRelay.value = relay;
}

function selectAllVisibleRelays() {
  selectedRelayNames.value = [...visibleRelayNames.value];
  focusedRelay.value = selectedRelayNames.value[0] ?? null;
}

function clearSelectedRelays() {
  selectedRelayNames.value = [];
  focusedRelay.value = null;
}

function downsampleAnalogData(rows: AnalogData[], maxPoints: number) {
  if (rows.length <= maxPoints) return rows;

  const stride = Math.ceil(rows.length / maxPoints);
  const sampled = rows.filter((_row, index) => index % stride === 0);
  const lastRow = rows[rows.length - 1];
  if (sampled[sampled.length - 1]?.id !== lastRow.id) {
    sampled.push(lastRow);
  }
  return sampled;
}

const requestedRange = computed(() => {
  const min = startTime.value ? new Date(startTime.value).getTime() : undefined;
  const max = endTime.value ? new Date(endTime.value).getTime() : undefined;
  return {
    min: Number.isFinite(min) ? min : undefined,
    max: Number.isFinite(max) ? max : undefined,
  };
});

const effectiveXAxisRange = computed(() => ({
  min: sharedXAxisRange.value.min ?? requestedRange.value.min,
  max: sharedXAxisRange.value.max ?? requestedRange.value.max,
}));
const voltageWarningLimit = computed(() => Math.max(0, Number(voltageWarningLimitInput.value) || 0));
const currentWarningLimit = computed(() => Math.max(0, Number(currentWarningLimitInput.value) || 0));
const rawAnalogRows = computed(() => [...rawData.value.analog].sort((a, b) => parseTimestamp(a.timestamp) - parseTimestamp(b.timestamp)));
const rawRelayRows = computed(() =>
  [...rawData.value.relay]
    .filter((row) => row.timestamp && row.relay && row.action)
    .sort((a, b) => parseTimestamp(a.timestamp) - parseTimestamp(b.timestamp))
);
const displayedAnalogRows = computed(() => downsampleAnalogData(rawAnalogRows.value, MAX_ANALOG_POINTS));

const activeRelayNames = computed(() => {
  return sortRelayNames(rawRelayRows.value.map((relay) => relay.relay));
});

const visibleRelayNames = computed(() => {
  if (showOnlyActiveRelays.value) {
    return activeRelayNames.value;
  }
  return sortRelayNames([...relayCatalog, ...rawRelayRows.value.map((relay) => relay.relay)]);
});

const relayTrackNames = computed(() => sortRelayNames(selectedRelayNames.value.filter((relay) => visibleRelayNames.value.includes(relay))));
const dataTimestampBounds = computed(() => {
  const timestamps = [
    ...rawAnalogRows.value.map((row) => parseTimestamp(row.timestamp)),
    ...rawRelayRows.value.map((row) => parseTimestamp(row.timestamp)),
  ].filter((timestamp) => Number.isFinite(timestamp));

  if (!timestamps.length) {
    return { min: undefined, max: undefined };
  }

  return {
    min: Math.min(...timestamps),
    max: Math.max(...timestamps),
  };
});

const savedPrefs = loadAnalogMonitorPrefs();
if (typeof savedPrefs.selectedPageSize === 'number') {
  selectedPageSize.value = savedPrefs.selectedPageSize;
}
if (typeof savedPrefs.showCurrent === 'boolean') {
  showCurrent.value = savedPrefs.showCurrent;
}
if (typeof savedPrefs.showOnlyActiveRelays === 'boolean') {
  showOnlyActiveRelays.value = savedPrefs.showOnlyActiveRelays;
}
if (typeof savedPrefs.voltageWarningLimit === 'number') {
  voltageWarningLimitInput.value = savedPrefs.voltageWarningLimit;
}
if (typeof savedPrefs.currentWarningLimit === 'number') {
  currentWarningLimitInput.value = savedPrefs.currentWarningLimit;
}

const latestAnalogRow = computed(() => rawAnalogRows.value[rawAnalogRows.value.length - 1]);
const hasAnalogData = computed(() => rawAnalogRows.value.length > 0);
const hasRelayData = computed(() => rawRelayRows.value.length > 0);
const hasAnyData = computed(() => hasAnalogData.value || hasRelayData.value);

const latestVoltageSummary = computed(() => {
  if (!latestAnalogRow.value) return '--';
  return `一方向 ${latestAnalogRow.value.voltage_1.toFixed(2)} V / 二方向 ${latestAnalogRow.value.voltage_2.toFixed(2)} V`;
});

const anomalySummary = computed(() => {
  if (!hasAnalogData.value) return '无模拟量';
  return hasAbnormalPoints.value ? '存在异常电压' : '未见异常电压';
});

const currentAnomalySummary = computed(() => {
  if (!hasAnalogData.value) return '无模拟量';
  return hasAbnormalCurrent.value ? '存在异常电流' : '未见异常电流';
});

const rangeSummary = computed(() => {
  const start = startTime.value ? formatDisplayTime(startTime.value) : '--';
  const end = endTime.value ? formatDisplayTime(endTime.value) : '当前';
  return `${start} - ${end}`;
});

const analogSeriesToggles = computed(() => [
  { key: 'voltage_1' as const, label: '一方向电压', color: '#2978b5', visible: seriesVisibility.voltage_1 },
  { key: 'voltage_2' as const, label: '二方向电压', color: '#159f5b', visible: seriesVisibility.voltage_2 },
  { key: 'current_1' as const, label: '一方向电流', color: '#d67a00', visible: seriesVisibility.current_1 },
  { key: 'current_2' as const, label: '二方向电流', color: '#7a49d6', visible: seriesVisibility.current_2 },
]);

const voltageBounds = computed(() => {
  const values = displayedAnalogRows.value.flatMap((row) => [row.voltage_1, row.voltage_2]).filter((value) => Number.isFinite(value));
  if (!values.length) {
    return { min: -voltageWarningLimit.value, max: voltageWarningLimit.value };
  }

  const minValue = Math.min(...values, -voltageWarningLimit.value);
  const maxValue = Math.max(...values, voltageWarningLimit.value);
  const padding = Math.max((maxValue - minValue) * 0.08, 12);
  return {
    min: Math.floor(minValue - padding),
    max: Math.ceil(maxValue + padding),
  };
});

const currentBounds = computed(() => {
  const values = displayedAnalogRows.value.flatMap((row) => [row.current_1, row.current_2]).filter((value) => Number.isFinite(value));
  if (!values.length) {
    return { min: -10, max: 10 };
  }

  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const padding = Math.max((maxValue - minValue) * 0.1, 2);
  return {
    min: Math.floor(minValue - padding),
    max: Math.ceil(maxValue + padding),
  };
});

const hasAbnormalPoints = computed(() =>
  rawAnalogRows.value.some((row) =>
    [row.voltage_1, row.voltage_2].some((voltage) => Math.abs(voltage) >= voltageWarningLimit.value)
  )
);

const hasAbnormalCurrent = computed(() =>
  rawAnalogRows.value.some((row) =>
    [row.current_1, row.current_2].some((current) => Math.abs(current) >= currentWarningLimit.value)
  )
);

const relayRowsForOverlay = computed(() => {
  if (!relayTrackNames.value.length) {
    return [];
  }
  return rawRelayRows.value.filter((row) => relayTrackNames.value.includes(row.relay));
});

const relayMarkers = computed<RelayMarker[]>(() => {
  const topY = voltageBounds.value.max - Math.max((voltageBounds.value.max - voltageBounds.value.min) * 0.08, 8);
  return relayRowsForOverlay.value.map((row) => ({
    id: row.id,
    relay: row.relay,
    action: row.action,
    timestamp: row.timestamp,
    x: parseTimestamp(row.timestamp),
    y: topY,
    color: row.action === '吸起' ? '#159f5b' : '#d67a00',
  }));
});

function getRelayEventsNear(timestamp: number) {
  const sourceRows = relayTrackNames.value.length ? relayRowsForOverlay.value : rawRelayRows.value;
  return sourceRows.filter((row) => Math.abs(parseTimestamp(row.timestamp) - timestamp) <= RELAY_HOVER_WINDOW_MS);
}

function getAnalogTooltipLines(timestamp: number) {
  const events = getRelayEventsNear(timestamp).slice(0, 6);
  if (!events.length) return [];
  const lines = ['动作:'];
  for (const event of events) {
    lines.push(`${event.relay} ${event.action}`);
  }
  if (getRelayEventsNear(timestamp).length > events.length) {
    lines.push('更多动作未展开');
  }
  return lines;
}

function isTimestampWithinDataBounds(timestamp: number) {
  if (!Number.isFinite(timestamp)) {
    return false;
  }

  const { min, max } = dataTimestampBounds.value;
  if (min == null || max == null) {
    return false;
  }

  return timestamp >= min && timestamp <= max;
}

function getHoverTimestamp(chart: Chart, event: ChartEvent) {
  const xScale = chart.scales.x;
  if (!xScale || event.x == null || !Number.isFinite(event.x)) {
    return null;
  }

  const timestamp = Number(xScale.getValueForPixel(event.x));
  return Number.isFinite(timestamp) ? timestamp : null;
}

function updateHoverTimestamp(event: ChartEvent, activeElements: Array<{ datasetIndex: number; index: number }>, chart: Chart) {
  const hoverTimestamp = getHoverTimestamp(chart, event);
  (chart as any).$hoverTimestamp = hoverTimestamp;

  if (hoverTimestamp == null || !isTimestampWithinDataBounds(hoverTimestamp)) {
    (chart as any).$linkedCursorTimestamp = null;
    chart.setActiveElements([]);
    chart.tooltip?.setActiveElements([], { x: 0, y: 0 });
    chart.update('none');
    return;
  }

  if (!activeElements.length) {
    (chart as any).$linkedCursorTimestamp = null;
    chart.setActiveElements([]);
    chart.tooltip?.setActiveElements([], { x: 0, y: 0 });
    chart.update('none');
    return;
  }

  const point = chart.getDatasetMeta(activeElements[0].datasetIndex).data[activeElements[0].index];
  const parsed = (point as any)?.$context?.parsed;
  if (parsed?.x != null) {
    (chart as any).$linkedCursorTimestamp = Number(parsed.x);
    chart.draw();
  }
}

function syncXAxisFromChart(source: Chart) {
  if (syncingZoom.value) return;
  const xScale = source.scales.x;
  if (!xScale) return;

  const pinnedRange = {
    min: Number.isFinite(xScale.min) ? xScale.min : undefined,
    max: Number.isFinite(xScale.max) ? xScale.max : undefined,
  };

  syncingZoom.value = true;
  sharedXAxisRange.value = pinnedRange;
  viewportLocked.value = true;
  (source as any).$pinnedViewportRange = pinnedRange;

  nextTick(() => {
    syncingZoom.value = false;
  });
}

function getChartInstance(refValue: any): Chart | null {
  return refValue?.chart ?? null;
}

function capturePinnedViewportRange() {
  if (!viewportLocked.value) {
    return null;
  }

  const chart = getChartInstance(analogChartRef.value);
  const xScale = chart?.scales.x;
  if (!xScale) {
    return { ...sharedXAxisRange.value };
  }

  return {
    min: Number.isFinite(xScale.min) ? xScale.min : sharedXAxisRange.value.min,
    max: Number.isFinite(xScale.max) ? xScale.max : sharedXAxisRange.value.max,
  };
}

function restorePinnedViewportRange(range: { min?: number; max?: number } | null) {
  if (!range || (range.min == null && range.max == null)) {
    return;
  }

  sharedXAxisRange.value = {
    min: range.min,
    max: range.max,
  };

  nextTick(() => {
    const chart = getChartInstance(analogChartRef.value);
    if (!chart) {
      return;
    }

    (chart as any).$pinnedViewportRange = range;
    const xScale = chart.options.scales?.x as { min?: number; max?: number } | undefined;
    if (xScale) {
      xScale.min = range.min;
      xScale.max = range.max;
    }
    chart.update('none');
  });
}

function resetZoom() {
  sharedXAxisRange.value = {};
  viewportLocked.value = false;
  const chart = getChartInstance(analogChartRef.value);
  if (chart) {
    (chart as any).$linkedCursorTimestamp = null;
    (chart as any).$pinnedViewportRange = null;
  }
  chart?.resetZoom();
}

const relayAxisBounds = computed(() => ({
  min: -0.1,
  max: Math.max(relayTrackNames.value.length - 0.1, 0.9),
}));

const realtimeEnabled = computed(() => !endTime.value);
const directMonitorWsUrl = computed(() => {
  const system = getSystemFromRoute(route.params.system);
  return `${getWsBase(system)}/device-monitor/${deviceId.value}/`;
});
const sameOriginMonitorWsUrl = computed(() => {
  const system = getSystemFromRoute(route.params.system);
  return `${getWsBase(system)}/device-monitor/${deviceId.value}/`;
});
const monitorWsUrls = computed(() => {
  const urls = [sameOriginMonitorWsUrl.value, directMonitorWsUrl.value];
  return urls.filter((url, index) => urls.indexOf(url) === index);
});
const monitorConnectionLabel = computed(() => {
  if (!realtimeEnabled.value) return '历史模式';
  if (monitorConnectionState.value === 'live' && fallbackPollTimer.value != null) {
    return '实时连接中（轮询补偿）';
  }
  if (monitorConnectionState.value === 'live') return '实时连接中';
  if (monitorConnectionState.value === 'connecting') return '正在建立实时连接';
  if (monitorConnectionState.value === 'reconnecting') return '实时连接重试中';
  if (monitorConnectionState.value === 'fallback') return '实时连接失败，使用短轮询补偿';
  return '实时连接未启动';
});

function sortAnalogRows(rows: AnalogData[]) {
  return [...rows].sort((left, right) => parseTimestamp(left.timestamp) - parseTimestamp(right.timestamp));
}

function sortRelayRows(rows: RelayActionData[]) {
  return [...rows].sort((left, right) => parseTimestamp(left.timestamp) - parseTimestamp(right.timestamp));
}

function analogRowKey(row: AnalogData) {
  if (row.id) {
    return `id:${row.id}`;
  }
  return `ts:${row.timestamp}:${row.device}:${row.voltage_1}:${row.current_1}:${row.voltage_2}:${row.current_2}`;
}

function relayRowKey(row: RelayActionData) {
  if (row.id) {
    return `id:${row.id}`;
  }
  return `ts:${row.timestamp}:${row.device}:${row.relay}:${row.action}`;
}

function mergeAndTrimRows<T>(existingRows: T[], incomingRows: T[], makeKey: (row: T) => string, sorter: (rows: T[]) => T[]) {
  const rowMap = new Map<string, T>();
  for (const row of existingRows) {
    rowMap.set(makeKey(row), row);
  }
  for (const row of incomingRows) {
    rowMap.set(makeKey(row), row);
  }
  return sorter(Array.from(rowMap.values())).slice(-selectedPageSize.value);
}

function applyMonitorUpdate(payload: DeviceMonitorUpdatePayload) {
  if (payload.device_id !== deviceId.value) {
    return;
  }

  const preservedViewportRange = capturePinnedViewportRange();

  const incomingAnalogRows = filterAllowedAnalogRows(payload.analog ?? []);
  const incomingRelayRows = filterAllowedRelayRows(payload.relay ?? []);

  if (incomingAnalogRows.length) {
    rawData.value.analog = mergeAndTrimRows(rawData.value.analog, incomingAnalogRows, analogRowKey, sortAnalogRows);
  }
  if (incomingRelayRows.length) {
    rawData.value.relay = mergeAndTrimRows(rawData.value.relay, incomingRelayRows, relayRowKey, sortRelayRows);
  }

  restorePinnedViewportRange(preservedViewportRange);
}

function clearReconnectTimer() {
  if (reconnectTimer.value != null) {
    window.clearTimeout(reconnectTimer.value);
    reconnectTimer.value = null;
  }
}

function clearFallbackPollTimer() {
  if (fallbackPollTimer.value != null) {
    window.clearInterval(fallbackPollTimer.value);
    fallbackPollTimer.value = null;
  }
}

function clearRealtimeGuardTimer() {
  if (realtimeGuardTimer.value != null) {
    window.clearInterval(realtimeGuardTimer.value);
    realtimeGuardTimer.value = null;
  }
}

async function refreshRealtimeWindow() {
  const preservedViewportRange = capturePinnedViewportRange();
  try {
    await Promise.all([fetchAnalogData(), fetchRelayData()]);
    lastRealtimeDataAt.value = Date.now();
  } catch (error) {
    console.error('Error refreshing realtime monitor data:', error);
  } finally {
    restorePinnedViewportRange(preservedViewportRange);
  }
}

function startFallbackPolling() {
  if (!realtimeEnabled.value || fallbackPollTimer.value != null) {
    return;
  }
  monitorConnectionState.value = 'fallback';
  fallbackPollTimer.value = window.setInterval(() => {
    void refreshRealtimeWindow();
  }, 5000);
}

function startRealtimeGuard() {
  if (!realtimeEnabled.value || realtimeGuardTimer.value != null) {
    return;
  }

  realtimeGuardTimer.value = window.setInterval(() => {
    const staleMs = Date.now() - lastRealtimeDataAt.value;
    if (staleMs >= 5000) {
      void refreshRealtimeWindow();
    }
  }, 5000);
}

function closeMonitorSocket() {
  clearReconnectTimer();
  clearFallbackPollTimer();
  clearRealtimeGuardTimer();
  if (monitorSocket.value) {
    monitorSocket.value.onopen = null;
    monitorSocket.value.onmessage = null;
    monitorSocket.value.onerror = null;
    monitorSocket.value.onclose = null;
    monitorSocket.value.close();
    monitorSocket.value = null;
  }
  if (realtimeEnabled.value) {
    monitorConnectionState.value = 'idle';
  }
}

function scheduleReconnect() {
  if (!realtimeEnabled.value || monitorSocket.value) {
    return;
  }
  clearReconnectTimer();
  monitorConnectionState.value = 'reconnecting';
  reconnectTimer.value = window.setTimeout(() => {
    reconnectTimer.value = null;
    connectMonitorSocket();
  }, 1500);
}

function connectMonitorSocket() {
  if (!realtimeEnabled.value) {
    closeMonitorSocket();
    return;
  }

  if (monitorSocket.value?.readyState === WebSocket.OPEN || monitorSocket.value?.readyState === WebSocket.CONNECTING) {
    return;
  }

  clearReconnectTimer();
  const wsUrl = monitorWsUrls.value[monitorWsCandidateIndex.value];
  if (!wsUrl) {
    startFallbackPolling();
    return;
  }

  monitorConnectionState.value = monitorWsCandidateIndex.value === 0 ? 'connecting' : 'reconnecting';
  const system = getSystemFromRoute(route.params.system);
  const socket = new WebSocket(wsUrl, buildAuthWebSocketProtocols(userStore.auth[system].token));
  monitorSocket.value = socket;
  startRealtimeGuard();

  socket.onopen = () => {
    monitorWsCandidateIndex.value = 0;
    monitorConnectionState.value = 'live';
    lastRealtimeDataAt.value = Date.now();
    clearFallbackPollTimer();
  };

  socket.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data) as DeviceMonitorUpdatePayload;
      applyMonitorUpdate(payload);
      lastRealtimeDataAt.value = Date.now();
    } catch (error) {
      console.error('Error parsing monitor websocket message:', error);
    }
  };

  socket.onerror = () => {
    socket.close();
  };

  socket.onclose = () => {
    if (monitorSocket.value === socket) {
      monitorSocket.value = null;
      if (monitorConnectionState.value !== 'live' && monitorWsCandidateIndex.value < monitorWsUrls.value.length - 1) {
        monitorWsCandidateIndex.value += 1;
        connectMonitorSocket();
        return;
      }
      monitorWsCandidateIndex.value = 0;
      startFallbackPolling();
      scheduleReconnect();
    }
  };
}

function buildAnalogDatasets(): ChartDataset<'line'>[] {
  const datasets: ChartDataset<'line'>[] = [];

  if (seriesVisibility.voltage_1) {
    datasets.push({
      label: '一方向电压',
      yAxisID: 'voltage',
      borderColor: '#2978b5',
      backgroundColor: 'rgba(41, 120, 181, 0.16)',
      borderWidth: 2,
      pointRadius: 2,
      pointHoverRadius: 3,
      tension: 0.18,
      data: displayedAnalogRows.value.map((row) => ({ x: parseTimestamp(row.timestamp), y: row.voltage_1 })),
    });
  }

  if (seriesVisibility.voltage_2) {
    datasets.push({
      label: '二方向电压',
      yAxisID: 'voltage',
      borderColor: '#159f5b',
      backgroundColor: 'rgba(21, 159, 91, 0.16)',
      borderWidth: 2,
      pointRadius: 2,
      pointHoverRadius: 3,
      tension: 0.18,
      data: displayedAnalogRows.value.map((row) => ({ x: parseTimestamp(row.timestamp), y: row.voltage_2 })),
    });
  }

  if (showCurrent.value && seriesVisibility.current_1) {
    datasets.push({
      label: '一方向电流',
      yAxisID: 'current',
      borderColor: '#d67a00',
      backgroundColor: 'rgba(214, 122, 0, 0.12)',
      borderWidth: 1.8,
      pointRadius: 2,
      pointHoverRadius: 3,
      tension: 0.15,
      borderDash: [6, 4],
      data: displayedAnalogRows.value.map((row) => ({ x: parseTimestamp(row.timestamp), y: row.current_1 })),
    });
  }

  if (showCurrent.value && seriesVisibility.current_2) {
    datasets.push({
      label: '二方向电流',
      yAxisID: 'current',
      borderColor: '#7a49d6',
      backgroundColor: 'rgba(122, 73, 214, 0.12)',
      borderWidth: 1.8,
      pointRadius: 2,
      pointHoverRadius: 3,
      tension: 0.15,
      borderDash: [6, 4],
      data: displayedAnalogRows.value.map((row) => ({ x: parseTimestamp(row.timestamp), y: row.current_2 })),
    });
  }

  relayTrackNames.value.forEach((relay, index) => {
    datasets.push(buildRelayOverlayDataset(relay, index));
  });

  if (relayMarkers.value.length) {
    datasets.push({
      label: '继电器动作',
      yAxisID: 'voltage',
      type: 'line',
      showLine: false,
      pointStyle: 'triangle',
      pointRotation: (context) => {
        const marker = relayMarkers.value[context.dataIndex];
        return marker?.action === '落下' ? 180 : 0;
      },
      pointRadius: (context) => {
        const marker = relayMarkers.value[context.dataIndex];
        return marker && focusedRelay.value === marker.relay ? 7 : 5;
      },
      pointHoverRadius: 8,
      pointBackgroundColor: relayMarkers.value.map((marker) => marker.color),
      pointBorderColor: '#ffffff',
      pointBorderWidth: 1.5,
      data: relayMarkers.value.map((marker) => ({ x: marker.x, y: marker.y })),
    });
  }

  return datasets;
}

function buildRelayOverlayDataset(relay: string, orderIndex: number): ChartDataset<'line'> {
  const events = rawRelayRows.value.filter((row) => row.relay === relay);
  const relayColor = getRelayColor(relay);
  const baseColor = focusedRelay.value === relay ? relayColor : `${relayColor}cc`;
  const start = effectiveXAxisRange.value.min ?? requestedRange.value.min ?? (events[0] ? parseTimestamp(events[0].timestamp) : Date.now());
  const end = effectiveXAxisRange.value.max ?? requestedRange.value.max ?? (events[events.length - 1] ? parseTimestamp(events[events.length - 1].timestamp) : Date.now());

  if (!events.length) {
    return {
      label: relay,
      yAxisID: 'relay',
      borderColor: 'rgba(111, 120, 129, 0.45)',
      backgroundColor: 'rgba(111, 120, 129, 0.08)',
      borderWidth: 1.2,
      pointRadius: 0,
      borderDash: [4, 4],
      stepped: true,
      data: [
        { x: start, y: orderIndex + RELAY_BASELINE },
        { x: end, y: orderIndex + RELAY_BASELINE },
      ],
    };
  }

  const points: Array<{ x: number; y: number }> = [];
  let previousLevel: number | null = null;

  for (const event of events) {
    const x = parseTimestamp(event.timestamp);
    const nextLevel = event.action === '吸起' ? RELAY_STATE_HIGH : RELAY_STATE_LOW;
    if (previousLevel == null) {
      points.push({ x, y: orderIndex + nextLevel });
    } else {
      points.push({ x, y: orderIndex + previousLevel });
      points.push({ x, y: orderIndex + nextLevel });
    }
    previousLevel = nextLevel;
  }

  if (previousLevel != null) {
    points.push({ x: end, y: orderIndex + previousLevel });
  }

  return {
    label: relay,
    yAxisID: 'relay',
    borderColor: baseColor,
    backgroundColor: `${relayColor}22`,
    borderWidth: focusedRelay.value === relay ? 3 : 2,
    pointRadius: focusedRelay.value === relay ? 3 : 1.8,
    pointHoverRadius: 5,
    stepped: true,
    tension: 0,
    data: points,
  };
}

const analogChartData = computed(() => ({
  datasets: buildAnalogDatasets(),
}));

const analogChartOptions = computed<ChartOptions<'line'>>(() => ({
  responsive: true,
  maintainAspectRatio: false,
  normalized: true,
  animation: false,
  parsing: false,
  interaction: {
    mode: 'nearest',
    axis: 'x',
    intersect: false,
  },
  onHover: (event, activeElements, chart) => {
    updateHoverTimestamp(event, activeElements as Array<{ datasetIndex: number; index: number }>, chart);
  },
  onClick: (_event, activeElements, chart) => {
    if (!activeElements.length) return;
    const { datasetIndex, index } = activeElements[0];
    const dataset = chart.data.datasets[datasetIndex] as ChartDataset<'line'>;
    if (dataset.label === '继电器动作') {
      const marker = relayMarkers.value[index];
      if (marker) {
        focusedRelay.value = marker.relay;
      }
    } else if (dataset.yAxisID === 'relay' && dataset.label) {
      focusedRelay.value = dataset.label;
    }
  },
  scales: {
    x: {
      type: 'time',
      min: effectiveXAxisRange.value.min,
      max: effectiveXAxisRange.value.max,
      time: {
        unit: 'minute',
        tooltipFormat: 'MM月dd日 HH:mm:ss',
      },
      ticks: {
        maxRotation: 0,
        autoSkip: true,
      },
      title: {
        display: true,
        text: '时间',
      },
      grid: {
        color: 'rgba(22, 32, 44, 0.08)',
      },
    },
    voltage: {
      type: 'linear',
      position: 'left',
      min: voltageBounds.value.min,
      max: voltageBounds.value.max,
      title: {
        display: true,
        text: '电压 (V)',
      },
      grid: {
        color: 'rgba(22, 32, 44, 0.08)',
      },
    },
    current: {
      type: 'linear',
      position: 'right',
      display: showCurrent.value,
      min: currentBounds.value.min,
      max: currentBounds.value.max,
      title: {
        display: showCurrent.value,
        text: '电流 (mA)',
      },
      grid: {
        drawOnChartArea: false,
      },
    },
    relay: {
      type: 'linear',
      position: 'right',
      display: relayTrackNames.value.length > 0,
      offset: true,
      min: relayAxisBounds.value.min,
      max: relayAxisBounds.value.max,
      title: {
        display: relayTrackNames.value.length > 0,
        text: '继电器状态',
      },
      ticks: {
        stepSize: 1,
        callback(value) {
          const relay = relayTrackNames.value[Number(value)];
          return relay ?? '';
        },
        color: '#334155',
        font: {
          size: 11,
        },
      },
      grid: {
        drawOnChartArea: false,
      },
    },
  },
  plugins: {
    legend: {
      display: false,
    },
    tooltip: {
      backgroundColor: 'rgba(22, 32, 44, 0.92)',
      displayColors: true,
      filter(item: TooltipItem<'line'>) {
        const hoverTimestamp = (item.chart as any).$hoverTimestamp as number | null | undefined;
        return hoverTimestamp != null && isTimestampWithinDataBounds(hoverTimestamp);
      },
      callbacks: {
        title(items: TooltipItem<'line'>[]) {
          if (!items.length) {
            return '';
          }
          return formatDisplayTime(items[0]?.parsed?.x);
        },
        label(context: TooltipItem<'line'>) {
          if (context.dataset.label === '继电器动作') {
            const marker = relayMarkers.value[context.dataIndex];
            return marker ? `${marker.relay} ${marker.action}` : '继电器动作';
          }
          if (context.dataset.yAxisID === 'relay') {
            const value = Number(context.parsed.y) - Math.floor(Number(context.parsed.y));
            return `${context.dataset.label}: ${value >= 0.5 ? '吸起' : value > 0.3 ? '无动作' : '落下'}`;
          }
          const unit = context.dataset.yAxisID === 'current' ? 'mA' : 'V';
          return `${context.dataset.label}: ${Number(context.parsed.y).toFixed(2)} ${unit}`;
        },
        afterBody(items: TooltipItem<'line'>[]) {
          const timestamp = Number(items[0]?.parsed?.x);
          return Number.isFinite(timestamp) ? getAnalogTooltipLines(timestamp) : [];
        },
      },
    },
    zoom: {
      pan: {
        enabled: true,
        mode: 'x',
        onPan({ chart }: { chart: Chart }) {
          syncXAxisFromChart(chart);
        },
        onPanComplete({ chart }: { chart: Chart }) {
          syncXAxisFromChart(chart);
        },
      },
      zoom: {
        wheel: {
          enabled: true,
        },
        pinch: {
          enabled: true,
        },
        mode: 'x',
        onZoom({ chart }: { chart: Chart }) {
          syncXAxisFromChart(chart);
        },
        onZoomComplete({ chart }: { chart: Chart }) {
          syncXAxisFromChart(chart);
        },
      },
      limits: {
        x: {
          min: requestedRange.value.min,
          max: requestedRange.value.max,
        },
      },
    },
    linkedCursor: {},
    analogBands: {
      enabled: true,
      warningLimit: voltageWarningLimit.value,
    },
  },
}));

async function fetchAnalogData() {
  const params: Record<string, string | number> = {
    device: deviceId.value,
    page_size: selectedPageSize.value,
  };
  if (startTime.value) params.timestamp__gte = startTime.value;
  if (endTime.value) {
    params.timestamp__lte = endTime.value;
  } else {
    params.timestamp__lte = new Date().toISOString();
  }

  const response = await userStore.requestWithAuth<{ results?: AnalogData[] }>(
    getSystemFromRoute(route.params.system),
    {
      method: 'get',
      url: '/analog-data/',
      params,
    },
  );
  rawData.value.analog = sortAnalogRows(filterAllowedAnalogRows(response.results ?? []));
}

async function fetchRelayData() {
  const params: Record<string, string | number> = {
    device: deviceId.value,
    page_size: selectedPageSize.value,
  };
  if (startTime.value) params.timestamp__gte = startTime.value;
  if (endTime.value) {
    params.timestamp__lte = endTime.value;
  } else {
    params.timestamp__lte = new Date().toISOString();
  }

  const response = await userStore.requestWithAuth<{ results?: RelayActionData[] }>(
    getSystemFromRoute(route.params.system),
    {
      method: 'get',
      url: '/relay-actions/',
      params,
    },
  );
  rawData.value.relay = sortRelayRows(filterAllowedRelayRows(response.results ?? []));
}

async function fetchData() {
  loading.value = true;
  sharedXAxisRange.value = {};
  viewportLocked.value = false;
  try {
    await Promise.all([fetchAnalogData(), fetchRelayData()]);
    lastRealtimeDataAt.value = Date.now();
  } catch (error) {
    console.error('Error fetching analog monitor data:', error);
  } finally {
    loading.value = false;
    await nextTick();
    const chart = getChartInstance(analogChartRef.value);
    if (chart) {
      (chart as any).$hoverTimestamp = null;
      (chart as any).$linkedCursorTimestamp = null;
      chart.update('none');
    }
  }
}

watch(
  () => [route.params.index, route.params.system, realtimeEnabled.value],
  ([newIndex]) => {
    deviceId.value = parseInt(Array.isArray(newIndex) ? newIndex[0] : (newIndex as string), 10);
    focusedRelay.value = null;
    monitorWsCandidateIndex.value = 0;
    closeMonitorSocket();
    fetchData();
    if (realtimeEnabled.value) {
      startRealtimeGuard();
      connectMonitorSocket();
    }
  },
  { immediate: true }
);

watch(showCurrent, (enabled) => {
  saveAnalogMonitorPrefs();
  if (!enabled) {
    seriesVisibility.current_1 = false;
    seriesVisibility.current_2 = false;
  }
});

watch(() => [selectedPageSize.value, showOnlyActiveRelays.value, voltageWarningLimitInput.value, currentWarningLimitInput.value], () => {
  saveAnalogMonitorPrefs();
});

watch(visibleRelayNames, (relays) => {
  if (focusedRelay.value && !relays.includes(focusedRelay.value)) {
    focusedRelay.value = null;
  }
  const visibleSet = new Set(relays);
  selectedRelayNames.value = selectedRelayNames.value.filter((relay) => visibleSet.has(relay));
  if (!selectedRelayNames.value.length && relays.length) {
    const preferredRelays = activeRelayNames.value.length ? activeRelayNames.value : relays;
    selectedRelayNames.value = preferredRelays.slice(0, Math.min(preferredRelays.length, 6));
    focusedRelay.value = selectedRelayNames.value[0] ?? null;
  }
});

watch(
  () => [selectedPageSize.value],
  () => {
    sharedXAxisRange.value = {};
    rawData.value.analog = rawData.value.analog.slice(-selectedPageSize.value);
    rawData.value.relay = rawData.value.relay.slice(-selectedPageSize.value);
  }
);

watch(
  () => realtimeEnabled.value,
  (enabled) => {
    if (enabled) {
      startRealtimeGuard();
      monitorWsCandidateIndex.value = 0;
      connectMonitorSocket();
      return;
    }
    closeMonitorSocket();
    monitorConnectionState.value = 'idle';
  }
);

onBeforeUnmount(() => {
  closeMonitorSocket();
});

</script>

<style scoped>
.analog-monitor {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-top: 16px;
  padding: 20px;
  background: linear-gradient(180deg, #f7fafc 0%, #edf2f7 100%);
  border: 1px solid #d7e0ea;
  border-radius: 18px;
}

.monitor-header {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 16px;
}

.monitor-status-row {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  color: #4a5568;
  font-size: 13px;
}

.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #a0aec0;
}

.status-dot.connecting,
.status-dot.reconnecting {
  background: #d67a00;
}

.status-dot.live {
  background: #159f5b;
}

.status-dot.fallback {
  background: #b45309;
}

.monitor-header h2,
.chart-panel h3 {
  margin: 0;
  color: #16202c;
}

.monitor-header p,
.chart-panel p {
  margin: 6px 0 0;
  color: #51606f;
  font-size: 13px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(148px, 1fr));
  gap: 12px;
  flex: 1;
  min-width: min(100%, 460px);
}

.summary-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px 14px;
  background: rgba(255, 255, 255, 0.8);
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 12px;
}

.summary-card span {
  color: #64748b;
  font-size: 12px;
}

.summary-card strong {
  color: #16202c;
  font-size: 14px;
}

.summary-card .is-alert {
  color: #b42318;
}

.summary-card .is-normal {
  color: #0f7a4d;
}

.toolbar-panel,
.chart-panel {
  padding: 16px;
  background: rgba(255, 255, 255, 0.86);
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 16px;
}

.quick-range-row,
.control-row,
.filter-row,
.band-legend,
.panel-title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.control-row {
  margin-top: 12px;
}

.filter-row {
  justify-content: space-between;
  margin-top: 12px;
  gap: 16px;
}

.band-legend {
  margin-top: 12px;
}

.section-label {
  color: #51606f;
  font-size: 12px;
  font-weight: 600;
}

.range-button,
.toggle-chip,
.relay-chip,
.primary-button,
.ghost-button {
  border: 1px solid #cbd5e1;
  border-radius: 999px;
  background: #fff;
  color: #1e293b;
  cursor: pointer;
  transition: 0.18s ease;
}

.range-button,
.toggle-chip,
.relay-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  font-size: 12px;
}

.primary-button,
.ghost-button {
  padding: 8px 14px;
  font-size: 13px;
}

.primary-button {
  background: #16202c;
  border-color: #16202c;
  color: #fff;
}

.range-button.active,
.toggle-chip.active,
.relay-chip.active,
.ghost-button:hover,
.primary-button:hover {
  transform: translateY(-1px);
}

.range-button.active,
.toggle-chip.active,
.relay-chip.active {
  border-color: #16202c;
  background: #e8eef5;
}

.relay-chip.focused {
  box-shadow: 0 0 0 2px rgba(22, 32, 44, 0.16);
}

.relay-bulk-button {
  padding: 6px 12px;
}

.chip-swatch {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  display: inline-block;
}

.series-toggles,
.relay-focus {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.band {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  color: #334155;
}

.band-normal {
  background: rgba(25, 159, 91, 0.12);
}

.band-watch {
  background: rgba(214, 122, 0, 0.12);
}

.band-alert {
  background: rgba(223, 59, 87, 0.12);
}

.control-row label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #334155;
  font-size: 13px;
}

.control-row select,
.control-row input[type='datetime-local'] {
  min-height: 34px;
  padding: 0 10px;
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  background: #fff;
}

.checkbox-label input {
  margin: 0;
}

.panel-title-row {
  justify-content: space-between;
  margin-bottom: 14px;
}

.panel-meta {
  display: flex;
  gap: 12px;
  color: #64748b;
  font-size: 12px;
}

.chart-container {
  position: relative;
  width: 100%;
}

.analog-chart {
  height: 420px;
}

.relay-chart {
  min-height: 180px;
}

.panel-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 120px;
  padding: 24px;
  border: 1px dashed #cbd5e1;
  border-radius: 14px;
  color: #64748b;
  background: rgba(255, 255, 255, 0.7);
}

.panel-empty-inline {
  min-height: 220px;
}

@media (max-width: 960px) {
  .analog-monitor {
    padding: 14px;
  }

  .summary-grid {
    min-width: 100%;
  }

  .analog-chart {
    height: 340px;
  }
}
</style>
