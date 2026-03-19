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
        <el-button type="primary" @click="validatePassword" class="login-button">验证</el-button>
        <p v-if="error" class="error-message">{{ error }}</p>
      </div>

      <!-- 操作界面 -->
      <div v-else class="command-box">
        <device-name-component />

        <h3>发送切换模式命令</h3>
        <div class="direction-buttons">
          本站方向选择：
          <el-button
            :type="selectedDirection === 'direction1' ? 'primary' : 'default'"
            @click="selectedDirection = 'direction1'"
          >一方向</el-button>
          <el-button
            :type="selectedDirection === 'direction2' ? 'primary' : 'default'"
            @click="selectedDirection = 'direction2'"
          >二方向</el-button>
        </div>

        <div class="mode-buttons">
          模式选择：
          <el-button v-for="(label, mode) in modes" :key="mode"
                     :type="selectedMode === mode ? 'primary' : 'default'"
                     @click="selectedMode = mode">
            {{ label }}
          </el-button>
        </div>

        <div class="send-buttons">
          <el-button type="success" @click="sendCommand(device_id)">向本站发送</el-button>
          <el-button type="success" @click="sendNeighborCommand">向邻站发送</el-button>
        </div>

        <el-divider />
        <p v-if="error" class="error-message">
          {{ error }}
        </p>

        <el-divider />
        <h3>其他远程控制</h3>
        <div class="send-buttons">
          <el-button type="warning" @click="sendRestartCommand">
            重启当前网管板
          </el-button>
        </div>

        <el-divider />
        <h3>自定义命令</h3>
        <div class="custom-command">
          <span>命令字节：</span>
          <el-input
            v-model="customCommand"
            placeholder="例如 0x05 或 05"
            class="custom-input"
          ></el-input>
          <el-button type="primary" @click="sendCustomCommand(device_id)">向本站发送</el-button>
          <el-button type="primary" @click="sendNeighborCustomCommand">向邻站发送</el-button>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import axios from 'axios';
import { useRoute } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import DeviceNameComponent from '@/components/DeviceNameComponent.vue';
import { useUserStore } from '@/stores/userStore';
import { getApiBase, getSystemFromRoute } from '@/utils/systems';

const route = useRoute();
const device_id = route.params.index as string;
const selectedMode = ref<string | null>(null);
const selectedDirection = ref<string | null>(null);
const customCommand = ref('');
const password = ref('');
const error = ref('');
const isAuthenticated = ref(false);

const userStore = useUserStore();
const baseURL = () => getApiBase(getSystemFromRoute(route.params.system));
const username = computed(() => userStore.user?.username ?? null);

const modes = {
  cable: '强制电缆',
  fiber: '强制光缆',
  auto: '自动'
};

const modeOperationMap: Record<string, number> = {
  cable: 1,
  fiber: 3,
  auto: 2
};

const validatePassword = () => {
  if (password.value === 'fasong') {
    isAuthenticated.value = true;
    error.value = '';
  } else {
    error.value = '密码错误，请重试。';
  }
};

const showError = (message: string) => {
  error.value = message;
};

const showResponse = (message: string, type: 'success' | 'error') => {
  if (type === 'success') {
    error.value = '';
    ElMessage.success(message);
  } else {
    ElMessage.error(message);
  }
};

const getDirectionFunctionCode = (direction: string | null) => {
  if (!direction) {
    return null;
  }
  return direction === 'direction1' ? 1 : 2;
};

const sendPacketCommand = async (targetId: string, functionCode: number, operation: number) => {
  if (!username.value) {
    showError('用户信息为空，请重新登录。');
    return;
  }

  try {
    const response = await axios.post(`${baseURL()}/send-command/${targetId}/`, {
      function_code: functionCode,
      time: Math.floor(Date.now() / 1000),
      operation,
      username: username.value
    });
    showResponse(response.data.status, 'success');
  } catch (err: any) {
    console.error('Error:', err);
    showResponse(err.response?.data?.message || '发送失败，请重试。', 'error');
  }
};

const getNeighborInfo = async () => {
  const response = await axios.get(`${baseURL()}/devices/?device_id=${device_id}`);

  if (response.data.results.length === 0) {
    throw new Error('未找到设备信息。');
  }

  const deviceData = response.data.results[0];
  const neighborId = selectedDirection.value === 'direction1'
    ? deviceData.direction1_neighbor_id
    : deviceData.direction2_neighbor_id;
  const neighborDirection = selectedDirection.value === 'direction1'
    ? deviceData.direction1_neighbor_direction
    : deviceData.direction2_neighbor_direction;

  if (!neighborId) {
    throw new Error('未找到邻站设备。');
  }

  if (![1, 2].includes(neighborDirection)) {
    throw new Error('邻站方向配置错误。');
  }

  return {
    neighborId: String(neighborId),
    neighborDirection
  };
};

const parseCustomOperation = () => {
  const input = customCommand.value.trim();
  if (!input) {
    showError('请输入命令字节（16进制）。');
    return null;
  }

  const normalized = input.toLowerCase().startsWith('0x') ? input.slice(2) : input;
  if (!/^[0-9a-fA-F]{1,2}$/.test(normalized)) {
    showError('命令字节格式错误，请输入 1~2 位 16 进制数。');
    return null;
  }

  return parseInt(normalized, 16);
};

const sendCommand = async (targetId: string) => {
  if (!selectedMode.value || !selectedDirection.value) {
    showError('请选择模式和方向。');
    return;
  }

  const functionCode = getDirectionFunctionCode(selectedDirection.value);
  if (functionCode === null) {
    showError('方向配置错误。');
    return;
  }

  await sendPacketCommand(targetId, functionCode, modeOperationMap[selectedMode.value]);
};

const sendNeighborCommand = async () => {
  if (!selectedMode.value || !selectedDirection.value) {
    showError('请选择模式和方向。');
    return;
  }

  try {
    const { neighborId, neighborDirection } = await getNeighborInfo();
    await sendPacketCommand(neighborId, neighborDirection, modeOperationMap[selectedMode.value]);
  } catch (err: any) {
    console.error('Error:', err);
    showResponse(err.message || '获取邻站信息失败。', 'error');
  }
};

const sendCustomCommand = async (targetId: string) => {
  if (!selectedDirection.value) {
    showError('请选择方向。');
    return;
  }

  const operation = parseCustomOperation();
  const functionCode = getDirectionFunctionCode(selectedDirection.value);
  if (operation === null || functionCode === null) {
    return;
  }

  await sendPacketCommand(targetId, functionCode, operation);
};

const sendNeighborCustomCommand = async () => {
  if (!selectedDirection.value) {
    showError('请选择方向。');
    return;
  }

  const operation = parseCustomOperation();
  if (operation === null) {
    return;
  }

  try {
    const { neighborId, neighborDirection } = await getNeighborInfo();
    await sendPacketCommand(neighborId, neighborDirection, operation);
  } catch (err: any) {
    console.error('Error:', err);
    showResponse(err.message || '获取邻站信息失败。', 'error');
  }
};

const sendRestartCommand = async () => {
  try {
    await ElMessageBox.confirm(
      '确认重启当前网管板吗？',
      '确认发送重启命令',
      {
        confirmButtonText: '确认发送',
        cancelButtonText: '取消',
        type: 'warning',
      }
    );
  } catch {
    ElMessage.info('已取消发送');
    return;
  }

  await sendPacketCommand(device_id, 0x05, 0);
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

.custom-input {
  max-width: 180px;
}

.error-message {
  color: red;
  margin-top: 10px;
}
</style>
