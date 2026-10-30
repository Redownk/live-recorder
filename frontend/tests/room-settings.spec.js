import { expect, test } from '@playwright/test';

const keys = ['save_path', 'filename_template', 'check_interval_seconds', 'quality', 'segment_minutes'];
async function setup(page, { failLoad = false, failSave = false, denyBrowse = false } = {}) {
  const state = { overrides: { 1: {}, 2: {} }, writes: [], globalWrites: [], failLoad, failSave,
    global: { save_path: 'E:/global', filename_template: '{owner}_{timestamp}', check_interval_seconds: 5, quality: 'best', segment_minutes: 0,
      disk_protection_enabled: true, disk_min_free_gb: 5, disk_stop_free_gb: 1, health_check_enabled: true, health_startup_timeout_seconds: 60, health_stall_timeout_seconds: 60, health_max_restarts: 3 } };
  const response = (id, values = state.overrides[id]) => {
    const overrides = Object.fromEntries(keys.map((key) => [key, values[key] ?? null]));
    const effective = { ...state.global, ...Object.fromEntries(Object.entries(overrides).filter(([, value]) => value !== null)) };
    const tokens = { owner: id === 1 ? '独立主播' : '其他主播', remark: '备注', timestamp: '20261028120000' };
    return { room_id: id, overrides, effective, global_settings: state.global, customized: Object.values(overrides).some((value) => value !== null),
      resolved_save_path: effective.save_path, filename_example: effective.filename_template.replace(/\{(\w+)\}/g, (_, key) => tokens[key] || '') + '.ts' };
  };
  await page.route(/\/(api|crawler)\//, async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname;
    if (path === '/crawler/status') return route.fulfill({ json: { running: false } });
    if (path === '/api/recording-status') return route.fulfill({ json: {} });
    if (path === '/api/settings/disk') return route.fulfill({ json: { enabled: true, disks: [] } });
    if (path === '/api/rooms') return route.fulfill({ json: [1, 2].map((id) => ({ id, platform: 'DOUYIN', room_id: `${id}23`, owner: id === 1 ? '独立主播' : '其他主播', remark: '', monitor_enabled: true, recording_settings_customized: response(id).customized })) });
    const settings = path.match(/^\/api\/rooms\/(\d+)\/recording-settings(\/preview)?$/);
    if (settings) {
      const id = Number(settings[1]);
      if (state.failLoad && req.method() === 'GET') { state.failLoad = false; return route.fulfill({ status: 503, json: { detail: '房间设置暂不可用' } }); }
      const values = req.method() === 'GET' ? state.overrides[id] : req.postDataJSON();
      if (values.filename_template?.includes('{unknown}')) return route.fulfill({ status: 422, json: { detail: '不支持的命名变量或格式' } });
      if (!settings[2] && req.method() === 'PUT') {
        state.writes.push({ id, values });
        if (state.failSave) return route.fulfill({ status: 400, json: { detail: '房间保存目录不可用，请检查路径和写入权限' } });
        state.overrides[id] = values;
      }
      return route.fulfill({ json: response(id, values) });
    }
    if (path === '/api/settings/directories') {
      if (denyBrowse) return route.fulfill({ status: 403, json: { detail: '目录浏览仅允许从后端本机访问' } });
      const current = url.searchParams.get('path') || 'E:/global';
      return route.fulfill({ json: { path: current, parent: current === 'E:/global' ? 'E:/' : 'E:/global', directories: current === 'E:/global' ? [{ name: '独立录制', path: 'E:/global/独立录制' }] : [], shortcuts: [], offset: 0, limit: 200, total: 1, has_more: false } });
    }
    if (path === '/api/settings') {
      if (req.method() === 'PUT') { state.global = req.postDataJSON(); state.globalWrites.push(state.global); }
      return route.fulfill({ json: { ...state.global, resolved_save_path: state.global.save_path, filename_example: '独立主播_20261028120000.ts' } });
    }
    if (path === '/api/settings/preview') return route.fulfill({ json: { ...state.global, ...req.postDataJSON(), resolved_save_path: state.global.save_path, filename_example: '独立主播_20261028120000.ts' } });
    return route.fulfill({ json: [] });
  });
  return state;
}

