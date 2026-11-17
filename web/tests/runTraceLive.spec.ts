import { expect, test } from '@playwright/test';

/** 仅连接显式启动的隔离合成后端，覆盖真实入队、收据查询与刷新恢复。 */
test('隔离真实后端：空窗口完成后可读取过程与提交收据', async ({ page }) => {
  const origin = process.env.DAKE_RUN_TRACE_TEST_URL;
  test.skip(!origin, '须显式启动独立 MySQL 虚构验收服务');
  if (!origin || !/^http:\/\/127\.0\.0\.1:\d+$/.test(origin))
    throw new Error('只允许连接明确的本地隔离服务');
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route('**/*', (route) =>
    new URL(route.request().url()).origin === origin
      ? route.continue()
      : route.abort(),
  );
  await page.goto(`${origin}/runs`);
  await page.getByRole('button', { name: '处理新时段', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.locator('input[name=uid]').fill('555991');
  await dialog.locator('input[name=start]').fill('2038-06-01T00:00');
  await dialog.locator('input[name=end]').fill('2038-06-01T00:15');
  await dialog.getByRole('button', { name: '开始处理', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  const trace = page.getByRole('region', { name: '新消息处理过程' });
  await expect(trace.getByText('已保存', { exact: true })).toBeVisible();
  await expect(trace.getByText('本轮没有识别出需要跟进的事项。')).toBeVisible();
  const runId = new URL(page.url()).searchParams.get('run');
  expect(runId).toBeTruthy();
  const config = await (
    await page.request.get(`${origin}/api/v1/config`)
  ).json();
  const params = new URLSearchParams({
    uid: '555991',
    stream: config.customers[0].stream,
    window_index: '0',
  });
  const response = await page.request.get(
    `${origin}/api/v1/runs/${runId}/executions?${params}`,
  );
  expect(response.ok()).toBe(true);
  const saved = await response.json();
  expect(saved.items).toHaveLength(1);
  expect(saved.items[0].commit_status).toBe('committed');
  expect(saved.items[0].processed).toBe(0);
  expect(saved.items[0].writes).toEqual([]);
  await page.reload();
  await expect(trace.getByText('已保存', { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});
