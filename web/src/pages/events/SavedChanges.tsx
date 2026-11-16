import { formatTime } from '@/lib/utils';
import { VersionDifference } from './ChangeEvidence';
import { minuteTime, savedChanges } from './changeTimeline';
import { ExpandableText } from './ExpandableText';

/** 变化事实、触发引文和摘要前后直接展示；技术字段留在按需展开的详情。 */
export function SavedChanges({ data }: { data: API.EventChangesResponse }) {
  const rows = savedChanges(data);
  const days = [...new Set(rows.map((row) => row.day))];
  return (
    <section className="saved-changes" aria-label="已保存的事件变化">
      <h3>已保存的事件变化 · {rows.length} 条</h3>
      <p className="change-muted">
        按最后一条触发消息的上海时间分日展示，精确到分钟；保存时间见详情。
      </p>
      {!rows.length ? <p>暂无已保存的事件变化。</p> : null}
      {days.map((day) => (
        <section className="change-day" key={day} aria-label={day}>
          <h4>{day}</h4>
          <ol className="saved-change-list">
            {rows
              .filter((row) => row.day === day)
              .map((row) => (
                <li
                  key={row.index}
                  className="saved-change"
                  data-revision-index={row.index}
                >
                  <div className="saved-change-heading">
                    {row.time ? (
                      <time dateTime={row.time}>{minuteTime(row.time)}</time>
                    ) : (
                      <span>时间未记录</span>
                    )}
                    <strong>{row.title}</strong>
                    <small>版本 {row.revision.revision_no ?? '未记录'}</small>
                  </div>
                  <h5>触发消息</h5>
                  {row.triggers.length ? (
                    row.triggers.map((ref) => (
                      <blockquote
                        className="change-proof"
                        key={JSON.stringify([
                          ref.source,
                          ref.message_id,
                          ref.digest,
                        ])}
                      >
                        <ExpandableText
                          lines={4}
                          text={ref.quote || ''}
                          empty="触发消息正文未记录"
                        />
                        <small>
                          {ref.send_time
                            ? formatTime(ref.send_time)
                            : '消息时间未记录'}{' '}
                          · 消息 {ref.message_id || '未记录'}
                        </small>
                        <details>
                          <summary>来源与消息版本</summary>
                          <p>
                            来源 {ref.source || '未记录'} · 群{' '}
                            {ref.conversation_id || '未记录'}
                          </p>
                          <code>{ref.digest || '版本未记录'}</code>
                          <p>展示当时保存的引文或摘录，不以当前聊天替换。</p>
                        </details>
                      </blockquote>
                    ))
                  ) : (
                    <p>触发消息未记录。</p>
                  )}
                  <h5>变化说明</h5>
                  {row.evidenceOnly ? (
                    <p className="evidence-only-label">
                      仅补证据，不表示新的业务进展。
                    </p>
                  ) : null}
                  {row.descriptions.length ? (
                    row.descriptions.map((text) => <p key={text}>{text}</p>)
                  ) : (
                    <p>变化说明未记录。</p>
                  )}
                  <dl className="change-diff">
                    <dt>变化前摘要</dt>
                    <dd>
                      {row.revision.action === 'created'
                        ? '首次创建，无前版'
                        : (row.previous?.summary ?? '未记录')}
                    </dd>
                    <dt>变化后摘要</dt>
                    <dd>{row.revision.snapshot?.summary ?? '未记录'}</dd>
                  </dl>
                  {row.previous &&
                  row.revision.snapshot &&
                  row.previous.summary === row.revision.snapshot.summary ? (
                    <p className="change-muted">摘要未变化</p>
                  ) : null}
                  <details className="saved-change-details">
                    <summary>变化详情与保存依据</summary>
                    <VersionDifference
                      revision={row.revision}
                      previous={row.previous}
                    />
                  </details>
                </li>
              ))}
          </ol>
        </section>
      ))}
    </section>
  );
}
