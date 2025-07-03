<template>
  <div class="tabs-container" :class="{ 'has-alerts': hasAlerts }">
    <div class="tabs-text">FNTL-MS100 贝通云网管系统</div>
    <el-tabs type="card" @tab-click="handleClick" v-model="activeName">
      <el-tab-pane label="设备监控" name="main"></el-tab-pane>
      <el-tab-pane label="记录查询" name="records"></el-tab-pane>
      <el-tab-pane :label="thirdTabLabel" name="third"></el-tab-pane>
      <el-tab-pane label="帮助与支持" name="fourth"></el-tab-pane>
    </el-tabs>

    <!-- 暂停告警声按钮 -->
    <el-button @click="pauseAlerts" class="confirm-alert-button">
      暂停告警声
    </el-button>

    <!-- 显示当前登录用户名 -->
    <span v-if="username" class="username-display">
      {{ username }}
    </span>

    <!-- 登出按钮（带二次确认） -->
    <el-popconfirm
      title="确定要登出吗？"
      @confirm="confirmLogout"
      @cancel="cancelLogout"
      cancel-button-text="否"
      confirm-button-text="是"
    >
      <template #reference>
        <el-button type="primary" class="logout-button">
          登出
        </el-button>
      </template>
    </el-popconfirm>

    <!-- 声音开关 -->
    <el-switch
      class="sound-button"
      v-model="soundEnabled"
      @change="toggleSound"
      active-text="声音"
    />
  </div>
</template>

<script lang="ts" setup>
import { ref, onMounted, onBeforeUnmount, computed } from 'vue';
import { useRouter } from 'vue-router';
import type { TabsPaneContext } from 'element-plus';
import axios from 'axios';

import { useUserStore } from '@/stores/userStore';
import { getFromDB, saveToDB, deleteFromDB } from '@/utils/indexedDB'; // 用于告警声与设备ID等

// =====================
// Vue Router & Pinia
// =====================
const router = useRouter();
const userStore = useUserStore();

// =====================
// Props
// =====================
const props = defineProps({
  selectedTab: {
    type: String,
    default: 'None'
  }
});
const activeName = ref(props.selectedTab);

// =====================
// 用户名，从 Pinia 读取
// =====================
/** 
 * 如果 userStore.user 不为空，则显示其用户名 
 * 否则为空
 */
const username = computed(() => userStore.user?.username ?? null);

// =====================
// 告警相关
// =====================
const backendPort = import.meta.env.VITE_BACKEND_PORT;
const baseURL = `${window.location.protocol}//${window.location.hostname}:${backendPort}/api`;
const selectedDevices = ref<number[]>([]);
const hasAlerts = ref(false);
const thirdTabLabel = ref('当前告警');
let previousAlerts: any[] = [];

// 声音相关
const soundEnabled = ref<boolean>(false); // 声音开关
const alertAudio = ref<HTMLAudioElement | null>(null);

// =====================
// 切换标签
// =====================
const handleClick = (tab: TabsPaneContext) => {
  activeName.value = tab.paneName as string;
  switch (tab.paneName) {
    case 'main':
      router.push('/main');
      break;
    case 'records':
      router.push('/records');
      break;
    case 'third':
      router.push('/alerts');
      break;
    case 'fourth':
      router.push('/help');
      break;
    default:
      console.log('未知标签页');
  }
};

// =====================
// 告警 & 声音管理
// =====================
const pauseAlerts = async () => {
  // 停止声音
  await stopAlertSound();
  // 标记已暂停
  await saveToDB('alertSoundPaused', 'true');
};

const playAlertSound = async () => {
  const alertSoundPaused = await getFromDB('alertSoundPaused');
  if (!alertSoundPaused || alertSoundPaused !== 'true') {
    if (!alertAudio.value) {
      alertAudio.value = new Audio('/audio/alert.mp3');
      alertAudio.value.loop = true;
    }
    try {
      await alertAudio.value.play();
      await saveToDB('alertPlaying', 'true');
    } catch (err) {
      console.error('自动播放失败，需要用户点击:', err);
      const playOnClick = () => {
        alertAudio.value
          ?.play()
          .then(() => saveToDB('alertPlaying', 'true'))
          .catch(console.error);
      };
      document.body.addEventListener('click', playOnClick, { once: true });
    }
  }
};

