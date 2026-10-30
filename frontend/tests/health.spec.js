import { expect, test } from '@playwright/test';

async function healthApi(page) {
  const state = {
    statuses: { 1: { state: 'recording', elapsed_seconds: 120, log_id: 10,
      health: { state: 'starting', output_bytes: 0, restart_count: 0, last_error: null } } },
    writes: [],
    settings: { save_path: './record', filename_template: '{owner}_{timestamp}', check_interval_seconds: 5,
      disk_protection_enabled: true, disk_min_free_gb: 5, disk_stop_free_gb: 1,
      health_check_enabled: true, health_startup_timeout_seconds: 60, health_stall_timeout_seconds: 60, health_max_restarts: 3 },
  };
  const response = () => ({ ...state.settings, resolved_save_path: 'E:/record', filename_example: '主播_20261027150000.ts' });
  await page.route(/\/(api|crawler)\//, async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    if (path === '/crawler/status') return route.fulfill({ json: { running: true } });
    if (path === '/api/rooms') return route.fulfill({ json: [{ id: 1, platform: 'DOUYIN', room_id: '123', owner: '健康测试主播', monitor_enabled: true }] });
    if (path === '/api/recording-status') return route.fulfill({ json: state.statuses });
    if (path === '/api/settings/disk') return route.fulfill({ json: { enabled: true, disks: [] } });
    if (path === '/api/settings') {
      if (req.method() === 'PUT') {
        state.settings = req.postDataJSON();
        state.writes.push(state.settings);
      }
      return route.fulfill({ json: response() });
    }
    if (path === '/api/settings/preview') return route.fulfill({ json: response() });
    if (path === '/api/logs') return route.fulfill({ json: [{ id: 10, platform: 'DOUYIN', owner: '健康测试主播', title: '测试',
      start_live: '2026-10-27T15:00:00', interrupted: true, live_time: 120, health_restart_count: 3,
      health_last_error: '录制卡住：FFmpeg 媒体时间长时间未推进' }] });
    return route.fulfill({ json: [] });
  });
  return state;
}

test('recording health progresses through startup healthy waiting and recovery without resetting duration', async ({ page }, testInfo) => {
  await page.clock.install();
  const state = await healthApi(page);
  await page.goto('/rooms');
  await expect(page.getByRole('columnheader', { name: '录制健康', exact: true })).toBeVisible();
  await expect(page.locator('.recording-health-cell')).toContainText('启动中');
  state.statuses[1].health = { state: 'healthy', output_bytes: 1048576, restart_count: 0, last_error: null };
  await page.clock.runFor(3000);
  await expect(page.locator('.recording-health-cell')).toContainText('正常');
  await expect(page.locator('.recording-health-cell')).toContainText('1.0 MB');
  state.statuses[1].health.state = 'waiting';
  await page.clock.runFor(3000);
  await expect(page.locator('.recording-health-cell')).toContainText('等待数据');
  state.statuses[1] = { ...state.statuses[1], state: 'reconnecting', elapsed_seconds: 130,
    health: { state: 'recovering', output_bytes: 1048576, restart_count: 1, last_error: '录制卡住：文件大小长时间未增长' } };
  await page.clock.runFor(3000);
  await expect(page.locator('.recording-health-cell')).toContainText('自动恢复中');
  await expect(page.locator('.recording-health-cell')).toHaveAttribute('title', '录制卡住：文件大小长时间未增长');
  await expect(page.locator('.recording-duration')).toHaveText(/0:02:1\d/);
  await page.locator('.recording-health-cell').scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath('recording-health.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  state.statuses[1] = { state: 'health_failed', monitor_enabled: false, message: '自动恢复次数已用尽', elapsed_seconds: 0 };
  await page.clock.runFor(3000);
  await expect(page.getByRole('switch', { name: '监控 健康测试主播', exact: true })).not.toBeChecked();
  await expect(page.locator('.recording-health-cell')).toContainText('已暂停监控');
  await expect(page.getByRole('button', { name: '录制 健康测试主播', exact: true })).toBeEnabled();
  await expect(page.locator('.recording-duration')).toHaveText('-');
});

test('health settings persist reset validate and support disabling recovery', async ({ page }, testInfo) => {
  const state = await healthApi(page);
  await page.goto('/settings');
  await expect(page.getByLabel('启用录制健康检测', { exact: true })).toBeChecked();
  await page.getByRole('spinbutton', { name: '启动宽限时间', exact: true }).fill('90');
  await page.getByRole('spinbutton', { name: '卡住超时时间', exact: true }).fill('120');
  await page.getByRole('spinbutton', { name: '单场自动恢复次数', exact: true }).fill('0');
  await page.getByRole('button', { name: '保存设置', exact: true }).click();
  await expect(page.getByText('录制设置已保存', { exact: true })).toBeVisible();
  expect(state.writes[0]).toMatchObject({ health_check_enabled: true, health_startup_timeout_seconds: 90, health_stall_timeout_seconds: 120, health_max_restarts: 0 });
  await page.reload();
  await expect(page.getByRole('spinbutton', { name: '卡住超时时间', exact: true })).toHaveValue('120');
  await page.getByRole('spinbutton', { name: '卡住超时时间', exact: true }).fill('14');
  expect(await page.getByRole('spinbutton', { name: '卡住超时时间', exact: true }).evaluate((element) => element.validity.rangeUnderflow)).toBe(true);
  await page.getByRole('button', { name: '还原修改', exact: true }).click();
  await expect(page.getByRole('spinbutton', { name: '卡住超时时间', exact: true })).toHaveValue('120');
  await page.getByLabel('启用录制健康检测', { exact: true }).uncheck();
  await expect(page.getByRole('spinbutton', { name: '单场自动恢复次数', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '保存设置', exact: true }).click();
  await expect(page.getByRole('button', { name: '保存设置', exact: true })).toBeDisabled();
  expect(state.writes[1].health_check_enabled).toBe(false);
  await page.screenshot({ path: testInfo.outputPath('health-settings.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('persisted health failure reason remains visible in recording history', async ({ page }, testInfo) => {
  await healthApi(page);
  await page.goto('/logs');
  await expect(page.getByRole('columnheader', { name: '健康检测', exact: true })).toBeVisible();
  await expect(page.locator('.health-log-cell')).toContainText('自动恢复 3 次');
  await expect(page.locator('.health-log-cell')).toContainText('录制卡住：FFmpeg 媒体时间长时间未推进');
  await page.reload();
  await expect(page.locator('.health-log-cell')).toContainText('自动恢复 3 次');
  await page.locator('.health-log-cell').scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath('health-log.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
