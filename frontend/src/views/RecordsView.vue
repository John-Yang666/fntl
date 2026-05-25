<template>
  <div class="records-view">
    <section class="system-selector-card">
      <div class="system-selector-row">
        <h2 class="system-selector-title">设备选择</h2>
        <el-select v-model="selectedSystem" class="system-selector" style="width: 140px;">
          <el-option v-for="system in systems" :key="system" :label="labels[system]" :value="system" />
        </el-select>
      </div>
    </section>

    <section v-if="canOpenAdmin" class="system-summary-card">
      <div class="summary-header">
        <h2>打开后端界面</h2>
        <div class="summary-actions">
          <el-button @click="openAdmin(selectedSystem, 'alarmdata')">历史告警记录</el-button>
          <el-button @click="openAdmin(selectedSystem, 'relayaction')">继电器动作记录</el-button>
          <el-button @click="openAdmin(selectedSystem, 'useroperation')">用户操作记录</el-button>
          <el-button @click="openAdmin(selectedSystem, 'switchdata')">开关量记录</el-button>
          <el-button v-if="selectedSystem === 'bt'" @click="openAdmin(selectedSystem, 'analogdata')">电压电流记录</el-button>
          <el-button @click="openAdmin(selectedSystem, 'device')">设备信息</el-button>
        </div>
      </div>
    </section>

    <section class="filter-section">
      <div class="filter-header">
        <h2>记录查询</h2>
        <div class="filter-header-actions">
          <span class="last-updated">{{ lastUpdatedText }}</span>
          <el-button :loading="isRefreshing" @click="handleManualRefresh">手动刷新</el-button>
        </div>
      </div>

      <el-form inline class="query-form">
        <el-form-item label="时间范围">
          <el-date-picker
            v-model="timeRange"
            type="daterange"
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            style="width: 280px;"
          />
        </el-form-item>

        <el-form-item label="线路">
          <el-select v-model="selectedLine" clearable placeholder="全部线路" style="width: 240px;">
            <el-option label="全部线路" value="" />
            <el-option v-for="line in lineOptions" :key="line" :label="line" :value="line" />
          </el-select>
        </el-form-item>

        <el-form-item label="设备">
          <el-select v-model="selectedDeviceId" filterable placeholder="全部设备" style="width: 280px;">
            <el-option key="all-devices" label="全部设备" value="all" />
            <el-option
              v-for="device in filteredDeviceOptions"
              :key="device.device_id"
              :label="`${device.name} (${device.device_id})`"
              :value="device.device_id"
            />
          </el-select>
        </el-form-item>

        <el-form-item v-if="activeRecordType === 'alerts'" label="告警码">
          <el-input-number
            v-model="alarmCode"
            :min="0"
            :step="1"
            controls-position="right"
            placeholder="全部"
          />
        </el-form-item>

        <el-form-item v-if="activeRecordType === 'alerts'" label="确认状态">
          <el-select v-model="confirmedFilter" style="width: 160px;">
            <el-option label="全部" value="all" />
            <el-option label="未确认" value="unconfirmed" />
            <el-option label="已确认" value="confirmed" />
          </el-select>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :loading="activeState.loading" @click="handleQuery">查询</el-button>
          <el-button @click="handleReset">重置</el-button>
        </el-form-item>
      </el-form>

      <el-alert
        v-if="errors.devices"
        type="error"
        :closable="false"
        show-icon
        :title="errors.devices"
      />
    </section>

    <section class="table-section">
      <el-tabs v-model="activeRecordType" @tab-change="handleRecordTabChange">
        <el-tab-pane
          v-for="tab in availableRecordTabs"
          :key="tab.type"
          :name="tab.type"
          :label="tab.label"
        />
      </el-tabs>

      <div class="section-header">
        <h2>{{ activeTabLabel }}</h2>
        <div class="section-actions">
          <span class="section-count">{{ activeTotalText }} 条</span>
          <el-button :loading="activeState.loading" size="small" @click="fetchActiveRecord({ refreshTotal: true })">
            刷新
          </el-button>
          <el-button :loading="exporting[activeRecordType]" size="small" @click="exportActiveRecord">
            导出
          </el-button>
          <el-button
            v-if="activeRecordType === 'alerts'"
            type="primary"
            size="small"
            :loading="confirmingSelectedAlerts"
            @click="confirmSelectedAlerts"
          >
            确认选中
          </el-button>
          <el-button v-if="activeState.error" size="small" @click="fetchActiveRecord({ refreshTotal: true })">
            重试
          </el-button>
        </div>
      </div>

      <el-alert
        v-if="activeState.error"
        type="error"
        :closable="false"
        show-icon
        :title="activeState.error"
        class="section-alert"
      />

      <el-table
        v-if="activeRecordType === 'alerts'"
        :data="alertRows"
        row-key="id"
        stripe
        v-loading="activeState.loading"
        @selection-change="handleAlertSelectionChange"
      >
        <el-table-column type="selection" width="44" :selectable="isAlertSelectable" />
        <el-table-column prop="device_id" label="设备ID" width="100" />
        <el-table-column prop="device_name" label="设备名称" min-width="180" />
        <el-table-column prop="alarm_code" label="告警码" width="100" />
        <el-table-column prop="alarm_meaning" label="告警含义" min-width="180" />
        <el-table-column prop="timestamp" label="开始时间" min-width="180">
          <template #default="{ row }">{{ formatToLocalTime(row.timestamp) }}</template>
        </el-table-column>
        <el-table-column prop="timestamp_end" label="结束时间" min-width="180">
          <template #default="{ row }">{{ formatToLocalTime(row.timestamp_end) }}</template>
        </el-table-column>
        <el-table-column prop="duration_seconds" label="持续时长" min-width="130">
          <template #default="{ row }">{{ formatDuration(row.duration_seconds) }}</template>
        </el-table-column>
        <el-table-column prop="is_confirmed" label="确认状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_confirmed ? 'success' : 'warning'">
              {{ row.is_confirmed ? '已确认' : '未确认' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110">
          <template #default="{ row }">
            <el-button
              size="small"
              type="primary"
              :disabled="row.is_confirmed || !row.id"
              :loading="isConfirmingAlert(row.id)"
              @click="confirmHistoricalAlert(row)"
            >
              确认
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-table
        v-else-if="activeRecordType === 'relay-actions'"
        :data="relayRows"
        stripe
        v-loading="activeState.loading"
      >
        <el-table-column prop="device_id" label="设备ID" width="100" />
        <el-table-column prop="device_name" label="设备名称" min-width="180" />
        <el-table-column prop="relay" label="继电器" min-width="140" />
        <el-table-column prop="action" label="动作" min-width="120" />
        <el-table-column v-if="selectedSystem === 'sy'" prop="source" label="来源" width="100" />
        <el-table-column prop="timestamp" label="时间" min-width="180">
          <template #default="{ row }">{{ formatToLocalTime(row.timestamp) }}</template>
        </el-table-column>
      </el-table>

      <el-table
        v-else-if="activeRecordType === 'user-operations'"
        :data="userOperationRows"
        stripe
        v-loading="activeState.loading"
      >
        <el-table-column prop="device_id" label="设备ID" width="100">
          <template #default="{ row }">{{ row.device_id ?? '-' }}</template>
        </el-table-column>
        <el-table-column prop="device_name" label="设备名称" min-width="180">
          <template #default="{ row }">{{ row.device_name || '系统级操作' }}</template>
        </el-table-column>
        <el-table-column prop="function_code" label="操作码" min-width="120" />
        <el-table-column prop="operation" label="操作名称" min-width="150" />
        <el-table-column prop="username" label="用户名" min-width="120">
          <template #default="{ row }">{{ row.username || '-' }}</template>
        </el-table-column>
        <el-table-column prop="timestamp" label="操作时间" min-width="180">
          <template #default="{ row }">{{ formatToLocalTime(row.timestamp) }}</template>
        </el-table-column>
      </el-table>

      <el-table
        v-else-if="activeRecordType === 'switch-data'"
        :data="switchRows"
        stripe
        v-loading="activeState.loading"
      >
        <el-table-column prop="device_id" label="设备ID" width="100" />
        <el-table-column prop="device_name" label="设备名称" min-width="180" />
        <el-table-column prop="switch_status_hex" label="HEX" min-width="180" />
        <el-table-column prop="switch_status_text" label="开关量" min-width="320" show-overflow-tooltip />
        <el-table-column v-if="selectedSystem === 'sy'" prop="version" label="版本" width="100" />
        <el-table-column prop="timestamp" label="时间" min-width="180">
          <template #default="{ row }">{{ formatToLocalTime(row.timestamp) }}</template>
        </el-table-column>
      </el-table>

      <el-table
        v-else-if="activeRecordType === 'analog-data'"
        :data="analogRows"
        stripe
        v-loading="activeState.loading"
      >
        <el-table-column prop="device_id" label="设备ID" width="100" />
        <el-table-column prop="device_name" label="设备名称" min-width="180" />
        <el-table-column prop="voltage_1" label="电压1(V)" min-width="120" />
        <el-table-column prop="current_1" label="电流1(mA)" min-width="130" />
        <el-table-column prop="voltage_2" label="电压2(V)" min-width="120" />
        <el-table-column prop="current_2" label="电流2(mA)" min-width="130" />
        <el-table-column prop="timestamp" label="时间" min-width="180">
          <template #default="{ row }">{{ formatToLocalTime(row.timestamp) }}</template>
        </el-table-column>
      </el-table>

      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="activeState.pagination.page"
          v-model:page-size="activeState.pagination.pageSize"
          :total="activeState.pagination.total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="handleActivePageChange"
          @size-change="handleActiveSizeChange"
        />
      </div>
    </section>
  </div>
</template>

<script lang="ts" setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useUserStore } from '@/stores/userStore';
import { SYSTEM_LABELS, SYSTEMS, getSystemOrigin, type SystemType } from '@/utils/systems';

interface DeviceOption {
  device_id: number;
  name: string;
  line: string;
}

interface AlertRecord {
  id: string;
  device_id: number;
  device_name: string;
  alarm_code: number;
  alarm_meaning: string;
  timestamp: string;
  timestamp_end: string | null;
  is_confirmed: boolean;
  duration_seconds: number;
}

interface RelayActionRecord {
  id: string;
  device?: number;
  device_id?: number;
  device_name?: string;
  relay: string;
  action: string;
  source?: string;
  timestamp: string;
}

interface UserOperationRecord {
  id: string;
  device?: number | null;
  device_id?: number | null;
  device_name?: string | null;
  function_code: string;
  operation: string;
  username: string | null;
  timestamp: string;
}

interface SwitchDataRecord {
  id: string;
  device?: number;
  device_id?: number;
  device_name?: string;
  switch_status_text?: string;
  switch_status_hex?: string;
  version?: string;
  timestamp: string;
}

interface AnalogDataRecord {
  id: string;
  device?: number;
  device_id?: number;
  device_name?: string;
  voltage_1: number;
  current_1: number;
  voltage_2: number;
  current_2: number;
  timestamp: string;
}

type RecordType = 'alerts' | 'relay-actions' | 'user-operations' | 'switch-data' | 'analog-data';

type ListResponse<T> = {
  count?: number | null;
  results: T[];
};

type CountResponse = {
  count: number;
  approximate?: boolean;
};

type RecordState = {
  rows: unknown[];
  loading: boolean;
  error: string | null;
  pagination: {
    page: number;
    pageSize: number;
    total: number;
    approximateTotal: boolean;
  };
};

const systems = SYSTEMS;
const labels = SYSTEM_LABELS;
const RECORDS_SELECTED_SYSTEM_KEY = 'records:selectedSystem';
const userStore = useUserStore();

const recordTabs: Array<{ type: RecordType; label: string; systems: SystemType[] }> = [
  { type: 'alerts', label: '历史告警', systems: ['bt', 'sy'] },
  { type: 'relay-actions', label: '继电器动作', systems: ['bt', 'sy'] },
  { type: 'user-operations', label: '用户操作', systems: ['bt', 'sy'] },
  { type: 'switch-data', label: '开关量', systems: ['bt', 'sy'] },
  { type: 'analog-data', label: '电压电流', systems: ['bt'] },
];

const loadStoredSystem = (): SystemType => {
  if (typeof window === 'undefined') {
    return 'bt';
  }

  const storedSystem = window.localStorage.getItem(RECORDS_SELECTED_SYSTEM_KEY);
  if (storedSystem && systems.includes(storedSystem as SystemType)) {
    return storedSystem as SystemType;
  }

  return 'bt';
};

const persistSelectedSystem = (system: SystemType) => {
  if (typeof window === 'undefined') {
    return;
  }
  window.localStorage.setItem(RECORDS_SELECTED_SYSTEM_KEY, system);
};

const selectedSystem = ref<SystemType>(loadStoredSystem());
const activeRecordType = ref<RecordType>('alerts');

const defaultTimeRange = (): [Date, Date] => {
  const end = new Date();
  end.setHours(23, 59, 59, 999);
  const start = new Date(end);
  start.setDate(start.getDate() - 6);
  start.setHours(0, 0, 0, 0);
  return [start, end];
};

const createRecordState = (): RecordState => ({
  rows: [],
  loading: false,
  error: null,
  pagination: {
    page: 1,
    pageSize: 20,
    total: 0,
    approximateTotal: false,
  },
});

const timeRange = ref<[Date, Date] | undefined>(defaultTimeRange());
const selectedLine = ref<string>('');
const selectedDeviceId = ref<number | 'all'>('all');
const alarmCode = ref<number | undefined>(undefined);
const confirmedFilter = ref<'all' | 'unconfirmed' | 'confirmed'>('unconfirmed');

const lineOptions = ref<string[]>([]);
const deviceOptions = ref<DeviceOption[]>([]);
const lastUpdatedAt = ref<Date | null>(null);
const confirmingAlertIds = ref<string[]>([]);
const selectedAlertRows = ref<AlertRecord[]>([]);
const confirmingSelectedAlerts = ref(false);

const recordStates = reactive<Record<RecordType, RecordState>>({
  alerts: createRecordState(),
  'relay-actions': createRecordState(),
  'user-operations': createRecordState(),
  'switch-data': createRecordState(),
  'analog-data': createRecordState(),
});

const exporting = reactive<Record<RecordType, boolean>>({
  alerts: false,
  'relay-actions': false,
  'user-operations': false,
  'switch-data': false,
  'analog-data': false,
});

const loading = reactive({
  devices: false,
});

const errors = reactive({
  devices: null as string | null,
});

const availableRecordTabs = computed(() => recordTabs.filter((tab) => tab.systems.includes(selectedSystem.value)));
const activeState = computed(() => recordStates[activeRecordType.value]);
const activeTabLabel = computed(() => recordTabs.find((tab) => tab.type === activeRecordType.value)?.label || '');
const isRefreshing = computed(() => loading.devices || activeState.value.loading);

const filteredDeviceOptions = computed(() => {
  if (!selectedLine.value) {
    return deviceOptions.value;
  }
  return deviceOptions.value.filter((device) => device.line === selectedLine.value);
});

const lastUpdatedText = computed(() => {
  if (!lastUpdatedAt.value) {
    return '最后刷新：未刷新';
  }
  return `最后刷新：${formatToLocalTime(lastUpdatedAt.value.toISOString())}`;
});

const activeTotalText = computed(() => {
  const pagination = activeState.value.pagination;
  return `${pagination.approximateTotal ? '约 ' : ''}${pagination.total}`;
});

const alertRows = computed(() => recordStates.alerts.rows as AlertRecord[]);
const relayRows = computed(() => recordStates['relay-actions'].rows as RelayActionRecord[]);
const userOperationRows = computed(() => recordStates['user-operations'].rows as UserOperationRecord[]);
const switchRows = computed(() => recordStates['switch-data'].rows as SwitchDataRecord[]);
const analogRows = computed(() => recordStates['analog-data'].rows as AnalogDataRecord[]);

const formatToLocalTime = (timestamp: string | null): string => {
  if (!timestamp) {
    return '-';
  }

  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return timestamp;
  }

  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZone: 'Asia/Shanghai',
  }).format(date).replace(/\//g, '-').replace(',', '');
};

