<template>
  <div class="tabs-container" :class="{ 'has-alerts': hasAlerts }">
    <div class="tabs-text">FNTL-MS100 贝通云网管系统</div>

    <el-tabs type="card" @tab-click="handleClick" v-model="activeName" data-testid="main-navigation">
      <el-tab-pane label="设备监控" name="main" data-testid="nav-main"></el-tab-pane>
      <el-tab-pane :label="activeAlertsTabLabel" name="activeAlerts" data-testid="nav-alerts"></el-tab-pane>
      <el-tab-pane label="记录查询" name="records" data-testid="nav-records"></el-tab-pane>
      <el-tab-pane v-if="canAccessOps" label="运维管理" name="ops" data-testid="nav-ops"></el-tab-pane>
      <el-tab-pane v-if="isSuperuser" label="系统设置" name="systemSettings" data-testid="nav-runtime"></el-tab-pane>
      <el-tab-pane label="帮助" name="fourth" data-testid="nav-help"></el-tab-pane>
    </el-tabs>

    <div class="action-buttons">
      <div class="sound-control">
        <span class="sound-label">声音</span>
        <el-switch
          v-model="soundEnabled"
          @change="toggleSound"
        />
      </div>

      <el-button @click="pauseAlerts">暂停告警声</el-button>

      <el-button @click="toggleTestSound">
        {{ isTestingSound ? '停止' : '试音' }}
      </el-button>

      <span v-if="username" class="username-display">{{ username }}</span>

      <el-popconfirm
        title="确定要登出吗？"
        @confirm="confirmLogout"
        @cancel="cancelLogout"
        cancel-button-text="否"
        confirm-button-text="是"
      >
        <template #reference>
          <el-button type="primary">登出</el-button>
        </template>
      </el-popconfirm>
    </div>
  </div>
</template>

<script lang="ts" setup>
import { ref, onMounted, onBeforeUnmount, computed, watch } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import type { MessageHandler, TabsPaneContext } from 'element-plus';
import { useUserStore } from '@/stores/userStore';
import { ElMessage } from 'element-plus/es/components/message/index.mjs';
import { loadSelectedDeviceKeys } from '@/utils/selectedDevices';
import { SYSTEMS, SYSTEM_LABELS, makeDeviceKey, type SystemType } from '@/utils/systems';

const router = useRouter();
const route = useRoute();
const userStore = useUserStore();

const props = defineProps({
  selectedTab: { type: String, default: 'None' }
});
const activeName = ref(props.selectedTab);

const username = computed(() => userStore.user?.username ?? null);
const isSuperuser = computed(() => userStore.isSuperuser);
const canAccessOps = computed(() => userStore.canAccessOps);
const selectedDevices = ref<string[]>([]);
const hasAlerts = ref(false);
const hasUnconfirmedAlerts = ref(false);
const activeAlertsTabLabel = ref('当前告警');

const soundEnabled = ref<boolean>(true);
const alertAudio = ref<HTMLAudioElement | null>(null);
const isAudioPrimed = ref(false);
const pendingAlertPlayback = ref(false);
const hasShownAutoplayWarning = ref(false);
let autoplayWarningMessage: MessageHandler | null = null;
const endedAlertMessages: Record<SystemType, MessageHandler | null> = {
  bt: null,
  sy: null,
};
let isHeaderMounted = false;

const isTestingSound = ref(false);

// -------- SessionStorage Helpers --------
const ssGet = (k: string) => sessionStorage.getItem(k);
const ssSet = (k: string, v: string) => sessionStorage.setItem(k, v);
const ssDel = (k: string) => sessionStorage.removeItem(k);
const soundPrefGet = () => localStorage.getItem('soundEnabled');
const soundPrefSet = (value: boolean) => localStorage.setItem('soundEnabled', JSON.stringify(value));
const canHandleAlertAudio = () =>
  isHeaderMounted && !route.matched.some((record) => record.meta.hideHeader);

// -------- 标签切换 --------
const handleClick = (tab: TabsPaneContext) => {
  activeName.value = tab.paneName as string;
  switch (tab.paneName) {
    case 'main': router.push('/main'); break;
    case 'records': router.push('/records'); break;
    case 'ops': router.push('/ops'); break;
    case 'activeAlerts': router.push('/alerts'); break;
    case 'systemSettings': router.push('/runtime-config'); break;
    case 'fourth': router.push('/help'); break;
    default: console.log('未知标签页');
  }
};

