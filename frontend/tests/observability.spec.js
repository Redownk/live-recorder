import { expect, test } from '@playwright/test';

const id = (number) => `${String(number).padStart(20, '0')}-a1b2c3d4`;
async function setup(page, { failLogs = false, deny = false } = {}) {
  const state = {
    entries: [
      { id: id(1), timestamp: '2026-10-28T01:00:00+00:00', level: 'INFO', logger: 'app.recording', room_id: 1, platform: 'DOUYIN', message: '房间一开始检查', traceback: '' },
      { id: id(2), timestamp: '2026-10-28T01:01:00+00:00', level: 'WARNING', logger: 'app.recording', room_id: 1, platform: 'DOUYIN', message: '网络断流，准备重连', traceback: 'Traceback\nValueError: token=[REDACTED]' },
      { id: id(3), timestamp: '2026-10-28T01:02:00+00:00', level: 'ERROR', logger: 'app.recording', room_id: 2, platform: 'BILIBILI', message: '房间二合并失败', traceback: '' },
    ], calls: [], diagnostics: [], platformTests: [], encoderTests: [], exports: [], failLogs, deny,
  };
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (text) => { window.copiedLog = text; } } });
  });
  await page.route(/\/(api|crawler)\//, async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname;
    if (path === '/crawler/status') return route.fulfill({ json: { running: true } });
    if (path === '/api/settings/disk') return route.fulfill({ json: { enabled: true, disks: [] } });
    if (path === '/api/recording-status') return route.fulfill({ json: {} });
    if (path === '/api/rooms') return route.fulfill({ json: [{ id: 1, platform: 'DOUYIN', room_id: '123', owner: '日志主播一', monitor_enabled: true }, { id: 2, platform: 'BILIBILI', room_id: '456', owner: '日志主播二', monitor_enabled: true }] });
    if (path === '/api/system/logs') {
      state.calls.push(Object.fromEntries(url.searchParams));
      if (state.deny) return route.fulfill({ status: 403, json: { detail: '运行日志与故障诊断仅允许从后端本机页面访问' } });
      if (state.failLogs) { state.failLogs = false; return route.fulfill({ status: 503, json: { detail: '日志暂不可用' } }); }
      const filter = Object.fromEntries(url.searchParams);
      let entries = state.entries.filter((entry) => (!filter.room_id || entry.room_id === Number(filter.room_id)) && (!filter.level || entry.level === filter.level) && (!filter.keyword || (entry.message + entry.traceback).includes(filter.keyword)) && (!filter.before || entry.id < filter.before) && (!filter.after || entry.id > filter.after));
      entries.sort((a, b) => b.id.localeCompare(a.id));
      const has_more = entries.length > 200;
      entries = entries.slice(0, 200);
      return route.fulfill({ json: { entries, cursor: [...state.entries].sort((a, b) => b.id.localeCompare(a.id))[0]?.id || '', next_before: entries.at(-1)?.id || null, has_more, dropped: 0, write_error: '' } });
    }
    if (path === '/api/system/issues') return route.fulfill({ json: { issues: [{ id: id(2), code: 'recording_health', room_id: 1, level: 'WARNING', message: '网络断流，准备重连', count: 3, last_seen: '2026-10-28T01:01:00+00:00', advice: '检查网络和直播源' }], scope: '最近 1000 条警告与错误，不代表当前仍未解决' } });
    if (path === '/api/system/diagnostics') {
      state.diagnostics.push(req.postDataJSON());
      return route.fulfill({ json: { checked_at: '2026-10-28T01:00:00+00:00', environment: { system: 'Windows', release: '11', python: '3.14.3' }, tasks: { checks: 1, recordings: 2, processing: 0 }, checks: [{ key: 'database', label: 'SQLite', status: 'ok', detail: '数据库连接及只读查询正常' }, { key: 'ffmpeg', label: 'FFmpeg', status: 'ok', detail: 'ffmpeg 7.1.1' }, { key: 'disk', label: '录制磁盘', status: 'warning', detail: 'E:/record：磁盘剩余空间不足' }], encoders: { encoders: [{ value: 'h264_nvenc', label: 'H.264 (NVIDIA NVENC)', available: true }], error: '' } } });
    }
    if (path.startsWith('/api/system/diagnostics/platform/')) { state.platformTests.push(path); return route.fulfill({ json: { status: 'ok', detail: '平台检查请求完成，当前开播' } }); }
    if (path === '/api/system/diagnostics/encoder') { state.encoderTests.push(req.postDataJSON()); return route.fulfill({ json: { status: 'failed', detail: '当前驱动无法初始化编码器' } }); }
    if (path === '/api/system/diagnostics/export') { state.exports.push(req.postDataJSON()); return route.fulfill({ contentType: 'application/zip', body: 'PK diagnostic fixture' }); }
    return route.fulfill({ json: [] });
  });
  return state;
}

