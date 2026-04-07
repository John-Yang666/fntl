<template>
  <div class="login-container">
    <el-card class="box-card">
      <!-- 密码验证部分 -->
      <div v-if="!isAuthenticated" class="login-box">
        <el-input
          v-model="password"
          placeholder="请输入密码"
          show-password
          @keyup.enter="validatePassword"
          class="input-field"
        ></el-input>
        <el-button
          type="primary"
          @click="validatePassword"
          class="login-button"
        >
          验证
        </el-button>
        <p v-if="error" class="error-message">{{ error }}</p>
      </div>

      <!-- 操作界面 -->
      <div v-else class="command-box">
        <!-- ✅ 监听 DeviceNameComponent 的 loaded 事件，避免重复请求 -->
        <device-name-component @loaded="onDeviceLoaded" />

        <el-divider />

        <h3>发送切换模式命令</h3>

        <!-- 本站方向选择 -->
        <div class="direction-buttons">
          本站方向选择：
          <el-button
            :type="selectedDirection === 'direction1' ? 'primary' : 'default'"
            @click="selectedDirection = 'direction1'"
          >
            一方向（上行）
          </el-button>
          <el-button
            :type="selectedDirection === 'direction2' ? 'primary' : 'default'"
            @click="selectedDirection = 'direction2'"
          >
            二方向（下行）
          </el-button>
        </div>

        <!-- 模式选择：只保留 强制电缆 / 自动 -->
        <div class="mode-buttons">
          模式选择：
          <el-button
            :type="selectedMode === 'cable' ? 'primary' : 'default'"
            @click="selectedMode = 'cable'"
          >
            强制电缆
          </el-button>
          <el-button
            :type="selectedMode === 'auto' ? 'primary' : 'default'"
            @click="selectedMode = 'auto'"
          >
            自动
          </el-button>
        </div>

        <div class="send-buttons">
          <el-button type="success" @click="sendModeToLocal">
            向本站发送
          </el-button>
          <el-button type="success" @click="sendModeToNeighbor">
            向邻站发送
          </el-button>
        </div>

        <!-- 其他远程控制 -->
        <el-divider />
        <h3>其他远程控制</h3>
        <div class="send-buttons">
          <el-button
            v-if="pendingRemoteAction !== 'start' && pendingRemoteAction !== 'disable'"
            type="warning"
            @click="prepareRemoteStart"
          >
            启动当前设备
          </el-button>

          <!-- ✅ 合并后的按钮：根据设备名是否含“备机”选择停用A/停用B -->
          <el-button
            v-if="pendingRemoteAction !== 'start' && pendingRemoteAction !== 'disable'"
            type="danger"
            @click="prepareDisableCurrent"
          >
            停用当前设备
          </el-button>

          <div v-else class="remote-confirm">
            <span class="remote-confirm-text">{{ remoteConfirmText }}</span>
            <el-button
              :type="pendingRemoteAction === 'disable' ? 'danger' : 'warning'"
              :loading="isSendingRemoteAction"
              @click="confirmRemoteAction"
            >
              确认发送
            </el-button>
            <el-button
              :disabled="isSendingRemoteAction"
              @click="cancelRemoteAction"
            >
              取消
            </el-button>
          </div>
        </div>

        <!-- 自定义命令 -->
        <el-divider />
        <h3>自定义命令</h3>
        <div class="custom-command">
          <span>命令字节：0x</span>
          <el-input
            v-model="customCode"
            placeholder="例如 32"
            class="custom-input"
          />
          <el-button type="primary" @click="sendCustomCommand">
            发送
          </el-button>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import axios from 'axios';
import { useRoute } from 'vue-router';
import { ElMessage } from 'element-plus';
import DeviceNameComponent from '@/components/DeviceNameComponent.vue';
import { useUserStore } from '@/stores/userStore';
import { getApiBase, getSystemFromRoute } from '@/utils/systems';

const route = useRoute();
const device_id = route.params.index as string;

const selectedMode = ref<'cable' | 'auto' | null>(null);
const selectedDirection = ref<'direction1' | 'direction2' | null>(null);
const customCode = ref(''); // 自定义命令字节（16进制）

const password = ref('');
const error = ref('');
const isAuthenticated = ref(false);
const pendingRemoteAction = ref<'start' | 'disable' | null>(null);
const isSendingRemoteAction = ref(false);

