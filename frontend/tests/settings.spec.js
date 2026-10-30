import { expect, test } from '@playwright/test';

async function settingsApi(page, { failLoad = false, failSave = false, failBrowseOnce = false } = {}) {
  let settings = { save_path: './record', filename_template: '{platform}_{owner}_{timestamp}', check_interval_seconds: 5,
    quality: 'best', segment_minutes: 0,
    disk_protection_enabled: true, disk_min_free_gb: 5, disk_stop_free_gb: 1,
    health_check_enabled: true, health_startup_timeout_seconds: 60, health_stall_timeout_seconds: 60, health_max_restarts: 3 };
  const writes = [];
  function response(options) {
    const values = { platform: 'DOUYIN', owner: '示例主播', remark: '示例备注', room_id: '123456', title: '直播标题', timestamp: '20260101120000', date: '20260101', time: '120000', record_id: 'a1b2c3d4'.repeat(4) };
    return { ...options, resolved_save_path: `E:/live-recorder/${options.save_path}`, filename_example: options.filename_template.replace(/\{(\w+)\}/g, (_, key) => values[key] || '') + '.ts' };
  }
  await page.route(/\/(api|crawler)\//, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === '/crawler/status') return route.fulfill({ json: { running: false } });
    if (path === '/api/settings/directories') {
      if (failBrowseOnce) {
        failBrowseOnce = false;
        return route.fulfill({ status: 403, json: { detail: '没有权限访问此目录' } });
      }
      const url = new URL(request.url());
      const current = url.searchParams.get('path')?.replaceAll('\\', '/') || null;
      const offset = Number(url.searchParams.get('offset') || 0);
      const shortcuts = [{ name: '项目目录', path: 'E:/live-recorder' }, { name: '用户目录', path: 'C:/Users/test' }];
      const directory = (name, base) => ({ name, path: `${base}/${name}` });
      let resolved = current === './record' ? 'E:/live-recorder/record' : current;
      let parent = null;
      let entries;
      if (!current) entries = [{ name: 'C:/', path: 'C:/' }, { name: 'E:/', path: 'E:/' }];
      else if (current === 'E:/') entries = [directory('直播存档', 'E:')];
      else if (current === 'E:/直播存档') { parent = 'E:/'; entries = []; }
      else if (current === 'E:/live-recorder') { parent = 'E:/'; entries = [directory('record', resolved)]; }
      else if (current === 'E:/live-recorder/record' || current === './record') {
        parent = 'E:/live-recorder';
        entries = Array.from({ length: 201 }, (_, index) => directory(index === 0 ? '中文存档' : `目录${String(index).padStart(3, '0')}`, resolved));
      } else if (current === 'E:/live-recorder/record/中文存档') { parent = 'E:/live-recorder/record'; entries = []; }
      else return route.fulfill({ status: 404, json: { detail: '目录不存在或不是文件夹' } });
      return route.fulfill({ json: { path: resolved, parent, directories: entries.slice(offset, offset + 200), shortcuts, offset, limit: 200, total: entries.length, has_more: offset + 200 < entries.length } });
    }
    if (path === '/api/settings/preview') {
      const draft = request.postDataJSON();
      if (draft.filename_template.includes('{unknown}')) return route.fulfill({ status: 422, json: { detail: [{ msg: '不支持的命名变量或格式' }] } });
      return route.fulfill({ json: response({ ...settings, ...draft }) });
    }
    if (path === '/api/settings' && request.method() === 'PUT') {
      writes.push(request.postDataJSON());
      if (failSave) return route.fulfill({ status: 400, json: { detail: '保存目录不可用，请检查路径和写入权限' } });
      settings = request.postDataJSON();
      return route.fulfill({ json: response(settings) });
    }
    if (path === '/api/settings') return route.fulfill(failLoad ? { status: 503, json: { detail: '服务暂不可用' } } : { json: response(settings) });
    return route.fulfill({ json: [] });
  });
  return writes;
}

test('settings can be edited, saved and reloaded', async ({ page }, testInfo) => {
  const writes = await settingsApi(page);
  await page.goto('/rooms');
  await page.getByRole('link', { name: '设置', exact: true }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.getByLabel('保存路径', { exact: true })).toHaveValue('./record');
  await page.getByLabel('保存路径', { exact: true }).fill('./record/custom');
  await page.getByLabel('命名规则', { exact: true }).selectOption('custom');
  await page.getByLabel('文件名模板', { exact: true }).fill('{owner}_{room_id}_{timestamp}');
  await page.getByLabel('检查周期', { exact: true }).fill('15');
  await expect(page.getByText('示例主播_123456_20260101120000.ts', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '保存设置', exact: true }).click();
  await expect(page.getByText('录制设置已保存', { exact: true })).toBeVisible();
  expect(writes).toEqual([{ save_path: './record/custom', filename_template: '{owner}_{room_id}_{timestamp}', check_interval_seconds: 15,
    quality: 'best', segment_minutes: 0,
    disk_protection_enabled: true, disk_min_free_gb: 5, disk_stop_free_gb: 1,
    health_check_enabled: true, health_startup_timeout_seconds: 60, health_stall_timeout_seconds: 60, health_max_restarts: 3 }]);
  await page.reload();
  await expect(page.getByLabel('检查周期', { exact: true })).toHaveValue('15');
  await expect(page.getByLabel('文件名模板', { exact: true })).toHaveValue('{owner}_{room_id}_{timestamp}');
  await page.getByLabel('检查周期', { exact: true }).fill('30');
  await page.getByRole('button', { name: '还原修改', exact: true }).click();
  await expect(page.getByLabel('检查周期', { exact: true })).toHaveValue('15');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('settings.png'), fullPage: true });
});

