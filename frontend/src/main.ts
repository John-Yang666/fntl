import { createApp } from 'vue';
import {
  ElAlert,
  ElAside,
  ElButton,
  ElCard,
  ElCheckbox,
  ElCol,
  ElCollapse,
  ElCollapseItem,
  ElContainer,
  ElDatePicker,
  ElDialog,
  ElDivider,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElHeader,
  ElInput,
  ElInputNumber,
  ElLoading,
  ElMain,
  ElMenu,
  ElMenuItem,
  ElOption,
  ElPagination,
  ElPopconfirm,
  ElRow,
  ElSelect,
  ElSkeleton,
  ElSkeletonItem,
  ElSubMenu,
  ElSwitch,
  ElTabPane,
  ElTable,
  ElTableColumn,
  ElTabs,
  ElTag,
  ElTimePicker,
  ElTransfer,
  ElUpload,
  provideGlobalConfig,
} from 'element-plus';
import zhCn from 'element-plus/es/locale/lang/zh-cn';
import * as ElIcons from '@element-plus/icons-vue';
import 'element-plus/dist/index.css';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import App from './App.vue';
import router from './router/index';
import { createPinia } from 'pinia';
import { useUserStore } from '@/stores/userStore';

const pinia = createPinia();
const app = createApp(App);
const elementComponents = [
  ElAlert,
  ElAside,
  ElButton,
  ElCard,
  ElCheckbox,
  ElCol,
  ElCollapse,
  ElCollapseItem,
  ElContainer,
  ElDatePicker,
  ElDialog,
  ElDivider,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElHeader,
  ElInput,
  ElInputNumber,
  ElMain,
  ElMenu,
  ElMenuItem,
  ElOption,
  ElPagination,
  ElPopconfirm,
  ElRow,
  ElSelect,
  ElSkeleton,
  ElSkeletonItem,
  ElSubMenu,
  ElSwitch,
  ElTabPane,
  ElTable,
  ElTableColumn,
  ElTabs,
  ElTag,
  ElTimePicker,
  ElTransfer,
  ElUpload,
];

// Register all icons
for (const [key, component] of Object.entries(ElIcons)) {
  app.component(key, component);
}

for (const component of elementComponents) {
  app.use(component);
}

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

app.mount('#app');
