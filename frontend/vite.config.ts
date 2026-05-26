import { defineConfig, loadEnv } from 'vite';
import vue from '@vitejs/plugin-vue';
import { fileURLToPath, URL } from 'node:url';

export default defineConfig(({ mode }) => {
  // 加载环境变量
  const env = loadEnv(mode, process.cwd());
  const backendPort = env.VITE_BACKEND_PORT || '8000';

  return {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      host: '0.0.0.0',
      port: 5173,
      proxy: {
        '/api': {
          target: `http://localhost:${backendPort}`, //是给 /api/ 的 HTTP 请求用的
          changeOrigin: true,
          secure: false,
        },
        '/ws': {
          target: `ws://localhost:${backendPort}`, //是给 WebSocket 请求用的
          ws: true,
        },
      },
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (!id.includes('node_modules')) {
              return;
            }
            if (id.includes('/vue/') || id.includes('/vue-router/') || id.includes('/pinia/')) {
              return 'vendor-vue';
            }
            if (id.includes('/@element-plus/icons-vue/')) {
              return 'vendor-element-icons';
            }
            if (id.includes('/element-plus/') || id.includes('/@element-plus/')) {
              return 'vendor-element-plus';
            }
            if (id.includes('/chart.js/') || id.includes('/vue-chartjs/') || id.includes('/chartjs-')) {
              return 'vendor-charts';
            }
            if (id.includes('/axios/') || id.includes('/dayjs/') || id.includes('/date-fns/')) {
              return 'vendor-utils';
            }
            return 'vendor';
          },
        },
      },
    },
  };
});