const userStore = useUserStore();
const baseURL = () => getApiBase(getSystemFromRoute(route.params.system));
const username = computed(() => userStore.user?.username ?? null);

/** ✅ 从 DeviceNameComponent 接收的设备信息（避免重复 GET） */
const currentDeviceName = ref('');
const isBackupDevice = ref(false);
const remoteConfirmText = computed(() => {
  if (pendingRemoteAction.value === 'start') {
    return '确认启动当前设备？';
  }

  if (pendingRemoteAction.value === 'disable') {
    const deviceLabel = currentDeviceName.value || `设备 ${device_id}`;
    const actionLabel = isBackupDevice.value ? '停用备机（B落下）' : '停用主机（A落下）';
    return `确认对 ${deviceLabel} 执行“${actionLabel}”吗？`;
  }

  return '';
});

const onDeviceLoaded = (payload: { name: string; isBackup: boolean; deviceId: number | null }) => {
  currentDeviceName.value = payload.name || '';
  isBackupDevice.value = !!payload.isBackup;
};

const showSelectionMessage = (message: string) => {
  error.value = '';
  ElMessage.warning(message);
};

const showCommandMessage = (message: string, type: 'warning' | 'error' = 'warning') => {
  error.value = '';
  ElMessage[type](message);
};

const validatePassword = () => {
  if (password.value === 'fasong') {
    isAuthenticated.value = true;
    error.value = '';
  } else {
    error.value = '密码错误，请重试。';
  }
};

/**
 * 把 “方向 + 模式” 映射成后端 BB 命令名称
 * - direction1: 上行
 * - direction2: 下行
 */
const getBbNameForMode = (): string | null => {
  if (!selectedDirection.value || !selectedMode.value) return null;

  if (selectedDirection.value === 'direction1') {
    // 上行
    return selectedMode.value === 'cable' ? 'UP_FORCE_CABLE' : 'UP_AUTO';
  } else {
    // 下行
    return selectedMode.value === 'cable' ? 'DOWN_FORCE_CABLE' : 'DOWN_AUTO';
  }
};

/**
 * 通用发送函数：
 *  - bbName: 使用预定义 BB_CODES 名称
 *  - extra: 可选额外字段（比如邻站操作时带个 meta）
 */
const sendBbByName = async (targetId: string, bbName: string, extra?: any) => {
  if (!username.value) {
    showCommandMessage('用户信息为空，请重新登录。', 'error');
    return;
  }

  try {
    const res = await axios.post(
      `${baseURL()}/sy/send-command/${targetId}/`,
      {
        username: username.value,
        cmd_type: 'BB',
        bb_name: bbName,
        ...extra,
      }
    );

    ElMessage.success(res.data.status ?? '命令已发送');
    error.value = '';
  } catch (err: any) {
    console.error('Error:', err);
    const msg = err.response?.data?.message || '发送失败，请重试。';
    ElMessage.error(msg);
  }
};

/**
 * 通用发送函数（自定义 code）：
 * - codeHex: 1~2 位 16 进制字符串（不带 0x）
 */
const sendBbByCode = async (targetId: string, codeHex: string) => {
  if (!username.value) {
    showCommandMessage('用户信息为空，请重新登录。', 'error');
    return;
  }

  try {
    const res = await axios.post(
      `${baseURL()}/sy/send-command/${targetId}/`,
      {
        username: username.value,
        cmd_type: 'BB',
        bb_code: codeHex,
      }
    );

    ElMessage.success(res.data.status ?? '命令已发送');
    error.value = '';
  } catch (err: any) {
    console.error('Error:', err);
    const msg = err.response?.data?.message || '发送失败，请重试。';
    ElMessage.error(msg);
  }
};

/** 向本站发送模式命令 */
const sendModeToLocal = async () => {
  const bbName = getBbNameForMode();
  if (!bbName) {
    showSelectionMessage('请选择方向和模式。');
    return;
  }
  await sendBbByName(device_id, bbName);
};

