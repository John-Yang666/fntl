<template>
  <section class="alerts-view" data-testid="alerts-view">
    <div class="page-heading">
      <div>
        <h2>告警详情</h2>
        <p>展示所选监控设备的当前告警和未确认历史告警。</p>
      </div>
      <div class="summary">
        <span>当前 {{ currentCount }}</span>
        <span>未确认历史 {{ historicalCount }}</span>
        <span class="pending">待确认 {{ unconfirmedCount }}</span>
      </div>
    </div>

    <div class="filter-container">
      <select v-model="selectedSystem">
        <option value="">所有系统</option>
        <option value="bt">BT</option>
        <option value="sy">SY</option>
      </select>
      <select v-model="selectedDevice">
        <option value="">所有设备</option>
        <option v-for="device in deviceNames" :key="device" :value="device">{{ device }}</option>
      </select>
      <select v-model="selectedStatus">
        <option value="">所有状态</option>
        <option value="unconfirmed">未确认</option>
        <option value="confirmed">已确认</option>
      </select>
      <select v-model="selectedAlarmMeaning">
        <option value="">所有告警</option>
        <option v-for="meaning in alarmMeanings" :key="meaning" :value="meaning">{{ meaning }}</option>
      </select>
      <el-button :loading="loading" @click="fetchAlerts">刷新</el-button>
    </div>

    <el-tabs v-model="activeAlarmTab" class="alarm-tabs" data-testid="alarm-detail-tabs">
      <el-tab-pane :label="`当前告警（${filteredCurrentAlerts.length}）`" name="current">
    <section class="table-section" aria-labelledby="current-alerts-heading" data-testid="current-alerts-table">
      <div class="table-heading">
        <h3 id="current-alerts-heading">当前告警（{{ filteredCurrentAlerts.length }}）</h3>
        <el-button
          type="primary"
          :disabled="selectedCurrentConfirmable.length === 0"
          :loading="confirming"
          @click="confirmSelectedCurrent"
        >
          批量确认当前告警（{{ selectedCurrentConfirmable.length }}）
        </el-button>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th class="check-column">
                <input
                  type="checkbox"
                  :checked="allVisibleCurrentSelected"
                  :disabled="visibleCurrentConfirmable.length === 0"
                  aria-label="选择全部可确认当前告警"
                  @change="toggleAllCurrent"
                />
              </th>
              <th>序号</th>
              <th>系统</th>
              <th>设备ID</th>
              <th>设备名称</th>
              <th>告警码</th>
              <th>告警含义</th>
              <th>起始时间</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(alert, index) in filteredCurrentAlerts" :key="alert.uniqueKey">
              <td class="check-column">
                <input
                  v-if="!alert.confirmed"
                  v-model="selectedKeys"
                  type="checkbox"
                  :value="alert.uniqueKey"
                  :aria-label="`选择${alert.device_name}当前告警`"
                />
              </td>
              <td>{{ index + 1 }}</td>
              <td>{{ alert.system.toUpperCase() }}</td>
              <td>{{ alert.device_id }}</td>
              <td>{{ alert.device_name }}</td>
              <td>{{ alert.alarm_code }}</td>
              <td>{{ alert.alarm_meaning }}</td>
              <td>{{ formatToLocalTime(alert.timestamp) }}</td>
              <td><span :class="{ pending: !alert.confirmed }">{{ alert.confirmed ? '已确认' : '未确认' }}</span></td>
              <td>
                <el-button v-if="!alert.confirmed" link type="primary" @click="confirmAlerts([alert])">确认</el-button>
                <span v-else>—</span>
              </td>
            </tr>
            <tr v-if="!loading && filteredCurrentAlerts.length === 0">
              <td colspan="10" class="empty-row">暂无符合条件的当前告警</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
      </el-tab-pane>

      <el-tab-pane :label="`未确认历史告警（${filteredHistoricalAlerts.length}）`" name="history">
    <section class="table-section" aria-labelledby="historical-alerts-heading" data-testid="historical-alerts-table">
      <div class="table-heading">
        <h3 id="historical-alerts-heading">未确认历史告警（{{ filteredHistoricalAlerts.length }}）</h3>
        <el-button
          type="primary"
          :disabled="selectedHistoricalConfirmable.length === 0"
          :loading="confirming"
          @click="confirmSelectedHistorical"
        >
          批量确认历史告警（{{ selectedHistoricalConfirmable.length }}）
        </el-button>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th class="check-column">
                <input
                  type="checkbox"
                  :checked="allVisibleHistoricalSelected"
                  :disabled="visibleHistoricalConfirmable.length === 0"
                  aria-label="选择全部未确认历史告警"
                  @change="toggleAllHistorical"
                />
              </th>
              <th>序号</th>
              <th>系统</th>
              <th>设备ID</th>
              <th>设备名称</th>
              <th>告警码</th>
              <th>告警含义</th>
              <th>起始时间</th>
              <th>结束时间</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(alert, index) in filteredHistoricalAlerts" :key="alert.uniqueKey">
              <td class="check-column">
                <input
                  v-model="selectedKeys"
                  type="checkbox"
                  :value="alert.uniqueKey"
                  :aria-label="`选择${alert.device_name}历史告警`"
                />
              </td>
              <td>{{ index + 1 }}</td>
              <td>{{ alert.system.toUpperCase() }}</td>
              <td>{{ alert.device_id }}</td>
              <td>{{ alert.device_name }}</td>
              <td>{{ alert.alarm_code }}</td>
              <td>{{ alert.alarm_meaning }}</td>
              <td>{{ formatToLocalTime(alert.timestamp) }}</td>
              <td>{{ alert.timestamp_end ? formatToLocalTime(alert.timestamp_end) : '—' }}</td>
              <td><span class="pending">未确认</span></td>
              <td><el-button link type="primary" @click="confirmAlerts([alert])">确认</el-button></td>
            </tr>
            <tr v-if="!loading && filteredHistoricalAlerts.length === 0">
              <td colspan="11" class="empty-row">暂无符合条件的未确认历史告警</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
      </el-tab-pane>
    </el-tabs>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { useUserStore } from '@/stores/userStore';
