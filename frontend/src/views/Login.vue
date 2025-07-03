<template>
  <div class="login-container">
    <div class="login-header">
      <h2>武汉贝通网管登陆</h2>
    </div>
    <form @submit.prevent="handleLogin">
      <div class="input-group">
        <label for="username">用户名</label>
        <input v-model="username" id="username" type="text" required />
      </div>
      <div class="input-group">
        <label for="password">密码</label>
        <input v-model="password" id="password" type="password" required />
      </div>
      <button type="submit" class="login-button">登陆</button>
    </form>
    <p v-if="error" class="error-message">{{ error }}</p>
  </div>
</template>

<script lang="ts">
import { defineComponent, ref, onMounted } from 'vue';
import { useUserStore } from '@/stores/userStore';
import { useRouter, useRoute } from 'vue-router';
import { getFromDB } from '@/utils/indexedDB';

export default defineComponent({
  setup() {
    const userStore = useUserStore();
    const router = useRouter();
    const route = useRoute();
    const username = ref('');
    const password = ref('');
    const error = ref('');

    // 处理用户登录
    const handleLogin = async () => {
      try {
        await userStore.login(username.value, password.value);
        const redirectPath = (route.query.redirect as string) || '/';
        router.push(redirectPath);
      } catch (err) {
        error.value = '登录失败，请检查用户名或密码。';
      }
    };

    // 应用启动时检查用户是否已登录
    onMounted(async () => {
      try {
        const tokenData = await getFromDB<{ access: string }>('token'); // 🔹 使用 IndexedDB 获取 token
        if (tokenData?.access) {
          await userStore.fetchUserDetails();
          const redirectPath = (route.query.redirect as string) || '/';
          router.push(redirectPath); // ✅ 如果已登录，自动跳转
        }
      } catch {
        userStore.logout(); // 🔹 如果获取失败，执行登出清理
      }
    });

    return {
      username,
      password,
      error,
      handleLogin,
    };
  }
});
</script>

<style scoped>
.login-container {
  max-width: 400px;
  margin: 0 auto;
  padding: 2em;
  border-radius: 10px;
  box-shadow: 0 0 15px rgba(0, 0, 0, 0.1);
  background-color: #fff;
}

.login-header {
  text-align: center;
  margin-bottom: 1em;
}

h2 {
  color: #1878ff;
  font-weight: bold;
}

.input-group {
  margin-bottom: 1em;
}

label {
  display: block;
  margin-bottom: 0.5em;
  color: #333;
}

input {
  width: calc(100% - 20px);
  padding: 10px;
  border-radius: 5px;
  border: 1px solid #ccc;
}

.login-button {
  width: 100%;
  padding: 10px;
  border: none;
  border-radius: 5px;
  background-color: #1878ff;
  color: #fff;
  font-size: 1em;
  cursor: pointer;
  transition: background-color 0.3s;
}

.login-button:hover {
  background-color: #005bb5;
}

.error-message {
  color: red;
  text-align: center;
  margin-top: 1em;
}
</style>
