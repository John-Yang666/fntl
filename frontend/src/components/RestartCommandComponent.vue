<template>
    <div class="login-container">
      <el-card class="box-card">
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
        <div v-else class="command-box">
          <p><device-name-component /></p>
          <h3>发送重启网管板命令</h3>
          <div class="command-button">
            <el-button type="primary" @click="sendRestartCommand">发送</el-button>
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
const password = ref('');
const error = ref('');
const isAuthenticated = ref(false);
const responseMessage = ref(''); // 存储后端的响应信息
const messageType = ref<'success' | 'error'>('success'); // 消息类型

// 动态获取当前浏览器地址栏的 IP 或域名
const backendPort = import.meta.env.VITE_BACKEND_PORT;
const baseURL = `${window.location.protocol}//${window.location.hostname}:${backendPort}/api`;
const userStore = useUserStore();

const validatePassword = () => {
  const correctPassword = 'chongqi'; // 替换为实际密码
  if (password.value === correctPassword) {
    isAuthenticated.value = true;
    error.value = '';
  } else {
    error.value = '密码错误，请重试。';
  }
};

const sendRestartCommand = async () => {
  if (!isAuthenticated.value) {
    error.value = '请先验证密码。';
    return;
  }

  const functionCode = 0x05;
  const modeByte = 0;
  const username = computed(() => userStore.user?.username ?? null);

  try {
    const response = await axios.post(`${baseURL}/send-command/${device_id}/`, {
      function_code: functionCode,
      time: Math.floor(Date.now() / 1000),
      operation: modeByte,
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
  padding: 0px 20px 20px 20px; /* 仅减少顶部的 padding */
  border-radius: 10px;
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
  background-color: #ffffff;
}

.login-box, .command-box {
  text-align: center;
}

.input-field {
  margin-bottom: 20px;
}

.login-button, .direction-buttons el-button, .command-button el-button {
  width: 100%;
  margin-bottom: 10px;
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