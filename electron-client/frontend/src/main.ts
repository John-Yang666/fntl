import { createApp } from 'vue';
import { provideGlobalConfig } from 'element-plus/es/components/config-provider/index.mjs';
import { ElLoading } from 'element-plus/es/components/loading/index.mjs';
import 'element-plus/es/components/loading/style/css';
import 'element-plus/es/components/message/style/css';
import 'element-plus/es/components/message-box/style/css';
import zhCn from 'element-plus/es/locale/lang/zh-cn';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import App from './App.vue';
import router from './router/index';
import { createPinia } from 'pinia';
import { useUserStore } from '@/stores/userStore';
import { initializeDesktopClientConfig } from '@/utils/clientRuntime';

const bootstrap = async () => {
  await initializeDesktopClientConfig();

  const pinia = createPinia();
  const app = createApp(App);

  app.use(pinia);
  app.use(router);
  app.use(ElLoading);
  provideGlobalConfig({ locale: zhCn }, app, true);
  dayjs.locale('zh-cn');

  // 恢复 IndexedDB 中的用户数据
  const userStore = useUserStore();
  userStore.loadAuthData().then(() => {
    // 已经从 IndexedDB 恢复 token、user 等数据
  });

  await router.isReady();
  app.mount('#app');
};

void bootstrap();