import { SYSTEMS, type SystemType } from '@/utils/systems';

type AlarmSource = 'current' | 'history';

interface Alert {
  system: SystemType;
  source: AlarmSource;
  occurrenceId: string;
  uniqueKey: string;
  device_id: number;
  device_name: string;
  alarm_code: number;
  alarm_meaning: string;
  timestamp: string;
  timestamp_end: string | null;
  confirmed: boolean;
}

interface CurrentAlarmResponse {
  id: string;
  device_id: number;
  device_name: string;
  alarm_code: number;
  alarm_meaning: string;
  timestamp: string;
  confirmed: boolean;
}

interface HistoricalAlarmResponse {
  id: string;
  device_id: number;
  device_name: string;
  alarm_code: number;
  alarm_meaning: string;
  timestamp: string;
  timestamp_end: string | null;
  is_confirmed: boolean;
}

interface Page<T> {
  next: string | null;
  results: T[];
}

const alerts = ref<Alert[]>([]);
const activeAlarmTab = ref<AlarmSource>('current');
const selectedSystem = ref('');
const selectedDevice = ref('');
const selectedStatus = ref('');
const selectedAlarmMeaning = ref('');
const selectedKeys = ref<string[]>([]);
const loading = ref(false);
const confirming = ref(false);
const userStore = useUserStore();
let refreshTimer: ReturnType<typeof setTimeout> | null = null;

const fetchAllHistorical = async (system: SystemType) => {
  const rows: HistoricalAlarmResponse[] = [];
  let url: string | null = '/alerts/?is_confirmed=false&monitored=true&page_size=500';
  while (url) {
    const page: Page<HistoricalAlarmResponse> = await userStore.requestWithAuth(system, {
      method: 'get',
      url,
    });
    rows.push(...page.results);
    url = page.next;
  }
  return rows;
};

const fetchAlerts = async () => {
  loading.value = true;
  try {
    const responses = await Promise.allSettled(SYSTEMS.map(async (system) => {
      const [current, history] = await Promise.all([
        userStore.requestWithAuth<CurrentAlarmResponse[]>(system, { method: 'get', url: '/active-alarms/' }),
        fetchAllHistorical(system),
      ]);
      return { system, current, history };
    }));

    alerts.value = responses.flatMap((result, index) => {
      if (result.status === 'rejected') {
        console.error(`获取 ${SYSTEMS[index].toUpperCase()} 告警详情失败`, result.reason);
        return [];
      }
      const { system, current, history } = result.value;
      return [
        ...current.map((alarm): Alert => ({
          system,
          source: 'current',
          occurrenceId: alarm.id,
          uniqueKey: `${system}:current:${alarm.id}`,
          ...alarm,
          timestamp_end: null,
        })),
        ...history.map((alarm): Alert => ({
          system,
          source: 'history',
          occurrenceId: alarm.id,
          uniqueKey: `${system}:history:${alarm.id}`,
          ...alarm,
          confirmed: alarm.is_confirmed,
        })),
      ];
    });
    const currentKeys = new Set(alerts.value.filter((alert) => !alert.confirmed).map((alert) => alert.uniqueKey));
    selectedKeys.value = selectedKeys.value.filter((key) => currentKeys.has(key));
  } finally {
    loading.value = false;
  }
};

const deviceNames = computed(() => Array.from(new Set(alerts.value.map((alert) => alert.device_name))).sort());
const alarmMeanings = computed(() => Array.from(new Set(alerts.value.map((alert) => alert.alarm_meaning))).sort());
const currentCount = computed(() => alerts.value.filter((alert) => alert.source === 'current').length);
const historicalCount = computed(() => alerts.value.filter((alert) => alert.source === 'history').length);
const unconfirmedCount = computed(() => alerts.value.filter((alert) => !alert.confirmed).length);