const formatDuration = (durationSeconds: number): string => {
  if (!Number.isFinite(durationSeconds) || durationSeconds < 0) {
    return '-';
  }

  const days = Math.floor(durationSeconds / 86400);
  const hours = Math.floor((durationSeconds % 86400) / 3600);
  const minutes = Math.floor((durationSeconds % 3600) / 60);
  const seconds = Math.floor(durationSeconds % 60);
  const chunks: string[] = [];

  if (days > 0) {
    chunks.push(`${days}天`);
  }
  if (hours > 0 || days > 0) {
    chunks.push(`${hours}时`);
  }
  if (minutes > 0 || hours > 0 || days > 0) {
    chunks.push(`${minutes}分`);
  }
  chunks.push(`${seconds}秒`);

  return chunks.join(' ');
};

const openAdmin = (system: SystemType, model: string) => {
  window.open(`${getSystemOrigin(system)}/admin/myapp/${model}/`, '_blank');
};

const canOpenAdmin = computed(() => {
  const user = userStore.getUser(selectedSystem.value);
  return !!user?.is_staff;
});

const toStartOfDayIso = (date: Date): string => {
  const value = new Date(date);
  value.setHours(0, 0, 0, 0);
  return value.toISOString();
};

const toEndOfDayIso = (date: Date): string => {
  const value = new Date(date);
  value.setHours(23, 59, 59, 999);
  return value.toISOString();
};

