<template>
  <div class="login-container" data-testid="login-view">
    <div class="login-header">
      <h2>武汉贝通 / SY 统一网管登录</h2>
    </div>
    <form @submit.prevent="handleLogin">
      <div class="input-group">
        <label for="username">用户名</label>
        <input v-model="username" id="username" data-testid="login-username" type="text" required />
      </div>
      <div class="input-group">
        <label for="password">密码</label>
        <input v-model="password" id="password" data-testid="login-password" type="password" required />
      </div>
      <button type="submit" class="login-button" data-testid="login-submit">登录</button>
    </form>
    <p v-if="error" class="error-message">{{ error }}</p>
  </div>
</template>

<script lang="ts">
import { defineComponent, ref, onMounted } from 'vue';
import { useUserStore } from '@/stores/userStore';
import { useRouter, useRoute } from 'vue-router';

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
        error.value = err instanceof Error ? err.message : '登录失败，请检查用户名或密码。';
      }
    };

    onMounted(async () => {
      try {
        await userStore.loadAuthData();
        if (userStore.isAuthenticated) {
          await userStore.ensureUsersLoaded();
          const redirectPath = (route.query.redirect as string) || '/';
          router.push(redirectPath);
        }
      } catch {
        userStore.logout();
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
