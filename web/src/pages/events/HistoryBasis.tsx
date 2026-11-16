import { useState } from 'react';
import { ErrorNotice, LoadingRows } from '@/components/Feedback';
import { Button } from '@/components/ui/button';
import { useResource } from '@/lib/useResource';
import { api } from '@/services/api';
import { Proofs } from './ChangeEvidence';
import { historyBasis } from './historyBasisRecords';

/** 按需读取现有只读记录；切事件卸载后取消请求，不启动或重跑任何分析。 */
export function HistoryBasis({ event }: { event: API.EventResponse }) {
  const [open, setOpen] = useState(false);
  const [offset, setOffset] = useState(0);
  const [executionOffset, setExecutionOffset] = useState(0);
  const resource = useResource(
    open
      ? JSON.stringify([
          'history-basis',
          event.uid,
          event.stream,
          event.event_id,
          offset,
          executionOffset,
        ])
      : null,
    (signal) =>
      api.eventChanges(
        event.event_id,
        event.uid,
        event.stream,
        offset,
        signal,
        executionOffset,
      ),
  );
  const data = resource.data;
  const scoped =
    data?.uid === event.uid &&
    data.stream === event.stream &&
    data.event_id === event.event_id
      ? data
      : undefined;
  const refs = scoped ? historyBasis(scoped) : [];
  return (
    <details
      className="event-history-basis"
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary>查看历史依据</summary>
      {open ? (
        <>
          <p className="change-muted">
            以下是本事件已保存判断引用的旧消息片段，不是本轮新增消息，也不等于完整群聊。
          </p>
          {resource.loading && !scoped ? <LoadingRows /> : null}
          {resource.error ? (
            <ErrorNotice message={resource.error} retry={resource.refresh} />
          ) : null}
          {data && !scoped ? <p>返回范围不匹配，未展示依据。</p> : null}
          {scoped ? (
            <>
              {refs.length ? (
                <Proofs items={refs} />
              ) : (
                <p>本页历史依据未记录；不代表没有发生过相关讨论。</p>
              )}
              {scoped.next_execution_offset != null ||
              scoped.next_offset != null ? (
                <Button
                  variant="ghost"
                  onClick={() => {
                    setExecutionOffset(
                      scoped.next_execution_offset ?? executionOffset,
                    );
                    setOffset(scoped.next_offset ?? offset);
                  }}
                >
                  查看更早依据
                </Button>
              ) : null}
              {offset > 0 || executionOffset > 0 ? (
                <Button
                  variant="ghost"
                  onClick={() => {
                    setOffset(0);
                    setExecutionOffset(0);
                  }}
                >
                  回到最新依据
                </Button>
              ) : null}
            </>
          ) : null}
        </>
      ) : null}
    </details>
  );
}