test('room settings inherit by default and independently save all recording options', async ({ page }, testInfo) => {
  const state = await setup(page);
  await page.goto('/rooms');
  await page.getByRole('button', { name: '录制设置 独立主播', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '录制设置 · 独立主播', exact: true });
  await expect(dialog.getByRole('checkbox', { name: '继承全局保存目录', exact: true })).toBeChecked();
  await expect(dialog.getByRole('textbox', { name: '保存目录', exact: true })).toBeDisabled();
  await expect(dialog.getByRole('button', { name: '保存设置', exact: true })).toBeDisabled();
  for (const label of ['保存目录', '命名规则', '清晰度', '检查周期', '分片时长']) await dialog.getByRole('checkbox', { name: `继承全局${label}`, exact: true }).uncheck();
  await dialog.getByRole('textbox', { name: '保存目录', exact: true }).fill('E:/独立存档');
  await dialog.getByRole('textbox', { name: '命名规则', exact: true }).fill('{remark}/{timestamp}');
  await dialog.getByRole('combobox', { name: '清晰度', exact: true }).selectOption('low');
  await dialog.getByRole('spinbutton', { name: '检查周期', exact: true }).fill('30');
  await dialog.getByRole('spinbutton', { name: '分片时长', exact: true }).fill('15');
  await expect(dialog).toContainText('15 分钟独立分片');
  await page.screenshot({ path: testInfo.outputPath('room-recording-settings.png'), fullPage: true });
  await dialog.getByRole('button', { name: '保存设置', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(state.writes[0]).toEqual({ id: 1, values: { save_path: 'E:/独立存档', filename_template: '{remark}/{timestamp}', quality: 'low', check_interval_seconds: 30, segment_minutes: 15 } });
  await expect(page.getByRole('button', { name: '录制设置 独立主播', exact: true })).toHaveAttribute('title', '录制设置（独立配置）');
  await expect(page.getByRole('button', { name: '录制设置 其他主播', exact: true })).toHaveAttribute('title', '录制设置（继承全局）');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('partial override follows global changes until restored to full inheritance', async ({ page }) => {
  const state = await setup(page);
  state.overrides[1] = { quality: 'low' };
  await page.goto('/rooms');
  await page.getByRole('button', { name: '录制设置 独立主播', exact: true }).click();
  let dialog = page.getByRole('dialog', { name: '录制设置 · 独立主播', exact: true });
  await expect(dialog.getByRole('combobox', { name: '清晰度', exact: true })).toHaveValue('low');
  await dialog.getByRole('button', { name: '取消', exact: true }).click();
  state.global.save_path = 'E:/更新的全局目录';
  state.global.quality = 'high';
  state.global.check_interval_seconds = 17;
  await page.getByRole('button', { name: '录制设置 独立主播', exact: true }).click();
  dialog = page.getByRole('dialog', { name: '录制设置 · 独立主播', exact: true });
  await expect(dialog.getByRole('textbox', { name: '保存目录', exact: true })).toHaveValue('E:/更新的全局目录');
  await expect(dialog.getByRole('spinbutton', { name: '检查周期', exact: true })).toHaveValue('17');
  await expect(dialog.getByRole('combobox', { name: '清晰度', exact: true })).toHaveValue('low');
  await dialog.getByRole('button', { name: '全部继承全局', exact: true }).click();
  await expect(dialog.getByRole('combobox', { name: '清晰度', exact: true })).toHaveValue('high');
  await dialog.getByRole('button', { name: '保存设置', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(Object.values(state.writes[0].values).every((value) => value === null)).toBe(true);
  await expect(page.getByRole('button', { name: '录制设置 独立主播', exact: true })).toHaveAttribute('title', '录制设置（继承全局）');
});

test('nested directory picker selects without persisting and cancellation restores focus', async ({ page }) => {
  const state = await setup(page);
  await page.goto('/rooms');
  const button = page.getByRole('button', { name: '录制设置 独立主播', exact: true });
  await button.click();
  const dialog = page.getByRole('dialog', { name: '录制设置 · 独立主播', exact: true });
  await dialog.getByRole('checkbox', { name: '继承全局保存目录', exact: true }).uncheck();
  await dialog.getByRole('button', { name: '浏览房间保存目录', exact: true }).click();
  const picker = page.getByRole('dialog', { name: '选择保存目录', exact: true });
  await picker.getByRole('button', { name: '打开 独立录制', exact: true }).click();
  await picker.getByRole('button', { name: '选择此目录', exact: true }).click();
  await expect(picker).toHaveCount(0);
  await expect(dialog.getByRole('textbox', { name: '保存目录', exact: true })).toHaveValue('E:/global/独立录制');
  expect(state.writes).toHaveLength(0);
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(button).toBeFocused();
  await button.click();
  await expect(page.getByRole('checkbox', { name: '继承全局保存目录', exact: true })).toBeChecked();
});

test('invalid preview blocks save and server save failure preserves draft for retry', async ({ page }) => {
  const state = await setup(page, { failSave: true });
  await page.goto('/rooms');
  await page.getByRole('button', { name: '录制设置 独立主播', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '录制设置 · 独立主播', exact: true });
  await dialog.getByRole('checkbox', { name: '继承全局命名规则', exact: true }).uncheck();
  await dialog.getByRole('textbox', { name: '命名规则', exact: true }).fill('{unknown}');
  await expect(dialog.getByRole('alert')).toContainText('不支持的命名变量');
  await expect(dialog.getByRole('button', { name: '保存设置', exact: true })).toBeDisabled();
  await dialog.getByRole('textbox', { name: '命名规则', exact: true }).fill('{owner}/{timestamp}');
  await dialog.getByRole('button', { name: '保存设置', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('房间保存目录不可用');
  await expect(dialog.getByRole('textbox', { name: '命名规则', exact: true })).toHaveValue('{owner}/{timestamp}');
  state.failSave = false;
  await dialog.getByRole('button', { name: '保存设置', exact: true }).click();
  await expect(dialog).toHaveCount(0);
});

test('room load and directory denial are recoverable without saving defaults', async ({ page }) => {
  const state = await setup(page, { failLoad: true, denyBrowse: true });
  await page.goto('/rooms');
  await page.getByRole('button', { name: '录制设置 独立主播', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('房间设置暂不可用');
  await page.getByRole('button', { name: '重试', exact: true }).click();
  await page.getByRole('checkbox', { name: '继承全局保存目录', exact: true }).uncheck();
  await page.getByRole('button', { name: '浏览房间保存目录', exact: true }).click();
  const picker = page.getByRole('dialog', { name: '选择保存目录', exact: true });
  await expect(picker.getByRole('alert')).toContainText('仅允许从后端本机访问');
  await picker.getByRole('button', { name: '取消', exact: true }).click();
  expect(state.writes).toHaveLength(0);
});

test('global default quality and segmentation can be configured independently', async ({ page }) => {
  const state = await setup(page);
  await page.goto('/settings');
  await page.getByRole('combobox', { name: '默认录制清晰度', exact: true }).selectOption('medium');
  await page.getByLabel('定时独立分片', { exact: true }).check();
  await page.getByRole('spinbutton', { name: '默认分片时长', exact: true }).fill('20');
  await page.getByRole('button', { name: '保存设置', exact: true }).click();
  await expect(page.getByText('录制设置已保存', { exact: true })).toBeVisible();
  expect(state.globalWrites[0]).toMatchObject({ quality: 'medium', segment_minutes: 20 });
  await page.reload();
  await expect(page.getByRole('combobox', { name: '默认录制清晰度', exact: true })).toHaveValue('medium');
  await expect(page.getByRole('spinbutton', { name: '默认分片时长', exact: true })).toHaveValue('20');
});
