/** 按上海自然日比较事件最后关联消息时间，日期范围包含首尾。 */
export function messageDay(value: string) {
  const date = new Date(value);
  return Number.isFinite(date.getTime())
    ? date.toLocaleDateString('sv-SE', { timeZone: 'Asia/Shanghai' })
    : '';
}

export function inMessageRange(value: string, start: string, end: string) {
  const day = messageDay(value);
  return Boolean(day) && (!start || day >= start) && (!end || day <= end);
}
