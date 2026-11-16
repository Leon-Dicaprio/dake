/** 消息身份与证据版本分开计数，避免把原消息的修订算成新消息。 */
export function messageKey(item: API.EvidenceResponse) {
  return JSON.stringify([item.source, item.message_id]);
}

export function evidenceKey(item: API.EvidenceResponse) {
  return JSON.stringify([item.source, item.message_id, item.digest ?? null]);
}

export function revisionEvidence(
  revision: API.EventRevision,
  previous: API.EventSnapshot | null | undefined,
  current: API.EvidenceResponse[],
) {
  const ids = new Set(revision.message_ids);
  const before = previous?.evidence || [];
  const knownVersions = new Set(before.map(evidenceKey));
  const knownMessages = new Set(before.map(messageKey));
  const comparable = revision.action === 'created' || Boolean(previous);
  const entries = (revision.snapshot?.evidence || []).filter(
    (item) =>
      ids.has(item.message_id) &&
      (!comparable || !knownVersions.has(evidenceKey(item))),
  );
  const unique = [
    ...new Map(entries.map((item) => [evidenceKey(item), item])).values(),
  ].sort((a, b) => Date.parse(a.send_time) - Date.parse(b.send_time));
  const missing =
    ids.size - new Set(unique.map((item) => item.message_id)).size;
  const complete = Boolean(revision.snapshot) && comparable && missing === 0;
  // 旧记录只有消息 ID；缺少前一快照时，多版本消息不能确定本次引用了哪一版。
  const locatable = unique
    .filter((item) => {
      if (
        !comparable &&
        unique.filter((other) => other.message_id === item.message_id)
          .length !== 1
      )
        return false;
      return (
        current.filter((other) => evidenceKey(other) === evidenceKey(item))
          .length === 1
      );
    })
    .map(evidenceKey);
  return {
    entries: unique,
    missing,
    complete,
    added: new Set(
      unique
        .filter((item) => !knownMessages.has(messageKey(item)))
        .map(messageKey),
    ).size,
    revised: new Set(
      unique
        .filter((item) => knownMessages.has(messageKey(item)))
        .map(messageKey),
    ).size,
    locatable,
  };
}
