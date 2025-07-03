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

        <h3>发送切换模式命令</h3>
        <div class="send-buttons">
          <el-button type="success" @click="sendCommand(device_id)">向本站发送</el-button>
          <el-button type="success" @click="sendNeighborCommand">向邻站发送</el-button>
        </div>

        <!-- 显示响应信息 -->
        <p v-if="responseMessage" :class="['response-message', messageType]">
          {{ responseMessage }}
        </p>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import axios from 'axios';
import { useRoute } from 'vue-router';
import DeviceNameComponent from '@/components/DeviceNameComponent.vue';
import { useUserStore } from '@/stores/userStore';

const route = useRoute();
const device_id = route.params.index as string;
const selectedMode = ref<string | null>(null);
const selectedDirection = ref<string | null>(null);
const password = ref('');
const error = ref('');
const isAuthenticated = ref(false);
const responseMessage = ref(''); // 用于存储后端的响应信息
const messageType = ref<'success' | 'error'>('success'); // 消息类型

// 动态获取当前浏览器地址栏的 IP 或域名
const backendPort = import.meta.env.VITE_BACKEND_PORT;
const baseURL = `${window.location.protocol}//${window.location.hostname}:${backendPort}/api`;
const userStore = useUserStore();

const modes = {
  cable: '强制电缆',
  fiber: '强制光缆',
  auto: '自动'
};

const validatePassword = () => {
  if (password.value === 'fasong') {
    isAuthenticated.value = true;
    error.value = '';
  } else {
    error.value = '密码错误，请重试。';
  }
};

const sendCommand = async (targetId: string) => {
  if (!selectedMode.value || !selectedDirection.value) {
    error.value = '请选择模式和方向。';
    return;
  }

  try {
    const username = computed(() => userStore.user?.username ?? null);
    const response = await axios.post(`${baseURL}/send-command/${targetId}/`, {
      function_code: selectedDirection.value === 'direction1' ? 1 : 2,
      time: Math.floor(Date.now() / 1000),
      operation: { cable: 1, fiber: 3, auto: 2 }[selectedMode.value],
      username: username.value
    });
    // 请求成功时
    responseMessage.value = response.data.status;
    messageType.value = 'success';
    error.value = '';
  } catch (err: any) {
    console.error('Error:', err);
    // 请求失败时
    responseMessage.value = err.response?.data?.message || '发送失败，请重试。';
    messageType.value = 'error';
  }
};

const sendNeighborCommand = async () => {
  try {
    const response = await axios.get(`${baseURL}/devices/?device_id=${device_id}`);
    
    if (response.data.results.length === 0) {
      responseMessage.value = '未找到设备信息。';
      messageType.value = 'error';
      return;
    }

    const deviceData = response.data.results[0];  // 获取设备的实际数据

    const neighborId = selectedDirection.value === 'direction1'
      ? deviceData.direction1_neighbor_id
      : deviceData.direction2_neighbor_id;

    const neighborDirection = selectedDirection.value === 'direction1'
      ? deviceData.direction1_neighbor_direction
      : deviceData.direction2_neighbor_direction;

    if (neighborId) {
      // 直接调用 sendCommand，传入邻站的方向
      if (!selectedMode.value) {
        error.value = '请选择模式。';
        return;
      }

      const username = computed(() => userStore.user?.username ?? null);
      const commandResponse = await axios.post(`${baseURL}/send-command/${neighborId}/`, {
        function_code: neighborDirection,  // 使用邻站的方向
        time: Math.floor(Date.now() / 1000),
        operation: { cable: 1, fiber: 3, auto: 2 }[selectedMode.value],
        username: username.value
      });

      // 请求成功时
      responseMessage.value = commandResponse.data.status;
      messageType.value = 'success';
      error.value = '';
    } else {
      responseMessage.value = '未找到邻站设备。';
      messageType.value = 'error';
    }
  } catch (err) {
    console.error('Error:', err);
    responseMessage.value = '获取邻站信息失败。';
    messageType.value = 'error';
  }
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
  width: 400px;
  border-radius: 10px;
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
}

.login-box, .command-box {
  text-align: center;
}

.input-field {
  margin-bottom: 20px;
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
