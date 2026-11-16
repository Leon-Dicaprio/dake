import { formatTime } from '@/lib/utils';
import { Proofs, VersionDifference } from './ChangeEvidence';

const actions: Record<string, string> = {
  new: '新建',
  update: '旧事件进展',
  duplicate: '重复',
  review: '待确认',
  created: '新建',
  updated: '旧事件进展',
  no_change: '无变化',
};
const reasons: Record<string, string> = {
  candidate: '历史候选命中',
  context: '旧聊天依据关联',
  model_input: '请求候选引用',
  suggestion: '模型建议引用',
  decision: '程序决定引用',
  write: '提交收据中的写入',
  recovery: '恢复原结果',
  revision: '事件版本关联',
  retry: '明确接续前次执行',
};
const availability: Record<string, string> = {
  full: '已取得原版本',
  excerpt_only: '仅有旧摘录',
  missing: '正文缺失',
  historical_version_unavailable: '历史版本无法还原',
  already_in_input: '已在本批输入中',
};
const gaps: Record<string, string> = {
  candidate_retrieval_incomplete: '候选检索不完整',
  no_candidate: '没有取得候选',
  evidence_references_unavailable: '证据引用缺失',
  evidence_version_unavailable: '证据版本缺失',
  message_truncated: '长消息已截断',
  message_budget: '消息数量预算不足',
  context_budget: '上下文预算不足',
  neighbor_anchor_unavailable: '邻域定位锚点缺失',
  neighbor_not_found: '没有取得邻域消息',
  neighbor_budget: '邻域补取达到预算',
  neighbor_version_unavailable: '邻域历史版本无法还原',
};
const delivery: Record<string, string> = {
  saved: '已保存',
  restored_or_kept_existing: '已恢复或保留已有展示',
  failed: '保存失败',
  unconfirmed: '写入未确认',
  not_attempted: '尚未尝试写入',
};
const action = (value: string | null) =>
  value ? actions[value] || value : '未记录';
const stageNames: Record<string, string> = {
  execution: '执行开始',
  ingestion: '消息取得',
  input: '输入清单',
  history: '历史候选',
  history_context: '旧聊天补取',
  extraction: '分析开始',
  provider_input: '分析输入',
  model_started: '模型请求准备',
  model_completed: '模型结构化结果',
  model_failed: '模型调用或校验失败',
  suggestions: '结构化建议',
  decision: '程序决定',
  program_result: '程序结果',
  commit: '提交前准备',
  recovery: '恢复原结果',
  verification: '显式核实记录',
};
const stageStatuses: Record<string, string> = {
  started: '已记录开始',
  completed: '已记录结果',
  skipped: '已记录跳过',
  failed: '已记录失败',
  pending: '提交前记录',
};

/** 只根据已有观察点显示阶段状态，不按后续结果反推步骤完成。 */
function Stage({ item, names }: { item: API.EventExecution; names: string[] }) {
  const stages = item.stages.filter((stage) => names.includes(stage.stage));
  if (!stages.length) return <span>未记录</span>;
  return (
    <span>
      {stages
        .map((stage) => stageStatuses[stage.status] || '状态未识别')
        .filter((v, i, a) => a.indexOf(v) === i)
        .join('、')}
    </span>
  );
}

