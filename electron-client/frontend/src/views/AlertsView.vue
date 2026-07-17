<template>
  <section class="alerts-view" data-testid="alerts-view">
    <div class="page-heading">
      <div><h2>告警详情</h2><p>展示所选监控设备的当前告警和未确认历史告警。</p></div>
      <div class="summary"><span>当前 {{ currentCount }}</span><span class="pending">待确认 {{ unconfirmedCount }}</span></div>
    </div>
    <div class="filter-container">
      <select v-model="selectedSystem"><option value="">所有系统</option><option value="bt">BT</option><option value="sy">SY</option></select>
      <select v-model="selectedDevice"><option value="">所有设备</option><option v-for="device in deviceNames" :key="device" :value="device">{{ device }}</option></select>
      <select v-model="selectedStatus"><option value="">所有状态</option><option value="unconfirmed">未确认</option><option value="confirmed">已确认</option></select>
      <select v-model="selectedAlarmMeaning"><option value="">所有告警</option><option v-for="meaning in alarmMeanings" :key="meaning" :value="meaning">{{ meaning }}</option></select>
      <el-button :loading="loading" @click="fetchAlerts">刷新</el-button>
      <el-button type="primary" :disabled="selectedConfirmable.length === 0" :loading="confirming" @click="confirmSelected">批量确认（{{ selectedConfirmable.length }}）</el-button>
    </div>
    <div class="table-wrap"><table>
      <thead><tr><th><input type="checkbox" :checked="allVisibleConfirmableSelected" :disabled="visibleConfirmable.length === 0" @change="toggleAllVisible" /></th><th>序号</th><th>系统</th><th>来源</th><th>设备ID</th><th>设备名称</th><th>告警码</th><th>告警含义</th><th>起始时间</th><th>结束时间</th><th>状态</th><th>操作</th></tr></thead>
      <tbody>
        <tr v-for="(alert, index) in filteredAlerts" :key="alert.uniqueKey">
          <td><input v-if="!alert.confirmed" v-model="selectedKeys" type="checkbox" :value="alert.uniqueKey" /></td><td>{{ index + 1 }}</td><td>{{ alert.system.toUpperCase() }}</td><td>{{ alert.source === 'current' ? '当前' : '历史' }}</td><td>{{ alert.device_id }}</td><td>{{ alert.device_name }}</td><td>{{ alert.alarm_code }}</td><td>{{ alert.alarm_meaning }}</td><td>{{ formatToLocalTime(alert.timestamp) }}</td><td>{{ alert.timestamp_end ? formatToLocalTime(alert.timestamp_end) : '—' }}</td><td><span :class="{ pending: !alert.confirmed }">{{ alert.confirmed ? '已确认' : '未确认' }}</span></td><td><el-button v-if="!alert.confirmed" link type="primary" @click="confirmAlerts([alert])">确认</el-button><span v-else>—</span></td>
        </tr>
        <tr v-if="!loading && filteredAlerts.length === 0"><td colspan="12" class="empty-row">暂无符合条件的告警</td></tr>
      </tbody>
    </table></div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { useUserStore } from '@/stores/userStore';