/** 向邻站发送模式命令：需要查一次设备信息拿邻站ID */
const sendModeToNeighbor = async () => {
  if (!selectedMode.value || !selectedDirection.value) {
    showSelectionMessage('请选择方向和模式。');
    return;
  }

  try {
    const res = await axios.get(
      `${baseURL()}/devices/?device_id=${device_id}`
    );

    if (!res.data.results?.length) {
      ElMessage.error('未找到设备信息。');
      return;
    }

    const deviceData = res.data.results[0];

    const neighborId =
      selectedDirection.value === 'direction1'
        ? deviceData.direction1_neighbor_id
        : deviceData.direction2_neighbor_id;

    const neighborDirection =
      selectedDirection.value === 'direction1'
        ? deviceData.direction1_neighbor_direction
        : deviceData.direction2_neighbor_direction;

    if (!neighborId) {
      ElMessage.error('未找到邻站设备。');
      return;
    }

    const bbName =
      neighborDirection === 1
        ? selectedMode.value === 'cable'
          ? 'UP_FORCE_CABLE'
          : 'UP_AUTO'
        : neighborDirection === 2
        ? selectedMode.value === 'cable'
          ? 'DOWN_FORCE_CABLE'
          : 'DOWN_AUTO'
        : null;

    if (!bbName) {
      ElMessage.error('邻站方向配置错误。');
      return;
    }

    await sendBbByName(String(neighborId), bbName, {
      neighbor_direction: neighborDirection,
    });
  } catch (err) {
    console.error('Error:', err);
    ElMessage.error('获取邻站信息失败。');
  }
};

/** 远程启动本站：0x37 -> REMOTE_START_LOCAL */
const sendRemoteStart = async () => {
  await sendBbByName(device_id, 'REMOTE_START_LOCAL');
};

const prepareRemoteStart = () => {
  pendingRemoteAction.value = 'start';
};

const prepareDisableCurrent = () => {
  pendingRemoteAction.value = 'disable';
};

const cancelRemoteAction = () => {
  pendingRemoteAction.value = null;
  ElMessage.info('已取消发送');
};

const confirmRemoteAction = async () => {
  if (!pendingRemoteAction.value) {
    return;
  }

  isSendingRemoteAction.value = true;
  try {
    if (pendingRemoteAction.value === 'start') {
      await sendRemoteStart();
    } else {
      await sendDisableCurrent();
    }
    pendingRemoteAction.value = null;
  } finally {
    isSendingRemoteAction.value = false;
  }
};

/**
 * ✅ 合并后的“停用当前设备”
 * 规则：
 * - 设备名称包含“备机” -> FORCE_B_DROP (0x24)
 * - 否则 -> FORCE_A_DROP (0x12)
 *
 * ✅ 这里不再 GET 设备名，直接用 DeviceNameComponent 抛上来的结果
 */
const sendDisableCurrent = async () => {
  const bbName = isBackupDevice.value ? 'FORCE_B_DROP' : 'FORCE_A_DROP';

  await sendBbByName(device_id, bbName, {
    device_name: currentDeviceName.value,
    is_backup: isBackupDevice.value,
  });

  ElMessage.info(
    isBackupDevice.value
      ? '检测到设备名包含“备机”，已发送：停用备机（B落下）'
      : '已发送：停用主机（A落下）'
  );
};

/** 自定义命令：输入 cd，发 bb_code，后端生成 7F 7F X BB cd...F7 */
const sendCustomCommand = async () => {
  const codeStr = customCode.value.trim();
  if (!codeStr) {
    showCommandMessage('请输入命令字节（16进制）。');
    return;
  }

  if (!/^[0-9a-fA-F]{1,2}$/.test(codeStr)) {
    showCommandMessage('命令字节格式错误，请输入 1~2 位 16 进制数。');
    return;
  }

  await sendBbByCode(device_id, codeStr);
};
</script>

<style scoped>
.login-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  background-color: #ffffff;
}

.box-card {
  width: 480px;
  border-radius: 10px;
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
}

.login-box,
.command-box {
  text-align: center;
}

.input-field {
  margin-bottom: 20px;
}

.direction-buttons,
.mode-buttons,
.send-buttons,
.custom-command {
  margin-top: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  flex-wrap: wrap;
}

.remote-confirm {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  flex-wrap: wrap;
}

.remote-confirm-text {
  color: #606266;
}

.custom-input {
  max-width: 180px;
}

.error-message {
  color: red;
  margin-top: 10px;
}

.response-message {
  margin-top: 10px;
  font-size: 14px;
}

.response-message.success {
  color: green;
}

.response-message.error {
  color: red;
}
</style>