const syncActiveTabWithRoute = () => {
  if (route.path.startsWith('/runtime-config') && isSuperuser.value) {
    activeName.value = 'systemSettings';
    return;
  }

  if (route.path.startsWith('/ops') && canAccessOps.value) {
    activeName.value = 'ops';
    return;
  }

  if (route.path.startsWith('/alerts')) {
    activeName.value = 'activeAlerts';
    return;
  }

  if (route.path.startsWith('/records')) {
    activeName.value = 'records';
    return;
  }

  if (route.path.startsWith('/help')) {
    activeName.value = 'fourth';
    return;
  }

  activeName.value = 'main';
};

// -------- 声音控制 --------
const ensureAlertAudio = () => {
  if (!alertAudio.value) {
    const audio = new Audio('/audio/alert.mp3');
    audio.loop = true;
    audio.preload = 'auto';
    alertAudio.value = audio;
  }

  return alertAudio.value;
};

const isAlertAudioPlaying = () => {
  const audio = alertAudio.value;
  return !!audio && !audio.paused && !audio.ended;
};

const primeAudioPlayback = async () => {
  if (!canHandleAlertAudio()) {
    return false;
  }

  const audio = ensureAlertAudio();
  if (isAlertAudioPlaying()) {
    isAudioPrimed.value = true;
    return true;
  }
  const previousMuted = audio.muted;

  audio.muted = true;
  try {
    await audio.play();
    audio.pause();
    audio.currentTime = 0;
    isAudioPrimed.value = true;
    return true;
  } catch (error) {
    console.warn('告警音频预热失败:', error);
    isAudioPrimed.value = false;
    return false;
  } finally {
    audio.muted = previousMuted;
  }
};

const ensureAutoplayPrepared = async () => {
  if (!soundEnabled.value || !canHandleAlertAudio()) {
    closeAutoplayWarning();
    return false;
  }

  const primed = await primeAudioPlayback();
  if (primed) {
    closeAutoplayWarning();
    return true;
  }

  if (!hasShownAutoplayWarning.value) {
    hasShownAutoplayWarning.value = true;
    openAutoplayWarning();
  }
  return false;
};

const handleAudioInteraction = async () => {
  if (!canHandleAlertAudio()) {
    return;
  }

  if (!pendingAlertPlayback.value && isAudioPrimed.value) {
    return;
  }

  const primed = await primeAudioPlayback();
  if (primed) {
    closeAutoplayWarning();
  }

  if (primed && pendingAlertPlayback.value && soundEnabled.value) {
    pendingAlertPlayback.value = false;
    void playAlertSound();
  }
};

const openAutoplayWarning = () => {
  if (!canHandleAlertAudio() || autoplayWarningMessage) {
    return;
  }

  autoplayWarningMessage = ElMessage({
    type: 'warning',
    message: '请先在页面内点击任意位置启用告警声，否则刷新后新增告警可能没有声音',
    duration: 0,
    showClose: true,
    onClose: () => {
      autoplayWarningMessage = null;
      hasShownAutoplayWarning.value = false;
    },
  });
};

const closeAutoplayWarning = () => {
  if (autoplayWarningMessage) {
    autoplayWarningMessage.close();
    autoplayWarningMessage = null;
  }
  hasShownAutoplayWarning.value = false;
};

const openEndedAlertNotice = (system: SystemType) => {
  if (!isHeaderMounted || endedAlertMessages[system]) {
    return;
  }

  endedAlertMessages[system] = ElMessage({
    type: 'warning',
    message: `${SYSTEM_LABELS[system]} 有告警结束，请查看历史告警记录。`,
    duration: 0,
    showClose: true,
    onClose: () => {
      endedAlertMessages[system] = null;
    },
  });
};

const closeEndedAlertNotice = (system?: SystemType) => {
  if (system) {
    if (endedAlertMessages[system]) {
      endedAlertMessages[system]?.close();
      endedAlertMessages[system] = null;
    }
    return;
  }

  SYSTEMS.forEach((item) => {
    if (endedAlertMessages[item]) {
      endedAlertMessages[item]?.close();
      endedAlertMessages[item] = null;
    }
  });
};

const pauseAlerts = async () => {
  stopAlertSound();
  ssSet('alertSoundPaused', 'true');
};

const playAlertSound = async () => {
  if (!canHandleAlertAudio()) {
    pendingAlertPlayback.value = false;
    return;
  }

  const paused = ssGet('alertSoundPaused');
  if (paused === 'true') {
    return;
  }

  const audio = ensureAlertAudio();
  if (isAlertAudioPlaying()) {
    pendingAlertPlayback.value = false;
    closeAutoplayWarning();
    ssSet('alertPlaying', 'true');
    return;
  }
  try {
    await audio.play();
    if (!canHandleAlertAudio()) {
      audio.pause();
      audio.currentTime = 0;
      pendingAlertPlayback.value = false;
      ssSet('alertPlaying', 'false');
      return;
    }
    pendingAlertPlayback.value = false;
    closeAutoplayWarning();
    ssSet('alertPlaying', 'true');
  } catch (err) {
    if (!canHandleAlertAudio()) {
      pendingAlertPlayback.value = false;
      return;
    }
    pendingAlertPlayback.value = true;
    console.warn('自动播放失败，等待用户交互后重试:', err);
    if (!hasShownAutoplayWarning.value) {
      hasShownAutoplayWarning.value = true;
      openAutoplayWarning();
    }
  }
};