const timeFieldForRecord = (recordType: RecordType): 'timestamp_start' | 'timestamp' => (
  recordType === 'alerts' ? 'timestamp_start' : 'timestamp'
);

const buildRecordQuery = (recordType: RecordType, includePagination: boolean): URLSearchParams => {
  const query = new URLSearchParams();
  const state = recordStates[recordType];
  const timeField = timeFieldForRecord(recordType);

  if (includePagination) {
    query.set('page', String(state.pagination.page));
    query.set('page_size', String(state.pagination.pageSize));
    query.set('include_count', '0');
  }

  if (timeRange.value && timeRange.value.length === 2) {
    query.set(`${timeField}__gte`, toStartOfDayIso(timeRange.value[0]));
    query.set(`${timeField}__lte`, toEndOfDayIso(timeRange.value[1]));
  }

  if (selectedDeviceId.value !== 'all') {
    query.set('device', String(selectedDeviceId.value));
  } else if (selectedLine.value) {
    query.set('device__line', selectedLine.value);
  }

  if (recordType === 'alerts') {
    if (alarmCode.value !== undefined) {
      query.set('alarm_code', String(alarmCode.value));
    }
    if (confirmedFilter.value === 'confirmed') {
      query.set('is_confirmed', 'true');
    } else if (confirmedFilter.value === 'unconfirmed') {
      query.set('is_confirmed', 'false');
    }
  }

  return query;
};

