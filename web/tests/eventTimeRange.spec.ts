import { expect, test } from '@playwright/test';
import { inMessageRange, messageDay } from '../src/pages/events/eventTimeRange';

test('消息时间按上海日历筛选，包含首尾且支持单边范围', () => {
  expect(messageDay('2038-06-01T16:00:00Z')).toBe('2038-06-02');
  expect(
    inMessageRange('2038-06-01T16:00:00Z', '2038-06-02', '2038-06-02'),
  ).toBe(true);
  expect(
    inMessageRange('2038-06-02T15:59:59Z', '2038-06-02', '2038-06-02'),
  ).toBe(true);
  expect(
    inMessageRange('2038-06-02T16:00:00Z', '2038-06-02', '2038-06-02'),
  ).toBe(false);
  expect(inMessageRange('2038-06-02T16:00:00Z', '2038-06-02', '')).toBe(true);
  expect(inMessageRange('2038-06-01T16:00:00Z', '', '2038-06-02')).toBe(true);
  expect(inMessageRange('invalid', '', '')).toBe(false);
});
