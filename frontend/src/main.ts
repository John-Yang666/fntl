import { createApp } from 'vue';
import ElementPlus from 'element-plus';
import zhCn from 'element-plus/es/locale/lang/zh-cn';
import * as ElIcons from '@element-plus/icons-vue';
import 'element-plus/dist/index.css';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import App from './App.vue';
import router from './router/index';
import { createPinia } from 'pinia';
import { useUserStore } from '@/stores/userStore'

const pinia = createPinia();
const app = createApp(App);

// Register all icons
for (const [key, component] of Object.entries(ElIcons)) {
    app.component(key, component);
  }

app.use(pinia);
app.use(router);
dayjs.locale('zh-cn');
app.use(ElementPlus, { locale: zhCn });

// 恢复 IndexedDB 中的用户数据
const userStore = useUserStore()
userStore.loadAuthData().then(() => {
  // 已经从 IndexedDB 恢复 token、user 等数据
});

app.mount('#app');
