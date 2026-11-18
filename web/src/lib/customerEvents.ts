/** 统计和列表使用相同范围，历史事件保留各自保存时的分析版本。 */
export function savedEventCount(customer?: API.CustomerResponse) {
  if (!customer) return undefined;
  return Object.values(customer.archived_event_counts || {}).reduce(
    (total, count) => total + count,
    customer.event_count,
  );
}

export function savedEventScopes(customer: API.CustomerResponse) {
  const archives = Object.keys(customer.archived_event_counts || {});
  const streams =
    customer.event_count === 0 ? archives : [customer.stream, ...archives];
  return streams.map((stream) => ({ uid: customer.uid, stream }));
}