const stopAlertSound = () => {
  if (alertAudio.value) {
    alertAudio.value.pause();
    alertAudio.value.currentTime = 0;
    ssSet('alertPlaying', 'false');
  }
  pendingAlertPlayback.value = false;
  closeAutoplayWarning();
};

const toggleSound = () => {
  soundPrefSet(soundEnabled.value);
  if (!soundEnabled.value) {
    stopAlertSound();
    ssDel('alertSoundPaused');
  } else {
    void ensureAutoplayPrepared().then((primed) => {
      if (primed && canHandleAlertAudio() && hasUnconfirmedAlerts.value) {
        void playAlertSound();
      }
    });
  }
};

// -------- 告警检测 --------
let intervalId: number;
let previousAlertKeysBySystem: Record<SystemType, Set<string>> = {
  bt: new Set<string>(),
  sy: new Set<string>(),
};
let previousHasUnconfirmedAlerts = false;

const buildAlertKey = (system: SystemType, deviceId: number, alarmCode: number) =>
  `${system}:${deviceId}-${alarmCode}`;

const checkAlerts = async () => {
  if (!isHeaderMounted) {
    return;
  }

  if (!userStore.isAuthenticated) {
    activeAlertsTabLabel.value = '当前告警';
    hasAlerts.value = false;
    hasUnconfirmedAlerts.value = false;
    previousAlertKeysBySystem = {
      bt: new Set<string>(),
      sy: new Set<string>(),
    };
    previousHasUnconfirmedAlerts = false;
    closeEndedAlertNotice();
    return;
  }

  const settledResponses = await Promise.allSettled(
    SYSTEMS.map(async (system) => ({
      system,
      alerts: await userStore.requestWithAuth<Array<{
        device_id: number;
        alarm_code: number;
        confirmed: boolean;
      }>>(system, {
        method: 'get',
        url: '/active-alarms/',
      }),
    })),
  );

  if (!canHandleAlertAudio()) {
    return;
  }

  const responses = settledResponses.flatMap((result) => {
    if (result.status === 'fulfilled') {
      return [result.value];
    }
    console.error('获取告警失败:', result.reason);
    return [];
  });

  const selectedSet = new Set(selectedDevices.value);
  const filteredAlerts = responses.flatMap(({ system, alerts }) =>
    alerts
      .filter((alert) =>
        selectedSet.size === 0 || selectedSet.has(makeDeviceKey(system, alert.device_id)),
      )
      .map((alert) => ({
        system,
        ...alert,
      })),
  );

  const currentAlertKeysBySystem: Record<SystemType, Set<string>> = {
    bt: new Set<string>(),
    sy: new Set<string>(),
  };
  const currentUnconfirmedAlertKeysBySystem: Record<SystemType, Set<string>> = {
    bt: new Set<string>(),
    sy: new Set<string>(),
  };

  filteredAlerts.forEach((alert) => {
    const alertKey = buildAlertKey(alert.system, alert.device_id, alert.alarm_code);
    currentAlertKeysBySystem[alert.system].add(alertKey);
    if (!alert.confirmed) {
      currentUnconfirmedAlertKeysBySystem[alert.system].add(alertKey);
    }
  });

  let hasNewUnconfirmedAlerts = false;
  SYSTEMS.forEach((system) => {
    const currentAlertKeys = currentAlertKeysBySystem[system];
    const currentUnconfirmedAlertKeys = currentUnconfirmedAlertKeysBySystem[system];
    const previousAlertKeys = previousAlertKeysBySystem[system];
    const systemHasNewUnconfirmedAlerts = Array.from(currentUnconfirmedAlertKeys).some((key) => !previousAlertKeys.has(key));
    const systemHasEndedAlerts = Array.from(previousAlertKeys).some((key) => !currentAlertKeys.has(key));

    if (systemHasNewUnconfirmedAlerts) {
      hasNewUnconfirmedAlerts = true;
    }

    if (systemHasEndedAlerts) {
      openEndedAlertNotice(system);
    }
  });

  if (hasNewUnconfirmedAlerts) {
    ssDel('alertSoundPaused');
  }

  const currentHasUnconfirmedAlerts = filteredAlerts.some((alert) => !alert.confirmed);
  const allCurrentAlertsConfirmed = filteredAlerts.length > 0 && !currentHasUnconfirmedAlerts;
  if (previousHasUnconfirmedAlerts && allCurrentAlertsConfirmed) {
    void pauseAlerts();
  }
  hasUnconfirmedAlerts.value = currentHasUnconfirmedAlerts;
  previousHasUnconfirmedAlerts = currentHasUnconfirmedAlerts;
  previousAlertKeysBySystem = currentAlertKeysBySystem;

  const count = filteredAlerts.length;
  if (count > 0) {
    activeAlertsTabLabel.value = `当前告警 (${count})`;
    hasAlerts.value = true;
    if (soundEnabled.value && hasNewUnconfirmedAlerts) {
      void playAlertSound();
    }
  } else {
    activeAlertsTabLabel.value = '当前告警';
    hasAlerts.value = false;
    hasUnconfirmedAlerts.value = false;
  }
};

