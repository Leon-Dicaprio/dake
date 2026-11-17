import { useState } from 'react';
import { Link } from 'umi';
import { ErrorNotice } from '@/components/Feedback';
import { Button } from '@/components/ui/button';
import { useResource } from '@/lib/useResource';
import { formatTime } from '@/lib/utils';
import { api } from '@/services/api';

const actions: Record<string, string> = {
  new: '新建事项',
  update: '更新已有事项',
  duplicate: '无需推进',
  review: '待确认',
  created: '新建事项',
  updated: '更新已有事项',
};
const phases = [
  { label: '接收新消息', stages: ['input'] },
  { label: '查找本群旧事项', stages: ['history'] },
  {
    label: '分析与归属判断',
    stages: ['suggestions', 'model_started', 'model_failed'],
  },
  { label: '核验并保存', stages: ['commit'] },
];

/** 只读真实过程记录，没有事件也可逐轮查看；运行期间自动刷新。 */
export function RunTrace({
  run,
  uid,
  stream,
  windowIndex,
}: {
  run: API.RunResponse;
  uid: string;
  stream: string;
  windowIndex: number;
}) {
  const [offset, setOffset] = useState(0);
  const active = run.status === 'queued' || run.status === 'running';
  const result = useResource(
    `trace:${uid}:${stream}:${run.run_id}:${windowIndex}:${run.status}:${offset}`,
    (signal) =>
      api.runExecutions(run.run_id, uid, stream, windowIndex, offset, signal),
    active ? 1500 : 0,
  );
  return (
    <section className="run-trace" aria-label="新消息处理过程">
      <div className="run-trace-heading">
        <div>
          <h3>新消息如何处理</h3>
          <p>
            第 {windowIndex + 1} 轮 ·{' '}
            {active
              ? '正在自动读取实际处理进展'
              : '以下为当时保存的输入、判断和结果'}
          </p>
        </div>
        <Button variant="ghost" size="small" onClick={result.refresh}>
          刷新过程
        </Button>
      </div>
      {result.error && (
        <ErrorNotice message={result.error} retry={result.refresh} />
      )}
      {!result.data && result.loading && <p>正在读取处理过程…</p>}
      {result.data && !result.data.items.length && (
        <p>
          {result.data.available
            ? active
              ? '等待这个窗口开始处理，消息进入后会显示在这里。'
              : '这个窗口没有保存处理过程记录。'
            : '当前环境尚未配置过程记录表。'}
        </p>
      )}
      {result.data?.items.map((item) => (
        <Trace
          key={item.attempt_id}
          item={item}
          uid={uid}
          stream={stream}
          timeoutSeconds={run.request.llm_timeout_seconds || 120}
        />
      ))}
      {(offset > 0 || result.data?.next_offset != null) && (
        <div className="dialog-actions">
          <Button
            size="small"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - 10))}
          >
            较新执行
          </Button>
          <Button
            size="small"
            disabled={result.data?.next_offset == null}
            onClick={() => setOffset(result.data?.next_offset ?? 0)}
          >
            较早执行
          </Button>
        </div>
      )}
    </section>
  );
}