const stopAlertSound = async () => {
  if (alertAudio.value) {
    alertAudio.value.pause();
    alertAudio.value.currentTime = 0;
    await saveToDB('alertPlaying', 'false');
  }
};

const toggleSound = async () => {
  await saveToDB('soundEnabled', JSON.stringify(soundEnabled.value));
  if (!soundEnabled.value) {
    // 关闭
    stopAlertSound();
  } else if (hasAlerts.value) {
    // 打开且当前存在告警
    playAlertSound();
  }
};

// =====================
// 定时获取告警
// =====================
let intervalId: number;
const checkAlerts = async () => {
  try {
    const response = await axios.get(`${baseURL}/alerts-amount/`);
    const count = response.data.alerts_amount;

    if (count > 0) {
      thirdTabLabel.value = `当前告警 (${count})`;
      hasAlerts.value = true;
      if (soundEnabled.value) {
        playAlertSound();
      }
    } else {
      thirdTabLabel.value = '当前告警';
      hasAlerts.value = false;
    }
  } catch (error) {
    console.error('Failed to fetch alerts amount:', error);
  }
};

// =====================
// 登出
// =====================
const confirmLogout = async () => {
  // Pinia 用户登出
  await userStore.logout();
  // 清除本地 username
  await deleteFromDB('username');
  // 跳转到登录页
  router.push('/login');
};
const cancelLogout = () => {
  console.log('Logout canceled');
};

// =====================
// 生命周期
// =====================
onMounted(async () => {
  try {
    // 读取选中的设备 ID
    const storedSelectedDevices = await getFromDB<string>('selectedDevices');
    if (storedSelectedDevices) {
      selectedDevices.value = JSON.parse(storedSelectedDevices);
    }

    // 读取是否已开启声音
    const storedSoundEnabled = await getFromDB<string>('soundEnabled');
    if (storedSoundEnabled !== null) {
      soundEnabled.value = JSON.parse(storedSoundEnabled);
    } else {
      soundEnabled.value = false;
      await saveToDB('soundEnabled', 'false');
    }

    // 检查告警
    await checkAlerts();

    // 如果有告警 && 声音开关已开
    if (hasAlerts.value && soundEnabled.value) {
      playAlertSound();
    }

    // 定时刷新告警
    intervalId = window.setInterval(checkAlerts, 3000);
  } catch (error) {
    console.error('Failed to initialize settings:', error);
  }
});

onBeforeUnmount(() => {
  clearInterval(intervalId);
  stopAlertSound();
  alertAudio.value = null;
});

// 用户离开页面时，关闭声音
window.addEventListener('beforeunload', async () => {
  soundEnabled.value = false;
  await saveToDB('soundEnabled', 'false');
});
</script>

<style scoped>
.tabs-container {
  display: flex;
  align-items: center;
  position: relative;
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
  background: linear-gradient(90deg, rgb(38, 110, 255), rgba(0,255,0,1));
  transition: all 0.5s ease;
}

.tabs-container.has-alerts:after {
  animation: blink 1s infinite;
}

@keyframes blink {
  0%, 50%, 100% {
    background: red;
  }
  25%, 75% {
    background: transparent;
  }
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

.username-display {
  position: absolute;
  right: 130px;
  top: 15px;
  font-size: 16px;
  color: #666;
}

.logout-button {
  position: absolute;
  right: 10px;
  top: 10px;
}

.sound-button {
  position: absolute;
  right: 220px;
  top: 12px;
}

.confirm-alert-button {
  position: absolute;
  right: 320px;
  top: 12px;
}
</style>
