import { expect, test } from '@playwright/test';

async function mockApi(page, { failAdd = false, failRemarkOnce = false } = {}) {
  const requests = [];
  let running = false;
  let rooms = [{
    id: 1, platform: 'DOUYIN', room_id: '12345', owner: '测试主播', title: '<b>直播标题</b>', remark: '初始备注',
    monitor_enabled: true, room_url: 'https://live.douyin.com/12345', avatar: null,
    last_live_time: '2026-10-09T09:00:00',
  }];
  await page.route(/\/(api|crawler)\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    const body = request.postDataJSON();
    requests.push({ path, method, body, query: Object.fromEntries(url.searchParams) });
    const json = (data, status = 200) => route.fulfill({ status, json: data });
    if (path === '/crawler/status') return json({ running });
    if (path === '/api/recording-status') return json({});
    if (path === '/crawler/start' || path === '/crawler/stop') {
      running = path.endsWith('/start');
      return json({ msg: running ? 'started' : 'stopped' });
    }
    if (path === '/api/rooms' && method === 'GET') {
      const keyword = url.searchParams.get('keyword') || '';
      return json(rooms.filter((room) => `${room.owner}${room.room_id}${room.remark || ''}`.includes(keyword)));
    }
    if (path === '/api/rooms' && method === 'POST') {
      if (failAdd) return json({ detail: '直播间信息获取失败，请检查链接是否有效' }, 400);
      await new Promise((resolve) => setTimeout(resolve, 200));
      const room = { ...rooms[0], id: 2, owner: '新主播', room_id: '67890', ...body };
      room.remark = (body.remark || '').trim() || room.owner;
      rooms = [...rooms, room];
      return json(room, 201);
    }
    const match = path.match(/^\/api\/rooms\/(\d+)(?:\/(monitor|live-status))?$/);
    if (match) {
      const room = rooms.find((item) => item.id === Number(match[1]));
      if (match[2] === 'live-status') return json({ is_live: true, owner: room.owner, title: '正在直播' });
      if (method === 'DELETE') { rooms = rooms.filter((item) => item !== room); return route.fulfill({ status: 204 }); }
      if (method === 'PUT' && Object.hasOwn(body, 'remark')) {
        if (failRemarkOnce) { failRemarkOnce = false; return json({ detail: '备注保存失败' }, 503); }
        await new Promise((resolve) => setTimeout(resolve, 200));
      }
      Object.assign(room, body);
      return json(room);
    }
    if (path === '/api/logs') return json([{ id: 7, live_room_id: 1, platform: 'DOUYIN', owner: '测试主播', title: '录制标题', start_live: '2026-10-09T09:00:00', end_live: '2026-10-09T10:00:00', live_time: 3600, user_num: 0 }]);
    if (path === '/api/videos') return json([{ id: 10, file_name: '直播录制.mp4', file_size: 1048576, duration: 3600, create_time: '2026-10-09T10:00:00', file_url: 'https://example.com/video.mp4' }]);
    return json({ detail: '未模拟的接口' }, 404);
  });
  return requests;
}

