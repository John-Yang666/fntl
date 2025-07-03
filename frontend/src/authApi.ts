import instance from './axios';
import { useUserStore } from '@/stores/userStore';
import { getFromDB, saveToDB } from '@/utils/indexedDB';

let isRefreshing = false;
let failedQueue: any[] = [];

/**
 * 当刷新 token 成功或失败时，通知队列中的请求进行重试或失败
 */
const processQueue = (error: any, token: string | null = null) => {
  failedQueue.forEach(prom => {
    if (error) {
      prom.reject(error);
    } else {
      prom.resolve(token);
    }
  });
  failedQueue = [];
};

// 在每次请求前，从 IndexedDB 读取最新 token 并添加到 headers
instance.interceptors.request.use(
  async (config) => {
    try {
      const tokenData = await getFromDB<{ access: string }>('token');
      if (tokenData?.access) {
        config.headers['Authorization'] = `Bearer ${tokenData.access}`;
      }
    } catch (error) {
      console.error('Failed to get token from IndexedDB:', error);
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// 响应拦截：若 status=401 且未重试过，则尝试 refresh token
instance.interceptors.response.use(
  response => response,
  async error => {
    const userStore = useUserStore();
    const originalRequest = error.config;

    // 如果是 401 且尚未重试过
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;

      // 若已在刷新 token, 则把当前请求放到队列中，等待刷新成功后再发起
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        })
          .then(token => {
            // token 刷新成功后，再为本次请求添加新的 token
            originalRequest.headers['Authorization'] = 'Bearer ' + token;
            return instance(originalRequest);
          })
          .catch(err => Promise.reject(err));
      }

      // 标记正在刷新 token
      isRefreshing = true;
      return new Promise(async (resolve, reject) => {
        try {
          // 从 IndexedDB 拿到 refresh
          const tokenData = await getFromDB<{ access: string; refresh: string }>('token');
          if (!tokenData?.refresh) {
            throw new Error('No refresh token available');
          }

          // 发起刷新请求
          const response = await instance.post('/token/refresh/', { refresh: tokenData.refresh });
          const newToken = response.data.access;

          // 更新 IndexedDB & Pinia
          await saveToDB('token', { access: newToken, refresh: tokenData.refresh });
          userStore.updateToken(newToken);

          // 通知队列：刷新成功
          processQueue(null, newToken);

          // 再次发送原请求
          originalRequest.headers['Authorization'] = 'Bearer ' + newToken;
          resolve(instance(originalRequest));
        } catch (err) {
          // 通知队列：刷新失败
          processQueue(err, null);
          // 登出清理
          await userStore.logout();
          reject(err);
        } finally {
          isRefreshing = false;
        }
      });
    }
    return Promise.reject(error);
  }
);

export default instance;
