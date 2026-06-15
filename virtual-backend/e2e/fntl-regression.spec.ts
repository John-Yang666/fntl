import { expect, test, type Page } from '@playwright/test';
import { createBackendServer } from '../electron/simulator/backendServer.js';
import { createSimulatorStore } from '../electron/simulator/store.js';

const store = createSimulatorStore();
const startedServers: Array<{ stop: () => Promise<void> }> = [];

test.beforeAll(async () => {
  const bt = createBackendServer({ system: 'bt', store });
  const sy = createBackendServer({ system: 'sy', store });
  await bt.start(18080);
  await sy.start(18081);
  startedServers.push(bt, sy);
});

test.afterAll(async () => {
  await Promise.all(startedServers.splice(0).map((server) => server.stop()));
});

const login = async (page: Page) => {
  await page.goto('/login');
  await page.getByTestId('login-username').fill('admin');
  await page.getByTestId('login-password').fill('admin');
  await page.getByTestId('login-submit').click();
  await expect(page.getByTestId('main-view')).toBeVisible();
};

const clickHeaderTab = async (page: Page, name: string | RegExp) => {
  await page.getByRole('tab', { name }).click();
};

test('operator can log in and exercise the main FNTL navigation flow', async ({ page }) => {
  await login(page);

  await expect(page.getByTestId('topology-canvas')).toBeVisible();
  await page.getByTestId('topology-zoom-in').click();
  await page.getByTestId('topology-fit').click();

  store.updateDeviceState({ system: 'bt', deviceId: 2, fault: 'direction1_fault' });

  await clickHeaderTab(page, /当前告警/);
  await expect(page.getByTestId('alerts-view')).toContainText('一方向线路故障');
  await page.getByRole('button', { name: '确认' }).first().click();
  await expect(page.getByTestId('alerts-view')).toContainText('已确认');

  await clickHeaderTab(page, '记录查询');
  await expect(page.getByTestId('records-view')).toBeVisible();
  await page.getByRole('tab', { name: '继电器动作' }).click();
  await expect(page.getByTestId('records-view')).toContainText('继电器动作');

  await clickHeaderTab(page, '运维管理');
  await expect(page.getByTestId('ops-page')).toBeVisible();
  await page.getByTestId('ops-device-id-filter').locator('input').fill('2');
  await page.getByTestId('ops-device-query').click();
  await expect(page.getByTestId('ops-page')).toContainText('BT-02');
  await page.getByRole('tab', { name: '车间管理' }).click();
  await expect(page.getByTestId('ops-page')).toContainText('车间管理');
  await page.getByRole('tab', { name: '线路管理' }).click();
  await expect(page.getByTestId('ops-page')).toContainText('线路管理');
});

test('superuser can open help and runtime configuration pages against both systems', async ({ page }) => {
  await login(page);

  await clickHeaderTab(page, '帮助');
  await expect(page.getByTestId('help-view')).toContainText('常见问题解答');
  await expect(page.getByTestId('file-manage')).toContainText('BT');
  await page.getByRole('tab', { name: 'SY 文件' }).click();
  await expect(page.getByTestId('file-manage')).toContainText('SY');

  await clickHeaderTab(page, '系统设置');
  await expect(page.getByTestId('runtime-config-page')).toBeVisible();
  await page.getByRole('tab', { name: 'SY 参数' }).click();
  await expect(page.getByTestId('runtime-config-page')).toContainText('SY 参数');
  await page.getByTestId('runtime-reload-sy').click();
  await page.getByTestId('runtime-cleanup-group-sy').click();
  await page.getByTestId('runtime-cleanup-export-sy').click();
  await expect(page.getByRole('dialog', { name: 'SY 导出测试结果' })).toBeVisible();
  await page.getByRole('button', { name: '确定' }).click();
  await expect(page.getByText('SY 导出测试完成')).toBeVisible();
});
