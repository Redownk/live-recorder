import { expect, test } from '@playwright/test';

async function settingsApi(page, { failLoad = false, failSave = false } = {}) {
  let settings = { save_path: './record', filename_template: '{platform}_{owner}_{timestamp}', check_interval_seconds: 5 };
  const writes = [];
  function response(options) {
    const values = { platform: 'DOUYIN', owner: '示例主播', remark: '示例备注', room_id: '123456', title: '直播标题', timestamp: '20260101120000', date: '20260101', time: '120000', record_id: 'a1b2c3d4'.repeat(4) };
    return { ...options, resolved_save_path: `E:/live-recorder/${options.save_path}`, filename_example: options.filename_template.replace(/\{(\w+)\}/g, (_, key) => values[key] || '') + '.ts' };
  }
  await page.route(/\/(api|crawler)\//, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === '/crawler/status') return route.fulfill({ json: { running: false } });
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
  expect(writes).toEqual([{ save_path: './record/custom', filename_template: '{owner}_{room_id}_{timestamp}', check_interval_seconds: 15 }]);
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
