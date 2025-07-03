import { defineStore } from 'pinia';
import authApi from '@/authApi';
import { saveToDB, getFromDB, deleteFromDB } from '@/utils/indexedDB';

interface User {
  username: string;
  email: string;
  groups: string[];
  is_staff: boolean;
  is_superuser: boolean;
  permissions: string[];
}

interface UserState {
  user: User | null;
  token: string | null;
  refreshToken: string | null;
}

export const useUserStore = defineStore('user', {
  state: (): UserState => ({
    user: null,
    token: null,
    refreshToken: null,
  }),
  actions: {
    /**
     * 在应用启动时(如 main.ts / App.vue onMounted 里) 调用
     * 以恢复 IndexedDB 中的 token、refreshToken、user 到 Pinia state
     */
    async loadAuthData(): Promise<void> {
      const tokenData = await getFromDB<{ access: string; refresh: string }>('token');
      if (tokenData) {
        this.token = tokenData.access;
        this.refreshToken = tokenData.refresh;
      }

      const userData = await getFromDB<User>('user');
      if (userData) {
        this.user = userData;
      }
    },

    /** 登录并持久化 token、refreshToken、user */
    async login(username: string, password: string): Promise<void> {
      try {
        const response = await authApi.post('/token/', { username, password });
        const { access, refresh } = response.data;

        // 更新 Pinia state
        this.token = access;
        this.refreshToken = refresh;

        // 写入 IndexedDB
        await saveToDB('token', { access, refresh });

        // 拉取用户详情并存储
        await this.fetchUserDetails();
      } catch (error) {
        throw new Error('Failed to login');
      }
    },

    /** 获取用户信息并存储到 Pinia & IndexedDB */
    async fetchUserDetails(): Promise<void> {
      try {
        const tokenData = await getFromDB<{ access: string; refresh: string }>('token');
        if (tokenData?.access) {
          const response = await authApi.get('/user/', {
            headers: {
              Authorization: `Bearer ${tokenData.access}`,
            },
          });
          this.user = response.data;
          await saveToDB('user', response.data); // 持久化用户信息
        }
      } catch (error) {
        // 拉取失败，说明当前 token 不可用，登出清理
        await this.logout();
        throw new Error('Failed to fetch user details');
      }
    },

    /** 通过 refresh token 刷新 access token */
    async refreshTokenAction(): Promise<void> {
      try {
        const tokenData = await getFromDB<{ access: string; refresh: string }>('token');
        if (!tokenData?.refresh) {
          throw new Error('No refresh token available');
        }

        const response = await authApi.post('/token/refresh/', { refresh: tokenData.refresh });
        const newToken = response.data.access;

        this.updateToken(newToken);
      } catch (error) {
        // 若刷新失败，强制登出
        await this.logout();
        throw new Error('Failed to refresh token');
      }
    },

    /** 更新 Pinia & IndexedDB 中的 access token */
    async updateToken(newToken: string): Promise<void> {
      this.token = newToken;
      const tokenData = await getFromDB<{ access: string; refresh: string }>('token');
      if (tokenData) {
        tokenData.access = newToken;
        await saveToDB('token', tokenData);
      }
    },

    /** 清空 Pinia & IndexedDB 中的所有凭据 */
    async logout(): Promise<void> {
      this.user = null;
      this.token = null;
      this.refreshToken = null;
      await deleteFromDB('token');
      await deleteFromDB('user');
    }
  },
  getters: {
    /** 通过 token 是否为空来判断是否已登录 */
    isAuthenticated: (state: UserState): boolean => !!state.token,
    /** 是否为管理员 */
    isAdmin: (state: UserState): boolean => state.user?.groups.includes('System Admin') || false,
    /** 检查某个权限 */
    hasPermission: (state: UserState): (permission: string) => boolean => (permission: string): boolean =>
      state.user?.permissions.includes(permission) || false,
  }
});