test('invalid template and save error preserve editable inputs', async ({ page }) => {
  const writes = await settingsApi(page, { failSave: true });
  await page.goto('/settings');
  await page.getByLabel('命名规则', { exact: true }).selectOption('custom');
  await page.getByLabel('文件名模板', { exact: true }).fill('{unknown}');
  await expect(page.getByRole('alert')).toHaveText('不支持的命名变量或格式');
  await expect(page.getByRole('button', { name: '保存设置', exact: true })).toBeDisabled();
  await page.getByLabel('文件名模板', { exact: true }).fill('{owner}_{timestamp}');
  await expect(page.getByRole('button', { name: '保存设置', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '保存设置', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveText('保存目录不可用，请检查路径和写入权限');
  await expect(page.getByLabel('文件名模板', { exact: true })).toHaveValue('{owner}_{timestamp}');
  await expect(page.getByRole('button', { name: '保存设置', exact: true })).toBeEnabled();
  expect(writes).toHaveLength(1);
});

test('owner directory preset and nested custom template can be previewed and saved', async ({ page }) => {
  const writes = await settingsApi(page);
  await page.goto('/settings');
  await page.getByLabel('命名规则', { exact: true }).selectOption('{owner}/{timestamp}');
  await expect(page.getByText('示例主播/20260101120000.ts', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '保存设置', exact: true }).click();
  await expect(page.getByText('录制设置已保存', { exact: true })).toBeVisible();
  expect(writes[0].filename_template).toBe('{owner}/{timestamp}');
  await page.reload();
  await expect(page.getByLabel('命名规则', { exact: true })).toHaveValue('{owner}/{timestamp}');
  await page.getByLabel('命名规则', { exact: true }).selectOption('custom');
  await page.getByLabel('文件名模板', { exact: true }).fill('{platform}/{owner}/{date}/{timestamp}');
  await expect(page.getByText('DOUYIN/示例主播/20260101/20260101120000.ts', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '保存设置', exact: true }).click();
  await expect(page.getByRole('button', { name: '保存设置', exact: true })).toBeDisabled();
  expect(writes[1].filename_template).toBe('{platform}/{owner}/{date}/{timestamp}');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('settings load failure has retry without saving default values', async ({ page }) => {
  const writes = await settingsApi(page, { failLoad: true });
  await page.goto('/settings');
  await expect(page.getByRole('alert')).toContainText('服务暂不可用');
  await expect(page.getByRole('button', { name: '重试加载设置' })).toBeVisible();
  await expect(page.getByRole('button', { name: '保存设置', exact: true })).toHaveCount(0);
  expect(writes).toEqual([]);
});

test('remark directory preset and custom remark filename can be saved', async ({ page }) => {
  const writes = await settingsApi(page);
  await page.goto('/settings');
  await page.getByLabel('命名规则', { exact: true }).selectOption('{remark}/{owner}_{timestamp}');
  await expect(page.getByText('示例备注/示例主播_20260101120000.ts', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '保存设置', exact: true }).click();
  await expect(page.getByRole('button', { name: '保存设置', exact: true })).toBeDisabled();
  expect(writes[0].filename_template).toBe('{remark}/{owner}_{timestamp}');
  await page.getByLabel('命名规则', { exact: true }).selectOption('custom');
  await expect(page.getByText('{remark}', { exact: true })).toBeVisible();
  await page.getByLabel('文件名模板', { exact: true }).fill('{owner}_{remark}_{timestamp}');
  await expect(page.getByText('示例主播_示例备注_20260101120000.ts', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '保存设置', exact: true }).click();
  await expect(page.getByRole('button', { name: '保存设置', exact: true })).toBeDisabled();
  expect(writes[1].filename_template).toBe('{owner}_{remark}_{timestamp}');
});

test('record ID only appears when explicitly included in the template', async ({ page }) => {
  await settingsApi(page);
  await page.goto('/settings');
  await expect(page.getByText('DOUYIN_示例主播_20260101120000.ts', { exact: true })).toBeVisible();
  await page.getByLabel('命名规则', { exact: true }).selectOption('custom');
  await page.getByLabel('文件名模板', { exact: true }).fill('{owner}_{timestamp}_{record_id}');
  await expect(page.getByText('示例主播_20260101120000_' + 'a1b2c3d4'.repeat(4) + '.ts', { exact: true })).toBeVisible();
});

test('directory browser navigates and chooses without saving until confirmed', async ({ page }, testInfo) => {
  const writes = await settingsApi(page);
  await page.goto('/settings');
  await page.getByRole('button', { name: '浏览保存目录' }).click();
  const dialog = page.getByRole('dialog', { name: '选择保存目录' });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel('当前目录')).toHaveValue('E:/live-recorder/record');
  await dialog.getByRole('button', { name: '下一页目录' }).click();
  await expect(dialog.getByRole('button', { name: '打开 目录200', exact: true })).toBeVisible();
  await dialog.getByRole('button', { name: '上一页目录' }).click();
  await dialog.getByRole('button', { name: '打开 中文存档', exact: true }).click();
  await expect(dialog.getByText('没有子目录', { exact: true })).toBeVisible();
  await expect(dialog.getByLabel('当前目录')).toHaveValue('E:/live-recorder/record/中文存档');
  await dialog.getByRole('button', { name: '上一级', exact: true }).click();
  await expect(dialog.getByLabel('当前目录')).toHaveValue('E:/live-recorder/record');
  await dialog.getByRole('button', { name: '打开 中文存档', exact: true }).click();
  await page.screenshot({ path: testInfo.outputPath('directory-picker.png'), fullPage: true });
  await dialog.getByRole('button', { name: '选择此目录', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByLabel('保存路径', { exact: true })).toHaveValue('E:/live-recorder/record/中文存档');
  expect(writes).toEqual([]);
  await expect(page.getByRole('button', { name: '保存设置', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '保存设置', exact: true }).click();
  await expect(page.getByText('录制设置已保存', { exact: true })).toBeVisible();
  expect(writes[0].save_path).toBe('E:/live-recorder/record/中文存档');
  await page.reload();
  await expect(page.getByLabel('保存路径', { exact: true })).toHaveValue('E:/live-recorder/record/中文存档');
});

test('directory browser supports drives, manual navigation and cancellation', async ({ page }) => {
  const writes = await settingsApi(page);
  await page.goto('/settings');
  await page.getByRole('button', { name: '浏览保存目录' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByLabel('当前目录')).toHaveValue('E:/live-recorder/record');
  await dialog.getByRole('button', { name: '盘符和根目录' }).click();
  await expect(dialog.getByRole('button', { name: '选择此目录' })).toBeDisabled();
  await dialog.getByRole('button', { name: '打开 E:/', exact: true }).click();
  await dialog.getByRole('button', { name: '打开 直播存档', exact: true }).click();
  await expect(dialog.getByLabel('当前目录')).toHaveValue('E:/直播存档');
  await dialog.getByLabel('当前目录').fill('E:/live-recorder/record/中文存档');
  await expect(dialog.getByRole('button', { name: '选择此目录' })).toBeDisabled();
  await dialog.getByRole('button', { name: '打开目录', exact: true }).click();
  await expect(dialog.getByRole('button', { name: '选择此目录' })).toBeEnabled();
  await dialog.getByRole('button', { name: '取消', exact: true }).click();
  await expect(page.getByLabel('保存路径', { exact: true })).toHaveValue('./record');
  expect(writes).toEqual([]);
  await page.getByRole('button', { name: '浏览保存目录' }).click();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '浏览保存目录' })).toBeFocused();
});

test('directory access failure can be recovered without modifying settings', async ({ page }) => {
  const writes = await settingsApi(page, { failBrowseOnce: true });
  await page.goto('/settings');
  await page.getByRole('button', { name: '浏览保存目录' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('alert')).toHaveText('没有权限访问此目录');
  await expect(dialog.getByRole('button', { name: '选择此目录' })).toBeDisabled();
  await dialog.getByRole('button', { name: '刷新目录', exact: true }).click();
  await expect(dialog.getByLabel('当前目录')).toHaveValue('E:/live-recorder/record');
  await dialog.getByLabel('当前目录').fill('E:/missing');
  await dialog.getByRole('button', { name: '打开目录', exact: true }).click();
  await expect(dialog.getByRole('alert')).toHaveText('目录不存在或不是文件夹');
  await expect(dialog.getByRole('button', { name: '选择此目录' })).toBeDisabled();
  await dialog.getByRole('button', { name: '项目目录', exact: true }).click();
  await expect(dialog.getByLabel('当前目录')).toHaveValue('E:/live-recorder');
  await dialog.getByRole('button', { name: '取消', exact: true }).click();
  expect(writes).toEqual([]);
  await expect(page.getByLabel('保存路径', { exact: true })).toHaveValue('./record');
});
