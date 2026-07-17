<template>
  <div class="tabs-container" :class="{ 'has-alerts': hasAlerts }">
    <div class="tabs-text">FNTL-MS100 贝通云网管系统</div>
    <el-tabs v-model="activeName" type="card" data-testid="main-navigation" @tab-click="handleClick">
      <el-tab-pane label="设备监控" name="main" data-testid="nav-main" />
      <el-tab-pane :label="activeAlertsTabLabel" name="activeAlerts" data-testid="nav-alerts" />
      <el-tab-pane label="记录查询" name="records" data-testid="nav-records" />
      <el-tab-pane v-if="canAccessOps" label="运维管理" name="ops" data-testid="nav-ops" />
      <el-tab-pane v-if="isSuperuser" label="系统设置" name="systemSettings" data-testid="nav-runtime" />
      <el-tab-pane label="帮助" name="fourth" data-testid="nav-help" />
    </el-tabs>

    <div class="action-buttons">
      <div class="sound-control">
        <span class="sound-label">声音</span>
        <el-switch v-model="soundEnabled" @change="toggleSound" />
      </div>
      <el-button @click="pauseAlerts">暂停告警声</el-button>
      <el-button @click="toggleTestSound">{{ isTestingSound ? '停止' : '试音' }}</el-button>
      <span v-if="username" class="username-display">{{ username }}</span>
      <el-popconfirm
        title="确定要登出吗？"
        cancel-button-text="否"
        confirm-button-text="是"
        @confirm="confirmLogout"
      >
        <template #reference><el-button type="primary">登出</el-button></template>
      </el-popconfirm>
    </div>
  </div>
</template>

<script lang="ts" setup>
import { computed, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import type { TabsPaneContext } from 'element-plus';
import { useAlarmSound } from '@/composables/useAlarmSound';
import { useUserStore } from '@/stores/userStore';

const props = defineProps({ selectedTab: { type: String, default: 'None' } });
const router = useRouter();
const route = useRoute();
const userStore = useUserStore();
const activeName = ref(props.selectedTab);
const username = computed(() => userStore.user?.username ?? null);
const isSuperuser = computed(() => userStore.isSuperuser);
const canAccessOps = computed(() => userStore.canAccessOps);
const {
  activeAlertsTabLabel,
  hasAlerts,
  isTestingSound,
  pauseAlerts,
  soundEnabled,
  toggleSound,
  toggleTestSound,
} = useAlarmSound();

const handleClick = (tab: TabsPaneContext) => {
  const paths: Record<string, string> = {
    main: '/main',
    records: '/records',
    ops: '/ops',
    activeAlerts: '/alerts',
    systemSettings: '/runtime-config',
    fourth: '/help',
  };
  const name = String(tab.paneName ?? 'main');
  activeName.value = name;
  if (paths[name]) void router.push(paths[name]);
};

const syncActiveTabWithRoute = () => {
  if (route.path.startsWith('/runtime-config') && isSuperuser.value) activeName.value = 'systemSettings';
  else if (route.path.startsWith('/ops') && canAccessOps.value) activeName.value = 'ops';
  else if (route.path.startsWith('/alerts')) activeName.value = 'activeAlerts';
  else if (route.path.startsWith('/records')) activeName.value = 'records';
  else if (route.path.startsWith('/help')) activeName.value = 'fourth';
  else activeName.value = 'main';
};

const confirmLogout = async () => {
  await userStore.logout();
  await router.push('/login');
};

watch(() => route.path, syncActiveTabWithRoute, { immediate: true });
</script>

<style scoped>
.tabs-container {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 12px;
  position: relative;
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
  margin: 0 0 16px;
  overflow: visible;
  background-color: #f5f5f5;
  padding: 8px 140px 8px 12px;
  border-radius: 8px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
}
.tabs-container:after {
  content: "";
  position: absolute;
  left: 0;
  bottom: 0;
  height: 2px;
  width: 100%;
  animation: blink1 10s infinite;
}
.tabs-container.has-alerts:after { animation: blink2 1s infinite; }
@keyframes blink1 {
  0%, 50%, 100% { background: rgb(0, 255, 123); }
  25%, 75% { background: transparent; }
}
@keyframes blink2 {
  0%, 50%, 100% { background: red; }
  25%, 75% { background: transparent; }
}
.tabs-text {
  flex: 0 0 auto;
  font-size: 20px;
  font-weight: bold;
  line-height: 32px;
  white-space: nowrap;
  color: #1878ff;
}
.tabs-container :deep(.el-tabs) { flex: 1 1 560px; min-width: min(520px, 100%); }
.tabs-container :deep(.el-tabs__header) { margin: 0; }
.action-buttons {
  position: static;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px 12px;
  min-width: 0;
  margin-left: auto;
}
.action-buttons :deep(.el-button) { margin-left: 0; }
.sound-control { display: flex; align-items: center; gap: 8px; }
.sound-label { font-weight: 600; color: #1f2937; }
.username-display { white-space: nowrap; }
@media (max-width: 1500px) { .action-buttons { flex-basis: 100%; } }
</style>
