import { expect, test } from '@playwright/test';

test('隔离真实后端：选择起点、空窗口推进、暂停刷新及恢复', async ({ page }) => {
  const origin = process.env.DAKE_SCHEDULING_TEST_URL;
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
  await page.goto(`${origin}/schedules`);
  await expect(page.getByRole('heading', { name: '定时增量' })).toBeVisible();
  await page.getByLabel('最初开始日期（上海时间）').fill('2038-06-01');
  await page.getByRole('button', { name: '开始持续处理' }).click();
  await expect(
    page.getByRole('button', { name: '已保存开始日期' }),
  ).toBeDisabled();
  const row = page
    .getByRole('row')
    .filter({ hasText: 'synthetic-schedule-browser-a' });
  await expect(row).toBeVisible();
  await row.getByRole('button', { name: '暂停', exact: true }).click();
  await expect(row.getByText('已暂停', { exact: true })).toBeVisible();
  await page.reload();
  await expect(row.getByText('已暂停', { exact: true })).toBeVisible();
  await row.getByRole('button', { name: '恢复', exact: true }).click();
  await expect(
    row.getByRole('button', { name: '暂停', exact: true }),
  ).toBeVisible();
  await expect(
    row.getByText('已追上，等待新窗口', { exact: true }),
  ).toBeVisible({ timeout: 30000 });
  const response = await page.request.get(`${origin}/api/v1/schedules`);
  const status = await response.json();
  expect(status.items.length).toBe(2);
  expect(
    status.items.every(
      (item: API.ScheduleResponse) =>
        item.next_start === '2038-06-01T00:45:00+08:00',
    ),
  ).toBe(true);
  const requests = await (
    await page.request.get(`${origin}/api/v1/runs`)
  ).json();
  expect(
    requests.items.every(
      (item: API.RunResponse) => item.status === 'succeeded',
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});
