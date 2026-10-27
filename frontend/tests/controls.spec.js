import { expect, test } from '@playwright/test';

async function setup(page) {
  const state = {
    rooms: [1, 2].map((id) => ({ id, platform: 'DOUYIN', room_id: `${id}23`, owner: `主播${id}`, monitor_enabled: true })),
    statuses: {}, stops: [], starts: [], writes: [], startMode: 'started', release: null, diskCalls: 0,
    settings: { save_path: './record', filename_template: '{platform}_{owner}_{timestamp}', check_interval_seconds: 5,
      disk_protection_enabled: true, disk_min_free_gb: 5, disk_stop_free_gb: 1 },
    disk: { path: 'E:/record', total_bytes: 100 * 1024 ** 3, used_bytes: 80 * 1024 ** 3, free_bytes: 20 * 1024 ** 3, state: 'normal', message: '磁盘空间正常' },
  };
  const settingsResponse = () => ({ ...state.settings, resolved_save_path: 'E:/record', filename_example: 'DOUYIN_主播_20261027120000.ts' });
  await page.route(/\/(api|crawler)\//, async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    if (path === '/crawler/status') return route.fulfill({ json: { running: false } });
    if (path === '/api/rooms') return route.fulfill({ json: state.rooms });
    if (path === '/api/recording-status') return route.fulfill({ json: state.statuses });
    if (path === '/api/settings/disk') {
      state.diskCalls += 1;
      return route.fulfill({ json: { enabled: state.settings.disk_protection_enabled, disks: [state.disk] } });
    }
    if (path === '/api/settings/preview') return route.fulfill({ json: settingsResponse() });
    if (path === '/api/settings') {
      if (req.method() === 'PUT') {
        state.settings = req.postDataJSON();
        state.writes.push(state.settings);
      }
      return route.fulfill({ json: settingsResponse() });
    }
    const action = path.match(/^\/api\/rooms\/(\d+)\/recording\/(start|stop)$/);
    if (action) {
      const id = Number(action[1]);
      if (action[2] === 'start') {
        state.starts.push(id);
        if (state.startMode === 'checking') {
          state.statuses[id] = { state: 'checking', elapsed_seconds: 0 };
          await new Promise((resolve) => { state.release = resolve; });
          return route.fulfill({ json: { status: 'stopped' } });
        }
        if (state.startMode === 'error') return route.fulfill({ status: 507, json: { detail: '磁盘剩余空间不足，已暂停新录制' } });
        if (state.startMode === 'started') state.statuses[id] = { state: 'recording', elapsed_seconds: 10, log_id: id };
        return route.fulfill({ json: { status: state.startMode } });
      }
      const payload = req.postDataJSON();
      state.stops.push({ id, ...payload });
      if (payload.disable_monitor) state.rooms.find((room) => room.id === id).monitor_enabled = false;
      delete state.statuses[id];
      state.release?.();
      return route.fulfill({ json: { status: 'stopped', monitor_enabled: state.rooms.find((room) => room.id === id).monitor_enabled } });
    }
    return route.fulfill({ json: [] });
  });
  return state;
}