// -------- 试音 --------
const toggleTestSound = async () => {
  if (!canHandleAlertAudio()) {
    return;
  }

  if (!soundEnabled.value) {
    ElMessage.warning('请先打开声音开关再测试告警声');
    return;
  }
  const audio = ensureAlertAudio();
  if (isTestingSound.value) {
    audio.pause();
    audio.currentTime = 0;
    isTestingSound.value = false;
  } else {
    try {
      await audio.play();
      isTestingSound.value = true;
      closeAutoplayWarning();
    } catch (err) {
      console.warn('测试播放失败:', err);
      ElMessage.warning('浏览器限制了播放，请先在页面内点击一次后再试音');
    }
  }
};

// -------- 登出 --------
const confirmLogout = async () => {
  await userStore.logout();
  router.push('/login');
};
const cancelLogout = () => console.log('Logout canceled');

// -------- 生命周期 --------
onMounted(async () => {
  isHeaderMounted = true;
  syncActiveTabWithRoute();
  selectedDevices.value = await loadSelectedDeviceKeys();
  if (!canHandleAlertAudio()) {
    return;
  }

  const storedSoundEnabled = soundPrefGet();
  soundEnabled.value = storedSoundEnabled ? JSON.parse(storedSoundEnabled) : true;
  soundPrefSet(soundEnabled.value);
  ensureAlertAudio();
  window.addEventListener('pointerdown', handleAudioInteraction, true);
  window.addEventListener('keydown', handleAudioInteraction, true);
  window.addEventListener('focus', handleAudioInteraction);

  if (soundEnabled.value) {
    await ensureAutoplayPrepared();
  }

  await checkAlerts();
  if (!canHandleAlertAudio()) {
    return;
  }
  if (soundEnabled.value && (hasUnconfirmedAlerts.value || pendingAlertPlayback.value)) {
    void playAlertSound();
  }
  intervalId = window.setInterval(checkAlerts, 3000);
});

watch(() => route.path, () => {
  syncActiveTabWithRoute();
}, { immediate: true });

onBeforeUnmount(() => {
  isHeaderMounted = false;
  clearInterval(intervalId);
  stopAlertSound();
  closeAutoplayWarning();
  closeEndedAlertNotice();
  alertAudio.value = null;
  isAudioPrimed.value = false;
  window.removeEventListener('pointerdown', handleAudioInteraction, true);
  window.removeEventListener('keydown', handleAudioInteraction, true);
  window.removeEventListener('focus', handleAudioInteraction);
});
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
  background-size: 100% 100%;
  animation: blink1 10s infinite;
  transition: all 0.5s ease;
}
.tabs-container.has-alerts:after {
  animation: blink2 1s infinite;
}
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
  padding: 0 2px 2px 0;
  font-size: 20px;
  font-weight: bold;
  line-height: 32px;
  text-align: center;
  white-space: nowrap;
  color: #1878ff;
  transition: color 0.5s ease-in-out;
}
.tabs-container :deep(.el-tabs) {
  flex: 1 1 560px;
  min-width: min(520px, 100%);
}
.tabs-container :deep(.el-tabs__header) {
  margin: 0;
}
.action-buttons {
  position: static;
  display: flex;
  align-items: center;
  flex: 0 1 auto;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px 12px;
  min-width: 0;
  margin-left: auto;
}
.action-buttons :deep(.el-button) {
  margin-left: 0;
}

.sound-control {
  display: flex;
  align-items: center;
  flex: 0 0 auto;
  gap: 8px;
}

.sound-label {
  font-weight: 600;
  color: #1f2937;
}

.username-display {
  flex: 0 0 auto;
  white-space: nowrap;
}

@media (max-width: 1500px) {
  .action-buttons {
    flex-basis: 100%;
  }
}
</style>
