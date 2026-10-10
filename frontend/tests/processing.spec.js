import { expect, test } from '@playwright/test';

async function processingApi(page, { failBrowse = false, failSubmit = false } = {}) {
  const writes = [];
  const jobs = [];
  await page.route(/\/(api|crawler)\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === '/crawler/status') return route.fulfill({ json: { running: false } });
    if (path === '/api/settings') return route.fulfill({ json: { resolved_save_path: 'E:/record' } });
    if (path === '/api/processing/capabilities') return route.fulfill({ json: { encoders: [{ value: 'copy', label: 'copy', available: true }, { value: 'libx264', label: 'H.264 (x264)', available: true }, { value: 'libx265', label: 'H.265 (x265)', available: true }, { value: 'h264_nvenc', label: 'H.264 (NVIDIA NVENC)', available: false }], error: '' } });
    if (path === '/api/processing/files' || path === '/api/settings/directories') {
      if (failBrowse) { failBrowse = false; return route.fulfill({ status: 403, json: { detail: '没有权限访问此目录' } }); }
      const current = url.searchParams.get('path') || null;
      const directories = path === '/api/processing/files' ? [{ name: '片段1.ts', path: 'E:/record/片段1.ts', is_file: true, size: 1024 }, { name: '很长的直播视频文件名称用于验证移动端文本换行片段2.ts', path: 'E:/record/很长的直播视频文件名称用于验证移动端文本换行片段2.ts', is_file: true, size: 2048 }] : [];
      return route.fulfill({ json: { path: current || 'E:/record', parent: 'E:/', directories, shortcuts: [{ name: '项目目录', path: 'E:/record' }], offset: 0, limit: 200, total: directories.length, has_more: false } });
    }
    if (path === '/api/processing/jobs' && request.method() === 'POST') {
      writes.push(request.postDataJSON());
      if (failSubmit) return route.fulfill({ status: 400, json: { detail: '文件已被其他处理任务占用' } });
      const body = request.postDataJSON();
      const job = { id: String(jobs.length + 1), mode: body.mode, status: 'running', progress: 35, current_file: '输出视频.mp4', files: body.files, outputs: [], error: '', warning: '' };
      jobs.unshift(job);
      return route.fulfill({ status: 202, json: job });
    }
    if (path.startsWith('/api/processing/jobs/') && request.method() === 'DELETE') {
      const job = jobs.find((item) => item.id === path.split('/').pop());
      job.status = 'cancelled';
      return route.fulfill({ json: job });
    }
    if (path === '/api/processing/jobs') return route.fulfill({ json: jobs });
    return route.fulfill({ json: [] });
  });
  return writes;
}

async function selectFiles(page) {
  await page.getByRole('button', { name: '添加', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('checkbox', { name: '选择 片段1.ts', exact: true }).check();
  await dialog.getByRole('checkbox', { name: /选择 很长/ }).check();
  await dialog.getByRole('button', { name: '添加所选文件' }).click();
  await expect(dialog).not.toBeVisible();
}

test('transcode selection, encoder rules, output directory and cancellation', async ({ page }, testInfo) => {
  const writes = await processingApi(page);
  await page.goto('/processing/transcode');
  await expect(page.getByRole('button', { name: '立即转换' })).toBeDisabled();
  await selectFiles(page);
  await expect(page.getByRole('button', { name: '添加', exact: true })).toBeFocused();
  await page.getByLabel('编码器', { exact: true }).selectOption('libx265');
  await page.getByLabel('转码规则', { exact: true }).selectOption('quality');
  await page.getByLabel('输出格式', { exact: true }).selectOption('mkv');
  await page.getByRole('checkbox', { name: '保存到原始文件夹' }).uncheck();
  await expect(page.getByRole('button', { name: '立即转换' })).toBeDisabled();
  await page.getByRole('button', { name: '选择输出目录' }).click();
  await page.getByRole('button', { name: '选择此目录' }).click();
  await expect(page.getByLabel('输出目录', { exact: true })).toHaveValue('E:/record');
  await page.getByRole('button', { name: '立即转换' }).click();
  await expect(page.getByText('处理中', { exact: true })).toBeVisible();
  expect(writes[0]).toMatchObject({ mode: 'transcode', encoder: 'libx265', preset: 'quality', container: 'mkv', save_original: false, output_directory: 'E:/record', remove_source: false });
  await page.getByRole('button', { name: '取消任务' }).click();
  await expect(page.getByText('已取消', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('transcode.png'), fullPage: true });
});

test('merge keeps file order and accepts subtitles and metadata options', async ({ page }, testInfo) => {
  const writes = await processingApi(page);
  await page.goto('/processing/merge');
  await selectFiles(page);
  await page.getByRole('button', { name: '下移 片段1.ts', exact: true }).click();
  await page.getByRole('checkbox', { name: '合并弹幕 / 字幕' }).check();
  await page.getByRole('checkbox', { name: '保留元数据' }).uncheck();
  await page.getByLabel('输出文件名').fill('直播合集');
  await page.getByRole('button', { name: '立即合并' }).click();
  expect(writes[0]).toMatchObject({ mode: 'merge', output_name: '直播合集', merge_subtitles: true, keep_metadata: false, remove_source: false });
  expect(writes[0].files[0]).toContain('片段2.ts');
  expect(writes[0].files[1]).toBe('E:/record/片段1.ts');
  await expect(page.getByRole('progressbar')).toHaveAttribute('value', '35');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('merge.png'), fullPage: true });
});

test('source removal requires confirmation and file browser recovers from error', async ({ page }) => {
  const writes = await processingApi(page, { failBrowse: true });
  await page.goto('/processing/transcode');
  await page.getByRole('button', { name: '添加', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveText('没有权限访问此目录');
  await page.getByRole('button', { name: '刷新目录' }).click();
  await page.getByRole('checkbox', { name: '选择 片段1.ts', exact: true }).check();
  await page.getByRole('button', { name: '添加所选文件' }).click();
  await page.getByRole('checkbox', { name: '完成后移除源文件' }).check();
  await page.getByRole('button', { name: '立即转换' }).click();
  await expect(page.getByRole('dialog', { name: '确认移除源文件' })).toBeVisible();
  expect(writes).toHaveLength(0);
  await page.getByRole('button', { name: '确认转换并移除' }).click();
  expect(writes[0].remove_source).toBe(true);
});

test('copy disables quality preset and submission errors preserve selection', async ({ page }) => {
  const writes = await processingApi(page, { failSubmit: true });
  await page.goto('/processing/transcode');
  await selectFiles(page);
  await page.getByLabel('编码器', { exact: true }).selectOption('copy');
  await expect(page.getByLabel('转码规则', { exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '立即转换' }).click();
  await expect(page.getByRole('alert')).toHaveText('文件已被其他处理任务占用');
  await expect(page.getByRole('button', { name: '移除 片段1.ts', exact: true })).toBeVisible();
  expect(writes).toHaveLength(1);
});
