import { fileURLToPath, URL } from 'node:url';

export default {
  test: {
    environment: 'node',
    globals: true,
    restoreMocks: true,
    include: ['src/**/*.test.ts'],
    setupFiles: ['./src/test/setup.ts'],
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
};
