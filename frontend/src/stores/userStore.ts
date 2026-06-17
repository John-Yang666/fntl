import axios, { type AxiosRequestConfig } from 'axios';
import { defineStore } from 'pinia';
import { deleteFromDB, getFromDB, saveToDB } from '@/utils/indexedDB';
import { formatLoginFailureMessage, type LoginSystemFailure } from '@/utils/loginErrorMessage';
import {
  SYSTEMS,
  TOKEN_STORAGE_KEYS,
  USER_STORAGE_KEYS,
  type SystemType,
  getApiBase,
} from '@/utils/systems';

interface User {
  username: string;
  email: string;
  groups: string[];
  is_staff: boolean;
  is_superuser: boolean;
  permissions: string[];
}

interface UserState {
  auth: Record<SystemType, {
    user: User | null;
    token: string | null;
    refreshToken: string | null;
  }>;
}

export const useUserStore = defineStore('user', {
  state: (): UserState => ({
    auth: {
      bt: {
        user: null,
        token: null,
        refreshToken: null,
      },
      sy: {
        user: null,
        token: null,
        refreshToken: null,
      },
    },
  }),
  actions: {
    async loadAuthData(): Promise<void> {
      await Promise.all(SYSTEMS.map(async (system) => {
        const tokenData = await getFromDB<{ access: string; refresh: string }>(
          TOKEN_STORAGE_KEYS[system],
        );
        if (tokenData) {
          this.auth[system].token = tokenData.access;
          this.auth[system].refreshToken = tokenData.refresh;
        }

        const userData = await getFromDB<User>(USER_STORAGE_KEYS[system]);
        if (userData) {
          this.auth[system].user = userData;
        }
      }));
    },

    async login(username: string, password: string): Promise<void> {
      const results = await Promise.allSettled(SYSTEMS.map(async (system) => {
        const response = await axios.post(`${getApiBase(system)}/token/`, {
          username,
          password,
        });

        const { access, refresh } = response.data;
        this.auth[system].token = access;
        this.auth[system].refreshToken = refresh;
        await saveToDB(TOKEN_STORAGE_KEYS[system], { access, refresh });
        await this.fetchUserDetails(system);
      }));

      const settledResults = results.map((result, index) => ({ result, system: SYSTEMS[index] }));
      const successfulSystems = settledResults
        .filter(({ result }) => result.status === 'fulfilled')
        .map(({ system }) => system);
      const failedResults = settledResults
        .filter((item): item is { result: PromiseRejectedResult; system: SystemType } =>
          item.result.status === 'rejected',
        );
      const failedSystems = failedResults.map(({ system }) => system);

      await Promise.all(failedSystems.map((system) => this.logoutSystem(system)));

      if (successfulSystems.length === 0) {
        const failures: LoginSystemFailure[] = failedResults.map(({ result, system }) => ({
          system,
          error: result.reason,
          apiBase: getApiBase(system),
        }));
        await this.logout();
        throw new Error(formatLoginFailureMessage(failures));
      }
    },

    async fetchUserDetails(system: SystemType): Promise<void> {
      const tokenData = await getFromDB<{ access: string; refresh: string }>(TOKEN_STORAGE_KEYS[system]);
      if (!tokenData?.access) {
        throw new Error(`No access token for ${system}`);
      }

      try {
        const response = await axios.get(`${getApiBase(system)}/user/`, {
          headers: {
            Authorization: `Bearer ${tokenData.access}`,
          },
        });
        this.auth[system].user = response.data;
        await saveToDB(USER_STORAGE_KEYS[system], response.data);
      } catch (error) {
        if (axios.isAxiosError(error) && error.response?.status === 401 && tokenData.refresh) {
          await this.refreshTokenAction(system);
          const refreshed = await getFromDB<{ access: string; refresh: string }>(TOKEN_STORAGE_KEYS[system]);
          if (!refreshed?.access) {
            throw error;
          }

          const retry = await axios.get(`${getApiBase(system)}/user/`, {
            headers: {
              Authorization: `Bearer ${refreshed.access}`,
            },
          });
          this.auth[system].user = retry.data;
          await saveToDB(USER_STORAGE_KEYS[system], retry.data);
          return;
        }

        await this.logoutSystem(system);
        throw new Error(`Failed to fetch user details for ${system}`);
      }
    },

    async refreshTokenAction(system: SystemType): Promise<void> {
      const tokenData = await getFromDB<{ access: string; refresh: string }>(TOKEN_STORAGE_KEYS[system]);
      if (!tokenData?.refresh) {
        throw new Error(`No refresh token available for ${system}`);
      }

      const response = await axios.post(`${getApiBase(system)}/token/refresh/`, {
        refresh: tokenData.refresh,
      });
      const newToken = response.data.access;
      const newRefreshToken = response.data.refresh || tokenData.refresh;
      await this.updateToken(system, newToken, newRefreshToken);
    },

    async updateToken(system: SystemType, newToken: string, newRefreshToken?: string): Promise<void> {
      this.auth[system].token = newToken;
      if (newRefreshToken) {
        this.auth[system].refreshToken = newRefreshToken;
      }
      const tokenData = await getFromDB<{ access: string; refresh: string }>(TOKEN_STORAGE_KEYS[system]);
      if (tokenData) {
        tokenData.access = newToken;
        if (newRefreshToken) {
          tokenData.refresh = newRefreshToken;
        }
        await saveToDB(TOKEN_STORAGE_KEYS[system], tokenData);
      }
    },

    async ensureUsersLoaded(): Promise<void> {
      const results = await Promise.allSettled(SYSTEMS.map(async (system) => {
        if (this.auth[system].token && !this.auth[system].user) {
          await this.fetchUserDetails(system);
        }
      }));

      const failedSystems = results
        .map((result, index) => ({ result, system: SYSTEMS[index] }))
        .filter(({ result, system }) => result.status === 'rejected' && !!this.auth[system].token)
        .map(({ system }) => system);

      if (failedSystems.length > 0) {
        await Promise.all(failedSystems.map((system) => this.logoutSystem(system)));
      }

      if (!this.isAuthenticated) {
        throw new Error('No authenticated systems available');
      }
    },

    async getAuthHeaders(system: SystemType): Promise<Record<string, string>> {
      const tokenData = await getFromDB<{ access: string; refresh: string }>(TOKEN_STORAGE_KEYS[system]);
      if (!tokenData?.access) {
        throw new Error(`No token for ${system}`);
      }

      return {
        Authorization: `Bearer ${tokenData.access}`,
      };
    },

    async requestWithAuth<T = unknown>(system: SystemType, config: AxiosRequestConfig): Promise<T> {
      const execute = async () => {
        const headers = await this.getAuthHeaders(system);
        const response = await axios.request<T>({
          ...config,
          url: config.url?.startsWith('http') ? config.url : `${getApiBase(system)}${config.url}`,
          headers: {
            ...(config.headers || {}),
            ...headers,
          },
        });
        return response.data;
      };

      try {
        return await execute();
      } catch (error) {
        if (axios.isAxiosError(error) && error.response?.status === 401) {
          await this.refreshTokenAction(system);
          return execute();
        }
        throw error;
      }
    },

    async logoutSystem(system: SystemType): Promise<void> {
      this.auth[system].user = null;
      this.auth[system].token = null;
      this.auth[system].refreshToken = null;
      await deleteFromDB(TOKEN_STORAGE_KEYS[system]);
      await deleteFromDB(USER_STORAGE_KEYS[system]);
    },

    async logout(): Promise<void> {
      await Promise.all(SYSTEMS.map((system) => this.logoutSystem(system)));
    }
  },
  getters: {
    user: (state: UserState): User | null => state.auth.bt.user || state.auth.sy.user,
    isAuthenticated: (state: UserState): boolean =>
      SYSTEMS.some((system) => !!state.auth[system].token),
    isSuperuser: (state: UserState): boolean =>
      SYSTEMS.some((system) => !!state.auth[system].user?.is_superuser),
    isSystemAuthenticated: (state: UserState): (system: SystemType) => boolean =>
      (system: SystemType): boolean => !!state.auth[system].token,
    isSystemSuperuser: (state: UserState): (system: SystemType) => boolean =>
      (system: SystemType): boolean => !!state.auth[system].user?.is_superuser,
    canAccessOps: (state: UserState): boolean =>
      SYSTEMS.some((system) => {
        const user = state.auth[system].user;
        return !!user?.is_superuser || !!user?.is_staff || !!user?.groups.includes('System Admin');
      }),
    getUser: (state: UserState): (system: SystemType) => User | null =>
      (system: SystemType): User | null => state.auth[system].user,
    hasPermission: (state: UserState): (permission: string) => boolean =>
      (permission: string): boolean =>
        !!state.auth.bt.user?.permissions.includes(permission) ||
        !!state.auth.sy.user?.permissions.includes(permission),
  }
});
