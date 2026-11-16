import { expect, test } from '@playwright/test';
import { historyBasis } from '../src/pages/events/historyBasisRecords';

const uid = '555002';
const stream = 'synthetic-history';
const stamp = '2038-06-01T10:00:00+08:00';
const proof = {
  source: 'official_chat',
  message_id: 'old',
  digest: 'synthetic-version',
  conversation_id: 'synthetic-room',
  send_time: stamp,
  quote: '虚构历史：上传问题此前已出现。',
  role: 'auxiliary',
};
function data(id = 'synthetic-first', quote = proof.quote) {
  return {
    uid,
    stream,
    event_id: id,
    batches: [],
    tasks: [],
    revisions: [],
    total_runs: 0,
    offset: 0,
    next_offset: null,
    execution_records_available: true,
    total_executions: 1,
    execution_offset: 0,
    next_execution_offset: null,
    executions: [
      {
        commit_status: 'committed',
        decisions: [
          { event_id: id, contributed_to_revision: true, proposal_id: 'p1' },
        ],
        inputs: [{ new_messages: [{ ...proof, message_id: 'new' }] }],
        suggestions: [{ proposal_id: 'p1', basis: [{ ...proof, quote }] }],
      },
    ],
  } as unknown as API.EventChangesResponse;
}

test('只取当前事件已提交且贡献修订的历史依据，去重但不混版本', () => {
  const value = data();
  expect(historyBasis(value)).toEqual([proof]);
  for (const mode of [
    'unconfirmed',
    'foreign',
    'no_contribution',
    'current_bot',
  ]) {
    const copy = structuredClone(value);
    const execution = copy.executions[0];
    if (mode === 'unconfirmed') execution.commit_status = 'unconfirmed';
    if (mode === 'foreign') execution.decisions[0].event_id = 'another';
    if (mode === 'no_contribution')
      execution.decisions[0].contributed_to_revision = false;
    if (mode === 'current_bot') execution.inputs[0].new_messages.push(proof);
    expect(historyBasis(copy)).toEqual([]);
  }
  value.executions[0].suggestions[0].basis.push(proof, {
    ...proof,
    digest: 'another-version',
  });
  expect(historyBasis(value)).toHaveLength(2);
});

function event(id: string) {
  return {
    event_id: id,
    uid,
    stream,
    type: '排障',
    topic_key: '虚构事项',
    start_time: stamp,
    end_time: stamp,
    created_on: stamp,
    summary: `虚构事件 ${id}`,
    status: '未知',
    severity: '未知',
    evidence: [],
    assignees: [],
    attributes: {},
    extensions: {},
    review_flag: null,
    closed_at: null,
    recovery: null,
    recurrence_of: null,
    schema_version: 1,
    updated_by: [],
    conversations: [],
    platforms: [],
  };
}

test('原事件页按需展开、分页、失败重试和切事件隔离，仅发只读请求', async ({
  page,
}) => {
  const reads: URL[] = [];
  const writes: string[] = [];
  let fail = false;
  let delayed = false;
  let release: (() => void) | undefined;
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    if (route.request().method() !== 'GET') {
      writes.push(route.request().method());
      return route.abort();
    }
    if (!['localhost', '127.0.0.1'].includes(url.hostname))
      return route.abort();
    if (!url.pathname.startsWith('/api/')) return route.continue();
    if (url.pathname.endsWith('/config'))
      return route.fulfill({
        json: {
          uid,
          start: '2038-06-01',
          end: '2038-06-02',
          interval: '5m',
          event_types: ['排障'],
          provider: 'stub',
          customers: [{ uid, stream, label: '虚构验收', synthetic: false }],
        },
      });
    if (url.pathname.endsWith('/runs'))
      return route.fulfill({ json: { items: [], total: 0 } });
    if (url.pathname.endsWith('/events'))
      return route.fulfill({
        json: {
          items: [event('synthetic-first'), event('synthetic-second')],
          total: 2,
        },
      });
    if (url.pathname.endsWith('/changes')) {
      reads.push(url);
      const second = url.pathname.includes('synthetic-second');
      if (delayed && !second)
        await new Promise<void>((resolve) => {
          release = resolve;
        });
      if (fail)
        return route.fulfill({ status: 503, json: { detail: '虚构读取失败' } });
      const value = data(
        second ? 'synthetic-second' : 'synthetic-first',
        second ? '虚构第二事件依据' : '虚构第一事件依据',
      );
      if (url.searchParams.get('execution_offset') === '0')
        value.next_execution_offset = 20;
      else value.executions = [];
      return route.fulfill({ json: value });
    }
    return route.fulfill({ status: 404, json: { detail: '虚构未配置' } });
  });
  await page.goto(`/events?uid=${uid}&stream=${stream}&event=synthetic-first`);
  const summary = page.locator('.event-history-basis > summary');
  await expect(summary).toBeVisible();
  expect(reads).toHaveLength(0);
  await summary.click();
  await expect(
    page.getByText('虚构第一事件依据', { exact: true }),
  ).toBeVisible();
  expect(
    reads.every(
      (url) =>
        url.searchParams.get('uid') === uid &&
        url.searchParams.get('stream') === stream,
    ),
  ).toBe(true);
  await page.getByRole('button', { name: '查看更早依据' }).click();
  await expect(
    page.getByText('本页历史依据未记录；不代表没有发生过相关讨论。'),
  ).toBeVisible();
  fail = true;
  await page.getByRole('button', { name: '回到最新依据' }).click();
  await expect(page.getByText('虚构读取失败')).toBeVisible();
  fail = false;
  delayed = true;
  await page
    .locator('.event-history-basis')
    .getByRole('button', { name: '重试' })
    .click();
  await expect.poll(() => !!release).toBe(true);
  await page
    .locator('.event-rows button')
    .filter({ hasText: 'synthetic-second' })
    .click();
  release?.();
  await expect(page.locator('.event-history-basis')).not.toHaveAttribute(
    'open',
    '',
  );
  await summary.click();
  await expect(
    page.getByText('虚构第二事件依据', { exact: true }),
  ).toBeVisible();
  await expect(page.getByText('虚构第一事件依据', { exact: true })).toHaveCount(
    0,
  );
  expect(writes).toEqual([]);
});
