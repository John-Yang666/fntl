import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';

const { db, axiosMock } = vi.hoisted(() => ({
  db: new Map<string, unknown>(),
  axiosMock: {
    get: vi.fn(),
    post: vi.fn(),
    request: vi.fn(),
    isAxiosError: (error: unknown) => Boolean((error as any)?.isAxiosError),
  },
}));

vi.mock('axios', () => ({
  default: axiosMock,
  isAxiosError: axiosMock.isAxiosError,
}));

vi.mock('@/utils/indexedDB', () => ({
  getFromDB: vi.fn(async (key: string) => db.get(key) ?? null),
  saveToDB: vi.fn(async (key: string, value: unknown) => {
    db.set(key, value);
  }),
  deleteFromDB: vi.fn(async (key: string) => {
    db.delete(key);
  }),
}));

import { TOKEN_STORAGE_KEYS, USER_STORAGE_KEYS } from '@/utils/systems';
import { useUserStore } from '../userStore';

const adminUser = {
  username: 'admin',
  email: 'admin@example.com',
  groups: ['System Admin'],
  is_staff: true,
  is_superuser: false,
  permissions: ['myapp.view_device'],
};

describe('userStore', () => {
  beforeEach(() => {
    db.clear();
    axiosMock.get.mockReset();
    axiosMock.post.mockReset();
    axiosMock.request.mockReset();
    setActivePinia(createPinia());
    window.history.pushState({}, '', 'http://fntl.local:5173/');
  });

  it('loads persisted BT/SY tokens and users from IndexedDB', async () => {
    db.set(TOKEN_STORAGE_KEYS.bt, { access: 'bt-access', refresh: 'bt-refresh' });
    db.set(USER_STORAGE_KEYS.bt, adminUser);

    const store = useUserStore();
    await store.loadAuthData();

    expect(store.auth.bt.token).toBe('bt-access');
    expect(store.user?.username).toBe('admin');
    expect(store.isAuthenticated).toBe(true);
    expect(store.canAccessOps).toBe(true);
  });

  it('keeps successfully authenticated systems and clears failed systems on login', async () => {
    axiosMock.post.mockImplementation(async (url: string) => {
      if (url.includes(':8000')) {
        return { data: { access: 'bt-access', refresh: 'bt-refresh' } };
      }
      throw new Error('SY unavailable');
    });
    axiosMock.get.mockResolvedValue({ data: adminUser });

    const store = useUserStore();
    await store.login('admin', 'admin');

    expect(store.auth.bt.token).toBe('bt-access');
    expect(store.auth.sy.token).toBeNull();
    expect(db.get(TOKEN_STORAGE_KEYS.bt)).toEqual({ access: 'bt-access', refresh: 'bt-refresh' });
    expect(db.has(TOKEN_STORAGE_KEYS.sy)).toBe(false);
  });

  it('refreshes an expired access token before retrying authenticated requests', async () => {
    db.set(TOKEN_STORAGE_KEYS.bt, { access: 'old-access', refresh: 'refresh-token' });
    const expired = { isAxiosError: true, response: { status: 401 } };
    axiosMock.request
      .mockRejectedValueOnce(expired)
      .mockResolvedValueOnce({ data: { ok: true } });
    axiosMock.post.mockResolvedValue({ data: { access: 'new-access' } });

    const store = useUserStore();
    const result = await store.requestWithAuth('bt', { url: '/devices/' });

    expect(result).toEqual({ ok: true });
    expect(axiosMock.post).toHaveBeenCalledWith('http://fntl.local:8000/api/token/refresh/', {
      refresh: 'refresh-token',
    });
    expect(axiosMock.request).toHaveBeenLastCalledWith(
      expect.objectContaining({
        url: 'http://fntl.local:8000/api/devices/',
        headers: { Authorization: 'Bearer new-access' },
      }),
    );
  });
});