test('individual recording start and both stop modes leave other room unchanged', async ({ page }, testInfo) => {
  const state = await setup(page);
  state.statuses[2] = { state: 'recording', elapsed_seconds: 30, log_id: 2 };
  await page.goto('/rooms');
  await page.getByRole('button', { name: '录制 主播1', exact: true }).click();
  await expect(page.getByRole('button', { name: '录制 主播1', exact: true })).toBeDisabled();
  await expect(page.getByText('录制中', { exact: true })).toHaveCount(2);
  await page.getByRole('button', { name: '停止录制 主播1', exact: true }).click();
  await expect(page.getByRole('radio', { name: '停止并暂停监控', exact: true })).toBeChecked();
  await page.getByRole('radio', { name: '停止本次，保留监控', exact: true }).check();
  await page.screenshot({ path: testInfo.outputPath('stop-dialog.png'), fullPage: true });
  await page.getByRole('button', { name: '确认停止', exact: true }).click();
  await expect(page.getByRole('switch', { name: '监控 主播1', exact: true })).toBeChecked();
  await expect(page.getByText('录制中', { exact: true })).toHaveCount(1);
  await page.getByRole('button', { name: '停止录制 主播1', exact: true }).click();
  await page.getByRole('button', { name: '确认停止', exact: true }).click();
  await expect(page.getByRole('switch', { name: '监控 主播1', exact: true })).not.toBeChecked();
  await expect(page.getByRole('switch', { name: '监控 主播2', exact: true })).toBeChecked();
  expect(state.stops).toEqual([{ id: 1, disable_monitor: false }, { id: 1, disable_monitor: true }]);
  expect(state.starts).toEqual([1]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('pending live check can be stopped before start request completes', async ({ page }) => {
  const state = await setup(page);
  state.startMode = 'checking';
  await page.goto('/rooms');
  await page.getByRole('button', { name: '录制 主播1', exact: true }).click();
  await expect.poll(() => Boolean(state.release)).toBe(true);
  await expect(page.getByRole('button', { name: '停止录制 主播1', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '停止录制 主播1', exact: true }).click();
  await page.getByRole('button', { name: '确认停止', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByRole('switch', { name: '监控 主播1', exact: true })).not.toBeChecked();
  expect(state.statuses[1]).toBeUndefined();
});

test('offline and disk start errors keep controls usable and disk warnings refresh', async ({ page }, testInfo) => {
  await page.clock.install();
  const state = await setup(page);
  state.startMode = 'offline';
  state.disk = { ...state.disk, state: 'warning', free_bytes: 4 * 1024 ** 3, message: '磁盘剩余空间不足，已暂停新录制' };
  await page.goto('/rooms');
  await expect(page.locator('.disk-status.warning')).toContainText('已暂停新录制');
  await page.getByRole('button', { name: '录制 主播1', exact: true }).click();
  await expect(page.getByText('当前未开播', { exact: true })).toBeVisible();
  state.startMode = 'error';
  await page.getByRole('button', { name: '录制 主播1', exact: true }).click();
  await expect(page.locator('.toast.error')).toContainText('磁盘剩余空间不足');
  state.disk = { ...state.disk, state: 'critical', free_bytes: 1024 ** 3, message: '磁盘空间严重不足，将停止录制' };
  await page.clock.runFor(5000);
  await expect(page.locator('.disk-status.critical')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('disk-warning.png'), fullPage: true });
  state.disk = { ...state.disk, state: 'normal' };
  await page.clock.runFor(5000);
  await expect(page.locator('.disk-status')).toHaveCount(0);
  await page.getByRole('link', { name: '录制日志', exact: true }).click();
  const calls = state.diskCalls;
  await page.clock.runFor(10000);
  expect(state.diskCalls).toBe(calls);
});

test('disk thresholds save reload and reset with responsive capacity display', async ({ page }, testInfo) => {
  const state = await setup(page);
  await page.goto('/settings');
  await expect(page.locator('.disk-status')).toContainText('E:/record');
  await expect(page.getByLabel('启用磁盘空间保护', { exact: true })).toBeChecked();
  await page.getByRole('spinbutton', { name: '暂停新录制阈值', exact: true }).fill('10');
  await page.getByRole('spinbutton', { name: '停止录制阈值', exact: true }).fill('2');
  await page.getByRole('button', { name: '保存设置', exact: true }).click();
  await expect(page.getByText('录制设置已保存', { exact: true })).toBeVisible();
  expect(state.writes[0]).toMatchObject({ disk_protection_enabled: true, disk_min_free_gb: 10, disk_stop_free_gb: 2 });
  await page.reload();
  await expect(page.getByRole('spinbutton', { name: '停止录制阈值', exact: true })).toHaveValue('2');
  await page.getByRole('spinbutton', { name: '停止录制阈值', exact: true }).fill('10');
  expect(await page.getByRole('spinbutton', { name: '停止录制阈值', exact: true }).evaluate((input) => input.validity.rangeOverflow)).toBe(true);
  await page.getByRole('button', { name: '还原修改', exact: true }).click();
  await page.getByLabel('启用磁盘空间保护', { exact: true }).uncheck();
  await expect(page.getByRole('spinbutton', { name: '暂停新录制阈值', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '保存设置', exact: true }).click();
  await expect(page.getByRole('button', { name: '保存设置', exact: true })).toBeDisabled();
  expect(state.writes[1].disk_protection_enabled).toBe(false);
  await page.screenshot({ path: testInfo.outputPath('disk-settings.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
