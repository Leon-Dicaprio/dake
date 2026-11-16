import { ArrowRight, Inbox, RefreshCw, TriangleAlert } from 'lucide-react';
import type { ReactNode } from 'react';
import { Button } from './ui/button';

/** 请求失败保留明确重试入口，不用空列表掩盖连接问题。 */
export function ErrorNotice({
  message,
  retry,
}: {
  message: string;
  retry?: () => void;
}) {
  return (
    <div className="error-notice" role="alert">
      <TriangleAlert size={16} />
      <span>{message}</span>
      {retry && (
        <Button size="small" variant="ghost" onClick={retry}>
          <RefreshCw size={14} />
          重试
        </Button>
      )}
    </div>
  );
}

/** 空状态只说明当前事实，操作由页面提供。 */
export function EmptyState({
  title,
  description,
  action,
  icon,
}: {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">
        {icon || <Inbox size={26} strokeWidth={1.4} />}
      </div>
      <h2>{title}</h2>
      {description ? <p>{description}</p> : null}
      {action && (
        <div className="empty-action">
          {action}
          <ArrowRight size={14} />
        </div>
      )}
    </div>
  );
}

/** 首屏骨架与实际表格保持相同密度，避免加载时大幅跳动。 */
export function LoadingRows({ count = 5 }: { count?: number }) {
  return (
    <div className="loading-rows" role="status" aria-label="正在读取">
      <span className="sr-only">正在读取</span>
      {['first', 'second', 'third', 'fourth', 'fifth']
        .slice(0, count)
        .map((row) => (
          <div className="loading-row" key={row}>
            <i />
            <i />
            <i />
          </div>
        ))}
    </div>
  );
}