const loadDevicesForSystem = async () => {
  loading.devices = true;
  errors.devices = null;

  try {
    const data = await userStore.requestWithAuth<Record<string, Array<{ device_id: number; name: string }>>>(
      selectedSystem.value,
      {
        method: 'get',
        url: '/devices-list/',
      },
    );

    const lines = Object.keys(data);
    const devices: DeviceOption[] = [];

    lines.forEach((line) => {
      data[line].forEach((device) => {
        devices.push({
          device_id: device.device_id,
          name: device.name,
          line,
        });
      });
    });

    lineOptions.value = lines;
    deviceOptions.value = devices;

    if (selectedLine.value && !lineOptions.value.includes(selectedLine.value)) {
      selectedLine.value = '';
    }

    if (
      selectedDeviceId.value !== 'all' &&
      !deviceOptions.value.some((device) => device.device_id === selectedDeviceId.value)
    ) {
      selectedDeviceId.value = 'all';
    }
  } catch (error) {
    console.error('加载设备列表失败:', error);
    errors.devices = '设备列表加载失败，请重试。';
    lineOptions.value = [];
    deviceOptions.value = [];
  } finally {
    loading.devices = false;
  }
};

const normalizeDeviceName = (deviceId: number | null | undefined, fallbackName?: string | null): string => {
  if (fallbackName) {
    return fallbackName;
  }
  if (deviceId === null || deviceId === undefined) {
    return '系统级操作';
  }
  return deviceOptions.value.find((device) => device.device_id === deviceId)?.name || `设备 ${deviceId}`;
};

