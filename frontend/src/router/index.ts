import { createRouter, createWebHistory } from 'vue-router';
import { useUserStore } from '@/stores/userStore';
import { getFromDB } from '@/utils/indexedDB';

const routes = [
  {
    path: '/',
    name: 'home',
    component: () => import('../views/Main.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/Login.vue')
  },
  {
    path: '/about',
    name: 'about',
    component: () => import('../views/AboutView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/main',
    name: 'main',
    component: () => import('../views/Main.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/records',
    name: 'records',
    component: () => import('../views/RecordsView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/device/:index',
    name: 'device',
    component: () => import('../views/DeviceView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/alerts',
    name: 'alerts',
    component: () => import('../views/AlertsView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/help',
    name: 'help',
    component: () => import('../views/HelpView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/topology',
    name: 'TopologyGraph',
    component: () => import('../views/TopologyGraph.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/switch-mode/:index',
    name: 'switchMode',
    component: () => import('../views/SwitchModeView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/restart-command/:index',
    name: 'restartCommand',
    component: () => import('../views/RestartCommandView.vue'),
    meta: { requiresAuth: true }
  }
];

const router = createRouter({
  history: createWebHistory(window.location.pathname),
  routes
});

router.beforeEach(async (to, from, next) => {
  const userStore = useUserStore();
  
  // ✅ 从 IndexedDB 获取 token
  const tokenData = await getFromDB<{ access: string }>('token');

  if (tokenData?.access) {
    try {
      if (!userStore.isAuthenticated) {
        await userStore.fetchUserDetails();
      }
    } catch (error) {
      await userStore.logout();
      next({ path: '/login', query: { redirect: to.fullPath } });
      return;
    }
  }

  // ✅ 处理受保护路由访问
  if (to.matched.some(record => record.meta.requiresAuth)) {
    if (!userStore.isAuthenticated) {
      next({ path: '/login', query: { redirect: to.fullPath } });
    } else {
      next();
    }
  } else {
    next();
  }
});

export default router;
