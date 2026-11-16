import { expect, test } from '@playwright/test';

test.skip(process.env.DAKE_LIVE_PANEL !== '1', '仅显式开启本地只读验收');

/** 显式开启的本地只读验收；不截图、不记录正文、不提交分析任务。 */
test('真实后端：变化先加载、详情按需读取、完成后停止轮询', async ({
  page,
  request,
}) => {
  const config = await (await request.get('/api/v1/config')).json();
  const result = await (
    await request.get('/api/v1/events', { params: { uid: config.uid } })
  ).json();
  expect(result.items.length).toBeGreaterThan(1);
  const event = result.items[0];
  const calls: string[] = [];
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.name));
  page.on('request', (req) => {
    if (new URL(req.url()).pathname.endsWith('/changes')) calls.push(req.url());
  });
  await page.route('**/*', (route) => {
    const url = new URL(route.request().url());
    if (
      ['127.0.0.1', 'localhost'].includes(url.hostname) &&
      route.request().method() === 'GET'
    )
      return route.continue();
    return route.abort();
  });
  await page.goto(
    `/events?${new URLSearchParams({ uid: event.uid, event: event.event_id })}`,
  );
  const button = page.getByRole('button', { name: '变化面板', exact: true });
  await expect(button).toBeEnabled();
  await expect(
    page.locator('.inbox-aside').getByText('查看历史依据', { exact: true }),
  ).toHaveCount(0);
  const timeFilter = page.getByRole('button', { name: /^时间范围：/ });
  await timeFilter.click();
  const picker = page.getByRole('dialog', { name: '选择时间范围' });
  await picker.locator('.rdp-day_button').filter({ hasText: /^10$/ }).click();
  await picker.locator('.rdp-day_button').filter({ hasText: /^12$/ }).click();
  await expect(picker.getByLabel('开始日期', { exact: true })).toHaveValue(
    /-10$/,
  );
  await expect(picker.getByLabel('结束日期', { exact: true })).toHaveValue(
    /-12$/,
  );
  await expect(picker.locator('.rdp-range_middle')).not.toHaveCount(0);
  await page.keyboard.press('Escape');
  await expect(timeFilter).toBeFocused();
  await timeFilter.click();
  await picker.getByLabel('开始日期', { exact: true }).fill('2099-01-01');
  await expect(
    picker.getByRole('button', { name: '应用', exact: true }),
  ).toBeDisabled();
  await picker.getByLabel('结束日期', { exact: true }).fill('2099-01-02');
  await expect(page.locator('.event-rows > li').first()).toBeVisible();
  await picker.getByRole('button', { name: '取消', exact: true }).click();
  await expect(timeFilter).toHaveText('全部时间');
  await timeFilter.click();
  await picker.getByLabel('开始日期', { exact: true }).fill('2099-01-01');
  await picker.getByLabel('结束日期', { exact: true }).fill('2099-01-02');
  await picker.getByRole('button', { name: '应用', exact: true }).click();
  await expect(page.locator('.event-rows > li')).toHaveCount(0);
  await expect(timeFilter).toHaveText('2099-01-01 至 2099-01-02');
  await timeFilter.click();
  await picker.getByRole('button', { name: '清除筛选', exact: true }).click();
  await expect(button).toBeEnabled();
  const compactResponse = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname.endsWith('/changes') &&
      new URL(response.url()).searchParams.get('include_details') === 'false',
  );
  await button.click();
  const compact = await (await compactResponse).json();
  expect(compact.details_included).toBe(false);
  expect(
    compact.executions.every((item: API.EventExecution) => !item.inputs.length),
  ).toBe(true);
  const dialog = page.getByRole('dialog', { name: '变化面板' });
  const timeline = dialog.getByRole('region', { name: '已保存的事件变化' });
  await expect(timeline).toBeVisible();
  expect(
    calls.every(
      (url) => new URL(url).searchParams.get('include_details') === 'false',
    ),
  ).toBe(true);
  const cards = timeline.locator('.saved-change');
  const order = await cards.evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute('data-revision-index')),
  );
  await timeline
    .getByRole('button', { name: '当前最新在前 · 从头查看流转' })
    .click();
  expect(
    await cards.evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute('data-revision-index')),
    ),
  ).toEqual([...order].reverse());
  const firstCard = cards.first();
  await expect(firstCard.locator('.change-proof').first()).not.toBeVisible();
  await firstCard.getByText(/^触发消息 ·/).click();
  await expect(firstCard.locator('.change-proof').first()).toBeVisible();
  await expect(
    firstCard.getByText('来源与消息版本', { exact: true }),
  ).toHaveCount(0);
  await expect(firstCard.locator('.change-diff').first()).not.toBeVisible();
  await firstCard.getByText('完整摘要对比', { exact: true }).click();
  await expect(firstCard.locator('.change-diff').first()).toBeVisible();
  await firstCard
    .getByText('核对记录 · 保存时间与消息标识', { exact: true })
    .click();
  await expect(firstCard.getByText('原摘要', { exact: true })).toHaveCount(0);
  const fullResponse = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname.endsWith('/changes') &&
      new URL(response.url()).searchParams.get('include_details') === 'true',
  );
  await dialog
    .getByRole('button', { name: '查看处理链路 · 输入 → 候选 → 判断 → 提交' })
    .click();
  await expect(timeline).toBeVisible();
  const full = await (await fullResponse).json();
  expect(full.details_included).toBe(true);
  expect(full.total_executions).toBe(compact.total_executions);
  expect(full.revisions.length).toBe(compact.revisions.length);
  await expect(
    dialog.getByRole('heading', { name: '与本事件有关的执行批次' }),
  ).toBeVisible();
  const active =
    full.executions.some(
      (item: API.EventExecution) => item.outcome === 'running',
    ) ||
    full.tasks.some((item: API.ScopedChangeTask) =>
      ['queued', 'running'].includes(item.status),
    );
  if (!active) {
    const count = calls.length;
    await page.waitForTimeout(3500);
    expect(calls.length).toBe(count);
  }
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  const second = result.items[1];
  await page.goto(
    `/events?${new URLSearchParams({ uid: second.uid, event: second.event_id })}`,
  );
  const nextResponse = page.waitForResponse((response) =>
    new URL(response.url()).pathname.endsWith(
      `/events/${second.event_id}/changes`,
    ),
  );
  await button.click();
  const next = await (await nextResponse).json();
  expect(
    next.event_id === second.event_id && next.details_included === false,
  ).toBe(true);
  await expect(dialog.locator('.change-technical')).not.toHaveAttribute(
    'open',
    '',
  );
  expect(errors).toEqual([]);
});