const normalizeRows = (recordType: RecordType, rows: unknown[]): unknown[] => {
  if (recordType === 'relay-actions') {
    return (rows as RelayActionRecord[]).map((record) => {
      const deviceId = record.device_id ?? record.device ?? 0;
      return {
        ...record,
        device_id: deviceId,
        device_name: normalizeDeviceName(deviceId, record.device_name),
      };
    });
  }

  if (recordType === 'user-operations') {
    return (rows as UserOperationRecord[]).map((record) => {
      const deviceId = record.device_id ?? record.device ?? null;
      return {
        ...record,
        device_id: deviceId,
        device_name: normalizeDeviceName(deviceId, record.device_name),
      };
    });
  }

  if (recordType === 'switch-data') {
    return (rows as SwitchDataRecord[]).map((record) => {
      const deviceId = record.device_id ?? record.device ?? 0;
      return {
        ...record,
        device_id: deviceId,
        device_name: normalizeDeviceName(deviceId, record.device_name),
        switch_status_text: record.switch_status_text || '-',
        switch_status_hex: record.switch_status_hex || '-',
      };
    });
  }

  if (recordType === 'analog-data') {
    return (rows as AnalogDataRecord[]).map((record) => {
      const deviceId = record.device_id ?? record.device ?? 0;
      return {
        ...record,
        device_id: deviceId,
        device_name: normalizeDeviceName(deviceId, record.device_name),
      };
    });
  }

  return rows;
};