test('room log modal isolates room filters shows stack copies and restores focus', async ({ page }, testInfo) => {
  const state = await setup(page);
  await page.goto('/rooms');
  const button = page.getByRole('button', { name: '运行日志 日志主播一', exact: true });
  await button.click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('运行日志 · 日志主播一');
  await expect(dialog).toContainText('房间一开始检查');
  await expect(dialog).not.toContainText('房间二合并失败');
  await dialog.getByText('异常堆栈', { exact: true }).click();
  await expect(dialog).toContainText('ValueError: token=[REDACTED]');
  await dialog.getByRole('button', { name: `复制日志 ${id(2)}`, exact: true }).click();
  expect(await page.evaluate(() => window.copiedLog)).toContain('ValueError: token=[REDACTED]');
  await dialog.getByRole('combobox', { name: '日志级别', exact: true }).selectOption('WARNING');
  await dialog.getByRole('searchbox', { name: '日志关键词', exact: true }).fill('网络');
  await dialog.getByRole('button', { name: '筛选日志', exact: true }).click();
  await expect(dialog.locator('.runtime-entry')).toHaveCount(1);
  expect(state.calls.at(-1)).toMatchObject({ room_id: '1', level: 'WARNING', keyword: '网络' });
  await page.screenshot({ path: testInfo.outputPath('room-runtime-logs.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await dialog.getByRole('button', { name: '关闭', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(button).toBeFocused();
});

test('room modal polling pauses resumes and stops after closing', async ({ page }) => {
  await page.clock.install();
  const state = await setup(page);
  await page.goto('/rooms');
  await page.getByRole('button', { name: '运行日志 日志主播一', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('房间一开始检查');
  const calls = state.calls.length;
  await page.getByRole('button', { name: '暂停日志刷新', exact: true }).click();
  await page.clock.runFor(6000);
  expect(state.calls.length).toBe(calls);
  state.entries.push({ ...state.entries[0], id: id(4), message: '新的恢复记录' });
  await page.getByRole('button', { name: '恢复日志刷新', exact: true }).click();
  await page.clock.runFor(2000);
  await expect(page.getByRole('dialog')).toContainText('新的恢复记录');
  await page.getByRole('dialog').getByRole('button', { name: '关闭', exact: true }).click();
  const stopped = state.calls.length;
  await page.clock.runFor(6000);
  expect(state.calls.length).toBe(stopped);
});

test('view all preserves room association and global filters load historical pages', async ({ page }, testInfo) => {
  const state = await setup(page);
  state.entries = Array.from({ length: 240 }, (_, index) => ({ ...state.entries[0], id: id(index + 1), message: `历史记录 ${index}` }));
  await page.goto('/rooms');
  await page.getByRole('button', { name: '运行日志 日志主播一', exact: true }).click();
  await page.getByRole('link', { name: '查看全部', exact: true }).click();
  await expect(page).toHaveURL(/\/runtime-logs\?room_id=1$/);
  await expect(page.getByRole('combobox', { name: '日志直播间', exact: true })).toHaveValue('1');
  await expect(page.locator('.runtime-entry')).toHaveCount(200);
  await page.getByRole('button', { name: '加载更早日志', exact: true }).click();
  await expect(page.locator('.runtime-entry')).toHaveCount(240);
  await page.getByRole('searchbox', { name: '日志关键词', exact: true }).fill('历史记录 239');
  await page.getByRole('button', { name: '筛选日志', exact: true }).click();
  await expect(page.locator('.runtime-entry')).toHaveCount(1);
  await page.screenshot({ path: testInfo.outputPath('global-runtime-logs.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('log request failure can retry and remote denial is explicit', async ({ page }) => {
  const state = await setup(page, { failLogs: true });
  await page.goto('/runtime-logs');
  await expect(page.getByRole('alert')).toContainText('日志暂不可用');
  await page.getByRole('button', { name: '刷新运行日志', exact: true }).click();
  await expect(page.locator('.runtime-entry')).toHaveCount(3);
  state.deny = true;
  await page.getByRole('button', { name: '刷新运行日志', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('仅允许从后端本机页面访问');
});

test('environment platform encoder diagnostics and export run only on explicit commands', async ({ page }, testInfo) => {
  const state = await setup(page);
  await page.goto('/diagnostics');
  await expect(page.getByText('尚未执行环境检查', { exact: true })).toBeVisible();
  expect(state.diagnostics).toHaveLength(0);
  await page.getByLabel('测试保存目录临时写入', { exact: true }).check();
  await page.getByRole('button', { name: '运行环境检查', exact: true }).click();
  await expect(page.getByText('数据库连接及只读查询正常', { exact: true })).toBeVisible();
  expect(state.diagnostics).toEqual([{ test_write: true }]);
  await page.getByRole('combobox', { name: '诊断直播间', exact: true }).selectOption('1');
  await page.getByRole('button', { name: '测试连接', exact: true }).click();
  await expect(page.getByText('平台检查请求完成，当前开播', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '实际编码测试', exact: true }).click();
  await expect(page.getByText('当前驱动无法初始化编码器', { exact: true })).toBeVisible();
  expect(state.encoderTests).toEqual([{ encoder: 'h264_nvenc' }]);
  await page.screenshot({ path: testInfo.outputPath('diagnostics.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', { name: '导出诊断包', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('Cookie、完整配置、数据库、录制视频');
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: '确认导出', exact: true }).click();
  expect((await download).suggestedFilename()).toBe('LiveRecorder-diagnostics.zip');
  expect(state.exports[0].room_id).toBe(1);
  await expect(page.getByRole('dialog')).toHaveCount(0);
});
