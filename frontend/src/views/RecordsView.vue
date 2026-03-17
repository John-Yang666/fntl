<template>
  <div class="records-view">
    <section class="filter-section">
      <div class="filter-header">
        <h2>记录查询</h2>
        <div class="filter-header-actions">
          <span class="last-updated">{{ lastUpdatedText }}</span>
          <el-button :loading="isRefreshing" @click="handleManualRefresh">手动刷新</el-button>
        </div>
      </div>

      <el-form inline class="query-form">
        <el-form-item label="系统">
          <el-select v-model="selectedSystem" style="width: 140px;">
            <el-option v-for="system in systems" :key="system" :label="labels[system]" :value="system" />
          </el-select>
        </el-form-item>

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
          <el-select
            v-model="selectedDeviceId"
            filterable
            placeholder="全部设备"
            style="width: 280px;"
          >
            <el-option key="all-devices" label="全部设备" value="all" />
            <el-option
              v-for="device in filteredDeviceOptions"
              :key="device.device_id"
              :label="`${device.name} (${device.device_id})`"
              :value="device.device_id"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="告警码">
          <el-input-number
            v-model="alarmCode"
            :min="0"
            :step="1"
            controls-position="right"
            placeholder="全部"
          />
        </el-form-item>

        <el-form-item label="确认状态">
          <el-select v-model="confirmedFilter" style="width: 160px;">
            <el-option label="全部" value="all" />
            <el-option label="未确认" value="unconfirmed" />
            <el-option label="已确认" value="confirmed" />
          </el-select>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :loading="loading.alerts || loading.relayActions" @click="handleQuery">
            查询
          </el-button>
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

    <section class="system-summary-card">
      <div class="summary-header">
        <h2>{{ labels[selectedSystem] }} 记录概览</h2>
        <div class="summary-actions">
          <span class="summary-actions-label">打开后端界面：</span>
          <el-button @click="openAdmin(selectedSystem, 'alarmdata')">历史告警记录</el-button>
          <el-button @click="openAdmin(selectedSystem, 'relayaction')">继电器动作记录</el-button>
          <el-button @click="openAdmin(selectedSystem, 'useroperation')">用户操作记录</el-button>
        </div>
      </div>
      <div class="summary-stats">
        <div class="stat-card">
          <span class="stat-label">历史告警</span>
          <strong>{{ alertsPagination.total }}</strong>
        </div>
        <div class="stat-card">
          <span class="stat-label">继电器动作</span>
          <strong>{{ relayPagination.total }}</strong>
        </div>
        <div class="stat-card">
          <span class="stat-label">用户操作</span>
          <strong>{{ userOperationPagination.total }}</strong>
        </div>
      </div>
    </section>

    <section class="table-section">
      <div class="section-header">
        <h2>历史告警</h2>
        <div class="section-actions">
          <span class="section-count">{{ alertsPagination.total }} 条</span>
          <el-button v-if="errors.alerts" size="small" @click="retryAlerts">重试</el-button>
        </div>
      </div>

      <el-alert
        v-if="errors.alerts"
        type="error"
        :closable="false"
        show-icon
        :title="errors.alerts"
        class="section-alert"
      />

      <el-table :data="alerts" stripe v-loading="loading.alerts">
        <el-table-column prop="device_id" label="设备ID" width="100" />
        <el-table-column prop="device_name" label="设备名称" min-width="180" />
        <el-table-column prop="alarm_code" label="告警码" width="100" />
        <el-table-column prop="alarm_meaning" label="告警含义" min-width="180" />
        <el-table-column prop="timestamp" label="开始时间" min-width="180">
          <template #default="{ row }">
            {{ formatToLocalTime(row.timestamp) }}
          </template>
        </el-table-column>
        <el-table-column prop="timestamp_end" label="结束时间" min-width="180">
          <template #default="{ row }">
            {{ formatToLocalTime(row.timestamp_end) }}
          </template>
        </el-table-column>
        <el-table-column prop="duration_seconds" label="持续时长" min-width="130">
          <template #default="{ row }">
            {{ formatDuration(row.duration_seconds) }}
          </template>
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

      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="alertsPagination.page"
          v-model:page-size="alertsPagination.pageSize"
          :total="alertsPagination.total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="handleAlertsPageChange"
          @size-change="handleAlertsSizeChange"
        />
      </div>
    </section>

    <section class="table-section">
      <div class="section-header">
        <h2>继电器动作</h2>
        <div class="section-actions">
          <span class="section-count">{{ relayPagination.total }} 条</span>
          <el-button v-if="errors.relayActions" size="small" @click="retryRelayActions">重试</el-button>
        </div>
      </div>

      <el-alert
        v-if="errors.relayActions"
        type="error"
        :closable="false"
        show-icon
        :title="errors.relayActions"
        class="section-alert"
      />

      <el-table :data="relayActions" stripe v-loading="loading.relayActions">
        <el-table-column prop="device_id" label="设备ID" width="100" />
        <el-table-column prop="device_name" label="设备名称" min-width="180" />
        <el-table-column prop="relay" label="继电器" min-width="140" />
        <el-table-column prop="action" label="动作" min-width="120" />
        <el-table-column prop="timestamp" label="时间" min-width="180">
          <template #default="{ row }">
            {{ formatToLocalTime(row.timestamp) }}
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="relayPagination.page"
          v-model:page-size="relayPagination.pageSize"
          :total="relayPagination.total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="handleRelayPageChange"
          @size-change="handleRelaySizeChange"
        />
      </div>
    </section>

    <section class="table-section">
      <div class="section-header">
        <h2>用户操作记录</h2>
        <div class="section-actions">
          <span class="section-count">{{ userOperationPagination.total }} 条</span>
          <el-button v-if="errors.userOperations" size="small" @click="retryUserOperations">重试</el-button>
        </div>
      </div>

      <el-alert
        v-if="errors.userOperations"
        type="error"
        :closable="false"
        show-icon
        :title="errors.userOperations"
        class="section-alert"
      />

      <el-table :data="userOperations" stripe v-loading="loading.userOperations">
        <el-table-column prop="device_id" label="设备ID" width="100" />
        <el-table-column prop="device_name" label="设备名称" min-width="180" />
        <el-table-column prop="function_code" label="操作码" min-width="120" />
        <el-table-column prop="operation" label="操作名称" min-width="150" />
        <el-table-column prop="username" label="用户名" min-width="120">
          <template #default="{ row }">
            {{ row.username || '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="timestamp" label="操作时间" min-width="180">
          <template #default="{ row }">
            {{ formatToLocalTime(row.timestamp) }}
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="userOperationPagination.page"
          v-model:page-size="userOperationPagination.pageSize"
          :total="userOperationPagination.total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="handleUserOperationPageChange"
          @size-change="handleUserOperationSizeChange"
        />
      </div>
    </section>
  </div>
</template>

<script lang="ts" setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import axios from 'axios';
import { ElMessage } from 'element-plus';
import { SYSTEM_LABELS, SYSTEMS, getApiBase, getSystemOrigin, type SystemType } from '@/utils/systems';

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
  device_id: number;
  device_name: string;
  relay: string;
  action: string;
  timestamp: string;
}

interface UserOperationRecord {
  id: string;
  device_id: number;
  device_name: string;
  function_code: string;
  operation: string;
  username: string | null;
  timestamp: string;
}

type ListResponse<T> = {
  count: number;
  results: T[];
};

const systems = SYSTEMS;
const labels = SYSTEM_LABELS;
const selectedSystem = ref<SystemType>('bt');

const defaultTimeRange = (): [Date, Date] => {
  const end = new Date();
  end.setHours(23, 59, 59, 999);
  const start = new Date(end);
  start.setDate(start.getDate() - 6);
  start.setHours(0, 0, 0, 0);
  return [start, end];
};

const timeRange = ref<[Date, Date]>(defaultTimeRange());
const selectedLine = ref<string>('');
const selectedDeviceId = ref<number | 'all'>('all');
const alarmCode = ref<number | undefined>(undefined);
const confirmedFilter = ref<'all' | 'unconfirmed' | 'confirmed'>('unconfirmed');

const lineOptions = ref<string[]>([]);
const deviceOptions = ref<DeviceOption[]>([]);
const alerts = ref<AlertRecord[]>([]);
const relayActions = ref<RelayActionRecord[]>([]);
const userOperations = ref<UserOperationRecord[]>([]);
const lastUpdatedAt = ref<Date | null>(null);
const confirmingAlertIds = ref<string[]>([]);

const loading = reactive({
  devices: false,
  alerts: false,
  relayActions: false,
  userOperations: false,
});

const errors = reactive({
  devices: null as string | null,
  alerts: null as string | null,
  relayActions: null as string | null,
  userOperations: null as string | null,
});

const alertsPagination = reactive({
  page: 1,
  pageSize: 20,
  total: 0,
});

const relayPagination = reactive({
  page: 1,
  pageSize: 20,
  total: 0,
});

const userOperationPagination = reactive({
  page: 1,
  pageSize: 20,
  total: 0,
});

const isRefreshing = computed(() =>
  loading.devices || loading.alerts || loading.relayActions || loading.userOperations,
);

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

const applyCommonFilters = (query: URLSearchParams, timeField: 'timestamp_start' | 'timestamp') => {
  if (timeRange.value && timeRange.value.length === 2) {
    query.set(`${timeField}__gte`, toStartOfDayIso(timeRange.value[0]));
    query.set(`${timeField}__lte`, toEndOfDayIso(timeRange.value[1]));
  }

  if (selectedDeviceId.value !== 'all') {
    query.set('device', String(selectedDeviceId.value));
  } else if (selectedLine.value) {
    query.set('device__line', selectedLine.value);
  }
};

const loadDevicesForSystem = async () => {
  loading.devices = true;
  errors.devices = null;

  try {
    const response = await axios.get(`${getApiBase(selectedSystem.value)}/devices-list/`);
    const data = response.data as Record<string, Array<{ device_id: number; name: string }>>;

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

const fetchAlerts = async () => {
  loading.alerts = true;
  errors.alerts = null;

  try {
    const query = new URLSearchParams();
    query.set('page', String(alertsPagination.page));
    query.set('page_size', String(alertsPagination.pageSize));
    applyCommonFilters(query, 'timestamp_start');

    if (alarmCode.value !== undefined) {
      query.set('alarm_code', String(alarmCode.value));
    }

    if (confirmedFilter.value === 'confirmed') {
      query.set('is_confirmed', 'true');
    } else if (confirmedFilter.value === 'unconfirmed') {
      query.set('is_confirmed', 'false');
    }

    const response = await axios.get(`${getApiBase(selectedSystem.value)}/alerts/?${query.toString()}`);
    const data = response.data as ListResponse<AlertRecord>;

    alerts.value = data.results;
    alertsPagination.total = data.count ?? data.results.length;
  } catch (error) {
    console.error('加载历史告警失败:', error);
    errors.alerts = '历史告警加载失败，请重试。';
    alerts.value = [];
    alertsPagination.total = 0;
    throw error;
  } finally {
    loading.alerts = false;
  }
};

const resolveDeviceName = (deviceId: number, fallbackName?: string): string => {
  if (fallbackName) {
    return fallbackName;
  }
  return deviceOptions.value.find((device) => device.device_id === deviceId)?.name || `设备 ${deviceId}`;
};

const fetchRelayActions = async () => {
  loading.relayActions = true;
  errors.relayActions = null;

  try {
    const query = new URLSearchParams();
    query.set('page', String(relayPagination.page));
    query.set('page_size', String(relayPagination.pageSize));
    applyCommonFilters(query, 'timestamp');

    const response = await axios.get(`${getApiBase(selectedSystem.value)}/relay-actions/?${query.toString()}`);
    const data = response.data as ListResponse<{
      id: string;
      device?: number;
      device_id?: number;
      device_name?: string;
      relay: string;
      action: string;
      timestamp: string;
    }>;

    relayActions.value = data.results.map((record) => {
      const deviceId = record.device_id ?? record.device ?? 0;
      return {
        id: record.id,
        device_id: deviceId,
        device_name: resolveDeviceName(deviceId, record.device_name),
        relay: record.relay,
        action: record.action,
        timestamp: record.timestamp,
      };
    });

    relayPagination.total = data.count ?? data.results.length;
  } catch (error) {
    console.error('加载继电器动作失败:', error);
    errors.relayActions = '继电器动作加载失败，请重试。';
    relayActions.value = [];
    relayPagination.total = 0;
    throw error;
  } finally {
    loading.relayActions = false;
  }
};

const fetchUserOperations = async () => {
  loading.userOperations = true;
  errors.userOperations = null;

  try {
    const query = new URLSearchParams();
    query.set('page', String(userOperationPagination.page));
    query.set('page_size', String(userOperationPagination.pageSize));
    applyCommonFilters(query, 'timestamp');

    const response = await axios.get(`${getApiBase(selectedSystem.value)}/user-operations/?${query.toString()}`);
    const data = response.data as ListResponse<{
      id: string;
      device?: number;
      device_id?: number;
      device_name?: string;
      function_code: string;
      operation: string;
      username: string | null;
      timestamp: string;
    }>;

    userOperations.value = data.results.map((record) => {
      const deviceId = record.device_id ?? record.device ?? 0;
      return {
        id: record.id,
        device_id: deviceId,
        device_name: resolveDeviceName(deviceId, record.device_name),
        function_code: record.function_code,
        operation: record.operation,
        username: record.username,
        timestamp: record.timestamp,
      };
    });
    userOperationPagination.total = data.count ?? data.results.length;
  } catch (error) {
    console.error('加载用户操作记录失败:', error);
    errors.userOperations = '用户操作记录加载失败，请重试。';
    userOperations.value = [];
    userOperationPagination.total = 0;
    throw error;
  } finally {
    loading.userOperations = false;
  }
};

const refreshRecords = async () => {
  const results = await Promise.allSettled([fetchAlerts(), fetchRelayActions(), fetchUserOperations()]);
  if (results.some((result) => result.status === 'fulfilled')) {
    lastUpdatedAt.value = new Date();
  }
};

const refreshAll = async (reloadDevices: boolean) => {
  if (reloadDevices) {
    await loadDevicesForSystem();
  }
  await refreshRecords();
};

const handleManualRefresh = async () => {
  await refreshAll(false);
};

const handleQuery = async () => {
  alertsPagination.page = 1;
  relayPagination.page = 1;
  userOperationPagination.page = 1;
  await refreshRecords();
};

const handleReset = async () => {
  const systemChanged = selectedSystem.value !== 'bt';
  selectedSystem.value = 'bt';
  timeRange.value = defaultTimeRange();
  selectedLine.value = '';
  selectedDeviceId.value = 'all';
  alarmCode.value = undefined;
  confirmedFilter.value = 'unconfirmed';
  alertsPagination.page = 1;
  relayPagination.page = 1;
  userOperationPagination.page = 1;
  alertsPagination.pageSize = 20;
  relayPagination.pageSize = 20;
  userOperationPagination.pageSize = 20;
  if (systemChanged) {
    return;
  }
  await refreshAll(true);
};

const retryAlerts = async () => {
  try {
    await fetchAlerts();
    lastUpdatedAt.value = new Date();
  } catch {
    // error already handled in fetchAlerts
  }
};

const retryRelayActions = async () => {
  try {
    await fetchRelayActions();
    lastUpdatedAt.value = new Date();
  } catch {
    // error already handled in fetchRelayActions
  }
};

const retryUserOperations = async () => {
  try {
    await fetchUserOperations();
    lastUpdatedAt.value = new Date();
  } catch {
    // error already handled in fetchUserOperations
  }
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
    await axios.post(`${getApiBase(selectedSystem.value)}/alerts/${alert.id}/confirm/`);
    alert.is_confirmed = true;
    ElMessage.success('历史告警已确认');
  } catch (error) {
    console.error('确认历史告警失败:', error);
    ElMessage.error('确认失败，请重试。');
  } finally {
    confirmingAlertIds.value = confirmingAlertIds.value.filter((id) => id !== alert.id);
  }
};

const handleAlertsPageChange = async () => {
  await fetchAlerts();
};

const handleAlertsSizeChange = async () => {
  alertsPagination.page = 1;
  await fetchAlerts();
};

const handleRelayPageChange = async () => {
  await fetchRelayActions();
};

const handleRelaySizeChange = async () => {
  relayPagination.page = 1;
  await fetchRelayActions();
};

const handleUserOperationPageChange = async () => {
  await fetchUserOperations();
};

const handleUserOperationSizeChange = async () => {
  userOperationPagination.page = 1;
  await fetchUserOperations();
};

watch(selectedSystem, async () => {
  selectedLine.value = '';
  selectedDeviceId.value = 'all';
  alertsPagination.page = 1;
  relayPagination.page = 1;
  userOperationPagination.page = 1;
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

.filter-section {
  border: 1px solid #dcdfe6;
  border-radius: 12px;
  padding: 16px;
  background: #ffffff;
}

.filter-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}

.filter-header h2 {
  margin: 0;
}

.filter-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.last-updated {
  color: #5b6b82;
  font-size: 13px;
}

.query-form {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 8px;
}

.system-summary-card {
  border: 1px solid #dcdfe6;
  border-radius: 12px;
  padding: 20px;
  background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
}

.summary-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 16px;
}

.summary-header h2 {
  margin: 0;
}

.summary-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.summary-actions-label {
  color: #5b6b82;
  font-size: 14px;
}

.summary-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.stat-card {
  padding: 14px 16px;
  border-radius: 10px;
  background: #eef5ff;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.stat-label {
  color: #5b6b82;
  font-size: 14px;
}

.stat-card strong {
  font-size: 24px;
  color: #1d4ed8;
}

.table-section {
  border: 1px solid #dcdfe6;
  border-radius: 12px;
  padding: 20px;
  background: #ffffff;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  gap: 10px;
}

.section-header h2 {
  margin: 0;
}

.section-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.section-count {
  color: #5b6b82;
  font-size: 14px;
}

.section-alert {
  margin-bottom: 12px;
}

.pagination-wrap {
  margin-top: 14px;
  display: flex;
  justify-content: flex-end;
}
</style>