/** 正式执行记录只读展开；候选、建议和拟变化都不能作为提交证明。 */
export function ExecutionChanges({
  item,
  data,
}: {
  item: API.EventExecution;
  data: API.EventChangesResponse;
}) {
  const pending =
    item.outcome === 'commit_unknown' || item.outcome === 'running';
  const title = pending
    ? item.outcome === 'commit_unknown'
      ? '提交待核实'
      : '执行结束尚未确认'
    : item.commit_status === 'committed'
      ? '业务已提交'
      : item.commit_status === 'not_committed'
        ? '已确认未提交'
        : '提交记录缺失或不一致';
  return (
    <details className="change-batch">
      <summary>
        <span>
          {formatTime(item.window.start)} — {formatTime(item.window.end)}
        </span>
        <small>
          {title}
          {item.receipt_kind === 'delivery_recovery' ? ' · 仅恢复原结果' : ''}
        </small>
      </summary>
      <p className="change-muted">
        执行 {item.attempt_id}
        {item.run_id ? ` · 任务 ${item.run_id}` : ''}
      </p>
      <p>
        与当前事件的关联：
        {item.related_by
          .map((value) => reasons[value] || '已保存引用')
          .join('、')}
      </p>
      <p className="change-notice">
        同批可能包含其他事项。候选命中不代表更新当前事件，请核对决定目标和提交收据。
      </p>
      {item.retry_of ? (
        <p>明确接续执行 {item.retry_of}；重试关系不代表执行成功。</p>
      ) : null}
      {item.retry_link_unavailable ? (
        <p>前次执行关联记录未取得，不能按相同窗口补造。</p>
      ) : null}
      {item.error_type ? <p>已记录执行异常类型：{item.error_type}</p> : null}
      {pending ? (
        <p className="change-notice">
          {item.outcome === 'commit_unknown'
            ? '当前执行仍待核实。'
            : '尚未记录执行结束。'}
          查看面板不会触发核实或重新分析。
        </p>
      ) : null}
      <ol className="change-stages">
        <li>
          <details>
            <summary>
              本批输入 ·{' '}
              <Stage
                item={item}
                names={['input', 'provider_input', 'model_started']}
              />
            </summary>
            <p>
              本轮新消息与辅助背景分开保存；辅助背景可含本轮仅供参考的通知，整批输入不等于全部归属当前事件。
            </p>
            {item.inputs.length ? (
              item.inputs.map((input, index) => (
                // biome-ignore lint/suspicious/noArrayIndexKey: 保存的输入顺序固定，调用间同版本也需分别展示。
                <details key={index}>
                  <summary>
                    {input.origin === 'manifest'
                      ? '待消费消息清单'
                      : input.origin === 'request'
                        ? `第 ${input.call_no ?? '未记录'} 次请求准备采用的输入`
                        : '实际分析输入'}
                  </summary>
                  {input.origin === 'request' ? (
                    <p>保存请求输入不证明模型已经成功返回。</p>
                  ) : null}
                  <h4>本轮新增／变更 · {input.new_messages.length} 条</h4>
                  <Proofs items={input.new_messages} showRole />
                  <h4>辅助背景 · {input.auxiliary_messages.length} 条</h4>
                  <p>包含近期历史及仅作辅助的通知，不因此成为事件新增事实。</p>
                  <Proofs items={input.auxiliary_messages} showRole />
                </details>
              ))
            ) : (
              <p>输入未记录</p>
            )}
          </details>
        </li>
        <li>
          <details>
            <summary>
              历史候选 · <Stage item={item} names={['history']} />
            </summary>
            {item.candidates.map((candidate) => (
              <div key={candidate.event_id} className="change-decision">
                <p>
                  候选 {candidate.event_id}
                  {candidate.event_id === data.event_id ? '（当前事件）' : ''}
                </p>
                <p>{candidate.summary ?? '当时摘要未记录'}</p>
                <p>当时状态：{candidate.status ?? '未记录'}</p>
                <p>
                  命中记录：
                  {candidate.hit_reasons.length
                    ? candidate.hit_reasons.join('、')
                    : '未记录'}
                </p>
                <p>
                  纳入模型请求：
                  {candidate.selected_for_request === null
                    ? '未记录'
                    : candidate.selected_for_request
                      ? '是'
                      : '否'}
                </p>
              </div>
            ))}
            {!item.candidates.length ? (
              <p>
                {item.stages.some(
                  (s) => s.stage === 'history' && s.status === 'completed',
                )
                  ? '实际检索未返回候选，不据此判断为新事件。'
                  : '候选内容未记录或该步骤已跳过。'}
              </p>
            ) : null}
          </details>
        </li>
        <li>
          <details>
            <summary>
              必要旧聊天 · <Stage item={item} names={['history_context']} />
            </summary>
            <p>
              直接证据与附近聊天分别标注；附近聊天不自动归属事件，旧聊天不作为新增消息消费。
            </p>
            {item.contexts.map((message, index) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: 保存的同版本补取可有多种来源链接，按原顺序展示。
              <div key={index} className="change-decision">
                <p>
                  {availability[message.availability || ''] || '可用性未记录'}
                  {message.truncated ? ' · 已截断' : ''}
                </p>
                <p>
                  {message.links
                    .map(
                      (link) =>
                        `${link.kind === 'event_evidence' ? '事件直接证据' : link.kind === 'neighbor' ? '同群附近聊天' : '关联类型未记录'}：${link.event_id}`,
                    )
                    .join('；')}
                </p>
                <p>
                  纳入请求：
                  {message.selected_for_request === null
                    ? '未记录'
                    : message.selected_for_request
                      ? '是'
                      : '否'}
                </p>
                {message.fragments.length ? (
                  message.fragments.map((fragment) => (
                    <div key={`${fragment.start}:${fragment.end}`}>
                      <small>
                        原文片段位置 {fragment.start}—{fragment.end}
                        ，不含省略部分
                      </small>
                      <Proofs
                        items={[{ ...message, quote: fragment.text }]}
                        showRole
                      />
                    </div>
                  ))
                ) : (
                  <Proofs items={[message]} showRole />
                )}
              </div>
            ))}
            {!item.contexts.length ? (
              <p>旧聊天片段未记录或本批未取得片段。</p>
            ) : null}
            {item.context_reasons.map((reason) => (
              <p key={reason}>{gaps[reason] || `已记录限制：${reason}`}</p>
            ))}
            {item.context_omitted !== null ? (
              <p>补取记录省略 {item.context_omitted} 项。</p>
            ) : null}
          </details>
        </li>
        <li>
          <details>
            <summary>
              模型建议 ·{' '}
              <Stage
                item={item}
                names={['suggestions', 'model_completed', 'model_failed']}
              />
            </summary>
            <p>这里只展示保存的结构化建议，不是程序决定或模型内部思维。</p>
            {item.suggestions.length ? (
              item.suggestions.map((suggestion, index) => (
                <div
                  key={suggestion.proposal_id || index}
                  className="change-decision"
                >
                  <p>模型建议：{action(suggestion.action)}</p>
                  <p>
                    建议目标：{suggestion.event_id || '未指定'}
                    {suggestion.event_id === data.event_id
                      ? '（当前事件）'
                      : ''}
                  </p>
                  <p>建议摘要：{suggestion.summary ?? '未记录'}</p>
                  <p>建议状态：{suggestion.status ?? '未记录'}</p>
                  {suggestion.possible_event_ids.length ? (
                    <p>建议备选：{suggestion.possible_event_ids.join('、')}</p>
                  ) : null}
                  <p>建议理由：{suggestion.reason || '未记录'}</p>
                  {suggestion.facts.map((fact, i) => (
                    // biome-ignore lint/suspicious/noArrayIndexKey: 保存顺序不变，重复的建议事实也分别保留。
                    <p key={`${i}:${fact}`}>建议变化：{fact}</p>
                  ))}
                  <Proofs items={suggestion.basis} showRole />
                </div>
              ))
            ) : (
              <p>
                {item.stages.some(
                  (s) =>
                    ['suggestions', 'model_completed'].includes(s.stage) &&
                    s.status === 'completed',
                )
                  ? '已记录结构化结果，本批没有建议条目。'
                  : '结构化模型建议未记录，不能从最终事件反推。'}
              </p>
            )}
          </details>
        </li>
        <li>
          <details>
            <summary>
              程序决定 ·{' '}
              <Stage item={item} names={['decision', 'program_result']} />
            </summary>
            {item.decisions.length ? (
              item.decisions.map((decision, index) => (
                <div
                  key={decision.proposal_id || index}
                  className="change-decision"
                >
                  <p>程序决定：{action(decision.action)}</p>
                  <p>
                    实际目标：{decision.event_id || '未指定'}
                    {decision.event_id === data.event_id ? '（当前事件）' : ''}
                  </p>
                  {decision.possible_event_ids.length ? (
                    <p>待确认备选：{decision.possible_event_ids.join('、')}</p>
                  ) : null}
                  <p>程序记录理由：{decision.reason || '未记录'}</p>
                  {decision.contributed_to_revision === false ? (
                    <p>这条建议未贡献拟写入修订。</p>
                  ) : null}
                  <details>
                    <summary>程序拟变化 · 不代表已提交</summary>
                    {decision.change_scope === 'combined_event_group' ? (
                      <p>
                        这是同一事件合并后的拟变化，不能全部归因于这一条建议。
                      </p>
                    ) : null}
                    <dl className="change-diff">
                      <dt>原摘要</dt>
                      <dd>{decision.before?.summary ?? '未记录'}</dd>
                      <dt>拟写摘要</dt>
                      <dd>{decision.after?.summary ?? '未记录'}</dd>
                      <dt>拟变状态</dt>
                      <dd>
                        {decision.before?.status ?? '未记录'} →{' '}
                        {decision.after?.status ?? '未记录'}
                      </dd>
                    </dl>
                    <Proofs items={decision.added_evidence} />
                  </details>
                </div>
              ))
            ) : (
              <p>
                {item.stages.some(
                  (s) =>
                    s.stage === 'program_result' && s.status === 'completed',
                )
                  ? '程序结果已记录，本批没有逐项归属决定。'
                  : '程序决定未记录。'}
              </p>
            )}
          </details>
        </li>
        <li>
          <details>
            <summary>真正提交的结果与摘要差异</summary>
            {item.commit_status === 'committed' ? (
              <>
                <p>
                  事务收据证明业务已提交。
                  {pending ? '执行结束状态尚未确认，不能标为整批成功。' : ''}
                </p>
                <p>本次实际消费 {item.processed ?? '未记录'} 条消息版本。</p>
                {item.receipt_kind === 'delivery_recovery' ? (
                  <p>本次仅恢复原结果，没有再次写入当前事件。</p>
                ) : (
                  <p>
                    {item.created
                      ? '本次提交新建了当前事件。'
                      : item.updated
                        ? '本次提交更新了当前事件。'
                        : '收据没有记录本次写入当前事件。'}
                  </p>
                )}
                {item.revision_indexes.map((index) =>
                  data.revisions[index] ? (
                    <div key={index}>
                      <h4>
                        已提交版本{' '}
                        {data.revisions[index].revision_no ?? '未记录'}
                      </h4>
                      <VersionDifference
                        revision={data.revisions[index]}
                        previous={data.revisions[index - 1]?.snapshot}
                      />
                    </div>
                  ) : null,
                )}
                {item.revision_link_unavailable ? (
                  <p>
                    收据引用的原版本缺失或核验不一致；摘要前后变化未取得，不用当前摘要替补。
                  </p>
                ) : null}
              </>
            ) : (
              <p>
                {item.commit_status === 'not_committed'
                  ? '该执行已确认未提交；前面的拟变化没有作为本次成果提交。'
                  : item.commit_status === 'unconfirmed'
                    ? '提交结果尚未确认，不能把程序决定显示成已提交。'
                    : '提交收据未记录或内容不一致，无法确认提交结果。'}
              </p>
            )}
          </details>
        </li>
        <li>
          <details>
            <summary>提交后的展示记录</summary>
            <p>展示保存状态与业务提交结果分开。</p>
            {item.delivery.length ? (
              item.delivery.map((value) => (
                <p key={value.destination}>
                  {value.destination === 'files'
                    ? '展示快照与续接位置'
                    : '任务进度'}
                  ：{delivery[value.status] || '状态未识别'}
                  {value.observed_at
                    ? ` · ${formatTime(value.observed_at)}`
                    : ''}
                </p>
              ))
            ) : (
              <p>展示结果未记录，不据此认定失败或成功。</p>
            )}
          </details>
        </li>
      </ol>
      <details>
        <summary>实际阶段记录时间</summary>
        <p>以下为程序观察时间，精确提交时间未记录。</p>
        {item.stages.map((stage, index) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: 阶段记录只追加，使用保存位置区分重复观察点。
          <p key={`${index}:${stage.stage}`}>
            {stageNames[stage.stage] || '阶段名称未识别'} ·{' '}
            {stageStatuses[stage.status] || '状态未识别'} ·{' '}
            {stage.recorded_at ? formatTime(stage.recorded_at) : '时间未记录'}
            {stage.error_type ? ` · 已记录异常类型 ${stage.error_type}` : ''}
          </p>
        ))}
      </details>
    </details>
  );
}
