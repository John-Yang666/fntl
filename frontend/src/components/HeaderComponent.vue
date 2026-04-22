<template>
  <div class="tabs-container" :class="{ 'has-alerts': hasAlerts }">
    <div class="tabs-text">FNTL-MS100 贝通云网管系统</div>

    <el-tabs type="card" @tab-click="handleClick" v-model="activeName">
      <el-tab-pane label="设备监控" name="main"></el-tab-pane>
      <el-tab-pane :label="activeAlertsTabLabel" name="activeAlerts"></el-tab-pane>
      <el-tab-pane label="记录查询" name="records"></el-tab-pane>
      <el-tab-pane v-if="isSuperuser" label="系统设置" name="systemSettings"></el-tab-pane>
      <el-tab-pane label="帮助与支持" name="fourth"></el-tab-pane>
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
import { ElMessage } from 'element-plus';
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
const selectedDevices = ref<string[]>([]);
const hasAlerts = ref(false);
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

const isTestingSound = ref(false);

// -------- SessionStorage Helpers --------
const ssGet = (k: string) => sessionStorage.getItem(k);
const ssSet = (k: string, v: string) => sessionStorage.setItem(k, v);
const ssDel = (k: string) => sessionStorage.removeItem(k);
const soundPrefGet = () => localStorage.getItem('soundEnabled');
const soundPrefSet = (value: boolean) => localStorage.setItem('soundEnabled', JSON.stringify(value));

// -------- 标签切换 --------
const handleClick = (tab: TabsPaneContext) => {
  activeName.value = tab.paneName as string;
  switch (tab.paneName) {
    case 'main': router.push('/main'); break;
    case 'records': router.push('/records'); break;
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
    console.error('告警音频预热失败:', error);
    isAudioPrimed.value = false;
    return false;
  } finally {
    audio.muted = previousMuted;
  }
};

const ensureAutoplayPrepared = async () => {
  if (!soundEnabled.value) {
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
  if (autoplayWarningMessage) {
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
  if (endedAlertMessages[system]) {
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
    pendingAlertPlayback.value = false;
    closeAutoplayWarning();
    ssSet('alertPlaying', 'true');
  } catch (err) {
    pendingAlertPlayback.value = true;
    console.error('自动播放失败，等待用户交互后重试:', err);
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
      if (primed && hasAlerts.value) {
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

const buildAlertKey = (system: SystemType, deviceId: number, alarmCode: number) =>
  `${system}:${deviceId}-${alarmCode}`;

const checkAlerts = async () => {
  const settledResponses = await Promise.allSettled(
    SYSTEMS.map(async (system) => ({
      system,
      alerts: await userStore.requestWithAuth<Array<{
        device_id: number;
        alarm_code: number;
      }>>(system, {
        method: 'get',
        url: '/active-alarms/',
      }),
    })),
  );

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

  filteredAlerts.forEach((alert) => {
    currentAlertKeysBySystem[alert.system].add(buildAlertKey(alert.system, alert.device_id, alert.alarm_code));
  });

  let hasNewAlerts = false;
  SYSTEMS.forEach((system) => {
    const currentAlertKeys = currentAlertKeysBySystem[system];
    const previousAlertKeys = previousAlertKeysBySystem[system];
    const systemHasNewAlerts = Array.from(currentAlertKeys).some((key) => !previousAlertKeys.has(key));
    const systemHasEndedAlerts = Array.from(previousAlertKeys).some((key) => !currentAlertKeys.has(key));

    if (systemHasNewAlerts) {
      hasNewAlerts = true;
    }

    if (systemHasEndedAlerts) {
      openEndedAlertNotice(system);
    }
  });

  if (hasNewAlerts) {
    ssDel('alertSoundPaused');
  }

  previousAlertKeysBySystem = currentAlertKeysBySystem;

  const count = filteredAlerts.length;
  if (count > 0) {
    activeAlertsTabLabel.value = `当前告警 (${count})`;
    hasAlerts.value = true;
    if (soundEnabled.value && hasNewAlerts) {
      void playAlertSound();
    }
  } else {
    activeAlertsTabLabel.value = '当前告警';
    hasAlerts.value = false;
  }
};

// -------- 试音 --------
const toggleTestSound = async () => {
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
      console.error('测试播放失败:', err);
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
  syncActiveTabWithRoute();
  selectedDevices.value = await loadSelectedDeviceKeys();

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
  if (soundEnabled.value && (hasAlerts.value || pendingAlertPlayback.value)) {
    void playAlertSound();
  }
  intervalId = window.setInterval(checkAlerts, 3000);
});

watch(() => route.path, () => {
  syncActiveTabWithRoute();
}, { immediate: true });

onBeforeUnmount(() => {
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
  position: relative;
  width: 100%;
  max-width: 100%;
  margin: 0 0 16px;
  overflow: hidden;
  background-color: #f5f5f5;
  padding: 8px 5px 0px 8px;
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
  padding: 10px;
  font-size: 20px;
  font-weight: bold;
  text-align: center;
  color: #1878ff;
  transition: color 0.5s ease-in-out;
  margin-top: -18px;
}
.action-buttons {
  position: absolute;
  top: 10px;
  right: 132px;
  display: flex;
  align-items: center;
  gap: 20px;
}

.sound-control {
  display: flex;
  align-items: center;
  gap: 8px;
}

.sound-label {
  font-weight: 600;
  color: #1f2937;
}
</style>