const filteredAlerts = computed(() => alerts.value
  .filter((alert) =>
    (!selectedSystem.value || alert.system === selectedSystem.value) &&
    (!selectedDevice.value || alert.device_name === selectedDevice.value) &&
    (!selectedAlarmMeaning.value || alert.alarm_meaning === selectedAlarmMeaning.value) &&
    (!selectedStatus.value || (selectedStatus.value === 'confirmed' ? alert.confirmed : !alert.confirmed)),
  )
  .sort((a, b) => {
    if (a.confirmed !== b.confirmed) return a.confirmed ? 1 : -1;
    return new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime();
  }));

const filteredCurrentAlerts = computed(() => filteredAlerts.value.filter((alert) => alert.source === 'current'));
const filteredHistoricalAlerts = computed(() => filteredAlerts.value.filter((alert) => alert.source === 'history'));
const visibleCurrentConfirmable = computed(() => filteredCurrentAlerts.value.filter((alert) => !alert.confirmed));
const visibleHistoricalConfirmable = computed(() => filteredHistoricalAlerts.value);
const selectedCurrentConfirmable = computed(() => {
  const keys = new Set(selectedKeys.value);
  return alerts.value.filter((alert) => alert.source === 'current' && !alert.confirmed && keys.has(alert.uniqueKey));
});
const selectedHistoricalConfirmable = computed(() => {
  const keys = new Set(selectedKeys.value);
  return alerts.value.filter((alert) => alert.source === 'history' && keys.has(alert.uniqueKey));
});
const allVisibleCurrentSelected = computed(() =>
  visibleCurrentConfirmable.value.length > 0 &&
  visibleCurrentConfirmable.value.every((alert) => selectedKeys.value.includes(alert.uniqueKey)),
);
const allVisibleHistoricalSelected = computed(() =>
  visibleHistoricalConfirmable.value.length > 0 &&
  visibleHistoricalConfirmable.value.every((alert) => selectedKeys.value.includes(alert.uniqueKey)),
);

const toggleAll = (event: Event, visibleAlerts: Alert[]) => {
  const checked = (event.target as HTMLInputElement).checked;
  const visibleKeys = new Set(visibleAlerts.map((alert) => alert.uniqueKey));
  selectedKeys.value = checked
    ? Array.from(new Set([...selectedKeys.value, ...visibleKeys]))
    : selectedKeys.value.filter((key) => !visibleKeys.has(key));
};
const toggleAllCurrent = (event: Event) => toggleAll(event, visibleCurrentConfirmable.value);
const toggleAllHistorical = (event: Event) => toggleAll(event, visibleHistoricalConfirmable.value);

const confirmAlerts = async (items: Alert[]) => {
  confirming.value = true;
  try {
    await Promise.all(SYSTEMS.map((system) => {
      const systemItems = items.filter((item) => item.system === system);
      if (systemItems.length === 0) return Promise.resolve();
      return userStore.requestWithAuth(system, {
        method: 'post',
        url: '/alarm-confirmations/',
        data: {
          alarms: systemItems.map((item) => ({
            source: item.source,
            occurrence_id: item.occurrenceId,
          })),
        },
      });
    }));
    selectedKeys.value = selectedKeys.value.filter((key) => !items.some((item) => item.uniqueKey === key));
    await fetchAlerts();
    ElMessage.success(`已确认 ${items.length} 条告警`);
  } catch (error) {
    console.error('确认告警失败', error);
    ElMessage.error('确认告警失败');
  } finally {
    confirming.value = false;
  }
};

const confirmSelectedCurrent = () => confirmAlerts(selectedCurrentConfirmable.value);
const confirmSelectedHistorical = () => confirmAlerts(selectedHistoricalConfirmable.value);
const formatToLocalTime = (timestamp: string) => {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hour12: false, timeZone: 'Asia/Shanghai',
  }).format(date).replace(/\//g, '-').replace(',', '');
};

const handleAlarmStateChanged = () => {
  if (refreshTimer) clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => { void fetchAlerts(); }, 150);
};

onMounted(() => {
  window.addEventListener('alarm-state-changed', handleAlarmStateChanged);
  void fetchAlerts();
});
onBeforeUnmount(() => {
  window.removeEventListener('alarm-state-changed', handleAlarmStateChanged);
  if (refreshTimer) clearTimeout(refreshTimer);
});
</script>

<style scoped>
.alerts-view { padding: 8px 0 24px; }
.page-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; }
.page-heading h2 { margin: 0 0 6px; }
.page-heading p { margin: 0; color: #6b7280; }
.summary { display: flex; gap: 16px; font-weight: 600; }
.pending { color: #d33; font-weight: 600; }
.filter-container { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin: 20px 0; }
select { padding: 6px 8px; font-size: 14px; }
.alarm-tabs { margin-top: 4px; }
.table-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 10px; }
.table-heading h3 { margin: 0; font-size: 18px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; min-width: 1080px; border-collapse: collapse; }
th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
th { background-color: #f2f2f2; white-space: nowrap; }
.check-column { width: 36px; text-align: center; }
.empty-row { padding: 32px; text-align: center; color: #6b7280; }
</style>
