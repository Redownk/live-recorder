import { test, expect } from '@playwright/test';

test('local videos use file endpoint while historical links stay available', async ({ page }) => {
  await page.route('**/crawler/status', (route) => route.fulfill({ json: { running: false, redis_connected: true } }));
  await page.route('**/api/videos?*', (route) => route.fulfill({ json: [
    { id: 1, file_name: 'local.ts', file_path: 'E:/record/local.ts', file_url: null, file_size: 100, duration: 12 },
    { id: 2, file_name: 'historical.mp4', file_url: 'https://example.com/old.mp4' },
    { id: 3, file_name: 'unsafe.mp4', file_url: 'javascript:alert(1)' },
  ] }));
  await page.goto('/videos');
  await expect(page.getByRole('link', { name: '打开 local.ts' })).toHaveAttribute('href', '/api/videos/1/file');
  await expect(page.getByRole('link', { name: '打开 historical.mp4' })).toHaveAttribute('href', 'https://example.com/old.mp4');
  await expect(page.getByRole('link', { name: '打开 unsafe.mp4' })).toHaveCount(0);
});
