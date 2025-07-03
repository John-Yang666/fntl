import { createApp } from 'vue';
import ElementPlus from 'element-plus';
import * as ElIcons from '@element-plus/icons-vue';
import 'element-plus/dist/index.css';
import App from './App.vue';
import router from './router';
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
app.use(ElementPlus);

app.mount('#app');

// 恢复 IndexedDB 中的用户数据
const userStore = useUserStore()
userStore.loadAuthData().then(() => {
  // 已经从 IndexedDB 恢复 token、user 等数据
})