const requestRecordCount = async (recordType: RecordType): Promise<CountResponse> => {
  return userStore.requestWithAuth<CountResponse>(selectedSystem.value, {
    method: 'get',
    url: `/${recordType}/count/`,
    params: buildRecordQuery(recordType, false),
  });
};

const fetchRecord = async (recordType: RecordType, options: { refreshTotal?: boolean } = {}) => {
  const state = recordStates[recordType];
  state.loading = true;
  state.error = null;

  try {
    const data = await userStore.requestWithAuth<ListResponse<unknown>>(selectedSystem.value, {
      method: 'get',
      url: `/${recordType}/`,
      params: buildRecordQuery(recordType, true),
    });

    state.rows = normalizeRows(recordType, data.results || []);

    if (options.refreshTotal ?? true) {
      const countData = await requestRecordCount(recordType);
      state.pagination.total = countData.count ?? state.rows.length;
      state.pagination.approximateTotal = Boolean(countData.approximate);
    } else if (state.pagination.total === 0) {
      state.pagination.total = state.rows.length;
      state.pagination.approximateTotal = false;
    }

    if (recordType === 'alerts') {
      selectedAlertRows.value = [];
    }
    lastUpdatedAt.value = new Date();
  } catch (error) {
    console.error(`加载${recordType}失败:`, error);
    state.error = `${recordTabs.find((tab) => tab.type === recordType)?.label || '记录'}加载失败，请重试。`;
    state.rows = [];
    state.pagination.total = 0;
    state.pagination.approximateTotal = false;
    throw error;
  } finally {
    state.loading = false;
  }
};

