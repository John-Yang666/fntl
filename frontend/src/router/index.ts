import { createRouter, createWebHistory } from 'vue-router';
import type { RouteRecordRaw } from 'vue-router';
import { useUserStore } from '@/stores/userStore';

const routes: RouteRecordRaw[] = [
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
    redirect: to => `/bt/device/${to.params.index}`
  },
  {
    path: '/:system(bt|sy)/device/:index',
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
    path: '/runtime-config',
    name: 'runtimeConfig',
    component: () => import('../views/RuntimeConfigView.vue'),
    meta: { requiresAuth: true, requiresSuperuser: true }
  },
  {
    path: '/topology',
    name: 'TopologyGraph',
    component: () => import('../views/TopologyGraph.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/switch-mode/:index',
    redirect: to => `/bt/switch-mode/${to.params.index}`
  },
  {
    path: '/:system(bt|sy)/switch-mode/:index',
    name: 'switchMode',
    component: () => import('../views/SwitchModeView.vue'),
    meta: { requiresAuth: true, hideHeader: true }
  },
  {
    path: '/restart-command/:index',
    redirect: to => `/bt/restart-command/${to.params.index}`
  },
  {
    path: '/:system(bt|sy)/restart-command/:index',
    name: 'restartCommand',
    component: () => import('../views/RestartCommandView.vue'),
    meta: { requiresAuth: true, hideHeader: true }
  }
];

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
});

router.beforeEach(async (to, from, next) => {
  const userStore = useUserStore();
  await userStore.loadAuthData();

  if (to.matched.some(record => record.meta.requiresAuth)) {
    if (!userStore.isAuthenticated) {
      next({ path: '/login', query: { redirect: to.fullPath } });
    } else {
      try {
        await userStore.ensureUsersLoaded();
        if (to.matched.some((record) => record.meta.requiresSuperuser) && !userStore.isSuperuser) {
          next({ path: '/main' });
          return;
        }
        next();
      } catch (error) {
        await userStore.logout();
        next({ path: '/login', query: { redirect: to.fullPath } });
      }
    }
  } else {
    next();
  }
});

export default router;
