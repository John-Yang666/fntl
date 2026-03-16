<template>
  <div class="tabs-container" :class="{ 'has-alerts': hasAlerts }">
    <div class="tabs-text">FNTL-MS100 BT / SY 统一云网管系统</div>

    <el-tabs type="card" @tab-click="handleClick" v-model="activeName">
      <el-tab-pane label="设备监控" name="main"></el-tab-pane>
      <el-tab-pane :label="activeAlertsTabLabel" name="activeAlerts"></el-tab-pane>
      <el-tab-pane label="记录查询" name="records"></el-tab-pane>
      <el-tab-pane label="帮助与支持" name="fourth"></el-tab-pane>
    </el-tabs>

    <div class="action-buttons">
      <el-button @click="pauseAlerts">暂停告警声</el-button>

      <el-switch
        v-model="soundEnabled"
        @change="toggleSound"
        active-text="声音"
        style="margin: 0 8px;"
      />

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
import { ref, onMounted, onBeforeUnmount, computed } from 'vue';
import { useRouter } from 'vue-router';
import type { TabsPaneContext } from 'element-plus';
import axios from 'axios';
import { useUserStore } from '@/stores/userStore';
import { ElMessage } from 'element-plus';
import { loadSelectedDeviceKeys } from '@/utils/selectedDevices';
import { SYSTEMS, makeDeviceKey, getApiBase } from '@/utils/systems';

const router = useRouter();
const userStore = useUserStore();

const props = defineProps({
  selectedTab: { type: String, default: 'None' }
});
const activeName = ref(props.selectedTab);

const username = computed(() => userStore.user?.username ?? null);
const selectedDevices = ref<string[]>([]);
const hasAlerts = ref(false);
const activeAlertsTabLabel = ref('当前告警');

const soundEnabled = ref<boolean>(false);
const alertAudio = ref<HTMLAudioElement | null>(null);

const isTestingSound = ref(false);

// -------- SessionStorage Helpers --------
const ssGet = (k: string) => sessionStorage.getItem(k);
const ssSet = (k: string, v: string) => sessionStorage.setItem(k, v);
const ssDel = (k: string) => sessionStorage.removeItem(k);

// -------- 标签切换 --------
const handleClick = (tab: TabsPaneContext) => {
  activeName.value = tab.paneName as string;
  switch (tab.paneName) {
    case 'main': router.push('/main'); break;
    case 'records': router.push('/records'); break;
    case 'activeAlerts': router.push('/alerts'); break;
    case 'fourth': router.push('/help'); break;
    default: console.log('未知标签页');
  }
};

// -------- 声音控制 --------
const pauseAlerts = async () => {
  stopAlertSound();
  ssSet('alertSoundPaused', 'true');
};

const playAlertSound = async () => {
  const paused = ssGet('alertSoundPaused');
  if (paused !== 'true') {
    if (!alertAudio.value) {
      alertAudio.value = new Audio('/audio/alert.mp3');
      alertAudio.value.loop = true;
    }
    try {
      await alertAudio.value.play();
      ssSet('alertPlaying', 'true');
    } catch (err) {
      console.error('自动播放失败，需要用户点击:', err);
      const playOnClick = () => {
        alertAudio.value?.play().then(() => ssSet('alertPlaying', 'true'));
      };
      document.body.addEventListener('click', playOnClick, { once: true });
    }
  }
};

const stopAlertSound = () => {
  if (alertAudio.value) {
    alertAudio.value.pause();
    alertAudio.value.currentTime = 0;
    ssSet('alertPlaying', 'false');
  }
};

const toggleSound = () => {
  ssSet('soundEnabled', JSON.stringify(soundEnabled.value));
  if (!soundEnabled.value) {
    stopAlertSound();
    ssDel('alertSoundPaused');
  } else if (hasAlerts.value) {
    playAlertSound();
  }
};

// -------- 告警检测 --------
let intervalId: number;
let previousAlertSnapshot = '';

const checkAlerts = async () => {
  try {
    const responses = await Promise.all(
      SYSTEMS.map(async (system) => ({
        system,
        alerts: (await axios.get(`${getApiBase(system)}/active-alarms/`)).data as Array<{
          device_id: number;
          alarm_code: number;
        }>,
      })),
    );

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

    const currentSnapshot = filteredAlerts
      .map(a => `${a.system}:${a.device_id}-${a.alarm_code}`)
      .sort()
      .join('|');

    if (currentSnapshot !== previousAlertSnapshot) {
      ssDel('alertSoundPaused');
    }
    previousAlertSnapshot = currentSnapshot;

    const count = filteredAlerts.length;
    if (count > 0) {
      activeAlertsTabLabel.value = `当前告警 (${count})`;
      hasAlerts.value = true;
      if (soundEnabled.value) playAlertSound();
    } else {
      activeAlertsTabLabel.value = '当前告警';
      hasAlerts.value = false;
      ssDel('alertSoundPaused');
    }
  } catch (error) {
    console.error('获取告警失败:', error);
  }
};

// -------- 试音 --------
const toggleTestSound = async () => {
  if (!soundEnabled.value) {
    ElMessage.warning('请先打开声音开关再测试告警声');
    return;
  }
  if (!alertAudio.value) {
    alertAudio.value = new Audio('/audio/alert.mp3');
    alertAudio.value.loop = true;
  }
  if (isTestingSound.value) {
    alertAudio.value.pause();
    alertAudio.value.currentTime = 0;
    isTestingSound.value = false;
  } else {
    try {
      await alertAudio.value.play();
      isTestingSound.value = true;
    } catch (err) {
      console.error('测试播放失败:', err);
      const playOnClick = () => {
        alertAudio.value?.play().then(() => { isTestingSound.value = true; });
      };
      document.body.addEventListener('click', playOnClick, { once: true });
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
  selectedDevices.value = await loadSelectedDeviceKeys();

  const storedSoundEnabled = ssGet('soundEnabled');
  soundEnabled.value = storedSoundEnabled ? JSON.parse(storedSoundEnabled) : false;
  ssSet('soundEnabled', JSON.stringify(soundEnabled.value));

  await checkAlerts();
  if (hasAlerts.value && soundEnabled.value) {
    playAlertSound();
  }
  intervalId = window.setInterval(checkAlerts, 3000);
});

onBeforeUnmount(() => {
  clearInterval(intervalId);
  stopAlertSound();
  alertAudio.value = null;
});

window.addEventListener('beforeunload', () => {
  soundEnabled.value = false;
  ssSet('soundEnabled', 'false');
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
  right: 10px;
  display: flex;
  align-items: center;
  gap: 12px;
}
</style>