const fetchActiveRecord = async (options: { refreshTotal?: boolean } = {}) => {
  try {
    await fetchRecord(activeRecordType.value, options);
  } catch {
    // fetchRecord already stores the user-facing error.
  }
};

const refreshAll = async (reloadDevices: boolean) => {
  if (reloadDevices) {
    await loadDevicesForSystem();
  }
  await fetchActiveRecord({ refreshTotal: true });
};

const resetPaginationForAll = () => {
  Object.values(recordStates).forEach((state) => {
    state.pagination.page = 1;
  });
};

const handleManualRefresh = async () => {
  await refreshAll(false);
};

const handleQuery = async () => {
  resetPaginationForAll();
  await fetchActiveRecord({ refreshTotal: true });
};

const handleReset = async () => {
  const systemChanged = selectedSystem.value !== 'bt';
  selectedSystem.value = 'bt';
  activeRecordType.value = 'alerts';
  timeRange.value = defaultTimeRange();
  selectedLine.value = '';
  selectedDeviceId.value = 'all';
  alarmCode.value = undefined;
  confirmedFilter.value = 'unconfirmed';
  Object.values(recordStates).forEach((state) => {
    state.pagination.page = 1;
    state.pagination.pageSize = 20;
  });
  if (systemChanged) {
    return;
  }
  await refreshAll(true);
};

const handleRecordTabChange = async () => {
  await fetchActiveRecord({ refreshTotal: true });
};

const isConfirmingAlert = (alertId?: string): boolean => {
  if (!alertId) {
    return false;
  }
  return confirmingAlertIds.value.includes(alertId);
};

const confirmHistoricalAlert = async (alert: AlertRecord) => {
  if (alert.is_confirmed || !alert.id || isConfirmingAlert(alert.id)) {
    return;
  }

  confirmingAlertIds.value = [...confirmingAlertIds.value, alert.id];
  try {
    await userStore.requestWithAuth(selectedSystem.value, {
      method: 'post',
      url: `/alerts/${alert.id}/confirm/`,
    });
    alert.is_confirmed = true;
    ElMessage.success('历史告警已确认');
    await requestRecordCount('alerts').then((countData) => {
      recordStates.alerts.pagination.total = countData.count ?? recordStates.alerts.pagination.total;
      recordStates.alerts.pagination.approximateTotal = Boolean(countData.approximate);
    });
  } catch (error) {
    console.error('确认历史告警失败:', error);
    ElMessage.error('确认失败，请重试。');
  } finally {
    confirmingAlertIds.value = confirmingAlertIds.value.filter((id) => id !== alert.id);
  }
};

const isAlertSelectable = (row: AlertRecord) => !row.is_confirmed && !!row.id;

const handleAlertSelectionChange = (rows: AlertRecord[]) => {
  selectedAlertRows.value = rows;
};

