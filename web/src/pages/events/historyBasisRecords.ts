/** 仅提取当前事件已提交决定实际使用的旧依据，候选命中与失败建议不算。 */
export function historyBasis(data: API.EventChangesResponse) {
  const refs: API.RecordedMessageRef[] = [];
  for (const execution of data.executions || []) {
    if (execution.commit_status !== 'committed') continue;
    const proposals = new Set(
      execution.decisions
        .filter(
          (decision) =>
            decision.event_id === data.event_id &&
            decision.contributed_to_revision === true &&
            decision.proposal_id,
        )
        .map((decision) => decision.proposal_id),
    );
    const newKeys = new Set(
      execution.inputs.flatMap((input) =>
        input.new_messages.map((ref) => `${ref.source}:${ref.message_id}`),
      ),
    );
    for (const suggestion of execution.suggestions) {
      if (!suggestion.proposal_id || !proposals.has(suggestion.proposal_id))
        continue;
      refs.push(
        ...suggestion.basis.filter(
          (ref) =>
            (ref.role === 'history' || ref.role === 'auxiliary') &&
            !newKeys.has(`${ref.source}:${ref.message_id}`),
        ),
      );
    }
  }
  // 旧批次只能以本事件已保存修订证明关联，不能将待确认或候选伪装为保存依据。
  for (const batch of data.batches || []) {
    for (const record of batch.attributions) {
      if (
        record.event_id === data.event_id &&
        record.revision_no != null &&
        data.revisions.some(
          (revision) => revision.revision_no === record.revision_no,
        )
      ) {
        refs.push(...record.basis.filter((ref) => ref.role === 'history'));
      }
    }
  }
  return [...new Map(refs.map((ref) => [JSON.stringify(ref), ref])).values()];
}
