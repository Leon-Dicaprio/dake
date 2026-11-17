import { type FormEvent, useState } from 'react';
import { Link } from 'umi';
import { EmptyState, ErrorNotice, LoadingRows } from '@/components/Feedback';
import { Button } from '@/components/ui/button';
import { useWorkspace } from '@/layouts/Workspace';
import { useResource } from '@/lib/useResource';
import { errorMessage, formatTime } from '@/lib/utils';
import { api } from '@/services/api';

const phases: Record<API.ScheduleResponse['phase'], string> = {
  disabled: '名单已停用',
  paused: '已暂停',
  needs_verification: '提交待核实',
  queued: '已排入处理队列',
  retry_wait: '等待重试',
  catching_up: '等待补跑',
  waiting: '已追上，等待新窗口',
};

/** 页面只选择最初日期与控制暂停，不自行推进窗口或推断任务结果。 */
export default function SchedulesPage() {
  const workspace = useWorkspace();
  const resource = useResource('processing-schedules', api.schedules, 5000);
  const [start, setStart] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const value = resource.data;
  const date = start || workspace.data?.start.slice(0, 10) || '';
  async function perform(action: () => Promise<unknown>) {
    setBusy(true);
    setError('');
    try {
      await action();
      resource.refresh();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void perform(() => api.startSchedules(date));
  }
  return (
    <main className="page schedules-page">
      <header className="page-header">
        <div>
          <div className="page-eyebrow">持续处理</div>
          <h1>定时增量</h1>
          <p>从选定日期补跑到最新，之后自动处理新的完整 15 分钟窗口。</p>
        </div>
        <Button onClick={resource.refresh} disabled={busy}>
          刷新状态
        </Button>
      </header>
      {resource.error && (
        <ErrorNotice message={resource.error} retry={resource.refresh} />
      )}
      {error && <ErrorNotice message={error} />}
      {resource.loading && !value ? <LoadingRows /> : null}
      <form className="schedule-start" onSubmit={submit}>
        <label className="form-field">
          <span>最初开始日期（上海时间）</span>
          <input
            type="date"
            value={value?.start_date || date}
            onChange={(event) => setStart(event.target.value)}
            required
            disabled={value?.configured || busy}
          />
        </label>
        <Button
          type="submit"
          variant="primary"
          disabled={busy || !value || value.configured}
        >
          {value?.configured ? '已保存开始日期' : '开始持续处理'}
        </Button>
      </form>
      <p className="schedule-help">
        客户来自已接入的客户名单。不同客户轮流处理，空窗口正常推进；临时错误最多重试
        3 次，默认间隔 1、5、15 分钟，超限后暂停该客户。
      </p>
      {value && !value.worker_enabled && (
        <div className="notice">
          当前网页服务未启用自动触发。使用独立执行器时，请根据最近检查时间确认其运行状态。
        </div>
      )}
      {value?.source_error && (
        <div className="notice" role="alert">
          {value.source_error}
        </div>
      )}
      <p className="schedule-help">
        最近检查：{value?.last_tick ? formatTime(value.last_tick) : '尚未检查'}
        。暂停不撤销已排队或执行中的窗口；恢复会重新给予有限重试次数。
      </p>
      {value?.items.length ? (
        <div className="schedule-table-scroll">
          <table className="schedule-table">
            <thead>
              <tr>
                <th>客户</th>
                <th>当前状态</th>
                <th>下个待处理窗口起点</th>
                <th>积压窗口</th>
                <th>重试与原因</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {value.items.map((item) => (
                <tr key={item.schedule_id}>
                  <td>{item.uid}</td>
                  <td>{phases[item.phase]}</td>
                  <td>{formatTime(item.next_start)}</td>
                  <td>{item.pending_windows}</td>
                  <td>
                    {item.retry_count ? (
                      <p>已安排重试 {item.retry_count}/3 次</p>
                    ) : null}
                    {item.retry_at ? (
                      <p>下次：{formatTime(item.retry_at)}</p>
                    ) : null}
                    {item.error ? <p>{item.error}</p> : '—'}
                  </td>
                  <td>
                    <div className="schedule-actions">
                      <Button
                        disabled={busy || !item.enabled}
                        onClick={() =>
                          void perform(() =>
                            item.status === 'active'
                              ? api.pauseSchedule(item.schedule_id)
                              : api.resumeSchedule(item.schedule_id),
                          )
                        }
                      >
                        {item.status === 'active'
                          ? '暂停'
                          : item.status === 'needs_verification'
                            ? '核实并恢复'
                            : '恢复'}
                      </Button>
                      {item.active_run_id || item.last_run_id ? (
                        <Link
                          to={`/runs?${new URLSearchParams({
                            uid: item.uid,
                            stream: item.stream,
                            run: item.active_run_id || item.last_run_id || '',
                          })}`}
                        >
                          处理记录
                        </Link>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : value ? (
        <EmptyState
          title="暂无客户调度记录"
          description="接入已确认的客户名单并选择开始日期后，这里会显示各客户的真实处理进度。"
        />
      ) : null}
    </main>
  );
}
