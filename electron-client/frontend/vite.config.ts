import { defineConfig, loadEnv } from 'vite';
import vue from '@vitejs/plugin-vue';
import Components from 'unplugin-vue-components/vite';
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers';
import { fileURLToPath, URL } from 'node:url';

export default defineConfig(({ mode }) => {
  // 加载环境变量
  const env = loadEnv(mode, process.cwd());
  const btProxyTarget = env.VITE_BT_PROXY_TARGET || 'http://127.0.0.1:8000';
  const syProxyTarget = env.VITE_SY_PROXY_TARGET || 'http://127.0.0.1:8001';

  return {
    plugins: [
      vue(),
      Components({
        dts: true,
        resolvers: [
          ElementPlusResolver({
            importStyle: 'css',
          }),
        ],
      }),
    ],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      host: '0.0.0.0',
      port: 5173,
      proxy: {
        '/bt-api': {
          target: btProxyTarget,
          changeOrigin: false,
          secure: false,
          rewrite: (path) => path.replace(/^\/bt-api/, '/api'),
        },
        '/sy-api': {
          target: syProxyTarget,
          changeOrigin: false,
          secure: false,
          rewrite: (path) => path.replace(/^\/sy-api/, '/api'),
        },
        '/bt-ws': {
          target: btProxyTarget,
          changeOrigin: false,
          secure: false,
          ws: true,
          rewrite: (path) => path.replace(/^\/bt-ws/, '/ws'),
        },
        '/sy-ws': {
          target: syProxyTarget,
          changeOrigin: false,
          secure: false,
          ws: true,
          rewrite: (path) => path.replace(/^\/sy-ws/, '/ws'),
        },
        '/bt-admin': {
          target: btProxyTarget,
          changeOrigin: false,
          secure: false,
        },
        '/sy-admin': {
          target: syProxyTarget,
          changeOrigin: false,
          secure: false,
        },
        '/bt-static': {
          target: btProxyTarget,
          changeOrigin: false,
          secure: false,
        },
        '/sy-static': {
          target: syProxyTarget,
          changeOrigin: false,
          secure: false,
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
            if (id.includes('/element-plus/') || id.includes('/@element-plus/')) {
              return;
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
