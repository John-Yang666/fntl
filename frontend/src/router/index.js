import { __awaiter, __generator } from "tslib";
import { createRouter, createWebHistory } from 'vue-router';
import { useUserStore } from '@/stores/userStore';
var routes = [
    {
        path: '/',
        name: 'home',
        component: function () { return import('../views/Main.vue'); },
        meta: { requiresAuth: true }
    },
    {
        path: '/login',
        name: 'login',
        component: function () { return import('../views/Login.vue'); }
    },
    {
        path: '/about',
        name: 'about',
        component: function () { return import('../views/AboutView.vue'); },
        meta: { requiresAuth: true }
    },
    {
        path: '/main',
        name: 'main',
        component: function () { return import('../views/Main.vue'); },
        meta: { requiresAuth: true }
    },
    {
        path: '/records',
        name: 'records',
        component: function () { return import('../views/RecordsView.vue'); },
        meta: { requiresAuth: true }
    },
    {
        path: '/device/:index',
        name: 'device',
        component: function () { return import('../views/DeviceView.vue'); },
        meta: { requiresAuth: true }
    },
    {
        path: '/alerts',
        name: 'alerts',
        component: function () { return import('../views/AlertsView.vue'); },
        meta: { requiresAuth: true }
    },
    {
        path: '/help',
        name: 'help',
        component: function () { return import('../views/HelpView.vue'); },
        meta: { requiresAuth: true }
    },
    {
        path: '/topology',
        name: 'TopologyGraph',
        component: function () { return import('../views/TopologyGraph.vue'); },
        meta: { requiresAuth: true }
    },
    {
        path: '/switch-mode/:index',
        name: 'switchMode',
        component: function () { return import('../views/SwitchModeView.vue'); },
        meta: { requiresAuth: true }
    },
    {
        path: '/restart-command/:index',
        name: 'restartCommand',
        component: function () { return import('../views/RestartCommandView.vue'); },
        meta: { requiresAuth: true }
    }
];
var router = createRouter({
    history: createWebHistory(import.meta.env.BASE_URL),
    routes: routes
});
router.beforeEach(function (to, from, next) { return __awaiter(void 0, void 0, void 0, function () {
    var userStore, token, error_1;
    return __generator(this, function (_a) {
        switch (_a.label) {
            case 0:
                userStore = useUserStore();
                token = JSON.parse(localStorage.getItem('token') || '{}');
                if (!(token && token.access)) return [3 /*break*/, 4];
                _a.label = 1;
            case 1:
                _a.trys.push([1, 3, , 4]);
                return [4 /*yield*/, userStore.fetchUserDetails()];
            case 2:
                _a.sent();
                return [3 /*break*/, 4];
            case 3:
                error_1 = _a.sent();
                userStore.logout();
                next({ path: '/login', query: { redirect: to.fullPath } });
                return [2 /*return*/];
            case 4:
                if (to.matched.some(function (record) { return record.meta.requiresAuth; })) {
                    if (!userStore.isAuthenticated) {
                        next({ path: '/login', query: { redirect: to.fullPath } });
                    }
                    else {
                        next();
                    }
                }
                else {
                    next();
                }
                return [2 /*return*/];
        }
    });
}); });
export default router;