const confirmSelectedAlerts = async () => {
  const ids = selectedAlertRows.value.filter((row) => !row.is_confirmed && row.id).map((row) => row.id);
  if (ids.length === 0) {
    ElMessage.warning('请选择未确认的历史告警');
    return;
  }

  try {
    await ElMessageBox.confirm(`确认选中的 ${ids.length} 条历史告警？`, '确认选中告警', {
      type: 'warning',
      confirmButtonText: '确认',
      cancelButtonText: '取消',
    });
  } catch {
    return;
  }

  confirmingSelectedAlerts.value = true;
  try {
    const result = await userStore.requestWithAuth<{ confirmed: number; skipped: number }>(selectedSystem.value, {
      method: 'post',
      url: '/alerts/bulk-confirm/',
      data: { ids },
    });
    ElMessage.success(`已确认 ${result.confirmed} 条，跳过 ${result.skipped} 条`);
    await fetchRecord('alerts', { refreshTotal: true });
  } catch (error) {
    console.error('批量确认历史告警失败:', error);
    ElMessage.error('确认选中失败，请重试。');
  } finally {
    confirmingSelectedAlerts.value = false;
  }
};

const getExportFilename = (recordType: RecordType) => {
  const date = new Date();
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');
  return `${selectedSystem.value}-${recordType}-${year}${month}${day}.csv`;
};

const exportActiveRecord = async () => {
  const recordType = activeRecordType.value;
  exporting[recordType] = true;
  try {
    const blob = await userStore.requestWithAuth<Blob>(selectedSystem.value, {
      method: 'get',
      url: `/${recordType}/export/`,
      params: buildRecordQuery(recordType, false),
      responseType: 'blob',
    });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = getExportFilename(recordType);
    link.click();
    URL.revokeObjectURL(link.href);
  } catch (error) {
    console.error('导出记录失败:', error);
    ElMessage.error('导出失败，请重试。');
  } finally {
    exporting[recordType] = false;
  }
};

const handleActivePageChange = async () => {
  await fetchActiveRecord({ refreshTotal: false });
};

const handleActiveSizeChange = async () => {
  activeState.value.pagination.page = 1;
  await fetchActiveRecord({ refreshTotal: false });
};

watch(selectedSystem, async (system) => {
  persistSelectedSystem(system);
  selectedLine.value = '';
  selectedDeviceId.value = 'all';
  if (!availableRecordTabs.value.some((tab) => tab.type === activeRecordType.value)) {
    activeRecordType.value = 'alerts';
  }
  resetPaginationForAll();
  await refreshAll(true);
});

watch(selectedLine, () => {
  if (
    selectedDeviceId.value !== 'all' &&
    !filteredDeviceOptions.value.some((device) => device.device_id === selectedDeviceId.value)
  ) {
    selectedDeviceId.value = 'all';
  }
});

onMounted(async () => {
  persistSelectedSystem(selectedSystem.value);
  await refreshAll(true);
});
</script>

<style scoped>
.records-view {
  display: flex;
  flex-direction: column;
  gap: 18px;
  margin-top: 16px;
}

.system-selector-card,
.filter-section,
.table-section {
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  padding: 16px;
  background: #ffffff;
}

.system-selector-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.system-selector-title {
  margin: 0;
}

.system-selector {
  max-width: 180px;
}

.system-summary-card {
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  padding: 16px;
  background: #ffffff;
}

.summary-header,
.filter-header,
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.summary-header h2,
.filter-header h2,
.section-header h2 {
  margin: 0;
}

.summary-actions,
.filter-header-actions,
.section-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.last-updated,
.section-count {
  color: #5b6b82;
  font-size: 13px;
}

.query-form {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 8px;
  margin-top: 14px;
}

.section-alert {
  margin-bottom: 12px;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

@media (max-width: 768px) {
  .summary-header,
  .filter-header,
  .section-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .query-form :deep(.el-form-item) {
    width: 100%;
  }

  .query-form :deep(.el-form-item__content),
  .query-form :deep(.el-select),
  .query-form :deep(.el-date-editor) {
    width: 100% !important;
  }

  .pagination-wrap {
    justify-content: flex-start;
    overflow-x: auto;
  }
}
</style>
