import { CircleAlert, Clock3 } from 'lucide-react';
import { Link } from 'umi';
import { useResource } from '@/lib/useResource';
import { api } from '@/services/api';
import { currentRun, progressUrl, runStatuses } from './progress';

/** 只读任务摘要；读取失败时不把上次的运行状态继续冒充当前状态。 */
export function RunProgressLink({
  uid,
  stream,
}: {
  uid: string;
  stream: string;
}) {
  const records = useResource(
    uid && stream ? `progress:${uid}:${stream}` : null,
    (signal) => api.scopedRuns(uid, stream, signal),
    4000,
  );
  const run = currentRun(records.data?.items || []);
  const state = records.error ? 'unavailable' : run?.status || 'empty';
  const Icon = records.error
    ? CircleAlert
    : run
      ? runStatuses[run.status].icon
      : Clock3;
  return (
    <Link
      className={`run-progress-link ${state}`}
      to={progressUrl(uid, stream)}
      aria-label="查看运行进度"
    >
      <Icon size={15} className={state === 'running' ? 'spinning' : ''} />
      <span>
        {records.error
          ? '进度读取失败'
          : run
            ? runStatuses[run.status].label
            : '运行进度'}
      </span>
      {run && !records.error && (
        <small>
          {run.completed_windows} / {run.total_windows}
        </small>
      )}
    </Link>
  );
}