function Trace({
  item,
  uid,
  stream,
  timeoutSeconds,
}: {
  item: API.RunExecution;
  uid: string;
  stream: string;
  timeoutSeconds: number;
}) {
  const requests = item.inputs.filter((batch) => batch.origin !== 'manifest');
  const versions = new Map<string, API.RecordedMessageRef>();
  for (const batch of [
    ...item.inputs.filter((value) => value.origin === 'manifest'),
    ...requests,
  ]) {
    for (const message of batch.new_messages)
      versions.set(
        `${message.source}:${message.message_id}:${message.digest}`,
        message,
      );
  }
  const candidates = new Map<string, Record<string, unknown>>();
  for (const history of item.histories)
    for (const candidate of history.candidates)
      candidates.set(String(candidate.event_id), candidate);
  const saved = item.commit_status === 'committed';
  const latestStage = item.stages[item.stages.length - 1];
  const waiting =
    item.outcome === 'running' && latestStage?.stage === 'model_started';
  const waitingSeconds = latestStage?.recorded_at
    ? Math.max(
        0,
        Math.floor((Date.now() - Date.parse(latestStage.recorded_at)) / 1000),
      )
    : null;
  return (
    <article className="trace-attempt">
      <div className="trace-caption">
        <strong>
          {formatTime(item.window.start)} — {formatTime(item.window.end)}
        </strong>
        <span>
          {item.outcome === 'commit_unknown'
            ? '提交待核实（不自动重跑）'
            : saved
              ? '已保存'
              : item.outcome === 'running'
                ? '处理中'
                : item.commit_status === 'not_committed'
                  ? '未保存'
                  : '保存结果待核实'}
        </span>
      </div>
      <ol className="trace-phases">
        {phases.map((phase, index) => {
          const found = item.stages.filter((stage) =>
            phase.stages.includes(stage.stage),
          );
          const label =
            index === 3
              ? saved
                ? '已提交'
                : found.length
                  ? '等待提交确认'
                  : '尚未开始'
              : found.some((stage) => stage.status === 'failed')
                ? '失败'
                : found.some((stage) => stage.status === 'completed')
                  ? '已记录结果'
                  : found.length
                    ? '处理中'
                    : '尚未开始';
          return (
            <li key={phase.label}>
              <span>{index + 1}</span>
              <strong>{phase.label}</strong>
              <small>{label}</small>
            </li>
          );
        })}
      </ol>
      {waiting && (
        <p className="trace-caption">
          正在分析本轮消息
          {waitingSeconds !== null ? `，已等待约 ${waitingSeconds} 秒` : ''}。
          单次分析等待上限约 {timeoutSeconds}{' '}
          秒；页面会自动更新，不需要重复提交。
        </p>
      )}
      {item.error_type && (
        <p className="notice">
          本次处理停止：{item.error_type}。以保存状态为准，页面不会自动重跑。
        </p>
      )}
      <h4>本轮新消息 · {versions.size} 条</h4>
      {[...versions.entries()].map(([key, message]) => (
        <div className="trace-message" key={key}>
          <small>
            {formatTime(message.send_time || '')} · 群{' '}
            {message.conversation_id || '未识别'} · 消息 {message.message_id}
          </small>
          <p>{message.quote || '已取得消息身份，分析原文尚未记录。'}</p>
        </div>
      ))}
      {!versions.size && <p>尚未取得待分析消息，或本窗口没有新增消息。</p>}
      <details className="trace-background">
        <summary>本群历史候选 · {candidates.size} 项</summary>
        {item.histories.map((history) => (
          <p key={JSON.stringify(history)}>
            群 {String(history.metadata.conversation_id || '未识别')} · 扫描{' '}
            {String(history.metadata.scanned ?? 0)} 项 ·
            {history.metadata.incomplete
              ? '检索有缺口，不能仅凭零命中新建'
              : '已完成本次历史检查'}
          </p>
        ))}
        {[...candidates.entries()].map(([id, candidate]) => (
          <p key={id}>
            {String(candidate.summary || '')} <small>{id}</small>
          </p>
        ))}
        {item.contexts.map((context) => (
          <div
            className="trace-message"
            key={`${context.message_id}-${context.digest}`}
          >
            <small>补取旧依据 · 消息 {context.message_id}</small>
            {context.fragments.map((fragment) => (
              <p key={fragment.text}>{fragment.text}</p>
            ))}
          </div>
        ))}
        {requests.some((r) => r.auxiliary_messages.length > 0) && (
          <details>
            <summary>查看辅助上下文</summary>
            {requests
              .flatMap((r) => r.auxiliary_messages)
              .map((message) => (
                <p
                  key={`${message.message_id}-${message.digest}-${message.quote}`}
                >
                  {message.quote || '仅保存身份引用'}
                </p>
              ))}
          </details>
        )}
      </details>
      <h4>逐项判断与保存结果</h4>
      {item.suggestions.map((suggestion) => {
        const decision = item.decisions.find(
          (d) => d.proposal_id && d.proposal_id === suggestion.proposal_id,
        );
        const write = item.writes.find(
          (w) => w.event_id && w.event_id === decision?.event_id,
        );
        return (
          <div
            className="trace-decision"
            key={suggestion.proposal_id || JSON.stringify(suggestion)}
          >
            <strong>{suggestion.summary || '本轮事项'}</strong>
            <p>
              分析建议：{actions[suggestion.action || ''] || '未记录'} ·
              程序决定：
              {decision
                ? actions[decision.action || ''] || decision.action
                : '等待核验'}
            </p>
            <p>{decision?.reason || suggestion.reason}</p>
            <p className="trace-save">
              {saved
                ? write
                  ? `已${actions[write.action || ''] || '保存'}`
                  : '本项未写入事件'
                : '尚无已确认的保存结果'}
              {saved && write?.event_id && (
                <Link
                  to={`/events?${new URLSearchParams({ uid, stream, event: write.event_id })}`}
                >
                  查看事件
                </Link>
              )}
            </p>
            {!!suggestion.basis.length && (
              <details>
                <summary>查看直接依据</summary>
                {suggestion.basis.map((proof) => (
                  <blockquote key={`${proof.message_id}-${proof.quote}`}>
                    {proof.quote}
                    <small>消息 {proof.message_id}</small>
                  </blockquote>
                ))}
              </details>
            )}
          </div>
        );
      })}
      {!item.suggestions.length && (
        <p>
          {saved || item.stages.some((stage) => stage.stage === 'suggestions')
            ? '本轮没有识别出需要跟进的事项。'
            : item.outcome === 'running'
              ? '等待分析结果。'
              : item.outcome === 'commit_unknown'
                ? '本轮结果待核实，请勿直接重复分析。'
                : '本轮未产生通过校验的分析结果，处理已停止。'}
        </p>
      )}
    </article>
  );
}