import { SYSTEMS, type SystemType } from '@/utils/systems';
type AlarmSource = 'current' | 'history';
interface Alert { system: SystemType; source: AlarmSource; occurrenceId: string; uniqueKey: string; device_id: number; device_name: string; alarm_code: number; alarm_meaning: string; timestamp: string; timestamp_end: string | null; confirmed: boolean }
interface CurrentAlarmResponse { id: string; device_id: number; device_name: string; alarm_code: number; alarm_meaning: string; timestamp: string; confirmed: boolean }
interface HistoricalAlarmResponse { id: string; device_id: number; device_name: string; alarm_code: number; alarm_meaning: string; timestamp: string; timestamp_end: string | null; is_confirmed: boolean }
interface Page<T> { next: string | null; results: T[] }
const alerts = ref<Alert[]>([]); const selectedSystem = ref(''); const selectedDevice = ref(''); const selectedStatus = ref(''); const selectedAlarmMeaning = ref(''); const selectedKeys = ref<string[]>([]); const loading = ref(false); const confirming = ref(false); const userStore = useUserStore(); let refreshTimer: ReturnType<typeof setTimeout> | null = null;
const fetchAllHistorical = async (system: SystemType) => { const rows: HistoricalAlarmResponse[] = []; let url: string | null = '/alerts/?is_confirmed=false&monitored=true&page_size=500'; while (url) { const page: Page<HistoricalAlarmResponse> = await userStore.requestWithAuth(system, { method: 'get', url }); rows.push(...page.results); url = page.next; } return rows; };
const fetchAlerts = async () => { loading.value = true; try { const responses = await Promise.allSettled(SYSTEMS.map(async (system) => { const [current, history] = await Promise.all([userStore.requestWithAuth<CurrentAlarmResponse[]>(system, { method: 'get', url: '/active-alarms/' }), fetchAllHistorical(system)]); return { system, current, history }; })); alerts.value = responses.flatMap((result, index) => { if (result.status === 'rejected') { console.error(`获取 ${SYSTEMS[index].toUpperCase()} 告警详情失败`, result.reason); return []; } const { system, current, history } = result.value; return [...current.map((alarm): Alert => ({ system, source: 'current', occurrenceId: alarm.id, uniqueKey: `${system}:current:${alarm.id}`, ...alarm, timestamp_end: null })), ...history.map((alarm): Alert => ({ system, source: 'history', occurrenceId: alarm.id, uniqueKey: `${system}:history:${alarm.id}`, ...alarm, confirmed: alarm.is_confirmed }))]; }); const keys = new Set(alerts.value.filter((alert) => !alert.confirmed).map((alert) => alert.uniqueKey)); selectedKeys.value = selectedKeys.value.filter((key) => keys.has(key)); } finally { loading.value = false; } };
const deviceNames = computed(() => Array.from(new Set(alerts.value.map((a) => a.device_name))).sort()); const alarmMeanings = computed(() => Array.from(new Set(alerts.value.map((a) => a.alarm_meaning))).sort()); const currentCount = computed(() => alerts.value.filter((a) => a.source === 'current').length); const unconfirmedCount = computed(() => alerts.value.filter((a) => !a.confirmed).length);
const filteredAlerts = computed(() => alerts.value.filter((a) => (!selectedSystem.value || a.system === selectedSystem.value) && (!selectedDevice.value || a.device_name === selectedDevice.value) && (!selectedAlarmMeaning.value || a.alarm_meaning === selectedAlarmMeaning.value) && (!selectedStatus.value || (selectedStatus.value === 'confirmed' ? a.confirmed : !a.confirmed))).sort((a, b) => { if (a.confirmed !== b.confirmed) return a.confirmed ? 1 : -1; if (a.source !== b.source) return a.source === 'current' ? -1 : 1; return new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(); }));
const visibleConfirmable = computed(() => filteredAlerts.value.filter((a) => !a.confirmed)); const selectedConfirmable = computed(() => { const keys = new Set(selectedKeys.value); return alerts.value.filter((a) => !a.confirmed && keys.has(a.uniqueKey)); }); const allVisibleConfirmableSelected = computed(() => visibleConfirmable.value.length > 0 && visibleConfirmable.value.every((a) => selectedKeys.value.includes(a.uniqueKey)));
const toggleAllVisible = (event: Event) => { const checked = (event.target as HTMLInputElement).checked; const keys = new Set(visibleConfirmable.value.map((a) => a.uniqueKey)); selectedKeys.value = checked ? Array.from(new Set([...selectedKeys.value, ...keys])) : selectedKeys.value.filter((key) => !keys.has(key)); };
const confirmAlerts = async (items: Alert[]) => { confirming.value = true; try { await Promise.all(SYSTEMS.map((system) => { const systemItems = items.filter((item) => item.system === system); return systemItems.length ? userStore.requestWithAuth(system, { method: 'post', url: '/alarm-confirmations/', data: { alarms: systemItems.map((item) => ({ source: item.source, occurrence_id: item.occurrenceId })) } }) : Promise.resolve(); })); selectedKeys.value = selectedKeys.value.filter((key) => !items.some((item) => item.uniqueKey === key)); await fetchAlerts(); ElMessage.success(`已确认 ${items.length} 条告警`); } catch (error) { console.error('确认告警失败', error); ElMessage.error('确认告警失败'); } finally { confirming.value = false; } };
const confirmSelected = () => confirmAlerts(selectedConfirmable.value); const formatToLocalTime = (timestamp: string) => { const date = new Date(timestamp); if (Number.isNaN(date.getTime())) return '—'; return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false, timeZone: 'Asia/Shanghai' }).format(date).replace(/\//g, '-').replace(',', ''); };
const handleAlarmStateChanged = () => { if (refreshTimer) clearTimeout(refreshTimer); refreshTimer = setTimeout(() => { void fetchAlerts(); }, 150); };
onMounted(() => { window.addEventListener('alarm-state-changed', handleAlarmStateChanged); void fetchAlerts(); }); onBeforeUnmount(() => { window.removeEventListener('alarm-state-changed', handleAlarmStateChanged); if (refreshTimer) clearTimeout(refreshTimer); });
</script>
<style scoped>
.alerts-view { padding: 8px 0 24px; }.page-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; }.page-heading h2 { margin: 0 0 6px; }.page-heading p { margin: 0; color: #6b7280; }.summary { display: flex; gap: 16px; font-weight: 600; }.pending { color: #d33; font-weight: 600; }.filter-container { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin: 20px 0; }select { padding: 6px 8px; font-size: 14px; }.table-wrap { overflow-x: auto; }table { width: 100%; min-width: 1180px; border-collapse: collapse; }th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }th { background-color: #f2f2f2; white-space: nowrap; }.empty-row { padding: 32px; text-align: center; color: #6b7280; }
</style>
