import { test, expect } from '@playwright/test';

async function recordingApi(page) {
  const control = { statuses: {}, fail: false, calls: 0 };
  await page.route(/\/(api|crawler)\//, async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/crawler/status') return route.fulfill({ json: { running: true } });
    if (path === '/api/rooms') return route.fulfill({ json: [{
      id: 1, platform: 'DOUYIN', room_id: '123', owner: '录制主播', remark: '录制备注', title: '测试标题', monitor_enabled: true,
    }] });
    if (path === '/api/recording-status') {
      control.calls += 1;
      return route.fulfill(control.fail ? { status: 503, json: { detail: '状态服务暂不可用' } } : { json: control.statuses });
    }
    if (path === '/api/rooms/1/live-status') return route.fulfill({ json: { is_live: true, title: '当前直播标题' } });
    return route.fulfill({ json: [] });
  });
  return control;
}

test('recording state and duration update automatically through reconnect and end', async ({ page }, testInfo) => {
  await page.clock.install();
  const control = await recordingApi(page);
  await page.goto('/rooms');
  await expect(page.getByRole('columnheader', { name: '录制状态', exact: true })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: '录制时长', exact: true })).toBeVisible();
  await expect(page.getByText('未录制', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '检查 录制主播', exact: true }).click();
  await expect(page.getByText('正在直播：当前直播标题', { exact: true })).toBeVisible();
  await expect(page.getByText('录制中', { exact: true })).toHaveCount(0);

  control.statuses = { 1: { state: 'recording', elapsed_seconds: 125, started_at: '2000-01-01T00:00:00Z', log_id: 10 } };
  await page.clock.runFor(3000);
  await expect(page.getByText('录制中', { exact: true })).toBeVisible();
  await expect(page.locator('.recording-duration')).toHaveText('0:02:05');
  await page.clock.runFor(1000);
  await expect(page.locator('.recording-duration')).toHaveText('0:02:06');
  await page.locator('.recording-state-cell').scrollIntoViewIfNeeded();
  await page.locator('.recording-duration').scrollIntoViewIfNeeded();
  expect(await page.locator('.recording-duration').evaluate((element) => {
    const bounds = element.getBoundingClientRect();
    return bounds.left >= 0 && bounds.right <= window.innerWidth;
  })).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('recording.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

  await page.getByRole('button', { name: '编辑备注 录制主播', exact: true }).click();
  const input = page.getByRole('textbox', { name: '备注 录制主播', exact: true });
  await input.fill('未保存的备注');
  control.statuses[1] = { ...control.statuses[1], state: 'reconnecting', elapsed_seconds: 130 };
  await page.clock.runFor(3000);
  await expect(page.getByText('重连中', { exact: true })).toBeVisible();
  await expect(input).toHaveValue('未保存的备注');
  await expect(page.locator('.recording-duration')).toHaveText(/0:02:1\d/);
  await page.getByRole('button', { name: '取消编辑备注', exact: true }).click();
  control.statuses[1] = { ...control.statuses[1], state: 'recording', elapsed_seconds: 135 };
  await page.clock.runFor(3000);
  await expect(page.getByText('录制中', { exact: true })).toBeVisible();
  await expect(page.locator('.recording-duration')).toHaveText(/0:02:1\d/);

  control.statuses = {};
  await page.clock.runFor(3000);
  await expect(page.getByText('未录制', { exact: true })).toBeVisible();
  await expect(page.locator('.recording-duration')).toHaveText('-');
});

test('status reload restores duration and failures do not show stale recording', async ({ page }) => {
  await page.clock.install();
  const control = await recordingApi(page);
  control.statuses = { 1: { state: 'recording', elapsed_seconds: 7200, log_id: 10, started_at: '2000-01-01T00:00:00Z' } };
  await page.goto('/rooms');
  await expect(page.locator('.recording-duration')).toHaveText('2:00:00');
  await page.reload();
  await expect(page.getByText('录制中', { exact: true })).toBeVisible();
  await expect(page.locator('.recording-duration')).toHaveText('2:00:00');
  control.fail = true;
  await page.getByRole('button', { name: '刷新直播间', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveText('录制状态获取失败：状态服务暂不可用');
  await expect(page.getByText('状态不可用', { exact: true })).toBeVisible();
  await expect(page.getByText('录制中', { exact: true })).toHaveCount(0);
  await expect(page.locator('.recording-duration')).toHaveText('-');
  control.fail = false;
  await page.getByRole('button', { name: '刷新直播间', exact: true }).click();
  await expect(page.getByText('录制中', { exact: true })).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
});

test('leaving rooms stops recording status polling', async ({ page }) => {
  await page.clock.install();
  const control = await recordingApi(page);
  await page.goto('/rooms');
  await expect(page.getByText('未录制', { exact: true })).toBeVisible();
  await page.getByRole('link', { name: '录制日志', exact: true }).click();
  await expect(page).toHaveURL(/\/logs$/);
  const calls = control.calls;
  await page.clock.runFor(6000);
  expect(control.calls).toBe(calls);
});