test('room workflow and crawler controls', async ({ page }, testInfo) => {
  const requests = await mockApi(page);
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/');
  await expect(page).toHaveURL(/\/rooms$/);
  await expect(page.getByText('<b>直播标题</b>', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '添加直播间', exact: true }).click();
  await page.getByRole('textbox', { name: '直播间 URL' }).fill('https://live.douyin.com/67890');
  await page.getByRole('textbox', { name: '备注', exact: true }).fill('新备注');
  await page.getByRole('button', { name: '添加', exact: true }).click();
  await expect(page.getByRole('button', { name: '提交中…' })).toBeDisabled();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByText('新主播', { exact: true })).toBeVisible();
  expect(requests.find((item) => item.method === 'POST' && item.path === '/api/rooms').body).toEqual({ room_url: 'https://live.douyin.com/67890', remark: '新备注', monitor_enabled: true });
  await page.getByRole('button', { name: '检查 新主播', exact: true }).click();
  await expect(page.getByText('正在直播：正在直播', { exact: true })).toBeVisible();
  await expect(page.getByText('录制中', { exact: true })).toHaveCount(0);
  await page.getByRole('switch', { name: '监控 新主播' }).uncheck();
  await expect(page.getByRole('switch', { name: '监控 新主播' })).not.toBeChecked();
  await page.getByRole('button', { name: '编辑 新主播' }).click();
  await page.getByRole('textbox', { name: '主播昵称' }).fill('已编辑主播');
  await page.getByRole('textbox', { name: '备注', exact: true }).fill('弹窗修改备注');
  await page.getByRole('button', { name: '保存', exact: true }).click();
  await expect(page.getByText('已编辑主播', { exact: true })).toBeVisible();
  await expect(page.getByText('弹窗修改备注', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '删除 已编辑主播' }).click();
  await page.getByRole('button', { name: '确认删除' }).click();
  await expect(page.getByText('已编辑主播', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '启动', exact: true }).click();
  await expect(page.getByText('监控运行中', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '停止', exact: true }).click();
  await expect(page.getByRole('region', { name: '录制监控' }).getByText('监控已停止', { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath('rooms.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('failed add preserves input and allows retry', async ({ page }) => {
  await mockApi(page, { failAdd: true });
  await page.goto('/rooms');
  await page.getByRole('button', { name: '添加直播间', exact: true }).click();
  const input = page.getByRole('textbox', { name: '直播间 URL' });
  await input.fill('https://live.douyin.com/67890');
  await page.getByRole('button', { name: '添加', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveText('直播间信息获取失败，请检查链接是否有效');
  await expect(input).toHaveValue('https://live.douyin.com/67890');
  await expect(page.getByRole('button', { name: '添加', exact: true })).toBeEnabled();
});

test('new room gets owner as default remark and can be edited after adding', async ({ page }) => {
  await mockApi(page);
  await page.goto('/rooms');
  await page.getByRole('button', { name: '添加直播间', exact: true }).click();
  await page.getByRole('textbox', { name: '直播间 URL' }).fill('https://live.douyin.com/67890');
  await page.getByRole('button', { name: '添加', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  const row = page.getByRole('row').filter({ has: page.getByRole('button', { name: '编辑备注 新主播', exact: true }) });
  await expect(row.getByRole('cell').nth(2)).toHaveText('新主播');
  await page.getByRole('button', { name: '编辑备注 新主播', exact: true }).click();
  const input = page.getByRole('textbox', { name: '备注 新主播', exact: true });
  await expect(input).toHaveValue('新主播');
  await input.fill('自定义备注');
  await page.getByRole('button', { name: '保存备注', exact: true }).click();
  await expect(row.getByRole('cell').nth(2)).toHaveText('自定义备注');
  await page.reload();
  await expect(row.getByRole('cell').nth(2)).toHaveText('自定义备注');
});

test('remarks can be edited inline, cancelled, searched and cleared', async ({ page }, testInfo) => {
  const requests = await mockApi(page);
  await page.goto('/rooms');
  await expect(page.getByRole('columnheader', { name: '备注', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '编辑备注 测试主播' }).click();
  const input = page.getByRole('textbox', { name: '备注 测试主播', exact: true });
  await expect(input).toBeFocused();
  await input.fill('  分类备注  ');
  await page.getByRole('button', { name: '保存备注', exact: true }).click();
  await expect(page.getByRole('button', { name: '保存备注', exact: true })).toBeDisabled();
  await expect(page.getByText('分类备注', { exact: true })).toBeVisible();
  expect(requests.find((item) => item.method === 'PUT').body).toEqual({ remark: '分类备注' });
  await page.reload();
  await expect(page.getByText('分类备注', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '编辑备注 测试主播' }).click();
  await input.fill('取消的修改');
  await page.getByRole('button', { name: '取消编辑备注', exact: true }).click();
  await expect(page.getByText('分类备注', { exact: true })).toBeVisible();
  expect(requests.filter((item) => item.method === 'PUT')).toHaveLength(1);
  await page.getByRole('searchbox', { name: '搜索直播间' }).fill('分类备注');
  await page.getByRole('button', { name: '搜索', exact: true }).click();
  await expect(page.getByText('分类备注', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '编辑备注 测试主播' }).click();
  await input.fill('');
  await page.getByRole('button', { name: '保存备注', exact: true }).click();
  await expect(page.getByRole('textbox', { name: '备注 测试主播', exact: true })).toHaveCount(0);
  expect(requests.filter((item) => item.method === 'PUT')[1].body).toEqual({ remark: null });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('remarks.png'), fullPage: true });
});

test('failed inline remark save preserves draft for retry', async ({ page }) => {
  await mockApi(page, { failRemarkOnce: true });
  await page.goto('/rooms');
  await page.getByRole('button', { name: '编辑备注 测试主播' }).click();
  const input = page.getByRole('textbox', { name: '备注 测试主播', exact: true });
  await input.fill('<b>备注</b>');
  await page.getByRole('button', { name: '保存备注', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveText('备注保存失败');
  await expect(input).toHaveValue('<b>备注</b>');
  await page.getByRole('button', { name: '保存备注', exact: true }).click();
  await expect(page.getByText('<b>备注</b>', { exact: true })).toBeVisible();
  await expect(page.locator('.remark-display b')).toHaveCount(0);
});

test('log and video filters survive reload', async ({ page }, testInfo) => {
  const requests = await mockApi(page);
  await page.goto('/rooms');
  await page.getByRole('link', { name: '日志 测试主播', exact: true }).click();
  await expect(page).toHaveURL(/\/logs\?room_id=1$/);
  await expect(page.getByText('录制标题', { exact: true })).toBeVisible();
  expect(requests.find((item) => item.path === '/api/logs').query.room_id).toBe('1');
  await page.getByRole('link', { name: '查看日志 7 的视频' }).click();
  await expect(page).toHaveURL(/\/videos\?log_id=7$/);
  await expect(page.getByText('直播录制.mp4', { exact: true })).toBeVisible();
  await expect(page.getByText('1.0 MB', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: '视频文件', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: '打开 直播录制.mp4' })).toHaveAttribute('href', 'https://example.com/video.mp4');
  await page.screenshot({ path: testInfo.outputPath('videos.png'), fullPage: true });
});
